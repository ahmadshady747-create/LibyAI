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
            created_at REAL NOT NULL
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

        # 6. Incoming Messages Ledger (Idempotent WhatsApp ingestion)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS incoming_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider TEXT NOT NULL DEFAULT 'whatsapp',
            message_id TEXT NOT NULL,
            sender TEXT NOT NULL,
            payload_json TEXT,
            created_at REAL NOT NULL,
            UNIQUE(provider, message_id)
        );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_incoming_messages_provider_mid ON incoming_messages(provider, message_id);")

        # 7. Durable Message Jobs Queue
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS message_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            incoming_message_id INTEGER NOT NULL REFERENCES incoming_messages(id),
            provider TEXT NOT NULL DEFAULT 'whatsapp',
            message_id TEXT NOT NULL UNIQUE,
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
            completed_at REAL
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
            clinic_id TEXT NOT NULL DEFAULT 'jasmine_hospital',
            sender_phone TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('user', 'model', 'system')),
            message_text TEXT NOT NULL,
            created_at REAL NOT NULL
        );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_conv_hist_sender ON conversation_history(clinic_id, sender_phone, created_at);")


def seed_default_data(db_path: str = DB_PATH) -> None:
    """Populates default clinic identity, doctors, and services if tables are empty."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) AS cnt FROM emergency_clinics;")
        if cursor.fetchone()["cnt"] == 0:
            from seed_jasmine_hospital import seed_jasmine
            seed_jasmine(db_path)

        # Seed Clinic Info
        default_info = {
            "name": "مستشفى الياسمين الإيوائي",
            "clinic_name": "مستشفى الياسمين الإيوائي",
            "address": "زليتن - خلف مدرسة خديجة الكبرى",
            "emergency_phone": "0911059900 - 0945361562",
            "reception_phone": "0911059900 - 0945361562",
            "booking_policy": "الاستفسار والخدمات متاحة 24 ساعة، الحضور والمتابعة بالاستقبال وفق الفترات المعلنة.",
            "map_link": "https://maps.google.com/?q=Zliten+Jasmine+Hospital",
            "admin_group_id": "clinic_staff_group@g.us",
            "authorized_staff_phones": "0911059900, 0945361562, 0912345678",
            "authorized_phones": "0911059900, 0945361562, 0912345678",
            "facilities_info": "قسم الإسعاف والطوارئ متاح 24 ساعة يومياً على مدار الأسبوع، غرف إيواء حديثة، عيادات تخصصية، ومختبر متكامل."
        }
        for k, v in default_info.items():
            cursor.execute("INSERT OR IGNORE INTO clinic_info (key, value) VALUES (?, ?);", (k, v))

        # Seed Doctors if empty
        cursor.execute("SELECT COUNT(*) AS cnt FROM doctors;")
        if cursor.fetchone()["cnt"] == 0:
            doctors_data = [
                ("د. عبدالله ديهوم", "عظام ومفاصل", "السبت إلى الخميس: 09:00 ص - 01:00 م", "available", "", 40.0),
                ("د. علي بن عمران", "مسالك بولية وعقم ذكورة", "السبت، الإثنين، الأربعاء: 04:00 م - 08:00 م", "available", "", 45.0),
                ("د. أحمد الزليطني", "باطنة عامة وسكري", "يومياً عدا الجمعة: 10:00 ص - 02:00 م", "available", "", 40.0),
                ("د. فاطمة الورفلي", "عيون وجراحة البصر", "الأحد، الثلاثاء، الخميس: 04:00 م - 07:30 م", "available", "", 50.0),
                ("د. عبدالعاطي المشيطي", "أطفال وحديثي ولادة", "يومياً: 10:00 ص - 01:00 م ومن 05:00 م - 08:00 م", "available", "", 35.0),
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
    Matches names or specialties (e.g. 'عظام', 'دكتور علي', 'ديهوم', 'اطفال').
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
    db_path: str = DB_PATH
) -> Tuple[bool, Dict[str, Any], Dict[str, Any], str]:
    """
    Executes business mutation, audit-log insertion, and marking the job
    as processing-completed in a SINGLE atomic SQLite transaction.

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
        else:
            raise ValueError(f"Unknown mutation_type: {mutation_type}")

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

def save_conversation_turn(phone_number: str, role: str, message_text: str, db_path: str = DB_PATH) -> None:
    """Saves a single conversation turn with high-precision epoch timestamp."""
    valid_role = role if role in ("user", "model", "system") else "user"
    with get_db(db_path) as conn:
        conn.cursor().execute("""
        INSERT INTO conversation_sessions (phone_number, role, message_text, created_at)
        VALUES (?, ?, ?, ?);
        """, (phone_number, valid_role, message_text, time.time()))


def get_sliding_session_history(
    phone_number: str,
    max_turns: int = 4,
    ttl_minutes: int = 15,
    db_path: str = DB_PATH
) -> List[Dict[str, str]]:
    """
    Retrieves the last `max_turns` interactions (user & model) for a patient within `ttl_minutes`.
    Returns list of dicts: [{"role": "user"|"model", "text": "..."}] sorted chronologically.
    """
    cutoff_time = time.time() - (ttl_minutes * 60)
    with get_db(db_path) as conn:
        cursor = conn.cursor()
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
# Jasmine Shelter Hospital - Dynamic Schedule & Overrides
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
    Real-time query for Jasmine Shelter Hospital schedule for a given day:
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
    clinic_id: str = "jasmine_hospital",
    db_path: str = DB_PATH
) -> None:
    """Records a message turn in conversation_history and conversation_sessions."""
    valid_role = role if role in ("user", "model", "system") else "user"
    now_epoch = time.time()
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO conversation_history (clinic_id, sender_phone, role, message_text, created_at)
            VALUES (?, ?, ?, ?, ?);
        """, (clinic_id, sender_phone, valid_role, message_text, now_epoch))

        cursor.execute("""
            INSERT INTO conversation_sessions (phone_number, role, message_text, created_at)
            VALUES (?, ?, ?, ?);
        """, (sender_phone, valid_role, message_text, now_epoch))


def get_conversation_history(
    sender_phone: str,
    limit: int = 6,
    clinic_id: str = "jasmine_hospital",
    db_path: str = DB_PATH
) -> List[Dict[str, str]]:
    """
    Fetches the last `limit` messages (chronological order) for (clinic_id, sender_phone).
    """
    with get_db(db_path) as conn:
        cursor = conn.cursor()
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
    norm_phone = "".join(filter(str.isdigit, phone_number))
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM authorized_staff;")
        all_staff = cursor.fetchall()
        for s in all_staff:
            s_phone = "".join(filter(str.isdigit, s["phone_number"]))
            if s_phone and (s_phone in norm_phone or norm_phone in s_phone):
                return True, s["role"], s["name"]

        cursor.execute("SELECT value FROM clinic_info WHERE key IN ('authorized_staff_phones', 'authorized_phones');")
        rows = cursor.fetchall()
        for r in rows:
            for p in r["value"].split(","):
                p_digits = "".join(filter(str.isdigit, p))
                if p_digits and (p_digits in norm_phone or norm_phone in p_digits):
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
