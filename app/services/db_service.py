from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from sqlmodel import Session, select
from app.database.models import Doctor, Service, ClinicConfig, AuditLog
from app.database.session import engine
from app.config import settings
from app.services.time_utils import get_libya_datetime_context


def get_all_doctors() -> List[Doctor]:
    with Session(engine) as session:
        statement = select(Doctor).where(Doctor.is_active == True)
        return list(session.exec(statement).all())


def get_doctors_by_specialty(specialty: str) -> List[Doctor]:
    with Session(engine) as session:
        statement = select(Doctor).where(
            Doctor.is_active == True,
            Doctor.specialty.contains(specialty)
        )
        return list(session.exec(statement).all())


def find_doctor_fuzzy(name_query: Optional[str] = None, specialty_query: Optional[str] = None) -> Optional[Doctor]:
    """
    Adapter over the legacy finder: scoring lives in exactly one place
    (`db.find_doctor_fuzzy`), and this function only converts its result
    to a SQLModel object so existing callers keep their return type.

    Previously this function had its own scoring, which diverged from
    the legacy finder (at one point it returned the first doctor sharing
    ANY keyword). Keeping two scorings in sync by hand failed, so there
    is now one. The active-only filter of the old SQLModel version is
    preserved: an inactive doctor found by the legacy finder is not
    returned here.
    """
    import db

    found = db.find_doctor_fuzzy(name_query=name_query, specialty_query=specialty_query)
    if not found:
        return None
    with Session(engine) as session:
        doc = session.get(Doctor, found["id"])
        if doc is None or not doc.is_active:
            return None
        return doc


def update_doctor_today_status(doctor_id: int, status: str, note: str = "") -> Optional[Doctor]:
    """
    Adapter over the legacy atomic doctor update, same pattern as the
    finders in round 5: the write lives in `db.update_doctor_atomic`,
    this only converts the result to a SQLModel object.

    This also fixes a sync bug in the old SQLModel version, which
    updated only today_status/today_note and left status/daily_note
    stale. Every other writer in the codebase keeps status and
    today_status (and daily_note and today_note) in sync, and readers
    use both, so a half-updated row was a divergence waiting to happen.
    A missing doctor still returns None, as before, instead of raising.
    """
    import db

    try:
        db.update_doctor_atomic(doctor_id, status=status, daily_note=note)
    except ValueError:
        return None
    with Session(engine) as session:
        return session.get(Doctor, doctor_id)


def upsert_doctor(name: str, specialty: str, regular_schedule: str, consultation_fee: float, room_number: str = "غير محدد", schedule_days: str = "السبت,الأحد,الإثنين,الثلاثاء,الأربعاء,الخميس") -> Doctor:
    with Session(engine) as session:
        clean_name = name.strip()
        if not clean_name.startswith("د.") and not clean_name.startswith("دكتور"):
            clean_name = f"د. {clean_name}"
            
        clean_search = clean_name.replace("د.", "").replace("دكتور", "").replace("دكتورة", "").strip().lower()
        
        doctors = list(session.exec(select(Doctor)).all())
        existing = None
        for d in doctors:
            d_clean = d.name.replace("د.", "").replace("دكتور", "").replace("دكتورة", "").strip().lower()
            if clean_search == d_clean or (len(clean_search) > 4 and clean_search in d_clean):
                existing = d
                break

        if existing:
            doc = session.get(Doctor, existing.id)
            doc.specialty = specialty or doc.specialty
            doc.regular_schedule = regular_schedule or doc.regular_schedule
            if consultation_fee and consultation_fee > 0:
                doc.consultation_fee = consultation_fee
            if room_number and room_number != "غير محدد":
                doc.room_number = room_number
            doc.updated_at = datetime.now(timezone.utc)
            session.add(doc)
            session.commit()
            session.refresh(doc)
            return doc
        else:
            new_doc = Doctor(
                name=clean_name,
                specialty=specialty or "عام",
                regular_schedule=regular_schedule or "يومياً",
                consultation_fee=consultation_fee if consultation_fee > 0 else 40.0,
                room_number=room_number or "غير محدد",
                schedule_days=schedule_days,
                today_status="available",
                updated_at=datetime.now(timezone.utc)
            )
            session.add(new_doc)
            session.commit()
            session.refresh(new_doc)
            return new_doc


