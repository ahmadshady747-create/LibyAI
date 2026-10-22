import os
import sys
import asyncio
import pytest

# Force UTF-8 on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

BASE_DIR = r"C:\Users\awsat\Desktop\LibyAI"
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from app.config import settings, validate_production_security
from app.main import app, lifespan

print("=== STARTING P0-A FAIL-CLOSED PRODUCTION STARTUP TESTS ===")

orig_env = settings.ENVIRONMENT
orig_secret = settings.WHATSAPP_APP_SECRET

def run_lifespan_test():
    async def _runner():
        async with lifespan(app):
            pass
    asyncio.run(_runner())

try:
    # 1. Test missing secret (None) in production
    print("--- 1. Testing Missing Secret (None) in Production ---")
    settings.ENVIRONMENT = "production"
    settings.WHATSAPP_APP_SECRET = None
    try:
        run_lifespan_test()
        assert False, "Expected RuntimeError when WHATSAPP_APP_SECRET is None in production!"
    except RuntimeError as e:
        assert "CRITICAL SECURITY CONFIGURATION ERROR" in str(e)
        print("✅ Correctly aborted startup with RuntimeError for missing (None) secret!")

    # 2. Test blank secret ("") in production
    print("--- 2. Testing Blank Secret in Production ---")
    settings.ENVIRONMENT = "production"
    settings.WHATSAPP_APP_SECRET = "   "
    try:
        run_lifespan_test()
        assert False, "Expected RuntimeError when WHATSAPP_APP_SECRET is blank in production!"
    except RuntimeError as e:
        assert "CRITICAL SECURITY CONFIGURATION ERROR" in str(e)
        print("✅ Correctly aborted startup with RuntimeError for blank secret!")

    # 3. Test development default secret in production
    print("--- 3. Testing Development Default Secret in Production ---")
    settings.ENVIRONMENT = "production"
    settings.WHATSAPP_APP_SECRET = "dev_meta_app_secret_libyai_2026"
    try:
        run_lifespan_test()
        assert False, "Expected RuntimeError when WHATSAPP_APP_SECRET is dev default in production!"
    except RuntimeError as e:
        assert "CRITICAL SECURITY CONFIGURATION ERROR" in str(e)
        print("✅ Correctly aborted startup with RuntimeError for development default secret!")

    # 4. Test valid production secret in production
    print("--- 4. Testing Valid Configured Secret in Production ---")
    settings.ENVIRONMENT = "production"
    settings.WHATSAPP_APP_SECRET = "prod_meta_super_secret_key_998877"
    # Should not raise exception
    run_lifespan_test()
    print("✅ Startup succeeded cleanly in production with valid configured secret!")

    # 5. Test development environment with default secret
    print("--- 5. Testing Development Environment with Default Secret ---")
    settings.ENVIRONMENT = "development"
    settings.WHATSAPP_APP_SECRET = "dev_meta_app_secret_libyai_2026"
    run_lifespan_test()
    print("✅ Startup succeeded in development with default secret!")

finally:
    settings.ENVIRONMENT = orig_env
    settings.WHATSAPP_APP_SECRET = orig_secret

print("🎉 ALL P0-A FAIL-CLOSED TESTS PASSED 100%! 🎉")
