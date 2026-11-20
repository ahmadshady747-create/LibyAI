from typing import Optional
from app.services import llm_service


def process_customer_message(
    sender_id: str,
    message_text: str,
    channel: str = "simulator",
) -> str:
    """Processes a 1:1 customer inquiry message and returns the response.

    sender_id and channel are threaded through to the customer response
    pipeline so conversation history is tracked per customer per channel,
    not shared across all customers.
    """
    return llm_service.generate_customer_response(
        message_text, sender_phone=sender_id, channel=channel
    )
