import os
import sys
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock

# Force UTF-8 on Windows stdout/stderr
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# Ensure Desktop directory is in sys.path
BASE_DIR = r"C:\Users\awsat\Desktop\LibyAI"
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from fastapi.testclient import TestClient
import db
from app.main import app
from app.config import settings

client = TestClient(app)

def test_webhook_verification():
    print("Testing Webhook Verification Challenge...")
    db_token = db.get_clinic_info().get("whatsapp_verify_token") or settings.WHATSAPP_VERIFY_TOKEN
    
    # Valid token
    res = client.get(f"/webhook/whatsapp?hub.mode=subscribe&hub.verify_token={db_token}&hub.challenge=test_12345")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    assert res.text == "test_12345", f"Expected challenge test_12345, got {res.text}"
    
    # Invalid token
    res_bad = client.get("/webhook/whatsapp?hub.mode=subscribe&hub.verify_token=wrong_token&hub.challenge=test_12345")
    assert res_bad.status_code == 403, f"Expected 403, got {res_bad.status_code}"
    print("✅ Webhook Verification Passed!")


import hmac
import hashlib
import json

def sign_test_payload(payload: dict) -> tuple:
    raw_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    sig = "sha256=" + hmac.new(settings.WHATSAPP_APP_SECRET.encode("utf-8"), raw_bytes, hashlib.sha256).hexdigest()
    return raw_bytes, {"X-Hub-Signature-256": sig, "Content-Type": "application/json"}


def test_webhook_unsupported_media():
    print("Testing Webhook Non-Text Media Handling...")
    from job_queue import job_queue
    with db.get_db() as conn:
        conn.cursor().execute("DELETE FROM message_jobs;")
        conn.cursor().execute("DELETE FROM incoming_messages;")
    media_payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": "218919998877",
                        "type": "audio",
                        "audio": {"id": "12345"}
                    }]
                }
            }]
        }]
    }
    raw_bytes, headers = sign_test_payload(media_payload)
    mock_send = AsyncMock(return_value="outbound_msg_id")
    res = client.post("/webhook/whatsapp", content=raw_bytes, headers=headers)
    assert res.status_code == 200
    asyncio.run(job_queue.process_next_job(send_reply_func=mock_send))
    mock_send.assert_called_once()
    args, kwargs = mock_send.call_args
    msg = kwargs.get("message", "")
    assert "يستقبل حالياً الرسائل النصية" in msg
    print("✅ Webhook Unsupported Media Handling Passed!")


def test_webhook_patient_dispatch():
    print("Testing Webhook Patient Message Unified Routing (Dispatch/Triage)...")
    from job_queue import job_queue
    with db.get_db() as conn:
        conn.cursor().execute("DELETE FROM message_jobs;")
        conn.cursor().execute("DELETE FROM incoming_messages;")
    patient_payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": "0918887766",
                        "type": "text",
                        "text": {"body": "شن مواعيد دكتور العظام؟"}
                    }]
                }
            }]
        }]
    }
    raw_bytes, headers = sign_test_payload(patient_payload)
    mock_send = AsyncMock(return_value="outbound_msg_id")
    with patch("patient_service.handle_patient_query", return_value="د. عبدالله ديهوم متاح من السبت للخميس") as mock_patient:
        res = client.post("/webhook/whatsapp", content=raw_bytes, headers=headers)
        assert res.status_code == 200
        asyncio.run(job_queue.process_next_job(send_reply_func=mock_send))
        mock_patient.assert_called_once()
        mock_send.assert_called_once_with(to="0918887766", message="د. عبدالله ديهوم متاح من السبت للخميس")
    print("✅ Webhook Patient Unified Routing Passed!")


def test_webhook_staff_dispatch():
    print("Testing Webhook Staff Message Unified Routing...")
    from job_queue import job_queue
    with db.get_db() as conn:
        conn.cursor().execute("DELETE FROM message_jobs;")
        conn.cursor().execute("DELETE FROM incoming_messages;")
    info = db.get_clinic_info()
    auth_phones = info.get("authorized_phones") or info.get("authorized_staff_phones") or settings.AUTHORIZED_STAFF_PHONES
    first_auth = [p.strip() for p in auth_phones.split(",") if p.strip()][0]
    
    staff_payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": first_auth,
                        "type": "text",
                        "text": {"body": "دكتور الباطنة وصل للعيادة"}
                    }]
                }
            }]
        }]
    }
    raw_bytes, headers = sign_test_payload(staff_payload)
    mock_send = AsyncMock(return_value="outbound_msg_id")
    with patch("admin_service.handle_admin_group_message", return_value="تم التحديث: دكتور الباطنة وصل للعيادة") as mock_admin:
        res = client.post("/webhook/whatsapp", content=raw_bytes, headers=headers)
        assert res.status_code == 200
        asyncio.run(job_queue.process_next_job(send_reply_func=mock_send))
        mock_admin.assert_called_once()
        d_args, d_kwargs = mock_admin.call_args
        assert "@Bot" in d_kwargs.get("raw_message")
        mock_send.assert_called_once_with(to=first_auth, message="تم التحديث: دكتور الباطنة وصل للعيادة")
    print("✅ Webhook Staff Unified Routing Passed!")


def test_simulator_state_resilience():
    print("Testing /api/simulator/state Audit Log Schema Resilience...")
    # Add a log entry in raw DB
    with db.get_db() as conn:
        conn.cursor().execute("""
        INSERT INTO audit_logs (admin_sender, raw_message, status_before, status_after, confirmation_text)
        VALUES (?, ?, ?, ?, ?);
        """, ("0912345678", "تعديل تجريبي", "{}", "{}", "تم التعديل بنجاح"))
        
    res = client.get("/api/simulator/state")
    assert res.status_code == 200
    data = res.json()
    assert "doctors" in data
    assert "services" in data
    assert "logs" in data
    assert len(data["logs"]) > 0
    # Check that schema fields exist
    first_log = data["logs"][0]
    assert "sender" in first_log
    assert "confirmation_sent" in first_log
    print("✅ Simulator State Resilience Passed!")


def test_database_cleanup():
    print("Testing Session Cleanup...")
    # Insert an old session
    with db.get_db() as conn:
        conn.cursor().execute("""
        INSERT INTO conversation_sessions (phone_number, role, message_text, created_at)
        VALUES ('0999999999', 'user', 'مرحبا قديم', 1000);
        """)
    cleaned = db.cleanup_expired_sessions(ttl_minutes=120)
    assert cleaned >= 1, f"Expected at least 1 cleaned session, got {cleaned}"
    print(f"✅ Session Cleanup Passed! (Cleaned {cleaned} sessions)")


def test_cors_configuration():
    print("Testing CORS Middleware Headers...")
    res = client.options("/health", headers={
        "Origin": "http://localhost:3000",
        "Access-Control-Request-Method": "GET"
    })
    # CORS is now explicit-origin only (localhost:3000 is in the default
    # allow-list), so the preflight must echo that origin, not "*", and
    # credentials must still be absent.
    assert res.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert res.headers.get("access-control-allow-credentials") is None
    print("✅ CORS Configuration Passed!")


if __name__ == "__main__":
    print("=== STARTING PHASE 3 VERIFICATION TESTS ===")
    test_webhook_verification()
    test_webhook_unsupported_media()
    test_webhook_patient_dispatch()
    test_webhook_staff_dispatch()
    test_simulator_state_resilience()
    test_database_cleanup()
    test_cors_configuration()
    print("🎉 ALL PHASE 3 & 4 VERIFICATION TESTS PASSED SUCCESSFULLY! 🎉")
