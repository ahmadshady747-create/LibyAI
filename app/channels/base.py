"""
LibyAI Channel Abstraction Layer (`app/channels/base.py`)

One normalized message model and one adapter interface for every
inbound/outbound channel. Messenger is the PRIMARY channel, WhatsApp is
SECONDARY, and the simulator is a third channel for local testing.

Every adapter must:
- verify webhook subscriptions with a constant-time token comparison,
- verify X-Hub-Signature-256 (HMAC-SHA256) BEFORE parsing JSON,
- parse provider payloads into normalized IncomingMessage objects,
- send outbound text through the provider's API.

Deduplication across channels is (channel, external_message_id): the
same external id on two channels is two different messages.
"""

import hashlib
import hmac
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

ChannelName = Literal["messenger", "whatsapp", "simulator"]


class IncomingMessage(BaseModel):
    """One normalized inbound message, from any channel."""

    channel: ChannelName
    external_message_id: str
    sender_id: str
    text: str = ""
    timestamp: float = Field(default_factory=time.time)
    is_admin_context: bool = False
    raw_metadata: Dict[str, Any] = Field(default_factory=dict)


def verify_hmac_sha256(
    raw_body: bytes,
    signature_header: Optional[str],
    app_secret: Optional[str],
) -> bool:
    """
    Validates a Meta X-Hub-Signature-256 header using HMAC-SHA256 and a
    server-side app secret, with constant-time comparison. Fail-closed:
    a missing header, a missing secret, or a malformed header never
    verifies. Never logs or exposes secrets.
    """
    if not signature_header or not app_secret:
        return False
    if not signature_header.startswith("sha256="):
        return False
    expected_hash = hmac.new(
        key=app_secret.encode("utf-8"),
        msg=raw_body,
        digestmod=hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(signature_header, f"sha256={expected_hash}")


def compute_hmac_sha256(raw_body: bytes, app_secret: str) -> str:
    """Computes the Meta-compliant X-Hub-Signature-256 header value for a
    raw body. Used by tests and by local tooling; never in production."""
    digest = hmac.new(
        key=app_secret.encode("utf-8"),
        msg=raw_body,
        digestmod=hashlib.sha256,
    ).hexdigest()
    return f"sha256={digest}"


class ChannelAdapter(ABC):
    """Abstract adapter every channel implements."""

    channel: ChannelName

    def __init__(self, settings=None):
        from app.config import settings as global_settings

        self.settings = settings or global_settings

    @abstractmethod
    def verify_webhook(self, mode: Optional[str], token: Optional[str]) -> bool:
        """Validates a Meta webhook subscription handshake (GET)."""

    @abstractmethod
    def verify_signature(self, raw_body: bytes, signature_header: Optional[str]) -> bool:
        """Validates X-Hub-Signature-256 for a raw POST body."""

    @abstractmethod
    def parse_incoming(self, body: Dict[str, Any]) -> List[IncomingMessage]:
        """Parses a provider webhook payload into normalized messages.
        Echoes, delivery receipts, read receipts, and other non-message
        events must be dropped here, never enqueued."""

    @abstractmethod
    async def send_text(self, to: str, message: str) -> Optional[str]:
        """Sends a text reply through the provider API. Returns the
        outbound message id, or a simulated id when no provider token is
        configured (development/simulator mode)."""


def get_adapter(channel: str, settings=None) -> ChannelAdapter:
    """Returns the adapter for a channel name. Raises ValueError for an
    unknown channel."""
    name = (channel or "").strip().lower()
    if name == "messenger":
        from app.channels.messenger import MessengerAdapter

        return MessengerAdapter(settings=settings)
    if name == "whatsapp":
        from app.channels.whatsapp import WhatsAppAdapter

        return WhatsAppAdapter(settings=settings)
    raise ValueError(f"Unknown channel: {channel!r}")


async def send_via_channel(channel: str, to: str, message: str) -> Optional[str]:
    """Dispatches an outbound reply through the adapter matching the
    channel. Unknown channels fall back to the WhatsApp adapter (the
    legacy default) instead of dropping the reply."""
    try:
        adapter = get_adapter(channel)
    except ValueError:
        adapter = get_adapter("whatsapp")
    return await adapter.send_text(to=to, message=message)
