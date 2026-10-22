import json
from typing import Optional, Dict, Any
from app.config import settings, is_phone_authorized
from app.services import db_service, llm_service
from app.services.time_utils import get_libya_datetime_context


def is_staff_authorized(sender_phone: str) -> bool:
    """Checks whether the sender phone is in the authorized staff whitelist."""
    configs = db_service.get_clinic_configs()
    auth_str = configs.get("authorized_phones", settings.AUTHORIZED_STAFF_PHONES)
    return is_phone_authorized(sender_phone, auth_str)


def is_update_message(text: str) -> bool:
    """Detects whether text has update/admin intent."""
    triggers = [
        "@bot", "@Bot", "@بـوت", "@بوت", "اعتذر", "اعتذرت", "مش حيكون متواجد", "مش حتكون متواجدة",
        "مش جاي", "مش جاية", "غياب", "تأخير", "متأخر", "متأخرة", "حيبدأ", "حتبدأ", "كشفية", "سعر", "صار", "صارت",
        "متواجد", "حاضر", "تعديل", "تغيير", "إلغاء", "دينار", "موعد", "حضور",
        "غادر", "غادرت", "روح", "روحت", "روّح", "روّحت", "طلع", "طلعت", "كمل", "كملت", "أنهى", "أنهت", "خلص", "خلصت", "مشى",
        "وصل", "وصلت", "باشر", "قاعد توا", "قاعدة توا", "بدأ", "بدت", "استقبال", "بالعيادة",
        "اكتفى", "اكتفت", "اكتفوا", "اكتمل", "اكتملت", "قفل", "قفلوا", "وقف", "وقفوا", "توقف", "سد", "فل", "حجز",
        "تمديد", "مدد", "مددت", "مكمل", "مكملة", "دوام", "عيادة", "دكتور", "دكتورة", "تحليل", "فحص"
    ]
    return any(t in text for t in triggers)


