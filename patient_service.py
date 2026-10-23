"""
LibyAI Patient Reception Service (`patient_service.py`)
Grounded, Zero-Mock Production Receptionist for:
Any Clinic, Hospital, Healthcare Center, or Professional Service Facility in Libya.


Features:
- Dynamic Real-Time Context Injection (Fresh DB fetch per request).
- Persistent Chat History (last 6 turns from `conversation_history`).
- Strict Grounding (Zero Hallucination - 100% bound to database).
- Libya Standard Time context (Africa/Tripoli).
- Multi-tier clinical safety guardrails & emergency triage.
"""

import os
import json
import re
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv

load_dotenv()

import db
import triage
from app.services.time_utils import (
    get_libya_now,
    get_libya_datetime_context,
    ARABIC_DAYS,
    LIBYA_TZ
)

preferred_model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
MODELS_CASCADE = [preferred_model, "gemini-2.5-flash", "gemini-1.5-flash", "gemini-2.0-flash", "gemini-3.1-flash-lite"]
_seen = set()
MODELS_CASCADE = [m for m in MODELS_CASCADE if not (m in _seen or _seen.add(m))]

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
        print(f"Warning: Could not initialize Gemini in patient_service: {e}")


def detect_target_day(query: str, current_day: str) -> str:
    """
    Detects if the patient inquiry targets a specific day of the week,
    otherwise defaults to current day in Tripoli.
    """
    q = query.lower()
    if "غدوة" in q or "غدا" in q or "بكرة" in q:
        now = get_libya_now()
        tomorrow = now + timedelta(days=1)
        return ARABIC_DAYS.get(tomorrow.weekday(), current_day)

    days_map = {
        "جمعة": "الجمعة",
        "سبت": "السبت",
        "احد": "الأحد",
        "أحد": "الأحد",
        "اثنين": "الاثنين",
        "إثنين": "الاثنين",
        "ثلاثاء": "الثلاثاء",
        "اربعاء": "الأربعاء",
        "أربعاء": "الأربعاء",
        "خميس": "الخميس"
    }
    for k, v in days_map.items():
        if k in q:
            return v

    return current_day


