import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ALLOWED_CHAT_IDS = [int(x) for x in os.getenv("ALLOWED_CHAT_IDS", "").split(",") if x.strip()]
if not ALLOWED_CHAT_IDS:
    raise RuntimeError(
        "ALLOWED_CHAT_IDS is empty or unset — the bot would silently reject "
        "all messages. Set ALLOWED_CHAT_IDS to a comma-separated list of "
        "Telegram chat IDs in the environment."
    )

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

RESEND_API_KEY = os.environ["RESEND_API_KEY"]
RESEND_WEBHOOK_SECRET = os.environ["RESEND_WEBHOOK_SECRET"]
EMAIL_FROM_ADDRESS = os.getenv("EMAIL_FROM_ADDRESS", "invoice@zaraffa.online")

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_KEY = os.environ["SUPABASE_SERVICE_KEY"]

SENDER_NAME = os.environ["SENDER_NAME"]
SENDER_ADDRESS = os.environ["SENDER_ADDRESS"]
ACCOUNT_HOLDER = os.environ["ACCOUNT_HOLDER"]
BANK_NAME = os.environ["BANK_NAME"]
BANK_CODE = os.environ["BANK_CODE"]
BANK_ACCOUNT = os.environ["BANK_ACCOUNT"]
FPS_ID = os.environ["FPS_ID"]
BUSINESS_REGISTRATION = os.getenv("BUSINESS_REGISTRATION", "")

LOGO_PATH = os.getenv("LOGO_PATH", "assets/vence-zaraffa-logo.png")

DAILY_CLAUDE_API_CAP = int(os.getenv("DAILY_CLAUDE_API_CAP", "20"))
SESSION_LLM_CALL_CAP = int(os.getenv("SESSION_LLM_CALL_CAP", "5"))
MONTHLY_COST_ALERT_THRESHOLD = float(os.getenv("MONTHLY_COST_ALERT_THRESHOLD", "5"))

TIMEZONE = os.getenv("TIMEZONE", "Asia/Hong_Kong")
SESSION_TIMEOUT_MINUTES = int(os.getenv("SESSION_TIMEOUT_MINUTES", "30"))

HEALTH_PORT = int(os.getenv("HEALTH_PORT", "8080"))

MOCK_MODE = os.getenv("MOCK_MODE", "false").lower() == "true"

# Deployment environment label, surfaced in /start and /help so the user can
# tell at a glance which bot instance they're talking to (local docker compose
# vs Railway). Free-form string; suggested values: "local", "prod".
DEPLOY_ENV = os.getenv("DEPLOY_ENV", "local")

# MOCK_MODE skips Svix signature verification on the Resend webhook
# (src/health.py). Shipping that to production would let anyone on the
# internet spoof delivery events and trigger Telegram broadcasts + DB writes.
# Fail loudly at startup rather than silently degrading webhook auth.
if MOCK_MODE and DEPLOY_ENV.lower() == "prod":
    raise RuntimeError(
        "MOCK_MODE=true is not allowed when DEPLOY_ENV=prod — "
        "this would disable Resend webhook signature verification. "
        "Set MOCK_MODE=false in the production environment."
    )
