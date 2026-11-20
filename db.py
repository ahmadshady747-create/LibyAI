"""
LibyAI Database Layer (`db.py`)
Production-grade SQLite schema and helpers for clinic operations.

Tables:
1. doctors: id, name, specialty, regular_schedule, status, daily_note, consultation_fee, updated_at
2. services: id, name, category, price, instructions
3. clinic_info: key, value (name, address, emergency_phone, booking_policy, map_link)
4. conversation_sessions: id, phone_number, role, message_text, created_at
5. audit_logs: id, admin_sender, raw_message, status_before, status_after, confirmation_text, created_at
"""

import os
import sqlite3
import json
import time
from typing import Dict, Any, List, Optional, Tuple
from contextlib import contextmanager

DB_PATH = os.environ.get("DB_PATH", "clinic.db")


@contextmanager
def get_db(db_path: str = DB_PATH):
    """Thread-safe context manager providing SQLite connections with dict-like row access."""
    conn = sqlite3.connect(db_path, timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: str = DB_PATH) -> None:
    """Initializes tables, constraints, and indexes according to production specifications."""
    # Set WAL journal mode once during initialization
    try:
        conn_wal = sqlite3.connect(db_path, timeout=15.0)
        conn_wal.execute("PRAGMA journal_mode = WAL;")
        conn_wal.close()
    except Exception:
        pass

    with get_db(db_path) as conn:
        cursor = conn.cursor()

        # Migrate doctors table if legacy columns exist
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='doctors';")
        if cursor.fetchone():
            cursor.execute("PRAGMA table_info(doctors);")
            cols = [c["name"] for c in cursor.fetchall()]
            if "status" not in cols:
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS doctors_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    specialty TEXT NOT NULL,
                    regular_schedule TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('available', 'apologized', 'delayed', 'left', 'arrived', 'booking_closed')),
                    daily_note TEXT DEFAULT '',
                    consultation_fee REAL NOT NULL DEFAULT 40.0,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """)
                cursor.execute("""
                INSERT INTO doctors_new (id, name, specialty, regular_schedule, status, daily_note, consultation_fee, updated_at)
                SELECT id, name, specialty, regular_schedule,
                       COALESCE(today_status, 'available'),
                       COALESCE(today_note, ''),
                       COALESCE(consultation_fee, 40.0),
                       COALESCE(updated_at, CURRENT_TIMESTAMP)
                FROM doctors;
                """)
                cursor.execute("DROP TABLE doctors;")
                cursor.execute("ALTER TABLE doctors_new RENAME TO doctors;")

        # Migrate services table if legacy columns exist
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='services';")
        if cursor.fetchone():
            cursor.execute("PRAGMA table_info(services);")
            cols = [c["name"] for c in cursor.fetchall()]
            if "instructions" not in cols:
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS services_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    category TEXT NOT NULL,
                    price REAL NOT NULL DEFAULT 0.0,
                    instructions TEXT DEFAULT ''
                );
                """)
                cursor.execute("""
                INSERT INTO services_new (id, name, category, price, instructions)
                SELECT id, name, category, COALESCE(price, 0.0), COALESCE(prep_instructions, '')
                FROM services;
                """)
                cursor.execute("DROP TABLE services;")
                cursor.execute("ALTER TABLE services_new RENAME TO services;")

        # Migrate audit_logs if legacy columns exist
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='audit_logs';")
        if cursor.fetchone():
            cursor.execute("PRAGMA table_info(audit_logs);")
            cols = [c["name"] for c in cursor.fetchall()]
            if "admin_sender" not in cols:
                cursor.execute("DROP TABLE audit_logs;")

        # 1. Doctors table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS doctors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            specialty TEXT NOT NULL,
            regular_schedule TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('available', 'apologized', 'delayed', 'left', 'arrived', 'booking_closed')),
            daily_note TEXT DEFAULT '',
            consultation_fee REAL NOT NULL DEFAULT 40.0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_doctors_specialty ON doctors(specialty);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_doctors_name ON doctors(name);")


        # 2. Services & Lab tests table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS services (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            price REAL NOT NULL DEFAULT 0.0,
            instructions TEXT DEFAULT ''
        );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_services_category ON services(category);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_services_name ON services(name);")

        # 3. Clinic Info Key-Value table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS clinic_info (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """)

        # Backward compatibility checks for existing tables
        cursor.execute("PRAGMA table_info(doctors);")
        d_cols = [c["name"] for c in cursor.fetchall()]
        if d_cols:
            if "room_number" not in d_cols:
                cursor.execute("ALTER TABLE doctors ADD COLUMN room_number TEXT DEFAULT 'غير محدد';")
            if "schedule_days" not in d_cols:
                cursor.execute("ALTER TABLE doctors ADD COLUMN schedule_days TEXT DEFAULT 'السبت,الأحد,الإثنين,الثلاثاء,الأربعاء,الخميس';")
            if "today_status" not in d_cols:
                cursor.execute("ALTER TABLE doctors ADD COLUMN today_status TEXT DEFAULT 'available';")
            if "today_note" not in d_cols:
                cursor.execute("ALTER TABLE doctors ADD COLUMN today_note TEXT DEFAULT '';")
            if "is_active" not in d_cols:
                cursor.execute("ALTER TABLE doctors ADD COLUMN is_active INTEGER DEFAULT 1;")

        cursor.execute("PRAGMA table_info(services);")
        s_cols = [c["name"] for c in cursor.fetchall()]
        if s_cols:
            if "prep_instructions" not in s_cols:
                cursor.execute("ALTER TABLE services ADD COLUMN prep_instructions TEXT DEFAULT '';")
            if "availability" not in s_cols:
                cursor.execute("ALTER TABLE services ADD COLUMN availability TEXT DEFAULT 'متاح خلال ساعات العمل الرسمية';")
            if "updated_at" not in s_cols:
                cursor.execute("ALTER TABLE services ADD COLUMN updated_at TIMESTAMP DEFAULT '2026-01-01 00:00:00';")

        # 4. Conversation Sessions (Sliding Context) table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS conversation_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone_number TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('user', 'model', 'system')),
            message_text TEXT NOT NULL,
            created_at REAL NOT NULL,
            channel TEXT NOT NULL DEFAULT 'whatsapp'
        );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sessions_phone_created ON conversation_sessions(phone_number, created_at);")

        # 5. Audit Logs table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_sender TEXT NOT NULL,
            raw_message TEXT NOT NULL,
            status_before TEXT NOT NULL,
            status_after TEXT NOT NULL,
            confirmation_text TEXT NOT NULL,
            message_job_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        # 6. Incoming Messages Ledger (Idempotent ingestion, all channels)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS incoming_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider TEXT NOT NULL DEFAULT 'whatsapp',
            channel TEXT NOT NULL DEFAULT 'whatsapp',
            message_id TEXT NOT NULL,
            sender TEXT NOT NULL,
            payload_json TEXT,
            created_at REAL NOT NULL,
            UNIQUE(provider, message_id)
        );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_incoming_messages_provider_mid ON incoming_messages(provider, message_id);")
        # The UNIQUE(channel, message_id) index is created in the channel
        # migration block below, AFTER the channel column is added to
        # legacy tables; creating it here would fail on old databases.

        # 7. Durable Message Jobs Queue
        # Deduplication is (channel, external_message_id): the same
        # external id on two channels must not collide, so the UNIQUE
        # constraint is on (channel, message_id), not message_id alone.
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS message_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            incoming_message_id INTEGER NOT NULL REFERENCES incoming_messages(id),
            provider TEXT NOT NULL DEFAULT 'whatsapp',
            channel TEXT NOT NULL DEFAULT 'whatsapp',
            message_id TEXT NOT NULL,
            sender TEXT NOT NULL,
            message_text TEXT NOT NULL,
            is_group BOOLEAN NOT NULL DEFAULT 0,
            group_id TEXT,
            processing_status TEXT NOT NULL DEFAULT 'pending' CHECK(processing_status IN ('pending', 'processing', 'completed', 'failed')),
            outbound_status TEXT NOT NULL DEFAULT 'pending' CHECK(outbound_status IN ('pending', 'processing', 'sent', 'failed', 'skipped')),
            retry_count INTEGER NOT NULL DEFAULT 0,
            max_retries INTEGER NOT NULL DEFAULT 3,
            next_retry_at REAL NOT NULL DEFAULT 0,
            locked_at REAL,
            locked_by TEXT,
            lease_expires_at REAL,
            lease_token TEXT,
            lease_generation INTEGER NOT NULL DEFAULT 0,
            outbound_attempt_count INTEGER NOT NULL DEFAULT 0,
            response_text TEXT,
            outbound_message_id TEXT,
            last_error TEXT,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            completed_at REAL,
            UNIQUE(channel, message_id)
        );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_message_jobs_status_retry ON message_jobs(processing_status, outbound_status, next_retry_at);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_message_jobs_lease ON message_jobs(lease_expires_at);")

        # Backward compatibility column migrations for existing databases
        cursor.execute("PRAGMA table_info(audit_logs);")
        a_cols = [c["name"] for c in cursor.fetchall()]
        if a_cols and "message_job_id" not in a_cols:
            cursor.execute("ALTER TABLE audit_logs ADD COLUMN message_job_id INTEGER;")
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_audit_logs_job_id ON audit_logs(message_job_id) WHERE message_job_id IS NOT NULL;")

        cursor.execute("PRAGMA table_info(message_jobs);")
        mj_cols = [c["name"] for c in cursor.fetchall()]
        if mj_cols:
            if "lease_token" not in mj_cols:
                cursor.execute("ALTER TABLE message_jobs ADD COLUMN lease_token TEXT;")
            if "lease_generation" not in mj_cols:
                cursor.execute("ALTER TABLE message_jobs ADD COLUMN lease_generation INTEGER NOT NULL DEFAULT 0;")
            if "outbound_attempt_count" not in mj_cols:
                cursor.execute("ALTER TABLE message_jobs ADD COLUMN outbound_attempt_count INTEGER NOT NULL DEFAULT 0;")


        # 8. Emergency Clinics (7 days)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS emergency_clinics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            day_of_week TEXT NOT NULL,
            department TEXT NOT NULL,
            shift TEXT NOT NULL,
            shift_time TEXT NOT NULL,
            doctor_name TEXT NOT NULL
        );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_em_day_dept ON emergency_clinics(day_of_week, department);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_em_doc ON emergency_clinics(doctor_name);")

        # 9. Followup Clinics (7 days)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS followup_clinics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            day_of_week TEXT NOT NULL,
            specialty TEXT NOT NULL,
            doctor_name TEXT NOT NULL,
            shift_note TEXT DEFAULT ''
        );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_fu_day_spec ON followup_clinics(day_of_week, specialty);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_fu_doc ON followup_clinics(doctor_name);")

        # 10. Daily Overrides (Real-time exceptions)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_overrides (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            override_date TEXT NOT NULL,
            day_of_week TEXT NOT NULL,
            doctor_name TEXT NOT NULL,
            clinic_type TEXT NOT NULL DEFAULT 'both',
            status TEXT NOT NULL CHECK(status IN ('available', 'apologized', 'delayed', 'left', 'arrived', 'booking_closed')),
            note TEXT DEFAULT '',
            updated_by TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_overrides_date_doc ON daily_overrides(override_date, doctor_name);")

        # 11. Authorized Staff
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS authorized_staff (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone_number TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL DEFAULT 'موظف',
            role TEXT NOT NULL CHECK(role IN ('owner', 'admin', 'staff')) DEFAULT 'staff',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_staff_phone ON authorized_staff(phone_number);")

        # 12. Persistent Conversation History
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS conversation_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            clinic_id TEXT NOT NULL DEFAULT 'demo_hospital',
            sender_phone TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('user', 'model', 'system')),
            message_text TEXT NOT NULL,
            created_at REAL NOT NULL,
            channel TEXT NOT NULL DEFAULT 'whatsapp'
        );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_conv_hist_sender ON conversation_history(clinic_id, sender_phone, created_at);")

        # 13. Business Profile (multi-sector, single row id=1). The legacy
        # clinic_info key-value table stays as the store for webhook tokens
        # and staff lists; business_info is the source of truth for the
        # business identity, sector and policies.
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

        # 14. Catalog: products, services or menu items, any sector.
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
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_catalog_name ON catalog_items(name);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_catalog_category ON catalog_items(category);")

        # 15. Resources (optional per sector): doctors, technicians,
        # specialists or branches. Retail/restaurant businesses are not
        # forced to use this table.
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
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_resources_name ON resources(name);")

        # 16. Business FAQs / policies (delivery zones, returns, payment).
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS business_faqs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            keywords TEXT DEFAULT '',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        # --- Channel columns (Messenger-first pivot) -------------------
        # Deduplication is (channel, external_message_id), not a bare
        # WhatsApp wamid: the same external id on two channels must not
        # collide. The legacy `provider` column is kept and always holds
        # the same value as `channel` for backward compatibility.
        cursor.execute("PRAGMA table_info(incoming_messages);")
        im_cols = [c["name"] for c in cursor.fetchall()]
        if im_cols and "channel" not in im_cols:
            cursor.execute("ALTER TABLE incoming_messages ADD COLUMN channel TEXT NOT NULL DEFAULT 'whatsapp';")
            cursor.execute("UPDATE incoming_messages SET channel = provider;")
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_incoming_channel_mid ON incoming_messages(channel, message_id);")

        cursor.execute("PRAGMA table_info(conversation_history);")
        ch_cols = [c["name"] for c in cursor.fetchall()]
        if ch_cols and "channel" not in ch_cols:
            cursor.execute("ALTER TABLE conversation_history ADD COLUMN channel TEXT NOT NULL DEFAULT 'whatsapp';")
        cursor.execute("PRAGMA table_info(conversation_sessions);")
        cs_cols = [c["name"] for c in cursor.fetchall()]
        if cs_cols and "channel" not in cs_cols:
            cursor.execute("ALTER TABLE conversation_sessions ADD COLUMN channel TEXT NOT NULL DEFAULT 'whatsapp';")

        # message_jobs used to declare message_id UNIQUE on its own, which
        # would reject the same external id arriving on a second channel.
        # Rebuild it once (data preserved) with UNIQUE(channel, message_id).
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='message_jobs';")
        _mj_row = cursor.fetchone()
        mj_sql = _mj_row["sql"] if _mj_row else ""
        if "message_id TEXT NOT NULL UNIQUE" in mj_sql:
            cursor.execute("""
            CREATE TABLE message_jobs_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                incoming_message_id INTEGER NOT NULL REFERENCES incoming_messages(id),
                provider TEXT NOT NULL DEFAULT 'whatsapp',
                channel TEXT NOT NULL DEFAULT 'whatsapp',
                message_id TEXT NOT NULL,
                sender TEXT NOT NULL,
                message_text TEXT NOT NULL,
                is_group BOOLEAN NOT NULL DEFAULT 0,
                group_id TEXT,
                processing_status TEXT NOT NULL DEFAULT 'pending' CHECK(processing_status IN ('pending', 'processing', 'completed', 'failed')),
                outbound_status TEXT NOT NULL DEFAULT 'pending' CHECK(outbound_status IN ('pending', 'processing', 'sent', 'failed', 'skipped')),
                retry_count INTEGER NOT NULL DEFAULT 0,
                max_retries INTEGER NOT NULL DEFAULT 3,
                next_retry_at REAL NOT NULL DEFAULT 0,
                locked_at REAL,
                locked_by TEXT,
                lease_expires_at REAL,
                lease_token TEXT,
                lease_generation INTEGER NOT NULL DEFAULT 0,
                outbound_attempt_count INTEGER NOT NULL DEFAULT 0,
                response_text TEXT,
                outbound_message_id TEXT,
                last_error TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                completed_at REAL,
                UNIQUE(channel, message_id)
            );
            """)
            cursor.execute("""
            INSERT INTO message_jobs_new (
                id, incoming_message_id, provider, channel, message_id, sender,
                message_text, is_group, group_id, processing_status, outbound_status,
                retry_count, max_retries, next_retry_at, locked_at, locked_by,
                lease_expires_at, lease_token, lease_generation,
                outbound_attempt_count, response_text, outbound_message_id,
                last_error, created_at, updated_at, completed_at
            )
            SELECT id, incoming_message_id, provider, provider, message_id, sender,
                message_text, is_group, group_id, processing_status, outbound_status,
                retry_count, max_retries, next_retry_at, locked_at, locked_by,
                lease_expires_at, lease_token, lease_generation,
                outbound_attempt_count, response_text, outbound_message_id,
                last_error, created_at, updated_at, completed_at
            FROM message_jobs;
            """)
            cursor.execute("DROP TABLE message_jobs;")
            cursor.execute("ALTER TABLE message_jobs_new RENAME TO message_jobs;")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_message_jobs_status_retry ON message_jobs(processing_status, outbound_status, next_retry_at);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_message_jobs_lease ON message_jobs(lease_expires_at);")
        else:
            # Table already has the new shape (fresh DB) or was rebuilt:
            # make sure the channel column exists on any in-between schema.
            cursor.execute("PRAGMA table_info(message_jobs);")
            mj_cols2 = [c["name"] for c in cursor.fetchall()]
            if mj_cols2 and "channel" not in mj_cols2:
                cursor.execute("ALTER TABLE message_jobs ADD COLUMN channel TEXT NOT NULL DEFAULT 'whatsapp';")
                cursor.execute("UPDATE message_jobs SET channel = provider;")


