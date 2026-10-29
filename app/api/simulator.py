import asyncio
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Request, Header, Depends
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

from app.config import settings, is_phone_authorized
from app.services.time_utils import get_libya_datetime_context

import db
import admin_service
import patient_service

router = APIRouter(prefix="/api/simulator", tags=["Simulator"])


import hmac
from fastapi import status


def check_simulator_admin_access(request: Request, x_admin_key: Optional[str] = Header(None)):
    """
    Enforces server-side authentication for administrative simulator endpoints:
    - In production: Disabled unless ENABLE_PROD_SIMULATOR is True AND valid X-Admin-Key is provided.
    - In development: Allowed for local development requests (localhost, 127.0.0.1, ::1, testclient)
      or any request presenting a valid X-Admin-Key.
    - Remote/unauthorized requests without valid X-Admin-Key are strictly rejected with 403 Forbidden.
    """
    # 1. Production Enforcement
    if settings.ENVIRONMENT == "production":
        if not getattr(settings, "ENABLE_PROD_SIMULATOR", False):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="⛔ تم تعطيل نقاط نهاية المحاكي الإدارية في بيئة الإنتاج."
            )
        # No admin secret configured means no key can ever match: reject
        # instead of crashing inside compare_digest on a None secret.
        if not settings.ADMIN_SECRET_KEY or not x_admin_key or not hmac.compare_digest(x_admin_key, settings.ADMIN_SECRET_KEY):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="⛔ غير مصرح: مفتاح الإدارة السري (X-Admin-Key) مفقود أو غير صحيح."
            )
        return

    # 2. Development Enforcement
    client_host = request.client.host if request.client else ""
    is_local = client_host in ("127.0.0.1", "localhost", "::1", "testclient")

    if x_admin_key:
        if not settings.ADMIN_SECRET_KEY or not hmac.compare_digest(x_admin_key, settings.ADMIN_SECRET_KEY):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="⛔ غير مصرح: مفتاح الإدارة السري (X-Admin-Key) غير صحيح."
            )
        return

    if is_local:
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="⛔ غير مصرح: يتطلب الوصول عن بعد توفير مفتاح الإدارة السري (X-Admin-Key)."
    )


# Alias for backward compatibility
check_simulator_write_access = check_simulator_admin_access


class SimulatorMessageRequest(BaseModel):
    sender: str = "0912345678"
    message: str


class ClinicSettingsRequest(BaseModel):
    clinic_name: str
    address: str
    emergency_phone: str
    reception_phone: str
    booking_policy: str
    authorized_phones: str
    payment_methods: Optional[str] = None
    insurance_companies: Optional[str] = None
    facilities_info: Optional[str] = None


class IngestRequest(BaseModel):
    raw_text: str


@router.post("/admin-message")
async def send_admin_simulation(req: SimulatorMessageRequest):
    """
    Simulates an authorized staff member sending a private 1:1 message on WhatsApp.
    Only authorized numbers can update clinic data.
    Disabled in production unless ENABLE_PROD_SIMULATOR is explicitly True.
    """
    if settings.ENVIRONMENT == "production" and not getattr(settings, "ENABLE_PROD_SIMULATOR", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="⛔ تم تعطيل نقاط نهاية المحاكي في بيئة الإنتاج."
        )

    info = db.get_clinic_info()
    auth_str = info.get("authorized_phones") or info.get("authorized_staff_phones") or settings.AUTHORIZED_STAFF_PHONES
    authorized = is_phone_authorized(req.sender, auth_str)

    if not authorized:
        return {
            "authorized": False,
            "ignored": True,
            "reply": "⛔ [رفض الوصول]: هذا الرقم غير مسجل ضمن أرقام موظفي المصحة المصرح لهم بالتعديل. يمكنك إضافة هذا الرقم من زر 'إعدادات المصحة والمصرح لهم'.",
            "sender": req.sender,
            "message": req.message
        }

    raw_msg = req.message.strip()
    # In 1:1 simulator staff chat, automatically tag with @Bot if missing
    if not any(tag in raw_msg.lower() for tag in ["@bot", "@بـوت", "@بوت", "@مساعد"]):
        tagged_msg = f"@Bot {raw_msg}"
    else:
        tagged_msg = raw_msg

    reply = admin_service.handle_admin_group_message(
        sender_phone=req.sender,
        raw_message=tagged_msg,
        group_id="simulator_staff"
    )

    ignored = reply is None
    if ignored:
        reply = "ℹ️ تم استلام رسالتك ولكن لم يتم التعرف على أمر تعديل مباشر. مثال للتعديل: 'دكتور العظام علي اعتذر اليوم' أو 'كشفية عيادة العيون صارت 50 دينار'."

    return {
        "authorized": True,
        "ignored": False,
        "reply": reply,
        "sender": req.sender,
        "message": req.message
    }


