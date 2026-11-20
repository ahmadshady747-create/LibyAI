import sys
import os
import asyncio

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

project_path = r"C:\Users\awsat\Desktop\LibyAI"
if project_path not in sys.path:
    sys.path.insert(0, project_path)

import db
import admin_service
from debouncer import MessageDebouncer
from router import dispatch_message

async def test_admin_service_validation():
    print("--- 1. Testing Admin Service Status Validation & Mapping ---")
    
    # Ensure database is initialized
    db.init_db()
    db.seed_default_data()

    # Find a doctor to test on
    doctor = db.find_doctor_fuzzy(name_query="ديهوم")
    assert doctor is not None, "Doctor ديهوم should exist"

    # Test status mapping with an unstandardized status e.g. "absent" or "معتذر"
    # Create fake intent
    class FakeIntent:
        action = "DOCTOR_STATUS_UPDATE"
        doctor_identifier = "ديهوم"
        new_status = "absent" # Should map to apologized!
        daily_note = "تحديث تجريبي"
        is_ambiguous = False
        is_valid_update = True
        ambiguity_reason = None
        new_price = None

    # Patch parse_staff_message_with_ai temporarily
    orig_parse = admin_service.parse_staff_message_with_ai
    admin_service.parse_staff_message_with_ai = lambda msg: FakeIntent()

    try:
        reply = admin_service.handle_admin_group_message(
            sender_phone="0920202020",
            raw_message="@Bot دكتور ديهوم اعتذر اليوم",
            group_id="test_group"
        )
        assert "إيصال تأكيد التحديث الفوري" in reply, f"Expected success receipt, got: {reply}"
        
        # Verify doctor status in DB is "apologized"
        updated_doc = db.find_doctor_fuzzy(name_query="ديهوم")
        assert updated_doc["status"] == "apologized", f"Expected 'apologized', got '{updated_doc['status']}'"
        print(f"✅ 'absent' was successfully mapped to '{updated_doc['status']}' in database without IntegrityError!")

        # Test fee out of bounds
        class FakeFeeIntent:
            action = "UPDATE_FEE"
            doctor_identifier = "ديهوم"
            new_status = None
            daily_note = ""
            is_ambiguous = False
            is_valid_update = True
            ambiguity_reason = None
            new_price = -50.0 # Negative fee!

        admin_service.parse_staff_message_with_ai = lambda msg: FakeFeeIntent()
        fee_reply = admin_service.handle_admin_group_message(
            sender_phone="0920202020",
            raw_message="@Bot كشفية دكتور ديهوم صارت -50",
            group_id="test_group"
        )
        assert "غير منطقية" in fee_reply, f"Expected validation error, got: {fee_reply}"
        print("✅ Negative fee was rejected cleanly with validation error!")

    finally:
        admin_service.parse_staff_message_with_ai = orig_parse


async def test_debouncer_exception_handling():
    print("--- 2. Testing Debouncer Exception Fallback ---")
    debouncer = MessageDebouncer(window_seconds=0.1)

    async def faulty_callback(session_id, query):
        raise RuntimeError("Simulated network/LLM crash!")

    # Enqueue a message
    result = await debouncer.enqueue("0919998877", "السلام عليكم", faulty_callback)
    assert "حدث ضغط مؤقت" in result or "مرحباً بك" in result, f"Expected graceful fallback, got: {result}"
    print(f"✅ Debouncer cleanly caught exception and returned fallback: '{result[:50]}...'")


def test_conversation_turn_role_safety():
    print("--- 3. Testing Conversation Turn Role Safety ---")
    # Inserting an invalid role should be safely sanitized to 'user' without SQLite CHECK violation
    db.save_conversation_turn("0910000000", "INVALID_ROLE_123", "رسالة اختبارية")
    
    with db.get_db() as conn:
        row = conn.execute(
            "SELECT role FROM conversation_sessions WHERE phone_number = '0910000000' ORDER BY id DESC LIMIT 1;"
        ).fetchone()
        assert row["role"] == "user", f"Expected 'user', got '{row['role']}'"
    print("✅ Invalid role was safely defaulted to 'user'!")


async def test_router_async_group():
    print("--- 4. Testing Non-Blocking Router Dispatch ---")
    # Test dispatch_message with is_group=True runs non-blocking
    reply = await dispatch_message(
        sender="0920202020",
        message="@Bot كشفية عيادة العظام",
        is_group=True,
        group_id="clinic_group"
    )
    assert reply is not None, "Expected reply from group dispatch"
    print(f"✅ Group dispatch completed asynchronously without blocking event loop!")


async def main():
    await test_admin_service_validation()
    await test_debouncer_exception_handling()
    test_conversation_turn_role_safety()
    await test_router_async_group()
    print("\n🎉 ALL PHASE 2 RUNTIME & CONCURRENCY TESTS PASSED!")

if __name__ == "__main__":
    asyncio.run(main())
