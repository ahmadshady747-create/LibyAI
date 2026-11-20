"""Channel tests (Messenger-first pivot).

Covers the Messenger webhook (primary) and the WhatsApp webhook
(secondary) end to end through the FastAPI app: verification handshake,
fail-closed HMAC-SHA256, echo/receipt filtering, channel-scoped
deduplication, staff PSID tagging, disabled-channel 404s, and
Messenger-only production boot.

These tests share the repo's clinic.db like the other root tests; every
test uses a unique external message id so deduplication never leaks
between tests, and the queue tables are cleaned before each test.
"""

import asyncio
import hashlib
import hmac
import json
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest
from fastapi.testclient import TestClient

import db
from app.config import Settings, settings, validate_production_security
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clean_queue():
    with db.get_db() as conn:
        conn.execute("DELETE FROM message_jobs;")
        conn.execute("DELETE FROM incoming_messages;")
    yield
    with db.get_db() as conn:
        conn.execute("DELETE FROM message_jobs;")
        conn.execute("DELETE FROM incoming_messages;")


def _sign(body_bytes: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _messenger_token() -> str:
    return (
        db.get_clinic_info().get("messenger_verify_token")
        or settings.MESSENGER_VERIFY_TOKEN
    )


def _messenger_payload(mid, sender_psid, text=None, echo=False,
                       delivery=False, read=False, attachments=None):
    messaging = {
        "sender": {"id": sender_psid},
        "recipient": {"id": "page_1"},
        "timestamp": 1700000000000,
    }
    if delivery:
        messaging["delivery"] = {"mids": [mid], "watermark": 1700000000000}
    elif read:
        messaging["read"] = {"watermark": 1700000000000}
    else:
        msg = {"mid": mid}
        if echo:
            msg["is_echo"] = True
        if text is not None:
            msg["text"] = text
        if attachments:
            msg["attachments"] = attachments
        messaging["message"] = msg
    return {
        "object": "page",
        "entry": [{"id": "page_1", "time": 1700000000000, "messaging": [messaging]}],
    }


def _whatsapp_payload(wamid, sender, text):
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "1",
            "changes": [{
                "field": "messages",
                "value": {"messages": [{
                    "from": sender,
                    "id": wamid,
                    "timestamp": "1700000000",
                    "type": "text",
                    "text": {"body": text},
                }]},
            }],
        }],
    }


def _post_messenger(payload, secret=None, with_signature=True):
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if with_signature:
        headers["X-Hub-Signature-256"] = _sign(
            raw, secret if secret is not None else settings.MESSENGER_APP_SECRET
        )
    return client.post("/webhook/messenger", content=raw, headers=headers)


def _post_whatsapp(payload):
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "X-Hub-Signature-256": _sign(raw, settings.WHATSAPP_APP_SECRET),
    }
    return client.post("/webhook/whatsapp", content=raw, headers=headers)


def _jobs():
    with db.get_db() as conn:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT channel, message_id, sender, message_text, is_group, group_id "
                "FROM message_jobs ORDER BY id;"
            ).fetchall()
        ]


# -------------------------------------------------------------------
# Messenger verification handshake (GET)
# -------------------------------------------------------------------
def test_messenger_verify_success():
    res = client.get(
        "/webhook/messenger",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": _messenger_token(),
            "hub.challenge": "challenge_123",
        },
    )
    assert res.status_code == 200
    assert res.text == "challenge_123"


def test_messenger_verify_wrong_token():
    res = client.get(
        "/webhook/messenger",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "definitely-wrong-token",
            "hub.challenge": "challenge_123",
        },
    )
    assert res.status_code == 403


def test_messenger_verify_wrong_mode():
    res = client.get(
        "/webhook/messenger",
        params={
            "hub.mode": "unsubscribe",
            "hub.verify_token": _messenger_token(),
            "hub.challenge": "challenge_123",
        },
    )
    assert res.status_code == 403


# -------------------------------------------------------------------
# Messenger signature verification (POST) — fail-closed, before parsing
# -------------------------------------------------------------------
def test_messenger_post_valid_signature_enqueues():
    mid = f"m_test_{uuid.uuid4().hex}"
    res = _post_messenger(_messenger_payload(mid, "psid_1001", "بكم الشاشة؟"))
    assert res.status_code == 200
    assert res.json()["enqueued_count"] == 1
    jobs = _jobs()
    assert len(jobs) == 1
    assert jobs[0]["channel"] == "messenger"
    assert jobs[0]["message_id"] == mid
    assert jobs[0]["sender"] == "psid_1001"
    assert jobs[0]["message_text"] == "بكم الشاشة؟"


