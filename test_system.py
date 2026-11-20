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
from app.services import admin_processor, patient_processor, db_service

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
    reply_before = patient_processor.process_patient_message("0910000000", "من متواجد اليوم في العظام؟")
    print("Patient Reply Before:")
    print(reply_before)

    print("\n>>> 4. Testing Admin Update with @Bot (Doctor Apology)...")
    # Use the actual Thursday emergency orthopedics doctor from the current
    # Al-Noor seed. The old message named a doctor who no longer exists in
    # this seed, so fuzzy matching updated a different orthopedics doctor
    # and the patient view (which shows the Thursday schedule) correctly
    # kept showing the schedule doctor as available.
    admin_msg = "@Bot دكتور العظام عبدالله ديهوم اعتذر اليوم ومش حيكون متواجد."
    # A group update sender must be a real authorized phone number, not a
    # display name: authorization is checked against staff phone numbers.
    # This number is the seeded test staff number in seed_demo.py.
    admin_reply = admin_processor.process_admin_group_message("0920202020", admin_msg)
    print("Admin Confirmation Reply:")
    print(admin_reply)

    print("\n>>> 5. Testing Patient Inquiry AFTER update (Instant sync verification)...")
    reply_after = patient_processor.process_patient_message("0910000000", "من متواجد اليوم في العظام؟")
    print("Patient Reply After:")
    print(reply_after)
    assert "معتذر" in reply_after or "اعتذار" in reply_after or "غير متواجد" in reply_after, "Sync failed!"

    print("\n>>> 6. Testing Guardrail: Critical Emergency...")
    emergency_reply = patient_processor.process_patient_message("0910000000", "عندي ألم شديد بالصدر وضيق تنفس حاد!")
    print("Emergency Reply:")
    print(emergency_reply)
    assert "طوارئ" in emergency_reply or "إسعاف" in emergency_reply, "Emergency guardrail failed!"

    print("\n>>> 7. Testing Guardrail: Medical Diagnosis / Prescription...")
    diag_reply = patient_processor.process_patient_message("0910000000", "ولدي عنده سخانة 39 وكحة شن نعطيه دواء؟")
    print("Diagnosis Guardrail Reply:")
    print(diag_reply)
    assert "تشخيص" in diag_reply or "وصفات" in diag_reply or "سلامت" in diag_reply, "Diagnosis guardrail failed!"

    print("\n>>> 8. Testing Guardrail: Booking Policy Guidance...")
    booking_reply = patient_processor.process_patient_message("0910000000", "نبي نحجز موعد كشف")
    print("Booking Policy Reply:")
    print(booking_reply)
    assert "حضور" in booking_reply or "استقبال" in booking_reply, "Booking guidance guardrail failed!"

    print("\n=======================================================")
    print(" ALL TESTS PASSED! THE SYSTEM LOGIC IS ROCK SOLID! ")
    print("=======================================================")

if __name__ == "__main__":
    test_full_pipeline()
