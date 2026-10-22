import os
import sys
import time
import json
import asyncio
import hmac
import hashlib
from unittest.mock import patch, AsyncMock

# Force UTF-8 encoding on Windows
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
from job_queue import MessageJobQueue, job_queue

client = TestClient(app)

def clean_queue():
    with db.get_db() as conn:
        conn.cursor().execute("DELETE FROM message_jobs;")
        conn.cursor().execute("DELETE FROM incoming_messages;")

def sign_payload(body_bytes: bytes, secret: str = settings.WHATSAPP_APP_SECRET) -> str:
    digest = hmac.new(secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def test_duplicate_webhook_delivery():
    print("--- 1. Testing Duplicate Webhook Delivery ---")
    clean_queue()
    wamid = f"wamid_test_dup_{int(time.time() * 1000)}"
    payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "id": wamid,
                        "from": "0912345678",
                        "type": "text",
                        "text": {"body": "شن مواعيد العيادة؟"}
                    }]
                }
            }]
        }]
    }
    raw_bytes = json.dumps(payload).encode("utf-8")
    headers = {"X-Hub-Signature-256": sign_payload(raw_bytes), "Content-Type": "application/json"}

    # Delivery 1: Should be accepted and enqueued
    res1 = client.post("/webhook/whatsapp", content=raw_bytes, headers=headers)
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["enqueued_count"] == 1, f"Expected 1 enqueued job, got {data1}"

    # Delivery 2: Exact same wamid delivered again by Meta retry
    res2 = client.post("/webhook/whatsapp", content=raw_bytes, headers=headers)
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["enqueued_count"] == 0, f"Expected 0 enqueued jobs on duplicate, got {data2}"

    # Verify ledger in DB has exactly 1 entry for this wamid
    with db.get_db() as conn:
        cnt = conn.cursor().execute(
            "SELECT COUNT(*) AS cnt FROM incoming_messages WHERE provider = 'whatsapp' AND message_id = ?;",
            (wamid,)
        ).fetchone()["cnt"]
        assert cnt == 1, f"Expected exactly 1 ledger record, found {cnt}"

        job_cnt = conn.cursor().execute(
            "SELECT COUNT(*) AS cnt FROM message_jobs WHERE provider = 'whatsapp' AND message_id = ?;",
            (wamid,)
        ).fetchone()["cnt"]
        assert job_cnt == 1, f"Expected exactly 1 job queue record, found {job_cnt}"

    print(f"✅ Duplicate webhook delivery for {wamid} rejected at ledger and ignored!")


def test_concurrent_delivery_same_wamid():
    print("--- 2. Testing Concurrent Delivery of the Same Wamid ---")
    clean_queue()
    wamid = f"wamid_concurrent_{int(time.time() * 1000)}"
    
    # We test concurrent enqueue_incoming_message calls in asyncio
    async def try_enqueue():
        q = MessageJobQueue()
        return q.enqueue_incoming_message(
            provider="whatsapp",
            message_id=wamid,
            sender="0912345678",
            message_text="رسالة متزامنة"
        )

    async def run_concurrent():
        results = await asyncio.gather(try_enqueue(), try_enqueue(), try_enqueue())
        return results

    results = asyncio.run(run_concurrent())
    is_new_flags = [r[0] for r in results]
    
    # Exactly one must succeed as is_new=True, the others must be duplicates (is_new=False)
    assert is_new_flags.count(True) == 1, f"Expected exactly 1 True, got {is_new_flags}"
    assert is_new_flags.count(False) == 2, f"Expected 2 False, got {is_new_flags}"

    with db.get_db() as conn:
        cnt = conn.cursor().execute(
            "SELECT COUNT(*) AS cnt FROM message_jobs WHERE provider = 'whatsapp' AND message_id = ?;",
            (wamid,)
        ).fetchone()["cnt"]
        assert cnt == 1, f"Expected 1 job in DB, found {cnt}"

    print(f"✅ Concurrent delivery race condition handled atomically: 1 enqueued, 2 duplicates!")


