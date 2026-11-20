"""sender_phone propagation regression tests (stabilization pass, task 4).

process_patient_message(sender_phone, message_text) used to silently ignore
sender_phone: llm_service.generate_patient_response called
patient_service.handle_patient_query with the hardcoded key
"simulator_patient", so every patient's conversation history was stored
under one shared key. These tests pin the fix: the sender's number is
threaded through the whole patient pipeline.
"""

import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services import patient_processor


def test_sender_phone_reaches_patient_handler():
    with patch(
        "patient_service.handle_patient_query", return_value="ok"
    ) as mock_handle:
        reply = patient_processor.process_patient_message(
            "0917770001", "من دكتور العظام اليوم؟"
        )
    assert reply == "ok"
    mock_handle.assert_called_once_with("0917770001", "من دكتور العظام اليوم؟")


def test_distinct_senders_get_distinct_histories():
    import db as legacy_db

    phone_a = "0917000001"
    phone_b = "0917000002"
    patient_processor.process_patient_message(phone_a, "من دكتور العظام اليوم؟")
    patient_processor.process_patient_message(phone_b, "قداش كشف الباطنة؟")

    # Only user turns are compared: assistant replies may legitimately
    # mention other specialties, but a patient's own words must never
    # appear in another patient's history.
    user_a = [
        t["text"]
        for t in legacy_db.get_conversation_history(phone_a)
        if t["role"] == "user"
    ]
    user_b = [
        t["text"]
        for t in legacy_db.get_conversation_history(phone_b)
        if t["role"] == "user"
    ]
    assert any("عظام" in t for t in user_a)
    assert any("باطنة" in t for t in user_b)
    assert not any("باطنة" in t for t in user_a)
    assert not any("عظام" in t for t in user_b)