def upsert_service(name: str, category: str, price: float, prep_instructions: str = "", availability: str = "متاح 24 ساعة") -> Service:
    with Session(engine) as session:
        clean_name = name.strip().lower()
        services = list(session.exec(select(Service)).all())
        existing = None
        for s in services:
            if clean_name == s.name.strip().lower():
                existing = s
                break

        if existing:
            svc = session.get(Service, existing.id)
            if category:
                svc.category = category
            if price and price > 0:
                svc.price = price
            if prep_instructions:
                svc.prep_instructions = prep_instructions
                svc.instructions = prep_instructions
            if availability:
                svc.availability = availability
            svc.updated_at = datetime.now(timezone.utc)
            session.add(svc)
            session.commit()
            session.refresh(svc)
            return svc
        else:
            new_svc = Service(
                name=name.strip(),
                category=category or "مختبر",
                price=price if price > 0 else 0.0,
                instructions=prep_instructions,
                prep_instructions=prep_instructions,
                availability=availability or "متاح",
                updated_at=datetime.now(timezone.utc)
            )
            session.add(new_svc)
            session.commit()
            session.refresh(new_svc)
            return new_svc


def update_doctor_fee(doctor_id: int, new_fee: float) -> Optional[Doctor]:
    """Adapter over `db.update_doctor_atomic` (fee only, other fields kept)."""
    import db

    try:
        db.update_doctor_atomic(doctor_id, consultation_fee=new_fee)
    except ValueError:
        return None
    with Session(engine) as session:
        return session.get(Doctor, doctor_id)


def get_all_services(category: Optional[str] = None) -> List[Service]:
    with Session(engine) as session:
        statement = select(Service)
        if category:
            statement = statement.where(Service.category == category)
        return list(session.exec(statement).all())


def find_service_fuzzy(service_name: str) -> Optional[Service]:
    """
    Adapter over the legacy finder, same pattern as find_doctor_fuzzy:
    scoring lives in `db.find_service_fuzzy`; this only converts the
    result to a SQLModel object. Previously this had its own
    first-match-any-keyword logic, which could return a different
    service than the legacy finder for the same query.
    """
    import db

    found = db.find_service_fuzzy(service_name)
    if not found:
        return None
    with Session(engine) as session:
        return session.get(Service, found["id"])


def update_service_price(service_id: int, new_price: float) -> Optional[Service]:
    """Adapter over `db.update_service_atomic` (price only)."""
    import db

    try:
        db.update_service_atomic(service_id, price=new_price)
    except ValueError:
        return None
    with Session(engine) as session:
        return session.get(Service, service_id)


def get_clinic_configs() -> Dict[str, str]:
    import db
    info = db.get_clinic_info()
    clinic_name = info.get("clinic_name") or info.get("name") or settings.CLINIC_NAME
    auth_phones = info.get("authorized_phones") or info.get("authorized_staff_phones") or settings.AUTHORIZED_STAFF_PHONES
    
    return {
        "clinic_name": clinic_name,
        "name": clinic_name,
        "address": info.get("address", settings.CLINIC_ADDRESS),
        "emergency_phone": info.get("emergency_phone", settings.EMERGENCY_PHONE),
        "reception_phone": info.get("reception_phone", settings.RECEPTION_PHONE),
        "booking_policy": info.get("booking_policy", settings.BOOKING_POLICY),
        "authorized_phones": auth_phones,
        "authorized_staff_phones": auth_phones,
        "map_link": info.get("map_link", settings.CLINIC_MAP_LINK)
    }


