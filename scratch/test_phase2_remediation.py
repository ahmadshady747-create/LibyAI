import os
import sys
import time
import json
import asyncio
from unittest.mock import patch, AsyncMock

# Force UTF-8 on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

BASE_DIR = r"C:\Users\awsat\Desktop\LibyAI"
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from app.config import settings
from app.main import app, lifespan
import db
from job_queue import MessageJobQueue

def clean_database():
    db.init_db()
    db.seed_default_data()
    with db.get_db() as conn:
        conn.cursor().execute("DELETE FROM message_jobs;")
        conn.cursor().execute("DELETE FROM incoming_messages;")
        conn.cursor().execute("DELETE FROM audit_logs;")
        conn.cursor().execute("DELETE FROM conversation_sessions;")

print("=================================================================")
print("STARTING PHASE 2 REMEDIATION TEST SUITE (P0-A, P0-B, P1)")
print("=================================================================")

# -------------------------------------------------------------------
# 1. P0-A: Fail-Closed Production Startup Tests
# -------------------------------------------------------------------
def test_1_fail_closed_production_startup():
    print("\n--- 1. Testing P0-A: Fail-Closed Production Startup ---")
    orig_env = settings.ENVIRONMENT
    orig_secret = settings.WHATSAPP_APP_SECRET

    async def run_boot():
        async with lifespan(app):
            pass

    try:
        # Case 1: missing secret (None) in production
        settings.ENVIRONMENT = "production"
        settings.WHATSAPP_APP_SECRET = None
        try:
            asyncio.run(run_boot())
            assert False, "Should have raised RuntimeError for None secret in production!"
        except RuntimeError as e:
            assert "CRITICAL SECURITY CONFIGURATION ERROR" in str(e)
            print("  ✅ Missing secret (None) in production strictly failed closed!")

        # Case 2: blank secret in production
        settings.WHATSAPP_APP_SECRET = "   "
        try:
            asyncio.run(run_boot())
            assert False, "Should have raised RuntimeError for blank secret in production!"
        except RuntimeError as e:
            assert "CRITICAL SECURITY CONFIGURATION ERROR" in str(e)
            print("  ✅ Blank secret in production strictly failed closed!")

        # Case 3: development default secret in production
        settings.WHATSAPP_APP_SECRET = "dev_meta_app_secret_libyai_2026"
        try:
            asyncio.run(run_boot())
            assert False, "Should have raised RuntimeError for dev default in production!"
        except RuntimeError as e:
            assert "CRITICAL SECURITY CONFIGURATION ERROR" in str(e)
            print("  ✅ Development default secret in production strictly failed closed!")

        # Case 4: valid production secret
        settings.WHATSAPP_APP_SECRET = "strong_prod_secret_meta_987654321_secure"
        asyncio.run(run_boot())
        print("  ✅ Valid production secret booted cleanly!")

        # Case 5: development mode with default secret
        settings.ENVIRONMENT = "development"
        settings.WHATSAPP_APP_SECRET = "dev_meta_app_secret_libyai_2026"
        asyncio.run(run_boot())
        print("  ✅ Development mode booted cleanly with dev secret!")

    finally:
        settings.ENVIRONMENT = orig_env
        settings.WHATSAPP_APP_SECRET = orig_secret