def seed_default_data(db_path: str = DB_PATH, preset: Optional[str] = None) -> None:
    """Populates default clinic identity, doctors, and services if tables are empty."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        if preset == "demo":
            from seed_demo import seed_demo
            seed_demo(db_path)
            return

        cursor.execute("SELECT COUNT(*) AS cnt FROM emergency_clinics;")
        has_em = cursor.fetchone()["cnt"] > 0

        # Seed Clinic Info dynamically from settings / defaults
        from app.config import settings
        default_info = {
            "name": settings.CLINIC_NAME,
            "clinic_name": settings.CLINIC_NAME,
            "facility_type": getattr(settings, "CLINIC_TYPE", "مصحة"),
            "address": settings.CLINIC_ADDRESS,
            "emergency_phone": settings.EMERGENCY_PHONE,
            "reception_phone": settings.RECEPTION_PHONE,
            "contact_numbers": f"{settings.RECEPTION_PHONE} - {settings.EMERGENCY_PHONE}" if settings.EMERGENCY_PHONE != settings.RECEPTION_PHONE else settings.RECEPTION_PHONE,
            "booking_policy": settings.BOOKING_POLICY,
            "map_link": settings.CLINIC_MAP_LINK,
            "admin_group_id": "clinic_staff_group@g.us",
            "authorized_staff_phones": settings.AUTHORIZED_STAFF_PHONES,
            "authorized_phones": settings.AUTHORIZED_STAFF_PHONES,
            "facilities_info": "الخدمات متوفرة وفق الجداول والمواعيد المعتمدة.",
        }
        for k, v in default_info.items():
            cursor.execute("INSERT OR IGNORE INTO clinic_info (key, value) VALUES (?, ?);", (k, v))

        # Seed the generic business profile (single row, id=1) from the
        # same settings. The CLINIC_* env aliases still feed this through
        # settings.BUSINESS_NAME / BUSINESS_SECTOR fallbacks.
        cursor.execute("SELECT COUNT(*) AS cnt FROM business_info;")
        if cursor.fetchone()["cnt"] == 0:
            sector = (getattr(settings, "BUSINESS_SECTOR", "clinic") or "clinic").strip().lower()
            if sector not in ("retail", "restaurant", "clinic", "pharmacy",
                              "service_office", "workshop", "general", "medical"):
                sector = "clinic"
            cursor.execute("""
            INSERT INTO business_info (
                id, name, sector, address, map_link, support_phone,
                escalation_phone, working_hours, policy_notes, currency
            ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (
                getattr(settings, "BUSINESS_NAME", settings.CLINIC_NAME),
                sector,
                settings.CLINIC_ADDRESS,
                settings.CLINIC_MAP_LINK,
                getattr(settings, "SUPPORT_PHONE", settings.RECEPTION_PHONE),
                getattr(settings, "ESCALATION_PHONE", settings.EMERGENCY_PHONE),
                "الفترة الصباحية: 08:00 ص إلى 02:00 ظ\nالفترة المسائية: 02:00 ظ إلى 08:00 م",
                settings.BOOKING_POLICY,
                getattr(settings, "BUSINESS_CURRENCY", "LYD"),
            ))

        # Seed Doctors if empty
        cursor.execute("SELECT COUNT(*) AS cnt FROM doctors;")
        if cursor.fetchone()["cnt"] == 0:
            doctors_data = [
                ("د. يوسف العربي", "عظام ومفاصل", "السبت إلى الخميس: 09:00 ص - 01:00 م", "available", "", 40.0),
                ("د. سامي النور", "مسالك بولية وعقم ذكورة", "السبت، الإثنين، الأربعاء: 04:00 م - 08:00 م", "available", "", 45.0),
                ("د. أحمد الزليطني", "باطنة عامة وسكري", "يومياً عدا الجمعة: 10:00 ص - 02:00 م", "available", "", 40.0),
                ("د. فاطمة الورفلي", "عيون وجراحة البصر", "الأحد، الثلاثاء، الخميس: 04:00 م - 07:30 م", "available", "", 50.0),
                ("د. يوسف السالم", "أطفال وحديثي ولادة", "يومياً: 10:00 ص - 01:00 م ومن 05:00 م - 08:00 م", "available", "", 35.0),
            ]
            cursor.executemany("""
            INSERT INTO doctors (name, specialty, regular_schedule, status, daily_note, consultation_fee)
            VALUES (?, ?, ?, ?, ?, ?);
            """, doctors_data)

        # Seed Services if empty
        cursor.execute("SELECT COUNT(*) AS cnt FROM services;")
        if cursor.fetchone()["cnt"] == 0:
            services_data = [
                ("تحليل سكر صائم (FBS)", "مختبر", 10.0, "يشترط الصيام من 8 إلى 10 ساعات قبل سحب العينة"),
                ("تحليل السكر التراكمي (HbA1c)", "مختبر", 30.0, "لا يشترط الصيام، متاح على مدار اليوم"),
                ("صورة دم كاملة (CBC)", "مختبر", 25.0, "لا يشترط الصيام"),
                ("تحليل وظائف كلى (Urea / Creatinine)", "مختبر", 25.0, "يُفضل الصيام من 6 إلى 8 ساعات"),
                ("تحليل وظائف كبد (LFT)", "مختبر", 45.0, "يشترط الصيام من 8 إلى 10 ساعات"),
                ("تصوير موجات فوق صوتية / سونار بطن وحوض", "أشعة", 60.0, "شرب كمية وفيرة من الماء والامتناع عن التبول قبل الفحص بساعة"),
                ("أشعة سينية عادية (X-Ray)", "أشعة", 40.0, "لا توجد شروط مسبقة، متاح 24 ساعة بقسم الطوارئ"),
                ("تخطيط قلب كهربائي (ECG)", "طوارئ", 20.0, "متاح 24 ساعة في قسم الإسعاف والطوارئ")
            ]
            cursor.executemany("""
            INSERT INTO services (name, category, price, instructions)
            VALUES (?, ?, ?, ?);
            """, services_data)


