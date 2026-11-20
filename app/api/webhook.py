import asyncio
import hmac
import hashlib
import json
import logging
from typing import Optional
from fastapi import APIRouter, Request, Response, HTTPException, status
from app.config import settings, is_phone_authorized, enabled_channels
from app.channels.base import verify_hmac_sha256
from app.channels.whatsapp import WhatsAppAdapter
import db
import admin_service
import httpx

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhook", tags=["WhatsApp Webhook"])


def verify_meta_signature(raw_body: bytes, signature_header: Optional[str], app_secret: Optional[str]) -> bool:
    """
    Validates a Meta webhook 'X-Hub-Signature-256' using HMAC-SHA256 and
    a server-side App Secret. Kept as the public name for this module;
    the implementation lives in app/channels/base.py and is shared by
    both channels.
    """
    return verify_hmac_sha256(raw_body, signature_header, app_secret)


@router.get("/whatsapp")
async def verify_webhook(request: Request):
    """WhatsApp Cloud API Webhook Verification Challenge."""
    if "whatsapp" not in enabled_channels():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="WhatsApp channel is not enabled.")
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    adapter = WhatsAppAdapter()
    if adapter.verify_webhook(mode, token) and challenge is not None:
        return Response(content=challenge, media_type="text/plain")
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Verification failed")


async def send_whatsapp_reply(to: str, message: str) -> Optional[str]:
    """Sends text message back via WhatsApp Cloud API. Returns outbound
    message ID or raises exception on failure. Delegates to the
    WhatsAppAdapter; kept as a module function because the job queue's
    default outbound sender imports it."""
    return await WhatsAppAdapter().send_text(to=to, message=message)


@router.post("/whatsapp")
async def handle_whatsapp_webhook(request: Request):
    """
    Handles incoming webhook messages from WhatsApp Cloud API or Gateway.
    Directs messages through central router dispatching (debouncer, emergency triage, admin threadpool).
    Enforces HMAC-SHA256 signature verification via X-Hub-Signature-256 before any action or database mutation.
    Atomically ingests into durable SQLite message ledger and returns HTTP 200 immediately.
    """
    if "whatsapp" not in enabled_channels():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="WhatsApp channel is not enabled.")

    # 1. Read raw request body before JSON parsing
    raw_body = await request.body()

    # 2. Validate X-Hub-Signature-256 header using constant-time comparison
    signature_header = request.headers.get("X-Hub-Signature-256")
    if not signature_header:
        logger.warning("Rejected WhatsApp webhook request: Missing X-Hub-Signature-256 header.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-Hub-Signature-256 signature header."
        )

    app_secret = settings.WHATSAPP_APP_SECRET
    if not app_secret:
        logger.error("Rejected WhatsApp webhook request: Server-side WHATSAPP_APP_SECRET is not configured.")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Server-side Meta App Secret is not configured."
        )

    adapter = WhatsAppAdapter()
    if not adapter.verify_signature(raw_body, signature_header):
        logger.warning("Rejected WhatsApp webhook request: Invalid X-Hub-Signature-256 signature.")
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

    info = db.get_clinic_info()
    auth_phones = info.get("authorized_phones") or info.get("authorized_staff_phones") or settings.AUTHORIZED_STAFF_PHONES

    incoming = adapter.parse_incoming(body)
    enqueued_jobs = []
    for msg in incoming:
        # Non-text media: enqueue a marker job and pre-complete it with
        # the text-only notice, as before.
        if not msg.text.strip() and msg.raw_metadata.get("media_type"):
            fac_name = db.get_facility_profile().get("name", "المصحة")
            unsupported_reply = f"ℹ️ مرحباً بك في {fac_name}. نظام الاستقبال الذكي يستقبل حالياً الرسائل النصية. يرجى كتابة استفسارك نصياً لنتمكن من إفادتك فوراً."
            is_new, job_id, q_status = job_queue.enqueue_incoming_message(
                channel="whatsapp",
                message_id=msg.external_message_id,
                sender=msg.sender_id,
                message_text="[non-text media]",
                is_group=False,
                payload_json=json.dumps(msg.raw_metadata.get("msg", {}), ensure_ascii=False)
            )
            if is_new:
                with db.get_db(job_queue.db_path) as conn:
                    conn.execute("""
                        UPDATE message_jobs
                        SET processing_status = 'completed',
                            response_text = ?
                        WHERE id = ?;
                    """, (unsupported_reply, job_id))
                enqueued_jobs.append(job_id)
            continue

        # Determine if sender is an authorized staff member
        is_staff = is_phone_authorized(msg.sender_id, auth_phones)
        tagged_msg = msg.text
        if is_staff and not any(tag in msg.text.lower() for tag in ["@bot", "@بـوت", "@بوت", "@مساعد"]):
            tagged_msg = f"@Bot {msg.text}"

        # Atomically record incoming message in ledger & enqueue durable job
        is_new, job_id, q_status = job_queue.enqueue_incoming_message(
            channel="whatsapp",
            message_id=msg.external_message_id,
            sender=msg.sender_id,
            message_text=tagged_msg if is_staff else msg.text,
            is_group=is_staff,
            group_id="whatsapp_staff" if is_staff else None,
            payload_json=json.dumps(msg.raw_metadata.get("msg", {}), ensure_ascii=False)
        )

        if is_new:
            enqueued_jobs.append(job_id)
        else:
            logger.info(f"[Webhook] Duplicate message {msg.external_message_id} rejected at ledger.")

    return {
        "status": "success",
        "enqueued_count": len(enqueued_jobs),
        "enqueued_jobs": enqueued_jobs
    }
