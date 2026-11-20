"""
LibyAI WhatsApp Channel Adapter (`app/channels/whatsapp.py`)

SECONDARY channel. Wraps the existing WhatsApp Cloud API logic in the
same ChannelAdapter interface as Messenger. The FastAPI routes stay in
app/api/webhook.py (unchanged paths: GET/POST /webhook/whatsapp); this
adapter owns verification, parsing, and outbound sending.

WhatsApp is optional: the app boots cleanly in Messenger-only mode
without any WHATSAPP_* secret (see validate_production_security), and
the webhook returns 404 when WhatsApp is not in ENABLED_CHANNELS.
"""

import hashlib
import hmac
import logging
from typing import Any, Dict, List, Optional

import httpx

import db
from app.channels.base import ChannelAdapter, IncomingMessage, verify_hmac_sha256

logger = logging.getLogger(__name__)


class WhatsAppAdapter(ChannelAdapter):
    channel = "whatsapp"

    def verify_webhook(self, mode: Optional[str], token: Optional[str]) -> bool:
        verify_token = (
            db.get_clinic_info().get("whatsapp_verify_token")
            or self.settings.WHATSAPP_VERIFY_TOKEN
        )
        # Both sides must be present: a missing token on both sides
        # compared equal and could pass verification with no token at all.
        return bool(
            mode == "subscribe"
            and token
            and verify_token
            and hmac.compare_digest(token, verify_token)
        )

    def verify_signature(self, raw_body: bytes, signature_header: Optional[str]) -> bool:
        return verify_hmac_sha256(raw_body, signature_header, self.settings.WHATSAPP_APP_SECRET)

    def parse_incoming(self, body: Dict[str, Any]) -> List[IncomingMessage]:
        messages: List[IncomingMessage] = []
        for entry in body.get("entry", []) or []:
            for change in entry.get("changes", []) or []:
                value = change.get("value", {}) or {}
                for msg in value.get("messages", []) or []:
                    external_id = str(msg.get("id", "")).strip()
                    sender = str(msg.get("from", ""))
                    msg_type = msg.get("type")
                    if not external_id:
                        external_id = "wamid_fallback_" + hashlib.sha256(
                            (sender + str(msg.get("timestamp", "")) + str(msg.get("text", {}).get("body", ""))).encode("utf-8")
                        ).hexdigest()[:20]
                    if msg_type != "text":
                        # Non-text media: normalized with empty text and
                        # the media type in metadata; the route answers
                        # with the text-only notice, as before.
                        messages.append(IncomingMessage(
                            channel="whatsapp",
                            external_message_id=external_id,
                            sender_id=sender,
                            text="",
                            raw_metadata={"msg": msg, "media_type": msg_type},
                        ))
                        continue
                    text = (msg.get("text", {}) or {}).get("body", "")
                    if not text.strip():
                        continue
                    messages.append(IncomingMessage(
                        channel="whatsapp",
                        external_message_id=external_id,
                        sender_id=sender,
                        text=text,
                        raw_metadata={"msg": msg},
                    ))
        return messages

    async def send_text(self, to: str, message: str) -> Optional[str]:
        """Sends a text message via the WhatsApp Cloud API."""
        if not self.settings.WHATSAPP_TOKEN or not self.settings.WHATSAPP_PHONE_NUMBER_ID:
            logger.info(f"[SIMULATED WHATSAPP OUTGOING] To: {to} | Message: {message}")
            return "simulated_msg_id"

        url = f"https://graph.facebook.com/v21.0/{self.settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
        headers = {
            "Authorization": f"Bearer {self.settings.WHATSAPP_TOKEN}",
            "Content-Type": "application/json",
        }
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": message},
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(url, json=payload, headers=headers)
            r.raise_for_status()
            data = r.json()
            outbound_id = None
            if "messages" in data and len(data["messages"]) > 0:
                outbound_id = data["messages"][0].get("id")
            return outbound_id or "sent"