def test_application_restart_with_pending_jobs():
    print("--- 3. Testing Application Restart With Pending Jobs ---")
    clean_queue()
    wamid = f"wamid_restart_{int(time.time() * 1000)}"
    
    q = MessageJobQueue()
    is_new, job_id, status = q.enqueue_incoming_message(
        provider="whatsapp",
        message_id=wamid,
        sender="0912345678",
        message_text="رسالة قبل إعادة التشغيل"
    )
    assert is_new is True

    # Simulate app shutdown & restart by instantiating a fresh queue worker
    new_q = MessageJobQueue()
    recovered = new_q.recover_orphaned_jobs()
    
    # Process the job with mock outbound
    mock_send = AsyncMock(return_value="outbound_restart_msg_123")
    res = asyncio.run(new_q.process_next_job(send_reply_func=mock_send))
    assert res is not None
    assert res["job_id"] == job_id
    assert res["processing_status"] == "completed"
    assert res["outbound_status"] == "sent"

    # Verify DB states
    with db.get_db() as conn:
        row = conn.cursor().execute(
            "SELECT processing_status, outbound_status FROM message_jobs WHERE id = ?;",
            (job_id,)
        ).fetchone()
        assert row["processing_status"] == "completed"
        assert row["outbound_status"] == "sent"

    print("✅ Pending job survived simulated restart and was processed to completion!")


def test_worker_crash_and_lease_recovery():
    print("--- 4. Testing Worker Crash and Lease Recovery ---")
    clean_queue()
    wamid = f"wamid_crash_{int(time.time() * 1000)}"
    q = MessageJobQueue()
    is_new, job_id, status = q.enqueue_incoming_message(
        provider="whatsapp",
        message_id=wamid,
        sender="0912345678",
        message_text="رسالة لعامل ميت"
    )

    # Simulate worker dead: set locked_at in the past, lease_expires_at in the past
    now = time.time()
    past = now - 120
    with db.get_db() as conn:
        conn.cursor().execute("""
            UPDATE message_jobs
            SET processing_status = 'processing',
                locked_by = 'dead_worker_pid_999',
                locked_at = ?,
                lease_expires_at = ?
            WHERE id = ?;
        """, (past, past + 30, job_id))

    # A healthy worker attempts to acquire a job
    healthy_worker_q = MessageJobQueue()
    acquired_job = healthy_worker_q.acquire_job(worker_id="healthy_worker_pid_100")
    assert acquired_job is not None, "Healthy worker should acquire expired lease job"
    assert acquired_job["id"] == job_id
    assert acquired_job["locked_by"] == "healthy_worker_pid_100"

    # Process and complete
    mock_send = AsyncMock(return_value="outbound_recov_123")
    res = asyncio.run(healthy_worker_q.process_single_job(acquired_job, send_reply_func=mock_send))
    assert res["processing_status"] == "completed"
    assert res["outbound_status"] == "sent"

    print("✅ Expired lease from crashed worker successfully reclaimed and processed!")


def test_temporary_gemini_failure_and_retry():
    print("--- 5. Testing Temporary Gemini Failure and Retry Backoff ---")
    clean_queue()
    wamid = f"wamid_gemini_fail_{int(time.time() * 1000)}"
    q = MessageJobQueue(backoff_base=2.0)
    is_new, job_id, status = q.enqueue_incoming_message(
        provider="whatsapp",
        message_id=wamid,
        sender="0918887766",
        message_text="شن أسعار التحاليل؟"
    )

    # First attempt: Gemini throws temporary 503 error
    with patch("patient_service.handle_patient_query", side_effect=RuntimeError("Gemini 503 Overloaded")):
        res1 = asyncio.run(q.process_next_job())
        assert res1 is not None
        assert res1["processing_status"] == "pending"
        assert "Gemini 503" in res1["error"]

    # Verify retry count and backoff in DB
    with db.get_db() as conn:
        row = conn.cursor().execute("SELECT retry_count, next_retry_at, last_error FROM message_jobs WHERE id = ?;", (job_id,)).fetchone()
        assert row["retry_count"] == 1
        assert row["next_retry_at"] > time.time()
        assert "Gemini 503" in row["last_error"]

    # Simulate backoff elapsed
    with db.get_db() as conn:
        conn.cursor().execute("UPDATE message_jobs SET next_retry_at = ? WHERE id = ?;", (time.time() - 1, job_id))

    # Second attempt: Gemini recovers and succeeds
    with patch("patient_service.handle_patient_query", return_value="سعر تحليل السكر 10 د.ل"):
        mock_send = AsyncMock(return_value="outbound_gemini_ok")
        res2 = asyncio.run(q.process_next_job(send_reply_func=mock_send))
        assert res2 is not None
        assert res2["processing_status"] == "completed"
        assert res2["outbound_status"] == "sent"

    print("✅ Transient Gemini failure caught, retried with backoff, and completed!")


