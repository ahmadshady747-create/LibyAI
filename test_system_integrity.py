import sys
import asyncio
import httpx
import json
import sqlite3

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
        sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
    except Exception:
        pass
import time
from guardrails import evaluate_triage, TriageLevel
from db import get_clinic_info, get_all_doctors, update_doctor_atomic, find_doctor_fuzzy, update_clinic_info_key
from customer_service import handle_customer_query
from admin_service import handle_admin_group_message
from debouncer import message_debouncer

async def test_triage():
    print("\n--- 1. Testing Triage Level 1 (Emergency Fast-Path Interceptor) ---")
    clinic_info = get_clinic_info()
    
    test_cases = [
        ("severe_bleeding", "المريض ينزف دم غزير وما يبيش يوقف ساعدونا"),
        ("severe_bleeding_2", "عندي نزيف حاد ومستمر بعد العملية"),
        ("sudden_chest_pain", "وجع قوي في الصدر ويمتد ليدي اليسار"),
        ("sudden_chest_pain_2", "صدري يوجعني فجاة نحس بجلطة"),
        ("acute_dyspnea", "ضيق تنفس شديد ومش قادر نتنفس"),
        ("acute_dyspnea_2", "خنقة شديدة واختناق وازرقاق وجه"),
        ("loss_of_consciousness", "طاحت ومغمى عليها ومش واعية"),
        ("loss_of_consciousness_2", "فاقد الوعي ولا يستجيب للكلام"),
        ("acute_poisoning", "الولد شرب كلور ومنظف"),
        ("acute_poisoning_2", "بلع شريط حبوب وجرعة زائدة"),
        ("pediatric_lethargy", "حرارة 40 مع تشنج حراري"),
        ("pediatric_lethargy_2", "بنتي تتشنج ومش قادرة تتنفس"),
    ]
    
    for label, text in test_cases:
        res = evaluate_triage(text, clinic_info)
        assert res.level == TriageLevel.EMERGENCY_LEVEL_1, f"Failed for {label}: got {res.level}"
        assert res.is_emergency is True
        assert "طوارئ" in res.immediate_response or "عاجل" in res.immediate_response
        print(f"  [PASS] {label}: detected emergency flag -> {res.matched_flags}")

    print("\n--- 2. Testing Triage Level 2 (Clinical Advice Prohibition) ---")
    advice_cases = [
        "شن ناخذ دواء للمغص والبطن؟",
        "اعطيني اسم مضاد حيوي مناسب لالتهاب الحلق",
        "كم جرعة البنادول للاطفال؟",
        "فسرلي نتيجة التحليل الرقم طالع عالي",
    ]
    for text in advice_cases:
        res = evaluate_triage(text, clinic_info)
        assert res.level == TriageLevel.CLINICAL_ADVICE_LEVEL_2, f"Failed for '{text}': got {res.level}"
        assert res.is_clinical_advice_prohibited is True
        assert "يمنع" in res.immediate_response or "الاستقبال" in res.immediate_response
        print(f"  [PASS] Advice guardrail triggered for: '{text}'")

    print("\n--- 3. Testing Triage Level 3 (Routine Inquiries pass-through) ---")
    routine_cases = [
        "السلام عليكم من دكتور العظام اليوم؟",
        "قداش كشف الباطنة؟",
        "هل عندكم تحليل دم شامل وبكم؟",
    ]
    for text in routine_cases:
        res = evaluate_triage(text, clinic_info)
        assert res.level == TriageLevel.ROUTINE_LEVEL_3, f"Failed for '{text}': got {res.level}"
        assert res.immediate_response is None
        print(f"  [PASS] Routine pass-through for: '{text}'")


async def test_patient_ai_and_multiturn():
    print("\n--- 4. Testing Patient AI Service & Sliding Multi-Turn History ---")
    phone = f"21891{int(time.time() * 1000) % 10000000:07d}"
    
    # Turn 1
    resp1 = handle_customer_query(phone, "السلام عليكم، من دكتور العظام الموجود اليوم؟")
    print(f"\nTurn 1 Response:\n{resp1}\n")
    assert "عظام" in resp1
    assert "⚠️" not in resp1

    await asyncio.sleep(1.5)

    # Turn 2: Contextual follow-up
    resp2 = handle_customer_query(phone, "وقداش سعر كشفه؟")
    print(f"\nTurn 2 Response (Contextual Follow-up):\n{resp2}\n")
    assert "40" in resp2 or "دينار" in resp2 or "دكتور" in resp2

    await asyncio.sleep(1.5)

    # Turn 3: Booking policy
    resp3 = handle_customer_query(phone, "احجزلي موعد معاه")
    print(f"\nTurn 3 Response (Booking Request):\n{resp3}\n")
    # Must enforce in-person booking
    assert any(term in resp3 for term in ["حضور", "مباشر", "استقبال", "تذكرة", "أسبقية", "اسبقية"])


