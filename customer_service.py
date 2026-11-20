"""
LibyAI Customer Service (`customer_service.py`)
Grounded, Zero-Mock Production Customer Assistant for:
Any Libyan business — retail shop, restaurant, clinic, pharmacy,
service office, workshop, or general business — on Messenger
(primary) or WhatsApp (secondary).

Features:
- Dynamic Real-Time Context Injection (Fresh DB fetch per request:
  business_info, catalog_items, resources, business_faqs).
- Persistent Chat History per sender AND channel (last 6 turns from
  `conversation_history`).
- Strict Grounding (Zero Hallucination - 100% bound to database).
- Libya Standard Time context (Africa/Tripoli).
- Sector-aware guardrails: commercial human handoff on every sector;
  the deterministic medical emergency bypass and clinical-advice
  restrictions activate ONLY for medical sectors (clinic, pharmacy,
  medical) — see guardrails.py.
- Prices are always stated in LYD (Libyan Dinar).

`patient_service.py` remains as a thin compatibility shim re-exporting
this module, so existing imports keep working.
"""

import os
import json
import re
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv

load_dotenv()

import db
import guardrails
from app.services.time_utils import (
    get_libya_now,
    get_libya_datetime_context,
    ARABIC_DAYS,
    LIBYA_TZ
)

from app.config import settings as _app_settings

# The configured model (app/config.py GEMINI_MODEL, default
# gemini-3.1-flash-lite, same as .env.example) heads the fallback chain,
# so one setting controls the primary model everywhere. The same
# GEMINI_MODEL environment variable still overrides it, via settings.
preferred_model = _app_settings.GEMINI_MODEL
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
        print(f"Warning: Could not initialize Gemini in customer_service: {e}")


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


SECTOR_LABELS = {
    "retail": "متجر تجزئة",
    "restaurant": "مطعم",
    "clinic": "مصحة",
    "pharmacy": "صيدلية",
    "service_office": "مكتب خدمات",
    "workshop": "ورشة",
    "general": "نشاط تجاري",
    "medical": "مرفق طبي",
}


