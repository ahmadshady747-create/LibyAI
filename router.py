"""
LibyAI Central Router (`router.py`)

Central message coordinator:
- Distinguishes 1:1 customer inquiries vs. Staff Admin Group messages.
- Routes group updates tagged with `@Bot` to `admin_service`.
- Dispatches 1:1 customer messages through the fast-path guardrail
  interceptor (medical Level 1 emergencies bypass the debouncer).
- Feeds routine customer inquiries into the async 2.5s debouncer buffer
  before executing `customer_service`.
- Provides the LEGACY FastAPI webhook endpoints (/whatsapp/webhook,
  /whatsapp/message). New integrations should use the channel routers
  in app/channels/ (/webhook/messenger primary, /webhook/whatsapp
  secondary). The legacy endpoints are kept for backward compatibility
  and enforce the same fail-closed HMAC verification in production.
"""

import asyncio
import hashlib
import hmac
from typing import Dict, Any, Optional
from fastapi import APIRouter, Request, Response, HTTPException, Query
from pydantic import BaseModel, Field

import db
import guardrails
import admin_service
import customer_service
from debouncer import message_debouncer
from app.config import settings

router = APIRouter(prefix="/whatsapp", tags=["WhatsApp"])


class DirectMessagePayload(BaseModel):
    sender: str = Field(description="Sender phone number, e.g. 0920202020")
    message: str = Field(description="Incoming message text")
    is_group: bool = Field(default=False, description="True if sent within WhatsApp Staff Group")
    group_id: Optional[str] = Field(default=None, description="Group ID if applicable")


async def dispatch_message(
    sender: str,
    message: str,
    is_group: bool = False,
    group_id: Optional[str] = None,
    channel: str = "whatsapp",
) -> Optional[str]:
    """
    Core business dispatch function:
    1. Directs Staff Group messages -> `admin_service` (via threadpool to prevent event loop blocking).
    2. Directs 1:1 Customer messages:
       - Immediate Emergency Red Flag bypass (zero delay, medical
         sectors only).
       - Enters debouncer (2.5s window) -> `customer_service`.
    """
    clean_text = message.strip()
    if not clean_text:
        return None

    # Path A: Staff Admin Group Message (non-blocking thread pool)
    if is_group:
        return await asyncio.to_thread(
            admin_service.handle_admin_group_message,
            sender_phone=sender,
            raw_message=clean_text,
            group_id=group_id,
            channel=channel,
        )

    # Path B: 1:1 Customer Message
    # Fast guardrail interceptor for acute emergencies (no debounce delay
    # for critical red flags; medical sectors only).
    business_profile = db.get_business_profile()
    fast_guard = guardrails.evaluate_guardrails(clean_text, business_profile)
    if fast_guard.is_emergency and fast_guard.immediate_response:
        db.save_conversation_turn(sender, "user", clean_text, channel=channel)
        db.save_conversation_turn(sender, "model", fast_guard.immediate_response, channel=channel)
        return fast_guard.immediate_response

    async def _async_customer_callback(_session_id: str, cohesive_query: str) -> str:
        """Async wrapper executing the customer service in a thread pool.

        The debouncer session id is namespaced per channel
        ("whatsapp:<sender>"), so the callback uses the real sender id
        captured from dispatch_message, not the session id.
        """
        return await asyncio.to_thread(
            customer_service.handle_customer_query,
            sender,
            cohesive_query,
            channel,
        )

    # Pass routine inquiry through asynchronous sliding debouncer
    return await message_debouncer.enqueue(
        session_id=f"{channel}:{sender}",
        message=clean_text,
        processor_callback=_async_customer_callback,
    )


# =====================================================================
# FastAPI Webhook Endpoints (Meta WhatsApp Cloud API / Simulator)
# =====================================================================

