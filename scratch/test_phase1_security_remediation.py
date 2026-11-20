import os
import sys
import hmac
import hashlib
import json
from unittest.mock import patch

# Force UTF-8 on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

BASE_DIR = r"C:\Users\awsat\Desktop\LibyAI"
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from fastapi.testclient import TestClient
from app.main import app
from app.config import settings
import db

client = TestClient(app)

def sign_payload(body_bytes: bytes, secret: str) -> str:
    """Computes Meta-compliant HMAC-SHA256 signature."""
    digest = hmac.new(secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def test_missing_signature():
    print("--- 1. Testing Webhook Missing Signature ---")
    payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": "0920202020",
                        "type": "text",
                        "text": {"body": "مرحبا"}
                    }]
                }
            }]
        }]
    }
    # Send without X-Hub-Signature-256 header
    res = client.post("/webhook/whatsapp", json=payload)
    assert res.status_code in (401, 403), f"Expected 401 or 403, got {res.status_code}: {res.text}"
    print(f"✅ Missing signature rejected with status {res.status_code}!")


def test_invalid_signature():
    print("--- 2. Testing Webhook Invalid Signature ---")
    raw_body = b'{"test": "payload"}'
    headers = {
        "X-Hub-Signature-256": "sha256=0000000000000000000000000000000000000000000000000000000000000000",
        "Content-Type": "application/json"
    }
    res = client.post("/webhook/whatsapp", content=raw_body, headers=headers)
    assert res.status_code == 403, f"Expected 403, got {res.status_code}: {res.text}"
    print("✅ Invalid signature rejected with status 403!")


def test_valid_signature_against_raw_body():
    print("--- 3. Testing Webhook Valid Signature Against Raw Body ---")
    payload = {
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
    raw_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    valid_sig = sign_payload(raw_bytes, settings.WHATSAPP_APP_SECRET)

    headers = {
        "X-Hub-Signature-256": valid_sig,
        "Content-Type": "application/json"
    }
    from job_queue import job_queue
    with patch.object(job_queue, "enqueue_incoming_message", wraps=job_queue.enqueue_incoming_message) as mock_enqueue:
        res = client.post("/webhook/whatsapp", content=raw_bytes, headers=headers)
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        mock_enqueue.assert_called_once()
    print("✅ Valid signature accepted with status 200 and enqueued into job queue!")


def test_payload_tampering_after_signing():
    print("--- 4. Testing Webhook Payload Modification After Signing ---")
    original_payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": "0918887766",
                        "type": "text",
                        "text": {"body": "رسالة أصلية"}
                    }]
                }
            }]
        }]
    }
    original_bytes = json.dumps(original_payload, ensure_ascii=False).encode("utf-8")
    # Sign original payload
    sig = sign_payload(original_bytes, settings.WHATSAPP_APP_SECRET)

    # Tamper with the content
    tampered_payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": "0920202020", # attacker changed sender to staff
                        "type": "text",
                        "text": {"body": "@Bot دكتور العظام روح"}
                    }]
                }
            }]
        }]
    }
    tampered_bytes = json.dumps(tampered_payload, ensure_ascii=False).encode("utf-8")

    # Send tampered bytes with original signature
    headers = {
        "X-Hub-Signature-256": sig,
        "Content-Type": "application/json"
    }
    res = client.post("/webhook/whatsapp", content=tampered_bytes, headers=headers)
    assert res.status_code == 403, f"Expected 403, got {res.status_code}: {res.text}"
    print("✅ Tampered payload with stale signature strictly rejected with status 403!")


def test_unauthorized_clinic_settings_access():
    print("--- 5. Testing Unauthorized Clinic Settings Access ---")
    # Simulate production environment
    orig_env = settings.ENVIRONMENT
    orig_enabled = settings.ENABLE_PROD_SIMULATOR
    try:
        settings.ENVIRONMENT = "production"
        settings.ENABLE_PROD_SIMULATOR = False

        payload = {
            "clinic_name": "مصحة تم اختراقها",
            "address": "عنوان مخترق",
            "emergency_phone": "0999999999",
            "reception_phone": "0999999999",
            "booking_policy": "سياسة ملغاة",
            "authorized_phones": "0999999999"
        }

        # 1. Access in production without simulator enabled
        res = client.post("/api/simulator/clinic-settings", json=payload)
        assert res.status_code == 403, f"Expected 403 in production, got {res.status_code}: {res.text}"

        # 2. Access in production with simulator enabled but wrong admin key
        settings.ENABLE_PROD_SIMULATOR = True
        res_bad_key = client.post("/api/simulator/clinic-settings", json=payload, headers={"x-admin-key": "wrong_key"})
        assert res_bad_key.status_code == 403, f"Expected 403 with wrong key, got {res_bad_key.status_code}"

        # 3. Access in production with valid admin key should succeed
        res_valid = client.post("/api/simulator/clinic-settings", json=payload, headers={"x-admin-key": settings.ADMIN_SECRET_KEY})
        assert res_valid.status_code == 200, f"Expected 200 with valid admin key, got {res_valid.status_code}"
    finally:
        settings.ENVIRONMENT = orig_env
        settings.ENABLE_PROD_SIMULATOR = orig_enabled
        # Restore exact default clinic settings and authorized phones
        default_phones = "0920202020, 0921111111, 218912345678"
        db.update_clinic_info_key("authorized_phones", default_phones)
        db.update_clinic_info_key("authorized_staff_phones", default_phones)
        db.update_clinic_info_key("clinic_name", "مصحة الشفاء التخصصية")
        db.update_clinic_info_key("name", "مصحة الشفاء التخصصية")
        settings.AUTHORIZED_STAFF_PHONES = default_phones
        settings.CLINIC_NAME = "مصحة الشفاء التخصصية"

    print("✅ Unauthorized clinic settings access prevented in production!")


