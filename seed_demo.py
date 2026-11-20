"""
Seed Data Script — LibyAI multi-sector fictional demo profiles (زليتن)

FICTIONAL DEMO DATA ONLY. Every business name, person name, phone number,
price and schedule in this file is invented for demonstration and testing.
No real business, clinic, doctor or person is represented here. Never
replace this with real data in a public repository.

Usage:
    python seed_demo.py [--sector retail|restaurant|clinic|workshop|pharmacy]
    LIBYAI_DEMO_SECTOR=retail python seed_demo.py
    seed_demo(db_path, sector="retail")

The clinic profile is the historical default and its data is kept EXACTLY
as before (existing tests depend on it); it only gains a business_info row
and clinic FAQs on top. Other profiles seed business_info, catalog_items,
resources (where relevant), business_faqs, authorized_staff and the legacy
clinic_info keys.
"""

import sys
import sqlite3
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
import argparse
import os

DB_PATH = os.environ.get("DB_PATH", "clinic.db")

SECTORS = ("retail", "restaurant", "clinic", "workshop", "pharmacy")

# Fictional demo staff shared by every profile (demo-only placeholders,
# matching the AUTHORIZED_STAFF_PHONES default in app/config.py).
DEMO_STAFF = [
    ("0910101010", "إدارة النشاط التجريبي", "owner"),
    ("0930303030", "مشرف الاستقبال التجريبي", "admin"),
    ("0920202020", "موظف استقبال تجريبي", "staff"),
]

# Fictional demo Messenger staff PSIDs (demo-only placeholders).
DEMO_MESSENGER_PSIDS = "demo_psid_staff_1, demo_psid_staff_2"

# --- Clinic FAQs -------------------------------------------------------
# The booking answer MUST mention الحضور / الاستقبال: existing tests
# (test_system.py step 8, test_system_integrity.py turn 3) assert those
# words for booking questions.
CLINIC_FAQS = [
    (
        "كيف أحجز موعد كشف؟",
        "الحجز يتم بالحضور الشخصي لمكتب الاستقبال أو بالاتصال على رقم الاستقبال خلال ساعات الدوام.",
        "حجز موعد كشف",
    ),
    (
        "ما هي طرق الدفع المتاحة؟",
        "نقبل الدفع نقداً وبالبطاقات المصرفية (تداول، نمو) والخدمات الإلكترونية (سداد، إدفع لي، موبي كاش) بنفس السعر النقدي.",
        "دفع سداد تداول بطاقة",
    ),
    (
        "هل قسم الطوارئ متاح 24 ساعة؟",
        "نعم، قسم الطوارئ متاح 24 ساعة يومياً على مدار الأسبوع.",
        "طوارئ 24 ساعة",
    ),
]

