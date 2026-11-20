import os
import json
import re
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from app.config import settings
from app.services import db_service
from app.services.arabic_utils import is_fuzzy_match
from app.services.time_utils import get_libya_datetime_context

# Initialize Gemini Client if key exists
gemini_client = None
_gemini_key = settings.GEMINI_API_KEY or os.environ.get("GEMINI_KEY") or os.environ.get("GEMINI_API_KEY")
if _gemini_key:
    try:
        from google import genai
        from google.genai import types
        gemini_client = genai.Client(
            api_key=_gemini_key,
            http_options=types.HttpOptions(
                timeout=45000,
                retry_options=types.HttpRetryOptions(attempts=1)
            )
        )
    except Exception as e:
        print(f"Warning: Could not initialize Gemini client: {e}")



from typing import List

class IngestedDoctor(BaseModel):
    name: str = Field(description="اسم الطبيب، مثلا: د. عماد المهدوي")
    specialty: str = Field(description="التخصص الطبي")
    regular_schedule: str = Field(description="أيام وساعات الدوام المعتادة")
    consultation_fee: float = Field(default=40.0, description="سعر الكشف بالدينار")
    room_number: Optional[str] = Field(default="غير محدد", description="رقم العيادة أو الدور")


class IngestedService(BaseModel):
    category: str = Field(default="مختبر", description="القسم: مختبر, أشعة, طوارئ, كشوفات")
    name: str = Field(description="اسم التحليل أو الفحص")
    price: float = Field(default=20.0, description="السعر بالدينار")
    prep_instructions: Optional[str] = Field(default="لا توجد شروط خاصة", description="إرشادات الصيام والتحضير")
    availability: Optional[str] = Field(default="متاح 24 ساعة", description="أوقات التوفر")


class IngestedClinicPayload(BaseModel):
    doctors: List[IngestedDoctor] = Field(default_factory=list)
    services: List[IngestedService] = Field(default_factory=list)


class AdminUpdateExtraction(BaseModel):
    action: str = Field(description="Action type: DOCTOR_LEFT, DOCTOR_ARRIVED, BOOKING_CLOSED, DOCTOR_EXTENDED, DOCTOR_APOLOGY, DOCTOR_DELAY, DOCTOR_AVAILABLE, UPDATE_DOCTOR_FEE, UPDATE_SERVICE_PRICE, GENERAL_NOTE, CASUAL_CHATTER, UNKNOWN")
    doctor_name: Optional[str] = Field(default=None, description="Doctor name if applicable")
    specialty: Optional[str] = Field(default=None, description="Specialty like عظام, أطفال, باطنة")
    new_time: Optional[str] = Field(default=None, description="New attendance time, departure time, or extension time")
    new_price: Optional[float] = Field(default=None, description="New price or fee if price change")
    service_name: Optional[str] = Field(default=None, description="Service or lab test name if price change")
    note: Optional[str] = Field(default="", description="Summary note of the update in Arabic")
    confirmation_text: str = Field(description="Crisp polite Arabic confirmation message for the staff in Libyan clinic tone")