@router.post("/patient-message")
async def send_patient_simulation(req: SimulatorMessageRequest):
    """Simulates a patient sending a 1:1 inquiry message to the clinic."""
    if settings.ENVIRONMENT == "production" and not getattr(settings, "ENABLE_PROD_SIMULATOR", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="⛔ تم تعطيل نقاط نهاية المحاكي في بيئة الإنتاج."
        )
    reply = await asyncio.to_thread(
        patient_service.handle_patient_query,
        req.sender,
        req.message
    )
    return {
        "reply": reply,
        "sender": req.sender,
        "message": req.message
    }


@router.get("/state", dependencies=[Depends(check_simulator_admin_access)])
async def get_system_state():
    """Returns the full real-time database state for doctors, services, configs, and audit logs."""
    doctors = db.get_all_doctors()
    services = db.get_all_services()
    configs = db.get_clinic_info()

    clinic_name = configs.get("clinic_name") or configs.get("name") or settings.CLINIC_NAME
    auth_phones = configs.get("authorized_phones") or configs.get("authorized_staff_phones") or settings.AUTHORIZED_STAFF_PHONES

    # Fetch recent audit logs directly from database
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM audit_logs ORDER BY id DESC LIMIT 15;")
        log_rows = cursor.fetchall()

    logs = []
    for r in log_rows:
        keys = r.keys()
        sender_val = r["admin_sender"] if "admin_sender" in keys else (r["sender"] if "sender" in keys else "موظف")
        confirm_val = r["confirmation_text"] if "confirmation_text" in keys else (r["confirmation_sent"] if "confirmation_sent" in keys else "")
        action_val = r["action_type"] if "action_type" in keys else "تعديل لحظي"
        logs.append({
            "id": r["id"],
            "sender": sender_val,
            "raw_message": r["raw_message"],
            "action_type": action_val,
            "confirmation_sent": confirm_val,
            "created_at": str(r["created_at"])
        })

    # Map doctors for UI compatibility
    mapped_doctors = []
    for d in doctors:
        mapped_doctors.append({
            "id": d["id"],
            "name": d["name"],
            "specialty": d["specialty"],
            "room_number": d.get("room_number") or "عيادة عامة",
            "regular_schedule": d["regular_schedule"],
            "status": d["status"],
            "today_status": d["status"],
            "daily_note": d.get("daily_note") or "",
            "today_note": d.get("daily_note") or "",
            "consultation_fee": d["consultation_fee"],
            "updated_at": str(d.get("updated_at", ""))
        })

    # Map services for UI compatibility
    mapped_services = []
    for s in services:
        inst = s.get("instructions") or s.get("prep_instructions") or "لا توجد شروط خاصة"
        mapped_services.append({
            "id": s["id"],
            "name": s["name"],
            "category": s["category"],
            "price": s["price"],
            "instructions": inst,
            "prep_instructions": inst,
            "availability": s.get("availability") or "متاح خلال ساعات الدوام"
        })

    return {
        "doctors": mapped_doctors,
        "services": mapped_services,
        "configs": {
            "clinic_name": clinic_name,
            "name": clinic_name,
            "address": configs.get("address", settings.CLINIC_ADDRESS),
            "emergency_phone": configs.get("emergency_phone", settings.EMERGENCY_PHONE),
            "reception_phone": configs.get("reception_phone", settings.RECEPTION_PHONE),
            "booking_policy": configs.get("booking_policy", settings.BOOKING_POLICY),
            "authorized_phones": auth_phones,
            "authorized_staff_phones": auth_phones,
            "payment_methods": configs.get("payment_methods", "نقداً (كاش)، بطاقات الدفع المصرفي (تداول، نمو)، والخدمات الإلكترونية (سداد، إدفع لي، موبي كاش) بنفس السعر النقدي وبدون أي عمولة إضافية."),
            "insurance_companies": configs.get("insurance_companies", "متعاقدون مع تأمين المدار، ليبيانا، الشركة المتحدة للتأمين، وتأمين شركة الكهرباء والنفط، مع توفير فواتير معتمدة للاسترداد."),
            "facilities_info": configs.get("facilities_info", "قسم الطوارئ والمختبر متاحان 24 ساعة يومياً (بما في ذلك الجمعة والعطلات)، مع توفر مصاعد طبية حديثة لكبار السن وحالات العظام."),
            "map_link": configs.get("map_link", settings.CLINIC_MAP_LINK)
        },
        "logs": logs,
        "libya_time": get_libya_datetime_context()
    }


