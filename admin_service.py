"""
LibyAI Admin NLP & Verification Service (`admin_service.py`)

Handles dynamic real-time schedule and pricing updates from the verified WhatsApp
Staff / Admin Group when tagged with `@Bot`.

Features:
- Gemini Structured Output with Pydantic schema.
- Ambiguity detection (refuses ambiguous commands like "@Bot الدكتور مش جاي").
- Atomic database mutation.
- Explicit verification receipt with before/after status, fee, and daily note.
- Audit trail logging.
"""

import os
import json
import re
import logging
from typing import Dict, Any, Optional, Tuple
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

import db
from app.services.time_utils import get_libya_datetime_context

# Primary model as specified, with reliable fallbacks
preferred_model = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
MODELS_CASCADE = [preferred_model, "gemini-3.5-flash", "gemini-3.6-flash", "gemini-3.1-flash-lite", "gemini-3-flash-preview"]
_seen = set()
MODELS_CASCADE = [m for m in MODELS_CASCADE if not (m in _seen or _seen.add(m))]



# Initialize Gemini client if API key is present
gemini_client = None
GEMINI_KEY = os.environ.get("GEMINI_KEY") or os.environ.get("GEMINI_API_KEY")
if GEMINI_KEY:
    try:
        from google import genai
        from google.genai import types
        gemini_client = genai.Client(
            api_key=GEMINI_KEY,
            http_options=types.HttpOptions(
                timeout=15000,
                retry_options=types.HttpRetryOptions(attempts=1)
            )
        )
    except Exception as e:
        print(f"Warning: Could not initialize Gemini in admin_service: {e}")


class AdminUpdateIntent(BaseModel):
    is_valid_update: bool = Field(description="True if this is an actionable directive to modify doctor schedule, status, or pricing")
    is_ambiguous: bool = Field(description="True if the request lacks a clear doctor name, specialty, or item")
    ambiguity_reason: Optional[str] = Field(default=None, description="Explanation why the request is ambiguous if applicable")
    action: str = Field(description="DOCTOR_STATUS_UPDATE, UPDATE_FEE, UPDATE_SERVICE_PRICE, CHATTER, UNKNOWN")
    doctor_identifier: Optional[str] = Field(default=None, description="Doctor name or specialty (e.g. عظام, علي, فاطمة)")
    new_status: Optional[str] = Field(default=None, description="available, apologized, delayed, left, arrived, booking_closed")
    daily_note: Optional[str] = Field(default="", description="Specific note (e.g. 'تأخير للساعة 5', 'اعتذر لظرف طارئ')")
    new_price: Optional[float] = Field(default=None, description="Updated price or fee in Libyan Dinars if applicable")
    service_identifier: Optional[str] = Field(default=None, description="Name of service or lab test if updating service price")


STATUS_ARABIC_MAP = {
    "available": "متواجد حسب الجدول المعتاد ✅",
    "apologized": "معتذر اليوم ❌",
    "delayed": "تأخير / تعديل موعد ⏰",
    "left": "غادر العيادة لليوم 🚪",
    "arrived": "وصل للعيادة ويستقبل الآن 🩺",
    "booking_closed": "مكتمل العدد / الحجز مقفل ⛔",
}


