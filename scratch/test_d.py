import asyncio
import time
import sys
import os
sys.path.insert(0, os.path.abspath("."))
sys.stdout.reconfigure(encoding="utf-8")

from debouncer import MessageDebouncer

async def mock_processor(phone: str, query: str) -> str:
    print(f"\n[MOCK PROCESSOR TRIGGERED] for {phone} with cohesive query:")
    print("--------------------------------------------------")
    print(query)
    print("--------------------------------------------------")
    return f"Response to: {query.replace(chr(10), ' + ')}"

async def main():
    debouncer = MessageDebouncer(window_seconds=1.5)
    phone = "0912223344"

    print("Sending message 1: 'السلام عليكم' at t=0.0s")
    t0 = time.time()
    task1 = asyncio.create_task(debouncer.enqueue(phone, "السلام عليكم", mock_processor))

    await asyncio.sleep(0.4)
    print(f"Sending message 2: 'دكتور العظام متاح اليوم؟' at t={time.time()-t0:.2f}s")
    task2 = asyncio.create_task(debouncer.enqueue(phone, "دكتور العظام متاح اليوم؟", mock_processor))

    await asyncio.sleep(0.4)
    print(f"Sending message 3: 'وقداش كشفه؟' at t={time.time()-t0:.2f}s")
    task3 = asyncio.create_task(debouncer.enqueue(phone, "وقداش كشفه؟", mock_processor))

    res1, res2, res3 = await asyncio.gather(task1, task2, task3)
    elapsed = time.time() - t0
    print(f"\nAll tasks resolved after {elapsed:.2f}s!")
    print(f"Result received by client 1: {res1}")
    assert res1 == res2 == res3
    print("DEBOUNCER TEST PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    asyncio.run(main())