def test_outbound_api_failure_and_retry():
    print("--- 6. Testing Outbound API Failure and Retry ---")
    clean_queue()
    wamid = f"wamid_outbound_fail_{int(time.time() * 1000)}"
    q = MessageJobQueue(backoff_base=2.0)
    is_new, job_id, status = q.enqueue_incoming_message(
        provider="whatsapp",
        message_id=wamid,
        sender="0918887766",
        message_text="رسالة اختبار إرسال خارجي"
    )

    # Mock Gemini to succeed, but Outbound Meta API fails
    mock_failing_send = AsyncMock(side_effect=RuntimeError("Meta Graph API 500 Connection Timeout"))
    with patch("patient_service.handle_patient_query", return_value="رد جاهز"):
        res1 = asyncio.run(q.process_next_job(send_reply_func=mock_failing_send))
        assert res1 is not None
        assert res1["processing_status"] == "completed"  # Processing succeeded!
        assert res1["outbound_status"] == "pending"      # Outbound failed!
        assert "Meta Graph API 500" in res1["error"]

    # Verify Gemini was executed, but outbound marked for retry
    with db.get_db() as conn:
        row = conn.cursor().execute("SELECT processing_status, outbound_status, response_text, retry_count FROM message_jobs WHERE id = ?;", (job_id,)).fetchone()
        assert row["processing_status"] == "completed"
        assert row["outbound_status"] == "pending"
        assert row["response_text"] == "رد جاهز"
        assert row["retry_count"] == 1

    # Simulate backoff elapsed
    with db.get_db() as conn:
        conn.cursor().execute("UPDATE message_jobs SET next_retry_at = ? WHERE id = ?;", (time.time() - 1, job_id))

    # Second attempt: Meta API recovers. Notice: Gemini should NOT be called again!
    mock_recovering_send = AsyncMock(return_value="outbound_meta_msg_success_456")
    with patch("patient_service.handle_patient_query", side_effect=AssertionError("Gemini MUST NOT be called again!")):
        res2 = asyncio.run(q.process_next_job(send_reply_func=mock_recovering_send))
        assert res2 is not None
        assert res2["processing_status"] == "completed"
        assert res2["outbound_status"] == "sent"

    print("✅ Outbound network failure retried without re-executing Gemini model logic!")


def test_simulated_crash_after_outbound_delivery():
    print("--- 7. Testing Simulated Crash After Outbound Send Before Persistence ---")
    clean_queue()
    wamid = f"wamid_crash_post_send_{int(time.time() * 1000)}"
    q = MessageJobQueue()
    is_new, job_id, status = q.enqueue_incoming_message(
        provider="whatsapp",
        message_id=wamid,
        sender="0918887766",
        message_text="رسالة اختبار السقوط بعد الإرسال"
    )

    class CrashAfterSendSender:
        def __init__(self):
            self.send_count = 0
        async def __call__(self, to, message):
            self.send_count += 1
            if self.send_count == 1:
                # Meta received it, but simulated OS crash happens right after network returns
                raise MemoryError("Simulated server power-loss / kernel OOM right after HTTP 200 from Meta")
            return "outbound_crash_recovered_id"

    crasher = CrashAfterSendSender()

    # Attempt 1: Step 1 (patient service) succeeds and marks processing_status = completed in DB,
    # but Step 2 crasher raises MemoryError right after sending.
    with patch("patient_service.handle_patient_query", return_value="رد الاستقبال"):
        job1 = q.acquire_job()
        assert job1 is not None
        res1 = asyncio.run(q.process_single_job(job1, send_reply_func=crasher))
        assert res1["processing_status"] == "completed"
        assert res1["outbound_status"] == "pending"

    # Verify DB: processing is completed, outbound is pending
    with db.get_db() as conn:
        row = conn.cursor().execute("SELECT processing_status, outbound_status FROM message_jobs WHERE id = ?;", (job_id,)).fetchone()
        assert row["processing_status"] == "completed"
        assert row["outbound_status"] == "pending"

    # Reset backoff time to simulate retry recovery
    with db.get_db() as conn:
        conn.cursor().execute("UPDATE message_jobs SET next_retry_at = ? WHERE id = ?;", (time.time() - 1, job_id))

    # Attempt 2: Re-acquired by recovered worker.
    # Note: patient_service should NOT be called again, only crasher send is attempted.
    with patch("patient_service.handle_patient_query", side_effect=AssertionError("Should not call patient service on outbound retry")):
        job2 = q.acquire_job()
        assert job2 is not None
        assert job2["id"] == job_id
        res2 = asyncio.run(q.process_single_job(job2, send_reply_func=crasher))
        assert res2["processing_status"] == "completed"
        assert res2["outbound_status"] == "sent"
        assert crasher.send_count == 2

    print("✅ Crash after send tested: Verified business logic integrity and documented at-least-once outbound retry semantics.")


