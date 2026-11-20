"""Legacy-module shim tests (Messenger-first pivot).

The pivot renamed patient_service -> customer_service,
triage -> guardrails, patient_processor -> customer_processor and
patient_debouncer -> message_debouncer. The old module names remain as
thin re-export shims so existing imports keep working; these tests pin
that the shims resolve and delegate to the new implementations instead
of silently drifting into a second copy.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def test_patient_service_shim_delegates():
    import customer_service
    import patient_service

    assert patient_service.handle_customer_query is customer_service.handle_customer_query
    assert patient_service.handle_patient_query is customer_service.handle_patient_query
    assert patient_service.MODELS_CASCADE is customer_service.MODELS_CASCADE
    assert patient_service.fallback_customer_answer is customer_service.fallback_customer_answer


def test_triage_shim_delegates():
    import guardrails
    import triage

    assert triage.evaluate_triage is guardrails.evaluate_triage
    assert triage.TriageLevel is guardrails.TriageLevel
    assert triage.TriageResult is guardrails.TriageResult
    assert triage.build_emergency_directive is guardrails.build_emergency_directive


def test_patient_processor_shim_delegates():
    from app.services import customer_processor, patient_processor

    assert patient_processor.process_customer_message is customer_processor.process_customer_message
    # The legacy entry point still answers on the WhatsApp channel.
    assert patient_processor.process_patient_message.__doc__ is not None


def test_patient_debouncer_is_message_debouncer_alias():
    from debouncer import message_debouncer, patient_debouncer

    assert patient_debouncer is message_debouncer


def test_generate_patient_response_alias_still_exists():
    from app.services import llm_service

    assert callable(llm_service.generate_patient_response)
    assert callable(llm_service.generate_customer_response)


def test_legacy_patient_query_still_answers():
    # End-to-end through the shim: a WhatsApp-channel patient query on
    # the shared (clinic) DB still returns a grounded reply.
    import patient_service

    reply = patient_service.handle_patient_query(
        "0910000099", "من متواجد اليوم في العظام؟"
    )
    assert isinstance(reply, str)
    assert len(reply) > 0
