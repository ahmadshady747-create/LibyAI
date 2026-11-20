"""
LibyAI Multi-Facility Generality Test (`test_generic_multi_facility.py`)
Validates that LibyAI is completely facility-agnostic and dynamically configurable:
1. Works for any clinic (e.g. Al-Noor Demo Clinic in Zliten).
2. Dynamically switches to another medical clinic (e.g. مصحة الأمل التخصصية in Benghazi) with ZERO code changes.
3. Dynamically switches to a non-medical service facility (e.g. مجموعة الرواد للاستشارات والتدريب in Tripoli).
4. Restores Al-Noor Hospital baseline cleanly.
"""

import sys
import os
import sqlite3

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

import db
import patient_service
from seed_demo import seed_demo


def run_tests():
    print("=" * 70)
    print("🌐 STARTING LIBYAI MULTI-FACILITY GENERALITY TEST")
    print("=" * 70)

    # -------------------------------------------------------------
    # 1. Al-Noor Demo Clinic (Zliten) Baseline
    # -------------------------------------------------------------
    print("\n--- 1. Testing Baseline Facility (مصحة النور التجريبية - زليتن) ---")
    seed_demo()
    prof = db.get_facility_profile()
    print(f"Facility Name: {prof['name']}")
    print(f"Address:       {prof['address']}")
    print(f"City:          {prof['city']}")
    print(f"Phones:        {prof['contact_numbers']}")

    resp_demo = patient_service.handle_patient_query("0915550001", "شن عنوانكم ومن دكتور العظام المتواجد يوم الجمعة؟")
    print("\nPatient Query: شن عنوانكم ومن دكتور العظام المتواجد يوم الجمعة؟")
    print(f"Bot Response:\n{resp_demo}")

    assert "النور" in resp_demo or "زليتن" in resp_demo, "Should identify Al-Noor or Zliten"
    assert "يوسف العربي" in resp_demo, "Should mention Friday orthopedics doctor"
    print("✅ Baseline Al-Noor Clinic Test Passed!")

    # -------------------------------------------------------------
    # 2. Dynamic Switch to Another Clinic (مصحة الأمل التخصصية - بنغازي)
    # -------------------------------------------------------------
    print("\n--- 2. Dynamically Switching to Another Clinic (مصحة الأمل التخصصية - بنغازي) ---")
    al_amal_profile = {
        "name": "مصحة الأمل التخصصية",
        "clinic_name": "مصحة الأمل التخصصية",
        "facility_type": "مصحة تخصصية",
        "address": "بنغازي - شارع دبي بالقرب من ميدان الشجرة",
        "city": "بنغازي",
        "emergency_phone": "0921112233",
        "reception_phone": "0924445566",
        "contact_numbers": "0921112233 - 0924445566",
        "booking_policy": "الحجز المسبق متاح عبر الهاتف، والطوارئ تستقبل 24 ساعة.",
        "facilities_info": "عيادات تخصصية، غرف عمليات جراحية، مختبر تحاليل حديث، وأشعة مقطعية.",
        "is_medical": "1"
    }
    db.update_facility_profile(al_amal_profile)

    # Insert Al-Amal doctors for الجمعة
    with db.get_db() as conn:
        conn.execute("DELETE FROM emergency_clinics;")
        conn.execute("DELETE FROM followup_clinics;")
        conn.execute("DELETE FROM daily_overrides;")
        conn.execute("DELETE FROM conversation_history;")

        conn.execute("""
            INSERT INTO emergency_clinics (day_of_week, department, shift, shift_time, doctor_name)
            VALUES ('الجمعة', 'الجراحة العامة', 'الصباحية', '08:00 ص - 02:00 ظ', 'د. طارق المجبري');
        """)
        conn.execute("""
            INSERT INTO followup_clinics (day_of_week, specialty, doctor_name, shift_note)
            VALUES ('الجمعة', 'الجلدية والليزر', 'د. أسماء الفيتوري', '04:00 م - 08:00 م');
        """)

    prof_amal = db.get_facility_profile()
    print(f"Switched Facility: {prof_amal['name']} ({prof_amal['city']})")

    resp_amal = patient_service.handle_patient_query("0929990002", "وين مكان المصحة ومن دكتور الجراحة المتواجد اليوم الجمعة؟")
    print("\nPatient Query: وين مكان المصحة ومن دكتور الجراحة المتواجد اليوم الجمعة؟")
    print(f"Bot Response:\n{resp_amal}")

    # Strict Generality Assertions
    assert "الأمل" in resp_amal or "بنغازي" in resp_amal, "Must identify as Al-Amal or Benghazi"
    assert "طارق المجبري" in resp_amal, "Must identify Al-Amal surgeon Dr. Tareq Al-Mejbari"
    assert "النور" not in resp_amal, "CRITICAL ERROR: Al-Noor must NOT appear for Al-Amal!"
    assert "زليتن" not in resp_amal, "CRITICAL ERROR: Zliten must NOT appear for Al-Amal!"
    assert "0910101010" not in resp_amal, "CRITICAL ERROR: Al-Noor phone must NOT appear for Al-Amal!"
    print("✅ Dynamic Clinic Switch to Al-Amal Passed 100% Zero-Hardcoding!")

    # -------------------------------------------------------------
    # 3. Dynamic Switch to Non-Medical Facility (مجموعة الرواد للاستشارات والتدريب - طرابلس)
    # -------------------------------------------------------------
    print("\n--- 3. Dynamically Switching to Non-Medical Facility (مجموعة الرواد للاستشارات والتدريب) ---")
    rowad_profile = {
        "name": "مجموعة الرواد للاستشارات والتدريب",
        "clinic_name": "مجموعة الرواد للاستشارات والتدريب",
        "facility_type": "مركز استشارات وتدريب",
        "address": "طرابلس - حي الأندلس بجوار برج طرابلس",
        "city": "طرابلس",
        "emergency_phone": "0918889900",
        "reception_phone": "0918889900",
        "contact_numbers": "0918889900",
        "booking_policy": "المواعيد والاستشارات تُحجز مسبقاً خلال ساعات العمل من 09:00 ص إلى 05:00 م.",
        "facilities_info": "قاعات تدريب مجهزة، خدمات استشارات قانونية ومالية، قاعة اجتماعات لكبار العملاء.",
        "is_medical": "0"
    }
    db.update_facility_profile(rowad_profile)

    with db.get_db() as conn:
        conn.execute("DELETE FROM emergency_clinics;")
        conn.execute("DELETE FROM followup_clinics;")
        conn.execute("DELETE FROM daily_overrides;")
        conn.execute("DELETE FROM conversation_history;")

        conn.execute("""
            INSERT INTO followup_clinics (day_of_week, specialty, doctor_name, shift_note)
            VALUES ('الجمعة', 'استشارات العقود والشركات', 'المستشار سالم الورفلي', '10:00 ص - 02:00 ظ');
        """)

    prof_rowad = db.get_facility_profile()
    print(f"Switched Facility: {prof_rowad['name']} (Medical={prof_rowad['is_medical']})")

    resp_rowad = patient_service.handle_patient_query("0917770003", "شن خدماتكم وعنوانكم ومن مسؤول استشارات العقود اليوم؟")
    print("\nClient Query: شن خدماتكم وعنوانكم ومن مسؤول استشارات العقود اليوم؟")
    print(f"Bot Response:\n{resp_rowad}")

    assert "الرواد" in resp_rowad or "طرابلس" in resp_rowad, "Must identify as Al-Rowad or Tripoli"
    assert "سالم الورفلي" in resp_rowad, "Must identify consultant Salem Al-Warfali"
    assert "النور" not in resp_rowad, "Must not mention Al-Noor"
    assert "زليتن" not in resp_rowad, "Must not mention Zliten"
    print("✅ Non-Medical Facility Generality Test Passed 100%!")

    # -------------------------------------------------------------
    # 4. Clean Baseline Restoration (Al-Noor Demo Clinic)
    # -------------------------------------------------------------
    print("\n--- 4. Restoring Al-Noor Demo Clinic Baseline ---")
    seed_demo()
    final_prof = db.get_facility_profile()
    print(f"Restored Facility: {final_prof['name']} in {final_prof['city']}")
    print("=" * 70)
    print("🎉 ALL MULTI-FACILITY GENERALITY TESTS PASSED 100%! 🎉")
    print("=" * 70)


if __name__ == "__main__":
    run_tests()
