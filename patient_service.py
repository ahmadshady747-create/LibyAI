"""
LibyAI Patient Reception Service (`patient_service.py`)

Handles 1:1 patient inquiries with:
- WhatsApp micro-copy formatting (short paragraphs, *bold* highlights, bullet points).
- Sliding 4-turn session context (15-minute rolling window per phone number).
- Dynamic real-time clinic knowledge injection (doctors, schedules, statuses, prices, Libya time).
- Clinical advice prohibition & triage integration.
- Actionable next steps (official in-person booking policy).
"""

import os
import json
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv

load_dotenv()

import db
import triage
from app.services.time_utils import get_libya_datetime_context

preferred_model = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
MODELS_CASCADE = [preferred_model, "gemini-3.5-flash", "gemini-3.6-flash", "gemini-3.1-flash-lite", "gemini-3-flash-preview"]
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


def build_system_instruction(clinic_info: Dict[str, str], doctors: List[Dict[str, Any]], services: List[Dict[str, Any]]) -> str:
    """Builds rich, dynamic reception prompt with live clinic state and Libyan time."""
    time_ctx = get_libya_datetime_context()
    clinic_name = clinic_info.get("name") or clinic_info.get("clinic_name", "مصحة الشفاء التخصصية")
    address = clinic_info.get("address", "طرابلس - طريق الشط")
    emergency_phone = clinic_info.get("emergency_phone", "091-0000000 / 021-3333333")
    reception_phone = clinic_info.get("reception_phone", "092-1111111")
    booking_policy = clinic_info.get("booking_policy", "الحجز بالحضور الشخصي المباشر لمكتب الاستقبال بدءاً من 8:00 صباحاً.")
    payment_methods = clinic_info.get("payment_methods", "نقداً (كاش)، بطاقات الدفع المصرفي (تداول، نمو)، والخدمات الإلكترونية (سداد، إدفع لي، موبي كاش) بنفس السعر النقدي وبدون أي عمولة إضافية.")
    insurance_companies = clinic_info.get("insurance_companies", "متعاقدون مع تأمين المدار، ليبيانا، الشركة المتحدة للتأمين، وتأمين شركة الكهرباء والنفط. كما نوفر فواتير إلكترونية معتمدة للمرضى التابعين لشركات أخرى للاسترداد المالي.")
    facilities_info = clinic_info.get("facilities_info", "قسم الطوارئ والمختبر متاحان 24 ساعة يومياً طيلة أيام الأسبوع (بما في ذلك الجمعة والعطلات). المصحة مجهزة بمصاعد طبية حديثة ومجهزة لكبار السن وحالات العظام.")

    # Doctor formatting
    status_arabic = {
        "available": "متواجد حسب الجدول المعتاد",
        "apologized": "معتذر اليوم (غير متواجد بالمصحة)",
        "delayed": "تأخير / تعديل موعد الحضور",
        "left": "أنهى كشوفات اليوم وغادر المصحة",
        "arrived": "وصل للعيادة ويباشر الكشوفات الآن",
        "booking_closed": "مكتمل العدد (تم إيقاف الحجز لليوم)"
    }

    doc_lines = []
    for d in doctors:
        st_desc = status_arabic.get(d["status"], d["status"])
        note = f" | ملاحظة اليوم: {d['daily_note']}" if d.get("daily_note") else ""
        doc_lines.append(
            f"• *{d['name']}* ({d['specialty']}) | المواعيد: {d['regular_schedule']} | الكشفية: {d['consultation_fee']} د.ل | الحالة: [{st_desc}]{note}"
        )
    doctors_block = "\n".join(doc_lines)

    # Services formatting
    svc_lines = []
    for s in services[:15]:
        inst = f" | إرشادات: {s['instructions']}" if s.get("instructions") else ""
        svc_lines.append(f"• [{s['category']}] *{s['name']}* | السعر: {s['price']} د.ل{inst}")
    services_block = "\n".join(svc_lines)

    return f"""
أنت "مساعد الاستقبال الرقمي" الرسمي لمصحة "{clinic_name}".
مهمتك: الرد على استفسارات المرضى والمراجعين عبر واتساب بلباقة فائقة ومودة وسرعة، مع تقديم معلومات دقيقة ومحدثة.

-------------------------
[قواعد الصياغة وتنسيق رسائل واتساب (WhatsApp Micro-Copy)]
-------------------------
1. لا تكتب فقرات طويلة أو كتل نصية مكدسة. اجعل الردود قصيرة وواضحة وسهلة القراءة على شاشة الهاتف.
2. استخدم تنسيق واتساب بذكاء:
   - الكلمات والمواعيد والأسعار المهمة بين نجوم لتبدو عريضة مثل: *د. عبدالله ديهوم* أو *40 د.ل*.
   - استخدم النقاط (•) لعرض الخيارات والأسعار بوضوح.
3. اختم دائماً رسالتك بتوجيه عملي واضح أو تذكير بآلية الحجز الرسمية.

-------------------------
[الهوية ونبرة التحدث المحلية]
-------------------------
- لغة عربية ميسرة ومهذبة جداً مطعمة باللباقة والترحيب الليبي اللطيف (مثل: "أهلاً بك"، "لا بأس عليكم إن شاء الله"، "طهور وسلامتكم").
- تحدث بصفتك موظف الاستقبال بالمصحة؛ إياك وذكر أنك ذكاء اصطناعي أو نموذج لغوي أو روبوت.

-------------------------
[السياق الزمني المحدث لليوم في ليبيا (طرابلس)]
-------------------------
- {time_ctx['summary']}
- عند سؤال المريض هل الطبيب متاح "توا" أو "الآن":
  * قارن توقيت ليبيا الحالي بساعات دوام الطبيب. إذا كان خارج دوامه لليوم (مثلاً وقت دوامه انتهى، أو لم يحن بعد)، وضّح ذلك واذكر موعده القادم.
  * إذا كان الطبيب مسجلاً كـ "غادر العيادة"، وضّح أنه أنهى كشوفات اليوم وغادر المصحة.
  * إذا كان الطبيب "مكتمل العدد"، وضّح أن أرقام الحجز اكتملت وتم إيقاف الحجز لليوم.
  * إذا كان "معتذراً"، وضّح صراحة أنه معتذر عن موعد اليوم.

-------------------------
[قواعد الأمان الطبي والتوجيه السريري]
-------------------------
1. يمنع منعاً باتاً تشخيص الأمراض أو اقتراح أدوية وجرعات أو قراءة نتائج تحاليل.
   - إذا طلب المريض دواء أو علاجاً، اعتذر بلطف ووضح أنك في الاستقبال ولا يمكنك وصف أدوية لحرص المصحة على سلامته، ودله على الطبيب المختص للكشف، أو قسم الطوارئ إذا كانت الحالة مستعجلة.
2. وجه المريض بمرونة للتخصص المناسب حسب شكواه (مثلاً: ألم جنب ومسالك للمسالك البولية، آلام مفاصل للعظام، حرارة ومغص أطفال للأطفال... إلخ) واذكر له اسم طبيب المصحة المتاح وسعره.
3. سياسة الحجز: أنت لا تحجز مواعيد ولا تسجل أسماء عبر المحادثة؛ اشرح دائماً أن الحجز يتم بالحضور الشخصي المباشر: "{booking_policy}".

-------------------------
[إرشادات الأسئلة الشائعة في ليبيا (الدفع، التأمين، المرافق)]
-------------------------
1. طرق الدفع المعتمدة:
   - عند سؤال المريض عن الدفع (كاش، تداول، سداد، بطاقة): وضّح له أن المصحة تقبل: {payment_methods}
2. شركات التأمين الصحي:
   - عند سؤال المريض عن التأمين والشركات: وضح له بدقة: {insurance_companies}
3. المرافق ودوام الجمعة والعطلات:
   - وضح له: {facilities_info}
4. التحاليل أو الأطباء غير المسجلين:
   - إذا سأل المريض عن تحليل نادر أو تخصص غير مسجل بالقائمة، اعتذر بلطف وأخبره أنه غير مدرج حالياً، وانصحه بالاتصال برقم الاستقبال ({reception_phone}) للتأكد بدقة، وإياك وتخمين أسعار من عندك.

-------------------------
[بيانات المصحة المحدثة لحظياً]
-------------------------
- اسم المصحة: {clinic_name}
- العنوان: {address}
- هاتف الطوارئ والإسعاف (24 ساعة): {emergency_phone}
- هاتف الاستقبال والمتابعة: {reception_phone}
- آلية الحجز المعتمدة: {booking_policy}
- طرق الدفع: {payment_methods}
- التأمين الصحي: {insurance_companies}
- المرافق: {facilities_info}

جدول الأطباء وحالة اليوم:
{doctors_block}

أبرز التحاليل والخدمات والأسعار:
{services_block}
"""