# ==========================================
# Data Access Methods
# ==========================================

def get_clinic_info(db_path: str = DB_PATH) -> Dict[str, str]:
    """Fetches all key-value entries from clinic_info."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT key, value FROM clinic_info;")
        return {row["key"]: row["value"] for row in cursor.fetchall()}


def update_clinic_info_key(key: str, value: str, db_path: str = DB_PATH) -> None:
    """Inserts or updates a clinic_info key, automatically keeping aliases in sync."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO clinic_info (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value;
        """, (key, value))

        alias_map = {
            "name": "clinic_name",
            "clinic_name": "name",
            "authorized_staff_phones": "authorized_phones",
            "authorized_phones": "authorized_staff_phones"
        }
        if key in alias_map:
            cursor.execute("""
            INSERT INTO clinic_info (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value;
            """, (alias_map[key], value))


# Sectors for which the medical safety module (Level 1 emergency bypass
# and Level 2 clinical-advice restrictions) is active. Every other sector
# gets the commercial guardrails only.
MEDICAL_SECTORS = ("clinic", "pharmacy", "medical")


def get_business_profile(db_path: str = DB_PATH) -> Dict[str, Any]:
    """
    Returns the unified business profile for this deployment.

    Primary source is the business_info table (single row, id=1). A
    legacy database that has no business_info row yet falls back to the
    clinic_info key-value table and environment variables, so existing
    deployments keep working without a manual migration step.

    The returned dict carries both the new generic keys (sector,
    support_phone, escalation_phone, working_hours, policy_notes,
    currency) and the legacy clinic keys (clinic_name, facility_type,
    emergency_phone, reception_phone, booking_policy, is_medical,
    shifts_info) so every existing caller keeps working.
    """
    info = get_clinic_info(db_path)
    row = None
    try:
        with get_db(db_path) as conn:
            r = conn.execute("SELECT * FROM business_info WHERE id = 1;").fetchone()
            row = dict(r) if r else None
    except Exception:
        row = None

    if row:
        name = row.get("name") or info.get("clinic_name") or info.get("name") or "المصحة الطبية"
        sector = (row.get("sector") or "general").strip().lower()
        address = row.get("address") or info.get("address") or "ليبيا"
        map_link = row.get("map_link") or info.get("map_link") or ""
        support_phone = row.get("support_phone") or info.get("reception_phone") or "0910000000"
        escalation_phone = row.get("escalation_phone") or info.get("emergency_phone") or support_phone
        working_hours = row.get("working_hours") or ""
        policy_notes = row.get("policy_notes") or ""
        currency = row.get("currency") or "LYD"
    else:
        name = (
            info.get("clinic_name")
            or info.get("name")
            or os.environ.get("BUSINESS_NAME")
            or os.environ.get("CLINIC_NAME")
            or "المصحة الطبية"
        )
        sector = (info.get("sector") or os.environ.get("BUSINESS_SECTOR") or "clinic").strip().lower()
        address = (
            info.get("address")
            or info.get("clinic_address")
            or os.environ.get("CLINIC_ADDRESS")
            or "ليبيا"
        )
        map_link = info.get("map_link") or os.environ.get("CLINIC_MAP_LINK") or ""
        support_phone = (
            info.get("reception_phone")
            or info.get("contact_numbers")
            or os.environ.get("RECEPTION_PHONE")
            or "0910000000"
        )
        escalation_phone = (
            info.get("emergency_phone")
            or os.environ.get("EMERGENCY_PHONE")
            or support_phone
        )
        working_hours = info.get("working_hours") or ""
        policy_notes = info.get("policy_notes") or ""
        currency = info.get("currency") or os.environ.get("BUSINESS_CURRENCY") or "LYD"

    if sector not in ("retail", "restaurant", "clinic", "pharmacy",
                      "service_office", "workshop", "general", "medical"):
        sector = "general"

    facility_type = (
        info.get("facility_type")
        or info.get("clinic_type")
        or os.environ.get("CLINIC_TYPE")
        or ("مستشفى إيوائي" if "مستشفى" in name else "مصحة" if "مصحة" in name else "مجمع عيادات" if "عيادات" in name else "مركز خدمات")
    )
    city = info.get("city") or os.environ.get("CLINIC_CITY") or ""
    if not city:
        for c in ["زليتن", "طرابلس", "بنغازي", "مصراتة", "الزاوية", "البيضاء", "طبرق", "سبها", "سرت", "الخمس", "درنة"]:
            if c in address:
                city = c
                break

    contact_numbers = info.get("contact_numbers") or (
        f"{support_phone} - {escalation_phone}" if escalation_phone != support_phone else support_phone
    )
    booking_policy = (
        info.get("booking_policy")
        or policy_notes
        or os.environ.get("BOOKING_POLICY")
        or "الاستفسار والخدمات متاحة وفق الفترات المعلنة، والحضور أو الحجز عبر مكتب الاستقبال."
    )
    facilities_info = info.get("facilities_info") or "الخدمات متوفرة وفق الجداول والمواعيد المعتمدة."

    # Medical status is decided by sector now, not by name keywords. A
    # legacy explicit is_medical flag in clinic_info still wins when the
    # sector is unknown to an older seed.
    if "is_medical" in info and sector == "general":
        is_medical = str(info.get("is_medical")).strip() not in ("0", "false", "False", "")
    else:
        is_medical = sector in MEDICAL_SECTORS

    shifts_info = info.get("shifts_info") or working_hours or (
        "• الفترة الصباحية: 08:00 ص إلى 02:00 ظ\n"
        "• الفترة المسائية: 02:00 ظ إلى 08:00 م\n"
        "• الفترة الليلية / الطوارئ: متاحة حسب جدول المناوبات"
    )

    return {
        "name": name,
        "clinic_name": name,
        "business_name": name,
        "sector": sector,
        "facility_type": facility_type,
        "address": address,
        "city": city,
        "map_link": map_link,
        "support_phone": support_phone,
        "escalation_phone": escalation_phone,
        "emergency_phone": escalation_phone,
        "reception_phone": support_phone,
        "contact_numbers": contact_numbers,
        "booking_policy": booking_policy,
        "policy_notes": policy_notes,
        "working_hours": working_hours,
        "currency": currency,
        "facilities_info": facilities_info,
        "is_medical": is_medical,
        "shifts_info": shifts_info,
    }


def get_facility_profile(db_path: str = DB_PATH) -> Dict[str, Any]:
    """Legacy alias: the facility profile IS the business profile now."""
    return get_business_profile(db_path)


def update_business_profile(profile_data: Dict[str, Any], db_path: str = DB_PATH) -> None:
    """Upserts the single business_info row (id=1) and keeps the shared
    clinic_info keys (name, address, phones) in sync, so legacy readers
    that still read clinic_info see the same values."""
    allowed = {
        "name", "sector", "address", "map_link", "support_phone",
        "escalation_phone", "working_hours", "policy_notes", "currency",
    }
    updates = {k: str(v) for k, v in profile_data.items() if k in allowed and v is not None}
    if "sector" in updates:
        sector = updates["sector"].strip().lower()
        if sector not in ("retail", "restaurant", "clinic", "pharmacy",
                          "service_office", "workshop", "general", "medical"):
            raise ValueError(f"Unknown business sector: {sector}")
        updates["sector"] = sector
    if not updates:
        return
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM business_info WHERE id = 1;")
        if cursor.fetchone() is None:
            cursor.execute("INSERT INTO business_info (id, name) VALUES (1, 'النشاط التجاري');")
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        cursor.execute(
            f"UPDATE business_info SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = 1;",
            list(updates.values()),
        )
    # Sync shared keys into clinic_info for legacy readers.
    sync_map = {
        "name": ("name", "clinic_name"),
        "address": ("address",),
        "support_phone": ("reception_phone",),
        "escalation_phone": ("emergency_phone",),
    }
    for key, clinic_keys in sync_map.items():
        if key in updates:
            for ck in clinic_keys:
                update_clinic_info_key(ck, updates[key], db_path)


def update_facility_profile(profile_data: Dict[str, Any], db_path: str = DB_PATH) -> None:
    """Updates active facility profile in clinic_info."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        for k, v in profile_data.items():
            if v is not None:
                cursor.execute("""
                    INSERT INTO clinic_info (key, value) VALUES (?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value;
                """, (k, str(v)))
                if k == "name":
                    cursor.execute("INSERT OR REPLACE INTO clinic_info (key, value) VALUES ('clinic_name', ?);", (str(v),))
                elif k == "clinic_name":
                    cursor.execute("INSERT OR REPLACE INTO clinic_info (key, value) VALUES ('name', ?);", (str(v),))



def get_all_doctors(db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Returns list of all active doctors."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM doctors ORDER BY id ASC;")
        return [dict(row) for row in cursor.fetchall()]


def get_all_services(category: Optional[str] = None, db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Returns list of services, optionally filtered by category."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        if category:
            cursor.execute("SELECT * FROM services WHERE category LIKE ? ORDER BY id ASC;", (f"%{category}%",))
        else:
            cursor.execute("SELECT * FROM services ORDER BY id ASC;")
        return [dict(row) for row in cursor.fetchall()]


# ==========================================
# Multi-sector catalog / resources / FAQs
# ==========================================

def get_catalog_items(
    available_only: bool = False,
    category: Optional[str] = None,
    db_path: str = DB_PATH
) -> List[Dict[str, Any]]:
    """Returns catalog items (products/services/menu items), any sector."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        query = "SELECT * FROM catalog_items WHERE 1 = 1"
        params: List[Any] = []
        if available_only:
            query += " AND is_available = 1"
        if category:
            query += " AND category LIKE ?"
            params.append(f"%{category}%")
        query += " ORDER BY id ASC;"
        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]


def find_catalog_item_fuzzy(item_query: str, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    """Fuzzy-matches a catalog item by name or category (Libyan dialect
    tolerant: normalized Arabic, token scoring, like the doctor finder)."""
    items = get_catalog_items(db_path=db_path)
    q = (item_query or "").strip().lower()
    if not q:
        return None
    q_norm = norm(q)
    q_tokens = [tok for tok in q_norm.split() if len(tok) > 2]
    best_item = None
    best_score = 0
    for item in items:
        name_norm = norm(item["name"])
        cat_norm = norm(item.get("category") or "")
        score = 0
        if q_norm and (q_norm in name_norm or name_norm in q_norm):
            score += 10
        if q_norm and (q_norm in cat_norm or cat_norm in q_norm):
            score += 6
        name_tokens = [t for t in name_norm.split() if len(t) > 2]
        cat_tokens = [t for t in cat_norm.split() if len(t) > 2]
        for tok in q_tokens:
            if tok in name_norm:
                score += 5
            elif any(nt in tok for nt in name_tokens):
                # Reverse match: the item word is inside the query word
                # ("شاشه" in "الشاشه" — the definite article, or a
                # trailing question mark). Same direction the schedule
                # path uses for departments.
                score += 5
            if tok in cat_norm:
                score += 3
            elif any(ct in tok for ct in cat_tokens):
                score += 3
        if score > best_score:
            best_score = score
            best_item = item
    if best_score >= 4:
        return best_item
    return None


def get_catalog_view(db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Unified catalog view: catalog_items plus the legacy services table
    (lab tests / clinic services) mapped to the same shape, so a clinic
    answers price questions from one view without duplicating data."""
    view: List[Dict[str, Any]] = []
    for item in get_catalog_items(db_path=db_path):
        view.append({
            "id": item["id"],
            "name": item["name"],
            "category": item.get("category") or "",
            "price_lyd": item.get("price_lyd", 0.0),
            "is_available": bool(item.get("is_available", 1)),
            "schedule_or_eta": item.get("schedule_or_eta") or "",
            "details": item.get("details") or "",
            "source": "catalog",
        })
    for svc in get_all_services(db_path=db_path):
        view.append({
            "id": svc["id"],
            "name": svc["name"],
            "category": svc.get("category") or "",
            "price_lyd": svc.get("price", 0.0),
            "is_available": True,
            "schedule_or_eta": svc.get("availability") or "",
            "details": svc.get("instructions") or svc.get("prep_instructions") or "",
            "source": "service",
        })
    return view


def find_in_catalog_view(item_query: str, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    """Fuzzy match over the unified catalog view (catalog + services)."""
    catalog_hit = find_catalog_item_fuzzy(item_query, db_path=db_path)
    if catalog_hit:
        return {
            "id": catalog_hit["id"],
            "name": catalog_hit["name"],
            "category": catalog_hit.get("category") or "",
            "price_lyd": catalog_hit.get("price_lyd", 0.0),
            "is_available": bool(catalog_hit.get("is_available", 1)),
            "schedule_or_eta": catalog_hit.get("schedule_or_eta") or "",
            "details": catalog_hit.get("details") or "",
            "source": "catalog",
        }
    svc = find_service_fuzzy(item_query, db_path=db_path)
    if svc:
        return {
            "id": svc["id"],
            "name": svc["name"],
            "category": svc.get("category") or "",
            "price_lyd": svc.get("price", 0.0),
            "is_available": True,
            "schedule_or_eta": svc.get("availability") or "",
            "details": svc.get("instructions") or svc.get("prep_instructions") or "",
            "source": "service",
        }
    return None


def get_resources(db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Returns staff/resource rows (doctors, technicians, specialists)."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM resources ORDER BY id ASC;")
        return [dict(row) for row in cursor.fetchall()]


def find_resource_fuzzy(resource_query: str, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    """Fuzzy-matches a resource by name or role/specialty."""
    resources = get_resources(db_path=db_path)
    q = (resource_query or "").strip().lower()
    if not q:
        return None
    q_norm = norm(q)
    q_tokens = [tok for tok in q_norm.split() if len(tok) > 2]
    best = None
    best_score = 0
    for res in resources:
        name_norm = norm(res["name"])
        role_norm = norm(res.get("role_or_specialty") or "")
        score = 0
        if q_norm and (q_norm in name_norm or name_norm in q_norm):
            score += 10
        if q_norm and (q_norm in role_norm or role_norm in q_norm):
            score += 8
        name_tokens = [t for t in name_norm.split() if len(t) > 2]
        role_tokens = [t for t in role_norm.split() if len(t) > 2]
        for tok in q_tokens:
            if tok in name_norm:
                score += 5
            elif any(nt in tok for nt in name_tokens):
                # Reverse match: the resource word is inside the query
                # word (definite article / trailing punctuation).
                score += 5
            if tok in role_norm:
                score += 4
            elif any(rt in tok for rt in role_tokens):
                score += 4
        if score > best_score:
            best_score = score
            best = res
    if best_score >= 4:
        return best
    return None


def get_business_faqs(db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Returns business FAQ rows (delivery, returns, payment, warranty)."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM business_faqs ORDER BY id ASC;")
        return [dict(row) for row in cursor.fetchall()]


# Generic words that must never trigger an FAQ match on their own. Without
# this filter, a doctor-availability question ("هل دكتور العظام متاح؟")
# matched the emergency-hours FAQ on the single shared token "متاح" and
# the patient never got the schedule answer (caught by
# test_system_integrity.py::test_admin_service during the pivot). Tokens
# are in normalized form (norm() maps أ/إ/آ to ا, ة to ه, ى to ي).
FAQ_STOPWORDS = frozenset({
    "هل", "شن", "كيف", "وين", "متي", "اين", "عندكم", "عندك", "عندي",
    "فيه", "في", "من", "ما", "كم", "بكم", "نبي", "ابي", "اريد", "ارغب",
    "ممكن", "لو", "سمحت", "اليوم", "توا", "الان", "هذا", "هذه", "هو",
    "هي", "كان", "يكون", "شي", "اي", "متاح", "متاحه", "متوفر", "متوفره",
    "موجود", "موجوده", "قاعد", "قاعده", "يوجد", "نقدر", "استطيع",
    "مازال", "لسه", "حاب", "حابه", "نحب", "نبغي",
})


def match_faq(query: str, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    """Keyword-overlap FAQ match. Returns the best-scoring FAQ, or None
    when no FAQ shares a meaningful (non-stopword) keyword with the
    query. Generic availability/question words never count: they belong
    to the catalog/schedule paths, not to FAQs."""
    faqs = get_business_faqs(db_path=db_path)
    q_norm = norm(query or "")
    q_tokens = {tok for tok in q_norm.split() if len(tok) > 2} - FAQ_STOPWORDS
    if not q_tokens:
        return None
    best = None
    best_score = 0
    for faq in faqs:
        haystack = norm(f"{faq.get('question', '')} {faq.get('keywords', '')}")
        hay_tokens = {tok for tok in haystack.split() if len(tok) > 2} - FAQ_STOPWORDS
        score = len(q_tokens & hay_tokens)
        if score > best_score:
            best_score = score
            best = faq
    if best_score >= 1:
        return best
    return None


def norm(text: str) -> str:
    """Normalizes Arabic text for flexible name/keyword matching."""
    if not text:
        return ""
    t = text.lower()
    t = t.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    t = t.replace("ة", "ه").replace("ى", "ي")
    t = t.replace("د.", "").replace("دكتور", "").replace("دكتورة", "")
    return t.strip()


def find_doctor_fuzzy(name_query: Optional[str] = None, specialty_query: Optional[str] = None, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    """
    Intelligent fuzzy matcher for Libyan dialect variations:
    Matches names or specialties (e.g. 'عظام', 'دكتور علي', 'يوسف العربي', 'اطفال').
    """
    all_docs = get_all_doctors(db_path)
    combined_query = f"{name_query or ''} {specialty_query or ''}".strip().lower()
    if not combined_query:
        return None

    q_norm = norm(combined_query)
    q_tokens = [tok for tok in q_norm.split() if len(tok) > 2]

    best_doc = None
    best_score = 0

    for doc in all_docs:
        d_name_norm = norm(doc["name"])
        d_spec_norm = norm(doc["specialty"])
        score = 0

        # Exact substring matches
        if q_norm and (q_norm in d_name_norm or d_name_norm in q_norm):
            score += 10
        if q_norm and (q_norm in d_spec_norm or d_spec_norm in q_norm):
            score += 8

        # Token matches
        for tok in q_tokens:
            if tok in d_name_norm:
                score += 5
            if tok in d_spec_norm:
                score += 4

        if score > best_score:
            best_score = score
            best_doc = doc

    if best_score >= 4:
        return best_doc
    return None


def find_service_fuzzy(service_query: str, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    """Fuzzy searches laboratory or imaging services."""
    services = get_all_services(db_path=db_path)
    q = service_query.lower().strip()
    for s in services:
        s_name = s["name"].lower()
        if q in s_name or any(word in s_name for word in q.split() if len(word) > 3):
            return s
    return None


def update_doctor_atomic(
    doctor_id: int,
    status: Optional[str] = None,
    daily_note: Optional[str] = None,
    consultation_fee: Optional[float] = None,
    db_path: str = DB_PATH
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Atomically updates doctor fields and returns (status_before, status_after).
    """
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM doctors WHERE id = ?;", (doctor_id,))
        row_before = cursor.fetchone()
        if not row_before:
            raise ValueError(f"Doctor with ID {doctor_id} not found.")

        status_before = dict(row_before)

        # Prepare updates
        new_status = status if status is not None else status_before["status"]
        new_note = daily_note if daily_note is not None else status_before["daily_note"]
        new_fee = consultation_fee if consultation_fee is not None else status_before["consultation_fee"]

        cursor.execute("""
        UPDATE doctors
        SET status = ?, today_status = ?, daily_note = ?, today_note = ?, consultation_fee = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?;
        """, (new_status, new_status, new_note, new_note, new_fee, doctor_id))

        cursor.execute("SELECT * FROM doctors WHERE id = ?;", (doctor_id,))
        status_after = dict(cursor.fetchone())

        return status_before, status_after


def update_service_atomic(
    service_id: int,
    price: float,
    db_path: str = DB_PATH
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Atomically updates service price and returns (before, after)."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM services WHERE id = ?;", (service_id,))
        row_before = cursor.fetchone()
        if not row_before:
            raise ValueError(f"Service with ID {service_id} not found.")
        status_before = dict(row_before)

        cursor.execute("UPDATE services SET price = ? WHERE id = ?;", (price, service_id))
        cursor.execute("SELECT * FROM services WHERE id = ?;", (service_id,))
        status_after = dict(cursor.fetchone())

        return status_before, status_after


class StaleWorkerFencedError(RuntimeError):
    """Raised when a worker attempts to commit changes but its lease was superseded or expired."""
    pass


def log_audit_trail(
    admin_sender: str,
    raw_message: str,
    status_before: Dict[str, Any],
    status_after: Dict[str, Any],
    confirmation_text: str,
    message_job_id: Optional[int] = None,
    db_path: str = DB_PATH
) -> int:
    """Inserts a permanent verification audit record for staff updates."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO audit_logs (admin_sender, raw_message, status_before, status_after, confirmation_text, message_job_id)
        VALUES (?, ?, ?, ?, ?, ?);
        """, (
            admin_sender,
            raw_message,
            json.dumps(status_before, ensure_ascii=False),
            json.dumps(status_after, ensure_ascii=False),
            confirmation_text,
            message_job_id
        ))
        return cursor.lastrowid


def apply_admin_mutation_atomic(
    mutation_type: str,
    target_id: int,
    mutation_fields: Dict[str, Any],
    audit_sender: str,
    raw_message: str,
    confirmation_text: str,
    job_id: Optional[int] = None,
    lease_token: Optional[str] = None,
    worker_id: Optional[str] = None,
    db_path: str = DB_PATH,
    daily_override: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, Dict[str, Any], Dict[str, Any], str]:
    """
    Executes business mutation, audit-log insertion, and marking the job
    as processing-completed in a SINGLE atomic SQLite transaction.

    If daily_override is given (doctor status changes), its daily_overrides
    row is written in the SAME transaction. It must not be written by a
    separate call beforehand: that call committed its own transaction
    (including a doctors-table update), so a later crash could not roll
    the status change back.

    Returns:
        (already_applied: bool, status_before: dict, status_after: dict, receipt: str)
    """
    now = time.time()
    with get_db(db_path) as conn:
        cursor = conn.cursor()

        # 1. Idempotency Check: Was this exact job already committed?
        if job_id is not None:
            cursor.execute(
                "SELECT confirmation_text, status_before, status_after FROM audit_logs WHERE message_job_id = ?;",
                (job_id,)
            )
            existing_audit = cursor.fetchone()
            if existing_audit:
                sb = json.loads(existing_audit["status_before"]) if existing_audit["status_before"] else {}
                sa = json.loads(existing_audit["status_after"]) if existing_audit["status_after"] else {}
                return True, sb, sa, existing_audit["confirmation_text"]

        # 2. Stale Worker Fencing Check: If job_id and lease_token are provided, verify ownership
        if job_id is not None and lease_token is not None:
            cursor.execute(
                "SELECT id, locked_by, lease_token, lease_expires_at FROM message_jobs WHERE id = ?;",
                (job_id,)
            )
            job_row = cursor.fetchone()
            if not job_row:
                raise ValueError(f"Job {job_id} not found in message_jobs.")
            if job_row["lease_token"] != lease_token or (worker_id and job_row["locked_by"] != worker_id):
                raise StaleWorkerFencedError(
                    f"Worker '{worker_id}' with lease_token '{lease_token}' is stale. "
                    f"Job {job_id} is currently held by '{job_row['locked_by']}' (token: {job_row['lease_token']})"
                )

        # 3. Apply Business Mutation
        if mutation_type == "doctor":
            cursor.execute("SELECT * FROM doctors WHERE id = ?;", (target_id,))
            row_before = cursor.fetchone()
            if not row_before:
                raise ValueError(f"Doctor with ID {target_id} not found.")
            status_before = dict(row_before)

            new_status = mutation_fields.get("status", status_before["status"])
            new_note = mutation_fields.get("daily_note", status_before["daily_note"])
            new_fee = mutation_fields.get("consultation_fee", status_before["consultation_fee"])

            cursor.execute("""
                UPDATE doctors
                SET status = ?, today_status = ?, daily_note = ?, today_note = ?,
                    consultation_fee = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?;
            """, (new_status, new_status, new_note, new_note, new_fee, target_id))

            cursor.execute("SELECT * FROM doctors WHERE id = ?;", (target_id,))
            status_after = dict(cursor.fetchone())

        elif mutation_type == "service":
            cursor.execute("SELECT * FROM services WHERE id = ?;", (target_id,))
            row_before = cursor.fetchone()
            if not row_before:
                raise ValueError(f"Service with ID {target_id} not found.")
            status_before = dict(row_before)

            new_price = mutation_fields.get("price", status_before["price"])
            cursor.execute("UPDATE services SET price = ? WHERE id = ?;", (new_price, target_id))
            cursor.execute("SELECT * FROM services WHERE id = ?;", (target_id,))
            status_after = dict(cursor.fetchone())

        elif mutation_type == "catalog_item":
            cursor.execute("SELECT * FROM catalog_items WHERE id = ?;", (target_id,))
            row_before = cursor.fetchone()
            if not row_before:
                raise ValueError(f"Catalog item with ID {target_id} not found.")
            status_before = dict(row_before)

            new_price = mutation_fields.get(
                "price_lyd", mutation_fields.get("price", status_before["price_lyd"])
            )
            new_available = mutation_fields.get("is_available", status_before["is_available"])
            new_eta = mutation_fields.get("schedule_or_eta", status_before["schedule_or_eta"])
            new_details = mutation_fields.get("details", status_before["details"])
            cursor.execute("""
                UPDATE catalog_items
                SET price_lyd = ?, is_available = ?, schedule_or_eta = ?,
                    details = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?;
            """, (new_price, 1 if new_available else 0, new_eta, new_details, target_id))
            cursor.execute("SELECT * FROM catalog_items WHERE id = ?;", (target_id,))
            status_after = dict(cursor.fetchone())

        elif mutation_type == "resource":
            cursor.execute("SELECT * FROM resources WHERE id = ?;", (target_id,))
            row_before = cursor.fetchone()
            if not row_before:
                raise ValueError(f"Resource with ID {target_id} not found.")
            status_before = dict(row_before)

            new_schedule = mutation_fields.get("schedule", status_before["schedule"])
            new_available = mutation_fields.get("is_available", status_before["is_available"])
            new_notes = mutation_fields.get("notes", status_before["notes"])
            cursor.execute("""
                UPDATE resources
                SET schedule = ?, is_available = ?, notes = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?;
            """, (new_schedule, 1 if new_available else 0, new_notes, target_id))
            cursor.execute("SELECT * FROM resources WHERE id = ?;", (target_id,))
            status_after = dict(cursor.fetchone())

        elif mutation_type == "business_info":
            cursor.execute("SELECT * FROM business_info WHERE id = 1;")
            row_before = cursor.fetchone()
            if not row_before:
                cursor.execute("INSERT INTO business_info (id, name) VALUES (1, 'النشاط التجاري');")
                cursor.execute("SELECT * FROM business_info WHERE id = 1;")
                row_before = cursor.fetchone()
            status_before = dict(row_before)

            allowed = ("name", "sector", "address", "map_link", "support_phone",
                       "escalation_phone", "working_hours", "policy_notes", "currency")
            updates = {k: v for k, v in mutation_fields.items() if k in allowed}
            if "sector" in updates:
                sector = str(updates["sector"]).strip().lower()
                if sector not in ("retail", "restaurant", "clinic", "pharmacy",
                                  "service_office", "workshop", "general", "medical"):
                    raise ValueError(f"Unknown business sector: {sector}")
                updates["sector"] = sector
            if updates:
                set_clause = ", ".join(f"{k} = ?" for k in updates)
                cursor.execute(
                    f"UPDATE business_info SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = 1;",
                    [str(v) for v in updates.values()],
                )
            cursor.execute("SELECT * FROM business_info WHERE id = 1;")
            status_after = dict(cursor.fetchone())
        else:
            raise ValueError(f"Unknown mutation_type: {mutation_type}")

        # 3b. Daily override in the SAME transaction (doctor status only).
        # The override row must commit or roll back together with the
        # doctors update above; writing it in a separate transaction first
        # is what previously broke rollback.
        if daily_override is not None:
            cursor.execute("""
                DELETE FROM daily_overrides
                WHERE override_date = ? AND doctor_name = ?;
            """, (daily_override["override_date"], daily_override["doctor_name"]))
            cursor.execute("""
                INSERT INTO daily_overrides (
                    override_date, day_of_week, doctor_name, clinic_type, status, note, updated_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?);
            """, (
                daily_override["override_date"],
                daily_override.get("day_of_week", ""),
                daily_override["doctor_name"],
                daily_override.get("clinic_type", "both"),
                daily_override["status"],
                daily_override.get("note", ""),
                daily_override.get("updated_by", ""),
            ))

        # 4. Insert Audit Log (with unique message_job_id)
        cursor.execute("""
            INSERT INTO audit_logs (
                admin_sender, raw_message, status_before, status_after, confirmation_text, message_job_id
            ) VALUES (?, ?, ?, ?, ?, ?);
        """, (
            audit_sender,
            raw_message,
            json.dumps(status_before, ensure_ascii=False),
            json.dumps(status_after, ensure_ascii=False),
            confirmation_text,
            job_id
        ))

        # 5. Atomically Mark message_jobs as processing_status = 'completed' in the same transaction
        if job_id is not None:
            if lease_token:
                cursor.execute("""
                    UPDATE message_jobs
                    SET processing_status = 'completed',
                        response_text = :resp,
                        updated_at = :now
                    WHERE id = :job_id
                      AND lease_token = :token;
                """, {"resp": confirmation_text, "now": now, "job_id": job_id, "token": lease_token})
            else:
                cursor.execute("""
                    UPDATE message_jobs
                    SET processing_status = 'completed',
                        response_text = :resp,
                        updated_at = :now
                    WHERE id = :job_id;
                """, {"resp": confirmation_text, "now": now, "job_id": job_id})

            if cursor.rowcount == 0 and lease_token:
                raise StaleWorkerFencedError(f"Fenced! Failed to update message_jobs {job_id} with token {lease_token}")

    return False, status_before, status_after, confirmation_text


# ==========================================
# Sliding Context / Session History
# ==========================================

def save_conversation_turn(
    phone_number: str,
    role: str,
    message_text: str,
    db_path: str = DB_PATH,
    channel: str = "whatsapp"
) -> None:
    """Saves a single conversation turn with high-precision epoch timestamp."""
    valid_role = role if role in ("user", "model", "system") else "user"
    with get_db(db_path) as conn:
        conn.cursor().execute("""
        INSERT INTO conversation_sessions (phone_number, role, message_text, created_at, channel)
        VALUES (?, ?, ?, ?, ?);
        """, (phone_number, valid_role, message_text, time.time(), channel or "whatsapp"))


def get_sliding_session_history(
    phone_number: str,
    max_turns: int = 4,
    ttl_minutes: int = 15,
    db_path: str = DB_PATH,
    channel: Optional[str] = None
) -> List[Dict[str, str]]:
    """
    Retrieves the last `max_turns` interactions (user & model) for a customer within `ttl_minutes`.
    When channel is given, history is scoped to that channel too, so a
    Messenger conversation never leaks into a WhatsApp one for the same
    sender id. channel=None keeps the legacy unfiltered behavior.
    Returns list of dicts: [{"role": "user"|"model", "text": "..."}] sorted chronologically.
    """
    cutoff_time = time.time() - (ttl_minutes * 60)
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        if channel:
            cursor.execute("""
            SELECT role, message_text, created_at
            FROM conversation_sessions
            WHERE phone_number = ? AND channel = ? AND created_at >= ?
            ORDER BY id DESC
            LIMIT ?;
            """, (phone_number, channel, cutoff_time, max_turns * 2))
        else:
            cursor.execute("""
            SELECT role, message_text, created_at
            FROM conversation_sessions
            WHERE phone_number = ? AND created_at >= ?
            ORDER BY id DESC
            LIMIT ?;
            """, (phone_number, cutoff_time, max_turns * 2))

        rows = cursor.fetchall()
        # Reverse to chronological order
        chronological = list(reversed(rows))
        return [{"role": r["role"], "text": r["message_text"]} for r in chronological]


def cleanup_expired_sessions(ttl_minutes: int = 60, db_path: str = DB_PATH) -> int:
    """Removes sessions older than TTL to keep database compact."""
    cutoff = time.time() - (ttl_minutes * 60)
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM conversation_sessions WHERE created_at < ?;", (cutoff,))
        return cursor.rowcount


# ==========================================
# Al-Noor Demo Clinic - Dynamic Schedule & Overrides
# ==========================================

def normalize_day_name(day_str: str) -> str:
    """Normalizes Libyan/Arabic day names (e.g. 'الاثنين' / 'الإثنين')."""
    d = day_str.strip()
    d = d.replace("إ", "ا").replace("أ", "ا").replace("آ", "ا")
    if "جمعة" in d: return "الجمعة"
    if "سبت" in d: return "السبت"
    if "احد" in d or "أحد" in d: return "الأحد"
    if "اثنين" in d or "إثنين" in d: return "الاثنين"
    if "ثلاثاء" in d: return "الثلاثاء"
    if "اربعاء" in d or "أربعاء" in d: return "الأربعاء"
    if "خميس" in d: return "الخميس"
    return day_str.strip()


def get_daily_schedule(day_name: str, target_date: Optional[str] = None, db_path: str = DB_PATH) -> Dict[str, Any]:
    """
    Real-time query for Al-Noor Demo Clinic schedule for a given day:
    - Queries emergency_clinics (morning, evening, night).
    - Queries followup_clinics.
    - Merges active daily_overrides for target_date.
    - Overrides take precedence over the base weekly schedule.
    """
    normalized_day = normalize_day_name(day_name)
    if not target_date:
        from app.services.time_utils import get_libya_now
        target_date = get_libya_now().strftime("%Y-%m-%d")

    with get_db(db_path) as conn:
        cursor = conn.cursor()

        # 1. Fetch active daily overrides for target_date or day_of_week
        cursor.execute("""
            SELECT * FROM daily_overrides
            WHERE override_date = ? OR day_of_week = ?
            ORDER BY id ASC;
        """, (target_date, normalized_day))
        override_rows = cursor.fetchall()

        overrides_by_doc = {}
        for ov in override_rows:
            norm_name = norm(ov["doctor_name"])
            overrides_by_doc[norm_name] = dict(ov)

        # 2. Fetch emergency clinics
        cursor.execute("""
            SELECT * FROM emergency_clinics
            WHERE day_of_week = ? OR day_of_week = ?
            ORDER BY id ASC;
        """, (normalized_day, "الإثنين" if normalized_day == "الاثنين" else normalized_day))
        emergency_rows = cursor.fetchall()

        # 3. Fetch followup clinics
        cursor.execute("""
            SELECT * FROM followup_clinics
            WHERE day_of_week = ? OR day_of_week = ?
            ORDER BY id ASC;
        """, (normalized_day, "الإثنين" if normalized_day == "الاثنين" else normalized_day))
        followup_rows = cursor.fetchall()

        status_arabic_map = {
            "available": "متواجد حسب الجدول المعتاد ✅",
            "apologized": "معتذر اليوم - غير متواجد ❌",
            "delayed": "تأخير / تعديل موعد ⏰",
            "left": "غادر العيادة لليوم 🚪",
            "arrived": "وصل للعيادة ويستقبل الآن 🩺",
            "booking_closed": "مكتمل العدد / الحجز مقفل ⛔"
        }

        # Format emergency clinics with overrides
        emergency_list = []
        for r in emergency_rows:
            item = dict(r)
            d_norm = norm(item["doctor_name"])
            matched_override = None
            for ov_key, ov_val in overrides_by_doc.items():
                if ov_key in d_norm or d_norm in ov_key:
                    matched_override = ov_val
                    break

            if matched_override:
                item["status"] = matched_override["status"]
                item["status_display"] = status_arabic_map.get(matched_override["status"], matched_override["status"])
                item["note"] = matched_override.get("note", "")
                item["is_overridden"] = True
            else:
                item["status"] = "available"
                item["status_display"] = "متواجد حسب الجدول المعتاد ✅"
                item["note"] = ""
                item["is_overridden"] = False
            emergency_list.append(item)

        # Format followup clinics with overrides
        followup_list = []
        for r in followup_rows:
            item = dict(r)
            d_norm = norm(item["doctor_name"])
            matched_override = None
            for ov_key, ov_val in overrides_by_doc.items():
                if ov_key in d_norm or d_norm in ov_key:
                    matched_override = ov_val
                    break

            if matched_override:
                item["status"] = matched_override["status"]
                item["status_display"] = status_arabic_map.get(matched_override["status"], matched_override["status"])
                item["note"] = matched_override.get("note", "")
                item["is_overridden"] = True
            else:
                item["status"] = "available"
                item["status_display"] = "متواجد حسب الجدول المعتاد ✅"
                item["note"] = ""
                item["is_overridden"] = False
            followup_list.append(item)

        return {
            "day_name": normalized_day,
            "target_date": target_date,
            "emergency_clinics": emergency_list,
            "followup_clinics": followup_list,
            "overrides_applied": list(overrides_by_doc.values())
        }


def add_daily_override(
    doctor_name: str,
    status: str,
    note: str = "",
    updated_by: str = "staff",
    day_of_week: Optional[str] = None,
    override_date: Optional[str] = None,
    clinic_type: str = "both",
    db_path: str = DB_PATH
) -> Dict[str, Any]:
    """
    Inserts or updates a daily override for a doctor and commits immediately to SQLite.
    Returns the saved row dict.
    """
    if not override_date:
        from app.services.time_utils import get_libya_now
        now = get_libya_now()
        override_date = now.strftime("%Y-%m-%d")
        if not day_of_week:
            from app.services.time_utils import ARABIC_DAYS
            day_of_week = ARABIC_DAYS.get(now.weekday(), "اليوم")

    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            DELETE FROM daily_overrides
            WHERE override_date = ? AND doctor_name = ?;
        """, (override_date, doctor_name))

        cursor.execute("""
            INSERT INTO daily_overrides (
                override_date, day_of_week, doctor_name, clinic_type, status, note, updated_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?);
        """, (override_date, day_of_week, doctor_name, clinic_type, status, note, updated_by))

        override_id = cursor.lastrowid
        cursor.execute("SELECT * FROM daily_overrides WHERE id = ?;", (override_id,))
        saved_row = dict(cursor.fetchone())

        # Also reflect in legacy doctors table for backwards compatibility
        cursor.execute("""
            UPDATE doctors
            SET status = ?, today_status = ?, daily_note = ?, today_note = ?
            WHERE name LIKE ?;
        """, (status, status, note, note, f"%{doctor_name}%"))

        return saved_row


def get_active_overrides(target_date: Optional[str] = None, db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Returns all active daily overrides for target_date (or today)."""
    if not target_date:
        from app.services.time_utils import get_libya_now
        target_date = get_libya_now().strftime("%Y-%m-%d")

    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM daily_overrides
            WHERE override_date = ?
            ORDER BY id DESC;
        """, (target_date,))
        return [dict(r) for r in cursor.fetchall()]


# ==========================================
# Persistent Conversation History
# ==========================================

def add_conversation_history(
    sender_phone: str,
    role: str,
    message_text: str,
    clinic_id: str = "demo_hospital",
    db_path: str = DB_PATH,
    channel: str = "whatsapp"
) -> None:
    """Records a message turn in conversation_history and conversation_sessions."""
    valid_role = role if role in ("user", "model", "system") else "user"
    now_epoch = time.time()
    channel = channel or "whatsapp"
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO conversation_history (clinic_id, sender_phone, role, message_text, created_at, channel)
            VALUES (?, ?, ?, ?, ?, ?);
        """, (clinic_id, sender_phone, valid_role, message_text, now_epoch, channel))

        cursor.execute("""
            INSERT INTO conversation_sessions (phone_number, role, message_text, created_at, channel)
            VALUES (?, ?, ?, ?, ?);
        """, (sender_phone, valid_role, message_text, now_epoch, channel))


def get_conversation_history(
    sender_phone: str,
    limit: int = 6,
    clinic_id: str = "demo_hospital",
    db_path: str = DB_PATH,
    channel: Optional[str] = None
) -> List[Dict[str, str]]:
    """
    Fetches the last `limit` messages (chronological order) for (clinic_id, sender_phone).
    When channel is given, history is scoped to that channel too.
    channel=None keeps the legacy unfiltered behavior.
    """
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        if channel:
            cursor.execute("""
                SELECT role, message_text
                FROM conversation_history
                WHERE sender_phone = ? AND clinic_id = ? AND channel = ?
                ORDER BY id DESC
                LIMIT ?;
            """, (sender_phone, clinic_id, channel, limit))
        else:
            cursor.execute("""
                SELECT role, message_text
                FROM conversation_history
                WHERE sender_phone = ? AND clinic_id = ?
                ORDER BY id DESC
                LIMIT ?;
            """, (sender_phone, clinic_id, limit))
        rows = cursor.fetchall()
        return [{"role": r["role"], "text": r["message_text"]} for r in reversed(rows)]


# ==========================================
# Authorized Staff Management (Deterministic SQL)
# ==========================================

def is_staff_authorized(phone_number: str, db_path: str = DB_PATH) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Checks if phone_number is authorized in authorized_staff or clinic_info.
    Returns: (is_authorized, role, name)
    """
    def _normalize(phone: str) -> str:
        # Full-number normalization only: strip non-digits, the 00 prefix,
        # the Libya country code 218, and a leading zero. Substring matching
        # is forbidden here: a sender id containing a single digit (or a
        # short suffix) must never match a staff number that merely contains it.
        digits = "".join(filter(str.isdigit, phone or ""))
        if digits.startswith("00"):
            digits = digits[2:]
        if digits.startswith("218") and len(digits) >= 9:
            digits = digits[3:]
        while digits.startswith("0") and len(digits) > 7:
            digits = digits[1:]
        return digits

    norm_phone = _normalize(phone_number)
    if not norm_phone:
        return False, None, None
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM authorized_staff;")
        all_staff = cursor.fetchall()
        for s in all_staff:
            s_phone = _normalize(s["phone_number"])
            if s_phone and s_phone == norm_phone:
                return True, s["role"], s["name"]

        cursor.execute("SELECT value FROM clinic_info WHERE key IN ('authorized_staff_phones', 'authorized_phones');")
        rows = cursor.fetchall()
        for r in rows:
            for p in r["value"].split(","):
                p_digits = _normalize(p)
                if p_digits and p_digits == norm_phone:
                    return True, "staff", "موظف معتمد"

    return False, None, None


def is_sender_authorized(
    sender: str,
    channel: str = "whatsapp",
    db_path: str = DB_PATH
) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Channel-aware staff authorization.
    - WhatsApp / simulator: the sender is a phone number, matched with
      full-number normalization (is_staff_authorized).
    - Messenger: the sender is a Page-scoped user id (PSID), an opaque
      identifier that must NEVER be phone-normalized (stripping digits
      could collapse two different PSIDs). It is matched exactly against
      the authorized_staff table (PSIDs are stored in its phone_number
      column as plain identifiers) and against the
      authorized_messenger_psids key in clinic_info.
    Returns: (is_authorized, role, name)
    """
    channel = (channel or "whatsapp").strip().lower()
    if channel != "messenger":
        return is_staff_authorized(sender, db_path)

    psid = (sender or "").strip()
    if not psid:
        return False, None, None
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM authorized_staff;")
        for s in cursor.fetchall():
            if (s["phone_number"] or "").strip() == psid:
                return True, s["role"], s["name"]
        cursor.execute(
            "SELECT value FROM clinic_info WHERE key = 'authorized_messenger_psids';"
        )
        row = cursor.fetchone()
        if row:
            for item in (row["value"] or "").split(","):
                if item.strip() == psid:
                    return True, "staff", "موظف معتمد"
    return False, None, None


def add_authorized_staff(
    phone_number: str,
    name: str = "موظف",
    role: str = "staff",
    db_path: str = DB_PATH
) -> bool:
    """Adds or updates an authorized staff member."""
    clean_role = role if role in ("owner", "admin", "staff") else "staff"
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO authorized_staff (phone_number, name, role)
            VALUES (?, ?, ?);
        """, (phone_number.strip(), name.strip(), clean_role))
        return True


def remove_authorized_staff(phone_number: str, db_path: str = DB_PATH) -> bool:
    """Removes an authorized staff member."""
    norm_phone = "".join(filter(str.isdigit, phone_number))
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, phone_number FROM authorized_staff;")
        rows = cursor.fetchall()
        deleted = False
        for r in rows:
            p_clean = "".join(filter(str.isdigit, r["phone_number"]))
            if p_clean and (p_clean in norm_phone or norm_phone in p_clean):
                cursor.execute("DELETE FROM authorized_staff WHERE id = ?;", (r["id"],))
                deleted = True
        return deleted


def list_authorized_staff(db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Returns all authorized staff."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM authorized_staff ORDER BY id ASC;")
        return [dict(r) for r in cursor.fetchall()]


# Initialize database automatically on import if not exists
init_db(DB_PATH)
seed_default_data(DB_PATH)
