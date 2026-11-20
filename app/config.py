import os
import re
from typing import Optional, List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "LibyAI - Smart Business Assistant"
    # Business identity. The BUSINESS_* names are the new multi-sector
    # settings; the CLINIC_* names stay as backward-compatible aliases
    # (an existing deployment that sets CLINIC_NAME keeps working).
    BUSINESS_NAME: str = os.getenv("BUSINESS_NAME", os.getenv("CLINIC_NAME", "المصحة الطبية"))
    BUSINESS_SECTOR: str = os.getenv("BUSINESS_SECTOR", "clinic")
    BUSINESS_CURRENCY: str = os.getenv("BUSINESS_CURRENCY", "LYD")
    SUPPORT_PHONE: str = os.getenv("SUPPORT_PHONE", os.getenv("RECEPTION_PHONE", "0910000000"))
    ESCALATION_PHONE: str = os.getenv("ESCALATION_PHONE", os.getenv("EMERGENCY_PHONE", "0910000000"))
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
    # No development defaults for any secret: a missing secret must fail
    # closed (webhook verification rejects, simulator admin rejects) rather
    # than silently using a value anyone who read the code would know.
    WHATSAPP_VERIFY_TOKEN: Optional[str] = None
    WHATSAPP_TOKEN: Optional[str] = None
    WHATSAPP_PHONE_NUMBER_ID: Optional[str] = None
    WHATSAPP_APP_SECRET: Optional[str] = None

    # Messenger (PRIMARY channel). Same fail-closed rule as WhatsApp:
    # no development defaults for any secret.
    MESSENGER_APP_SECRET: Optional[str] = None
    MESSENGER_VERIFY_TOKEN: Optional[str] = None
    MESSENGER_PAGE_ACCESS_TOKEN: Optional[str] = None
    MESSENGER_PAGE_ID: Optional[str] = None

    # Channels enabled for this deployment, comma-separated.
    # "messenger" runs Messenger-only (WhatsApp secrets not required);
    # "messenger,whatsapp" runs both. Unknown names are ignored.
    ENABLED_CHANNELS: str = "messenger,whatsapp"

    # Database
    DATABASE_URL: str = "sqlite:///./clinic.db"

    # Security & Administration
    ADMIN_SECRET_KEY: Optional[str] = None
    # Default to production (fail-closed). Local development via run.py
    # explicitly sets ENVIRONMENT=development before importing the app.
    ENVIRONMENT: str = "production"
    ENABLE_PROD_SIMULATOR: bool = False
    # Comma-separated CORS origins. The simulator is served same-origin, so
    # the default is local origins only; production must set this explicitly
    # to the real frontend origin(s) instead of opening to every origin.
    ALLOWED_ORIGINS: str = os.getenv(
        "ALLOWED_ORIGINS",
        "http://localhost:8000,http://127.0.0.1:8000,http://localhost:3000",
    )
    
    # Authorized Staff Phone numbers for Private 1:1 Updates (Comma-separated)
    # DEMO-ONLY DEFAULT: these three numbers are fictional placeholders
    # for local development and the simulator (they match the demo
    # defaults in app/static/app.js and the demo seed). They are NEVER
    # active in production unless staff phones are explicitly configured
    # via the AUTHORIZED_STAFF_PHONES environment variable (or .env) —
    # see is_phone_authorized, which fails closed in production when no
    # explicit configuration exists. A real deployment MUST set this to
    # the clinic's real authorized staff numbers.
    AUTHORIZED_STAFF_PHONES: str = "0920202020,0921111111,218912345678"
    BOT_TRIGGER_TAG: str = "@Bot"
    
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


# A previously published development default value. It must never be
# accepted as a production secret on any channel.
DEV_DEFAULT_APP_SECRET = "dev_meta_app_secret_libyai_2026"

KNOWN_CHANNELS = ("messenger", "whatsapp")