async def test_admin_service():
    print("\n--- 5. Testing Admin WhatsApp Group NLP & Edge Cases ---")
    # Use the seeded test staff number: the previous number was not in the
    # seeded authorized list, so every "valid" update was rejected as
    # unauthorized and the test could never pass.
    auth_phone = "0920202020"
    unauth_phone = "0990000000"

    # Test Unauthorized
    unauth_resp = handle_admin_group_message(unauth_phone, "@Bot دكتور العظام اعتذر")
    assert "غير مصرح" in unauth_resp
    print(f"  [PASS] Unauthorized phone successfully rejected.")

    # Test Ambiguous update
    ambig_resp = handle_admin_group_message(auth_phone, "@Bot الدكتور مش جاي اليوم")
    assert "تعذر" in ambig_resp or "تحديد" in ambig_resp
    print(f"  [PASS] Ambiguous request rejected gracefully:\n  --> {ambig_resp}")

    await asyncio.sleep(1.5)

    # Test Valid Update 1: Doctor departed / apologized
    # "يوسف العربي" is the fictional orthopedics doctor present in both
    # seed paths (db.py default seed and seed_demo.py).
    valid_resp = handle_admin_group_message(auth_phone, "@Bot دكتور العظام يوسف العربي روح وما عادش يستقبل اليوم")
    print(f"\nAdmin Valid Update Receipt 1:\n{valid_resp}\n")
    assert "يوسف" in valid_resp or "العربي" in valid_resp
    assert any(w in valid_resp for w in ["معتذر", "غادر", "روح", "apologized", "left"])

    # Verify DB directly
    doc = find_doctor_fuzzy(name_query="يوسف العربي", specialty_query="عظام")
    assert doc is not None
    assert doc["status"] in ["apologized", "left"]
    print(f"  [PASS] SQLite state successfully mutated: status={doc.get('status')}")

    await asyncio.sleep(1.5)

    # Patient asks about Dr Youssef now
    check_phone = f"21892{int(time.time() * 1000) % 10000000:07d}"
    patient_resp = handle_customer_query(check_phone, "هل دكتور العظام يوسف العربي متاح الآن للكشف؟")
    print(f"\nPatient Check After Doctor Apologized/Left:\n{patient_resp}\n")
    assert any(w in patient_resp for w in ["معتذر", "غادر", "روح", "غير متاح", "اعتذر", "انهى", "أنهى"])

    await asyncio.sleep(1.5)

    # Restore Doctor back to available
    restore_resp = handle_admin_group_message(auth_phone, "@Bot دكتور يوسف العربي عظام متاح اليوم والكشف 40")
    print(f"\nAdmin Restore Receipt:\n{restore_resp}\n")
    doc_after = find_doctor_fuzzy(name_query="يوسف العربي", specialty_query="عظام")
    assert doc_after["status"] == "available"
    print(f"  [PASS] SQLite state restored: status={doc_after.get('status')}")


async def test_http_api_endpoints():
    print("\n--- 6. Testing Simulator HTTP API Endpoints ---")
    # Previously this test required a live server on 127.0.0.1:8000, so it
    # could never pass under pytest and failed with a proxy URL error in
    # sandboxed environments. Use FastAPI's TestClient instead: it runs the
    # real app (including lifespan seeding) in-process, with no live server.
    from fastapi.testclient import TestClient
    from app.main import app as fastapi_app

    with TestClient(fastapi_app) as client:
        # GET /api/simulator/state
        r_state = client.get("/api/simulator/state")
        assert r_state.status_code == 200, f"Expected 200, got {r_state.status_code}"
        state_data = r_state.json()
        assert "doctors" in state_data
        assert "configs" in state_data
        print(f"  [PASS] /api/simulator/state OK (doctors count: {len(state_data['doctors'])})")

        # POST /api/simulator/patient-message
        r_pat = client.post("/api/simulator/patient-message", json={"sender": "218910001122", "message": "السلام عليكم"})
        assert r_pat.status_code == 200
        assert "reply" in r_pat.json()
        print(f"  [PASS] /api/simulator/patient-message OK -> reply received ({len(r_pat.json()['reply'])} chars)")

        # POST /api/simulator/admin-message
        r_adm = client.post("/api/simulator/admin-message", json={"sender": "0915556677", "message": "@Bot دكتور باطنة متاح اليوم"})
        assert r_adm.status_code == 200
        assert "reply" in r_adm.json()
        print(f"  [PASS] /api/simulator/admin-message OK -> reply received")

        # POST /api/simulator/clinic-settings (Save settings)
        # Snapshot first, and restore afterwards: this test shares the
        # working clinic.db with the scratch suite, and a leftover
        # "authorized_phones" value here used to break the scratch test
        # that asserts no keyword like "admin" is stored as a phone.
        _clinic_before = get_clinic_info()
        _settings_keys = [
            "clinic_name", "emergency_phone", "reception_phone",
            "address", "booking_policy", "authorized_phones",
        ]
        r_set = client.post("/api/simulator/clinic-settings", json={
            "clinic_name": "مصحة الشفاء التخصصية - فرع طرابلس",
            "emergency_phone": "091-2223344",
            "reception_phone": "092-1111111",
            "address": "طرابلس",
            "booking_policy": "الحجز بالحضور الشخصي فقط",
            "authorized_phones": "0915556677, 0928889900"
        })
        assert r_set.status_code == 200
        assert r_set.json().get("status") == "success"
        print(f"  [PASS] /api/simulator/clinic-settings saved successfully")
        for _k in _settings_keys:
            if _k in _clinic_before:
                update_clinic_info_key(_k, _clinic_before[_k])


async def main():
    print("=" * 60)
    print("STARTING LIBYAI FULL INTEGRITY & LOGIC VERIFICATION SUITE")
    print("=" * 60)
    await test_triage()
    await test_patient_ai_and_multiturn()
    await test_admin_service()
    await test_http_api_endpoints()
    print("\n" + "=" * 60)
    print("ALL VERIFICATION SUITE TESTS PASSED WITH ZERO ERRORS!")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())