def fallback_admin_parser(text: str) -> Dict[str, Any]:
    """Fallback rule-based parser in case Gemini API key is not configured or offline."""
    clean = text.replace("@Bot", "").replace("@bot", "").replace("@بـوت", "").replace("@مساعد", "").strip()
    time_ctx = get_libya_datetime_context()

    # Find doctor if present in text
    doctor = db_service.find_doctor_fuzzy(name_query=clean, specialty_query=clean)
    doc_name = doctor.name if doctor else "الطبيب"
    spec = doctor.specialty if doctor else ""

    # 1. Doctor Left / Departed (غادر / روح / طلع / كمل / خلص / مشى)
    if any(k in clean for k in ["غادر", "غادرت", "روح", "روحت", "روّح", "روّحت", "طلع", "طلعت", "كمل", "كملت", "أنهى", "أنهت", "خلص", "خلصت", "مشى", "مشات"]):
        time_now = time_ctx["time_arabic"]
        return {
            "action": "DOCTOR_LEFT",
            "doctor_name": doc_name,
            "specialty": spec,
            "new_time": time_now,
            "new_price": None,
            "service_name": None,
            "note": f"غادر العيادة لليوم ({time_now})",
            "confirmation_text": f"تم التحديث: {doc_name} ({spec}) غادر العيادة لليوم وأنهى كشوفاته."
        }

    # 2. Doctor Arrived (وصل / باشر / قاعد توا / بدأ يستقبل)
    if any(k in clean for k in ["وصل", "وصلت", "قاعد توا", "قاعدة توا", "بدأ يستقبل", "بدت تستقبل", "باشر", "في العيادة"]):
        time_now = time_ctx["time_arabic"]
        return {
            "action": "DOCTOR_ARRIVED",
            "doctor_name": doc_name,
            "specialty": spec,
            "new_time": time_now,
            "new_price": None,
            "service_name": None,
            "note": f"وصل للعيادة ويباشر استقبال الكشوفات ({time_now})",
            "confirmation_text": f"تم التحديث: {doc_name} ({spec}) وصل للعيادة ويباشر استقبال الحالات حالياً."
        }

    # 3. Booking Closed / Capacity Reached (اكتفى / اكتمل العدد / قفل الحجز / وقفوا الحجز)
    if any(k in clean for k in ["اكتفى", "اكتفت", "اكتفوا", "اكتمل العدد", "قفل الحجز", "قفلوا الحجز", "وقف الحجز", "وقفوا الحجز", "توقف الحجز", "سد", "فل"]):
        return {
            "action": "BOOKING_CLOSED",
            "doctor_name": doc_name,
            "specialty": spec,
            "new_time": None,
            "new_price": None,
            "service_name": None,
            "note": "اكتمل العدد وتم إيقاف الحجز لليوم",
            "confirmation_text": f"تم التحديث: {doc_name} ({spec}) مكتمل العدد، تم إيقاف حجز أرقام جديدة لليوم."
        }

    # 4. Hours Extension (تمديد / مكمل للساعة / قاعد لعند)
    if any(k in clean for k in ["تمديد", "مدد", "مددت", "مكمل للساعة", "مكملة للساعة", "قاعد لعند", "قاعدة لعند"]):
        time_match = re.search(r"(\d{1,2}(?::\d{2})?)", clean)
        time_str = f"الساعة {time_match.group(1)}" if time_match else "وقت إضافي"
        return {
            "action": "DOCTOR_EXTENDED",
            "doctor_name": doc_name,
            "specialty": spec,
            "new_time": time_str,
            "new_price": None,
            "service_name": None,
            "note": f"تمديد دوام اليوم حتى {time_str}",
            "confirmation_text": f"تم التحديث: تم تمديد دوام {doc_name} ({spec}) لليوم حتى {time_str}."
        }

    # 5. Doctor Apology (اعتذر / مش حيكون متواجد / غياب / مش جاي / مسافر)
    if any(k in clean for k in ["اعتذر", "اعتذرت", "مش حيكون متواجد", "مش حتكون متواجدة", "غياب", "مش جاي", "مش جاية", "مسافر"]):
        return {
            "action": "DOCTOR_APOLOGY",
            "doctor_name": doc_name,
            "specialty": spec,
            "new_time": None,
            "new_price": None,
            "service_name": None,
            "note": "معتذر عن الحضور اليوم",
            "confirmation_text": f"تم التحديث: {doc_name} ({spec}) غير متواجد اليوم (اعتذار)."
        }

    # 6. Delay / Time change (حيبدأ الساعة / تأخير / حتبدأ / متأخر)
    if any(k in clean for k in ["حيبدأ", "حتبدأ", "تأخير", "متأخر", "متأخرة", "الساعة", "بدل"]):
        time_match = re.search(r"(\d{1,2}(?::\d{2})?)", clean)
        time_str = time_match.group(1) if time_match else "الموعد الجديد"
        return {
            "action": "DOCTOR_DELAY",
            "doctor_name": doc_name,
            "specialty": spec,
            "new_time": time_str,
            "new_price": None,
            "service_name": None,
            "note": clean,
            "confirmation_text": f"تم التحديث: {doc_name} ({spec}) تم تعديل موعده اليوم: {clean}."
        }

    # 7. Price change (كشفية / سعر / دينار / صارت)
    if any(k in clean for k in ["كشفية", "سعر", "صار", "صارت", "دينار"]):
        price_match = re.search(r"(\d+(?:\.\d+)?)", clean)
        new_price = float(price_match.group(1)) if price_match else None

        if doctor and new_price:
            return {
                "action": "UPDATE_DOCTOR_FEE",
                "doctor_name": doctor.name,
                "specialty": doctor.specialty,
                "new_time": None,
                "new_price": new_price,
                "service_name": None,
                "note": f"تعديل كشفية {doctor.name} إلى {new_price} د.ل",
                "confirmation_text": f"تم التحديث: تم تعديل كشفية {doctor.name} لتصبح {new_price} دينار."
            }

        service = db_service.find_service_fuzzy(clean)
        if service and new_price:
            return {
                "action": "UPDATE_SERVICE_PRICE",
                "doctor_name": None,
                "specialty": None,
                "new_time": None,
                "new_price": new_price,
                "service_name": service.name,
                "note": f"تعديل سعر {service.name} إلى {new_price} د.ل",
                "confirmation_text": f"تم التحديث: تم تعديل سعر {service.name} إلى {new_price} دينار."
            }

    # 8. Doctor Available (متواجد / أكد حضوره)
    if any(k in clean for k in ["متواجد", "حيكون متواجد", "أكد حضوره"]):
        return {
            "action": "DOCTOR_AVAILABLE",
            "doctor_name": doc_name,
            "specialty": spec,
            "new_time": None,
            "new_price": None,
            "service_name": None,
            "note": "متواجد اليوم",
            "confirmation_text": f"تم التحديث: {doc_name} ({spec}) متواجد اليوم حسب الجدول."
        }

    # 9. Casual Chatter (سالفة / دردشة عادية)
    if any(k in clean for k in ["شن جو", "كيف الحال", "صباح الخير", "مساء الخير", "السلام عليكم", "جمعة مباركة", "شن أخبار"]):
        return {
            "action": "CASUAL_CHATTER",
            "doctor_name": None,
            "specialty": None,
            "new_time": None,
            "new_price": None,
            "service_name": None,
            "note": "",
            "confirmation_text": ""
        }

    return {
        "action": "GENERAL_NOTE",
        "doctor_name": None,
        "specialty": None,
        "new_time": None,
        "new_price": None,
        "service_name": None,
        "note": clean,
        "confirmation_text": f"تم استلام الملاحظة وحفظها: {clean}"
    }