def build_system_instruction(
    business_profile: Dict[str, Any],
    catalog_view: Optional[List[Dict[str, Any]]] = None,
    daily_schedule: Optional[Dict[str, Any]] = None,
    time_ctx: Optional[Dict[str, str]] = None,
    faqs: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """
    Builds a strictly grounded system instruction for ANY Libyan business.
    Dynamically loads the business profile and live DB data and
    parameterizes all references. Zero hallucination: only answers with
    data retrieved from SQLite. Prices are always in LYD.
    """
    business_profile = business_profile or {}
    daily_schedule = daily_schedule or {}
    time_ctx = time_ctx or {}
    catalog_view = catalog_view or []
    faqs = faqs or []

    business_name = (
        business_profile.get("business_name")
        or business_profile.get("clinic_name")
        or business_profile.get("name")
        or "النشاط التجاري"
    )
    sector = (business_profile.get("sector") or "general").strip().lower()
    sector_label = SECTOR_LABELS.get(sector, business_profile.get("facility_type") or "نشاط تجاري")
    address = business_profile.get("address", "ليبيا")
    city = business_profile.get("city", "")
    if not city:
        for c in ["زليتن", "طرابلس", "بنغازي", "مصراتة", "الزاوية", "البيضاء", "طبرق", "سبها", "سرت", "الخمس", "درنة"]:
            if c in address:
                city = c
                break
    city_suffix = f" في {city}" if city else ""

    support_phone = business_profile.get("support_phone") or business_profile.get("reception_phone") or "0910000000"
    escalation_phone = business_profile.get("escalation_phone") or business_profile.get("emergency_phone") or support_phone
    phones = business_profile.get("contact_numbers") or (
        f"{support_phone} - {escalation_phone}" if escalation_phone != support_phone else support_phone
    )
    working_hours = business_profile.get("working_hours") or business_profile.get("shifts_info") or (
        "• الفترة الصباحية: 08:00 ص إلى 02:00 ظ\n"
        "• الفترة المسائية: 02:00 ظ إلى 08:00 م"
    )
    policy_notes = business_profile.get("policy_notes") or business_profile.get("booking_policy") or (
        "الاستفسار والخدمات متاحة وفق الفترات المعلنة."
    )
    currency = business_profile.get("currency") or "LYD"

    is_medical = guardrails.is_medical_sector(business_profile)

    target_day = daily_schedule.get("day_name", time_ctx.get("day_name", "اليوم"))
    target_date = daily_schedule.get("target_date", "")

    # Catalog block (all sectors): products / services / menu items.
    cat_lines = []
    for item in catalog_view:
        avail = "متوفر ✅" if item.get("is_available") else "غير متوفر حالياً ❌"
        eta = f" | {item['schedule_or_eta']}" if item.get("schedule_or_eta") else ""
        details = f" | {item['details']}" if item.get("details") else ""
        cat_lines.append(
            f"• {item['name']} ({item.get('category') or 'عام'}) | السعر: {item.get('price_lyd', 0)} دينار | {avail}{eta}{details}"
        )
    catalog_block = "\n".join(cat_lines) if cat_lines else "لا توجد أصناف مسجلة في الكتالوج حالياً."

    # FAQ block (all sectors).
    faq_lines = [f"• س: {f['question']}\n  ج: {f['answer']}" for f in faqs]
    faq_block = "\n".join(faq_lines) if faq_lines else "لا توجد أسئلة شائعة مسجلة."

    # Medical schedule blocks (medical sectors only).
    schedule_section = ""
    if is_medical:
        em_lines = []
        for em in daily_schedule.get("emergency_clinics", []):
            st_text = em.get("status_display", "متواجد ✅")
            note_str = f" | ملاحظة: {em['note']}" if em.get("note") else ""
            em_lines.append(
                f"• قسم {em['department']} | الفترة {em['shift']} ({em['shift_time']}): {em['doctor_name']} | الحالة: [{st_text}]{note_str}"
            )
        emergency_block = "\n".join(em_lines) if em_lines else "لا توجد مناوبات طوارئ/فترات مسجلة لهذا اليوم."

        fu_lines = []
        for fu in daily_schedule.get("followup_clinics", []):
            st_text = fu.get("status_display", "متواجد ✅")
            note_str = f" | ملاحظة: {fu['note']}" if fu.get("note") else ""
            timing_str = f" | التوقيت: {fu['shift_note']}" if fu.get("shift_note") else ""
            fu_lines.append(
                f"• تخصص/قسم {fu['specialty']}: {fu['doctor_name']}{timing_str} | الحالة: [{st_text}]{note_str}"
            )
        followup_block = "\n".join(fu_lines) if fu_lines else "لا توجد عيادات متابعة/استشارات مسجلة لهذا اليوم."

        ov_lines = []
        for ov in daily_schedule.get("overrides_applied", []):
            ov_lines.append(
                f"• المسؤول/الطبيب: {ov.get('doctor_name')} -> الحالة الحالية: [{ov.get('status')}] (ملاحظة: {ov.get('note', '')})"
            )
        overrides_block = "\n".join(ov_lines) if ov_lines else "لا توجد اعتذارات أو استثناءات مسجلة اليوم (جميع الكوادر وفق جدولهم الطبيعي)."

        schedule_section = f"""
[المناوبات والأقسام الأساسية ({target_day}):
{emergency_block}

[العيادات التخصصية والاستشارات ({target_day}):
{followup_block}

[الاستثناءات والتحديثات اللحظية المعتمدة لليوم:
{overrides_block}
"""

    if is_medical:
        role_desc = f'أنت موظف الاستقبال الآلي الرسمي لـ "{business_name}" ({sector_label}){city_suffix}.'
        guardrail_rule = (
            f'5. الحارس الطبي: يُمنع منعاً باتاً تشخيص الأمراض أو وصف أي دواء أو تحديد جرعات طبية. '
            f'في حالات الطوارئ الحادة والحرجة، وجّه العميل فوراً لزيارة قسم الإسعاف والطوارئ في {business_name} '
            f'على العنوان ({address}) أو الاتصال فوراً بأرقام الطوارئ: ({phones}).'
        )
    else:
        role_desc = f'أنت موظف خدمة العملاء الآلي لـ "{business_name}" ({sector_label}){city_suffix}.'
        guardrail_rule = (
            f'5. التحويل البشري: إذا طلب العميل التحدث مع إنسان أو مدير، أو اشتكى بغضب، أو طلب استرجاعاً أو '
            f'تعويضاً، أو طلب طلبية خاصة/بالجملة، وجّهه بأدب إلى الإدارة على الرقم ({escalation_phone}) '
            f'ولا تعد بأي استرجاع أو خصم أو حل من عندك.'
        )

    return f"""
{role_desc}
مهمتك: الرد على استفسارات العملاء عبر ماسنجر أو واتساب بأسلوب ليبي مهذب، محترم، مختصر ومباشر، مع مطابقة نبرة العميل.

-------------------------
[بيانات النشاط والثوابت العامة]
-------------------------
• اسم النشاط: {business_name}
• القطاع: {sector_label}
• العنوان: {address}
• أرقام التواصل والاستفسار: {phones}
• ساعات العمل:
{working_hours}
• السياسات (التوصيل، الحجز، الاسترجاع، الدفع): {policy_notes}
• العملة: {currency} (الدينار الليبي) — كل الأسعار بالدينار الليبي فقط.

-------------------------
[السياق الزمني المعتمد لليوم]
-------------------------
• توقيت ليبيا الحالي: {time_ctx.get('summary', '')}
• اليوم المستعلم عنه: {target_day} ({target_date})

-------------------------
[البيانات الحية المسحوبة لحظياً من قاعدة البيانات]
-------------------------
[1] الكتالوج (منتجات / خدمات / أصناف):
{catalog_block}

[2] الأسئلة الشائعة والسياسات:
{faq_block}
{schedule_section}
-------------------------
[قواعد صارمة لمنع الهلوسة والالتزام بالبيانات (Zero Hallucination)]
-------------------------
1. أنت مقيد بنسبة 100% بالبيانات الحية المرفقة أعلاه فقط.
2. يُمنع منعاً باتاً اختراع أي اسم، أو تخمين موعد من عندك، أو تأليف أسعار أو رسوم توصيل غير واردة في البيانات.
3. إذا سأل العميل عن منتج أو خدمة أو شخص غير مدرج في البيانات أعلاه، قل له بوضوح وأدب:
   "هذا الصنف/الاسم غير مدرج حالياً، يمكنك التواصل مع الإدارة على الرقم ({phones}) للتأكد."
4. إذا كان الصنف مسجلاً كـ [غير متوفر حالياً ❌]، أخبر العميل بوضوح أنه غير متوفر، ولا تقترح بديلاً غير مسجل.
{guardrail_rule}
6. التنسيق: استخدم نجوم *الخط العريض* للأسماء والأسعار لتكون الرسالة واضحة وسريعة القراءة على ماسنجر وواتساب.
"""


def fallback_customer_answer(
    query: str,
    business_profile: Dict[str, Any],
    daily_schedule: Optional[Dict[str, Any]] = None,
    history=None,
    db_path: Optional[str] = None,
) -> str:
    """
    Deterministic fallback grounded 100% in SQLite data if LLM is unavailable.
    Completely dynamic for any business sector. Answer order:
    address/hours -> catalog match (price/availability in LYD) -> FAQ
    match -> medical schedule (medical sectors only) -> contextual price
    follow-up from history -> generic grounded welcome.
    """
    daily_schedule = daily_schedule or {}
    q = query.lower()
    business_name = (
        business_profile.get("business_name")
        or business_profile.get("clinic_name")
        or business_profile.get("name")
        or "النشاط التجاري"
    )
    phones = (
        business_profile.get("contact_numbers")
        or business_profile.get("support_phone")
        or business_profile.get("reception_phone")
        or "أرقام الاستقبال"
    )
    address = business_profile.get("address", "ليبيا")
    city = business_profile.get("city", "")
    city_suffix = f" في {city}" if city else ""
    working_hours = business_profile.get("working_hours") or business_profile.get("shifts_info") or (
        "• *الفترة الصباحية:* 08:00 ص إلى 02:00 ظ\n"
        "• *الفترة المسائية:* 02:00 ظ إلى 08:00 م"
    )
    day_name = daily_schedule.get("day_name", "اليوم")
    is_medical = guardrails.is_medical_sector(business_profile)
    db_path = db_path or db.DB_PATH

    # 1. Address / Location
    if any(k in q for k in ["عنوان", "مكان", "وين", "موقع", "وين تجوا", "خريطة"]):
        map_link = business_profile.get("map_link") or ""
        map_line = f"\n🗺️ *الخريطة:* {map_link}" if map_link else ""
        return (
            "أهلاً بك 🌸\n\n"
            f"📍 *عنوان {business_name}:*\n"
            f"{address}{map_line}\n\n"
            f"📞 *للتواصل والاستفسار:* {phones}"
        )

    # 2. Working hours / Shifts
    if any(k in q for k in ["دوام", "ساعات", "فترات", "امتى تفتحوا", "توقيت", "وقت", "فاتحين"]):
        return (
            f"أهلاً بك 🌸 مواعيد العمل المعتمدة في {business_name}:\n\n"
            f"{working_hours}\n\n"
            f"📞 *للاستفسار المباشر:* {phones}"
        )

    # 3. Catalog match (all sectors): price / availability / details in LYD.
    catalog_hit = db.find_in_catalog_view(query, db_path=db_path)
    if catalog_hit:
        avail = "متوفر ✅" if catalog_hit.get("is_available") else "غير متوفر حالياً ❌"
        eta = f"\n⏰ *التوقيت/التوصيل:* {catalog_hit['schedule_or_eta']}" if catalog_hit.get("schedule_or_eta") else ""
        details = f"\n📌 *تفاصيل:* {catalog_hit['details']}" if catalog_hit.get("details") else ""
        return (
            f"أهلاً بك 🌸\n\n"
            f"🛍️ *{catalog_hit['name']}* ({catalog_hit.get('category') or 'عام'})\n"
            f"💰 *السعر:* {catalog_hit.get('price_lyd', 0)} د.ل\n"
            f"📦 *التوفر:* {avail}{eta}{details}\n\n"
            f"📍 *المقر:* {address}\n📞 *الاستفسار:* {phones}"
        )

    # 4. FAQ match (delivery zones, returns, payment, warranty...).
    faq = db.match_faq(query, db_path=db_path)
    if faq:
        return (
            f"أهلاً بك 🌸\n\n"
            f"❓ *{faq['question']}*\n"
            f"{faq['answer']}\n\n"
            f"📞 *للاستفسار المباشر:* {phones}"
        )

    # 5. Doctor / Specialty / Service Search in daily_schedule
    # (medical sectors only).
    if is_medical:
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

    # 6. Contextual price follow-up: "how much is it?" after an item or
    # doctor was just discussed. Use the conversation history: find the
    # most recently mentioned catalog item or doctor and answer with its
    # real price from the DB, instead of a generic welcome.
    if history and any(k in q for k in ["سعر", "كشف", "كشفية", "قداش", "بكم", "ثمن", "تكلفة"]):
        try:
            catalog_view = db.get_catalog_view(db_path=db_path)
        except Exception:
            catalog_view = []
        try:
            all_doctors = db.get_all_doctors(db_path=db_path) if is_medical else []
        except Exception:
            all_doctors = []
        for turn in reversed(history):
            turn_norm = db.norm(turn.get("text", ""))
            for item in catalog_view:
                item_name = item.get("name", "")
                if item_name and db.norm(item_name) in turn_norm:
                    return (
                        f"أهلاً بك 🌸\n\n"
                        f"💰 *سعر {item_name}:* {item.get('price_lyd', 0)} د.ل.\n\n"
                        f"📍 *المقر:* {address}\n📞 *الاستقبال:* {phones}"
                    )
            for doc in all_doctors:
                doc_name = doc.get("name", "")
                if doc_name and db.norm(doc_name) in turn_norm:
                    fee = doc.get("consultation_fee")
                    if fee is not None:
                        return (
                            f"أهلاً بك 🌸\n\n"
                            f"💰 *سعر كشف {doc_name}:* {fee} د.ل.\n\n"
                            f"📍 *المقر:* {address}\n📞 *الاستقبال:* {phones}"
                        )
        # Fall through to the generic message if nothing was mentioned.

    # Default strictly grounded message
    return (
        f"مرحباً بك في خدمة العملاء الآلية لـ *{business_name}*{city_suffix} 🌸\n\n"
        f"يسعدني مساعدتك في معرفة الأسعار والتوفر، مواعيد العمل، أو موقع ومقر النشاط.\n\n"
        f"إذا كنت تسأل عن منتج أو خدمة معينة ولم تجدها، يرجى التواصل مباشرة مع الاستقبال على الأرقام:\n"
        f"📞 *{phones}*"
    )



def handle_customer_query(
    sender_id: str,
    query: str,
    channel: str = "simulator",
    db_path: Optional[str] = None,
) -> str:
    """
    Main entrypoint for 1:1 customer inquiries:
    1. Sector-aware guardrails (medical emergency bypass, commercial
       human handoff, clinical-advice refusal for medical sectors).
    2. Dynamic Real-Time DB Query for Libya time, live catalog, FAQs,
       and (medical sectors) the target day schedule with overrides.
    3. Multi-turn conversation context from persistent
       `conversation_history`, scoped to (sender_id, channel).
    4. Strict grounding with Zero Hallucination.
    5. Durable saving of user and model turns to `conversation_history`.
    """
    db_path = db_path or db.DB_PATH
    channel = channel or "simulator"
    business_profile = db.get_business_profile(db_path)
    time_ctx = get_libya_datetime_context()
    current_day = time_ctx.get("day_name", "الجمعة")

    # Step 1: Sector-aware guardrails (deterministic, before any LLM).
    guard = guardrails.evaluate_guardrails(query, business_profile)

    # 1a. Medical Level 1 emergency (medical sectors only): bypasses the
    # debouncer and the LLM completely.
    if guard.is_emergency and guard.immediate_response:
        db.add_conversation_history(sender_id, "user", query, db_path=db_path, channel=channel)
        db.add_conversation_history(sender_id, "model", guard.immediate_response, db_path=db_path, channel=channel)
        return guard.immediate_response

    # 1b. Commercial human handoff (all sectors): return the handoff
    # message and record it in the audit trail so the business sees it.
    if guard.needs_handoff and guard.immediate_response:
        db.add_conversation_history(sender_id, "user", query, db_path=db_path, channel=channel)
        db.add_conversation_history(sender_id, "model", guard.immediate_response, db_path=db_path, channel=channel)
        try:
            db.log_audit_trail(
                admin_sender="guardrails:handoff",
                raw_message=query,
                status_before={},
                status_after={"handoff_reason": guard.handoff_reason or "unknown", "channel": channel},
                confirmation_text=guard.immediate_response,
                db_path=db_path,
            )
        except Exception:
            pass
        return guard.immediate_response

    # 1c. Clinical advice / prescription requests must be refused
    # immediately, in every mode (medical sectors only).
    if guard.is_clinical_advice_prohibited and guard.immediate_response:
        db.add_conversation_history(sender_id, "user", query, db_path=db_path, channel=channel)
        db.add_conversation_history(sender_id, "model", guard.immediate_response, db_path=db_path, channel=channel)
        return guard.immediate_response

    # Step 2: Detect Target Day & Query Fresh Daily Schedule with Overrides
    # (medical sectors only; other sectors get an empty schedule).
    is_medical = guardrails.is_medical_sector(business_profile)
    target_day = detect_target_day(query, current_day)
    daily_schedule = (
        db.get_daily_schedule(target_day, db_path=db_path)
        if is_medical
        else {"day_name": target_day, "emergency_clinics": [], "followup_clinics": [], "overrides_applied": []}
    )
    catalog_view = db.get_catalog_view(db_path=db_path)
    faqs = db.get_business_faqs(db_path=db_path)

    # Step 3: Retrieve Persistent Chat History (last 6 turns, this channel)
    history = db.get_conversation_history(sender_id, limit=6, db_path=db_path, channel=channel)

    # Step 4: Build System Instruction with Real-time DB Context
    system_instruction = build_system_instruction(
        business_profile, catalog_view, daily_schedule, time_ctx, faqs
    )

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
        response_text = fallback_customer_answer(
            query, business_profile, daily_schedule, history=history, db_path=db_path
        )

    # Step 5: Persist Conversation Turns
    db.add_conversation_history(sender_id, "user", query, db_path=db_path, channel=channel)
    db.add_conversation_history(sender_id, "model", response_text, db_path=db_path, channel=channel)

    return response_text


# --- Backward-compatible aliases (used by patient_service.py shim) ---

def handle_patient_query(phone_number: str, query: str) -> str:
    """Legacy alias: a patient query is a customer query on WhatsApp."""
    return handle_customer_query(phone_number, query, channel="whatsapp")


def fallback_patient_answer(query: str, clinic_info: Dict[str, Any], daily_schedule: Dict[str, Any], history=None) -> str:
    """Legacy alias for the deterministic fallback responder."""
    return fallback_customer_answer(query, clinic_info, daily_schedule, history=history)
