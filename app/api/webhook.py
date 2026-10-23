import asyncio
import hmac
import hashlib
import json
import logging
from typing import Optional
from fastapi import APIRouter, Request, Response, HTTPException, status
from app.config import settings, is_phone_authorized
import db
import admin_service
import patient_service
import httpx

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhook", tags=["WhatsApp Webhook"])


def verify_meta_signature(raw_body: bytes, signature_header: Optional[str], app_secret: Optional[str]) -> bool:
    """
    Validates Meta WhatsApp Webhook 'X-Hub-Signature-256' using HMAC-SHA256 and server-side App Secret.
    Enforces constant-time comparison via hmac.compare_digest.
    Never logs or exposes secrets.
    """
    if not signature_header or not app_secret:
        return False
    if not signature_header.startswith("sha256="):
        return False

    expected_hash = hmac.new(
        key=app_secret.encode("utf-8"),
        msg=raw_body,
        digestmod=hashlib.sha256
    ).hexdigest()

    expected_header = f"sha256={expected_hash}"
    return hmac.compare_digest(signature_header, expected_header)


@router.get("/whatsapp")
async def verify_webhook(request: Request):
    """WhatsApp Cloud API Webhook Verification Challenge."""
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    verify_token = db.get_clinic_info().get("whatsapp_verify_token") or settings.WHATSAPP_VERIFY_TOKEN
    if mode == "subscribe" and token == verify_token:
        return Response(content=challenge, media_type="text/plain")
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Verification failed")


async def send_whatsapp_reply(to: str, message: str) -> Optional[str]:
    """Sends text message back via WhatsApp Cloud API. Returns outbound message ID or raises exception on failure."""
    if not settings.WHATSAPP_TOKEN or not settings.WHATSAPP_PHONE_NUMBER_ID:
        logger.info(f"[SIMULATED WHATSAPP OUTGOING] To: {to} | Message: {message}")
        return "simulated_msg_id"

    url = f"https://graph.facebook.com/v21.0/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {settings.WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": message}
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(url, json=payload, headers=headers)
        r.raise_for_status()
        data = r.json()
        outbound_id = None
        if "messages" in data and len(data["messages"]) > 0:
            outbound_id = data["messages"][0].get("id")
        return outbound_id or "sent"


@router.post("/whatsapp")
async def handle_whatsapp_webhook(request: Request):
    """
    Handles incoming webhook messages from WhatsApp Cloud API or Gateway.
    Directs messages through central router dispatching (debouncer, emergency triage, admin threadpool).
    Enforces HMAC-SHA256 signature verification via X-Hub-Signature-256 before any action or database mutation.
    Atomically ingests into durable SQLite message ledger and returns HTTP 200 immediately.
    """
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

    if not verify_meta_signature(raw_body, signature_header, app_secret):
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

    entry = body.get("entry", [])
    enqueued_jobs = []
    for e in entry:
        changes = e.get("changes", [])
        for ch in changes:
            value = ch.get("value", {})
            messages = value.get("messages", [])
            for msg in messages:
                # 1. Extract Meta's unique message ID (wamid)
                wamid = str(msg.get("id", "")).strip()
                if not wamid:
                    wamid = f"wamid_fallback_{hashlib.sha256((str(msg.get('from', '')) + str(msg.get('timestamp', '')) + str(msg.get('text', {}).get('body', ''))).encode('utf-8')).hexdigest()[:20]}"

                sender_phone = str(msg.get("from", ""))
                msg_type = msg.get("type")

                # Handle non-text media
                if msg_type != "text":
                    fac_name = db.get_facility_profile().get("name", "المصحة")
                    unsupported_reply = f"ℹ️ مرحباً بك في {fac_name}. نظام الاستقبال الذكي يستقبل حالياً الرسائل النصية. يرجى كتابة استفسارك نصياً لنتمكن من إفادتك فوراً."
                    is_new, job_id, q_status = job_queue.enqueue_incoming_message(
                        provider="whatsapp",
                        message_id=wamid,
                        sender=sender_phone,
                        message_text="[non-text media]",
                        is_group=False,
                        payload_json=json.dumps(msg, ensure_ascii=False)
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

                text_body = msg.get("text", {}).get("body", "")
                if not text_body.strip():
                    continue

                # 2. Determine if sender is an authorized staff member
                is_staff = is_phone_authorized(sender_phone, auth_phones)
                tagged_msg = text_body
                if is_staff and not any(tag in text_body.lower() for tag in ["@bot", "@بـوت", "@بوت", "@مساعد"]):
                    tagged_msg = f"@Bot {text_body}"

                # 3. Atomically record incoming message in ledger & enqueue durable job
                is_new, job_id, q_status = job_queue.enqueue_incoming_message(
                    provider="whatsapp",
                    message_id=wamid,
                    sender=sender_phone,
                    message_text=tagged_msg if is_staff else text_body,
                    is_group=is_staff,
                    group_id="whatsapp_staff" if is_staff else None,
                    payload_json=json.dumps(msg, ensure_ascii=False)
                )

                if is_new:
                    enqueued_jobs.append(job_id)
                else:
                    logger.info(f"[Webhook] Duplicate message {wamid} rejected at ledger.")

    return {
        "status": "success",
        "enqueued_count": len(enqueued_jobs),
        "enqueued_jobs": enqueued_jobs
    }