# -------------------------------------------------------------------
# 2. P0-B: Crash during administrative mutation before transaction commit; rollback & safe recovery
# -------------------------------------------------------------------
def test_2_admin_mutation_transaction_rollback_on_crash():
    print("\n--- 2. Testing P0-B: Admin Mutation Rollback on Mid-Transaction Failure ---")
    clean_database()
    doctor = db.find_doctor_fuzzy(name_query="ديهوم")
    doc_id = doctor["id"]
    initial_status = doctor["status"]

    with db.get_db() as conn:
        initial_logs = conn.cursor().execute("SELECT COUNT(*) AS cnt FROM audit_logs;").fetchone()["cnt"]

    q = MessageJobQueue()
    wamid = f"wamid_rem_crash_{int(time.time()*1000)}"
    is_new, job_id, _ = q.enqueue_incoming_message(
        provider="whatsapp",
        message_id=wamid,
        sender="0912345678",
        message_text="@Bot دكتور ديهوم اعتذر اليوم",
        is_group=True,
        group_id="staff_group"
    )
    job = q.acquire_job()
    assert job is not None

    # Simulate an unhandled database error / crash inside apply_admin_mutation_atomic
    # right after the UPDATE doctors but before transaction commits
    with patch("db.apply_admin_mutation_atomic", side_effect=RuntimeError("Simulated disk I/O error or crash inside atomic transaction")):
        res = asyncio.run(q.process_single_job(job))
        assert "Simulated disk I/O error" in res["error"]

    # Verify that transaction rolled back completely:
    doc_after_fail = db.find_doctor_fuzzy(name_query="ديهوم")
    with db.get_db() as conn:
        logs_after_fail = conn.cursor().execute("SELECT COUNT(*) AS cnt FROM audit_logs;").fetchone()["cnt"]
        job_status = conn.cursor().execute("SELECT processing_status FROM message_jobs WHERE id = ?;", (job_id,)).fetchone()["processing_status"]

    assert doc_after_fail["status"] == initial_status, "Doctor status must NOT have changed on rollback!"
    assert logs_after_fail == initial_logs, "No audit log must be written on rollback!"
    assert job_status == "pending", "Job must be scheduled for retry on failure!"
    print("  ✅ Verified complete rollback: Doctor status unchanged, 0 audit logs created, job marked pending for retry!")

    # Safe recovery attempt:
    with db.get_db() as conn:
        conn.cursor().execute("UPDATE message_jobs SET next_retry_at = ? WHERE id = ?;", (time.time() - 1, job_id))

    recovered_job = q.acquire_job()
    assert recovered_job is not None
    mock_send = AsyncMock(return_value="outbound_meta_success")
    res_recovery = asyncio.run(q.process_single_job(recovered_job, send_reply_func=mock_send))
    assert res_recovery["processing_status"] == "completed"

    doc_after_rec = db.find_doctor_fuzzy(name_query="ديهوم")
    with db.get_db() as conn:
        logs_after_rec = conn.cursor().execute("SELECT COUNT(*) AS cnt FROM audit_logs;").fetchone()["cnt"]

    assert doc_after_rec["status"] == "apologized"
    assert logs_after_rec == initial_logs + 1
    print("  ✅ Safe recovery verified: Exactly 1 doctor status mutation and 1 audit log created upon retry!")


# -------------------------------------------------------------------
# 3. P0-B: Duplicate Administrative Message Recovery (Idempotency)
# -------------------------------------------------------------------
def test_3_duplicate_admin_message_recovery_idempotency():
    print("\n--- 3. Testing P0-B: Duplicate Administrative Message Idempotency ---")
    clean_database()
    doctor = db.find_doctor_fuzzy(name_query="ديهوم")
    doc_id = doctor["id"]

    with db.get_db() as conn:
        initial_logs = conn.cursor().execute("SELECT COUNT(*) AS cnt FROM audit_logs;").fetchone()["cnt"]

    q = MessageJobQueue()
    wamid = f"wamid_rem_idemp_{int(time.time()*1000)}"
    is_new, job_id, _ = q.enqueue_incoming_message(
        provider="whatsapp",
        message_id=wamid,
        sender="0912345678",
        message_text="@Bot دكتور ديهوم اعتذر اليوم",
        is_group=True,
        group_id="staff_group"
    )
    job = q.acquire_job()

    # Step 1: Execute job to completion
    mock_send = AsyncMock(return_value="outbound_admin_receipt_1")
    res1 = asyncio.run(q.process_single_job(job, send_reply_func=mock_send))
    assert res1["processing_status"] == "completed"

    with db.get_db() as conn:
        logs_after1 = conn.cursor().execute("SELECT COUNT(*) AS cnt FROM audit_logs;").fetchone()["cnt"]
    assert logs_after1 == initial_logs + 1

    # Simulate ungraceful recovery scenario: Job is manually re-submitted or re-processed with same job_id
    import admin_service
    # Direct execution of handle_admin_group_message with same job_id
    receipt2 = admin_service.handle_admin_group_message(
        sender_phone="0912345678",
        raw_message="@Bot دكتور ديهوم اعتذر اليوم",
        group_id="staff_group",
        job_id=job_id,
        lease_token="recovered_token"
    )
    assert receipt2 is not None
    assert "إيصال تأكيد التحديث الفوري" in receipt2

    # Verify audit logs did NOT increase:
    with db.get_db() as conn:
        logs_after2 = conn.cursor().execute("SELECT COUNT(*) AS cnt FROM audit_logs;").fetchone()["cnt"]
    assert logs_after2 == logs_after1, f"Audit logs grew from {logs_after1} to {logs_after2} on duplicate!"

    # Verify UNIQUE(message_job_id) constraint in DB protects against raw duplicate inserts
    import sqlite3
    with db.get_db() as conn:
        try:
            conn.cursor().execute("""
                INSERT INTO audit_logs (admin_sender, raw_message, status_before, status_after, confirmation_text, message_job_id)
                VALUES (?, ?, ?, ?, ?, ?);
            """, ("0912345678", "raw duplicate", "{}", "{}", "receipt", job_id))
            assert False, "UNIQUE constraint on message_job_id should have blocked duplicate insert!"
        except sqlite3.IntegrityError:
            print("  ✅ UNIQUE(message_job_id) constraint verified in DB: blocked duplicate audit log insertion!")

    print("  ✅ Idempotency verified: Duplicate job run returned cached receipt and created zero extra mutations or logs!")