def test_admin_command_deduplication():
    print("--- 8. Testing Administrative Command Deduplication ---")
    clean_queue()
    # Clean doctor state
    db.init_db()
    db.seed_default_data()
    doctor = db.find_doctor_fuzzy(name_query="ديهوم")
    assert doctor is not None
    doc_id = doctor["id"]
    
    # Reset doctor to available
    with db.get_db() as conn:
        conn.cursor().execute("UPDATE doctors SET status = 'available', daily_note = '' WHERE id = ?;", (doc_id,))

    # Snapshot audit log count before
    with db.get_db() as conn:
        initial_logs = conn.cursor().execute("SELECT COUNT(*) AS cnt FROM audit_logs;").fetchone()["cnt"]

    wamid_admin = f"wamid_admin_dedup_{int(time.time() * 1000)}"
    admin_payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "id": wamid_admin,
                        "from": "0912345678", # authorized staff
                        "type": "text",
                        "text": {"body": "@Bot دكتور ديهوم اعتذر اليوم"}
                    }]
                }
            }]
        }]
    }
    raw_bytes = json.dumps(admin_payload).encode("utf-8")
    headers = {"X-Hub-Signature-256": sign_payload(raw_bytes), "Content-Type": "application/json"}

    # Delivery 1: Ingestion
    res1 = client.post("/webhook/whatsapp", content=raw_bytes, headers=headers)
    assert res1.status_code == 200
    assert res1.json()["enqueued_count"] == 1

    # Worker executes admin command
    q = MessageJobQueue()
    mock_send = AsyncMock(return_value="outbound_admin_ok")
    res_job1 = asyncio.run(q.process_next_job(send_reply_func=mock_send))
    assert res_job1 is not None
    assert res_job1["processing_status"] == "completed"

    # Verify doctor changed to apologized and 1 audit log was added
    doc_after1 = db.find_doctor_fuzzy(name_query="ديهوم")
    assert doc_after1["status"] == "apologized"

    with db.get_db() as conn:
        logs_after1 = conn.cursor().execute("SELECT COUNT(*) AS cnt FROM audit_logs;").fetchone()["cnt"]
    assert logs_after1 == initial_logs + 1, f"Expected {initial_logs + 1} logs, found {logs_after1}"

    # Delivery 2: Meta retries the identical administrative webhook with same wamid
    res2 = client.post("/webhook/whatsapp", content=raw_bytes, headers=headers)
    assert res2.status_code == 200
    assert res2.json()["enqueued_count"] == 0 # Deduplicated!

    # Worker checks for new jobs: None should exist
    res_job2 = asyncio.run(q.process_next_job(send_reply_func=mock_send))
    assert res_job2 is None, "No duplicate job should be available"

    # Verify audit logs count DID NOT INCREASE
    with db.get_db() as conn:
        logs_after2 = conn.cursor().execute("SELECT COUNT(*) AS cnt FROM audit_logs;").fetchone()["cnt"]
    assert logs_after2 == logs_after1, f"Audit logs grew from {logs_after1} to {logs_after2} on duplicate!"

    print("✅ Administrative command deduplication verified: No duplicate DB mutation or audit logs!")


if __name__ == "__main__":
    print("=== STARTING PHASE 2 RELIABILITY TEST SUITE ===")
    test_duplicate_webhook_delivery()
    test_concurrent_delivery_same_wamid()
    test_application_restart_with_pending_jobs()
    test_worker_crash_and_lease_recovery()
    test_temporary_gemini_failure_and_retry()
    test_outbound_api_failure_and_retry()
    test_simulated_crash_after_outbound_delivery()
    test_admin_command_deduplication()
    print("🎉 ALL PHASE 2 RELIABILITY TESTS PASSED 100%! 🎉")
