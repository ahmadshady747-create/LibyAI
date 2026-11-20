"""
Backward-compatibility shim for `customer_processor.py`.

Patient inquiries are customer inquiries on the medical sector; this
module re-exports the generalized processor under the old name. New
code should import from `customer_processor` directly.
"""

from app.services.customer_processor import process_customer_message


def process_patient_message(sender_phone: str, message_text: str) -> str:
    """Legacy alias: processes a 1:1 patient inquiry message."""
    return process_customer_message(sender_phone, message_text, channel="whatsapp")