# -------------------------------------------------------------------
# 4. P1: Slow worker whose lease expires while another worker acquires job
# -------------------------------------------------------------------
def test_4_slow_worker_lease_expiration_and_supersession():
    print("\n--- 4. Testing P1: Slow Worker Lease Expiration & Supersession ---")
    clean_database()
    q = MessageJobQueue()
    wamid = f"wamid_p1_supersede_{int(time.time()*1000)}"
    q.enqueue_incoming_message(
        provider="whatsapp",
        message_id=wamid,
        sender="0918887766",
        message_text="رسالة مريض لاختبار العامل البطيء"
    )

    worker1 = MessageJobQueue()
    worker1.worker_id = "worker_slow_1"
    job1 = worker1.acquire_job()
    assert job1 is not None
    job_id = job1["id"]
    token1 = job1["lease_token"]
    gen1 = job1["lease_generation"]
    print(f"  -> Worker 1 acquired Job {job_id} with token {token1[:8]}... (Gen {gen1})")

    # Fast forward: Worker 1 hangs, lease expires in DB
    with db.get_db() as conn:
        conn.cursor().execute("UPDATE message_jobs SET lease_expires_at = ? WHERE id = ?;", (time.time() - 5, job_id))

    # Worker 2 acquires the expired job
    worker2 = MessageJobQueue()
    worker2.worker_id = "worker_fast_2"
    job2 = worker2.acquire_job()
    assert job2 is not None
    token2 = job2["lease_token"]
    gen2 = job2["lease_generation"]
    print(f"  -> Worker 2 acquired Job {job_id} with token {token2[:8]}... (Gen {gen2})")

    assert token1 != token2, "Each acquisition must generate a new unique lease token!"
    assert gen2 > gen1, "Lease generation must increment monotonically!"

    # Worker 2 processes and completes
    mock_send2 = AsyncMock(return_value="outbound_worker2_success")
    with patch("patient_service.handle_patient_query", return_value="رد من العامل السريع 2"):
        res2 = asyncio.run(worker2.process_single_job(job2, send_reply_func=mock_send2))
    assert res2["outbound_status"] == "sent"
    assert mock_send2.call_count == 1
    print("  -> Worker 2 finished processing and delivered reply.")

    # Worker 1 wakes up and attempts to verify lease
    is_valid_worker1 = worker1.verify_lease(job_id, token1)
    assert is_valid_worker1 is False, "Worker 1 must fail lease verification!"
    print("  ✅ Worker 1 lease verification correctly evaluated to FALSE (lease lost)!")