@router.get("/webhook")
async def verify_webhook(
    hub_mode: Optional[str] = Query(None, alias="hub.mode"),
    hub_verify_token: Optional[str] = Query(None, alias="hub.verify_token"),
    hub_challenge: Optional[str] = Query(None, alias="hub.challenge")
):
    """WhatsApp Cloud API webhook verification handshake."""
    verify_token = db.get_clinic_info().get("whatsapp_verify_token") or settings.WHATSAPP_VERIFY_TOKEN
    if (
        hub_mode == "subscribe"
        and hub_verify_token
        and verify_token
        and hmac.compare_digest(hub_verify_token, verify_token)
    ):
        return Response(content=hub_challenge or "", media_type="text/plain")
    raise HTTPException(status_code=403, detail="Invalid verification token")


@router.post("/webhook")
async def receive_webhook(request: Request):
    """
    Parses incoming webhook events from Meta Cloud API or direct simulator payloads.
    """
    raw_body = await request.body()

    # Production gate: this endpoint previously accepted both Meta payloads
    # and direct sender/message payloads with no signature at all, so anyone
    # could claim an authorized staff phone number and update clinic data.
    # In production every payload must carry a valid Meta HMAC signature,
    # exactly like the signed /webhook/whatsapp endpoint. Development keeps
    # the unsigned local path for simulator and gateway testing.
    # The gate runs BEFORE JSON parsing, like the signed endpoint: an
    # unauthenticated request is rejected (401/403) without the server
    # spending any work on its body.
    if settings.ENVIRONMENT.strip().lower() == "production":
        signature_header = request.headers.get("X-Hub-Signature-256")
        app_secret = settings.WHATSAPP_APP_SECRET
        if not signature_header:
            raise HTTPException(status_code=401, detail="Missing X-Hub-Signature-256 signature header.")
        if not app_secret:
            raise HTTPException(status_code=403, detail="Server-side Meta App Secret is not configured.")
        if not signature_header.startswith("sha256="):
            raise HTTPException(status_code=403, detail="Invalid webhook signature.")
        expected = "sha256=" + hmac.new(
            key=app_secret.encode("utf-8"), msg=raw_body, digestmod=hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature_header, expected):
            raise HTTPException(status_code=403, detail="Invalid webhook signature.")

    try:
        import json as _json

        body = _json.loads(raw_body) if raw_body else {}
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # Direct simplified JSON payload (e.g. from local simulator or gateway)
    if "sender" in body and "message" in body:
        sender = str(body["sender"])
        text = str(body["message"])
        is_group = bool(body.get("is_group", False))
        group_id = body.get("group_id")

        reply = await dispatch_message(sender=sender, message=text, is_group=is_group, group_id=group_id)
        return {
            "status": "processed",
            "sender": sender,
            "reply": reply
        }

    # Meta WhatsApp Cloud API standard webhook format
    entry = body.get("entry", [])
    if not entry:
        return {"status": "ignored_no_entry"}

    changes = entry[0].get("changes", [])
    if not changes:
        return {"status": "ignored_no_changes"}

    value = changes[0].get("value", {})
    messages = value.get("messages", [])
    if not messages:
        return {"status": "ignored_no_messages"}

    msg_obj = messages[0]
    sender = msg_obj.get("from", "")
    msg_type = msg_obj.get("type", "")

    if msg_type != "text":
        fac_name = db.get_facility_profile().get("name", "المصحة")
        return {
            "status": "unsupported_media_type",
            "sender": sender,
            "reply": f"ℹ️ مرحباً بك في {fac_name}. نظام الاستقبال الذكي يستقبل حالياً الرسائل النصية. يرجى كتابة استفسارك نصياً لنتمكن من إفادتك فوراً."
        }

    text = msg_obj.get("text", {}).get("body", "")
    group_id = msg_obj.get("group_id")  # Present if group webhook
    is_group = bool(group_id)

    reply = await dispatch_message(sender=sender, message=text, is_group=is_group, group_id=group_id)

    return {
        "status": "processed",
        "sender": sender,
        "reply": reply
    }


@router.post("/message")
async def direct_message_endpoint(payload: DirectMessagePayload):
    """Direct testing endpoint for simulated messages."""
    reply = await dispatch_message(
        sender=payload.sender,
        message=payload.message,
        is_group=payload.is_group,
        group_id=payload.group_id
    )
    return {
        "sender": payload.sender,
        "is_group": payload.is_group,
        "reply": reply
    }