def fallback_patient_answer(query: str, clinic_info: Dict[str, str], doctors: List[Dict[str, Any]], services: List[Dict[str, Any]]) -> str:
    """Deterministic fallback responder in case of LLM connectivity issues."""
    q = query.lower()

    # 1. Payment Methods
    if any(k in q for k in ["تداول", "نمو", "سداد", "ادفع لي", "إدفع لي", "موبي كاش", "كاش", "نقدا", "دفع", "بطاقة"]):
        pm = clinic_info.get("payment_methods", "نقداً (كاش)، بطاقات الدفع المصرفي (تداول، نمو)، والخدمات الإلكترونية (سداد، إدفع لي، موبي كاش) بنفس السعر النقدي وبدون أي عمولة إضافية.")
        return (
            "أهلاً بحضرتك في مصحة الشفاء التخصصية 🌸\n\n"
            "💳 *طرق الدفع المعتمدة بالمصحة:*\n"
            f"{pm}\n\n"
            "يسعدنا استقبالك في أي وقت، ولا بأس عليك إن شاء الله."
        )

    # 2. Insurance Companies
    if any(k in q for k in ["تأمين", "تامين", "ضمان", "ليبيانا", "المدار", "شركة تأمين", "استرداد"]):
        ins = clinic_info.get("insurance_companies", "متعاقدون مع تأمين المدار، ليبيانا، الشركة المتحدة للتأمين، وتأمين شركة الكهرباء والنفط. كما نوفر فواتير إلكترونية معتمدة للاسترداد المالي.")
        return (
            "أهلاً بحضرتك 🌸\n\n"
            "🏥 *خدمات التأمين الصحي المعتمدة بالمصحة:*\n"
            f"{ins}\n\n"
            "لأي تفاصيل حول الإجراءات، يرجى التوجه لمكتب التأمين والاستقبال بالطابق الأرضي."
        )

    # 3. Facilities / Working Hours / Friday
    if any(k in q for k in ["جمعة", "عطلة", "مصعد", "اصنصير", "طابق", "طوارئ", "دوام"]):
        fac = clinic_info.get("facilities_info", "قسم الطوارئ والمختبر متاحان 24 ساعة يومياً (بما في ذلك الجمعة والعطلات). المصحة مجهزة بمصاعد طبية حديثة لكبار السن وحالات العظام.")
        return (
            "أهلاً بحضرتك 🌸\n\n"
            "ℹ️ *المرافق والدوام العام بالمصحة:*\n"
            f"{fac}\n\n"
            "نحن دائماً في خدمتكم على مدار الساعة."
        )

    # 4. Booking policy
    if any(k in q for k in ["حجز", "نحجز", "موعد", "قص رقم", "نبي نجي"]):
        policy = clinic_info.get("booking_policy", "الحجز يتم بالحضور الشخصي المباشر لمكتب الاستقبال بالطابق الأرضي بدءاً من الساعة 08:00 صباحاً.")
        return (
            "أهلاً بحضرتك في مصحة الشفاء التخصصية 🌸\n\n"
            "📋 *نظام وآلية الحجز المعتمدة بالمصحة:*\n"
            f"{policy}\n\n"
            "⚠️ نلفت عنايتكم بأنه لا يتوفر حجز مسبق عبر الهاتف أو الرسائل لضمان عدالة وأسبقية الحضور.\n\n"
            "هل تود الاستفسار عن كشفية أو موعد طبيب معين اليوم؟"
        )

    # Doctor search
    matched_doc = db.find_doctor_fuzzy(name_query=query, specialty_query=query)
    if matched_doc:
        st = matched_doc["status"]
        st_text = "متواجد حسب الجدول المعتاد ✅"
        if st == "apologized":
            st_text = "معتذر اليوم وغير متواجد ❌"
        elif st == "left":
            st_text = "أنهى كشوفات اليوم وغادر المصحة 🚪"
        elif st == "booking_closed":
            st_text = "مكتمل العدد وتم إيقاف الحجز لليوم ⛔"
        elif st == "arrived":
            st_text = "وصل للعيادة ويستقبل الحالات الآن 🩺"
        elif st == "delayed":
            st_text = f"تعديل موعد: {matched_doc['daily_note']} ⏰"

        return (
            f"أهلاً بك 🌸 إليك بيانات الطبيب:\n\n"
            f"👨‍⚕️ *{matched_doc['name']}* ({matched_doc['specialty']})\n"
            f"📅 *المواعيد الرسمية:* {matched_doc['regular_schedule']}\n"
            f"💰 *الكشفية:* *{matched_doc['consultation_fee']} د.ل*\n"
            f"🔔 *حالة اليوم:* {st_text}\n\n"
            f"📍 *نظام الحجز:* الحضور الشخصي لمكتب الاستقبال (أسبقية الحضور)."
        )

    # Service search
    matched_svc = db.find_service_fuzzy(query)
    if matched_svc:
        inst = f"\n📌 *الإرشادات:* {matched_svc['instructions']}" if matched_svc.get("instructions") else ""
        return (
            f"أهلاً بك 🌸 تفاصيل الفحص المطلوب:\n\n"
            f"🔬 *{matched_svc['name']}* ({matched_svc['category']})\n"
            f"💰 *السعر:* *{matched_svc['price']} د.ل*{inst}\n\n"
            f"المختبر وقسم الأشعة يعملان على مدار 24 ساعة لاستقبالكم."
        )

    return (
        "مرحباً بك في خدمة الاستقبال الذكية لمصحة الشفاء التخصصية 🌸\n\n"
        "يسعدني مساعدتك في الإجابة عن:\n"
        "• مواعيد وأسعار كشوفات الأطباء المتواجدين اليوم.\n"
        "• التوجيه للتخصص والعيادة المناسبة لحالتك.\n"
        "• أسعار التحاليل والأشعة وشروط الصيام والتحضير.\n"
        "• آلية الحجز وعنوان المصحة وأرقام الطوارئ.\n\n"
        "كيف يمكنني خدمتك اليوم؟"
    )