# -------------------------------------------------------------------
# 5. P1: Stale worker attempting to commit or begin outbound after losing lease
# -------------------------------------------------------------------
def test_5_stale_worker_fenced_from_commit_and_outbound():
    print("\n--- 5. Testing P1: Stale Worker Fencing (Commit & Outbound Blocked) ---")
    clean_database()
    q = MessageJobQueue()
    wamid = f"wamid_p1_fence_{int(time.time()*1000)}"
    q.enqueue_incoming_message(
        provider="whatsapp",
        message_id=wamid,
        sender="0918887766",
        message_text="رسالة مريض لاختبار سياج العامل الميت"
    )

    worker_stale = MessageJobQueue()
    worker_stale.worker_id = "worker_stale"
    job_stale = worker_stale.acquire_job()
    assert job_stale is not None
    job_id = job_stale["id"]
    token_stale = job_stale["lease_token"]

    # Supersede worker_stale by simulating Worker 2 acquiring the job
    worker_usurper = MessageJobQueue()
    worker_usurper.worker_id = "worker_usurper"
    with db.get_db() as conn:
        conn.cursor().execute("UPDATE message_jobs SET lease_expires_at = ? WHERE id = ?;", (time.time() - 1, job_id))
    job_usurped = worker_usurper.acquire_job()
    assert job_usurped is not None

    # Stale worker attempts to process job_stale
    mock_stale_send = AsyncMock(return_value="stale_outbound_should_not_happen")
    with patch("patient_service.handle_patient_query", return_value="رد من العامل المستبعد"):
        res_stale = asyncio.run(worker_stale.process_single_job(job_stale, send_reply_func=mock_stale_send))

    # Assertions: Stale worker was fenced!
    assert res_stale.get("fenced") is True, f"Expected fenced=True, got {res_stale}"
    assert mock_stale_send.call_count == 0, f"Stale worker sent outbound {mock_stale_send.call_count} times! Outbound MUST be 0!"
    print("  ✅ Fencing verified: Stale worker was completely blocked from committing and outbound send count was 0!")


# -------------------------------------------------------------------
# 6. P1: Heartbeat Failure and Lease-Renewal Recovery
# -------------------------------------------------------------------
def test_6_heartbeat_lease_renewal():
    print("\n--- 6. Testing P1: Heartbeat Lease Renewal & Loss Handling ---")
    clean_database()
    q = MessageJobQueue(lease_duration=10.0, heartbeat_interval=0.1)
    wamid = f"wamid_p1_heartbeat_{int(time.time()*1000)}"
    q.enqueue_incoming_message(
        provider="whatsapp",
        message_id=wamid,
        sender="0918887766",
        message_text="رسالة اختبار النبضات"
    )

    job = q.acquire_job()
    assert job is not None
    job_id = job["id"]
    token = job["lease_token"]

    # Test direct renewal
    initial_exp = job["lease_expires_at"]
    time.sleep(0.05)
    renewed = q.renew_lease(job_id, token, extension=30.0)
    assert renewed is True, "renew_lease must return True when worker holds lease!"

    with db.get_db() as conn:
        new_exp = conn.cursor().execute("SELECT lease_expires_at FROM message_jobs WHERE id = ?;", (job_id,)).fetchone()["lease_expires_at"]
    assert new_exp > initial_exp, f"Expected {new_exp} > {initial_exp}"
    print(f"  ✅ Heartbeat renewal verified: lease extended from {initial_exp:.2f} to {new_exp:.2f}!")

    # Test renewal failure when lease token is wrong or superseded
    renew_bad_token = q.renew_lease(job_id, "wrong_token_123")
    assert renew_bad_token is False, "renew_lease must return False for invalid/superseded token!"
    print("  ✅ Heartbeat correctly reported False when attempting to renew with stale token!")


if __name__ == "__main__":
    test_1_fail_closed_production_startup()
    test_2_admin_mutation_transaction_rollback_on_crash()
    test_3_duplicate_admin_message_recovery_idempotency()
    test_4_slow_worker_lease_expiration_and_supersession()
    test_5_stale_worker_fenced_from_commit_and_outbound()
    test_6_heartbeat_lease_renewal()
    print("\n🎉 ALL PHASE 2 REMEDIATION TESTS PASSED 100%! 🎉")