def fallback_admin_parser(clean_text: str) -> AdminUpdateIntent:
    """Deterministic fallback NLP parser for common staff updates in Libyan dialect."""
    t = clean_text.strip()
    
    # 1. Ambiguity detection: check if update is mentioned with NO doctor name or specialty
    update_words = ["اعتذر", "مش جاي", "تأخير", "حيبدأ", "روح", "غادر", "وصل", "كشفية", "سعر", "اكتفوا", "قفلوا"]
    has_update_word = any(w in t for w in update_words)
    
    matched_doc = db.find_doctor_fuzzy(name_query=t, specialty_query=t)
    matched_svc = db.find_service_fuzzy(t)

    if has_update_word and not matched_doc and not matched_svc:
        # Check if generic words like "الدكتور" or "الدكتورة" are present without name/specialty
        if any(w in t for w in ["الدكتور", "الدكتورة", "الطبيب", "العيادة"]):
            return AdminUpdateIntent(
                is_valid_update=False,
                is_ambiguous=True,
                ambiguity_reason="لم يتم تحديد اسم الطبيب أو التخصص بوضوح",
                action="UNKNOWN",
                doctor_identifier=None
            )

    # 2. Doctor status updates
    if matched_doc:
        doc_name = matched_doc["name"]
        
        # Apology / Absent
        if any(w in t for w in ["اعتذر", "اعتذرت", "مش جاي", "مش جاية", "مش حيكون متواجد", "غياب",
                                 "ماجاش", "ما جاش", "مش حيجي", "ما حيجيش", "غائب", "مش متواجد",
                                 "ما حيكونش", "عنده ظرف", "تعذر حضوره", "ما يقدرش يجي",
                                 "مش جايه", "ما جاتش", "مش حتجي"]):
            return AdminUpdateIntent(
                is_valid_update=True,
                is_ambiguous=False,
                action="DOCTOR_STATUS_UPDATE",
                doctor_identifier=doc_name,
                new_status="apologized",
                daily_note="اعتذار عن موعد اليوم"
            )
        
        # Departure
        if any(w in t for w in ["روح", "غادر", "طلع", "كمل", "خلص", "مشى", "فك",
                                 "ماعادش قاعد", "ما عادش قاعد", "مش قاعد", "روح للدار",
                                 "فك الدار", "انتهى", "كمل كشوفاته", "أنهى كشوفاته",
                                 "خلص كشوفاته", "ما عادش يستقبل", "مش موجود خلاص"]):
            time_now = get_libya_datetime_context()["time_arabic"]
            return AdminUpdateIntent(
                is_valid_update=True,
                is_ambiguous=False,
                action="DOCTOR_STATUS_UPDATE",
                doctor_identifier=doc_name,
                new_status="left",
                daily_note=f"أنهى كشوفات اليوم وغادر العيادة ({time_now})"
            )

        # Arrival
        if any(w in t for w in ["وصل", "باشر", "قاعد توا", "بدأ يستقبل", "جا", "جاي",
                                 "قاعد في العيادة", "متواجد توا", "حاضر", "قاعد يكشف",
                                 "في العيادة توا", "جا وقاعد", "فتح العيادة",
                                 "بدأ الكشوفات"]):
            time_now = get_libya_datetime_context()["time_arabic"]
            return AdminUpdateIntent(
                is_valid_update=True,
                is_ambiguous=False,
                action="DOCTOR_STATUS_UPDATE",
                doctor_identifier=doc_name,
                new_status="arrived",
                daily_note=f"وصل للعيادة ويستقبل الحالات الآن ({time_now})"
            )

        # Booking closed
        if any(w in t for w in ["اكتفوا", "اكتفى", "قفلوا الحجز", "وقفوا الحجز", "سد",
                                 "العدد اكتمل", "الحجز مقفل", "سد الحجز", "كمل العدد",
                                 "مافيش حجز", "الحجز اكتمل"]):
            return AdminUpdateIntent(
                is_valid_update=True,
                is_ambiguous=False,
                action="DOCTOR_STATUS_UPDATE",
                doctor_identifier=doc_name,
                new_status="booking_closed",
                daily_note="اكتمل العدد وتم إيقاف الحجز لليوم"
            )

        # Delay
        if any(w in t for w in ["تأخير", "حيبدأ", "حتبدأ", "متأخر", "تأجل", "بدل الساعة",
                                 "حيجي متأخر", "عنده تأخير"]):
            time_match = re.search(r"(\d{1,2}(?::\d{2})?)", t)
            time_str = f"الساعة {time_match.group(1)}" if time_match else "تعديل موعد"
            return AdminUpdateIntent(
                is_valid_update=True,
                is_ambiguous=False,
                action="DOCTOR_STATUS_UPDATE",
                doctor_identifier=doc_name,
                new_status="delayed",
                daily_note=f"تأخير موعد البدء إلى {time_str}"
            )

        # Available / back to normal
        if any(w in t for w in ["متاح", "رجع متاح", "حيكون متواجد", "موجود", "كالعادة",
                                 "الجدول المعتاد", "عادي"]):
            return AdminUpdateIntent(
                is_valid_update=True,
                is_ambiguous=False,
                action="DOCTOR_STATUS_UPDATE",
                doctor_identifier=doc_name,
                new_status="available",
                daily_note="الطبيب متاح ويستقبل حسب الجدول المعتاد"
            )

        # Fee update
        if any(w in t for w in ["كشفية", "سعر", "صارت", "دينار"]):
            num_match = re.search(r"(\d+(?:\.\d+)?)", t)
            if num_match:
                return AdminUpdateIntent(
                    is_valid_update=True,
                    is_ambiguous=False,
                    action="UPDATE_FEE",
                    doctor_identifier=doc_name,
                    new_price=float(num_match.group(1))
                )

    # 3. Service update
    if matched_svc and any(w in t for w in ["سعر", "صارت", "دينار"]):
        num_match = re.search(r"(\d+(?:\.\d+)?)", t)
        if num_match:
            return AdminUpdateIntent(
                is_valid_update=True,
                is_ambiguous=False,
                action="UPDATE_SERVICE_PRICE",
                service_identifier=matched_svc["name"],
                new_price=float(num_match.group(1))
            )

    return AdminUpdateIntent(
        is_valid_update=False,
        is_ambiguous=False,
        action="CHATTER" if any(w in t for w in ["جو", "خير", "سلام", "شكرا"]) else "UNKNOWN"
    )