def test_messenger_post_missing_signature_401():
    mid = f"m_test_{uuid.uuid4().hex}"
    res = _post_messenger(
        _messenger_payload(mid, "psid_1001", "مرحبا"), with_signature=False
    )
    assert res.status_code == 401
    assert _jobs() == []


def test_messenger_post_invalid_signature_403():
    mid = f"m_test_{uuid.uuid4().hex}"
    res = _post_messenger(
        _messenger_payload(mid, "psid_1001", "مرحبا"), secret="wrong-secret"
    )
    assert res.status_code == 403
    assert _jobs() == []


def test_messenger_post_invalid_json_after_valid_signature_400():
    raw = b"{not json"
    headers = {
        "Content-Type": "application/json",
        "X-Hub-Signature-256": _sign(raw, settings.MESSENGER_APP_SECRET),
    }
    res = client.post("/webhook/messenger", content=raw, headers=headers)
    assert res.status_code == 400


# -------------------------------------------------------------------
# Echo / receipt / non-text filtering (no reply loops)
# -------------------------------------------------------------------
def test_messenger_echo_ignored():
    mid = f"m_test_{uuid.uuid4().hex}"
    res = _post_messenger(
        _messenger_payload(mid, "psid_1001", "بكم الشاشة؟", echo=True)
    )
    assert res.status_code == 200
    assert res.json()["enqueued_count"] == 0
    assert _jobs() == []


def test_messenger_delivery_and_read_receipts_ignored():
    mid = f"m_test_{uuid.uuid4().hex}"
    res = _post_messenger(_messenger_payload(mid, "psid_1001", delivery=True))
    assert res.status_code == 200
    assert res.json()["enqueued_count"] == 0
    res = _post_messenger(_messenger_payload(mid, "psid_1001", read=True))
    assert res.status_code == 200
    assert res.json()["enqueued_count"] == 0
    assert _jobs() == []


def test_messenger_attachment_only_ignored():
    mid = f"m_test_{uuid.uuid4().hex}"
    res = _post_messenger(_messenger_payload(
        mid, "psid_1001",
        attachments=[{"type": "image", "payload": {"url": "https://example.invalid/x.jpg"}}],
    ))
    assert res.status_code == 200
    assert res.json()["enqueued_count"] == 0
    assert _jobs() == []


# -------------------------------------------------------------------
# Channel-scoped deduplication
# -------------------------------------------------------------------
def test_messenger_duplicate_mid_enqueued_once():
    mid = f"m_test_{uuid.uuid4().hex}"
    payload = _messenger_payload(mid, "psid_1001", "بكم الشاشة؟")
    assert _post_messenger(payload).json()["enqueued_count"] == 1
    assert _post_messenger(payload).json()["enqueued_count"] == 0
    assert len(_jobs()) == 1


def test_same_external_id_on_both_channels_is_two_messages():
    shared_id = f"shared_{uuid.uuid4().hex}"
    res_m = _post_messenger(_messenger_payload(shared_id, "psid_1001", "مرحبا من ماسنجر"))
    res_w = _post_whatsapp(_whatsapp_payload(shared_id, "0918887766", "مرحبا من واتساب"))
    assert res_m.status_code == 200 and res_m.json()["enqueued_count"] == 1
    assert res_w.status_code == 200 and res_w.json()["enqueued_count"] == 1
    jobs = _jobs()
    assert len(jobs) == 2
    assert {j["channel"] for j in jobs} == {"messenger", "whatsapp"}


# -------------------------------------------------------------------
# WhatsApp secondary: independent, and alongside Messenger
# -------------------------------------------------------------------
def test_whatsapp_post_valid_signature_enqueues_with_channel():
    wamid = f"wamid.test_{uuid.uuid4().hex}"
    res = _post_whatsapp(_whatsapp_payload(wamid, "0918887766", "شن مواعيد دكتور العظام؟"))
    assert res.status_code == 200
    assert res.json()["enqueued_count"] == 1
    jobs = _jobs()
    assert len(jobs) == 1
    assert jobs[0]["channel"] == "whatsapp"
    assert jobs[0]["message_id"] == wamid


def test_whatsapp_and_messenger_both_live_in_one_app():
    mid = f"m_test_{uuid.uuid4().hex}"
    wamid = f"wamid.test_{uuid.uuid4().hex}"
    assert _post_messenger(_messenger_payload(mid, "psid_1001", "مرحبا")).status_code == 200
    assert _post_whatsapp(_whatsapp_payload(wamid, "0918887766", "مرحبا")).status_code == 200
    assert len(_jobs()) == 2


