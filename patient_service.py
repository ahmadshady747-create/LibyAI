"""
Backward-compatibility shim for `customer_service.py`.

The customer response service was generalized from clinic-only to all
business sectors (Messenger-first / multi-sector pivot). The clinic
behaviour is unchanged — a patient query is a customer query on the
medical sector — so this module re-exports the generalized
implementation under the old names. New code should import from
`customer_service` directly.
"""

from customer_service import (
    MODELS_CASCADE,
    gemini_client,
    detect_target_day,
    build_system_instruction,
    fallback_patient_answer,
    fallback_customer_answer,
    handle_customer_query,
    handle_patient_query,
)

__all__ = [
    "MODELS_CASCADE",
    "gemini_client",
    "detect_target_day",
    "build_system_instruction",
    "fallback_patient_answer",
    "fallback_customer_answer",
    "handle_customer_query",
    "handle_patient_query",
]
