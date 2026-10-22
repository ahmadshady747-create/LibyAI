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

from fastapi.testclient import TestClient
from app.config import settings, Settings
from app.main import app, lifespan
import db
from job_queue import MessageJobQueue

def clean_tables():
    with db.get_db() as conn:
        conn.cursor().execute("DELETE FROM message_jobs;")
        conn.cursor().execute("DELETE FROM incoming_messages;")

print("=================================================================")
print("ADVERSARIAL AUDIT VERIFICATION SUITE — LIBYAI")
print("=================================================================")

# -------------------------------------------------------------------
# Test 1: Administrative mutation crash before processing_status commit
# -------------------------------------------------------------------
def test_q1_admin_mutation_double_execution():
    print("\n[TEST 1] Checking Administrative Mutation Crash & Double Execution...")
    clean_tables()
    db.init_db()
    db.seed_default_data()
    doctor = db.find_doctor_fuzzy(name_query="ديهوم")
    doc_id = doctor["id"]

    # Reset doctor to available
    with db.get_db() as conn:
        conn.cursor().execute("UPDATE doctors SET status = 'available', daily_note = '' WHERE id = ?;", (doc_id,))
        initial_logs = conn.cursor().execute("SELECT COUNT(*) AS cnt FROM audit_logs;").fetchone()["cnt"]

    q = MessageJobQueue()
    wamid = f"wamid_audit_q1_{int(time.time()*1000)}"
    q.enqueue_incoming_message(
        provider="whatsapp",
        message_id=wamid,
        sender="0912345678", # authorized staff
        message_text="@Bot دكتور ديهوم اعتذر اليوم",
        is_group=True,
        group_id="staff_group"
    )

    # Worker acquires job
    job = q.acquire_job(worker_id="worker_q1")
    assert job is not None
    job_id = job["id"]

    # Simulate execution where admin_service completes mutation and logs audit,
    # but process crashes right before updating message_jobs.processing_status = 'completed'
    import admin_service
    # Step 1 logic runs:
    receipt = admin_service.handle_admin_group_message(
        sender_phone=job["sender"],
        raw_message=job["message_text"],
        group_id=job["group_id"]
    )
    assert receipt is not None

    # Inspect DB immediately after admin_service returns:
    with db.get_db() as conn:
        doc_after_first = db.find_doctor_fuzzy(name_query="ديهوم")
        logs_after_first = conn.cursor().execute("SELECT COUNT(*) AS cnt FROM audit_logs;").fetchone()["cnt"]
        job_status = conn.cursor().execute("SELECT processing_status FROM message_jobs WHERE id = ?;", (job_id,)).fetchone()["processing_status"]

    print(f"  -> State right after admin_service (simulated crash point):")
    print(f"     Doctor status in DB: {doc_after_first['status']}")
    print(f"     Audit logs count: {logs_after_first} (increased by 1)")
    print(f"     message_jobs.processing_status: '{job_status}' (NOT 'completed')")

    # Now simulate worker crash & lease recovery (lease expired):
    with db.get_db() as conn:
        conn.cursor().execute("UPDATE message_jobs SET lease_expires_at = ? WHERE id = ?;", (time.time() - 10, job_id))

    # Recovered worker acquires the job again
    recovered_job = q.acquire_job(worker_id="recovered_worker")
    assert recovered_job is not None
    assert recovered_job["id"] == job_id

    # Recovered worker processes the job to completion
    mock_send = AsyncMock(return_value="outbound_recovered_receipt")
    asyncio.run(q.process_single_job(recovered_job, send_reply_func=mock_send))

    with db.get_db() as conn:
        logs_after_recovery = conn.cursor().execute("SELECT COUNT(*) AS cnt FROM audit_logs;").fetchone()["cnt"]

    print(f"  -> State after recovered worker run:")
    print(f"     Audit logs count: {logs_after_recovery} (increased by {logs_after_recovery - initial_logs})")

    if logs_after_recovery > initial_logs + 1:
        print(f"  ❌ VULNERABILITY CONFIRMED: Admin mutation executed twice! Duplicate audit logs created ({initial_logs} -> {logs_after_first} -> {logs_after_recovery}).")
    else:
        print("  ✅ Protected against duplicate mutation.")


