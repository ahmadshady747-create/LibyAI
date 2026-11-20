# Test environment for LibyAI.
#
# The app now defaults to production (fail-closed). Tests are local
# development runs, so they must opt into development explicitly *before*
# any app module is imported, and provide test-only secrets. These values
# are for tests only and must never be used in a real deployment.
import os

os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("ADMIN_SECRET_KEY", "test-admin-key-for-tests-only")
os.environ.setdefault("WHATSAPP_APP_SECRET", "test-app-secret-for-tests-only")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test-verify-token-for-tests-only")
os.environ.setdefault("MESSENGER_APP_SECRET", "test-messenger-secret-for-tests-only")
os.environ.setdefault("MESSENGER_VERIFY_TOKEN", "test-messenger-verify-for-tests-only")
os.environ.setdefault("MESSENGER_PAGE_ACCESS_TOKEN", "test-messenger-page-token-for-tests-only")