def process_authorized_staff_message(sender_phone: str, message_text: str) -> Optional[str]:
    """
    Processes incoming message from authorized staff (private 1:1 or group @bot).
    Returns confirmation message if processed as an admin update, or None if ignored/unauthorized.
    """
    if not is_staff_authorized(sender_phone):
        return None

    # Parse update with Gemini / NLP
    parsed = llm_service.parse_admin_update(message_text)
    action = parsed.get("action", "UNKNOWN")

    # If message is casual chatter (greeting, question about work, etc.), ignore cleanly
    if action == "CASUAL_CHATTER":
        return None

    # If action is unknown or general note and text doesn't contain update intent, ignore
    if action in ["UNKNOWN"] and not is_update_message(message_text):
        return None

    time_ctx = get_libya_datetime_context()
    confirmation_msg = parsed.get("confirmation_text", "تم استلام التحديث وحفظه بنجاح.")

    # Execute DB mutations: locate doctor by name, specialty, or raw message
    doctor = None
    if parsed.get("doctor_name") or parsed.get("specialty"):
        doctor = db_service.find_doctor_fuzzy(
            name_query=parsed.get("doctor_name"),
            specialty_query=parsed.get("specialty")
        )
    if not doctor:
        doctor = db_service.find_doctor_fuzzy(name_query=message_text, specialty_query=message_text)

    # 1. Doctor Left / Finished for today
    if action == "DOCTOR_LEFT" and doctor:
        time_str = parsed.get("new_time") or time_ctx["time_arabic"]
        note = parsed.get("note") or f"غادر العيادة لليوم ({time_str})"
        db_service.update_doctor_today_status(doctor.id, status="left", note=note)
        confirmation_msg = (
            f"✅ تم التحديث الفوري: {doctor.name} ({doctor.specialty}) مسجل كـ [غادر العيادة].\n"
            f"🚪 سيتم إفادة أي مريض يستفسر عنه بأنه أنهى كشوفات اليوم وغادر المصحة."
        )

    # 2. Doctor Arrived / Started receiving
    elif action == "DOCTOR_ARRIVED" and doctor:
        time_str = parsed.get("new_time") or time_ctx["time_arabic"]
        note = parsed.get("note") or f"وصل للعيادة ويباشر استقبال الحالات ({time_str})"
        db_service.update_doctor_today_status(doctor.id, status="arrived", note=note)
        confirmation_msg = (
            f"✅ تم التحديث الفوري: {doctor.name} ({doctor.specialty}) مسجل كـ [وصل للعيادة ويباشر الكشوفات الآن].\n"
            f"🩺 سيتم إفادة المرضى بأنه متواجد بالداخل حالياً."
        )

    # 3. Booking Closed / Capacity Reached
    elif action == "BOOKING_CLOSED" and doctor:
        note = parsed.get("note") or "اكتمل العدد وتم إيقاف الحجز لليوم"
        db_service.update_doctor_today_status(doctor.id, status="booking_closed", note=note)
        confirmation_msg = (
            f"✅ تم التحديث الفوري: {doctor.name} ({doctor.specialty}) مسجل كـ [مكتمل العدد - الحجز مقفل لليوم].\n"
            f"⛔ سيتم تنبيه المرضى باكتمال الأرقام وتوقف الحجز لليوم."
        )

    # 4. Doctor Hours Extended
    elif action == "DOCTOR_EXTENDED" and doctor:
        note = parsed.get("note") or f"تمديد دوام اليوم حتى {parsed.get('new_time', '')}"
        db_service.update_doctor_today_status(doctor.id, status="delayed", note=note)
        confirmation_msg = f"✅ تم التحديث الفوري: {doctor.name} ({doctor.specialty}) تم تمديد دوامه لليوم [{note}]."

    # 5. Doctor Apology (Absent)
    elif action == "DOCTOR_APOLOGY" and doctor:
        note = parsed.get("note") or "اعتذار عن موعد اليوم"
        db_service.update_doctor_today_status(doctor.id, status="apologized", note=note)
        confirmation_msg = f"✅ تم التحديث الفوري: {doctor.name} ({doctor.specialty}) مسجل كـ [معتذر اليوم] ولن يظهر كمتواجد للمرضى."

    # 6. Doctor Delay
    elif action == "DOCTOR_DELAY" and doctor:
        note = parsed.get("note") or f"تأخير موعد البدء إلى {parsed.get('new_time', '')}"
        db_service.update_doctor_today_status(doctor.id, status="delayed", note=note)
        confirmation_msg = f"✅ تم التحديث الفوري: {doctor.name} ({doctor.specialty}) تم تعديل موعده اليوم [{note}]."

    # 7. Doctor Available (Confirmed attendance)
    elif action == "DOCTOR_AVAILABLE" and doctor:
        db_service.update_doctor_today_status(doctor.id, status="available", note="")
        confirmation_msg = f"✅ تم التحديث الفوري: {doctor.name} ({doctor.specialty}) مسجل كـ [متواجد اليوم] حسب موعده المعتاد."

    # 8. Update Doctor Fee
    elif action == "UPDATE_DOCTOR_FEE" and doctor and parsed.get("new_price"):
        new_price = float(parsed["new_price"])
        db_service.update_doctor_fee(doctor.id, new_price)
        confirmation_msg = f"✅ تم التحديث الفوري: تم تعديل كشفية {doctor.name} إلى {new_price} د.ل."

    # 9. Update Service Price
    elif action == "UPDATE_SERVICE_PRICE" and parsed.get("service_name") and parsed.get("new_price"):
        service = db_service.find_service_fuzzy(parsed["service_name"])
        if service:
            new_price = float(parsed["new_price"])
            db_service.update_service_price(service.id, new_price)
            confirmation_msg = f"✅ تم التحديث الفوري: تم تعديل سعر ({service.name}) إلى {new_price} د.ل."

    # 10. General Note
    elif action == "GENERAL_NOTE":
        confirmation_msg = parsed.get("confirmation_text") or f"تم استلام وتوثيق الملاحظة: {message_text}"

    # Audit log entry for transparency
    db_service.log_audit(
        sender=f"الموظف المصرح له ({sender_phone})",
        raw_message=message_text,
        action_type=action,
        extracted_data=json.dumps(parsed, ensure_ascii=False),
        confirmation_sent=confirmation_msg,
    )

    return confirmation_msg


def process_admin_group_message(sender_id: str, message_text: str) -> Optional[str]:
    """Compatibility wrapper."""
    return process_authorized_staff_message(sender_id, message_text)
