"""
LibyAI Clinical Triage & Safety Guardrails Layer (`triage.py`)

Multi-Tier Triage Engine:
- Triage Level 1 (Red Flag Interceptor): Fast-path deterministic regex/matcher for acute emergency symptoms.
  Bypasses LLM completely and returns pre-compiled high-priority emergency instructions.
- Triage Level 2 (Clinical Advice Prohibition): Strict guardrail against prescribing drugs, giving dosages,
  or rendering definitive diagnoses.
- Triage Level 3 (Routine Inquiries): General clinic and doctor schedule/pricing queries.
"""

import re
from enum import Enum
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field


class TriageLevel(str, Enum):
    EMERGENCY_LEVEL_1 = "EMERGENCY_LEVEL_1"
    CLINICAL_ADVICE_LEVEL_2 = "CLINICAL_ADVICE_LEVEL_2"
    ROUTINE_LEVEL_3 = "ROUTINE_LEVEL_3"


class TriageResult(BaseModel):
    level: TriageLevel
    is_emergency: bool = False
    is_clinical_advice_prohibited: bool = False
    matched_flags: List[str] = Field(default_factory=list)
    immediate_response: Optional[str] = None


# =====================================================================
# Red Flag Regex & Deterministic Patterns (Acute Clinical Emergencies)
# =====================================================================

RED_FLAG_PATTERNS = {
    "severe_bleeding": [
        r"(?:^|\W|[وفلكب])(?:نزيف|نزف)\s*(?:حاد|شديد|مستمر|قوي|غزير|لا\s+يتوقف|واجد)",
        r"(?:^|\W|[وفلكب])دم\s+(?:غزير|كثير\s+جدا|ينزف\s+بقوة|ما\s+(?:يبيش|يوقفش)\s+يوقف|يصب)",
        r"(?:^|\W|[وفلكب])(?:ينزف|تنزف)\s+دم(?:\s+غزير|\s+بقوة)?",
        r"(?:^|\W|[وفلكب])(?:طعنة|جرح\s+عميق\s+ينزف)",
    ],
    "sudden_chest_pain": [
        r"(?:^|\W|[وفلكب])(?:الم|وجع)\b.*?\b(?:الصدر|صدري|القلب)",
        r"(?:^|\W|[وفلكب])(?:جلطة|نوبة\s+قلبية|ذبحة\s+صدرية)",
        r"(?:^|\W|[وفلكب])صدري\s+يوجع(?:ني)?(?:\s+فجاة)?",
        r"(?:^|\W|[وفلكب])الم\s+يمتد\s+لليد\s+اليسرى",
    ],
    "acute_dyspnea": [
        r"(?:^|\W|[وفلكب])(?:ضيق\s+تنفس|انقطاع\s+(?:في\s+)?النفس|مش\s+قادر(?:ة)?\s+[نيت]تنفس|اختناق|كتمة\s+شديدة|خنقة\s+شديدة|ما\s+[نيت]تنفسش)",
        r"(?:^|\W|[وفلكب])زرقة\s+في\s+(?:الشفاه|الوجه)",
    ],
    "loss_of_consciousness": [
        r"(?:^|\W|[وفلكب])(?:فقدان\s+(?:ال)?وعي|(?:ا|م)غم[يى](?:\s+عليه)?|اغماء|غيبوبة|فاقد\s+(?:ال)?وعي(?:ه)?)",
        r"(?:^|\W|[وفلكب])(?:طاح|طاحت|سقط|سقطت)\s+(?:ودايخ|ومغم[يى]|وفاقد\s+الوعي)?",
        r"(?:^|\W|[وفلكب])دايخ\s+وطاح",
        r"(?:^|\W|[وفلكب])(?:مش\s+واعي|مش\s+واعية|لا\s+يستجيب\s+للكلام)",
    ],
    "acute_poisoning": [
        r"(?:^|\W|[وفلكب])(?:تسمم\s*(?:حاد|شديد|دوائي)?|شرب\s+(?:مادة\s+سامة|منظف|كلور|فلاش|سم|دواء\s+واجد|نفط)|بلع\s+(?:.*?\s+)?(?:مادة\s+سامة|منظف|كلور|سم|حبوب|شريط|ادوية)|(?:لدغة|قرصة)\s+(?:عقرب|ثعبان|افعى))",
        r"(?:^|\W|[وفلكب])جرعة\s+زائدة(?:\s+من\s+الدواء)?",
    ],
    "pediatric_lethargy_and_seizures": [
        r"(?:^|\W|[وفلكب])(?:تشنج(?:ات)?|[يت]تشنج|طفل\s+فاقد\s+(?:ال)?وعي|ولدي\s+خامل|بنتي\s+خاملة|رضيع\s+ما\s+يتنفسش)",
        r"(?:^|\W|[وفلكب])حرارة\s+(?:40|41)\s+مع\s+تشنج",
    ],
}


