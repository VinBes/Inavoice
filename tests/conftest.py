import os
import pathlib
import sys

# Make src/ importable without installing the package
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "src"))

# Provide dummy env vars so config.py loads without a real .env
_DEFAULTS = {
    "TELEGRAM_BOT_TOKEN": "test-token",
    "ALLOWED_CHAT_IDS": "123456789",
    "ANTHROPIC_API_KEY": "test-anthropic-key",
    "RESEND_API_KEY": "test-resend-key",
    "RESEND_WEBHOOK_SECRET": "whsec_dGVzdHNlY3JldA==",  # base64("testsecret")
    "EMAIL_FROM_ADDRESS": "invoice@example.com",
    "SUPABASE_URL": "https://test.supabase.co",
    "SUPABASE_SERVICE_KEY": "test-service-key",
    "SENDER_NAME": "Test Sender",
    "SENDER_COMPANY": "Test Company",
    "SENDER_ADDRESS": "Test Address, Test City",
    "ACCOUNT_HOLDER": "Test Holder",
    "BANK_NAME": "Test Bank",
    "BANK_CODE": "000",
    "BANK_ACCOUNT": "000-000000-0",
    "FPS_ID": "test@fps",
    "BUSINESS_REGISTRATION": "TEST-BR-0001",
    "MOCK_MODE": "true",
    "TIMEZONE": "Asia/Hong_Kong",
    "DEPLOY_ENV": "test",
}

for key, value in _DEFAULTS.items():
    os.environ.setdefault(key, value)