def log_audit(sender: str, raw_message: str, action_type: str, extracted_data: str, confirmation_sent: str) -> AuditLog:
    with Session(engine) as session:
        log = AuditLog(
            sender=sender,
            raw_message=raw_message,
            action_type=action_type,
            extracted_data=extracted_data,
            confirmation_sent=confirmation_sent,
            created_at=datetime.now(timezone.utc),
        )
        session.add(log)
        session.commit()
        session.refresh(log)
        return log


def get_recent_audit_logs(limit: int = 15) -> List[AuditLog]:
    with Session(engine) as session:
        statement = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
        return list(session.exec(statement).all())


def update_clinic_config(key: str, value: str, description: Optional[str] = None):
    import db
    db.update_clinic_info_key(key, value)
    
    # Sync runtime settings
    if key in ["clinic_name", "name"]:
        settings.CLINIC_NAME = value
    elif key == "address":
        settings.CLINIC_ADDRESS = value
    elif key == "emergency_phone":
        settings.EMERGENCY_PHONE = value
    elif key == "reception_phone":
        settings.RECEPTION_PHONE = value
    elif key == "booking_policy":
        settings.BOOKING_POLICY = value
    elif key in ["authorized_phones", "authorized_staff_phones"]:
        settings.AUTHORIZED_STAFF_PHONES = value

    with Session(engine) as session:
        statement = select(ClinicConfig).where(ClinicConfig.key == key)
        cfg = session.exec(statement).first()
        if cfg:
            cfg.value = value
            if description:
                cfg.description = description
            session.add(cfg)
        else:
            new_cfg = ClinicConfig(key=key, value=value, description=description)
            session.add(new_cfg)
        session.commit()


def update_multiple_configs(configs_dict: Dict[str, str]):
    for k, v in configs_dict.items():
        update_clinic_config(k, v)


def delete_doctor(doctor_id: int) -> bool:
    with Session(engine) as session:
        doc = session.get(Doctor, doctor_id)
        if doc:
            session.delete(doc)
            session.commit()
            return True
        return False


def delete_service(service_id: int) -> bool:
    with Session(engine) as session:
        svc = session.get(Service, service_id)
        if svc:
            session.delete(svc)
            session.commit()
            return True
        return False


def wipe_all_data(keep_configs: bool = False):
    """Completely wipes dummy/seed doctors and services to start fresh."""
    from sqlmodel import delete
    with Session(engine) as session:
        session.exec(delete(Doctor))
        session.exec(delete(Service))
        if not keep_configs:
            session.exec(delete(AuditLog))
        session.commit()


def get_prompt_formatted_data() -> Dict[str, Any]:
    """Prepares structured prompt injection data for the patient reception prompt."""
    import json
    doctors = get_all_doctors()
    services = get_all_services()
    configs = get_clinic_configs()
    time_ctx = get_libya_datetime_context()

    status_labels_ar = {
        "available": "متواجد حسب موعده المعتاد",
        "arrived": "وصل للعيادة ويباشر استقبال الكشوفات حالياً",
        "left": "غادر العيادة (أنهى كشوفات اليوم ولا يستقبل حالات جديدة)",
        "booking_closed": "مكتمل العدد (تم إيقاف حجز أرقام جديدة لليوم)",
        "delayed": "تأخير / تعديل موعد الحضور لليوم",
        "apologized": "معتذر اليوم (غير متواجد بالمصحة)",
        "off_duty": "ليس يوم دوامه الرسمي",
    }

    docs_list = []
    for d in doctors:
        status_label = status_labels_ar.get(d.today_status, d.today_status)
        docs_list.append({
            "name": d.name,
            "specialty": d.specialty,
            "room": d.room_number,
            "schedule": d.regular_schedule,
            "fee_lyd": d.consultation_fee,
            "status_code": d.today_status,
            "status_today_arabic": status_label,
            "note_today": d.today_note or "لا توجد ملاحظات خاصة"
        })

    services_list = []
    for s in services:
        services_list.append({
            "service_name": s.name,
            "category": s.category,
            "price_lyd": s.price,
            "preparation": s.prep_instructions or "لا توجد شروط خاصة",
            "availability": s.availability
        })

    return {
        "clinic_name": configs.get("clinic_name", settings.CLINIC_NAME),
        "address": configs.get("address", settings.CLINIC_ADDRESS),
        "emergency_phone": configs.get("emergency_phone", settings.EMERGENCY_PHONE),
        "booking_policy": configs.get("booking_policy", settings.BOOKING_POLICY),
        "libya_time_summary": time_ctx["summary"],
        "libya_time_arabic": time_ctx["time_arabic"],
        "libya_day_name": time_ctx["day_name"],
        "libya_date_arabic": time_ctx["date_arabic"],
        "doctors_data_json": json.dumps(docs_list, ensure_ascii=False, indent=2),
        "services_data_json": json.dumps(services_list, ensure_ascii=False, indent=2)
    }