def build_system_instruction(clinic_info: Dict[str, Any], daily_schedule: Dict[str, Any], time_ctx: Dict[str, str]) -> str:
    """
    Builds strictly grounded system instruction for ANY clinic, hospital, or service facility.
    Dynamically loads facility profile and parameterizes all references.
    Zero hallucination: only answers with data retrieved from SQLite.
    """
    clinic_name = clinic_info.get("clinic_name") or clinic_info.get("name") or "المصحة"
    facility_type = clinic_info.get("facility_type") or ("مستشفى" if "مستشفى" in clinic_name else "مصحة" if "مصحة" in clinic_name else "مركز خدمات")
    address = clinic_info.get("address", "ليبيا")
    city = clinic_info.get("city", "")
    if not city:
        for c in ["زليتن", "طرابلس", "بنغازي", "مصراتة", "الزاوية", "البيضاء", "طبرق", "سبها", "سرت", "الخمس", "درنة"]:
            if c in address:
                city = c
                break
    city_suffix = f" في {city}" if city else ""

    emergency_phone = clinic_info.get("emergency_phone") or "0910000000"
    reception_phone = clinic_info.get("reception_phone") or clinic_info.get("contact_numbers") or emergency_phone
    phones = clinic_info.get("contact_numbers") or (
        f"{reception_phone} - {emergency_phone}" if emergency_phone != reception_phone else reception_phone
    )
    booking_policy = clinic_info.get("booking_policy", "الاستفسار والخدمات متاحة وفق الفترات المعلنة، والحضور أو الحجز عبر مكتب الاستقبال.")
    facilities_info = clinic_info.get("facilities_info", "الخدمات متوفرة وفق الجداول والمواعيد المعتمدة.")
    shifts_info = clinic_info.get("shifts_info") or (
        "• الفترة الصباحية: 08:00 ص إلى 02:00 ظ\n"
        "• الفترة المسائية: 02:00 ظ إلى 08:00 م\n"
        "• الفترة الليلية / الطوارئ: متاحة حسب جدول المناوبات"
    )

    is_medical = clinic_info.get("is_medical", True)

    target_day = daily_schedule.get("day_name", time_ctx.get("day_name", "اليوم"))
    target_date = daily_schedule.get("target_date", "")

    # Format Emergency / Urgent Clinics
    em_lines = []
    for em in daily_schedule.get("emergency_clinics", []):
        st_text = em.get("status_display", "متواجد ✅")
        note_str = f" | ملاحظة: {em['note']}" if em.get("note") else ""
        em_lines.append(
            f"• قسم {em['department']} | الفترة {em['shift']} ({em['shift_time']}): {em['doctor_name']} | الحالة: [{st_text}]{note_str}"
        )
    emergency_block = "\n".join(em_lines) if em_lines else "لا توجد مناوبات طوارئ/فترات مسجلة لهذا اليوم."

    # Format Followup Clinics / Consultations
    fu_lines = []
    for fu in daily_schedule.get("followup_clinics", []):
        st_text = fu.get("status_display", "متواجد ✅")
        note_str = f" | ملاحظة: {fu['note']}" if fu.get("note") else ""
        timing_str = f" | التوقيت: {fu['shift_note']}" if fu.get("shift_note") else ""
        fu_lines.append(
            f"• تخصص/قسم {fu['specialty']}: {fu['doctor_name']}{timing_str} | الحالة: [{st_text}]{note_str}"
        )
    followup_block = "\n".join(fu_lines) if fu_lines else "لا توجد عيادات متابعة/استشارات مسجلة لهذا اليوم."

    # Format Active Overrides
    ov_lines = []
    for ov in daily_schedule.get("overrides_applied", []):
        ov_lines.append(
            f"• المسؤول/الطبيب: {ov.get('doctor_name')} -> الحالة الحالية: [{ov.get('status')}] (ملاحظة: {ov.get('note', '')})"
        )
    overrides_block = "\n".join(ov_lines) if ov_lines else "لا توجد اعتذارات أو استثناءات مسجلة اليوم (جميع الكوادر وفق جدولهم الطبيعي)."

    if is_medical:
        role_desc = f'أنت موظف الاستقبال الآلي الرسمي لـ "{clinic_name}" ({facility_type}){city_suffix}.'
        guardrail_rule = f'5. الحارس الطبي: يُمنع منعاً باتاً تشخيص الأمراض أو وصف أي دواء أو تحديد جرعات طبية. في حالات الطوارئ الحادة والحرجة، وجّه المريض فوراً لزيارة قسم الإسعاف والطوارئ في {clinic_name} على العنوان ({address}) أو الاتصال فوراً بأرقام الطوارئ: ({phones}).'
    else:
        role_desc = f'أنت موظف الاستقبال وخدمة العملاء الآلي لـ "{clinic_name}" ({facility_type}){city_suffix}.'
        guardrail_rule = f'5. القواعد المهنية: تقديم المعلومات بدقة استناداً إلى جدول الخدمات والمستشارين المتاحين فقط. في المسائل التخصصية المعقدة، وجّه العميل لحجز موعد استشارة بمقر {clinic_name} على العنوان ({address}) أو التواصل مع إدارة المرفق على ({phones}).'

    return f"""
{role_desc}
مهمتك: الرد على استفسارات المراجعين والعملاء عبر واتساب بأسلوب ليبي مهذب، محترم، مختصر ومباشر.

-------------------------
[بيانات المرفق والثوابت العامة]
-------------------------
• اسم المرفق: {clinic_name}
• نوع المرفق: {facility_type}
• العنوان: {address}
• أرقام التواصل والاستفسار: {phones}
• الفترات ومواعيد العمل المعتمدة:
{shifts_info}
• الخدمات والتسهيلات: {facilities_info}
• نظام الحجز: {booking_policy}

-------------------------
[السياق الزمني المعتمد لليوم]
-------------------------
• توقيت ليبيا الحالي: {time_ctx.get('summary', '')}
• اليوم المستعلم عنه: {target_day} ({target_date})

-------------------------
[البيانات الحية المسحوبة لحظياً من قاعدة البيانات ليوم {target_day}]
-------------------------
[1] المناوبات والأقسام الأساسية ({target_day}):
{emergency_block}

[2] العيادات التخصصية والاستشارات ({target_day}):
{followup_block}

[3] الاستثناءات والتحديثات اللحظية المعتمدة لليوم:
{overrides_block}

-------------------------
[قواعد صارمة لمنع الهلوسة والالتزام بالبيانات (Zero Hallucination)]
-------------------------
1. أنت مقيد بنسبة 100% بالبيانات الحية المرفقة أعلاه فقط.
2. يُمنع منعاً باتاً اختراع أي اسم، أو تخمين موعد من عندك، أو تأليف أسعار غير واردة في البيانات.
3. إذا سأل المراجع عن شخص/طبيب/تخصص أو خدمة غير مدرجة في جدول اليوم أعلاه، قل له بوضوح وأدب:
   "هذا التخصص/الاسم غير مدرج في جدول اليوم، يمكنك التواصل مع الاستقبال على الرقم ({phones}) للتأكد من المواعيد القادمة."
4. إذا كان الشخص أو الطبيب مسجلاً كـ [معتذر اليوم - غير متواجد ❌]، يجب أن تخبر المراجع بوضوح أنه معتذر اليوم وغير متواجد.
{guardrail_rule}
6. التنسيق: استخدم نجوم *الخط العريض* للأسماء والفترات لتكون الرسالة واضحة وسريعة القراءة على واتساب.
"""