def parse_admin_update(message_text: str) -> Dict[str, Any]:
    """Uses instant pattern matching or Gemini Structured Outputs to extract database mutations."""
    # Fast path: instant rule-based parsing for standard staff updates
    fast_result = fallback_admin_parser(message_text)
    if fast_result.get("action") not in ["GENERAL_NOTE", "UNKNOWN"]:
        return fast_result

    global gemini_client
    if not gemini_client:
        return fast_result

    time_ctx = get_libya_datetime_context()
    doctors = db_service.get_all_doctors()
    doctors_summary = "\n".join([f"- {d.name} ({d.specialty}) | العيادة: {d.room_number} | كشفية: {d.consultation_fee} د.ل" for d in doctors])

    prompt = f"""
أنت مساعد ذكي فائق الدقة متخصص في إدارة وتحديث بيانات مصحة طبية في ليبيا عبر واتساب.
المستخدم هو موظف استقبال أو مدير المصحة، وقام بكتابة هذا التحديث باللغة العربية أو اللهجة الليبية:
"{message_text}"

-------------------------
سياق التوقيت الحالي في ليبيا (طرابلس):
{time_ctx['summary']}

قائمة الأطباء المسجلين بالمصحة:
{doctors_summary}
-------------------------

المطلوب:
قم بتحليل المعنى واستخراج البيانات في هيئة JSON مطابق لـ AdminUpdateExtraction:
- طابق الطبيب وتخصصه بدقة من القائمة أعلاه (مثال: "دكتور العظام" -> د. عبد الله ديهوم، "دكتور مسالك" -> د. سامي النور، "دكتور علي" -> د. سامي النور، "دكتور باطنة" -> د. أحمد الزليطني).
- حدد نوع الإجراء (action) بدقة بالغة:
  * DOCTOR_LEFT: الطبيب غادر العيادة أو أنهى كشوفاته لليوم (مثلاً: روح، غادر، كمل حالاته، مشى، طلع).
  * DOCTOR_ARRIVED: الطبيب وصل للعيادة ويباشر استقبال الحالات (مثلاً: وصل، قاعد في العيادة توا، باشر).
  * BOOKING_CLOSED: تم إيقاف الحجز أو اكتمل العدد للطبيب لليوم (مثلاً: قفلوا الحجز، اكتفوا بالعدد، سد، فل).
  * DOCTOR_EXTENDED: تمديد ساعات دوام الطبيب لليوم (مثلاً: مكمل لعند الساعة 3، مدد دوامه).
  * DOCTOR_APOLOGY: الطبيب اعتذر عن موعد اليوم ولن يأتي (مثلاً: اعتذر، مش جاي، غايب، مسافر).
  * DOCTOR_DELAY: تأخير موعد حضور الطبيب (مثلاً: حيتأخر، حيبدأ الساعة 5).
  * DOCTOR_AVAILABLE: تأكيد تواجد الطبيب.
  * UPDATE_DOCTOR_FEE: تعديل سعر كشفية طبيب.
  * UPDATE_SERVICE_PRICE: تعديل سعر تحليل أو فحص.
  * GENERAL_NOTE: ملاحظة عامة أو إعلان إداري عن المصحة.
  * CASUAL_CHATTER: دردشة عادية أو سالفة لا تحتوي على أي تحديث.

- اكتب نص تأكيد رسمي ومختصر وواضح باللهجة المهذبة في confirmation_text ليتم إرساله للموظف.
"""

    models_to_try = [settings.GEMINI_MODEL, "gemini-3.1-flash-lite", "gemini-3.5-flash-lite", "gemini-flash-lite-latest"]
    seen = set()
    models_to_try = [m for m in models_to_try if not (m in seen or seen.add(m))]

    for model_name in models_to_try:
        try:
            response = gemini_client.models.generate_content(
                model=model_name,
                contents=prompt,
                config={
                    "response_mime_type": "application/json",
                    "response_schema": AdminUpdateExtraction,
                    "temperature": 0.1,
                }
            )
            if response and response.text:
                return json.loads(response.text)
        except Exception as e:
            print(f"Gemini API Error in parse_admin_update with {model_name}: {e}")
            continue

    return fallback_admin_parser(message_text)