def handle_patient_query(phone_number: str, query: str) -> str:
    """
    Main entrypoint for 1:1 patient inquiries:
    1. Evaluates multi-tier triage (Red Flags & Clinical Advice Guardrails).
    2. Retrieves 4-turn sliding conversation context (within 15 minutes).
    3. Queries Gemini 2.5 Flash with freshly injected clinic knowledge and sliding history.
    4. Persists the interaction into `conversation_sessions`.
    """
    clinic_info = db.get_clinic_info()
    doctors = db.get_all_doctors()
    services = db.get_all_services()

    # Step 1: Multi-Tier Triage
    triage_result = triage.evaluate_triage(query, clinic_info)
    if triage_result.is_emergency and triage_result.immediate_response:
        # Fast-path bypass LLM
        db.save_conversation_turn(phone_number, "user", query)
        db.save_conversation_turn(phone_number, "model", triage_result.immediate_response)
        return triage_result.immediate_response

    # Step 2: Retrieve Sliding Context (last 4 turns / 15 mins)
    history = db.get_sliding_session_history(phone_number, max_turns=4, ttl_minutes=15)

    # Step 3: Build Dynamic Prompt
    system_instruction = build_system_instruction(clinic_info, doctors, services)

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

        contents = sanitized_turns

        for model_name in MODELS_CASCADE:
            try:
                response = gemini_client.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config={
                        "system_instruction": system_instruction,
                        "temperature": 0.3,
                    }
                )
                if response and response.text:
                    response_text = response.text.strip()
                    break
            except Exception as e:
                continue

    # If LLM generation failed or no key, use fallback
    if not response_text:
        response_text = fallback_patient_answer(query, clinic_info, doctors, services)

    # Step 4: Persist Conversation Turns for Rolling Session Memory
    db.save_conversation_turn(phone_number, "user", query)
    db.save_conversation_turn(phone_number, "model", response_text)

    return response_text
