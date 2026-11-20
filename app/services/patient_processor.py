from typing import Optional
from app.services import llm_service


def process_patient_message(sender_phone: str, message_text: str) -> str:
    """Processes 1:1 patient inquiry message and returns the response.

    sender_phone is threaded through to the patient response pipeline so
    conversation history is tracked per patient, not shared across all
    patients.
    """
    return llm_service.generate_patient_response(message_text, sender_phone=sender_phone)