def parse_staff_message_with_ai(clean_text: str) -> AdminUpdateIntent:
    """Uses Gemini Structured Outputs to classify and extract admin intent with deep Libyan dialect understanding."""
    global gemini_client
    if not gemini_client:
        return fallback_admin_parser(clean_text)

    doctors = db.get_all_doctors()
    doctors_list_str = "\n".join([f"- {d['name']} ({d['specialty']}) | حالته الحالية: {d['status']} | الكشفية: {d['consultation_fee']} | ID: {d['id']}" for d in doctors])
    time_ctx = get_libya_datetime_context()

    prompt = f"""أنت مساعد ذكي يفهم اللهجة الليبية بطلاقة تامة. مهمتك فهم رسائل موظفي الاستقبال في مصحة ليبية واستخراج القصد الحقيقي من كلامهم حتى لو كان عامياً أو مختصراً.

📩 رسالة الموظف:
"{clean_text}"

🕐 السياق الزمني: {time_ctx['summary']}

👨‍⚕️ أطباء المصحة المسجلين حالياً:
{doctors_list_str}

━━━━━━━━━━━━━━━━━━━━━━
📖 دليل فهم اللهجة الليبية والتعبيرات الشائعة:
━━━━━━━━━━━━━━━━━━━━━━

🚪 عبارات تعني "غادر العيادة" (new_status = "left"):
روح، مشى، طلع، غادر، خلاص مشى، كمل وروح، انتهى وروح، ماعادش قاعد، روح للدار، فك، ما عادش يستقبل، خلص كشوفاته، أنهى كشوفاته، كمل كشوفاته وروح، مشى من العيادة، مش قاعد، روح من زمان، فك الدار

❌ عبارات تعني "معتذر" (new_status = "apologized"):
اعتذر، معتذر، مش جاي، ماجاش، ما جاش اليوم، مش حيجي، ما حيجيش، غائب، مش متواجد، ما حيكونش متواجد، مش جاي اليوم، عنده ظرف، عذر، تعذر حضوره، ما يقدرش يجي

🩺 عبارات تعني "وصل ويستقبل" (new_status = "arrived"):
وصل، جا، قاعد، متواجد توا، باشر، بدأ يستقبل، بدأ الكشوفات، قاعد في العيادة، جاي، حاضر، قاعد يكشف، في العيادة توا، جا وقاعد، فتح العيادة

✅ عبارات تعني "متاح / رجع متاح" (new_status = "available"):
متاح، متاح اليوم، رجع متاح، حيكون متواجد، حيجي، موجود، عادي، الجدول المعتاد، كالعادة

⏰ عبارات تعني "تأخير" (new_status = "delayed"):
تأخير، متأخر، حيبدأ الساعة...، حتبدأ...، بدل الساعة...، تأجل لـ...، حيجي متأخر، عنده تأخير

⛔ عبارات تعني "اكتمل العدد / إيقاف الحجز" (new_status = "booking_closed"):
اكتفوا، قفلوا الحجز، وقفوا الحجز، العدد اكتمل، الحجز مقفل، سد الحجز، كمل العدد، مافيش حجز

💰 عبارات تعني "تغيير السعر":
كشفيته صارت...، عدلوا الكشفية لـ...، السعر صار...، غيروا الكشفية، الكشفية الجديدة...

━━━━━━━━━━━━━━━━━━━━━━
⚠️ قواعد حاسمة:
━━━━━━━━━━━━━━━━━━━━━━

1. طابق اسم الطبيب أو تخصصه من القائمة أعلاه. استخدم المطابقة الذكية:
   - "عظام" تطابق طبيب تخصصه "عظام ومفاصل"
   - "الباطنة" تطابق "باطنة وجهاز هضمي"
   - "يوسف" أو "العربي" تطابق "د. يوسف العربي"
   - حتى لو كتب الاسم بشكل مختلف قليلاً (مثل يوسف / يوسف العربي)

2. إذا الرسالة فيها أمر تعديل لكن ما حدد الطبيب ولا التخصص بأي شكل:
   - is_valid_update = false, is_ambiguous = true

3. إذا مجرد كلام عادي أو سوالف (مثل: "شنو جو الشغل؟"، "صباح الخير"، "تمام"):
   - action = "CHATTER"

4. daily_note: اكتب ملاحظة طبيعية ومفهومة بالعربية توضح ما حصل (مثال: "أنهى كشوفات اليوم وغادر العيادة")

أجب بكائن JSON فقط بهذا الشكل بالضبط:
{{
  "is_valid_update": true/false,
  "is_ambiguous": true/false,
  "ambiguity_reason": "السبب أو null",
  "action": "DOCTOR_STATUS_UPDATE أو UPDATE_FEE أو UPDATE_SERVICE_PRICE أو CHATTER أو UNKNOWN",
  "doctor_identifier": "اسم أو تخصص الطبيب من القائمة أو null",
  "new_status": "available/apologized/delayed/left/arrived/booking_closed أو null",
  "daily_note": "ملاحظة توضيحية أو فارغ",
  "new_price": null أو رقم,
  "service_identifier": "اسم الخدمة أو null"
}}"""

    for model_name in MODELS_CASCADE:
        try:
            response = gemini_client.models.generate_content(
                model=model_name,
                contents=prompt,
                config={
                    "response_mime_type": "application/json",
                    "temperature": 0.2,
                }
            )
            if response and response.text:
                clean_json = response.text.strip()
                if clean_json.startswith("```json"):
                    clean_json = clean_json[7:]
                if clean_json.endswith("```"):
                    clean_json = clean_json[:-3]
                data = json.loads(clean_json.strip())
                return AdminUpdateIntent(**data)
        except Exception as e:
            continue

    return fallback_admin_parser(clean_text)


