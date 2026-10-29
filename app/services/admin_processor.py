from typing import Optional
from app.config import settings, is_phone_authorized
from app.services import db_service


def is_staff_authorized(sender_phone: str) -> bool:
    """Checks whether the sender phone is in the authorized staff whitelist."""
    configs = db_service.get_clinic_configs()
    auth_str = configs.get("authorized_phones", settings.AUTHORIZED_STAFF_PHONES)
    return is_phone_authorized(sender_phone, auth_str)


def is_update_message(text: str) -> bool:
    """Detects whether text has update/admin intent."""
    triggers = [
        "@bot", "@Bot", "@بـوت", "@بوت", "اعتذر", "اعتذرت", "مش حيكون متواجد", "مش حتكون متواجدة",
        "مش جاي", "مش جاية", "غياب", "تأخير", "متأخر", "متأخرة", "حيبدأ", "حتبدأ", "كشفية", "سعر", "صار", "صارت",
        "متواجد", "حاضر", "تعديل", "تغيير", "إلغاء", "دينار", "موعد", "حضور",
        "غادر", "غادرت", "روح", "روحت", "روّح", "روّحت", "طلع", "طلعت", "كمل", "كملت", "أنهى", "أنهت", "خلص", "خلصت", "مشى",
        "وصل", "وصلت", "باشر", "قاعد توا", "قاعدة توا", "بدأ", "بدت", "استقبال", "بالعيادة",
        "اكتفى", "اكتفت", "اكتفوا", "اكتمل", "اكتملت", "قفل", "قفلوا", "وقف", "وقفوا", "توقف", "سد", "فل", "حجز",
        "تمديد", "مدد", "مددت", "مكمل", "مكملة", "دوام", "عيادة", "دكتور", "دكتورة", "تحليل", "فحص"
    ]
    return any(t in text for t in triggers)


def process_authorized_staff_message(sender_phone: str, message_text: str) -> Optional[str]:
    """
    Processes incoming message from authorized staff (private 1:1 or group @bot / @تحديث / @إدارة).
    Delegates to admin_service for unified, atomic SQLite execution.
    """
    import admin_service
    # Do NOT auto-tag untagged messages here. In a group, an untagged message
    # is casual chatter and handle_admin_group_message must return None for
    # it. Auto-tagging turned every greeting into an update attempt (and, with
    # the old substring phone check, could even appear authorized). The 1:1
    # simulator endpoint tags its own messages before calling the handler
    # directly, so no caller depends on auto-tagging here.
    return admin_service.handle_admin_group_message(sender_phone, message_text.strip())


def process_admin_group_message(sender_id: str, message_text: str) -> Optional[str]:
    """Compatibility wrapper."""
    return process_authorized_staff_message(sender_id, message_text)
