"""Model configuration and demo-default regression tests (stabilization
pass, task 5).

- settings.GEMINI_MODEL (app/config.py, default gemini-3.1-flash-lite,
  same as .env.example) heads the patient_service model fallback chain.
- The normalize_phone_digits docstring examples are correct.
- The demo staff phone list is fictional and demo-only: it is active in
  development, but in production it authorizes nobody unless staff phones
  were explicitly configured (environment variable or .env).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def test_model_cascade_head_is_settings_model():
    from app.config import settings
    import patient_service

    assert patient_service.MODELS_CASCADE[0] == settings.GEMINI_MODEL


def test_model_cascade_has_no_duplicates():
    import patient_service

    cascade = patient_service.MODELS_CASCADE
    assert len(cascade) == len(set(cascade)), f"Duplicate models in cascade: {cascade}"


def test_normalize_phone_digits_docstring_examples():
    from app.config import normalize_phone_digits

    assert normalize_phone_digits("+218 91 234 5678") == "912345678"
    assert normalize_phone_digits("0920202020") == "920202020"
    assert normalize_phone_digits("٠٩١٢٣٤٥٦٧٨") == "912345678"
    assert normalize_phone_digits("00218912345678") == "912345678"


def _fresh_settings(monkeypatch, environment, staff_phones=None):
    """Build a fresh Settings object with a controlled environment.

    The global settings object is replaced only inside is_phone_authorized's
    own module, so no other module's already-imported reference is touched.
    """
    import app.config as config_module
    from app.config import Settings

    monkeypatch.setenv("ENVIRONMENT", environment)
    if staff_phones is None:
        monkeypatch.delenv("AUTHORIZED_STAFF_PHONES", raising=False)
    else:
        monkeypatch.setenv("AUTHORIZED_STAFF_PHONES", staff_phones)
    fresh = Settings()
    monkeypatch.setattr(config_module, "settings", fresh)
    return fresh


def test_demo_staff_phones_not_active_in_production_when_unconfigured(monkeypatch):
    from app.config import is_phone_authorized

    fresh = _fresh_settings(monkeypatch, "production")
    assert "AUTHORIZED_STAFF_PHONES" not in fresh.model_fields_set
    # No database value either: both the None and empty-string paths must
    # fail closed, not fall back to the fictional demo default.
    assert not is_phone_authorized("0920202020")
    assert not is_phone_authorized("0920202020", "")


def test_demo_staff_phones_active_in_development(monkeypatch):
    from app.config import is_phone_authorized

    fresh = _fresh_settings(monkeypatch, "development")
    assert "AUTHORIZED_STAFF_PHONES" not in fresh.model_fields_set
    assert is_phone_authorized("0920202020")


def test_explicitly_configured_staff_phones_work_in_production(monkeypatch):
    from app.config import is_phone_authorized

    fresh = _fresh_settings(monkeypatch, "production", staff_phones="0915550000")
    assert "AUTHORIZED_STAFF_PHONES" in fresh.model_fields_set
    assert is_phone_authorized("0915550000")
    # The demo default is not merged in: only the configured number works.
    assert not is_phone_authorized("0920202020")
