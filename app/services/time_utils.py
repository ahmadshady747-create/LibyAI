from datetime import datetime
from typing import Dict, Any, Optional
from zoneinfo import ZoneInfo

# Libya Standard Timezone (Africa/Tripoli - UTC+2)
LIBYA_TZ = ZoneInfo("Africa/Tripoli")

ARABIC_DAYS = {
    0: "الإثنين",
    1: "الثلاثاء",
    2: "الأربعاء",
    3: "الخميس",
    4: "الجمعة",
    5: "السبت",
    6: "الأحد",
}

ARABIC_MONTHS = {
    1: "يناير",
    2: "فبراير",
    3: "مارس",
    4: "أبريل",
    5: "مايو",
    6: "يونيو",
    7: "يوليو",
    8: "أغسطس",
    9: "سبتمبر",
    10: "أكتوبر",
    11: "نوفمبر",
    12: "ديسمبر",
}


def get_libya_now() -> datetime:
    """Returns the current datetime in Libya timezone (Tripoli / UTC+2)."""
    return datetime.now(LIBYA_TZ)


def format_libya_time_arabic(dt: Optional[datetime] = None) -> str:
    """Formats time nicely in Arabic 12-hour format with صباحاً / مساءً."""
    if dt is None:
        dt = get_libya_now()
    hour = dt.hour
    minute = dt.minute
    period = "صباحاً" if hour < 12 else "مساءً"
    h12 = hour if 1 <= hour <= 12 else (hour - 12 if hour > 12 else 12)
    return f"{h12:02d}:{minute:02d} {period}"


def format_libya_date_arabic(dt: Optional[datetime] = None) -> str:
    """Formats full Arabic date, e.g. 'الثلاثاء 13 أكتوبر 2026'."""
    if dt is None:
        dt = get_libya_now()
    day_name = ARABIC_DAYS.get(dt.weekday(), "")
    month_name = ARABIC_MONTHS.get(dt.month, "")
    return f"{day_name} {dt.day} {month_name} {dt.year}"


def get_libya_datetime_context() -> Dict[str, str]:
    """
    Returns rich Libya datetime context for injection into LLM prompts and API responses.
    """
    now = get_libya_now()
    day_name = ARABIC_DAYS.get(now.weekday(), "")
    time_arabic = format_libya_time_arabic(now)
    date_arabic = format_libya_date_arabic(now)
    time_24 = now.strftime("%H:%M")

    return {
        "day_name": day_name,
        "date_arabic": date_arabic,
        "time_arabic": time_arabic,
        "time_24": time_24,
        "iso_timestamp": now.isoformat(),
        "summary": f"اليوم: {day_name} ({now.day}/{now.month}/{now.year}) | التوقيت الآن في ليبيا (طرابلس): {time_arabic} (الساعة {time_24} بنظام 24 ساعة)"
    }