# --- Generic (non-clinic) profiles --------------------------------------
# Format per profile:
#   business_info: (name, sector, address, support_phone, escalation_phone,
#                   working_hours, policy_notes)
#   catalog: list of (name, category, price_lyd, is_available, schedule_or_eta, details)
#   resources: list of (name, role_or_specialty, schedule, is_available, notes)
#   faqs: list of (question, answer, keywords)
PROFILES = {
    "retail": {
        "business_info": (
            "متجر النور للإلكترونيات",
            "retail",
            "زليتن - شارع تجريبي",
            "0910202020",
            "0910202020",
            "السبت - الخميس: 9 صباحاً - 9 مساءً، الجمعة: 4 مساءً - 9 مساءً",
            "الدفع نقداً أو عبر تداول وسداد بنفس السعر، الإرجاع خلال 7 أيام مع الفاتورة، التوصيل داخل زليتن 15 د.ل.",
        ),
        "catalog": [
            ("شاشة سامسونج 55 بوصة", "شاشات", 2450.0, 1, "متوفرة في المحل", "شاشة ذكية 4K مع ضمان سنتين"),
            ("ثلاجة هيتاشي", "أجهزة منزلية", 3200.0, 1, "متوفرة في المحل", "ثلاجة بابين مع ضمان 3 سنوات"),
            ("غسالة ال جي", "أجهزة منزلية", 2800.0, 1, "متوفرة في المحل", "غسالة أوتوماتيك 8 كجم"),
            ("مكيف جنرال 12", "تكييف", 1800.0, 1, "متوفرة في المحل", "مكيف سبلت 12000 وحدة مع التركيب"),
            ("هاتف شاومي نوت", "هواتف", 1450.0, 1, "متوفر في المحل", "ذاكرة 256 جيجا، رام 8 جيجا"),
            ("سماعات بلوتوث", "إكسسوارات", 120.0, 1, "متوفرة في المحل", "سماعات لاسلكية مع علبة شحن"),
            ("مكنسة كهربائية", "أجهزة منزلية", 450.0, 0, "تصل خلال أسبوع", "مكنسة 2000 واط"),
            ("فرن كهربائي", "أجهزة منزلية", 650.0, 1, "متوفر في المحل", "فرن 60 لتر مع شواية"),
        ],
        "resources": [],
        "faqs": [
            (
                "كم سعر التوصيل؟",
                "التوصيل داخل مدينة زليتن 15 د.ل، وخارجها حسب المدينة، ويتم التوصيل خلال يوم إلى يومين.",
                "توصيل شحن سعر",
            ),
            (
                "ما هي طرق الدفع؟",
                "نقبل الدفع نقداً وعبر تداول وسداد وموبي كاش بنفس السعر النقدي وبدون عمولة إضافية.",
                "دفع سداد تداول موبي كاش",
            ),
            (
                "هل يمكن إرجاع المنتج؟",
                "نعم، يمكنك إرجاع المنتج خلال 7 أيام من الشراء مع الفاتورة بحالته الأصلية.",
                "إرجاع استبدال ضمان",
            ),
        ],
    },
    "restaurant": {
        "business_info": (
            "مطعم النور للمشويات",
            "restaurant",
            "زليتن - شارع تجريبي",
            "0910303030",
            "0910303030",
            "يومياً: 11 صباحاً - 12 منتصف الليل",
            "الحجز بالحضور أو الاتصال، التوصيل داخل زليتن 10 د.ل خلال 45 دقيقة، الدفع نقداً أو سداد.",
        ),
        "catalog": [
            ("مشوي مشكل", "مشويات", 65.0, 1, "جاهز خلال 25 دقيقة", "لحم ودجاج مشوي مع الأرز والسلطة"),
            ("شاورما دجاج", "سندويتشات", 18.0, 1, "جاهزة خلال 10 دقائق", "شاورما دجاج مع الثومية والمخلل"),
            ("شاورما لحم", "سندويتشات", 22.0, 1, "جاهزة خلال 10 دقائق", "شاورما لحم مع الطحينة"),
            ("برجر لحم", "سندويتشات", 25.0, 1, "جاهز خلال 15 دقيقة", "برجر لحم مع الجبن والبطاطس"),
            ("بيتزا خضار", "بيتزا", 30.0, 1, "جاهزة خلال 20 دقيقة", "بيتزا بالخضار المشكلة والجبن"),
            ("سلطة مشكلة", "سلطات", 12.0, 1, "جاهزة فوراً", "سلطة خضار طازجة مع زيت الزيتون"),
            ("عصير برتقال طبيعي", "مشروبات", 8.0, 1, "جاهز فوراً", "عصير برتقال طازج"),
            ("مشروب غازي", "مشروبات", 5.0, 1, "جاهز فوراً", "مشروب غازي بارد"),
        ],
        "resources": [],
        "faqs": [
            (
                "هل يوجد توصيل؟",
                "نعم، نوصل داخل مدينة زليتن مقابل 10 د.ل خلال 45 دقيقة تقريباً.",
                "توصيل دليفري",
            ),
            (
                "كيف أحجز طاولة؟",
                "الحجز بالحضور الشخصي أو بالاتصال على رقم المطعم خلال ساعات العمل.",
                "حجز طاولة",
            ),
            (
                "ما هي طرق الدفع؟",
                "نقبل الدفع نقداً وعبر سداد وموبي كاش.",
                "دفع سداد موبي كاش",
            ),
        ],
    },
    "workshop": {
        "business_info": (
            "ورشة النور لصيانة السيارات",
            "workshop",
            "زليتن - شارع تجريبي",
            "0910404040",
            "0910404040",
            "السبت - الخميس: 8 صباحاً - 7 مساءً، الجمعة مغلق",
            "الحجز بالحضور أو الاتصال، ضمان 3 أشهر على أعمال الصيانة، الدفع نقداً أو سداد.",
        ),
        "catalog": [
            ("تغيير زيت المحرك", "صيانة دورية", 120.0, 1, "يتم خلال ساعة", "زيت محرك مع الفلتر"),
            ("فحص كمبيوتر", "تشخيص", 50.0, 1, "يتم خلال نصف ساعة", "فحص شامل بأنظمة السيارة"),
            ("تغيير فرامل", "صيانة", 180.0, 1, "يتم خلال ساعتين", "تغيير أقمشة الفرامل الأمامية والخلفية"),
            ("صيانة مكيف السيارة", "صيانة", 250.0, 1, "يتم خلال 3 ساعات", "شحن غاز وفحص دورة التكييف"),
            ("غسيل كامل", "غسيل", 35.0, 1, "يتم خلال 45 دقيقة", "غسيل خارجي وداخلي شامل"),
            ("تغيير إطارات", "إطارات", 80.0, 1, "يتم خلال ساعة", "تغيير وترصيص 4 إطارات"),
        ],
        "resources": [
            ("سالم بن عيسى", "فني ميكانيكا", "السبت - الخميس: 8 صباحاً - 7 مساءً", 1, "متخصص في المحركات"),
            ("عمر الحداد", "فني كهرباء سيارات", "السبت - الخميس: 9 صباحاً - 6 مساءً", 1, "متخصص في أنظمة الكهرباء والتكييف"),
        ],
        "faqs": [
            (
                "هل يوجد ضمان على الصيانة؟",
                "نعم، جميع أعمال الصيانة مضمونة لمدة 3 أشهر.",
                "ضمان صيانة",
            ),
            (
                "كيف أحجز موعد صيانة؟",
                "الحجز بالحضور الشخصي للورشة أو بالاتصال على رقم الورشة خلال ساعات العمل.",
                "حجز موعد صيانة",
            ),
            (
                "ما هي طرق الدفع؟",
                "نقبل الدفع نقداً وعبر سداد.",
                "دفع سداد",
            ),
        ],
    },
    "pharmacy": {
        "business_info": (
            "صيدلية النور",
            "pharmacy",
            "زليتن - شارع تجريبي",
            "0910505050",
            "0910505050",
            "يومياً: 8 صباحاً - 12 منتصف الليل",
            "الأدوية الموصوفة تحتاج وصفة طبية، التوصيل داخل زليتن 10 د.ل، الدفع نقداً أو سداد.",
        ),
        "catalog": [
            ("فيتامين سي", "فيتامينات", 25.0, 1, "متوفر في الصيدلية", "فيتامين سي 1000 ملغ، 20 قرص فوار"),
            ("مسكن عام", "مسكنات", 15.0, 1, "متوفر في الصيدلية", "مسكن وخافض حرارة، يرجى استشارة الصيدلي"),
            ("معقم يدين", "عناية", 10.0, 1, "متوفر في الصيدلية", "معقم يدين 250 مل"),
            ("ضمادات طبية", "مستلزمات", 8.0, 1, "متوفرة في الصيدلية", "علبة ضمادات متنوعة"),
            ("شامبو طبي", "عناية", 30.0, 1, "متوفر في الصيدلية", "شامبو طبي للشعر الجاف"),
            ("كريم مرطب", "عناية", 20.0, 1, "متوفر في الصيدلية", "كريم مرطب للبشرة الجافة"),
        ],
        "resources": [
            ("صيدلي المناوبة", "صيدلي", "يومياً: 8 صباحاً - 12 منتصف الليل", 1, "للاستشارة حول الأدوية المتاحة"),
        ],
        "faqs": [
            (
                "هل أحتاج وصفة طبية؟",
                "الأدوية الموصوفة تحتاج وصفة طبية سارية، أما مستحضرات العناية والفيتامينات فمتاحة بدون وصفة.",
                "وصفة طبية دواء",
            ),
            (
                "هل يوجد توصيل؟",
                "نعم، نوصل داخل مدينة زليتن مقابل 10 د.ل.",
                "توصيل",
            ),
            (
                "ما هي ساعات العمل؟",
                "نعمل يومياً من 8 صباحاً حتى 12 منتصف الليل.",
                "ساعات العمل دوام",
            ),
        ],
    },
}


