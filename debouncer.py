"""
LibyAI Message Debouncer (`debouncer.py`)

In-memory asynchronous debouncer buffer for WhatsApp conversational UX:
- Absorbs rapid burst messages (2–4 short messages within seconds).
- Enforces an asynchronous sliding window of 2.5 seconds per user session.
- Concatenates rapid fragments into a single cohesive query before querying AI or Triage.
"""

import asyncio
from typing import Dict, List, Callable, Awaitable, Any, Optional


class MessageDebouncer:
    """
    Thread-safe asynchronous debouncer that buffers user messages for a configurable
    window (default 2.5s) of inactivity before flushing them as a unified query.
    """

    def __init__(self, window_seconds: float = 2.5):
        self.window_seconds = window_seconds
        self._buffers: Dict[str, List[str]] = {}
        self._tasks: Dict[str, asyncio.Task] = {}
        self._futures: Dict[str, List[asyncio.Future]] = {}
        self._lock = asyncio.Lock()

    async def enqueue(
        self,
        session_id: str,
        message: str,
        processor_callback: Callable[[str, str], Awaitable[str]]
    ) -> str:
        """
        Enqueues an incoming user fragment. Resets the 2.5s debounce timer.
        Returns the final generated response once the debounce window expires and processing completes.
        """
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()

        async with self._lock:
            # 1. Append message fragment
            if session_id not in self._buffers:
                self._buffers[session_id] = []
            self._buffers[session_id].append(message.strip())

            # 2. Track futures for all callers in this burst
            if session_id not in self._futures:
                self._futures[session_id] = []
            self._futures[session_id].append(future)

            # 3. Cancel existing timer if still counting down
            if session_id in self._tasks and not self._tasks[session_id].done():
                self._tasks[session_id].cancel()

            # 4. Schedule new timer task
            self._tasks[session_id] = asyncio.create_task(
                self._wait_and_flush(session_id, processor_callback)
            )

        # Await the cohesive result
        return await future

    async def _wait_and_flush(
        self,
        session_id: str,
        processor_callback: Callable[[str, str], Awaitable[str]]
    ) -> None:
        """
        Waits for window_seconds of silence. If not canceled by a subsequent message,
        concatenates all buffered fragments and executes processor_callback.
        """
        try:
            await asyncio.sleep(self.window_seconds)
        except asyncio.CancelledError:
            # A new message arrived before window expired; do not resolve futures yet
            return

        # Window elapsed without new messages: Flush cohesive query
        async with self._lock:
            fragments = self._buffers.pop(session_id, [])
            futures = self._futures.pop(session_id, [])
            self._tasks.pop(session_id, None)

        if not fragments:
            for fut in futures:
                if not fut.done():
                    fut.set_result("")
            return

        # Join fragments into one clean, multi-line cohesive query
        cohesive_query = "\n".join(fragments)

        try:
            # Execute processing callback (e.g. Triage -> Gemini)
            response = await processor_callback(session_id, cohesive_query)
            for fut in futures:
                if not fut.done():
                    fut.set_result(response)
        except Exception as e:
            fallback_msg = (
                "ℹ️ مرحباً بك في مصحة الشفاء التخصصية.\n"
                "نعتذر، حدث ضغط مؤقت في معالجة طلبك عبر النظام. يرجى إعادة المحاولة بعد لحظات، "
                "أو التواصل مع مكتب الاستقبال مباشرة: 092-1111111."
            )
            for fut in futures:
                if not fut.done():
                    fut.set_result(fallback_msg)


# Default global debouncer instance (2.5 seconds window)
patient_debouncer = MessageDebouncer(window_seconds=2.5)
