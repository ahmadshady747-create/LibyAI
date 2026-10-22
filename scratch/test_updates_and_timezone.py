import sys
import requests
import json
import time

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_URL = "http://127.0.0.1:8000"


def test_full_scenario():
    print("==================================================")
    print("1. Checking Server & Libya Time State...")
    res = requests.get(f"{BASE_URL}/api/simulator/state")
    assert res.status_code == 200, f"Failed to get state: {res.status_code}"
    state = res.json()
    libya_time = state.get("libya_time", {})
    print(f"Libya Time Context: {libya_time.get('summary')}")

    print("\n==================================================")
    print("2. Testing Admin Update: 'دكتور العظام غادر العيادة وروح خلاص'")
    t0 = time.time()
    res = requests.post(f"{BASE_URL}/api/simulator/admin-message", json={
        "sender": "0912345678",
        "message": "دكتور العظام غادر العيادة وروح خلاص"
    })
    elapsed = time.time() - t0
    assert res.status_code == 200, f"Admin message failed: {res.status_code}"
    admin_data = res.json()
    print(f"Time taken: {elapsed:.2f}s")
    print(f"Admin Reply:\n{admin_data['reply']}")

    # Verify DB status
    res = requests.get(f"{BASE_URL}/api/simulator/state")
    state = res.json()
    ortho_doc = next((d for d in state["doctors"] if "عظام" in d["specialty"]), None)
    print(f"Ortho Doctor Status in DB: {ortho_doc['today_status']} | Note: {ortho_doc['today_note']}")
    assert ortho_doc["today_status"] == "left", f"Expected 'left', got {ortho_doc['today_status']}"

    print("\n==================================================")
    print("3. Testing Patient Inquiry about Ortho Doctor who left:")
    print("Patient: 'السلام عليكم، دكتور العظام قاعد توا نقدر نجي نكشف؟'")
    t0 = time.time()
    res = requests.post(f"{BASE_URL}/api/simulator/patient-message", json={
        "sender": "0919998877",
        "message": "السلام عليكم، دكتور العظام قاعد توا نقدر نجي نكشف؟"
    })
    elapsed = time.time() - t0
    assert res.status_code == 200
    patient_reply = res.json()["reply"]
    print(f"Time taken: {elapsed:.2f}s")
    print(f"Patient Bot Reply:\n{patient_reply}")

    print("\n==================================================")
    print("4. Testing Admin Update: 'دكتور الباطنة وصل وبدأ يستقبل كشوفات'")
    res = requests.post(f"{BASE_URL}/api/simulator/admin-message", json={
        "sender": "0912345678",
        "message": "دكتور الباطنة وصل وبدأ يستقبل كشوفات"
    })
    print(f"Admin Reply:\n{res.json()['reply']}")
    res = requests.get(f"{BASE_URL}/api/simulator/state")
    internal_doc = next((d for d in res.json()["doctors"] if "باطنة" in d["specialty"]), None)
    print(f"Internal Med Doctor Status: {internal_doc['today_status']}")
    assert internal_doc["today_status"] == "arrived"

    print("\n==================================================")
    print("5. Testing Admin Update: 'وقفوا حجز عيادة الأطفال خلاص اكتفوا بالعدد اليوم'")
    res = requests.post(f"{BASE_URL}/api/simulator/admin-message", json={
        "sender": "0912345678",
        "message": "وقفوا حجز عيادة الأطفال خلاص اكتفوا بالعدد اليوم"
    })
    print(f"Admin Reply:\n{res.json()['reply']}")
    res = requests.get(f"{BASE_URL}/api/simulator/state")
    ped_doc = next((d for d in res.json()["doctors"] if "طفال" in d["specialty"]), None)
    print(f"Pediatrics Doctor Status: {ped_doc['today_status']}")
    assert ped_doc["today_status"] == "booking_closed"

    print("\n==================================================")
    print("6. Testing Patient Inquiry about Pediatrics Booking:")
    print("Patient: 'نبي نجي نكشف لولدي عند دكتور الأطفال نقدر نحجز توا؟'")
    t0 = time.time()
    res = requests.post(f"{BASE_URL}/api/simulator/patient-message", json={
        "sender": "0919998877",
        "message": "نبي نجي نكشف لولدي عند دكتور الأطفال نقدر نحجز توا؟"
    })
    elapsed = time.time() - t0
    print(f"Time taken: {elapsed:.2f}s")
    print(f"Patient Bot Reply:\n{res.json()['reply']}")

    print("\n==================================================")
    print("7. Testing Casual Chatter from Staff (Should be cleanly ignored):")
    res = requests.post(f"{BASE_URL}/api/simulator/admin-message", json={
        "sender": "0912345678",
        "message": "شن جو الشغل اليوم؟"
    })
    print(f"Chatter Response: {res.json()}")
    assert "لم يتم التعرف على أمر تعديل مباشر" in res.json()["reply"]

    print("\n==================================================")
    print("ALL TESTS PASSED SUCCESSFULLY! ✅")

if __name__ == "__main__":
    test_full_scenario()
