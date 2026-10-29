import sys
import json
import time
from fastapi.testclient import TestClient
from app.main import app

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Previously this test required a live server on 127.0.0.1:8000.
# It now uses TestClient against the real app, so it runs in CI too.
client = TestClient(app)


def test_full_scenario():
    # Reset to a known state first: this suite shares clinic.db with the
    # root tests, and a previous run leaves doctors in left/arrived/
    # booking_closed states that would make the assertions below
    # order-dependent. The scenario itself then drives every change.
    import db as _db

    with _db.get_db() as _conn:
        _conn.execute("UPDATE doctors SET status = 'available', today_status = 'available', daily_note = '', today_note = '';")
        _conn.execute("DELETE FROM daily_overrides;")
    print("==================================================")
    print("1. Checking Server & Libya Time State...")
    res = client.get(f"/api/simulator/state")
    assert res.status_code == 200, f"Failed to get state: {res.status_code}"
    state = res.json()
    libya_time = state.get("libya_time", {})
    print(f"Libya Time Context: {libya_time.get('summary')}")

    print("\n==================================================")
    print("2. Testing Admin Update: 'دكتور العظام غادر العيادة وروح خلاص'")
    t0 = time.time()
    res = client.post(f"/api/simulator/admin-message", json={
        "sender": "0912345678",
        "message": "دكتور العظام غادر العيادة وروح خلاص"
    })
    elapsed = time.time() - t0
    assert res.status_code == 200, f"Admin message failed: {res.status_code}"
    admin_data = res.json()
    print(f"Time taken: {elapsed:.2f}s")
    print(f"Admin Reply:\n{admin_data['reply']}")

    # Verify DB status of the doctor named in the receipt. The seed has
    # several doctors per specialty, and the update targets the one on
    # duty today, so "first doctor with this specialty" is the wrong
    # doctor to check.
    import re as _re

    def _doctor_named_in_receipt(reply, doctors):
        _m = _re.search(r"\*الطبيب:\*\s*(.+?)\s*\(", reply)
        assert _m, f"Receipt did not name a doctor: {reply[:200]}"
        _name = _m.group(1).strip()
        _doc = next((d for d in doctors if d["name"] == _name), None)
        assert _doc is not None, f"Doctor named in receipt not in state: {_name}"
        return _doc

    res = client.get(f"/api/simulator/state")
    state = res.json()
    ortho_doc = _doctor_named_in_receipt(admin_data["reply"], state["doctors"])
    print(f"Ortho Doctor Status in DB: {ortho_doc['today_status']} | Note: {ortho_doc['today_note']}")
    assert ortho_doc["today_status"] == "left", f"Expected 'left', got {ortho_doc['today_status']}"

    print("\n==================================================")
    print("3. Testing Patient Inquiry about Ortho Doctor who left:")
    print("Patient: 'السلام عليكم، دكتور العظام قاعد توا نقدر نجي نكشف؟'")
    t0 = time.time()
    res = client.post(f"/api/simulator/patient-message", json={
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
    res = client.post(f"/api/simulator/admin-message", json={
        "sender": "0912345678",
        "message": "دكتور الباطنة وصل وبدأ يستقبل كشوفات"
    })
    print(f"Admin Reply:\n{res.json()['reply']}")
    _internal_reply = res.json()["reply"]
    res = client.get(f"/api/simulator/state")
    internal_doc = _doctor_named_in_receipt(_internal_reply, res.json()["doctors"])
    print(f"Internal Med Doctor Status: {internal_doc['today_status']}")
    assert internal_doc["today_status"] == "arrived"

    print("\n==================================================")
    print("5. Testing Admin Update: 'وقفوا حجز عيادة الأطفال خلاص اكتفوا بالعدد اليوم'")
    res = client.post(f"/api/simulator/admin-message", json={
        "sender": "0912345678",
        "message": "وقفوا حجز عيادة الأطفال خلاص اكتفوا بالعدد اليوم"
    })
    print(f"Admin Reply:\n{res.json()['reply']}")
    _ped_reply = res.json()["reply"]
    res = client.get(f"/api/simulator/state")
    ped_doc = _doctor_named_in_receipt(_ped_reply, res.json()["doctors"])
    print(f"Pediatrics Doctor Status: {ped_doc['today_status']}")
    assert ped_doc["today_status"] == "booking_closed"

    print("\n==================================================")
    print("6. Testing Patient Inquiry about Pediatrics Booking:")
    print("Patient: 'نبي نجي نكشف لولدي عند دكتور الأطفال نقدر نحجز توا؟'")
    t0 = time.time()
    res = client.post(f"/api/simulator/patient-message", json={
        "sender": "0919998877",
        "message": "نبي نجي نكشف لولدي عند دكتور الأطفال نقدر نحجز توا؟"
    })
    elapsed = time.time() - t0
    print(f"Time taken: {elapsed:.2f}s")
    print(f"Patient Bot Reply:\n{res.json()['reply']}")

    print("\n==================================================")
    print("7. Testing Casual Chatter from Staff (Should be cleanly ignored):")
    res = client.post(f"/api/simulator/admin-message", json={
        "sender": "0912345678",
        "message": "شن جو الشغل اليوم؟"
    })
    print(f"Chatter Response: {res.json()}")
    # Wording updated to the app's current message; the behavior checked
    # here is unchanged: casual chatter is recognized as no update order.
    assert "لم يتم التعرف على أمر تحديث مباشر" in res.json()["reply"]

    print("\n==================================================")
    print("ALL TESTS PASSED SUCCESSFULLY! ✅")

if __name__ == "__main__":
    test_full_scenario()
