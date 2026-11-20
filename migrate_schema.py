import argparse
import os
import sqlite3


def run_migration(db_path=None):
    db_path = db_path or os.environ.get("DB_PATH", "clinic.db")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    tables = [r[0] for r in cursor.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()]

    # 1. Update doctors table columns
    if 'doctors' in tables:
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
    else:
        print('No doctors table; skipping doctor migration.')

    # 2. Update services table columns
    if 'services' in tables:
        svc_cols = [c[1] for c in cursor.execute('PRAGMA table_info(services)').fetchall()]
        print('Existing services cols:', svc_cols)
        if 'prep_instructions' not in svc_cols:
            cursor.execute("ALTER TABLE services ADD COLUMN prep_instructions TEXT DEFAULT '';")
        if 'availability' not in svc_cols:
            cursor.execute("ALTER TABLE services ADD COLUMN availability TEXT DEFAULT 'متاح خلال ساعات العمل الرسمية';")

        cursor.execute("UPDATE services SET prep_instructions = instructions WHERE prep_instructions IS NULL OR prep_instructions = '';")
    else:
        print('No services table; skipping service migration.')

    # 3. Sync clinic_info with aliases
    if 'clinic_info' not in tables:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS clinic_info (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """)
        tables.append('clinic_info')
    info_rows = cursor.execute('SELECT key, value FROM clinic_info;').fetchall()
    info_dict = {r[0]: r[1] for r in info_rows}
    print('Existing clinic_info keys:', list(info_dict.keys()))

    clinic_name = info_dict.get('name') or info_dict.get('clinic_name') or 'مصحة الشفاء التخصصية'
    cursor.execute("INSERT OR REPLACE INTO clinic_info (key, value) VALUES ('name', ?);", (clinic_name,))
    cursor.execute("INSERT OR REPLACE INTO clinic_info (key, value) VALUES ('clinic_name', ?);", (clinic_name,))

    auth_phones = info_dict.get('authorized_staff_phones') or info_dict.get('authorized_phones') or '0920202020, 0921111111, admin, staff'
    cursor.execute("INSERT OR REPLACE INTO clinic_info (key, value) VALUES ('authorized_staff_phones', ?);", (auth_phones,))
    cursor.execute("INSERT OR REPLACE INTO clinic_info (key, value) VALUES ('authorized_phones', ?);", (auth_phones,))

    # 4. Sync clinic_config table if exists
    if 'clinic_config' in tables:
        for k, v in cursor.execute('SELECT key, value FROM clinic_info;').fetchall():
            cursor.execute("INSERT OR REPLACE INTO clinic_config (key, value) VALUES (?, ?);", (k, v))

    # 5. Messenger-first / multi-sector pivot: business tables.
    # db.init_db() creates these too; this script is the standalone path
    # for an existing clinic.db that is migrated by hand.
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS business_info (
        id INTEGER PRIMARY KEY CHECK(id = 1),
        name TEXT NOT NULL,
        sector TEXT NOT NULL DEFAULT 'clinic'
            CHECK(sector IN ('retail', 'restaurant', 'clinic', 'pharmacy',
                             'service_office', 'workshop', 'general', 'medical')),
        address TEXT NOT NULL DEFAULT 'ليبيا',
        map_link TEXT DEFAULT '',
        support_phone TEXT DEFAULT '',
        escalation_phone TEXT DEFAULT '',
        working_hours TEXT DEFAULT '',
        policy_notes TEXT DEFAULT '',
        currency TEXT NOT NULL DEFAULT 'LYD',
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS catalog_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        category TEXT NOT NULL DEFAULT '',
        price_lyd REAL NOT NULL DEFAULT 0.0,
        is_available INTEGER NOT NULL DEFAULT 1,
        schedule_or_eta TEXT DEFAULT '',
        details TEXT DEFAULT '',
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS resources (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        role_or_specialty TEXT NOT NULL DEFAULT '',
        schedule TEXT DEFAULT '',
        is_available INTEGER NOT NULL DEFAULT 1,
        notes TEXT DEFAULT '',
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS business_faqs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        question TEXT NOT NULL,
        answer TEXT NOT NULL,
        keywords TEXT DEFAULT '',
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Backfill the single business_info row from clinic_info when missing.
    row = cursor.execute("SELECT COUNT(*) FROM business_info;").fetchone()
    if row[0] == 0:
        sector = (info_dict.get('sector') or 'clinic').strip().lower()
        if sector not in ('retail', 'restaurant', 'clinic', 'pharmacy',
                          'service_office', 'workshop', 'general', 'medical'):
            sector = 'clinic'
        cursor.execute("""
        INSERT INTO business_info (
            id, name, sector, address, map_link, support_phone,
            escalation_phone, working_hours, policy_notes, currency
        ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, (
            clinic_name,
            sector,
            info_dict.get('address') or 'ليبيا',
            info_dict.get('map_link') or '',
            info_dict.get('reception_phone') or '',
            info_dict.get('emergency_phone') or '',
            info_dict.get('working_hours') or info_dict.get('shifts_info') or '',
            info_dict.get('booking_policy') or '',
            info_dict.get('currency') or 'LYD',
        ))
        print('Backfilled business_info from clinic_info.')

    # 6. Channel columns for (channel, external_message_id) deduplication.
    for table in ('incoming_messages', 'message_jobs',
                  'conversation_history', 'conversation_sessions'):
        if table in tables:
            cols = [c[1] for c in cursor.execute(f'PRAGMA table_info({table})').fetchall()]
            if 'channel' not in cols:
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN channel TEXT NOT NULL DEFAULT 'whatsapp';")
                if table in ('incoming_messages', 'message_jobs'):
                    cursor.execute(f"UPDATE {table} SET channel = provider;")
                print(f'Added channel column to {table}.')
    if 'incoming_messages' in tables:
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_incoming_channel_mid ON incoming_messages(channel, message_id);")
    # NOTE: the message_jobs UNIQUE(message_id) -> UNIQUE(channel,
    # message_id) rebuild is done by db.init_db(), not here, because it
    # needs a table rebuild (SQLite cannot alter a UNIQUE constraint).

    conn.commit()
    conn.close()
    print(f'Schema migration and clinic info sync completed successfully! (db: {db_path})')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Migrate a LibyAI SQLite database to the current schema (multi-sector + channels).")
    parser.add_argument("--db", default=os.environ.get("DB_PATH", "clinic.db"),
                        help="SQLite database path (default: DB_PATH env or clinic.db).")
    args = parser.parse_args()
    run_migration(db_path=args.db)