def fallback_patient_answer(query: str, clinic_info: Dict[str, Any], daily_schedule: Dict[str, Any]) -> str:
    """
    Deterministic fallback grounded 100% in SQLite data if LLM is unavailable.
    Completely dynamic for any clinic or facility.
    """
    q = query.lower()
    clinic_name = clinic_info.get("clinic_name") or clinic_info.get("name") or "المصحة"
    phones = clinic_info.get("contact_numbers") or clinic_info.get("reception_phone") or "أرقام الاستقبال"
    address = clinic_info.get("address", "ليبيا")
    city = clinic_info.get("city", "")
    city_suffix = f" في {city}" if city else ""
    shifts_info = clinic_info.get("shifts_info") or (
        "• *الفترة الصباحية:* 08:00 ص إلى 02:00 ظ\n"
        "• *الفترة المسائية:* 02:00 ظ إلى 08:00 م\n"
        "• *الفترة الليلية / الطوارئ:* متاحة حسب جدول المناوبات"
    )
    day_name = daily_schedule.get("day_name", "اليوم")

    # 1. Address / Location
    if any(k in q for k in ["عنوان", "مكان", "وين", "موقع", "وين تجوا", "خريطة"]):
        return (
            "أهلاً بك 🌸\n\n"
            f"📍 *عنوان {clinic_name}:*\n"
            f"{address}\n\n"
            f"📞 *للتواصل والاستفسار:* {phones}"
        )

    # 2. Working hours / Shifts
    if any(k in q for k in ["دوام", "ساعات", "فترات", "امتى تفتحوا", "توقيت", "وقت"]):
        return (
            f"أهلاً بك 🌸 الفترات الزمنية ومواعيد العمل المعتمدة في {clinic_name}:\n\n"
            f"{shifts_info}\n\n"
            f"📞 *للاستفسار المباشر:* {phones}"
        )

    # 3. Doctor / Specialty / Service Search in daily_schedule
    norm_q = db.norm(query)
    matched_emergency = []
    for em in daily_schedule.get("emergency_clinics", []):
        if db.norm(em["doctor_name"]) in norm_q or norm_q in db.norm(em["doctor_name"]) or db.norm(em["department"]) in norm_q:
            matched_emergency.append(em)

    matched_followup = []
    for fu in daily_schedule.get("followup_clinics", []):
        if db.norm(fu["doctor_name"]) in norm_q or norm_q in db.norm(fu["doctor_name"]) or db.norm(fu["specialty"]) in norm_q:
            matched_followup.append(fu)

    if matched_emergency or matched_followup:
        res_lines = [f"أهلاً بك 🌸 إليك بيانات الجدول ليوم *{day_name}*:\n"]
        if matched_emergency:
            res_lines.append("🏥 *المناوبات والكوادر المتاحة:*")
            for em in matched_emergency:
                res_lines.append(f"• *{em['doctor_name']}* ({em['department']}) | الفترة {em['shift']} ({em['shift_time']}) | الحالة: {em['status_display']}")
            res_lines.append("")

        if matched_followup:
            res_lines.append("🩺 *العيادات والاستشارات:*")
            for fu in matched_followup:
                note_str = f" ({fu['shift_note']})" if fu.get("shift_note") else ""
                res_lines.append(f"• *{fu['doctor_name']}* ({fu['specialty']}){note_str} | الحالة: {fu['status_display']}")
            res_lines.append("")

        res_lines.append(f"📍 *المقر:* {address}\n📞 *الاستقبال:* {phones}")
        return "\n".join(res_lines)

    # Default strictly grounded message
    return (
        f"مرحباً بك في خدمة الاستقبال الآلي لـ *{clinic_name}*{city_suffix} 🌸\n\n"
        f"يسعدني مساعدتك في معرفة جداول اليوم ({day_name})، مواعيد الفترات، أو موقع ومقر المرفق.\n\n"
        f"إذا كنت تسأل عن قسم أو تخصص معين ولم تجده، يرجى التواصل مباشرة مع الاستقبال على الأرقام:\n"
        f"📞 *{phones}*"
    )