def test_attempt_to_add_administrator_unauthorized():
    print("--- 6. Testing Unauthorized Attempt to Add Administrator ---")
    orig_env = settings.ENVIRONMENT
    orig_enabled = settings.ENABLE_PROD_SIMULATOR
    
    # Snapshot authorized phones before
    initial_info = db.get_clinic_info()
    initial_auth_phones = initial_info.get("authorized_phones") or initial_info.get("authorized_staff_phones")

    try:
        settings.ENVIRONMENT = "production"
        settings.ENABLE_PROD_SIMULATOR = False

        malicious_payload = {
            "clinic_name": initial_info.get("name", "مصحة الشفاء"),
            "address": initial_info.get("address", "طرابلس"),
            "emergency_phone": "091-0000000",
            "reception_phone": "092-1111111",
            "booking_policy": "الحجز المباشر",
            "authorized_phones": "0999999999, 0988888888" # Malicious attacker phones
        }

        # Attempt to escalate privileges without authorization
        res = client.post("/api/simulator/clinic-settings", json=malicious_payload)
        assert res.status_code == 403

        # Verify DB was NOT modified
        current_info = db.get_clinic_info()
        current_auth_phones = current_info.get("authorized_phones") or current_info.get("authorized_staff_phones")
        assert current_auth_phones == initial_auth_phones, f"DB modified! Expected {initial_auth_phones}, got {current_auth_phones}"
        print(f"✅ Privilege escalation blocked! DB remains intact: '{current_auth_phones}'")
    finally:
        settings.ENVIRONMENT = orig_env
        settings.ENABLE_PROD_SIMULATOR = orig_enabled


def test_rejected_requests_cause_no_side_effects():
    print("--- 7. Testing Rejected Webhook Causes No Side Effects ---")
    # Make sure doctor exists and is available
    doctor = db.find_doctor_fuzzy(name_query="ديهوم")
    assert doctor is not None
    initial_status = doctor["status"]

    with db.get_db() as conn:
        initial_log_count = conn.cursor().execute("SELECT COUNT(*) AS cnt FROM audit_logs;").fetchone()["cnt"]

    # Attacker tries to forge staff message with invalid signature
    malicious_staff_payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": "0920202020", # legitimate staff phone
                        "type": "text",
                        "text": {"body": "@Bot دكتور ديهوم اعتذر اليوم"}
                    }]
                }
            }]
        }]
    }
    raw_bytes = json.dumps(malicious_staff_payload).encode("utf-8")
    fake_headers = {
        "X-Hub-Signature-256": "sha256=badbadbadbadbadbadbadbadbadbadbadbadbadbadbadbadbadbadbadbadbadbad",
        "Content-Type": "application/json"
    }

    res = client.post("/webhook/whatsapp", content=raw_bytes, headers=fake_headers)
    assert res.status_code == 403

    # Verify doctor status was NOT changed
    doc_after = db.find_doctor_fuzzy(name_query="ديهوم")
    assert doc_after["status"] == initial_status, f"Side effect detected! Doctor status changed to {doc_after['status']}"

    # Verify no audit log was created
    with db.get_db() as conn:
        current_log_count = conn.cursor().execute("SELECT COUNT(*) AS cnt FROM audit_logs;").fetchone()["cnt"]
    assert current_log_count == initial_log_count, f"Side effect detected! Audit log count grew from {initial_log_count} to {current_log_count}"

    print(f"✅ Zero side effects verified: Doctor status unchanged ({initial_status}), audit logs unchanged ({current_log_count}).")


if __name__ == "__main__":
    print("=== STARTING PHASE 1 SECURITY REMEDIATION TESTS ===")
    test_missing_signature()
    test_invalid_signature()
    test_valid_signature_against_raw_body()
    test_payload_tampering_after_signing()
    test_unauthorized_clinic_settings_access()
    test_attempt_to_add_administrator_unauthorized()
    test_rejected_requests_cause_no_side_effects()
    print("🎉 ALL PHASE 1 SECURITY REMEDIATION TESTS PASSED 100%! 🎉")