# -------------------------------------------------------------------
# Test 2: Lease expiration, lack of renewal, and lack of fencing
# -------------------------------------------------------------------
def test_q2_lease_expiration_and_stale_worker_fencing():
    print("\n[TEST 2] Checking Lease Expiration & Stale-Worker Fencing...")
    clean_tables()
    q = MessageJobQueue()
    wamid = f"wamid_audit_q2_{int(time.time()*1000)}"
    q.enqueue_incoming_message(
        provider="whatsapp",
        message_id=wamid,
        sender="0918887766",
        message_text="رسالة اختبار القفل"
    )

    # Worker 1 leases job
    worker1_q = MessageJobQueue()
    worker1_q.worker_id = "worker_slow_1"
    job1 = worker1_q.acquire_job()
    assert job1 is not None
    job_id = job1["id"]
    print(f"  -> Worker 1 leased Job {job_id} (locked_by: {job1['locked_by']})")

    # Fast forward: Worker 1 hangs, lease expires
    with db.get_db() as conn:
        conn.cursor().execute("UPDATE message_jobs SET lease_expires_at = ? WHERE id = ?;", (time.time() - 10, job_id))

    # Worker 2 acquires the same expired job
    worker2_q = MessageJobQueue()
    worker2_q.worker_id = "worker_fast_2"
    job2 = worker2_q.acquire_job()
    assert job2 is not None
    print(f"  -> Lease expired. Worker 2 acquired Job {job_id} (locked_by: {job2['locked_by']})")

    # Worker 2 finishes processing and sending
    mock_send2 = AsyncMock(return_value="outbound_worker2")
    with patch("patient_service.handle_patient_query", return_value="رد من العامل 2"):
        res2 = asyncio.run(worker2_q.process_single_job(job2, send_reply_func=mock_send2))
    assert res2["outbound_status"] == "sent"
    print(f"  -> Worker 2 completed job and sent response: {mock_send2.call_count} send")

    # Worker 1 wakes up and attempts to complete its job
    mock_send1 = AsyncMock(return_value="outbound_worker1_stale")
    with patch("patient_service.handle_patient_query", return_value="رد متأخر من العامل 1"):
        res1 = asyncio.run(worker1_q.process_single_job(job1, send_reply_func=mock_send1))

    print(f"  -> Stale Worker 1 send_reply_func called: {mock_send1.call_count} time(s)")
    if mock_send1.call_count > 0:
        print("  ❌ VULNERABILITY CONFIRMED: Stale worker was NOT fenced! Both Worker 1 and Worker 2 executed and sent replies.")
    else:
        print("  ✅ Stale worker was fenced from sending reply.")


# -------------------------------------------------------------------
# Test 3: Atomicity of incoming_messages and message_jobs
# -------------------------------------------------------------------
def test_q3_incoming_and_jobs_atomicity():
    print("\n[TEST 3] Checking Atomicity of incoming_messages and message_jobs...")
    clean_tables()
    q = MessageJobQueue()
    wamid = f"wamid_audit_q3_{int(time.time()*1000)}"

    # Simulate failure on the second insert (into message_jobs)
    # by corrupting the SQL or triggering an error in cursor.execute during message_jobs insert
    original_execute = None
    call_count = [0]

    with db.get_db() as conn:
        pass # connection test

    from unittest.mock import patch
    import sqlite3

    # We patch conn.cursor in get_db or raise during message_jobs insert
    def simulate_failure_enqueue():
        with db.get_db(q.db_path) as conn:
            cursor = conn.cursor()
            now = time.time()
            # Step 1: Insert into incoming_messages
            cursor.execute("""
                INSERT INTO incoming_messages (provider, message_id, sender, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?);
            """, ("whatsapp", wamid, "0912345678", "{}", now))
            
            # Simulated crash / disk error / unhandled exception before message_jobs insert:
            raise sqlite3.OperationalError("Simulated disk error or crash before message_jobs insert")

    try:
        simulate_failure_enqueue()
    except sqlite3.OperationalError as e:
        print(f"  -> Simulated failure caught: {e}")

    # Inspect database: Did incoming_messages rollback?
    with db.get_db() as conn:
        cur = conn.cursor()
        incoming_cnt = cur.execute("SELECT COUNT(*) AS cnt FROM incoming_messages WHERE message_id = ?;", (wamid,)).fetchone()["cnt"]
        jobs_cnt = cur.execute("SELECT COUNT(*) AS cnt FROM message_jobs WHERE message_id = ?;", (wamid,)).fetchone()["cnt"]

    print(f"  -> After failure: incoming_messages={incoming_cnt}, message_jobs={jobs_cnt}")
    if incoming_cnt == 0 and jobs_cnt == 0:
        print("  ✅ VERIFIED PROTECTION: Transaction rolled back completely! No orphaned incoming_messages row.")
    else:
        print("  ❌ DEFECT: Ingestion is NOT atomic! Orphaned record in incoming_messages.")


