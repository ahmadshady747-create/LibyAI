"""
LibyAI Durable Message Job Queue (`job_queue.py`)

Provides resilient, idempotent SQLite-backed job queue for message
ingestion and egress across channels (Messenger primary, WhatsApp
secondary, simulator):
1. Idempotent Ingestion: Deduplicates incoming messages by
   (channel, external_message_id) — the same external id on two
   channels is two different messages.
2. Durable State: Records incoming events and pending processing jobs atomically in SQLite before acknowledging.
3. Separation of Concerns: Separates business processing state ('pending', 'processing', 'completed', 'failed')
   from outbound delivery state ('pending', 'processing', 'sent', 'failed', 'skipped').
4. Worker Recovery: Crash recovery using atomic job leases (lease_expires_at) and recovery of orphaned jobs on startup.
5. Resilient Retries: Bounded retries (default max_retries=3) with exponential backoff on transient errors.
6. Channel Outbound: replies are dispatched through the adapter matching
   the queued job's channel.
"""

import os
import sys
import time
import json
import uuid
import asyncio
import logging
import sqlite3
from typing import Dict, Any, Optional, Tuple, Callable, Awaitable

import db
import guardrails
import admin_service
import customer_service

logger = logging.getLogger(__name__)


class MessageJobQueue:
    """
    Durable, thread-safe, SQLite-backed job queue for processing
    Messenger/WhatsApp messages.
    """

    def __init__(
        self,
        db_path: str = db.DB_PATH,
        lease_duration: float = 60.0,
        max_retries: int = 3,
        backoff_base: float = 2.0,
        heartbeat_interval: float = 15.0,
        worker_id: Optional[str] = None
    ):
        self.db_path = db_path
        self.lease_duration = lease_duration
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.heartbeat_interval = heartbeat_interval
        self.worker_id = worker_id or f"worker_{os.getpid()}_{uuid.uuid4().hex[:6]}"
        self._notify_event = asyncio.Event()
        self._running = False

    def enqueue_incoming_message(
        self,
        provider: Optional[str] = None,
        message_id: str = "",
        sender: str = "",
        message_text: str = "",
        is_group: bool = False,
        group_id: Optional[str] = None,
        payload_json: Optional[str] = None,
        channel: Optional[str] = None,
    ) -> Tuple[bool, int, str]:
        """
        Atomically records an incoming message in the ledger and enqueues a pending job.
        If (channel, message_id) already exists, treats it as a duplicate and does NOT enqueue a job.

        `channel` is the new name for the deduplication key; `provider`
        is kept as a backward-compatible alias (channel wins when both
        are given). Both columns are stored with the same value.

        Returns:
            (is_new, job_id, status_string)
            is_new: True if newly enqueued, False if duplicate.
        """
        channel = (channel or provider or "whatsapp").strip().lower()
        provider = channel
        now = time.time()
        with db.get_db(self.db_path) as conn:
            cursor = conn.cursor()

            # 1. Check ledger for existing message
            cursor.execute(
                "SELECT id FROM incoming_messages WHERE channel = ? AND message_id = ?;",
                (channel, message_id)
            )
            existing_msg = cursor.fetchone()
            if existing_msg:
                # Look up existing job ID
                cursor.execute(
                    "SELECT id, processing_status FROM message_jobs WHERE channel = ? AND message_id = ?;",
                    (channel, message_id)
                )
                existing_job = cursor.fetchone()
                job_id = existing_job["id"] if existing_job else existing_msg["id"]
                logger.info(f"[JobQueue] Duplicate message detected: channel={channel}, message_id={message_id}")
                return False, job_id, "duplicate"

            # 2. Insert into incoming_messages ledger
            try:
                cursor.execute("""
                    INSERT INTO incoming_messages (provider, channel, message_id, sender, payload_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?);
                """, (provider, channel, message_id, sender, payload_json or "", now))
                incoming_id = cursor.lastrowid
            except sqlite3.IntegrityError:
                # Concurrent race condition caught by UNIQUE constraint
                logger.info(f"[JobQueue] Concurrent duplicate caught by constraint: {channel}/{message_id}")
                cursor.execute(
                    "SELECT id FROM incoming_messages WHERE channel = ? AND message_id = ?;",
                    (channel, message_id)
                )
                existing = cursor.fetchone()
                return False, existing["id"] if existing else 0, "duplicate"

            # 3. Atomically enqueue into message_jobs
            cursor.execute("""
                INSERT INTO message_jobs (
                    incoming_message_id, provider, channel, message_id, sender, message_text,
                    is_group, group_id, processing_status, outbound_status,
                    retry_count, max_retries, next_retry_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', 'pending', 0, ?, ?, ?, ?);
            """, (
                incoming_id, provider, channel, message_id, sender, message_text,
                1 if is_group else 0, group_id, self.max_retries, now, now, now
            ))
            job_id = cursor.lastrowid

        # Wake up background worker if active
        self._notify_event.set()
        logger.info(f"[JobQueue] Enqueued new message job {job_id} for {channel}/{message_id}")
        return True, job_id, "enqueued"

    def acquire_job(self, worker_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Atomically finds and leases the next available job:
        - Ready pending jobs whose retry backoff has elapsed.
        - Jobs whose worker lease has expired (crash recovery).
        - Jobs whose processing is completed, but outbound delivery is pending/crashed.
        """
        wid = worker_id or self.worker_id
        if worker_id:
            self.worker_id = worker_id
        now = time.time()

        with db.get_db(self.db_path) as conn:
            cursor = conn.cursor()

            # Find candidate job
            cursor.execute("""
                SELECT * FROM message_jobs
                WHERE (
                    -- Case 1: Fresh or retryable pending job
                    (processing_status = 'pending' AND next_retry_at <= :now AND (locked_at IS NULL OR lease_expires_at <= :now))
                    OR
                    -- Case 2: Crashed processing job with expired lease
                    (processing_status = 'processing' AND lease_expires_at <= :now)
                    OR
                    -- Case 3: Processing complete, but outbound delivery is pending and ready
                    (processing_status = 'completed' AND outbound_status IN ('pending', 'failed') AND next_retry_at <= :now AND (locked_at IS NULL OR lease_expires_at <= :now))
                    OR
                    -- Case 4: Crashed outbound delivery with expired lease
                    (processing_status = 'completed' AND outbound_status = 'processing' AND lease_expires_at <= :now)
                )
                ORDER BY id ASC
                LIMIT 1;
            """, {"now": now})

            candidate = cursor.fetchone()
            if not candidate:
                return None

            job_id = candidate["id"]
            new_processing_status = "processing" if candidate["processing_status"] in ("pending", "processing") else candidate["processing_status"]
            new_outbound_status = "processing" if candidate["processing_status"] == "completed" and candidate["outbound_status"] in ("pending", "failed", "processing") else candidate["outbound_status"]

            # Acquire atomic lease with unique lease token and incremented generation
            lease_token = uuid.uuid4().hex
            cursor.execute("""
                UPDATE message_jobs
                SET locked_at = :now,
                    locked_by = :wid,
                    lease_token = :lease_token,
                    lease_generation = lease_generation + 1,
                    lease_expires_at = :lease_exp,
                    processing_status = :proc_status,
                    outbound_status = :out_status,
                    updated_at = :now
                WHERE id = :job_id
                  AND (
                      locked_at IS NULL
                      OR lease_expires_at <= :now
                      OR locked_by = :wid
                  );
            """, {
                "now": now,
                "wid": wid,
                "lease_token": lease_token,
                "lease_exp": now + self.lease_duration,
                "proc_status": new_processing_status,
                "out_status": new_outbound_status,
                "job_id": job_id
            })

            if cursor.rowcount == 0:
                # Claimed by a competing worker
                return None

            # Re-fetch full locked record
            cursor.execute("SELECT * FROM message_jobs WHERE id = ?;", (job_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def renew_lease(self, job_id: int, lease_token: str, extension: Optional[float] = None) -> bool:
        """
        Heartbeat: Renews the lease for an active job only if this worker still owns the lease token.
        Returns True if renewed, False if lease was lost/superseded.
        """
        now = time.time()
        ext = extension or self.lease_duration
        with db.get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE message_jobs
                SET lease_expires_at = :exp,
                    updated_at = :now
                WHERE id = :job_id
                  AND lease_token = :token
                  AND locked_by = :wid;
            """, {
                "exp": now + ext,
                "now": now,
                "job_id": job_id,
                "token": lease_token,
                "wid": self.worker_id
            })
            return cursor.rowcount > 0

    def verify_lease(self, job_id: int, lease_token: str) -> bool:
        """Verifies that this worker still holds a valid, unexpired lease token for this job."""
        now = time.time()
        with db.get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id FROM message_jobs
                WHERE id = ?
                  AND lease_token = ?
                  AND locked_by = ?
                  AND lease_expires_at > ?;
            """, (job_id, lease_token, self.worker_id, now))
            return cursor.fetchone() is not None

    async def process_single_job(
        self,
        job: Dict[str, Any],
        send_reply_func: Optional[Callable[[str, str], Awaitable[Any]]] = None
    ) -> Dict[str, Any]:
        """
        Executes business processing and outbound delivery for a single leased job.
        Maintains distinct processing_status and outbound_status.
        Enforces optimistic stale-worker fencing and background lease heartbeats.
        """
        job_id = job["id"]
        sender = job["sender"]
        message_text = job["message_text"]
        is_group = bool(job["is_group"])
        group_id = job["group_id"]
        processing_status = job["processing_status"]
        outbound_status = job["outbound_status"]
        response_text = job.get("response_text")
        lease_token = job.get("lease_token")
        job_channel = (job.get("channel") or job.get("provider") or "whatsapp").strip().lower()

        lease_lost_event = asyncio.Event()

        # Start background heartbeat renewal task
        async def _heartbeat_loop():
            while not lease_lost_event.is_set():
                try:
                    await asyncio.sleep(self.heartbeat_interval)
                    if not self.renew_lease(job_id, lease_token):
                        logger.warning(f"[JobQueue] Worker {self.worker_id} LOST lease for job {job_id}!")
                        lease_lost_event.set()
                        break
                except asyncio.CancelledError:
                    break
                except Exception as ex:
                    logger.error(f"[JobQueue] Heartbeat renewal error for job {job_id}: {ex}")

        heartbeat_task = asyncio.create_task(_heartbeat_loop())

        try:
            # ------------------------------------------------------------------
            # Step 1: AI / Admin Business Processing (Only if not already completed)
            # ------------------------------------------------------------------
            if processing_status != "completed":
                try:
                    if is_group:
                        # Atomic admin mutation + audit log + job completion in one transaction
                        response_text = await asyncio.to_thread(
                            admin_service.handle_admin_group_message,
                            sender_phone=sender,
                            raw_message=message_text,
                            group_id=group_id,
                            job_id=job_id,
                            lease_token=lease_token,
                            worker_id=self.worker_id,
                            db_path=self.db_path,
                            channel=job_channel,
                        )
                        processing_status = "completed"
                        job["processing_status"] = "completed"
                        job["response_text"] = response_text
                        logger.info(f"[JobQueue] Admin Job {job_id} processing completed atomically.")
                    else:
                        # Customer message: fast guardrail interceptor.
                        # Only a medical Level 1 emergency bypasses the
                        # customer pipeline here (zero delay); handoff and
                        # Level 2 are evaluated inside handle_customer_query.
                        business_profile = db.get_business_profile(self.db_path)
                        fast_guard = guardrails.evaluate_guardrails(message_text, business_profile)
                        if fast_guard.is_emergency and fast_guard.immediate_response:
                            response_text = fast_guard.immediate_response
                        else:
                            response_text = await asyncio.to_thread(
                                customer_service.handle_customer_query,
                                sender,
                                message_text,
                                job_channel,
                                self.db_path,
                            )

                        # Fencing check: verify lease before committing customer turn and status
                        if lease_lost_event.is_set() or not self.verify_lease(job_id, lease_token):
                            raise db.StaleWorkerFencedError(
                                f"Worker {self.worker_id} was superseded while processing job {job_id}."
                            )

                        now = time.time()
                        with db.get_db(self.db_path) as conn:
                            cursor = conn.cursor()
                            cursor.execute("""
                                INSERT INTO conversation_sessions (phone_number, role, message_text, created_at, channel)
                                VALUES (?, 'user', ?, ?, ?);
                            """, (sender, message_text, now, job_channel))
                            if response_text:
                                cursor.execute("""
                                    INSERT INTO conversation_sessions (phone_number, role, message_text, created_at, channel)
                                    VALUES (?, 'model', ?, ?, ?);
                                """, (sender, response_text, now, job_channel))

                            cursor.execute("""
                                UPDATE message_jobs
                                SET processing_status = 'completed',
                                    response_text = :resp,
                                    updated_at = :now
                                WHERE id = :job_id
                                  AND (lease_token IS NULL OR lease_token = :token);
                            """, {"resp": response_text, "now": now, "job_id": job_id, "token": lease_token})

                            if cursor.rowcount == 0:
                                raise db.StaleWorkerFencedError(
                                    f"Fenced! Worker {self.worker_id} lease token {lease_token} superseded on job {job_id}."
                                )

                        processing_status = "completed"
                        job["processing_status"] = "completed"
                        job["response_text"] = response_text
                        logger.info(f"[JobQueue] Patient Job {job_id} processing completed.")

                except db.StaleWorkerFencedError as fe:
                    logger.warning(f"[JobQueue] {fe}")
                    return {
                        "job_id": job_id,
                        "processing_status": processing_status,
                        "outbound_status": outbound_status,
                        "error": str(fe),
                        "fenced": True
                    }
                except Exception as e:
                    logger.error(f"[JobQueue] Error during processing job {job_id}: {e}")
                    now = time.time()
                    retry_count = job["retry_count"] + 1
                    if retry_count >= job["max_retries"]:
                        final_proc = "failed"
                        next_retry = now + 86400  # Do not retry further
                    else:
                        final_proc = "pending"
                        delay = self.backoff_base ** retry_count
                        next_retry = now + delay

                    with db.get_db(self.db_path) as conn:
                        conn.execute("""
                            UPDATE message_jobs
                            SET processing_status = ?,
                                retry_count = ?,
                                next_retry_at = ?,
                                last_error = ?,
                                locked_at = NULL,
                                locked_by = NULL,
                                lease_expires_at = NULL,
                                lease_token = NULL,
                                updated_at = ?
                            WHERE id = ?;
                        """, (final_proc, retry_count, next_retry, str(e), now, job_id))

                    return {
                        "job_id": job_id,
                        "processing_status": final_proc,
                        "outbound_status": outbound_status,
                        "error": str(e)
                    }

            # ------------------------------------------------------------------
            # Step 2: Safe Outbound Delivery
            # ------------------------------------------------------------------
            if processing_status == "completed" and outbound_status != "sent":
                # Fencing check before outbound delivery: Do NOT send if worker lost ownership
                if lease_lost_event.is_set() or not self.verify_lease(job_id, lease_token):
                    logger.warning(f"[JobQueue] Fenced! Worker {self.worker_id} superseded before outbound send on job {job_id}.")
                    return {
                        "job_id": job_id,
                        "processing_status": "completed",
                        "outbound_status": outbound_status,
                        "error": "fenced_before_outbound",
                        "fenced": True
                    }

                # If no response needed (e.g. casual staff chatter without admin intent)
                if not response_text:
                    now = time.time()
                    with db.get_db(self.db_path) as conn:
                        conn.execute("""
                            UPDATE message_jobs
                            SET outbound_status = 'skipped',
                                completed_at = ?,
                                locked_at = NULL,
                                locked_by = NULL,
                                lease_expires_at = NULL,
                                lease_token = NULL,
                                updated_at = ?
                            WHERE id = ?;
                        """, (now, now, job_id))
                    return {
                        "job_id": job_id,
                        "processing_status": "completed",
                        "outbound_status": "skipped",
                        "response_text": None
                    }

                # Outbound sender resolution: dispatch through the adapter
                # matching the queued job's channel. An explicit
                # send_reply_func (tests, custom senders) always wins.
                if send_reply_func is not None:
                    sender_func = send_reply_func
                else:
                    from app.channels.base import send_via_channel

                    async def _channel_sender(to: str, message: str):
                        return await send_via_channel(job_channel, to=to, message=message)

                    sender_func = _channel_sender

                try:
                    # Record outbound attempt count pre-flight
                    now = time.time()
                    with db.get_db(self.db_path) as conn:
                        conn.execute("""
                            UPDATE message_jobs
                            SET outbound_attempt_count = outbound_attempt_count + 1,
                                updated_at = ?
                            WHERE id = ?;
                        """, (now, job_id))

                    outbound_result = await sender_func(to=sender, message=response_text)
                    outbound_id = str(outbound_result) if outbound_result else "sent"
                    now = time.time()
                    with db.get_db(self.db_path) as conn:
                        cursor = conn.cursor()
                        cursor.execute("""
                            UPDATE message_jobs
                            SET outbound_status = 'sent',
                                outbound_message_id = :outbound_id,
                                completed_at = :now,
                                locked_at = NULL,
                                locked_by = NULL,
                                lease_expires_at = NULL,
                                lease_token = NULL,
                                updated_at = :now
                            WHERE id = :job_id
                              AND (lease_token IS NULL OR lease_token = :token);
                        """, {"outbound_id": outbound_id, "now": now, "job_id": job_id, "token": lease_token})

                        if cursor.rowcount == 0:
                            logger.warning(
                                f"[JobQueue] Meta accepted outbound send for job {job_id}, "
                                f"but worker lease was superseded before persisting 'sent' status. "
                                f"Possible at-least-once duplicate delivery edge case."
                            )

                    logger.info(f"[JobQueue] Job {job_id} successfully sent outbound response.")
                    return {
                        "job_id": job_id,
                        "processing_status": "completed",
                        "outbound_status": "sent",
                        "response_text": response_text
                    }

                except Exception as e:
                    logger.error(f"[JobQueue] Outbound delivery failed for job {job_id}: {e}")
                    now = time.time()
                    retry_count = job["retry_count"] + 1
                    if retry_count >= job["max_retries"]:
                        final_out = "failed"
                        next_retry = now + 86400
                    else:
                        final_out = "pending"
                        delay = self.backoff_base ** retry_count
                        next_retry = now + delay

                    with db.get_db(self.db_path) as conn:
                        conn.execute("""
                            UPDATE message_jobs
                            SET outbound_status = ?,
                                retry_count = ?,
                                next_retry_at = ?,
                                last_error = ?,
                                locked_at = NULL,
                                locked_by = NULL,
                                lease_expires_at = NULL,
                                lease_token = NULL,
                                updated_at = ?
                            WHERE id = ?;
                        """, (final_out, retry_count, next_retry, str(e), now, job_id))

                    return {
                        "job_id": job_id,
                        "processing_status": "completed",
                        "outbound_status": final_out,
                        "error": str(e)
                    }

            return {
                "job_id": job_id,
                "processing_status": processing_status,
                "outbound_status": outbound_status
            }

        finally:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass

    async def process_next_job(
        self,
        send_reply_func: Optional[Callable[[str, str], Awaitable[Any]]] = None
    ) -> Optional[Dict[str, Any]]:
        """Leases and processes one ready job if available."""
        job = self.acquire_job()
        if not job:
            return None
        return await self.process_single_job(job, send_reply_func=send_reply_func)

    def recover_orphaned_jobs(self) -> int:
        """
        Recovers jobs left in 'processing' status by crashed workers whose leases expired,
        or on application startup. Resets them to 'pending' so they are eligible for re-leasing.
        """
        now = time.time()
        with db.get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE message_jobs
                SET locked_at = NULL,
                    locked_by = NULL,
                    lease_expires_at = NULL,
                    lease_token = NULL,
                    processing_status = CASE WHEN processing_status = 'processing' THEN 'pending' ELSE processing_status END,
                    outbound_status = CASE WHEN outbound_status = 'processing' THEN 'pending' ELSE outbound_status END,
                    updated_at = ?
                WHERE (processing_status = 'processing' OR outbound_status = 'processing')
                  AND (lease_expires_at <= ? OR locked_at IS NOT NULL);
            """, (now, now))
            recovered = cursor.rowcount
            if recovered > 0:
                logger.info(f"[JobQueue] Recovered {recovered} orphaned message jobs on startup/reclaim.")
            return recovered

    async def run_worker_loop(self, poll_interval: float = 1.0):
        """Continuous background worker loop."""
        self._running = True
        logger.info(f"[JobQueue] Worker {self.worker_id} started.")

        # Recover jobs stranded before worker start
        self.recover_orphaned_jobs()

        while self._running:
            try:
                # Process all ready jobs in queue
                processed_any = False
                while self._running:
                    res = await self.process_next_job()
                    if res is None:
                        break
                    processed_any = True

                # Wait for next event or timeout
                self._notify_event.clear()
                try:
                    await asyncio.wait_for(self._notify_event.wait(), timeout=poll_interval)
                except asyncio.TimeoutError:
                    pass

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[JobQueue] Worker loop error: {e}")
                await asyncio.sleep(1.0)

        self._running = False
        logger.info(f"[JobQueue] Worker {self.worker_id} stopped.")

    def stop_worker(self):
        """Signals worker to stop."""
        self._running = False
        self._notify_event.set()


# Global default queue instance
job_queue = MessageJobQueue()