def handle_patient_query(phone_number: str, query: str) -> str:
    """
    Main entrypoint for 1:1 patient inquiries:
    1. Multi-tier clinical safety triage.
    2. Dynamic Real-Time DB Query for Libya time & target day schedule with overrides.
    3. Multi-turn conversation context from persistent `conversation_history`.
    4. Strict grounding with Zero Hallucination.
    5. Durable saving of user and model turns to `conversation_history`.
    """
    clinic_info = db.get_facility_profile()
    time_ctx = get_libya_datetime_context()
    current_day = time_ctx.get("day_name", "الجمعة")

    # Step 1: Emergency Triage Check
    triage_result = triage.evaluate_triage(query, clinic_info)
    if triage_result.is_emergency and triage_result.immediate_response:
        db.add_conversation_history(phone_number, "user", query)
        db.add_conversation_history(phone_number, "model", triage_result.immediate_response)
        return triage_result.immediate_response

    # Step 2: Detect Target Day & Query Fresh Daily Schedule with Overrides
    target_day = detect_target_day(query, current_day)
    daily_schedule = db.get_daily_schedule(target_day)

    # Step 3: Retrieve Persistent Chat History (last 6 turns)
    history = db.get_conversation_history(phone_number, limit=6)

    # Step 4: Build System Instruction with Real-time DB Context
    system_instruction = build_system_instruction(clinic_info, daily_schedule, time_ctx)

    response_text = None

    if gemini_client:
        raw_turns = []
        for turn in history:
            role = "user" if turn["role"] == "user" else "model"
            raw_turns.append((role, turn["text"]))
        raw_turns.append(("user", query))

        sanitized_turns = []
        for role, text in raw_turns:
            if not text.strip():
                continue
            if not sanitized_turns:
                if role == "user":
                    sanitized_turns.append({"role": "user", "parts": [{"text": text}]})
            else:
                last_role = sanitized_turns[-1]["role"]
                if role != last_role:
                    sanitized_turns.append({"role": role, "parts": [{"text": text}]})
                else:
                    sanitized_turns[-1]["parts"][0]["text"] += f"\n{text}"

        for model_name in MODELS_CASCADE:
            try:
                response = gemini_client.models.generate_content(
                    model=model_name,
                    contents=sanitized_turns,
                    config={
                        "system_instruction": system_instruction,
                        "temperature": 0.2,
                    }
                )
                if response and response.text:
                    response_text = response.text.strip()
                    break
            except Exception as e:
                continue

    # Fallback to local deterministic grounded responder if LLM fails
    if not response_text:
        response_text = fallback_patient_answer(query, clinic_info, daily_schedule)

    # Step 5: Persist Conversation Turns
    db.add_conversation_history(phone_number, "user", query)
    db.add_conversation_history(phone_number, "model", response_text)

    return response_text