# -------------------------------------------------------------------
# Staff PSID tagging
# -------------------------------------------------------------------
def test_messenger_staff_psid_tagged_bot():
    psid = f"test_psid_staff_{uuid.uuid4().hex[:8]}"
    old = db.get_clinic_info().get("authorized_messenger_psids") or ""
    db.update_clinic_info_key(
        "authorized_messenger_psids",
        f"{old},{psid}" if old else psid,
    )
    try:
        mid = f"m_test_{uuid.uuid4().hex}"
        res = _post_messenger(_messenger_payload(mid, psid, "سعر الشاشة صار 350 دينار"))
        assert res.status_code == 200
        assert res.json()["enqueued_count"] == 1
        jobs = _jobs()
        assert len(jobs) == 1
        assert jobs[0]["message_text"].startswith("@Bot")
        assert jobs[0]["is_group"] == 1
        assert jobs[0]["group_id"] == "messenger_staff"
    finally:
        db.update_clinic_info_key("authorized_messenger_psids", old)


def test_messenger_unknown_psid_not_tagged():
    mid = f"m_test_{uuid.uuid4().hex}"
    res = _post_messenger(_messenger_payload(mid, "psid_unknown_9999", "سعر الشاشة صار 350 دينار"))
    assert res.status_code == 200
    jobs = _jobs()
    assert len(jobs) == 1
    assert not jobs[0]["message_text"].startswith("@Bot")
    assert jobs[0]["is_group"] == 0


# -------------------------------------------------------------------
# Disabled channel → 404
# -------------------------------------------------------------------
def test_disabled_messenger_returns_404(monkeypatch):
    monkeypatch.setattr(settings, "ENABLED_CHANNELS", "whatsapp")
    res = client.get(
        "/webhook/messenger",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": _messenger_token(),
            "hub.challenge": "challenge_123",
        },
    )
    assert res.status_code == 404
    mid = f"m_test_{uuid.uuid4().hex}"
    res = _post_messenger(_messenger_payload(mid, "psid_1001", "مرحبا"))
    assert res.status_code == 404
    assert _jobs() == []


def test_disabled_whatsapp_returns_404(monkeypatch):
    monkeypatch.setattr(settings, "ENABLED_CHANNELS", "messenger")
    wamid = f"wamid.test_{uuid.uuid4().hex}"
    res = _post_whatsapp(_whatsapp_payload(wamid, "0918887766", "مرحبا"))
    assert res.status_code == 404
    assert _jobs() == []


# -------------------------------------------------------------------
# Production boot: Messenger-only, and no channel
# -------------------------------------------------------------------
def test_messenger_only_production_boot_passes_validation():
    cfg = Settings(
        ENVIRONMENT="production",
        ENABLED_CHANNELS="messenger",
        MESSENGER_APP_SECRET="strong-test-messenger-secret-123",
        WHATSAPP_APP_SECRET=None,
    )
    validate_production_security(cfg)  # must not raise


def test_no_channel_production_boot_fails_validation():
    cfg = Settings(
        ENVIRONMENT="production",
        ENABLED_CHANNELS="",
        MESSENGER_APP_SECRET="strong-test-messenger-secret-123",
        WHATSAPP_APP_SECRET="strong-test-whatsapp-secret-123",
    )
    with pytest.raises(RuntimeError, match="CRITICAL SECURITY CONFIGURATION ERROR"):
        validate_production_security(cfg)


def test_enabled_channel_with_dev_default_secret_fails_validation():
    from app.config import DEV_DEFAULT_APP_SECRET

    cfg = Settings(
        ENVIRONMENT="production",
        ENABLED_CHANNELS="messenger",
        MESSENGER_APP_SECRET=DEV_DEFAULT_APP_SECRET,
    )
    with pytest.raises(RuntimeError, match="CRITICAL SECURITY CONFIGURATION ERROR"):
        validate_production_security(cfg)


# -------------------------------------------------------------------
# Outbound: simulated send without a page token (no network)
# -------------------------------------------------------------------
def test_messenger_send_text_simulated_without_token(monkeypatch):
    from app.channels.messenger import MessengerAdapter

    monkeypatch.setattr(settings, "MESSENGER_PAGE_ACCESS_TOKEN", None)
    result = asyncio.run(MessengerAdapter().send_text("psid_1001", "مرحبا"))
    assert result == "simulated_msg_id"


def test_whatsapp_send_text_simulated_without_token(monkeypatch):
    from app.channels.whatsapp import WhatsAppAdapter

    monkeypatch.setattr(settings, "WHATSAPP_TOKEN", None)
    result = asyncio.run(WhatsAppAdapter().send_text("0918887766", "مرحبا"))
    assert result == "simulated_msg_id"