# =====================================================================
# Clinical Advice & Prescription Detection Patterns (Triage Level 2)
# =====================================================================

CLINICAL_ADVICE_KEYWORDS = [
    "شن دواء", "شن ناخذ دواء", "شن ناخذ علاج", "شن ناكل علاج", "شن نعطيه دواء",
    "اعطيني اسم دواء", "أعطيني اسم دواء", "اسم مضاد حيوي", "اسم مسكن", "شن نشرب دواء",
    "جرعة البنادول", "جرعة المضاد", "كم جرعة", "وصفة طبية", "علاج سريع للمغص",
    "فسرلي نتيجة التحليل", "شن معنى الرقم في الفحص", "هل عندي ورم", "شخصلي حالتي"
]


def normalize_arabic(text: str) -> str:
    """Normalizes Arabic text for consistent pattern matching."""
    t = text.lower()
    t = re.sub(r"[إأآا]", "ا", t)
    t = re.sub(r"[ىي]", "ي", t)
    t = re.sub(r"[ةه]", "ه", t)
    t = re.sub(r"[\u064B-\u065F]", "", t)  # remove harakat
    return t.strip()


def normalize_pattern(pat: str) -> str:
    """
    Normalizes Arabic letters in regex patterns WITHOUT lowercasing,
    preserving case-sensitive escape sequences such as \\W (non-word character).
    """
    t = re.sub(r"[إأآا]", "ا", pat)
    t = re.sub(r"[ىي]", "ي", t)
    t = re.sub(r"[ةه]", "ه", t)
    t = re.sub(r"[\u064B-\u065F]", "", t)
    return t


# Normalize clinical advice keywords
NORMALIZED_ADVICE_KEYWORDS = [normalize_arabic(kw) for kw in CLINICAL_ADVICE_KEYWORDS]

# Pre-compile normalized red flag patterns for microsecond-fast matching
COMPILED_RED_FLAGS = {}
for category, patterns in RED_FLAG_PATTERNS.items():
    compiled_list = []
    for pat in patterns:
        norm_pat = normalize_pattern(pat)
        compiled_list.append(re.compile(norm_pat, re.IGNORECASE))
    COMPILED_RED_FLAGS[category] = compiled_list


def build_emergency_directive(clinic_info: Dict[str, str], matched_symptom: str) -> str:
    """Constructs a prominent, WhatsApp-formatted urgent ER directive."""
    clinic_name = clinic_info.get("name", "مستشفى الياسمين الإيوائي")
    emergency_phone = clinic_info.get("emergency_phone", "0911059900 - 0945361562")
    address = clinic_info.get("address", "زليتن - خلف مدرسة خديجة الكبرى")
    map_link = clinic_info.get("map_link", "https://maps.google.com/?q=Zliten+Jasmine+Hospital")

    return (
        "🚨 *تنبيه طبي عاجل وحرج* 🚨\n\n"
        "⚠️ الأعراض المذكورة تشير إلى حالة طارئة محتملة تتطلب تدخلاً طبياً فورياً ولا تحتمل الانتظار!\n\n"
        f"🏥 *يرجى التوجه فوراً وبأقصى سرعة إلى قسم الإسعاف والطوارئ في {clinic_name} (متاح 24 ساعة).* \n\n"
        f"📞 *أرقام الطوارئ والإسعاف:* \n"
        f"*{emergency_phone}*\n\n"
        f"📍 *العنوان:* {address}\n\n"
        "_حفظكم الله وعافاكم من كل سوء._"
    )


