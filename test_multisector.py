"""Multi-sector tests (Messenger-first pivot).

Every test runs against its own temporary SQLite database seeded with a
fictional demo profile (seed_demo.py --sector ...), never the shared
clinic.db. Covers: catalog queries grounded in live DB data with LYD
pricing, commercial human handoff across sectors, medical triage
activating ONLY for medical sectors, atomic admin catalog updates with
audit logging, channel-scoped conversation history, and Messenger PSID
staff authorization.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest

import admin_service
import customer_service
import db
import guardrails
import seed_demo

STAFF_PHONE = "0920202020"
STAFF_PSID = "demo_psid_staff_1"


@pytest.fixture
def retail_db(tmp_path):
    path = str(tmp_path / "retail.db")
    db.init_db(path)
    seed_demo.seed_demo(path, sector="retail")
    return path


@pytest.fixture
def restaurant_db(tmp_path):
    path = str(tmp_path / "restaurant.db")
    db.init_db(path)
    seed_demo.seed_demo(path, sector="restaurant")
    return path


@pytest.fixture
def workshop_db(tmp_path):
    path = str(tmp_path / "workshop.db")
    db.init_db(path)
    seed_demo.seed_demo(path, sector="workshop")
    return path


@pytest.fixture
def pharmacy_db(tmp_path):
    path = str(tmp_path / "pharmacy.db")
    db.init_db(path)
    seed_demo.seed_demo(path, sector="pharmacy")
    return path


@pytest.fixture
def clinic_db(tmp_path):
    path = str(tmp_path / "clinic.db")
    db.init_db(path)
    seed_demo.seed_demo(path, sector="clinic")
    return path


# -------------------------------------------------------------------
# Catalog queries grounded in live DB data, LYD pricing
# -------------------------------------------------------------------
def test_retail_catalog_price_query_grounded_in_db(retail_db):
    reply = customer_service.handle_customer_query(
        "psid_customer_1", "بكم شاشة سامسونج؟",
        channel="messenger", db_path=retail_db,
    )
    assert "2450" in reply
    assert "د.ل" in reply
    assert "شاشة سامسونج" in reply


def test_retail_catalog_price_query_with_definite_article(retail_db):
    # "الشاشة" (with ال) must still match the "شاشة" item.
    reply = customer_service.handle_customer_query(
        "psid_customer_1", "بكم الشاشة؟",
        channel="messenger", db_path=retail_db,
    )
    assert "2450" in reply
    assert "د.ل" in reply


def test_retail_out_of_stock_item_says_unavailable(retail_db):
    reply = customer_service.handle_customer_query(
        "psid_customer_1", "هل المكنسة متوفرة؟",
        channel="messenger", db_path=retail_db,
    )
    assert "مكنسة" in reply
    assert "غير متوفر" in reply


def test_restaurant_menu_price_query_grounded_in_db(restaurant_db):
    reply = customer_service.handle_customer_query(
        "psid_customer_2", "بكم شاورما الدجاج؟",
        channel="messenger", db_path=restaurant_db,
    )
    assert "18" in reply
    assert "د.ل" in reply
    assert "شاورما دجاج" in reply


def test_restaurant_delivery_faq_answered(restaurant_db):
    reply = customer_service.handle_customer_query(
        "psid_customer_2", "هل يوجد توصيل؟",
        channel="messenger", db_path=restaurant_db,
    )
    assert "10 د.ل" in reply


def test_workshop_service_price_and_resource(workshop_db):
    reply = customer_service.handle_customer_query(
        "psid_customer_3", "بكم تغيير زيت المحرك؟",
        channel="messenger", db_path=workshop_db,
    )
    assert "120" in reply
    assert "د.ل" in reply


def test_catalog_answer_reflects_live_price_change(retail_db):
    # Change the price in the DB; the next answer must use the new price,
    # proving the reply is grounded in live data, not a cached prompt.
    item = db.find_catalog_item_fuzzy("شاشة سامسونج", db_path=retail_db)
    db.apply_admin_mutation_atomic(
        mutation_type="catalog_item",
        target_id=item["id"],
        mutation_fields={"price_lyd": 2600.0},
        audit_sender=STAFF_PHONE,
        raw_message="@Bot سعر الشاشة صار 2600",
        confirmation_text="تم",
        db_path=retail_db,
    )
    reply = customer_service.handle_customer_query(
        "psid_customer_1", "بكم شاشة سامسونج؟",
        channel="messenger", db_path=retail_db,
    )
    assert "2600" in reply
    assert "2450" not in reply


# -------------------------------------------------------------------
# Commercial human handoff — all sectors
# -------------------------------------------------------------------
def test_handoff_on_explicit_human_request(retail_db):
    reply = customer_service.handle_customer_query(
        "psid_customer_1", "نبي نكلم المدير لو سمحت",
        channel="messenger", db_path=retail_db,
    )
    assert "0910202020" in reply  # escalation phone from business_info


def test_handoff_on_angry_complaint(restaurant_db):
    reply = customer_service.handle_customer_query(
        "psid_customer_2", "أنا غاضب جداً، الأكل وصل بارد والخدمة سيئة",
        channel="messenger", db_path=restaurant_db,
    )
    assert "0910303030" in reply


def test_handoff_on_refund_dispute(retail_db):
    reply = customer_service.handle_customer_query(
        "psid_customer_1", "نبي نرجع فلوسي، المنتج طلع معطل",
        channel="messenger", db_path=retail_db,
    )
    assert "0910202020" in reply


def test_handoff_is_audit_logged(retail_db):
    customer_service.handle_customer_query(
        "psid_customer_1", "نبي نكلم إنسان مش بوت",
        channel="messenger", db_path=retail_db,
    )
    with db.get_db(retail_db) as conn:
        row = conn.execute(
            "SELECT * FROM audit_logs WHERE admin_sender = 'guardrails:handoff' "
            "ORDER BY id DESC LIMIT 1;"
        ).fetchone()
    assert row is not None


def test_handoff_detected_by_guardrails_engine_directly():
    profile = {"sector": "retail", "escalation_phone": "0910202020",
               "name": "متجر تجريبي", "is_medical": False}
    result = guardrails.evaluate_guardrails("أريد التكلم مع موظف", profile)
    assert result.needs_handoff is True
    assert result.immediate_response is not None
    assert "0910202020" in result.immediate_response


# -------------------------------------------------------------------
# Medical triage: ONLY for medical sectors
# -------------------------------------------------------------------
def test_emergency_directive_fires_for_clinic(clinic_db):
    reply = customer_service.handle_customer_query(
        "0917770001", "عندي ألم شديد بالصدر وضيق تنفس حاد!",
        channel="whatsapp", db_path=clinic_db,
    )
    assert "طوارئ" in reply or "عاجل" in reply


def test_emergency_directive_does_not_fire_for_retail(retail_db):
    reply = customer_service.handle_customer_query(
        "psid_customer_1", "عندي ألم شديد بالصدر وضيق تنفس حاد!",
        channel="messenger", db_path=retail_db,
    )
    assert "طوارئ" not in reply
    assert "الإسعاف" not in reply


def test_clinical_advice_refusal_fires_for_pharmacy(pharmacy_db):
    reply = customer_service.handle_customer_query(
        "psid_customer_4", "شن نعطي ولدي دواء يخفض الحرارة؟",
        channel="messenger", db_path=pharmacy_db,
    )
    assert any(w in reply for w in ["يمنع", "لا يمكننا", "لا يمكنني", "وصف"])


def test_clinical_advice_refusal_does_not_fire_for_restaurant(restaurant_db):
    reply = customer_service.handle_customer_query(
        "psid_customer_2", "شن نعطي ولدي دواء يخفض الحرارة؟",
        channel="messenger", db_path=restaurant_db,
    )
    assert "يمنع" not in reply
    assert "وصف أي أدوية" not in reply


def test_guardrails_sector_gate_directly():
    clinic_profile = {"sector": "clinic", "name": "مصحة", "is_medical": True}
    retail_profile = {"sector": "retail", "name": "متجر", "is_medical": False}
    assert guardrails.is_medical_sector(clinic_profile) is True
    assert guardrails.is_medical_sector({"sector": "pharmacy"}) is True
    assert guardrails.is_medical_sector(retail_profile) is False
    assert guardrails.is_medical_sector({"sector": "restaurant"}) is False
    assert guardrails.is_medical_sector({"sector": "workshop"}) is False


# -------------------------------------------------------------------
# Atomic admin updates for catalog + business info, with audit logs
# -------------------------------------------------------------------
def test_admin_catalog_price_update_atomic_with_receipt(retail_db):
    reply = admin_service.handle_admin_group_message(
        sender_phone=STAFF_PHONE,
        raw_message="@Bot سعر الشاشة صار 2600 دينار",
        group_id="test_staff",
        db_path=retail_db,
        channel="whatsapp",
    )
    assert "إيصال تعديل سعر الصنف" in reply
    assert "2600" in reply
    item = db.find_catalog_item_fuzzy("شاشة سامسونج", db_path=retail_db)
    assert item["price_lyd"] == 2600.0
    with db.get_db(retail_db) as conn:
        row = conn.execute(
            "SELECT * FROM audit_logs ORDER BY id DESC LIMIT 1;"
        ).fetchone()
    assert row is not None
    assert STAFF_PHONE in row["admin_sender"]


def test_admin_catalog_availability_update(retail_db):
    reply = admin_service.handle_admin_group_message(
        sender_phone=STAFF_PHONE,
        raw_message="@Bot المكنسة الكهربائية نفذت",
        group_id="test_staff",
        db_path=retail_db,
        channel="whatsapp",
    )
    assert "إيصال تعديل توفر الصنف" in reply
    assert "غير متوفر" in reply
    item = db.find_catalog_item_fuzzy("مكنسة كهربائية", db_path=retail_db)
    assert not item["is_available"]


def test_admin_working_hours_update(retail_db):
    reply = admin_service.handle_admin_group_message(
        sender_phone=STAFF_PHONE,
        raw_message="@Bot ساعات العمل صارت من 9 صباحاً حتى 10 مساءً",
        group_id="test_staff",
        db_path=retail_db,
        channel="whatsapp",
    )
    assert "إيصال تعديل ساعات العمل" in reply
    profile = db.get_business_profile(retail_db)
    assert "10 مساءً" in profile["working_hours"]


def test_admin_resource_schedule_update(workshop_db):
    reply = admin_service.handle_admin_group_message(
        sender_phone=STAFF_PHONE,
        raw_message="@Bot دوام فني الميكانيكا صار من 8 صباحاً حتى 6 مساءً",
        group_id="test_staff",
        db_path=workshop_db,
        channel="whatsapp",
    )
    assert "إيصال تعديل جدول المورد" in reply
    res = db.find_resource_fuzzy("سالم بن عيسى", db_path=workshop_db)
    assert "6 مساءً" in res["schedule"]


def test_admin_catalog_price_rejects_negative(retail_db):
    reply = admin_service.handle_admin_group_message(
        sender_phone=STAFF_PHONE,
        raw_message="@Bot سعر الشاشة صار -50 دينار",
        group_id="test_staff",
        db_path=retail_db,
        channel="whatsapp",
    )
    assert "تعذر" in reply or "غير منطقي" in reply
    item = db.find_catalog_item_fuzzy("شاشة سامسونج", db_path=retail_db)
    assert item["price_lyd"] == 2450.0


def test_admin_unauthorized_sender_rejected(retail_db):
    reply = admin_service.handle_admin_group_message(
        sender_phone="0919999999",
        raw_message="@Bot سعر الشاشة صار 2600 دينار",
        group_id="test_staff",
        db_path=retail_db,
        channel="whatsapp",
    )
    assert "غير مصرح" in reply
    item = db.find_catalog_item_fuzzy("شاشة سامسونج", db_path=retail_db)
    assert item["price_lyd"] == 2450.0


# -------------------------------------------------------------------
# Messenger PSID staff authorization
# -------------------------------------------------------------------
def test_messenger_psid_staff_authorized(retail_db):
    authorized, _role, _name = db.is_sender_authorized(
        STAFF_PSID, channel="messenger", db_path=retail_db
    )
    assert authorized is True


def test_messenger_psid_staff_can_update_catalog(retail_db):
    reply = admin_service.handle_admin_group_message(
        sender_phone=STAFF_PSID,
        raw_message="@Bot سعر الشاشة صار 2700 دينار",
        group_id="messenger_staff",
        db_path=retail_db,
        channel="messenger",
    )
    assert "إيصال تعديل سعر الصنف" in reply
    item = db.find_catalog_item_fuzzy("شاشة سامسونج", db_path=retail_db)
    assert item["price_lyd"] == 2700.0


def test_messenger_psid_never_phone_normalized(retail_db):
    # A PSID that happens to contain digits must NOT match a phone-based
    # staff entry by normalization, and a phone number must NOT match a
    # PSID entry on the Messenger channel.
    authorized, _, _ = db.is_sender_authorized(
        "0910202020", channel="messenger", db_path=retail_db
    )
    assert authorized is False
    # A PSID differing by even one character must not match.
    authorized, _, _ = db.is_sender_authorized(
        "demo_psid_staff_1x", channel="messenger", db_path=retail_db
    )
    assert authorized is False


def test_whatsapp_phone_not_authorized_as_psid(retail_db):
    authorized, _, _ = db.is_sender_authorized(
        STAFF_PSID, channel="whatsapp", db_path=retail_db
    )
    assert authorized is False


# -------------------------------------------------------------------
# Channel-scoped conversation history
# -------------------------------------------------------------------
def test_same_sender_history_scoped_by_channel(retail_db):
    sender = "shared_sender_1"
    customer_service.handle_customer_query(
        sender, "بكم الشاشة؟", channel="messenger", db_path=retail_db
    )
    customer_service.handle_customer_query(
        sender, "بكم الثلاجة؟", channel="whatsapp", db_path=retail_db
    )
    messenger_turns = db.get_conversation_history(
        sender, db_path=retail_db, channel="messenger"
    )
    whatsapp_turns = db.get_conversation_history(
        sender, db_path=retail_db, channel="whatsapp"
    )
    messenger_texts = " ".join(t["text"] for t in messenger_turns)
    whatsapp_texts = " ".join(t["text"] for t in whatsapp_turns)
    assert "شاشة" in messenger_texts
    assert "ثلاجة" not in messenger_texts
    assert "ثلاجة" in whatsapp_texts
    assert "شاشة" not in whatsapp_texts


# -------------------------------------------------------------------
# Seed profiles
# -------------------------------------------------------------------
def test_seed_profiles_have_business_info_and_catalog(retail_db, restaurant_db,
                                                      workshop_db, pharmacy_db):
    for path, sector in [
        (retail_db, "retail"),
        (restaurant_db, "restaurant"),
        (workshop_db, "workshop"),
        (pharmacy_db, "pharmacy"),
    ]:
        profile = db.get_business_profile(path)
        assert profile["sector"] == sector
        assert profile["currency"] == "LYD"
        assert len(db.get_catalog_items(db_path=path)) >= 6
        assert len(db.get_business_faqs(db_path=path)) >= 3


def test_seed_clinic_profile_keeps_doctors_and_adds_business_info(clinic_db):
    doctors = db.get_all_doctors(db_path=clinic_db)
    assert len(doctors) > 50
    profile = db.get_business_profile(clinic_db)
    assert profile["sector"] == "clinic"
    assert profile["name"] == "مصحة النور التجريبية"
    assert len(db.get_business_faqs(db_path=clinic_db)) >= 3


def test_seed_unknown_sector_raises(tmp_path):
    with pytest.raises(ValueError, match="Unknown demo sector"):
        seed_demo.seed_demo(str(tmp_path / "bad.db"), sector="spaceship")
