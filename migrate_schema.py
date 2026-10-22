import sqlite3

def run_migration():
    conn = sqlite3.connect('clinic.db')
    cursor = conn.cursor()

    # 1. Update doctors table columns
    doc_cols = [c[1] for c in cursor.execute('PRAGMA table_info(doctors)').fetchall()]
    print('Existing doctors cols:', doc_cols)
    if 'room_number' not in doc_cols:
        cursor.execute("ALTER TABLE doctors ADD COLUMN room_number TEXT DEFAULT 'غير محدد';")
    if 'schedule_days' not in doc_cols:
        cursor.execute("ALTER TABLE doctors ADD COLUMN schedule_days TEXT DEFAULT 'السبت,الأحد,الإثنين,الثلاثاء,الأربعاء,الخميس';")
    if 'today_status' not in doc_cols:
        cursor.execute("ALTER TABLE doctors ADD COLUMN today_status TEXT DEFAULT 'available';")
    if 'today_note' not in doc_cols:
        cursor.execute("ALTER TABLE doctors ADD COLUMN today_note TEXT DEFAULT '';")
    if 'is_active' not in doc_cols:
        cursor.execute("ALTER TABLE doctors ADD COLUMN is_active INTEGER DEFAULT 1;")

    cursor.execute("UPDATE doctors SET today_status = status WHERE today_status IS NULL OR today_status = '';")
    cursor.execute("UPDATE doctors SET today_note = daily_note WHERE today_note IS NULL OR today_note = '';")

    # 2. Update services table columns
    svc_cols = [c[1] for c in cursor.execute('PRAGMA table_info(services)').fetchall()]
    print('Existing services cols:', svc_cols)
    if 'prep_instructions' not in svc_cols:
        cursor.execute("ALTER TABLE services ADD COLUMN prep_instructions TEXT DEFAULT '';")
    if 'availability' not in svc_cols:
        cursor.execute("ALTER TABLE services ADD COLUMN availability TEXT DEFAULT 'متاح خلال ساعات العمل الرسمية';")

    cursor.execute("UPDATE services SET prep_instructions = instructions WHERE prep_instructions IS NULL OR prep_instructions = '';")

    # 3. Sync clinic_info with aliases
    info_rows = cursor.execute('SELECT key, value FROM clinic_info;').fetchall()
    info_dict = {r[0]: r[1] for r in info_rows}
    print('Existing clinic_info keys:', list(info_dict.keys()))

    clinic_name = info_dict.get('name') or info_dict.get('clinic_name') or 'مصحة الشفاء التخصصية'
    cursor.execute("INSERT OR REPLACE INTO clinic_info (key, value) VALUES ('name', ?);", (clinic_name,))
    cursor.execute("INSERT OR REPLACE INTO clinic_info (key, value) VALUES ('clinic_name', ?);", (clinic_name,))

    auth_phones = info_dict.get('authorized_staff_phones') or info_dict.get('authorized_phones') or '0912345678, 0921111111, admin, staff'
    cursor.execute("INSERT OR REPLACE INTO clinic_info (key, value) VALUES ('authorized_staff_phones', ?);", (auth_phones,))
    cursor.execute("INSERT OR REPLACE INTO clinic_info (key, value) VALUES ('authorized_phones', ?);", (auth_phones,))

    # 4. Sync clinic_config table if exists
    tables = [r[0] for r in cursor.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()]
    if 'clinic_config' in tables:
        for k, v in cursor.execute('SELECT key, value FROM clinic_info;').fetchall():
            cursor.execute("INSERT OR REPLACE INTO clinic_config (key, value) VALUES (?, ?);", (k, v))

    conn.commit()
    conn.close()
    print('Schema migration and clinic info sync completed successfully!')

if __name__ == '__main__':
    run_migration()