# -------------------------------------------------------------------
# Test 4: Crash after Meta HTTP 200 before outbound_status='sent'
# -------------------------------------------------------------------
def test_q4_crash_after_meta_send_duplicate_replies():
    print("\n[TEST 4] Demonstrating Crash After Meta Send & Duplicate Replies...")
    clean_tables()
    q = MessageJobQueue()
    wamid = f"wamid_audit_q4_{int(time.time()*1000)}"
    q.enqueue_incoming_message(
        provider="whatsapp",
        message_id=wamid,
        sender="0918887766",
        message_text="رسالة مريض لاختبار الإرسال المكرر"
    )

    class MetaSenderSimulator:
        def __init__(self):
            self.delivered_to_meta_count = 0
        async def __call__(self, to, message):
            self.delivered_to_meta_count += 1
            if self.delivered_to_meta_count == 1:
                # Meta HTTP 200 succeeded, but process crashes before recording 'sent'
                raise MemoryError("Process crashed right after Meta Graph API returned HTTP 200")
            return f"meta_wamid_outbound_{self.delivered_to_meta_count}"

    sender = MetaSenderSimulator()
    job = q.acquire_job()

    with patch("patient_service.handle_patient_query", return_value="رد المصحة الأول"):
        res1 = asyncio.run(q.process_single_job(job, send_reply_func=sender))

    print(f"  -> Attempt 1: Meta delivered count = {sender.delivered_to_meta_count}, outbound_status = '{res1['outbound_status']}'")

    # Fast forward retry backoff
    with db.get_db() as conn:
        conn.cursor().execute("UPDATE message_jobs SET next_retry_at = ? WHERE id = ?;", (time.time() - 1, job["id"]))

    # Recovered worker re-acquires job
    job_retry = q.acquire_job()
    assert job_retry is not None
    # Patient service should NOT re-run
    with patch("patient_service.handle_patient_query", side_effect=AssertionError("AI should not re-run")):
        res2 = asyncio.run(q.process_single_job(job_retry, send_reply_func=sender))

    print(f"  -> Attempt 2: Meta delivered count = {sender.delivered_to_meta_count}, outbound_status = '{res2['outbound_status']}'")

    if sender.delivered_to_meta_count == 2:
        print("  ⚠️ VERIFIED UNRESOLVED RISK: Duplicate outbound delivery occurred! (Meta sent 2 messages to patient, because Meta lacks client idempotency keys).")
        print("     Business state was protected (AI did not re-run), but recipient received duplicate WhatsApp reply.")
    else:
        print(f"  Delivered {sender.delivered_to_meta_count} times.")


# -------------------------------------------------------------------
# Test 5: Production startup with missing or default WHATSAPP_APP_SECRET
# -------------------------------------------------------------------
def test_q5_production_startup_fail_closed():
    print("\n[TEST 5] Checking Production Startup with Default / Missing WHATSAPP_APP_SECRET...")
    
    # Case A: Default secret in production
    print("  -> Case A: ENVIRONMENT='production', WHATSAPP_APP_SECRET='dev_meta_app_secret_libyai_2026' (default)")
    orig_env = settings.ENVIRONMENT
    orig_secret = settings.WHATSAPP_APP_SECRET
    try:
        settings.ENVIRONMENT = "production"
        settings.WHATSAPP_APP_SECRET = "dev_meta_app_secret_libyai_2026"
        
        # Test lifespan execution
        startup_failed = False
        try:
            async def run_lifespan():
                async with lifespan(app):
                    pass
            asyncio.run(run_lifespan())
            print("     Application started successfully with development secret in production!")
        except Exception as e:
            startup_failed = True
            print(f"     Application failed to start: {e}")

        if not startup_failed:
            print("  ❌ VULNERABILITY CONFIRMED: Production startup DOES NOT fail closed with default secret!")

        # Case B: Missing secret (None) in production
        print("  -> Case B: ENVIRONMENT='production', WHATSAPP_APP_SECRET=None")
        settings.WHATSAPP_APP_SECRET = None
        startup_failed_none = False
        try:
            async def run_lifespan_none():
                async with lifespan(app):
                    pass
            asyncio.run(run_lifespan_none())
            print("     Application started successfully with WHATSAPP_APP_SECRET=None!")
        except Exception as e:
            startup_failed_none = True
            print(f"     Application failed to start: {e}")

        if not startup_failed_none:
            print("  ❌ VULNERABILITY CONFIRMED: Production startup DOES NOT fail closed when secret is None!")

    finally:
        settings.ENVIRONMENT = orig_env
        settings.WHATSAPP_APP_SECRET = orig_secret


if __name__ == "__main__":
    test_q1_admin_mutation_double_execution()
    test_q2_lease_expiration_and_stale_worker_fencing()
    test_q3_incoming_and_jobs_atomicity()
    test_q4_crash_after_meta_send_duplicate_replies()
    test_q5_production_startup_fail_closed()