def handle_admin_group_message(
    sender_phone: str,
    raw_message: str,
    group_id: Optional[str] = None,
    job_id: Optional[int] = None,
    lease_token: Optional[str] = None,
    worker_id: Optional[str] = None,
    db_path: str = db.DB_PATH
) -> Optional[str]:
    """
    Main entrypoint for WhatsApp Staff Group processing.
    Ensures message is tagged with `@Bot`, checks for ambiguity, performs atomic mutations,
    and returns an explicit verification receipt.
    """
    # 0. Idempotency Check: if this exact job was already committed, return stored receipt
    if job_id is not None:
        with db.get_db(db_path) as conn:
            row = conn.cursor().execute(
                "SELECT confirmation_text FROM audit_logs WHERE message_job_id = ?;",
                (job_id,)
            ).fetchone()
            if row:
                logger.info(f"[AdminService] Job {job_id} already committed; returning cached receipt.")
                return row["confirmation_text"]

    # 1. Require @Bot, @تحديث, or @إدارة tag in group
    tag_pattern = r"(?:@تحديث:|@تحديث|@إدارة|@ادارة|@إداره|@Bot|@bot|@بـوت|@بوت|@مساعد)"
    if not re.search(tag_pattern, raw_message, re.IGNORECASE):
        # In a staff group, messages without tags are ignored to prevent chatter spam
        return None

    # Handle Management Commands (@إدارة)
    if re.search(r"@(?:إدارة|ادارة|إداره)", raw_message):
        is_auth, staff_role, staff_name = db.is_staff_authorized(sender_phone, db_path)
        if not is_auth or staff_role not in ("owner", "admin"):
            return "⛔ *غير مصرح:* عذراً، أوامر الإدارة (@إدارة) مخصصة فقط لمدير المستشفى أو المشرف الإداري المعتمد."

        clean_cmd = re.sub(r"@(?:إدارة|ادارة|إداره)", "", raw_message).strip()
        parts = clean_cmd.split()

        if not parts or parts[0] in ("الموظفين", "عرض", "قائمة", "الكل"):
            staff_list = db.list_authorized_staff(db_path)
            facility_name = db.get_facility_profile(db_path).get("name", "المصحة")
            lines = [
                f"👥 *قائمة الموظفين والمسؤولين المصرح لهم بـ {facility_name}:*",
                "━━━━━━━━━━━━━━━━━━━━━━"
            ]
            for s in staff_list:
                lines.append(f"• `{s['phone_number']}` | *{s['name']}* ({s['role']})")
            lines.append("━━━━━━━━━━━━━━━━━━━━━━")
            lines.append("💡 *أوامر الإدارة المتاحة:*\n• `@إدارة إضافة [الرقم] [الاسم] [الدور]`\n• `@إدارة حذف [الرقم]`")
            return "\n".join(lines)

        if parts[0] in ("إضافة", "اضافة"):
            if len(parts) < 2:
                return "⚠️ الصيغة غير مكتملة. الصيغة: `@إدارة إضافة [رقم الهاتف] [الاسم] [الدور: staff/admin]`"
            t_phone = parts[1]
            t_name = parts[2] if len(parts) > 2 else "موظف معتمد"
            t_role = parts[3] if len(parts) > 3 and parts[3] in ("owner", "admin", "staff") else "staff"
            db.add_authorized_staff(t_phone, t_name, t_role, db_path)
            return (
                "✅ *تمت إضافة الموظف بنجاح* ✅\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📱 *الرقم:* `{t_phone}`\n"
                f"👤 *الاسم:* {t_name}\n"
                f"🎖️ *الصلاحية:* {t_role}\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "_أصبح بإمكان هذا الرقم إرسال تحديثات الأطباء عبر أمر (@تحديث)._"
            )

        if parts[0] in ("حذف", "إلغاء", "الغاء"):
            if len(parts) < 2:
                return "⚠️ الصيغة غير مكتملة. الصيغة: `@إدارة حذف [رقم الهاتف]`"
            t_phone = parts[1]
            deleted = db.remove_authorized_staff(t_phone, db_path)
            if deleted:
                return f"✅ *تم إلغاء الصلاحية بنجاح*\n• تم حذف الرقم `{t_phone}` من قائمة المصرح لهم."
            return f"⚠️ الرقم `{t_phone}` غير مسجل مسبقاً في قائمة الموظفين المصرح لهم."

        return "ℹ️ لم يتم التعرف على أمر الإدارة. يمكنك كتابة `@إدارة الموظفين` لعرض القائمة والأوامر المتاحة."

    # Clean the update mention
    clean_message = re.sub(tag_pattern, "", raw_message, flags=re.IGNORECASE).strip()
    if not clean_message:
        return "👋 أهلاً بك زميلي في فريق الاستقبال. لتعديل جدول أو حالة طبيب، اكتب مثلاً:\n`@تحديث دكتور العظام يوسف العربي اعتذر اليوم`"

    # 2. Verify sender authorization
    is_auth, staff_role, staff_name = db.is_staff_authorized(sender_phone, db_path)
    if not is_auth:
        facility_name = db.get_facility_profile(db_path).get("name", "المصحة")
        return f"⛔ *غير مصرح:* هذا الرقم غير مسجل ضمن أرقام موظفي {facility_name} المصرح لهم بالتعديل."

    # 3. Parse intent via Gemini / Fallback
    intent = parse_staff_message_with_ai(clean_message)

    # 3. Handle Ambiguity (Fail-Safe)
    if intent.is_ambiguous:
        reason = intent.ambiguity_reason or "يرجى تحديد اسم الطبيب أو العيادة بوضوح"
        return (
            "⚠️ *تعذر تنفيذ التحديث: طلب غير محدد* ⚠️\n\n"
            f"📌 *السبب:* {reason}.\n"
            "💡 *الصيغة الصحيحة:* \n"
            "• `@Bot دكتور العظام علي اعتذر اليوم`\n"
            "• `@Bot دكتورة الأطفال فاطمة تأخير للساعة 5`\n"
            "• `@Bot كشفية عيادة العيون صارت 50 دينار`"
        )

    # 4. Handle Chatter / Non-updates
    if intent.action == "CHATTER" or not intent.is_valid_update:
        return (
            "ℹ️ تم استلام رسالتك ولكن لم يتم التعرف على أمر تحديث مباشر.\n"
            "لتحديث الجداول، يمكنك ذكر اسم الطبيب أو التخصص متبوعاً بحالته (اعتذار، تأخير، مغادرة، أو تعديل سعر)."
        )

    time_ctx = get_libya_datetime_context()

    # 5. Handle Doctor Status Update
    if intent.action == "DOCTOR_STATUS_UPDATE" and intent.doctor_identifier:
        doctor = db.find_doctor_fuzzy(name_query=intent.doctor_identifier, specialty_query=intent.doctor_identifier)
        if not doctor:
            return f"⚠️ *تعذر التحديث:* لم يتم العثور على طبيب باسم أو تخصص `{intent.doctor_identifier}` في النظام."

        ALLOWED_STATUSES = {
            'available': 'available',
            'apologized': 'apologized',
            'delayed': 'delayed',
            'left': 'left',
            'arrived': 'arrived',
            'booking_closed': 'booking_closed',
            # Arabized & synonym mappings
            'absent': 'apologized',
            'off': 'apologized',
            'غائب': 'apologized',
            'معتذر': 'apologized',
            'اعتذر': 'apologized',
            'اعتذرت': 'apologized',
            'متأخر': 'delayed',
            'تأخير': 'delayed',
            'مغادر': 'left',
            'غادر': 'left',
            'روح': 'left',
            'حاضر': 'available',
            'متواجد': 'available',
            'وصل': 'arrived',
            'مكتمل': 'booking_closed',
            'مكتمل_العدد': 'booking_closed',
            'قفل': 'booking_closed',
        }

        raw_status = (intent.new_status or "available").lower().strip()
        new_status = ALLOWED_STATUSES.get(raw_status, "available")
        daily_note = (intent.daily_note or "").strip()

        # 5. Prepare the daily override, but do NOT write it yet. It used
        # to be written by a separate call that committed its own
        # transaction (including a doctors-table update) before the atomic
        # mutation ran, so a crash inside the atomic mutation left the
        # status changed anyway and "rollback" was a lie. The override is
        # now written inside apply_admin_mutation_atomic, in the same
        # transaction as the doctors update, the audit log, and the job
        # completion, so all four commit together or none do.
        from app.services.time_utils import get_libya_now, ARABIC_DAYS

        _now = get_libya_now()
        override_row = {
            "override_date": _now.strftime("%Y-%m-%d"),
            "day_of_week": ARABIC_DAYS.get(_now.weekday(), "اليوم"),
            "doctor_name": doctor["name"],
            "clinic_type": "both",
            "status": new_status,
            "note": daily_note,
            "updated_by": sender_phone,
        }

        # Atomic SQLite mutation in doctors + audit-log + job completion
        before_label = STATUS_ARABIC_MAP.get(doctor["status"], doctor["status"])
        after_label = STATUS_ARABIC_MAP.get(new_status, new_status)

        receipt = (
            "✅ *إيصال تأكيد التحديث الفوري* ✅\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👨‍⚕️ *الطبيب:* {doctor['name']} ({doctor['specialty']})\n"
            f"🔄 *حالة التواجد:* {before_label} ⬅️ *{after_label}*\n"
            f"📝 *الملاحظة:* {daily_note if daily_note else 'لا توجد ملاحظات خاصة'}\n"
            f"📅 *التاريخ:* {override_row.get('override_date', '')} ({override_row.get('day_of_week', '')})\n"
            f"⏰ *وقت التحديث:* {time_ctx['time_arabic']} (بتوقيت ليبيا)\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "_تم حفظ التعديل بشكل دائم في جدول التحديثات اليومية (daily_overrides) وينعكس لحظياً على استفسارات المرضى._"
        )

        already_applied, status_before, status_after, final_receipt = db.apply_admin_mutation_atomic(
            mutation_type="doctor",
            target_id=doctor["id"],
            mutation_fields={"status": new_status, "daily_note": daily_note},
            audit_sender=sender_phone,
            raw_message=raw_message,
            confirmation_text=receipt,
            job_id=job_id,
            lease_token=lease_token,
            worker_id=worker_id,
            db_path=db_path,
            daily_override=override_row,
        )
        return final_receipt

    # 6. Handle Doctor Fee Update
    if intent.action == "UPDATE_FEE" and intent.doctor_identifier and intent.new_price is not None:
        if intent.new_price < 0 or intent.new_price > 5000:
            return "⚠️ *تعذر التحديث:* قيمة الكشفية غير منطقية. يرجى تحديد سعر صحيح بين 1 و 5000 دينار."

        doctor = db.find_doctor_fuzzy(name_query=intent.doctor_identifier, specialty_query=intent.doctor_identifier, db_path=db_path)
        if not doctor:
            return f"⚠️ *تعذر التحديث:* لم يتم العثور على طبيب باسم `{intent.doctor_identifier}`."

        receipt = (
            "✅ *إيصال تعديل كشفية الطبيب* ✅\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👨‍⚕️ *الطبيب:* {doctor['name']} ({doctor['specialty']})\n"
            f"💰 *الكشفية السابقة:* {doctor['consultation_fee']} د.ل\n"
            f"💵 *الكشفية الجديدة:* *{intent.new_price} د.ل*\n"
            f"⏰ *وقت التحديث:* {time_ctx['time_arabic']}\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "_انعكس السعر الجديد في النظام فورياً._"
        )

        already_applied, status_before, status_after, final_receipt = db.apply_admin_mutation_atomic(
            mutation_type="doctor",
            target_id=doctor["id"],
            mutation_fields={"consultation_fee": intent.new_price},
            audit_sender=sender_phone,
            raw_message=raw_message,
            confirmation_text=receipt,
            job_id=job_id,
            lease_token=lease_token,
            worker_id=worker_id,
            db_path=db_path
        )
        return final_receipt

    # 7. Handle Service Price Update
    if intent.action == "UPDATE_SERVICE_PRICE" and intent.service_identifier and intent.new_price is not None:
        if intent.new_price < 0 or intent.new_price > 10000:
            return "⚠️ *تعذر التحديث:* سعر التحليل أو الخدمة غير منطقي. يرجى تحديد سعر صحيح بالدينار الليبي."

        svc = db.find_service_fuzzy(intent.service_identifier, db_path=db_path)
        if not svc:
            return f"⚠️ *تعذر التحديث:* لم يتم العثور على تحليل أو خدمة باسم `{intent.service_identifier}`."

        receipt = (
            "✅ *إيصال تعديل سعر الخدمة / التحليل* ✅\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔬 *الخدمة:* {svc['name']} ({svc['category']})\n"
            f"💰 *السعر السابق:* {svc['price']} د.ل\n"
            f"💵 *السعر الجديد:* *{intent.new_price} د.ل*\n"
            f"⏰ *وقت التحديث:* {time_ctx['time_arabic']}\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "_تم حفظ السعر الجديد بالمختبر/الأقسام فورياً._"
        )

        already_applied, status_before, status_after, final_receipt = db.apply_admin_mutation_atomic(
            mutation_type="service",
            target_id=svc["id"],
            mutation_fields={"price": intent.new_price},
            audit_sender=sender_phone,
            raw_message=raw_message,
            confirmation_text=receipt,
            job_id=job_id,
            lease_token=lease_token,
            worker_id=worker_id,
            db_path=db_path
        )
        return final_receipt

    return "ℹ️ لم يتم التعرف على تفاصيل التعديل بدقة. يرجى مراجعة الصياغة والتأكد من ذكر اسم الطبيب أو الخدمة."