def fallback_patient_responder(query: str, context: str) -> str:
    """Intelligent fallback responder with strict guardrails when offline or no API key."""
    q = query.strip().lower()

    # 1. Critical Emergency Guardrail (فقط الحالات الحرجة الحقيقية - تجنب الكلمات المشتركة مثل 'سم')
    critical_phrases = ["نزيف حاد", "جلطة", "ألم حاد في الصدر", "ألم شديد في الصدر", "ضيق تنفس شديد", "فقدان وعي", "غيبوبة", "تشنج حاد", "تسمم حاد", "حادث سير", "حادث خطير"]
    if any(phrase in q for phrase in critical_phrases):
        return (
            "🚨 **تنبيه عاجل وطارئ:**\n"
            "الأعراض المذكورة قد تشير إلى حالة حرجة تتطلب تدخلاً طبياً فورياً.\n"
            "يرجى التوجه بأسرع وقت إلى **قسم الإسعاف والطوارئ** بالمصحة (متاح 24 ساعة).\n\n"
            "📞 أرقام سيارات الإسعاف والطوارئ الفورية:\n"
            "091-0000000 / 021-3333333\n"
            "📍 العنوان: طرابلس - طريق الشط بالقرب من جزيرة الميناء."
        )

    # 2. Medical Triage & Specialty Guidance (التوجيه والتصنيف للتخصص الأنسب)
    triage_urology = ["مسالك", "حرقان بول", "حرقان في البول", "وجع في جنبي", "ألم جنبي", "مغص كلوي", "حصوة", "كلى"]
    triage_ortho = ["عظام", "مفصل", "مفاصل", "ركبة", "ركبتي", "فقرات", "كسر", "التواء"]
    triage_ped = ["طفلي", "ولدي", "بنتي", "رضيع", "حرارته", "مسخن"]

    is_routing_query = any(k in q for k in ["نمشي لمن", "أي دكتور", "أفضل دكتور", "أحسن دكتور", "أي عيادة", "تخصص", "ولا مسالك", "أم مسالك", "أم باطنة"])

    if any(k in q for k in triage_urology) or (is_routing_query and "مسالك" in q):
        matched_docs = [d for d in db_service.get_all_doctors() if "مسالك" in d.specialty or "باطنة" in d.specialty]
        doc_info = f"ولدينا اليوم د. {matched_docs[0].name} ({matched_docs[0].specialty}) - كشفية {matched_docs[0].consultation_fee} د.ل." if matched_docs else ""
        return (
            "ألف سلامة عليك ولا بأس عليك إن شاء الله 🌸\n\n"
            "بخصوص حالتك، التخصص الأنسب هو **عيادة المسالك البولية** أو **عيادة الباطنة العامة** للكشف والاطمئنان.\n"
            f"{doc_info}\n\n"
            "يسعدنا استقبالك في المصحة، ونسأل الله لك دوام العافية."
        )

    if any(k in q for k in triage_ortho):
        matched_docs = [d for d in db_service.get_all_doctors() if "عظام" in d.specialty]
        doc_info = f"ولدينا في المصحة د. {matched_docs[0].name} ({matched_docs[0].specialty}) - مواعيده: {matched_docs[0].regular_schedule}." if matched_docs else ""
        return (
            "ألف سلامة عليك وما تشوف شر 🌸\n\n"
            "لآلام المفاصل والركبة والظهر، الأنسب دائماً مراجعة **عيادة جراحة العظام والمفاصل**.\n"
            f"{doc_info}\n\n"
            "تفضل بزيارتنا في مكتب الاستقبال لتنسيق كشفك."
        )

    # 3. Explicit Medication Prescription Guardrail (حظر وصف الأدوية بالاسم أو الجرعات)
    med_keywords = ["دواء", "مسكن", "مضاد", "حبوب", "وصفة", "شن ناخذ دواء", "شن ناخذ علاج", "علاج سريع"]
    if any(k in q for k in med_keywords):
        return (
            "أهلاً بك، وسلامتك ألف سلامة وما تشوف شر إن شاء الله 🌸\n\n"
            "بصفتي في الاستقبال، لا يمكنني تقديم استشارات أو وصف أدوية لحرصنا على سلامتكم. يمكنك مراجعة الطبيب المختص بالمصحة لتلقي الفحص والعلاج المناسب، أو زيارة قسم الطوارئ إذا كانت الحالة مستعجلة."
        )

    # 4. Booking inquiry
    if any(k in q for k in ["حجز", "نحجز", "موعد", "قص رقم", "نبي نجي"]):
        return (
            "أهلاً بحضرتك في مصحة الشفاء التخصصية 🌸\n\n"
            "📋 **آلية ونظام الحجز المعتمدة بالمصحة:**\n"
            "الحجز يتم **بالحضور الشخصي المباشر** لمكتب الاستقبال بالطابق الأرضي بدءاً من الساعة 8:00 صباحاً (نظام أسبقية الحضور).\n"
            "⚠️ نود التنويه بأنه لا يتوفر حجز مسبق عبر الهاتف أو الرسائل لضمان انتظام الكشوفات.\n\n"
            "هل تود الاستعلام عن جدول طبيب أو تخصص معين اليوم؟"
        )

    # 5. Lab / Test Preparation
    if any(k in q for k in ["سكر", "صائم", "تحليل", "فحص", "سونار", "أشعة", "صيام"]):
        matched_services = [s for s in db_service.get_all_services() if is_fuzzy_match(s.name, query) or is_fuzzy_match(s.category, query)]
        if matched_services:
            res = "أهلاً بك 🌸 إليك تفاصيل وإرشادات الفحص:\n\n"
            for s in matched_services[:3]:
                res += f"🔬 **{s.name}**\n"
                res += f"💰 السعر: {s.price} د.ل\n"
                res += f"⏰ التوفر: {s.availability}\n"
                if s.prep_instructions:
                    res += f"📌 الإرشادات: {s.prep_instructions}\n"
                res += "\n"
            return res.strip()

    # 6. Doctor inquiry
    doctors = db_service.get_all_doctors()
    matched_docs = [d for d in doctors if is_fuzzy_match(d.name, query) or is_fuzzy_match(d.specialty, query)]
    if matched_docs:
        res = "أهلاً بحضرتك 🌸 إليك بيانات الطبيب المحدّثة لحظياً:\n\n"
        for d in matched_docs:
            status_text = "متواجد حسب موعده المعتاد ✅"
            if d.today_status == "apologized":
                status_text = "⚠️ **معتذر اليوم وغير متواجد بالمصحة**"
            elif d.today_status == "left":
                status_text = "🚪 **أنهى كشوفاته لليوم وغادر المصحة**"
            elif d.today_status == "booking_closed":
                status_text = "⛔ **اكتمل العدد وتم إيقاف الحجز لليوم**"
            elif d.today_status == "arrived":
                status_text = "🩺 **وصل للعيادة ويستقبل الحالات الآن**"
            elif d.today_status == "delayed":
                status_text = f"⏰ **تعديل وقت:** {d.today_note}"
            
            res += f"👨‍⚕️ **{d.name}** ({d.specialty})\n"
            res += f"📍 {d.room_number}\n"
            res += f"📅 المواعيد الرسمية: {d.regular_schedule}\n"
            res += f"💰 الكشفية: {d.consultation_fee} د.ل\n"
            res += f"🔔 **حالة اليوم:** {status_text}\n"
            if d.today_note and d.today_status not in ["delayed", "left"]:
                res += f"📝 ملاحظة: {d.today_note}\n"
            res += "\n"
        return res.strip()

    # Default fallback welcome
    return (
        "مرحباً بك في خدمة الاستعلامات الذكية لمصحة الشفاء التخصصية 🌸\n"
        "أنا هنا لمساعدتك على مدار 24 ساعة. يمكنك الاستفسار عن:\n"
        "• جدول الأطباء المتواجدين اليوم وأسعار الكشوفات.\n"
        "• التوجيه للتخصص والعيادة الأنسب لحالتك وأعراضك.\n"
        "• أسعار التحاليل والأشعة وشروط التحضير (مثل ساعات الصيام).\n"
        "• عنوان المصحة وأرقام الطوارئ والإسعاف.\n"
        "• آلية الحجز المعتمدة بالمصحة.\n\n"
        "كيف يمكنني خدمتك اليوم؟"
    )