def build_clinical_advice_refusal(clinic_info: Dict[str, str]) -> str:
    """Constructs polite WhatsApp response refusing medication/diagnosis and guiding to doctors."""
    return (
        "ألف لا بأس عليكم وطهور إن شاء الله 🌸\n\n"
        "بصفتي في *مكتب الاستقبال الرقمي*، وحرصاً على سلامتكم وصحتكم:\n"
        "⛔ *يمنع منعاً باتاً وصف الأدوية، أو تحديد الجرعات، أو تشخيص الحالات الطبية عبر المحادثة.*\n\n"
        "🩺 *الخطوة المعتمدة لسلامتكم:*\n"
        "• يرجى مراجعة الطبيب المختص بالعيادة لإجراء الفحص السريري ووصف العلاج المناسب لحالتكم بدقة.\n"
        "• إذا كانت الحالة مستعجلة، يُرجى التوجه فوراً إلى *قسم الإسعاف والطوارئ بالمصحة* (متاح 24 ساعة).\n\n"
        "يسعدني مساعدتك في معرفة التخصص الأنسب لحالتك، أو مواعيد وكشفيات أطباء اليوم."
    )


def evaluate_triage(
    text: str,
    clinic_info: Optional[Dict[str, str]] = None
) -> TriageResult:
    """
    Evaluates incoming patient text through the dual-layer clinical triage engine.
    Returns TriageResult with Level 1, Level 2, or Level 3 determination.
    """
    clinic_info = clinic_info or {}
    norm_text = normalize_arabic(text)

    # -------------------------------------------------------------
    # Layer 1: Red Flag Emergency Check (Strict Fast-Path Bypass)
    # -------------------------------------------------------------
    matched_flags = []
    for category, compiled_patterns in COMPILED_RED_FLAGS.items():
        for regex in compiled_patterns:
            if regex.search(norm_text):
                matched_flags.append(f"{category}:{regex.pattern}")
                break

    if matched_flags:
        emergency_directive = build_emergency_directive(clinic_info, matched_flags[0])
        return TriageResult(
            level=TriageLevel.EMERGENCY_LEVEL_1,
            is_emergency=True,
            is_clinical_advice_prohibited=False,
            matched_flags=matched_flags,
            immediate_response=emergency_directive
        )

    # -------------------------------------------------------------
    # Layer 2: Clinical Advice / Prescription Request Check
    # -------------------------------------------------------------
    is_advice_prohibited = any(kw in norm_text for kw in NORMALIZED_ADVICE_KEYWORDS)
    if is_advice_prohibited:
        advice_refusal = build_clinical_advice_refusal(clinic_info)
        return TriageResult(
            level=TriageLevel.CLINICAL_ADVICE_LEVEL_2,
            is_emergency=False,
            is_clinical_advice_prohibited=True,
            matched_flags=["clinical_advice_prohibited"],
            immediate_response=advice_refusal
        )


    # -------------------------------------------------------------
    # Layer 3: Routine Inquiry (Pass through to Gemini 2.5 Flash)
    # -------------------------------------------------------------
    return TriageResult(
        level=TriageLevel.ROUTINE_LEVEL_3,
        is_emergency=False,
        is_clinical_advice_prohibited=False,
        matched_flags=[],
        immediate_response=None
    )
