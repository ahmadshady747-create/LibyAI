"""
Backward-compatibility shim for `guardrails.py`.

The clinical triage engine moved to guardrails.py (Messenger-first /
multi-sector pivot). The Level 1 red-flag patterns, Level 2 clinical
advice rules, and evaluate_triage behaviour are unchanged — this module
re-exports them so existing imports keep working. New code should import
from `guardrails` directly.
"""

from guardrails import (
    TriageLevel,
    TriageResult,
    RED_FLAG_PATTERNS,
    CLINICAL_ADVICE_KEYWORDS,
    NORMALIZED_ADVICE_KEYWORDS,
    COMPILED_RED_FLAGS,
    normalize_arabic,
    normalize_pattern,
    build_emergency_directive,
    build_clinical_advice_refusal,
    evaluate_triage,
)

__all__ = [
    "TriageLevel",
    "TriageResult",
    "RED_FLAG_PATTERNS",
    "CLINICAL_ADVICE_KEYWORDS",
    "NORMALIZED_ADVICE_KEYWORDS",
    "COMPILED_RED_FLAGS",
    "normalize_arabic",
    "normalize_pattern",
    "build_emergency_directive",
    "build_clinical_advice_refusal",
    "evaluate_triage",
]