@router.post("/clinic-settings", dependencies=[Depends(check_simulator_admin_access)])
async def update_settings(req: ClinicSettingsRequest):
    """Updates clinic identity, booking policy, and authorized staff phone numbers."""
    db.update_clinic_info_key("clinic_name", req.clinic_name)
    db.update_clinic_info_key("name", req.clinic_name)
    db.update_clinic_info_key("address", req.address)
    db.update_clinic_info_key("emergency_phone", req.emergency_phone)
    db.update_clinic_info_key("reception_phone", req.reception_phone)
    db.update_clinic_info_key("booking_policy", req.booking_policy)
    db.update_clinic_info_key("authorized_phones", req.authorized_phones)
    db.update_clinic_info_key("authorized_staff_phones", req.authorized_phones)

    if req.payment_methods is not None:
        db.update_clinic_info_key("payment_methods", req.payment_methods)
    if req.insurance_companies is not None:
        db.update_clinic_info_key("insurance_companies", req.insurance_companies)
    if req.facilities_info is not None:
        db.update_clinic_info_key("facilities_info", req.facilities_info)

    # Sync runtime settings
    settings.CLINIC_NAME = req.clinic_name
    settings.CLINIC_ADDRESS = req.address
    settings.EMERGENCY_PHONE = req.emergency_phone
    settings.RECEPTION_PHONE = req.reception_phone
    settings.BOOKING_POLICY = req.booking_policy
    settings.AUTHORIZED_STAFF_PHONES = req.authorized_phones

    # Sync clinic_config table if exists
    try:
        with db.get_db() as conn:
            config_items = [
                ("clinic_name", req.clinic_name),
                ("name", req.clinic_name),
                ("address", req.address),
                ("emergency_phone", req.emergency_phone),
                ("reception_phone", req.reception_phone),
                ("booking_policy", req.booking_policy),
                ("authorized_phones", req.authorized_phones),
                ("authorized_staff_phones", req.authorized_phones),
            ]
            if req.payment_methods is not None:
                config_items.append(("payment_methods", req.payment_methods))
            if req.insurance_companies is not None:
                config_items.append(("insurance_companies", req.insurance_companies))
            if req.facilities_info is not None:
                config_items.append(("facilities_info", req.facilities_info))

            for k, v in config_items:
                conn.execute("INSERT OR REPLACE INTO clinic_config (key, value) VALUES (?, ?);", (k, v))
    except Exception:
        pass

    return {"status": "success", "message": "تم تحديث إعدادات المصحة وأرقام الموظفين المصرح لهم بنجاح"}


@router.post("/wipe-data", dependencies=[Depends(check_simulator_write_access)])
async def wipe_data():
    """Wipes all dummy doctors and services so the user can enter their real data completely."""
    with db.get_db() as conn:
        conn.execute("DELETE FROM doctors;")
        conn.execute("DELETE FROM services;")
        conn.execute("DELETE FROM audit_logs;")
        conn.execute("DELETE FROM conversation_sessions;")
    return {"status": "success", "message": "تم تفريغ كافة البيانات بنجاح. يمكنك الآن إدخال بيانات مصحتك الفعلية."}


@router.delete("/doctor/{doctor_id}", dependencies=[Depends(check_simulator_write_access)])
async def delete_doctor_endpoint(doctor_id: int):
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM doctors WHERE id = ?;", (doctor_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Doctor not found")
    return {"status": "success"}


@router.delete("/service/{service_id}", dependencies=[Depends(check_simulator_write_access)])
async def delete_service_endpoint(service_id: int):
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM services WHERE id = ?;", (service_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Service not found")
    return {"status": "success"}


@router.post("/reset", dependencies=[Depends(check_simulator_write_access)])
async def reset_database():
    """Resets database back to seed defaults."""
    with db.get_db() as conn:
        conn.execute("DELETE FROM doctors;")
        conn.execute("DELETE FROM services;")
        conn.execute("DELETE FROM audit_logs;")
        conn.execute("DELETE FROM conversation_sessions;")
    db.init_db()
    db.seed_default_data()
    return {"status": "success", "message": "تمت إعادة ضبط البيانات إلى الوضع الافتراضي بنجاح"}


@router.post("/ai-ingest")
async def ai_ingest_endpoint(req: IngestRequest):
    """Accepts any raw unstructured text, copied tables, parses with Gemini, and saves into DB."""
    from app.services import llm_service
    result = llm_service.ingest_clinic_data_with_ai(raw_text=req.raw_text)
    return result


@router.post("/ai-ingest-file")
async def ai_ingest_file_endpoint(
    file: Optional[UploadFile] = File(None),
    raw_text: Optional[str] = Form(None)
):
    """
    Accepts uploaded files (Excel .xlsx/.xls, CSV, PDF, or Images .png/.jpg/.jpeg/.webp)
    along with optional notes, parses with Gemini multimodal vision/OCR, and saves into DB.
    """
    from app.services import llm_service
    file_bytes = None
    filename = None
    mime_type = None

    if file:
        filename = file.filename
        mime_type = file.content_type
        file_bytes = await file.read()

    result = llm_service.ingest_clinic_data_with_ai(
        raw_text=raw_text or "",
        file_bytes=file_bytes,
        filename=filename,
        mime_type=mime_type
    )
    return result