def _seed_generic_profile(cursor, sector: str):
    """Seeds one of the non-clinic fictional demo profiles."""
    profile = PROFILES[sector]
    name, sector_value, address, support_phone, escalation_phone, working_hours, policy_notes = profile["business_info"]

    clinic_constants = {
        "name": name,
        "clinic_name": name,
        "address": address,
        "city": "زليتن",
        "emergency_phone": escalation_phone,
        "reception_phone": support_phone,
        "is_medical": "1" if sector_value in ("pharmacy", "medical") else "0",
        "contact_numbers": support_phone,
        "map_link": "https://maps.google.com/?q=Zliten",
        "booking_policy": policy_notes,
        "authorized_staff_phones": "0910101010, 0930303030, 0920202020",
        "authorized_messenger_psids": DEMO_MESSENGER_PSIDS,
    }
    for k, v in clinic_constants.items():
        cursor.execute("INSERT OR REPLACE INTO clinic_info (key, value) VALUES (?, ?);", (k, v))

    cursor.execute("DELETE FROM authorized_staff;")
    cursor.executemany("INSERT INTO authorized_staff (phone_number, name, role) VALUES (?, ?, ?);", DEMO_STAFF)

    cursor.execute("DELETE FROM business_info;")
    cursor.execute(
        "INSERT INTO business_info (id, name, sector, address, support_phone, escalation_phone, working_hours, policy_notes, currency) "
        "VALUES (1, ?, ?, ?, ?, ?, ?, ?, 'LYD');",
        (name, sector_value, address, support_phone, escalation_phone, working_hours, policy_notes),
    )

    cursor.execute("DELETE FROM catalog_items;")
    cursor.executemany(
        "INSERT INTO catalog_items (name, category, price_lyd, is_available, schedule_or_eta, details) VALUES (?, ?, ?, ?, ?, ?);",
        profile["catalog"],
    )

    cursor.execute("DELETE FROM resources;")
    if profile["resources"]:
        cursor.executemany(
            "INSERT INTO resources (name, role_or_specialty, schedule, is_available, notes) VALUES (?, ?, ?, ?, ?);",
            profile["resources"],
        )

    cursor.execute("DELETE FROM business_faqs;")
    cursor.executemany(
        "INSERT INTO business_faqs (question, answer, keywords) VALUES (?, ?, ?);",
        profile["faqs"],
    )


