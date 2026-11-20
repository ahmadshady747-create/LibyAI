import asyncio
import sys
import os
sys.path.insert(0, os.path.abspath("."))
sys.stdout.reconfigure(encoding="utf-8")

from router import dispatch_message

async def main():
    print("==================================================")
    print("1. Testing Staff Group Tagged Message via Router:")
    admin_rep = await dispatch_message(
        sender="0920202020",
        message="@Bot دكتور العظام علي اعتذر اليوم",
        is_group=True,
        group_id="staff_group_1"
    )
    print("Admin Reply:\n", admin_rep)
    assert "إيصال تأكيد التحديث" in admin_rep

    print("\n==================================================")
    print("2. Testing Staff Group Untagged Message (Should be ignored):")
    untagged_rep = await dispatch_message(
        sender="0920202020",
        message="السلام عليكم يا شباب شن الجو اليوم",
        is_group=True,
        group_id="staff_group_1"
    )
    print("Untagged Reply:", untagged_rep)
    assert untagged_rep is None

    print("\n==================================================")
    print("3. Testing Patient Emergency Message (Zero Delay Bypass):")
    emerg_rep = await dispatch_message(
        sender="0919998877",
        message="نزيف حاد وضيق تنفس شديد!",
        is_group=False
    )
    print("Emergency Reply:\n", emerg_rep)
    assert "تنبيه طبي عاجل" in emerg_rep

    print("\n==================================================")
    print("4. Testing Patient Routine Message via Debouncer:")
    patient_rep = await dispatch_message(
        sender="0919998877",
        message="من دكتور العظام اليوم وكم كشفه؟",
        is_group=False
    )
    print("Patient Reply:\n", patient_rep)

    print("\nROUTER TESTS PASSED SUCCESSFULLY! ✅")

if __name__ == "__main__":
    asyncio.run(main())
