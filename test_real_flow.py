"""
End-to-End Real Flow Test (`test_real_flow.py`)
Simulates real WhatsApp clinic interactions:
1. Patient asks about a doctor present today (retrieved dynamically from SQLite).
2. Patient asks a follow-up question ("في أي فترة؟") -> verifies context memory from persistent chat history.
3. Authorized staff sends `@تحديث` apologizing for a doctor -> verifies durable SQLite write in `daily_overrides`.
4. Patient re-asks about the same doctor -> verifies bot now states doctor is apologized today.
5. Administrative management commands (`@إدارة إضافة`, `@إدارة الموظفين`, `@إدارة حذف`).
"""

import sys
import os
import time
import sqlite3

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import db
from seed_jasmine_hospital import seed_jasmine
import patient_service
import admin_service
from app.services.time_utils import get_libya_datetime_context


def run_full_flow_test():
    print("=" * 70)
    print("🚀 STARTING LIBYAI DEEP REFACTORING & REAL FLOW TEST")
    print("=" * 70)

    # 0. Clean & Seed Fresh Database
    print("\n--- 0. Seeding Jasmine Shelter Hospital Data ---")
    seed_jasmine()
    conn = sqlite3.connect(db.DB_PATH)
    conn.execute("DELETE FROM daily_overrides;")
    conn.execute("DELETE FROM conversation_history;")
    conn.execute("DELETE FROM conversation_sessions;")
    conn.commit()
    conn.close()
    print("✅ Clean baseline established.")

    time_ctx = get_libya_datetime_context()
    today_name = time_ctx["day_name"]
    print(f"📅 Current Libya Day: {today_name} ({time_ctx['date_arabic']})")

    patient_phone = "0915554433"
    staff_phone = "0911059900"  # Registered owner

    # Scenario 1: Patient asks about Orthopedics or a doctor present today
    print(f"\n--- 1. Patient Inquiry: Who is the Orthopedics doctor today ({today_name})? ---")
    q1 = f"من دكتور العظام المتواجد يوم {today_name}؟"
    print(f"👤 Patient ({patient_phone}): {q1}")
    r1 = patient_service.handle_patient_query(patient_phone, q1)
    print(f"🤖 Bot Response:\n{r1}\n")

    # Assertions for Scenario 1
    assert "الياسمين" in r1, "Response must mention Jasmine Hospital"
    assert "0911059900" in r1 or "0945361562" in r1, "Response must include official hospital contact numbers"
    # Check that either Abdullah Dayhoum or Mohamed Edrah or the day's orthopedics doctor is mentioned
    daily_sched = db.get_daily_schedule(today_name)
    ortho_docs = [d["doctor_name"] for d in daily_sched["emergency_clinics"] if "عظام" in d["department"]]
    ortho_docs += [d["doctor_name"] for d in daily_sched["followup_clinics"] if "عظام" in d["specialty"]]
    ortho_names_clean = [db.norm(name) for name in ortho_docs]
    matched_doc = any(name in db.norm(r1) for name in ortho_names_clean)
    assert matched_doc, f"Response must mention an actual orthopedics doctor from SQLite for {today_name}: {ortho_docs}"
    print("✅ Step 1 Passed: Grounded SQLite doctor information provided.")

    # Scenario 2: Follow-up question without repeating doctor name
    print("\n--- 2. Follow-Up Question: 'في أي فترة؟' (Context Retention) ---")
    q2 = "في أي فترة؟"
    print(f"👤 Patient ({patient_phone}): {q2}")
    r2 = patient_service.handle_patient_query(patient_phone, q2)
    print(f"🤖 Bot Response:\n{r2}\n")

    # Assertions for Scenario 2: Bot must understand it's about orthopedics / the previous doctor
    assert any(term in r2 for term in ["عظام", "ديهوم", "ادراه", "فترة", "صباحية", "مسائية", "ليلية", "الاستقبال"]), \
        "Bot should retain conversation context regarding orthopedics doctor shifts"
    print("✅ Step 2 Passed: Multi-turn conversation history preserved context.")

    # Target doctor to apologize for
    target_doc = ortho_docs[0] if ortho_docs else "د. عبدالله ديهوم"
    clean_target_name = target_doc.replace("د.", "").strip()

    # Scenario 3: Staff sends @تحديث to apologize for doctor
    print(f"\n--- 3. Staff Command: '@تحديث دكتور {clean_target_name} اعتذر اليوم' ---")
    admin_msg = f"@تحديث دكتور {clean_target_name} اعتذر اليوم لظرف طارئ"
    print(f"👨‍💼 Staff ({staff_phone}): {admin_msg}")
    admin_reply = admin_service.handle_admin_group_message(staff_phone, admin_msg)
    print(f"🤖 Bot Admin Receipt:\n{admin_reply}\n")

    assert "إيصال تأكيد" in admin_reply or "معتذر" in admin_reply, "Admin receipt must confirm status update"

    # Verify direct SQLite persistence in daily_overrides
    conn = sqlite3.connect(db.DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM daily_overrides WHERE doctor_name LIKE ?;", (f"%{clean_target_name}%",))
    override_row = cursor.fetchone()
    conn.close()

    assert override_row is not None, f"Override for {clean_target_name} must exist in SQLite daily_overrides table!"
    print(f"✅ Step 3 Passed: Override durably saved to disk in daily_overrides: {override_row}")

    # Scenario 4: Patient re-asks about the same doctor
    print(f"\n--- 4. Patient Re-Asks: Is {clean_target_name} available? ---")
    q3 = f"دكتور {clean_target_name} متواجد توا؟"
    print(f"👤 Patient ({patient_phone}): {q3}")
    r3 = patient_service.handle_patient_query(patient_phone, q3)
    print(f"🤖 Bot Response:\n{r3}\n")

    assert any(w in r3 for w in ["معتذر", "غير متواجد", "اعتذر", "اعتذرت"]), \
        "Bot must explicitly inform patient that the doctor apologized and is not available today!"
    print("✅ Step 4 Passed: Bot dynamically detected apology override from SQLite!")

    # Scenario 5: Administrative Deterministic SQL Management
    print("\n--- 5. Deterministic Management Commands (@إدارة) ---")
    # Add staff
    new_staff_phone = "0917778899"
    add_cmd = f"@إدارة إضافة {new_staff_phone} د. كمال staff"
    print(f"👨‍💼 Staff ({staff_phone}): {add_cmd}")
    add_resp = admin_service.handle_admin_group_message(staff_phone, add_cmd)
    print(f"🤖 Bot Admin Response:\n{add_resp}\n")
    assert "تمت إضافة الموظف" in add_resp, "Admin command must confirm addition"

    is_auth, role, name = db.is_staff_authorized(new_staff_phone)
    assert is_auth and role == "staff", "New staff must be recognized in DB"

    # List staff
    list_cmd = "@إدارة الموظفين"
    print(f"👨‍💼 Staff ({staff_phone}): {list_cmd}")
    list_resp = admin_service.handle_admin_group_message(staff_phone, list_cmd)
    print(f"🤖 Bot Admin Response:\n{list_resp}\n")
    assert new_staff_phone in list_resp, "Staff list must include new phone"

    # Delete staff
    del_cmd = f"@إدارة حذف {new_staff_phone}"
    print(f"👨‍💼 Staff ({staff_phone}): {del_cmd}")
    del_resp = admin_service.handle_admin_group_message(staff_phone, del_cmd)
    print(f"🤖 Bot Admin Response:\n{del_resp}\n")
    assert "تم إلغاء الصلاحية" in del_resp, "Admin command must confirm deletion"

    is_auth_after, _, _ = db.is_staff_authorized(new_staff_phone)
    assert not is_auth_after, "Staff should no longer be authorized after deletion"
    print("✅ Step 5 Passed: Deterministic SQL staff management verified.")

    print("\n" + "=" * 70)
    print("🎉 ALL REAL FLOW TESTS PASSED 100% WITH ZERO MOCKS! 🎉")
    print("=" * 70)


if __name__ == "__main__":
    run_full_flow_test()
