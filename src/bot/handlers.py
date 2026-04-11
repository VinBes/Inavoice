from telegram.ext import Application, CommandHandler, MessageHandler, filters
from config import TELEGRAM_BOT_TOKEN, ALLOWED_CHAT_IDS


async def start(update, context):
    if update.effective_chat.id not in ALLOWED_CHAT_IDS:
        return
    await update.message.reply_text("Inavoice ready. Send me an invoice description.")


def build_application() -> Application:
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    return app