def generate_patient_response(user_message: str, chat_history: Optional[list] = None) -> str:
    """
    Patient inquiries are answered by the legacy patient_service, by
    design (see ARCHITECTURE.md). That path owns the triage guardrails,
    the clinical-advice refusal, and the offline fallback. Do NOT add a
    second Gemini patient path here: an earlier version had one after
    this return statement, unreachable, which only misled readers about
    which path actually answers patients.
    """
    import patient_service
    return patient_service.handle_patient_query("simulator_patient", user_message)


def ingest_clinic_data_with_ai(
    raw_text: Optional[str] = None,
    file_bytes: Optional[bytes] = None,
    filename: Optional[str] = None,
    mime_type: Optional[str] = None
) -> Dict[str, Any]:
    """
    Multimodal AI Data Ingestion:
    Accepts:
    1. Raw text (WhatsApp messages, notes, pasted lists).
    2. Copied spreadsheets or tables (TSV, CSV, Markdown, Tab-separated).
    3. Uploaded Excel files (.xlsx, .xls) parsed via pandas/openpyxl.
    4. Uploaded CSV files.
    5. Uploaded PDF files (.pdf) with direct text extraction and fallback to Gemini PDF vision.
    6. Uploaded images (.png, .jpg, .jpeg, .webp) sent directly to Gemini multimodal vision.
    """
    global gemini_client
    if not gemini_client:
        _k = settings.GEMINI_API_KEY or os.environ.get("GEMINI_KEY") or os.environ.get("GEMINI_API_KEY")
        if _k:
            try:
                from google import genai
                gemini_client = genai.Client(api_key=_k)
            except Exception:
                pass
        if not gemini_client:
            return {"success": False, "error": "يتطلب الإدخال الذكي تفعيل مفتاح GEMINI_API_KEY"}

    from google.genai import types
    import io

    extracted_text_from_file = ""
    multimodal_parts = []

    ext = (filename.split(".")[-1].lower() if filename and "." in filename else "")

    if file_bytes:
        # 1. Excel files (.xlsx, .xls)
        if ext in ["xlsx", "xls"]:
            try:
                import pandas as pd
                excel_file = io.BytesIO(file_bytes)
                sheets = pd.read_excel(excel_file, sheet_name=None)
                sheets_str = []
                for sheet_name, df in sheets.items():
                    sheets_str.append(f"=== ورقة عمل: {sheet_name} ===\n" + df.to_string(index=False))
                extracted_text_from_file = "\n\n".join(sheets_str)
            except Exception as e:
                print(f"Error parsing Excel file: {e}")
                try:
                    multimodal_parts.append(
                        types.Part.from_bytes(data=file_bytes, mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                    )
                except Exception:
                    pass

        # 2. CSV files (.csv)
        elif ext == "csv" or (mime_type and "csv" in mime_type):
            try:
                import pandas as pd
                df = pd.read_csv(io.BytesIO(file_bytes))
                extracted_text_from_file = df.to_string(index=False)
            except Exception:
                try:
                    extracted_text_from_file = file_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    extracted_text_from_file = file_bytes.decode("cp1256", errors="ignore")

        # 3. PDF files (.pdf)
        elif ext == "pdf" or mime_type == "application/pdf":
            pdf_text = ""
            try:
                import pypdf
                reader = pypdf.PdfReader(io.BytesIO(file_bytes))
                for i, page in enumerate(reader.pages):
                    t = page.extract_text() or ""
                    if t.strip():
                        pdf_text += f"\n--- صفحة {i+1} ---\n{t.strip()}"
            except Exception as e:
                print(f"pypdf extraction error: {e}")

            if len(pdf_text.strip()) > 40:
                extracted_text_from_file = pdf_text
            else:
                # Scanned PDF without text layer: pass directly to Gemini Multimodal PDF reader
                try:
                    multimodal_parts.append(
                        types.Part.from_bytes(data=file_bytes, mime_type="application/pdf")
                    )
                except Exception as e:
                    print(f"Could not attach PDF bytes: {e}")

        # 4. Images (.png, .jpg, .jpeg, .webp, .bmp)
        elif ext in ["png", "jpg", "jpeg", "webp", "bmp"] or (mime_type and mime_type.startswith("image/")):
            actual_mime = mime_type or (f"image/{ext}" if ext != "jpg" else "image/jpeg")
            try:
                multimodal_parts.append(
                    types.Part.from_bytes(data=file_bytes, mime_type=actual_mime)
                )
            except Exception as e:
                print(f"Error attaching image bytes: {e}")

        # 5. Plain text or Markdown files (.txt, .md, .tsv)
        elif ext in ["txt", "md", "tsv"]:
            try:
                extracted_text_from_file = file_bytes.decode("utf-8")
            except UnicodeDecodeError:
                extracted_text_from_file = file_bytes.decode("cp1256", errors="ignore")

    # Combine file content and any additional raw text/notes
    combined_body = ""
    if extracted_text_from_file:
        combined_body += f"\n[محتوى الملف المرفق ({filename or 'ملف'})]:\n{extracted_text_from_file}\n"
    if raw_text and raw_text.strip():
        combined_body += f"\n[النص أو الملاحظات الإضافية المرفقة]:\n{raw_text.strip()}\n"

    if not combined_body.strip() and not multimodal_parts:
        return {"success": False, "error": "لم يتم إرسال أي نص أو ملف أو صورة لمعالجتها."}

    prompt = f"""أنت خبير فائق الذكاء ومتخصص في معالجة وهيكلة بيانات المصحات والمستشفيات في ليبيا والعالم العربي.
أمامك بيانات للمصحة مقدمة كـ (جدول إكسيل، صورة لافتة أو منشور، ملف PDF، أو نص منسوخ):

{combined_body}

المطلوب بدقة استخراج عنصرين:
1. قائمة الأطباء (doctors):
   - name: اسم الطبيب كاملاً (مع لقب د. أو دكتور)
   - specialty: التخصص الطبي بدقة (مثلاً: عظام ومفاصل، باطنة وسكري، أطفال، عيون...)
   - regular_schedule: أيام وساعات الدوام (مثلاً: السبت والإثنين من 4 إلى 8 مساءً)
   - consultation_fee: سعر الكشفية بالدينار الليبي (إذا لم تذكر خمن أو ضع 40.0)
   - room_number: رقم العيادة أو "غير محدد"
2. قائمة الفحوصات والتحاليل والخدمات (services):
   - category: القسم (مختبر, أشعة, طوارئ, كشوفات)
   - name: اسم الفحص أو التحليل (مثلاً: صورة دم كاملة CBC، تحليل سكر، إيكو قلب...)
   - price: السعر بالدينار
   - prep_instructions: إرشادات الصيام أو التحضير إن وجدت (مثلاً: صيام 10-12 ساعة)
   - availability: أوقات العمل بالمختبر/القسم (مثلاً: متاح 24 ساعة)

يجب أن يكون الرد كائن JSON صالحاً حصراً بهذا الشكل:
{{
  "doctors": [
    {{
      "name": "د. الاسم",
      "specialty": "التخصص",
      "regular_schedule": "المواعيد",
      "consultation_fee": 40.0,
      "room_number": "عيادة 101"
    }}
  ],
  "services": [
    {{
      "category": "مختبر",
      "name": "اسم الفحص",
      "price": 30.0,
      "prep_instructions": "لا توجد شروط خاصة",
      "availability": "متاح 24 ساعة"
    }}
  ]
}}
"""

    gemini_contents = []
    gemini_contents.extend(multimodal_parts)
    gemini_contents.append(prompt)

    preferred_m = os.environ.get("GEMINI_MODEL") or settings.GEMINI_MODEL or "gemini-3.1-flash-lite"
    models_to_try = [preferred_m, "gemini-3.1-flash-lite", "gemini-3.5-flash-lite", "gemini-3.5-flash"]
    seen = set()
    models_to_try = [m for m in models_to_try if not (m in seen or seen.add(m))]

    last_exc = None
    data = None

    for model_name in models_to_try:
        try:
            print(f"Attempting data ingestion with model: {model_name}...")
            response = gemini_client.models.generate_content(
                model=model_name,
                contents=gemini_contents,
                config={
                    "response_mime_type": "application/json",
                    "temperature": 0.1,
                }
            )
            if response and response.text:
                clean_json = response.text.strip()
                if clean_json.startswith("```json"):
                    clean_json = clean_json[7:]
                if clean_json.endswith("```"):
                    clean_json = clean_json[:-3]
                data = json.loads(clean_json.strip())
                print(f"Ingestion successful with {model_name}!")
                break
        except Exception as e:
            print(f"Model {model_name} failed during ingestion: {e}")
            last_exc = e
            continue

    if not data:
        return {"success": False, "error": f"تعذر استخراج البيانات من المصدر: {last_exc}"}

    added_doctors = []
    for d in data.get("doctors", []):
        doc = db_service.upsert_doctor(
            name=d["name"],
            specialty=d["specialty"],
            regular_schedule=d["regular_schedule"],
            consultation_fee=float(d.get("consultation_fee", 40.0)),
            room_number=d.get("room_number", "غير محدد")
        )
        added_doctors.append(doc.name)

    added_services = []
    for s in data.get("services", []):
        svc = db_service.upsert_service(
            name=s["name"],
            category=s.get("category", "مختبر"),
            price=float(s.get("price", 0.0)),
            prep_instructions=s.get("prep_instructions", "لا توجد شروط خاصة"),
            availability=s.get("availability", "متاح")
        )
        added_services.append(svc.name)

    audit_summary = f"استيراد بيانات ({filename or 'نص/جدول'}): {len(added_doctors)} أطباء، {len(added_services)} خدمات"
    try:
        import db
        db.log_audit_trail(
            admin_sender="الإدخال الذكي (AI Ingest)",
            raw_message=(filename or raw_text or "ملف مرفق")[:200],
            status_before=None,
            status_after={"doctors_added": len(added_doctors), "services_added": len(added_services)},
            confirmation_text=audit_summary
        )
    except Exception as e:
        print(f"Audit log warning: {e}")

    return {
        "success": True,
        "doctors_count": len(added_doctors),
        "services_count": len(added_services),
        "doctors": added_doctors,
        "services": added_services,
        "source": filename or "نص/جدول منسوخ"
    }