def enabled_channels(s: Settings = None) -> List[str]:
    """Parses ENABLED_CHANNELS into a deduplicated list of known channels,
    preserving the configured order. Unknown names are ignored."""
    cfg = s or settings
    seen = set()
    out = []
    for raw in (cfg.ENABLED_CHANNELS or "").split(","):
        name = raw.strip().lower()
        if name in KNOWN_CHANNELS and name not in seen:
            seen.add(name)
            out.append(name)
    return out


def validate_production_security(s: Settings = None) -> None:
    """
    Enforces fail-closed startup behavior in production.
    Raises RuntimeError if ENVIRONMENT is production and:
    - no channel is enabled, or
    - any enabled channel's Meta app secret is missing, blank, or using
      a previously published development default.
    A missing ADMIN_SECRET_KEY or verify token is not a startup error
    by design: those endpoints fail closed on their own (webhook
    verification rejects, simulator admin rejects), so a production
    deploy without them simply cannot verify webhooks or use simulator
    admin. WhatsApp secrets are only required when WhatsApp is enabled,
    so a Messenger-only deployment boots cleanly without WHATSAPP_*.
    """
    cfg = s or settings
    if cfg.ENVIRONMENT.strip().lower() == "production":
        channels = enabled_channels(cfg)
        if not channels:
            raise RuntimeError(
                "CRITICAL SECURITY CONFIGURATION ERROR: Application cannot start in production "
                "with no channel enabled. Set ENABLED_CHANNELS to at least one of "
                "'messenger' or 'whatsapp'."
            )
        channel_secrets = {
            "messenger": cfg.MESSENGER_APP_SECRET,
            "whatsapp": cfg.WHATSAPP_APP_SECRET,
        }
        for channel in channels:
            secret = (channel_secrets.get(channel) or "").strip()
            if not secret or secret == DEV_DEFAULT_APP_SECRET:
                secret_name = (
                    "MESSENGER_APP_SECRET" if channel == "messenger"
                    else "WHATSAPP_APP_SECRET"
                )
                raise RuntimeError(
                    "CRITICAL SECURITY CONFIGURATION ERROR: Application cannot start in production "
                    f"with missing, blank, or development default {secret_name} "
                    f"(channel '{channel}' is enabled). "
                    f"Configure a strong server-side {secret_name}."
                )


settings = Settings()


def normalize_phone_digits(phone: str) -> str:
    """
    Normalizes a phone number to its core significant digits.
    Supports Eastern Arabic digits (٠-٩), strips +, 00, international code 218,
    leading zeroes, spaces, and punctuation.
    Example:
      '+218 91 234 5678' -> '912345678'
      '0920202020' -> '920202020'
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

    # Use database / runtime value if available. When no database value
    # is configured, the settings default applies — EXCEPT in production
    # when staff phones were never explicitly configured: the settings
    # default is a fictional demo-only list, and it must never authorize
    # anyone in production. model_fields_set tells us whether the value
    # came from the environment / .env / explicit init (configured) or
    # from the hardcoded default (unconfigured).
    if authorized_phones_str is not None and authorized_phones_str.strip() != "":
        auth_source = authorized_phones_str
    elif settings.ENVIRONMENT.strip().lower() == "production" and "AUTHORIZED_STAFF_PHONES" not in settings.model_fields_set:
        return False
    else:
        auth_source = settings.AUTHORIZED_STAFF_PHONES

    # No wildcard support: a configured value of "*", "all", or similar used
    # to authorize every sender, so a single misconfiguration removed all
    # staff authorization. Such a value now matches no one.
    if auth_source.strip() in ["*", "all", "الكل"]:
        return False

    # Split by any separator: commas (English & Arabic), semicolons, spaces, newlines, pipes
    items = [item.strip() for item in re.split(r"[,،;؛\s\n\r|/]+", auth_source) if item.strip()]

    for item in items:
        allowed_core = normalize_phone_digits(item)
        # Strict exact match on normalized phone digits
        if allowed_core and sender_core == allowed_core:
            return True

    return False