def get_clinic_knowledge_context() -> str:
    """Builds a rich, real-time knowledge base snapshot for the LLM to answer patient questions."""
    doctors = get_all_doctors()
    services = get_all_services()
    configs = get_clinic_configs()
    time_ctx = get_libya_datetime_context()

    status_labels = {
        "available": "متواجد حسب الجدول المعتاد",
        "arrived": "وصل للعيادة وموجود حالياً يستقبل الحالات",
        "left": "غادر العيادة (أنهى كشوفات اليوم وغادر المصحة)",
        "booking_closed": "مكتمل العدد (تم إيقاف حجز أرقام جديدة لليوم)",
        "apologized": "معتذر اليوم (غير متواجد)",
        "delayed": "تأخير / تعديل موعد الحضور",
        "off_duty": "ليس يوم دوامه الرسمي",
    }

    doctors_txt = []
    for d in doctors:
        status_str = status_labels.get(d.today_status, d.today_status)
        note_str = f" | ملاحظة اليوم: {d.today_note}" if d.today_note else ""
        doctors_txt.append(
            f"- {d.name} ({d.specialty}) | العيادة: {d.room_number} | الجدول الأسبوعي: {d.regular_schedule} | "
            f"سعر الكشف: {d.consultation_fee} د.ل | حالة اليوم: [{status_str}]{note_str}"
        )

    services_txt = []
    for s in services:
        prep = f" | إرشادات التحضير: {s.prep_instructions}" if s.prep_instructions else " | لا توجد شروط مسبقة"
        services_txt.append(f"- [{s.category}] {s.name} | السعر: {s.price} د.ل | التوفر: {s.availability}{prep}")

    context = f"""
=== التوقيت الحالي في ليبيا (طرابلس) ===
{time_ctx['summary']}

=== معلومات المصحة العامة ===
اسم المصحة: {configs.get('clinic_name', settings.CLINIC_NAME)}
العنوان: {configs.get('address', settings.CLINIC_ADDRESS)}
أرقام الإسعاف والطوارئ (24 ساعة): {configs.get('emergency_phone', settings.EMERGENCY_PHONE)}
هاتف الاستعلامات: {configs.get('reception_phone', settings.RECEPTION_PHONE)}
أوقات العمل: {configs.get('working_hours', 'الطوارئ والمختبر 24 ساعة')}
آلية الحجز الرسمية والمعتمدة: {configs.get('booking_policy', settings.BOOKING_POLICY)}

=== جدول الأطباء الحالي والمحدث لحظياً ===
{chr(10).join(doctors_txt)}

=== قائمة الفحوصات والتحاليل والأسعار والإرشادات ===
{chr(10).join(services_txt)}
"""
    return context.strip()

