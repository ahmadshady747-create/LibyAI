import os
import re
from typing import Optional, List
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    PROJECT_NAME: str = "LibyAI - Smart Reception Bot"
    CLINIC_NAME: str = os.getenv("CLINIC_NAME", "المصحة الطبية")
    CLINIC_TYPE: str = os.getenv("CLINIC_TYPE", "مصحة")
    CLINIC_ADDRESS: str = os.getenv("CLINIC_ADDRESS", "ليبيا")
    CLINIC_MAP_LINK: str = os.getenv("CLINIC_MAP_LINK", "")
    EMERGENCY_PHONE: str = os.getenv("EMERGENCY_PHONE", "0910000000")
    RECEPTION_PHONE: str = os.getenv("RECEPTION_PHONE", "0910000000")
    BOOKING_POLICY: str = os.getenv("BOOKING_POLICY", "الاستفسار والخدمات متاحة خلال فترات الدوام المعلنة، والحضور أو الحجز عبر مكتب الاستقبال.")
    
    # AI / LLM Configuration
    GEMINI_API_KEY: Optional[str] = None
    GEMINI_MODEL: str = "gemini-3.1-flash-lite"
    
    # WhatsApp Webhook Verification & Security
    WHATSAPP_VERIFY_TOKEN: str = "LIBYAI_CLINIC_VERIFY_TOKEN_2026"
    WHATSAPP_TOKEN: Optional[str] = None
    WHATSAPP_PHONE_NUMBER_ID: Optional[str] = None
    WHATSAPP_APP_SECRET: Optional[str] = "dev_meta_app_secret_libyai_2026"
    
    # Database
    DATABASE_URL: str = "sqlite:///./clinic.db"
    
    # Security & Administration
    ADMIN_SECRET_KEY: str = "libyai_admin_secret_2026"
    ENVIRONMENT: str = "development"
    ENABLE_PROD_SIMULATOR: bool = False
    
    # Authorized Staff Phone numbers for Private 1:1 Updates (Comma-separated)
    AUTHORIZED_STAFF_PHONES: str = "0912345678,0921111111,218912345678"
    BOT_TRIGGER_TAG: str = "@Bot"
    
    class Config:
        env_file = ".env"
        extra = "ignore"


def validate_production_security(s: Settings = None) -> None:
    """
    Enforces fail-closed startup behavior in production.
    Raises RuntimeError if ENVIRONMENT is production and WHATSAPP_APP_SECRET
    is missing, blank, or using the development default.
    """
    cfg = s or settings
    if cfg.ENVIRONMENT.strip().lower() == "production":
        secret = (cfg.WHATSAPP_APP_SECRET or "").strip()
        if not secret or secret == "dev_meta_app_secret_libyai_2026":
            raise RuntimeError(
                "CRITICAL SECURITY CONFIGURATION ERROR: Application cannot start in production "
                "with missing, blank, or development default WHATSAPP_APP_SECRET. "
                "Configure a strong server-side WHATSAPP_APP_SECRET."
            )


settings = Settings()


def normalize_phone_digits(phone: str) -> str:
    """
    Normalizes a phone number to its core significant digits.
    Supports Eastern Arabic digits (٠-٩), strips +, 00, international code 218,
    leading zeroes, spaces, and punctuation.
    Example:
      '+218 91 234 5678' -> '912345678'
      '0912345678' -> '912345678'
      '٠٩١٢٣٤٥٦٧٨' -> '912345678'
      '00218912345678' -> '912345678'
    """
    if not phone:
        return ""
    # Convert Eastern Arabic digits to standard ASCII digits
    arabic_to_ascii = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
    clean = str(phone).translate(arabic_to_ascii)
    digits = "".join(filter(str.isdigit, clean))

    # Strip international prefix 00 (e.g. 00218...)
    if digits.startswith("00"):
        digits = digits[2:]

    # Strip country code 218 for Libya if present
    if digits.startswith("218") and len(digits) >= 9:
        digits = digits[3:]

    # Strip leading zero if present (e.g. 091... -> 91...)
    while digits.startswith("0") and len(digits) > 7:
        digits = digits[1:]

    return digits


def is_phone_authorized(phone: str, authorized_phones_str: Optional[str] = None) -> bool:
    """
    Checks if sender phone number matches any authorized staff member.
    Enforces strict full-number normalization without insecure substring or role alias matching.
    """
    if not phone:
        return False

    sender_core = normalize_phone_digits(str(phone))
    if not sender_core:
        return False

    # Use database / runtime value if available
    auth_source = authorized_phones_str if (authorized_phones_str is not None and authorized_phones_str.strip() != "") else settings.AUTHORIZED_STAFF_PHONES

    # Explicit full wildcard support if configured
    if auth_source.strip() in ["*", "all", "الكل"]:
        return True

    # Split by any separator: commas (English & Arabic), semicolons, spaces, newlines, pipes
    items = [item.strip() for item in re.split(r"[,،;؛\s\n\r|/]+", auth_source) if item.strip()]

    for item in items:
        allowed_core = normalize_phone_digits(item)
        # Strict exact match on normalized phone digits
        if allowed_core and sender_core == allowed_core:
            return True

    return False

