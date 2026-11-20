"""
LibyAI Messenger Channel Adapter (`app/channels/messenger.py`)

PRIMARY channel. Meta Messenger Platform webhook:
- GET /webhook/messenger — subscription verification challenge.
- POST /webhook/messenger — inbound messages, enqueued durably.

Security: X-Hub-Signature-256 (HMAC-SHA256 against
MESSENGER_APP_SECRET) is verified BEFORE parsing JSON, always — a
missing, malformed, or invalid signature is rejected (401/403) without
the server spending any work on the body, exactly like the signed
WhatsApp endpoint.

Loop prevention: message echoes (message.is_echo == True), delivery
receipts, and read receipts are dropped at parse time, never enqueued,
so the bot can never reply to its own messages.

Outbound replies go through the Meta Graph API (POST /v21.0/me/messages)
with MESSENGER_PAGE_ACCESS_TOKEN. Without a token, sending is simulated
(development mode) and returns a simulated id, like WhatsApp.
"""

import hashlib
import hmac
import json
import logging
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Request, Response, HTTPException, status

import db
from app.channels.base import ChannelAdapter, IncomingMessage, verify_hmac_sha256
from app.config import enabled_channels, settings

logger = logging.getLogger(__name__)

GRAPH_API_URL = "https://graph.facebook.com/v21.0/me/messages"


class MessengerAdapter(ChannelAdapter):
    channel = "messenger"

    def verify_webhook(self, mode: Optional[str], token: Optional[str]) -> bool:
        verify_token = (
            db.get_clinic_info().get("messenger_verify_token")
            or self.settings.MESSENGER_VERIFY_TOKEN
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
        return verify_hmac_sha256(raw_body, signature_header, self.settings.MESSENGER_APP_SECRET)

    def parse_incoming(self, body: Dict[str, Any]) -> List[IncomingMessage]:
        messages: List[IncomingMessage] = []
        for entry in body.get("entry", []) or []:
            for event in entry.get("messaging", []) or []:
                # Delivery and read receipts are not messages.
                if "delivery" in event or "read" in event:
                    continue
                msg = event.get("message") or {}
                # Echoes of our own sent messages must never be enqueued:
                # replying to an echo would loop forever.
                if msg.get("is_echo"):
                    continue
                text = (msg.get("text") or "").strip()
                if not text:
                    # Non-text Messenger content (attachments, stickers)
                    # is ignored: the bot answers text inquiries only.
                    continue
                sender_id = str((event.get("sender") or {}).get("id", "")).strip()
                if not sender_id:
                    continue
                external_id = str(msg.get("mid", "")).strip()
                if not external_id:
                    external_id = "mid_fallback_" + hashlib.sha256(
                        (sender_id + str(event.get("timestamp", "")) + text).encode("utf-8")
                    ).hexdigest()[:20]
                timestamp = event.get("timestamp")
                try:
                    timestamp_s = float(timestamp) / 1000.0 if timestamp else 0.0
                except (TypeError, ValueError):
                    timestamp_s = 0.0
                messages.append(IncomingMessage(
                    channel="messenger",
                    external_message_id=external_id,
                    sender_id=sender_id,
                    text=text,
                    timestamp=timestamp_s or 0.0,
                    raw_metadata={"event": event},
                ))
        return messages

    async def send_text(self, to: str, message: str) -> Optional[str]:
        """Sends a text message via the Messenger Send API."""
        if not self.settings.MESSENGER_PAGE_ACCESS_TOKEN:
            logger.info(f"[SIMULATED MESSENGER OUTGOING] To: {to} | Message: {message}")
            return "simulated_msg_id"

        url = GRAPH_API_URL
        params = {"access_token": self.settings.MESSENGER_PAGE_ACCESS_TOKEN}
        payload = {
            "recipient": {"id": to},
            "message": {"text": message},
            "messaging_type": "RESPONSE",
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(url, params=params, json=payload)
            r.raise_for_status()
            data = r.json()
            return data.get("message_id") or "sent"


router = APIRouter(prefix="/webhook", tags=["Messenger Webhook"])


def _messenger_enabled() -> bool:
    return "messenger" in enabled_channels()


@router.get("/messenger")
async def verify_messenger_webhook(request: Request):
    """Messenger Platform webhook verification challenge."""
    if not _messenger_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Messenger channel is not enabled.")
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    adapter = MessengerAdapter()
    if adapter.verify_webhook(mode, token) and challenge is not None:
        return Response(content=challenge, media_type="text/plain")
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Verification failed")


@router.post("/messenger")
async def handle_messenger_webhook(request: Request):
    """
    Handles incoming Messenger webhook events. Enforces fail-closed
    HMAC-SHA256 signature verification before any JSON parsing or
    database mutation, then atomically ingests each text message into
    the durable SQLite job queue and returns HTTP 200 immediately.
    """
    if not _messenger_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Messenger channel is not enabled.")

    # 1. Read raw request body before JSON parsing
    raw_body = await request.body()

    # 2. Validate X-Hub-Signature-256 header using constant-time comparison
    signature_header = request.headers.get("X-Hub-Signature-256")
    if not signature_header:
        logger.warning("Rejected Messenger webhook request: Missing X-Hub-Signature-256 header.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-Hub-Signature-256 signature header."
        )

    if not settings.MESSENGER_APP_SECRET:
        logger.error("Rejected Messenger webhook request: Server-side MESSENGER_APP_SECRET is not configured.")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Server-side Meta App Secret is not configured."
        )

    adapter = MessengerAdapter()
    if not adapter.verify_signature(raw_body, signature_header):
        logger.warning("Rejected Messenger webhook request: Invalid X-Hub-Signature-256 signature.")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid webhook signature."
        )

    # 3. Parse JSON payload only after signature verification succeeds
    try:
        body = json.loads(raw_body.decode("utf-8"))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload."
        )

    from job_queue import job_queue

    incoming = adapter.parse_incoming(body)
    enqueued_jobs = []
    for msg in incoming:
        # Staff senders (Messenger PSIDs in authorized_staff) get their
        # message tagged @Bot so the admin path picks it up, exactly like
        # the WhatsApp staff path.
        is_staff, _, _ = db.is_sender_authorized(msg.sender_id, "messenger")
        tagged_msg = msg.text
        if is_staff and not any(tag in msg.text.lower() for tag in ["@bot", "@بـوت", "@بوت", "@مساعد"]):
            tagged_msg = f"@Bot {msg.text}"

        is_new, job_id, q_status = job_queue.enqueue_incoming_message(
            channel="messenger",
            message_id=msg.external_message_id,
            sender=msg.sender_id,
            message_text=tagged_msg if is_staff else msg.text,
            is_group=is_staff,
            group_id="messenger_staff" if is_staff else None,
            payload_json=json.dumps(msg.raw_metadata.get("event", {}), ensure_ascii=False),
        )
        if is_new:
            enqueued_jobs.append(job_id)
        else:
            logger.info(f"[Messenger Webhook] Duplicate message {msg.external_message_id} rejected at ledger.")

    return {
        "status": "success",
        "enqueued_count": len(enqueued_jobs),
        "enqueued_jobs": enqueued_jobs,
    }
