"""
LibyAI Sector-Aware Guardrails Engine (`guardrails.py`)

Modular policy engine for every business sector:
- Commercial Handoff Rules (ALL sectors): deterministic detection of
  requests that need a human (explicit human/manager request, angry
  complaints, refund/dispute issues, wholesale/custom orders,
  out-of-scope inquiries). Returns a clean handoff message with the
  escalation phone and is logged to the audit trail by the caller.
- Medical Safety Module (OPT-IN by sector, ONLY when
  business.sector in ("clinic", "pharmacy", "medical")):
  - Triage Level 1 (Red Flag Interceptor): fast-path deterministic
    regex/matcher for acute emergency symptoms. Bypasses the debouncer
    and the LLM completely and returns pre-compiled high-priority
    emergency instructions. Behaviour is preserved EXACTLY as in the
    original triage.py for medical sectors.
  - Triage Level 2 (Clinical Advice Prohibition): strict guardrail
    against prescribing drugs, giving dosages, or rendering definitive
    diagnoses.
  - Triage Level 3 (Routine Inquiries): general schedule/pricing queries.

`triage.py` remains as a thin compatibility shim re-exporting this
module, so existing imports keep working.
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


class GuardrailResult(BaseModel):
    """Unified result of the full guardrail evaluation.

    Exactly one of is_emergency / needs_handoff /
    is_clinical_advice_prohibited may be set; when none is set the
    message is routine and flows to the debouncer / LLM path.
    """
    is_emergency: bool = False
    needs_handoff: bool = False
    handoff_reason: Optional[str] = None
    is_clinical_advice_prohibited: bool = False
    matched_flags: List[str] = Field(default_factory=list)
    immediate_response: Optional[str] = None


# Sectors where the medical safety module is active. Every other sector
# gets the commercial guardrails only — a retail customer who mentions a
# medical word must never receive an emergency-clinic directive.
MEDICAL_SECTORS = ("clinic", "pharmacy", "medical")


def is_medical_sector(business_info: Optional[Dict[str, Any]] = None) -> bool:
    """True only for medical sectors. A business dict may carry either
    a `sector` key (new) or the legacy `is_medical` flag; sector wins
    when present, otherwise the legacy flag is honoured (default True
    for backward compatibility with clinic-only deployments)."""
    info = business_info or {}
    sector = (info.get("sector") or "").strip().lower()
    if sector:
        return sector in MEDICAL_SECTORS
    return bool(info.get("is_medical", True))


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


def build_emergency_directive(clinic_info: Dict[str, Any], matched_symptom: str) -> str:
    """Constructs a prominent, WhatsApp-formatted urgent ER directive."""
    clinic_name = clinic_info.get("clinic_name") or clinic_info.get("name") or "المصحة"
    emergency_phone = clinic_info.get("emergency_phone") or clinic_info.get("contact_numbers") or clinic_info.get("reception_phone") or "أرقام الطوارئ"
    address = clinic_info.get("address") or "المقر الرئيسي"
    map_link = clinic_info.get("map_link") or ""

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
    clinic_info: Optional[Dict[str, Any]] = None
) -> TriageResult:
    """
    Evaluates incoming customer text through the dual-layer clinical triage engine.
    Returns TriageResult with Level 1, Level 2, or Level 3 determination.
    The medical module activates ONLY for medical sectors (sector in
    ("clinic", "pharmacy", "medical"), or the legacy is_medical flag);
    for every other sector clinical checks are bypassed entirely and the
    message is routine.
    """
    clinic_info = clinic_info or {}
    if not is_medical_sector(clinic_info):
        return TriageResult(
            level=TriageLevel.ROUTINE_LEVEL_3,
            is_emergency=False,
            is_clinical_advice_prohibited=False,
            matched_flags=[],
            immediate_response=None
        )

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
    # Layer 3: Routine Inquiry (Pass through to the LLM / fallback)
    # -------------------------------------------------------------
    return TriageResult(
        level=TriageLevel.ROUTINE_LEVEL_3,
        is_emergency=False,
        is_clinical_advice_prohibited=False,
        matched_flags=[],
        immediate_response=None
    )


# =====================================================================
# Commercial Handoff Rules (ALL sectors)
# =====================================================================

# Deterministic keyword groups (normalized Arabic). Each group maps to a
# stable handoff reason used in the audit log.
HANDOFF_KEYWORDS = {
    "human_request": [
        "تكلم مع انسان", "اتكلم مع انسان", "ابغى انسان", "ابي انسان",
        "تكلم مع موظف", "اتكلم مع موظف", "ابي موظف", "ابغى موظف",
        "تكلم مع المدير", "اتكلم مع المدير", "ابي المدير", "ابغى المدير",
        "تكلم مع مسؤول", "اتكلم مع مسؤول", "ابي مسؤول", "ابغى مسؤول",
        "تكلم مع شخص", "اتكلم مع شخص", "وصلني بالاداره", "وصلني بالادارة",
        "تكلم مع صاحب المحل", "اتكلم مع صاحب المحل", "ابي صاحب المحل",
        "كلم المدير", "كلم المسؤول", "كلم موظف", "كلم انسان",
        "human", "موظف حقيقي", "شخص حقيقي", "انسان حقيقي",
    ],
    "angry_complaint": [
        "شكوى", "اشتكي", "بشتكي", "اشكي", "مشتكي", "زعلان", "غاضب",
        "معصب", "مقهور", "متضايق", "اسوء خدمه", "اسوء خدمة",
        "خدمتكم سيئه", "خدمتكم سيئة", "خدمه سيئه", "خدمة سيئة",
        "معامله سيئه", "معاملة سيئة", "اهمال", "اهمالكم", "مستهترين",
        "نصابين", "نصب", "كذابين", "خدعتوني", "ضحكتوا علي",
        "مش راضي", "مش راضى", "غير راضي", "مستاء",
    ],
    "refund_dispute": [
        "استرجاع", "استرجاع فلوس", "رجعولي فلوسي", "ارجعولي فلوسي",
        "رد فلوسي", "نبي فلوسي", "استرداد", "تعويض", "مطالبه",
        "مطالبة", "خصم غلط", "خصمتوا زياده", "خصمتوا زيادة",
        "دفعت مرتين", "دفعت وماوصلش", "دفعت وما وصلش",
        "طلب ملغي", "الغي طلبي", "الغاء الطلب", "إلغاء الطلب",
        "فلوسي وين", "وين فلوسي", "نبي نرجع", "استرجاع المنتج",
    ],
    "wholesale_custom": [
        "جمله", "بالجمله", "بالجملة", "جملة", "كميه كبيره", "كمية كبيرة",
        "كميات", "طلبيه كبيره", "طلبية كبيرة", "طلب جمله", "طلب جملة",
        "سعر الجمله", "سعر الجملة", "خصم جمله", "خصم جملة",
        "طلب خاص", "طلب مخصص", "تفصيل خاص", "تصميم خاص", "صنع خاص",
        "تعاقد", "عقد شهري", "عقد سنوي", "اتفاقيه", "اتفاقية",
    ],
    "out_of_scope": [
        "تبيعوا سيارات", "تبيعون سيارات", "عندكم سيارات",
        "تبيعوا عقارات", "عندكم شقق", "تبيعوا اراضي",
        "تاجروا سيارات", "تأجير سيارات", "ايجار سيارات",
        "توصيل خارج ليبيا", "شحن دولي", "شحن خارج ليبيا",
        "تشتغلوا في الليل", "تفتحوا 24 ساعه", "فاتحين 24 ساعه",
    ],
}

NORMALIZED_HANDOFF_KEYWORDS = {
    reason: [normalize_arabic(kw) for kw in keywords]
    for reason, keywords in HANDOFF_KEYWORDS.items()
}


def build_handoff_message(business_info: Dict[str, Any], reason: str) -> str:
    """Clean handoff message with the escalation phone. No diagnosis, no
    promises about refunds or resolutions — the human handles it."""
    business_name = (
        business_info.get("business_name")
        or business_info.get("clinic_name")
        or business_info.get("name")
        or "النشاط التجاري"
    )
    escalation_phone = (
        business_info.get("escalation_phone")
        or business_info.get("emergency_phone")
        or business_info.get("support_phone")
        or business_info.get("reception_phone")
        or business_info.get("contact_numbers")
        or "مكتب الإدارة"
    )
    reason_lines = {
        "human_request": "تم تحويل طلبك إلى أحد موظفي خدمة العملاء.",
        "angry_complaint": "نأسف جداً لتجربتك، وتم تحويل شكواك إلى الإدارة لمراجعتها.",
        "refund_dispute": "تم تحويل طلبك المتعلق بالدفع أو الاسترجاع إلى الإدارة لمراجعته.",
        "wholesale_custom": "تم تحويل طلبك الخاص إلى الإدارة لدراسته والرد عليك.",
        "out_of_scope": "هذا الطلب خارج نطاق خدماتنا المعتادة، وتم تحويله إلى الإدارة للتأكد.",
    }
    line = reason_lines.get(reason, "تم تحويل طلبك إلى الإدارة.")
    return (
        f"أهلاً بك في *{business_name}* 🌸\n\n"
        f"{line}\n\n"
        f"📞 *للتواصل المباشر مع الإدارة:* {escalation_phone}\n\n"
        "سيتواصل معك أحد موظفينا في أقرب وقت خلال ساعات العمل."
    )


def evaluate_handoff(
    text: str,
    business_info: Optional[Dict[str, Any]] = None
) -> GuardrailResult:
    """Deterministic commercial handoff check (all sectors). Returns
    needs_handoff=True with a reason and a ready message when the text
    matches a handoff group, otherwise a routine result."""
    norm_text = normalize_arabic(text or "")
    for reason, keywords in NORMALIZED_HANDOFF_KEYWORDS.items():
        for kw in keywords:
            if kw and kw in norm_text:
                return GuardrailResult(
                    needs_handoff=True,
                    handoff_reason=reason,
                    matched_flags=[f"handoff:{reason}"],
                    immediate_response=build_handoff_message(business_info or {}, reason),
                )
    return GuardrailResult()


def evaluate_guardrails(
    text: str,
    business_info: Optional[Dict[str, Any]] = None
) -> GuardrailResult:
    """
    Full guardrail evaluation, in safety order:
    1. Medical Level 1 emergency (medical sectors only) — bypasses
       everything, including the debouncer and the LLM.
    2. Commercial handoff (all sectors).
    3. Medical Level 2 clinical-advice prohibition (medical sectors only).
    4. Routine — no guardrail triggered.
    """
    info = business_info or {}

    # 1. Medical emergency first: nothing outranks a red flag.
    triage_result = evaluate_triage(text, info)
    if triage_result.is_emergency and triage_result.immediate_response:
        return GuardrailResult(
            is_emergency=True,
            matched_flags=triage_result.matched_flags,
            immediate_response=triage_result.immediate_response,
        )

    # 2. Commercial handoff (all sectors).
    handoff = evaluate_handoff(text, info)
    if handoff.needs_handoff:
        return handoff

    # 3. Medical Level 2 (medical sectors only; evaluate_triage already
    # returns routine for non-medical sectors).
    if triage_result.is_clinical_advice_prohibited and triage_result.immediate_response:
        return GuardrailResult(
            is_clinical_advice_prohibited=True,
            matched_flags=triage_result.matched_flags,
            immediate_response=triage_result.immediate_response,
        )

    return GuardrailResult()
