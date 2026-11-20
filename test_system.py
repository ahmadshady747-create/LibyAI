import sys
import os

# Ensure UTF-8 output on Windows console
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# Set root dir in path
sys.path.insert(0, os.path.dirname(__file__))

from app.database.session import init_db
from app.database.seed import seed_database
from app.services import admin_processor, customer_processor, db_service

def test_full_pipeline():
    print(">>> 1. Initializing DB and Seeding...")
    init_db()
    seed_database()

    doctors = db_service.get_all_doctors()
    print(f"Loaded {len(doctors)} doctors.")
    for d in doctors:
        print(f" - {d.name} ({d.specialty}) | الحالة: {d.today_status} | كشفية: {d.consultation_fee}")

    print("\n>>> 2. Testing Normal Group Chat (Should be IGNORED)...")
    ignored_reply = admin_processor.process_admin_group_message("موظف 1", "صباح الخير شباب من مستلم شفت الصبح؟")
    assert ignored_reply is None, f"Expected None but got {ignored_reply}"
    print("SUCCESS: Normal chit-chat correctly ignored!")

    print("\n>>> 3. Testing Patient Inquiry BEFORE update...")
    reply_before = customer_processor.process_customer_message("0910000000", "من متواجد اليوم في العظام؟")
    print("Patient Reply Before:")
    print(reply_before)

    print("\n>>> 4. Testing Admin Update with @Bot (Doctor Apology)...")
    # Build the admin message from TODAY's emergency orthopedics doctor in
    # the current Al-Noor demo seed: the patient view shows today's
    # schedule, so the update must target the doctor who is on duty today.
    # A hardcoded name breaks on days when that doctor is not scheduled.
    from app.services.time_utils import get_libya_datetime_context
    import db as _legacy_db

    _day = get_libya_datetime_context()["day_name"]
    _schedule = _legacy_db.get_daily_schedule(_day)
    _ortho_today = [
        row for row in _schedule.get("emergency_clinics", [])
        if "عظام" in (row.get("department") or "")
    ] or [
        row for row in _schedule.get("followup_clinics", [])
        if "عظام" in (row.get("department") or "")
    ]
    assert _ortho_today, f"No orthopedics doctor scheduled today ({_day}) in the demo seed"
    _ortho_name = _ortho_today[0]["doctor_name"].replace("د.", "").strip()
    admin_msg = f"@Bot دكتور العظام {_ortho_name} اعتذر اليوم ومش حيكون متواجد."
    # A group update sender must be a real authorized phone number, not a
    # display name: authorization is checked against staff phone numbers.
    # This number is the seeded test staff number in seed_demo.py.
    admin_reply = admin_processor.process_admin_group_message("0920202020", admin_msg)
    print("Admin Confirmation Reply:")
    print(admin_reply)
    # The receipt must name the doctor we targeted: if the resolver picked
    # a different orthopedics doctor, the patient view below would still
    # show the schedule doctor as available and the sync check would fail
    # for the wrong reason.
    assert _ortho_name in admin_reply, f"Receipt did not name {_ortho_name}: {admin_reply[:200]}"

    print("\n>>> 5. Testing Patient Inquiry AFTER update (Instant sync verification)...")
    reply_after = customer_processor.process_customer_message("0910000000", "من متواجد اليوم في العظام؟")
    print("Patient Reply After:")
    print(reply_after)
    assert "معتذر" in reply_after or "اعتذار" in reply_after or "غير متواجد" in reply_after, "Sync failed!"

    print("\n>>> 6. Testing Guardrail: Critical Emergency...")
    emergency_reply = customer_processor.process_customer_message("0910000000", "عندي ألم شديد بالصدر وضيق تنفس حاد!")
    print("Emergency Reply:")
    print(emergency_reply)
    assert "طوارئ" in emergency_reply or "إسعاف" in emergency_reply, "Emergency guardrail failed!"

    print("\n>>> 7. Testing Guardrail: Medical Diagnosis / Prescription...")
    diag_reply = customer_processor.process_customer_message("0910000000", "ولدي عنده سخانة 39 وكحة شن نعطيه دواء؟")
    print("Diagnosis Guardrail Reply:")
    print(diag_reply)
    assert "تشخيص" in diag_reply or "وصفات" in diag_reply or "سلامت" in diag_reply, "Diagnosis guardrail failed!"

    print("\n>>> 8. Testing Guardrail: Booking Policy Guidance...")
    booking_reply = customer_processor.process_customer_message("0910000000", "نبي نحجز موعد كشف")
    print("Booking Policy Reply:")
    print(booking_reply)
    assert "حضور" in booking_reply or "استقبال" in booking_reply, "Booking guidance guardrail failed!"

    print("\n=======================================================")
    print(" ALL TESTS PASSED! THE SYSTEM LOGIC IS ROCK SOLID! ")
    print("=======================================================")

if __name__ == "__main__":
    test_full_pipeline()