def seed_demo(db_path: str = DB_PATH, sector: str = "clinic"):
    sector = (sector or "clinic").strip().lower()
    if sector not in SECTORS:
        raise ValueError(f"Unknown demo sector: {sector!r}. Choose one of: {', '.join(SECTORS)}")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 1. Create tables if not exist (DDL mirrors db.init_db, so the script
    # also works standalone on a fresh database without importing db —
    # importing db would seed the default clinic.db as an import side
    # effect, which a --db script must never do).
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
    cursor.execute("PRAGMA table_info(doctors);")
    _d_cols = [c[1] for c in cursor.fetchall()]
    if "room_number" not in _d_cols:
        cursor.execute("ALTER TABLE doctors ADD COLUMN room_number TEXT DEFAULT 'غير محدد';")
    if "schedule_days" not in _d_cols:
        cursor.execute("ALTER TABLE doctors ADD COLUMN schedule_days TEXT DEFAULT 'السبت,الأحد,الإثنين,الثلاثاء,الأربعاء,الخميس';")
    if "today_status" not in _d_cols:
        cursor.execute("ALTER TABLE doctors ADD COLUMN today_status TEXT DEFAULT 'available';")
    if "today_note" not in _d_cols:
        cursor.execute("ALTER TABLE doctors ADD COLUMN today_note TEXT DEFAULT '';")
    if "is_active" not in _d_cols:
        cursor.execute("ALTER TABLE doctors ADD COLUMN is_active INTEGER DEFAULT 1;")

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
    cursor.execute("PRAGMA table_info(services);")
    _s_cols = [c[1] for c in cursor.fetchall()]
    if "prep_instructions" not in _s_cols:
        cursor.execute("ALTER TABLE services ADD COLUMN prep_instructions TEXT DEFAULT '';")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS clinic_info (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS authorized_staff (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        phone_number TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL DEFAULT 'موظف',
        role TEXT NOT NULL CHECK(role IN ('owner', 'admin', 'staff')) DEFAULT 'staff',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

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

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS conversation_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        clinic_id TEXT NOT NULL DEFAULT 'demo_hospital',
        sender_phone TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('user', 'model', 'system')),
        message_text TEXT NOT NULL,
        created_at REAL NOT NULL
    );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_conv_hist_sender ON conversation_history(clinic_id, sender_phone, created_at);")

    # Business tables (multi-sector; DDL mirrors db.init_db).
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

    # Non-clinic profiles seed only the generic tables and return; the
    # clinic path below is kept exactly as before.
    if sector != "clinic":
        _seed_generic_profile(cursor, sector)
        conn.commit()
        conn.close()
        print(f"✅ Seeded fictional demo data successfully! (sector: {sector})")
        return

    # 2. Update Clinic Identity
    clinic_constants = {
        "name": "مصحة النور التجريبية",
        "clinic_name": "مصحة النور التجريبية",
        "facility_type": "مستشفى إيوائي",
        "english_name": "Al-Noor Demo Clinic",
        "address": "زليتن - شارع تجريبي",
        "city": "زليتن",
        "emergency_phone": "0910101010 - 0930303030",
        "reception_phone": "0910101010 - 0930303030",
        "is_medical": "1",
        "contact_numbers": "0910101010 - 0930303030",
        "map_link": "https://maps.google.com/?q=Zliten",
        "shift_morning": "من الساعة 08:00 صباحاً إلى 02:00 ظهراً",
        "shift_evening": "من الساعة 02:00 ظهراً إلى 08:00 مساءً",
        "shift_night": "من الساعة 08:00 مساءً إلى 08:00 صباحاً",
        "booking_policy": "الاستقبال والاستفسارات متاحة 24 ساعة، الحضور والمتابعة وفق الفترات المعلنة، والتوقيتات تقريبية تختلف باختلاف عيادات المتابعة.",
        "facilities_info": "قسم الإسعاف والطوارئ متاح 24 ساعة يومياً على مدار الأسبوع، غرف إيواء حديثة، عيادات تخصصية، ومختبر متكامل.",
        "authorized_staff_phones": "0910101010, 0930303030, 0920202020"
    }

    for k, v in clinic_constants.items():
        cursor.execute("INSERT OR REPLACE INTO clinic_info (key, value) VALUES (?, ?);", (k, v))

    # 3. Seed Authorized Staff
    cursor.execute("DELETE FROM authorized_staff;")
    initial_staff = [
        ("0910101010", "إدارة مستشفى النور", "owner"),
        ("0930303030", "مشرف الاستقبال والطوارئ", "admin"),
        ("0920202020", "موظف استقبال تجريبي", "staff")
    ]
    cursor.executemany("INSERT INTO authorized_staff (phone_number, name, role) VALUES (?, ?, ?);", initial_staff)

    # 4. Clear and Seed Emergency Clinics
    cursor.execute("DELETE FROM emergency_clinics;")

    # Format: (day_of_week, department, shift, shift_time, doctor_name)
    emergency_data = [
        # --- الجمعة ---
        ("الجمعة", "نساء وولادة", "صباحية", "8 ص - 2 ظ", "د. أحمد العربي"),
        ("الجمعة", "نساء وولادة", "مسائية", "2 ظ - 8 م", "د. أحمد العربي"),
        ("الجمعة", "نساء وولادة", "ليلية", "8 م - 8 ص", "د. أحمد العربي"),
        ("الجمعة", "أطفال", "صباحية", "8 ص - 2 ظ", "د. عمر الزاوي"),
        ("الجمعة", "أطفال", "مسائية", "2 ظ - 8 م", "د. عمر الزاوي"),
        ("الجمعة", "أطفال", "ليلية", "8 م - 8 ص", "د. مريم النور"),
        ("الجمعة", "جراحة", "صباحية", "8 ص - 2 ظ", "د. مريم السالم"),
        ("الجمعة", "جراحة", "مسائية", "2 ظ - 8 م", "د. مريم السالم"),
        ("الجمعة", "جراحة", "ليلية", "8 م - 8 ص", "د. سامي السالم"),
        ("الجمعة", "عظام", "صباحية", "8 ص - 2 ظ", "د. يوسف العربي"),
        ("الجمعة", "عظام", "مسائية", "2 ظ - 8 م", "د. يوسف العربي"),
        ("الجمعة", "عظام", "ليلية", "8 م - 8 ص", "د. يوسف العربي"),
        ("الجمعة", "باطنة", "صباحية", "8 ص - 2 ظ", "د. أحمد الهاشمي"),
        ("الجمعة", "باطنة", "مسائية", "2 ظ - 8 م", "د. أحمد الهاشمي"),
        ("الجمعة", "باطنة", "ليلية", "8 م - 8 ص", "د. طارق الفارسي"),

        # --- السبت ---
        ("السبت", "نساء وولادة", "صباحية", "8 ص - 2 ظ", "د. أحمد النور"),
        ("السبت", "نساء وولادة", "مسائية", "2 ظ - 8 م", "د. أحمد النور"),
        ("السبت", "نساء وولادة", "ليلية", "8 م - 8 ص", "د. محمد السالم"),
        ("السبت", "أطفال", "صباحية", "8 ص - 2 ظ", "د. علي الفارسي"),
        ("السبت", "أطفال", "مسائية", "2 ظ - 8 م", "د. يوسف السالم"),
        ("السبت", "أطفال", "ليلية", "8 م - 8 ص", "د. يوسف السالم"),
        ("السبت", "جراحة", "صباحية", "8 ص - 2 ظ", "د. يوسف النور"),
        ("السبت", "جراحة", "مسائية", "2 ظ - 8 م", "د. يوسف النور"),
        ("السبت", "جراحة", "ليلية", "8 م - 8 ص", "د. أحمد الشريف"),
        ("السبت", "عظام", "صباحية", "8 ص - 2 ظ", "د. يوسف العربي"),
        ("السبت", "عظام", "مسائية", "2 ظ - 8 م", "د. يوسف العربي"),
        ("السبت", "عظام", "ليلية", "8 م - 8 ص", "د. طارق النور"),
        ("السبت", "باطنة", "صباحية", "8 ص - 2 ظ", "د. طارق الزاوي"),
        ("السبت", "باطنة", "مسائية", "2 ظ - 8 م", "د. طارق الزاوي"),
        ("السبت", "باطنة", "ليلية", "8 م - 8 ص", "د. حسن القاضي"),
        ("السبت", "علاج طبيعي رجال", "مسائية", "2 ظ - 8 م", "م. محمد الزليطني"),
        ("السبت", "علاج طبيعي نساء", "صباحية", "8 ص - 2 ظ", "م. منى الشريف"),
        ("السبت", "علاج طبيعي نساء", "مسائية", "2 ظ - 8 م", "م. رموز الفارسي"),

        # --- الأحد ---
        ("الأحد", "نساء وولادة", "صباحية", "8 ص - 2 ظ", "د. محمد الشريف"),
        ("الأحد", "نساء وولادة", "مسائية", "2 ظ - 8 م", "د. محمد الشريف"),
        ("الأحد", "نساء وولادة", "ليلية", "8 م - 8 ص", "د. أحمد العربي"),
        ("الأحد", "أطفال", "صباحية", "8 ص - 2 ظ", "د. عمر القاضي"),
        ("الأحد", "أطفال", "مسائية", "2 ظ - 8 م", "د. عمر القاضي"),
        ("الأحد", "أطفال", "ليلية", "8 م - 8 ص", "د. مريم النور"),
        ("الأحد", "جراحة", "صباحية", "8 ص - 2 ظ", "د. ليلى النور"),
        ("الأحد", "جراحة", "مسائية", "2 ظ - 8 م", "د. ليلى النور"),
        ("الأحد", "جراحة", "ليلية", "8 م - 8 ص", "د. سارة النور"),
        ("الأحد", "عظام", "صباحية", "8 ص - 2 ظ", "د. يوسف العربي"),
        ("الأحد", "عظام", "مسائية", "2 ظ - 8 م", "د. يوسف العربي"),
        ("الأحد", "عظام", "ليلية", "8 م - 8 ص", "د. يوسف العربي"),
        ("الأحد", "باطنة", "صباحية", "8 ص - 2 ظ", "د. أحمد الهاشمي"),
        ("الأحد", "باطنة", "مسائية", "2 ظ - 8 م", "د. أحمد الهاشمي"),
        ("الأحد", "باطنة", "ليلية", "8 م - 8 ص", "د. حسن الهاشمي"),
        ("الأحد", "علاج طبيعي رجال", "مسائية", "2 ظ - 8 م", "م. نورالدين القاضي"),
        ("الأحد", "علاج طبيعي نساء", "صباحية", "8 ص - 2 ظ", "م. منى الشريف"),
        ("الأحد", "علاج طبيعي نساء", "مسائية", "2 ظ - 8 م", "م. رموز الفارسي"),

        # --- الاثنين ---
        ("الاثنين", "نساء وولادة", "صباحية", "8 ص - 2 ظ", "د. ليلى الفارسي"),
        ("الاثنين", "نساء وولادة", "مسائية", "2 ظ - 8 م", "د. ليلى الفارسي"),
        ("الاثنين", "نساء وولادة", "ليلية", "8 م - 8 ص", "د. ليلى الفارسي"),
        ("الاثنين", "أطفال", "صباحية", "8 ص - 2 ظ", "د. علي الفارسي"),
        ("الاثنين", "أطفال", "مسائية", "2 ظ - 8 م", "د. بلال النور"),
        ("الاثنين", "أطفال", "ليلية", "8 م - 8 ص", "د. بلال النور"),
        ("الاثنين", "جراحة", "صباحية", "8 ص - 2 ظ", "د. مريم الشريف"),
        ("الاثنين", "جراحة", "مسائية", "2 ظ - 8 م", "د. مريم الشريف"),
        ("الاثنين", "جراحة", "ليلية", "8 م - 8 ص", "د. مريم الشريف"),
        ("الاثنين", "عظام", "صباحية", "8 ص - 2 ظ", "د. يوسف العربي"),
        ("الاثنين", "عظام", "مسائية", "2 ظ - 8 م", "د. يوسف العربي"),
        ("الاثنين", "عظام", "ليلية", "8 م - 8 ص", "د. يوسف العربي"),
        ("الاثنين", "باطنة", "صباحية", "8 ص - 2 ظ", "د. سامي الشريف"),
        ("الاثنين", "باطنة", "مسائية", "2 ظ - 8 م", "د. سامي الشريف"),
        ("الاثنين", "باطنة", "ليلية", "8 م - 8 ص", "د. أحمد الهاشمي"),
        ("الاثنين", "علاج طبيعي رجال", "مسائية", "2 ظ - 8 م", "م. محمد الزليطني"),
        ("الاثنين", "علاج طبيعي نساء", "صباحية", "8 ص - 2 ظ", "م. منى الشريف"),
        ("الاثنين", "علاج طبيعي نساء", "مسائية", "2 ظ - 8 م", "م. رموز الفارسي"),

        # --- الثلاثاء ---
        ("الثلاثاء", "نساء وولادة", "صباحية", "8 ص - 2 ظ", "د. أحمد العربي"),
        ("الثلاثاء", "نساء وولادة", "مسائية", "2 ظ - 8 م", "د. أحمد العربي"),
        ("الثلاثاء", "نساء وولادة", "ليلية", "8 م - 8 ص", "د. أحمد العربي"),
        ("الثلاثاء", "أطفال", "صباحية", "8 ص - 2 ظ", "د. حسن السالم"),
        ("الثلاثاء", "أطفال", "مسائية", "2 ظ - 8 م", "د. حسن السالم"),
        ("الثلاثاء", "أطفال", "ليلية", "8 م - 8 ص", "د. محمد الزاوي"),
        ("الثلاثاء", "جراحة", "صباحية", "8 ص - 2 ظ", "د. حسن الفارسي"),
        ("الثلاثاء", "جراحة", "مسائية", "2 ظ - 8 م", "د. حسن الفارسي"),
        ("الثلاثاء", "جراحة", "ليلية", "8 م - 8 ص", "د. حسن الفارسي"),
        ("الثلاثاء", "عظام", "صباحية", "8 ص - 2 ظ", "د. يوسف القاضي"),
        ("الثلاثاء", "عظام", "مسائية", "2 ظ - 8 م", "د. يوسف القاضي"),
        ("الثلاثاء", "عظام", "ليلية", "8 م - 8 ص", "د. يوسف العربي"),
        ("الثلاثاء", "باطنة", "صباحية", "8 ص - 2 ظ", "د. خالد الهاشمي"),
        ("الثلاثاء", "باطنة", "مسائية", "2 ظ - 8 م", "د. خالد الهاشمي"),
        ("الثلاثاء", "باطنة", "ليلية", "8 م - 8 ص", "د. طارق الشريف"),
        ("الثلاثاء", "علاج طبيعي رجال", "مسائية", "2 ظ - 8 م", "م. نورالدين القاضي"),
        ("الثلاثاء", "علاج طبيعي نساء", "صباحية", "8 ص - 2 ظ", "م. منى الشريف"),
        ("الثلاثاء", "علاج طبيعي نساء", "مسائية", "2 ظ - 8 م", "م. رموز الفارسي"),

        # --- الأربعاء ---
        ("الأربعاء", "نساء وولادة", "صباحية", "8 ص - 2 ظ", "د. طارق العربي"),
        ("الأربعاء", "نساء وولادة", "مسائية", "2 ظ - 8 م", "د. طارق العربي"),
        ("الأربعاء", "نساء وولادة", "ليلية", "8 م - 8 ص", "د. محمد النور"),
        ("الأربعاء", "أطفال", "صباحية", "8 ص - 2 ظ", "د. يوسف السالم"),
        ("الأربعاء", "أطفال", "مسائية", "2 ظ - 8 م", "د. حسن الشريف"),
        ("الأربعاء", "أطفال", "ليلية", "8 م - 8 ص", "د. يوسف السالم"),
        ("الأربعاء", "جراحة", "صباحية", "8 ص - 2 ظ", "د. ليلى القاضي"),
        ("الأربعاء", "جراحة", "مسائية", "2 ظ - 8 م", "د. ليلى القاضي"),
        ("الأربعاء", "جراحة", "ليلية", "8 م - 8 ص", "د. سارة النور"),
        ("الأربعاء", "عظام", "صباحية", "8 ص - 2 ظ", "د. يوسف العربي"),
        ("الأربعاء", "عظام", "مسائية", "2 ظ - 8 م", "د. يوسف العربي"),
        ("الأربعاء", "عظام", "ليلية", "8 م - 8 ص", "د. يوسف العربي"),
        ("الأربعاء", "باطنة", "صباحية", "8 ص - 2 ظ", "د. محمد القاضي"),
        ("الأربعاء", "باطنة", "مسائية", "2 ظ - 8 م", "د. محمد القاضي"),
        ("الأربعاء", "باطنة", "ليلية", "8 م - 8 ص", "د. حسن القاضي"),
        ("الأربعاء", "علاج طبيعي رجال", "مسائية", "2 ظ - 8 م", "م. محمد الزليطني"),
        ("الأربعاء", "علاج طبيعي نساء", "صباحية", "8 ص - 2 ظ", "م. منى الشريف"),
        ("الأربعاء", "علاج طبيعي نساء", "مسائية", "2 ظ - 8 م", "م. رموز الفارسي"),

        # --- الخميس ---
        ("الخميس", "نساء وولادة", "صباحية", "8 ص - 2 ظ", "د. أحمد القاضي"),
        ("الخميس", "نساء وولادة", "مسائية", "2 ظ - 8 م", "د. أحمد القاضي"),
        ("الخميس", "نساء وولادة", "ليلية", "8 م - 8 ص", "د. أحمد القاضي"),
        ("الخميس", "أطفال", "صباحية", "8 ص - 2 ظ", "د. علي الفارسي"),
        ("الخميس", "أطفال", "مسائية", "2 ظ - 8 م", "د. عمر الزاوي"),
        ("الخميس", "أطفال", "ليلية", "8 م - 8 ص", "د. عمر الزاوي"),
        ("الخميس", "جراحة", "صباحية", "8 ص - 2 ظ", "د. سامي السالم"),
        ("الخميس", "جراحة", "مسائية", "2 ظ - 8 م", "د. سامي السالم"),
        ("الخميس", "جراحة", "ليلية", "8 م - 8 ص", "د. سامي السالم"),
        ("الخميس", "عظام", "صباحية", "8 ص - 2 ظ", "د. يوسف العربي"),
        ("الخميس", "عظام", "مسائية", "2 ظ - 8 م", "د. يوسف العربي"),
        ("الخميس", "عظام", "ليلية", "8 م - 8 ص", "د. يوسف العربي"),
        ("الخميس", "باطنة", "صباحية", "8 ص - 2 ظ", "د. طارق الزاوي"),
        ("الخميس", "باطنة", "مسائية", "2 ظ - 8 م", "د. طارق الزاوي"),
        ("الخميس", "باطنة", "ليلية", "8 م - 8 ص", "د. خالد الهاشمي"),
        ("الخميس", "علاج طبيعي رجال", "مسائية", "2 ظ - 8 م", "م. نورالدين القاضي"),
        ("الخميس", "علاج طبيعي نساء", "صباحية", "8 ص - 2 ظ", "م. منى الشريف"),
        ("الخميس", "علاج طبيعي نساء", "مسائية", "2 ظ - 8 م", "م. رموز الفارسي"),
    ]

    cursor.executemany(
        "INSERT INTO emergency_clinics (day_of_week, department, shift, shift_time, doctor_name) VALUES (?, ?, ?, ?, ?);",
        emergency_data
    )

    # 5. Clear and Seed Follow-up Clinics
    cursor.execute("DELETE FROM followup_clinics;")

    # Format: (day_of_week, specialty, doctor_name, shift_note)
    followup_data = [
        # --- الجمعة ---
        ("الجمعة", "النساء والولادة", "د. علي العربي", "صباحاً"),
        ("الجمعة", "النساء والولادة 1", "د. خالد الفارسي", ""),
        ("الجمعة", "العظام", "د. حسن النور", ""),
        ("الجمعة", "العيون", "د. عمر النور", ""),
        ("الجمعة", "الجراحة", "د. مريم السالم", ""),
        ("الجمعة", "الجلدية", "د. خالد النور", ""),
        ("الجمعة", "الجلدية 2", "د. ليلى السالم", ""),
        ("الجمعة", "الباطنية", "د. أحمد الهاشمي", ""),
        ("الجمعة", "الأوعية الدموية", "د. مريم الزاوي", ""),
        ("الجمعة", "المسالك", "د. عمر الشريف", ""),
        ("الجمعة", "الأطفال", "د. بلال الهاشمي", ""),
        ("الجمعة", "جراحة المخ والأعصاب", "د. أحمد الزاوي", ""),
        ("الجمعة", "الأنف والأذن والحنجرة", "د. يوسف الشريف", ""),
        ("الجمعة", "موجات فوق الصوتية (التصوير)", "د. سارة الشريف", ""),

        # --- السبت ---
        ("السبت", "النساء والولادة 1", "د. مريم العربي", "صباحاً"),
        ("السبت", "النساء والولادة 1", "د. خالد الشريف", ""),
        ("السبت", "النساء والولادة 2", "د. خالد السالم", ""),
        ("السبت", "القلب", "د. أحمد السالم", "صباحاً"),
        ("السبت", "القلب", "د. عمر العربي", ""),
        ("السبت", "الباطنية 1", "د. مريم الفارسي", "صباحاً"),
        ("السبت", "الباطنية 2", "د. طارق الزاوي", "صباحاً - مساءً"),
        ("السبت", "العظام", "د. حسن النور", ""),
        ("السبت", "الجراحة", "د. يوسف النور", ""),
        ("السبت", "الجلدية والتجميل", "د. بلال العربي", "صباحاً"),
        ("السبت", "الجلدية والتجميل", "د. خالد النور", ""),
        ("السبت", "المسالك", "د. علي السالم", ""),
        ("السبت", "التغذية العلاجية", "د. عمر الفارسي", "صباحاً"),
        ("السبت", "الأسنان 1", "د. طارق القاضي", "صباحاً - مساءً"),
        ("السبت", "الأسنان 2", "د. علي القاضي", "صباحاً - مساءً"),
        ("السبت", "أوردة وشرايين", "د. أحمد الفارسي", "صباحاً"),
        ("السبت", "المخ والأعصاب", "د. أحمد الزاوي", ""),
        ("السبت", "العيون", "د. عمر النور", ""),
        ("السبت", "العيون", "د. علي الشريف", "الساعة 02:30 ظهراً"),
        ("السبت", "الأطفال", "د. علي الهاشمي", "صباحاً"),
        ("السبت", "الأطفال", "د. يوسف الفارسي", ""),
        ("السبت", "أنف وأذن وحنجرة", "د. يوسف الشريف", ""),
        ("السبت", "موجات فوق الصوتية", "د. سارة الشريف", ""),

        # --- الأحد ---
        ("الأحد", "النساء والولادة 2", "د. ليلى الشريف", "صباحاً - مساءً"),
        ("الأحد", "النساء والولادة 2", "د. خالد السالم", ""),
        ("الأحد", "العيون", "د. عمر النور", "صباحاً"),
        ("الأحد", "العيون", "د. حسن العربي", ""),
        ("الأحد", "الأوعية الدموية", "د. سامي الهاشمي", ""),
        ("الأحد", "الجراحة", "د. يوسف النور", ""),
        ("الأحد", "العظام", "د. حسن الزاوي", ""),
        ("الأحد", "الأسنان 1", "د. بلال السالم", "صباحاً"),
        ("الأحد", "مخ وأعصاب", "د. سامي الزاوي", ""),
        ("الأحد", "الجلدية والتجميل", "د. خالد القاضي", ""),
        ("الأحد", "المسالك البولية", "د. عمر الشريف", ""),
        ("الأحد", "القلب", "د. أحمد السالم", ""),
        ("الأحد", "الأطفال 1", "د. بلال الهاشمي", ""),
        ("الأحد", "أنف وأذن وحنجرة", "د. سامي الفارسي", ""),
        ("الأحد", "موجات فوق الصوتية", "د. سارة الشريف", ""),
        ("الأحد", "التغذية العلاجية", "د. ليلى الهاشمي", ""),

        # --- الاثنين ---
        ("الاثنين", "النساء والولادة 2", "د. ليلى الشريف", "صباحاً"),
        ("الاثنين", "النساء والولادة 1", "د. محمد الفارسي", ""),
        ("الاثنين", "النساء والولادة 2", "د. مريم العربي", ""),
        ("الاثنين", "القلب", "د. أحمد السالم", "صباحاً"),
        ("الاثنين", "القلب", "د. عمر العربي", ""),
        ("الاثنين", "الباطنية", "د. مريم القاضي", "صباحاً"),
        ("الاثنين", "الباطنية", "د. طارق الزاوي", ""),
        ("الاثنين", "العظام", "د. بلال الشريف", ""),
        ("الاثنين", "موجات فوق الصوتية", "د. سارة الشريف", ""),
        ("الاثنين", "التغذية العلاجية", "د. محمد العربي", "صباحاً"),
        ("الاثنين", "الأسنان 1", "د. بلال السالم", "صباحاً + مساءً"),
        ("الاثنين", "مخ وأعصاب", "د. أحمد الزاوي", ""),
        ("الاثنين", "الجلدية والتجميل", "د. خالد النور", ""),
        ("الاثنين", "العيون", "د. سامي القاضي", ""),
        ("الاثنين", "مسالك", "د. علي النور", ""),
        ("الاثنين", "الجراحة", "د. يوسف النور", ""),
        ("الاثنين", "الأطفال 1", "د. علي الفارسي", "صباحاً"),
        ("الاثنين", "الأطفال 2", "د. يوسف الفارسي", ""),
        ("الاثنين", "أنف وأذن وحنجرة", "د. خالد الزاوي", ""),

        # --- الثلاثاء ---
        ("الثلاثاء", "النساء والولادة", "د. محمد الفارسي", "صباحاً"),
        ("الثلاثاء", "النساء والولادة", "د. علي الزاوي", "صباحاً"),
        ("الثلاثاء", "النساء والولادة", "د. محمد الهاشمي", ""),
        ("الثلاثاء", "العيون", "د. عمر النور", "صباحاً"),
        ("الثلاثاء", "العيون", "د. حسن العربي", ""),
        ("الثلاثاء", "الجراحة", "د. يوسف الهاشمي", ""),
        ("الثلاثاء", "التغذية العلاجية", "د. ليلى الزاوي", ""),
        ("الثلاثاء", "الأسنان 1", "د. بلال القاضي", "صباحاً"),
        ("الثلاثاء", "الأسنان 1", "د. طارق القاضي", "صباحاً - مساءً"),
        ("الثلاثاء", "الأسنان 2", "د. علي القاضي", "مساءً"),
        ("الثلاثاء", "موجات فوق الصوتية", "د. سارة الشريف", ""),
        ("الثلاثاء", "مخ وأعصاب", "د. سامي الزاوي", ""),
        ("الثلاثاء", "القلب", "د. عمر العربي", ""),
        ("الثلاثاء", "العظام", "د. مريم الهاشمي", ""),
        ("الثلاثاء", "المسالك", "د. سامي النور", ""),
        ("الثلاثاء", "الأطفال", "د. علي الهاشمي", ""),
        ("الثلاثاء", "الجلدية والتجميل", "د. خالد العربي", ""),
        ("الثلاثاء", "أنف وأذن وحنجرة", "د. طارق السالم", ""),

        # --- الأربعاء ---
        ("الأربعاء", "النساء والولادة 1", "د. مريم العربي", "صباحاً"),
        ("الأربعاء", "النساء والولادة 1", "د. بلال الزاوي", ""),
        ("الأربعاء", "النساء والولادة 2", "د. خالد السالم", ""),
        ("الأربعاء", "الجراحة", "د. عمر الهاشمي", ""),
        ("الأربعاء", "العظام", "د. بلال الشريف", ""),
        ("الأربعاء", "أنف وأذن وحنجرة", "د. عمر السالم", ""),
        ("الأربعاء", "المسالك", "د. طارق الهاشمي", ""),
        ("الأربعاء", "موجات فوق الصوتية", "د. سارة الشريف", ""),
        ("الأربعاء", "الأسنان 1", "د. بلال السالم", "صباحاً - مساءً"),
        ("الأربعاء", "الأسنان 1", "د. طارق القاضي", "مساءً"),
        ("الأربعاء", "مخ وأعصاب", "د. أحمد الزاوي", ""),
        ("الأربعاء", "الباطنة والكلى", "د. يوسف الزاوي", ""),
        ("الأربعاء", "القلب", "د. أحمد السالم", ""),
        ("الأربعاء", "الجلدية والتجميل", "د. خالد القاضي", ""),
        ("الأربعاء", "الأطفال", "د. علي الهاشمي", ""),
        ("الأربعاء", "العيون", "د. سامي القاضي", ""),
        ("الأربعاء", "التغذية العلاجية", "د. عمر الفارسي", "صباحاً"),

        # --- الخميس ---
        ("الخميس", "النساء والولادة 1", "د. مريم العربي", "صباحاً"),
        ("الخميس", "النساء والولادة 1", "د. خالد الفارسي", ""),
        ("الخميس", "النساء والولادة 2", "د. محمد الفارسي", ""),
        ("الخميس", "الباطنية 1", "د. طارق الزاوي", "صباحاً - مساءً"),
        ("الخميس", "أنف وأذن وحنجرة", "د. سامي العربي", ""),
        ("الخميس", "الأوعية الدموية", "د. ليلى العربي", ""),
        ("الخميس", "التغذية العلاجية", "د. عمر الفارسي", "صباحاً"),
        ("الخميس", "الأسنان 1", "د. بلال السالم", "صباحاً"),
        ("الخميس", "الأسنان 1", "د. بلال الفارسي", "صباحاً"),
        ("الخميس", "الأسنان 1", "د. طارق القاضي", "مساءً"),
        ("الخميس", "مخ وأعصاب", "د. أحمد الزاوي", ""),
        ("الخميس", "العيون", "د. علي الشريف", ""),
        ("الخميس", "العيون", "د. عمر النور", ""),
        ("الخميس", "المسالك", "د. عمر الشريف", ""),
        ("الخميس", "القلب", "د. أحمد السالم", ""),
        ("الخميس", "الجلدية والتجميل", "د. ليلى السالم", ""),
        ("الخميس", "الأطفال", "د. علي الهاشمي", ""),
        ("الخميس", "موجات فوق الصوتية", "د. سارة الشريف", ""),
    ]

    cursor.executemany(
        "INSERT INTO followup_clinics (day_of_week, specialty, doctor_name, shift_note) VALUES (?, ?, ?, ?);",
        followup_data
    )

    # 6. Also sync doctors table for legacy/simulator compatibility with distinct doctors
    cursor.execute("DELETE FROM doctors;")
    distinct_docs = set()
    for row in emergency_data:
        distinct_docs.add((row[4], row[1], f"{row[0]} ({row[2]}: {row[3]})"))
    for row in followup_data:
        note_str = f" - {row[3]}" if row[3] else ""
        distinct_docs.add((row[2], row[1], f"{row[0]}{note_str}"))

    docs_insert = []
    for doc_name, spec, sched in distinct_docs:
        # Include every column the SQLModel schema declares as NOT NULL without
        # a database-level default. The legacy schema gains these columns via
        # db.init_db() migration, so this insert works against both schemas.
        # (room_number, schedule_days, today_status, today_note, is_active)
        docs_insert.append((
            doc_name, spec, sched, "available", "", 40.0,
            "غير محدد", "السبت,الأحد,الإثنين,الثلاثاء,الأربعاء,الخميس",
            "available", "", 1,
        ))

    cursor.executemany(
        "INSERT INTO doctors (name, specialty, regular_schedule, status, daily_note, consultation_fee, room_number, schedule_days, today_status, today_note, is_active) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",
        docs_insert
    )

    # 7. Business profile row + clinic FAQs (pivot addition; the clinic
    # data above is unchanged).
    cursor.execute("DELETE FROM business_info;")
    cursor.execute(
        "INSERT INTO business_info (id, name, sector, address, map_link, support_phone, escalation_phone, working_hours, policy_notes, currency) "
        "VALUES (1, 'مصحة النور التجريبية', 'clinic', 'زليتن - شارع تجريبي', 'https://maps.google.com/?q=Zliten', "
        "'0910101010 - 0930303030', '0910101010 - 0930303030', "
        "'السبت - الخميس: 8 صباحاً - 8 مساءً، الطوارئ 24 ساعة', "
        "'الاستقبال والاستفسارات متاحة 24 ساعة، الحضور والمتابعة وفق الفترات المعلنة، والتوقيتات تقريبية تختلف باختلاف عيادات المتابعة.', 'LYD');"
    )
    cursor.execute("DELETE FROM business_faqs;")
    cursor.executemany(
        "INSERT INTO business_faqs (question, answer, keywords) VALUES (?, ?, ?);",
        CLINIC_FAQS,
    )
    # Demo Messenger staff PSIDs (demo-only placeholders).
    cursor.execute(
        "INSERT OR REPLACE INTO clinic_info (key, value) VALUES ('authorized_messenger_psids', ?);",
        (DEMO_MESSENGER_PSIDS,),
    )

    conn.commit()
    conn.close()
    print("✅ Seeded Al-Noor Demo Clinic data successfully!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed LibyAI with a fictional demo profile (all data fictional).")
    parser.add_argument(
        "--sector",
        default=os.environ.get("LIBYAI_DEMO_SECTOR", "clinic"),
        choices=list(SECTORS),
        help="Demo business sector to seed (default: clinic, or LIBYAI_DEMO_SECTOR).",
    )
    parser.add_argument("--db", default=DB_PATH, help="SQLite database path (default: DB_PATH env or clinic.db).")
    args = parser.parse_args()
    seed_demo(db_path=args.db, sector=args.sector)
