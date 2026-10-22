import sys
import os

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Add project path
project_path = r"C:\Users\awsat\Desktop\LibyAI"
if project_path not in sys.path:
    sys.path.insert(0, project_path)

from app.config import is_phone_authorized, normalize_phone_digits, settings
import db

def test_phone_authorization_security():
    print("--- 1. Testing Phone Authorization Security ---")
    authorized_list = "0912345678, 0921111111, 218912345678"

    # Should FAIL (Unauthorized spoofing attempts)
    assert not is_phone_authorized("admin", authorized_list), "Spoofed 'admin' should NOT be authorized!"
    assert not is_phone_authorized("staff", authorized_list), "Spoofed 'staff' should NOT be authorized!"
    assert not is_phone_authorized("مدير المصحة", authorized_list), "Spoofed 'مدير المصحة' should NOT be authorized!"
    assert not is_phone_authorized("0912345679", authorized_list), "Different phone should NOT be authorized!"
    assert not is_phone_authorized("678", authorized_list), "Partial phone '678' should NOT be authorized!"
    assert not is_phone_authorized("5678", authorized_list), "Partial phone '5678' should NOT be authorized!"
    assert not is_phone_authorized("092345678", authorized_list), "Wrong prefix should NOT be authorized!"
    assert not is_phone_authorized("", authorized_list), "Empty string should NOT be authorized!"

    # Should SUCCEED (Legitimate authorized numbers in various formats)
    assert is_phone_authorized("0912345678", authorized_list), "0912345678 should be authorized!"
    assert is_phone_authorized("+218 91 234 5678", authorized_list), "+218 91 234 5678 should be authorized!"
    assert is_phone_authorized("218912345678", authorized_list), "218912345678 should be authorized!"
    assert is_phone_authorized("٠٩١٢٣٤٥٦٧٨", authorized_list), "Arabic numeral phone should be authorized!"
    assert is_phone_authorized("092-1111111", authorized_list), "092-1111111 should be authorized!"

    print("✅ All phone authorization security tests PASSED!")


def test_reset_and_seeding():
    print("--- 2. Testing Database Reset & Re-Seeding ---")
    with db.get_db() as conn:
        conn.execute("DELETE FROM doctors;")
        conn.execute("DELETE FROM services;")
    
    # Check count is 0
    with db.get_db() as conn:
        doc_cnt = conn.execute("SELECT COUNT(*) FROM doctors;").fetchone()[0]
        assert doc_cnt == 0, "Doctors should be 0 before reset"

    # Call init_db and seed_default_data
    db.init_db()
    db.seed_default_data()

    with db.get_db() as conn:
        doc_cnt = conn.execute("SELECT COUNT(*) FROM doctors;").fetchone()[0]
        svc_cnt = conn.execute("SELECT COUNT(*) FROM services;").fetchone()[0]
        assert doc_cnt > 0, f"Doctors should be re-seeded, got {doc_cnt}"
        assert svc_cnt > 0, f"Services should be re-seeded, got {svc_cnt}"

    print(f"✅ Reset & Re-seeding test PASSED! ({doc_cnt} doctors, {svc_cnt} services)")


def test_no_admin_keyword_in_db():
    print("--- 3. Testing DB clean of 'admin' in authorized phones ---")
    info = db.get_clinic_info()
    auth_phones = info.get("authorized_phones", "")
    assert "admin" not in auth_phones.lower(), f"'admin' keyword found in clinic_info: {auth_phones}"
    assert "staff" not in auth_phones.lower(), f"'staff' keyword found in clinic_info: {auth_phones}"
    print(f"✅ Clinic info authorized phones are clean: '{auth_phones}'")


if __name__ == "__main__":
    test_phone_authorization_security()
    test_reset_and_seeding()
    test_no_admin_keyword_in_db()
    print("\n🎉 ALL PHASE 1 SECURITY TESTS COMPLETED SUCCESSFULLY!")
