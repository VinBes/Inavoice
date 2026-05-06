from datetime import datetime, timezone

import structlog
from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import config
from config import ALLOWED_CHAT_IDS, TELEGRAM_BOT_TOKEN
from bot.formatting import format_confirmation
from bot.keyboards import confirm_keyboard, delivery_keyboard
from db.contacts import get_contact, list_contacts
from models.session import CANCELLED, COMPLETE, CONFIRMED, GENERATING, PENDING, Session
from services.email_sender import send_invoice_email
from services.invoice_service import create_invoice, merge_and_compute
from services.llm_parser import (
    DailyCapExceededError,
    LLMAPIError,
    LLMParseError,
    LLMValidationError,
    SessionCapExceededError,
    parse_invoice_text,
)

log = structlog.get_logger()

_sessions: dict[int, Session] = {}


def _auth(chat_id: int) -> bool:
    return chat_id in ALLOWED_CHAT_IDS


def _reset_timeout(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    for job in context.job_queue.get_jobs_by_name(f"timeout_{chat_id}"):
        job.schedule_removal()
    context.job_queue.run_once(
        _timeout_callback,
        config.SESSION_TIMEOUT_MINUTES * 60,
        chat_id=chat_id,
        name=f"timeout_{chat_id}",
    )


async def _timeout_callback(context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = context.job.chat_id
    if chat_id in _sessions:
        del _sessions[chat_id]
        await context.bot.send_message(
            chat_id, "Your invoice session has expired. Please start over."
        )
        log.info("session.timeout", chat_id=chat_id)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _auth(update.effective_chat.id):
        return
    await update.message.reply_text("Inavoice ready. Send me an invoice description.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not _auth(chat_id):
        return

    text = update.message.text.strip()
    session = _sessions.get(chat_id)

    if session is None or session.state in (COMPLETE, CANCELLED):
        session = Session()
        _sessions[chat_id] = session

    if session.state in (CONFIRMED, GENERATING):
        await update.message.reply_text("Already processing your invoice.")
        return

    session.last_active = datetime.now(timezone.utc)

    contacts = await list_contacts()
    try:
        result = await parse_invoice_text(
            text,
            previous_data=session.parsed_data,  # always LLMOutput shape; None on first call
            contacts=contacts,
            session_call_count=session.llm_call_count,
        )
    except DailyCapExceededError:
        await update.message.reply_text("Daily limit reached, try again tomorrow.")
        return
    except SessionCapExceededError:
        await update.message.reply_text(
            "Too many corrections — please cancel and start over."
        )
        return
    except LLMAPIError:
        await update.message.reply_text(
            "The AI service is temporarily unavailable. Please try again in a few minutes."
        )
        return
    except (LLMParseError, LLMValidationError):
        await update.message.reply_text(
            "Something went wrong processing your request. Try again in a minute."
        )
        return

    session.llm_call_count += 1
    session.parsed_data = result.model_dump()  # always keep LLMOutput shape for correction path

    if result.missing_fields:
        fields = ", ".join(result.missing_fields)
        await update.message.reply_text(
            f"I need a few more details: {fields}. Please provide them."
        )
        _reset_timeout(chat_id, context)
        return

    contact = await get_contact(result.client_id)
    if contact is None:
        await update.message.reply_text(
            "I don't recognize that client. Which client should this be for?"
        )
        _reset_timeout(chat_id, context)
        return

    try:
        data = merge_and_compute(result, contact)
    except ValueError as e:
        await update.message.reply_text(str(e))
        return

    session.computed_data = data  # flat dict for PDF + confirmation
    msg = await update.message.reply_text(
        format_confirmation(data), reply_markup=confirm_keyboard()
    )
    session.message_id = msg.message_id
    _reset_timeout(chat_id, context)
    log.info("session.pending", chat_id=chat_id, client_id=data["client_id"])


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    # Auth against the user who pressed the button, not the chat the message is in
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    if not _auth(user_id):
        await query.answer()
        return

    session = _sessions.get(chat_id)
    cb = query.data

    if cb == "confirm":
        if session is None or session.state != PENDING:
            await query.answer("Already processing your invoice.", show_alert=True)
            return
        await query.answer()
        session.state = GENERATING
        await query.edit_message_text("Generating your invoice…")
        computed = session.computed_data or {}
        if computed.get("total") is None:
            await query.edit_message_text(
                "Invoice total is missing — please start over."
            )
            del _sessions[chat_id]
            return
        try:
            invoice_number, pdf_bytes = await create_invoice(computed)
        except Exception:
            log.exception("create_invoice.failed", chat_id=chat_id)
            await query.edit_message_text(
                "Failed to generate the PDF. This is a system error — try again."
            )
            del _sessions[chat_id]
            return
        session.invoice_number = invoice_number
        session.state = COMPLETE
        context.user_data["pdf_bytes"] = pdf_bytes
        context.user_data["invoice_number"] = invoice_number
        has_email = bool(computed.get("email"))
        await query.edit_message_text(
            f"Invoice {invoice_number} ready. How would you like to deliver it?",
            reply_markup=delivery_keyboard(has_email),
        )
        log.info("session.complete", chat_id=chat_id, invoice_number=invoice_number)

    elif cb == "edit":
        await query.answer()
        if session is None or session.state != PENDING:
            return
        await query.edit_message_text(
            "What would you like to change? Send me the correction."
        )

    elif cb == "cancel":
        await query.answer()
        _sessions.pop(chat_id, None)
        await query.edit_message_text("Invoice cancelled.")
        log.info("session.cancelled", chat_id=chat_id)

    elif cb in ("deliver_email", "deliver_telegram", "deliver_both"):
        await query.answer()
        pdf_bytes = context.user_data.get("pdf_bytes")
        invoice_number = context.user_data.get("invoice_number")
        if not pdf_bytes:
            await query.edit_message_text("Session data lost. Please start over.")
            return

        computed = (session.computed_data or {}) if session else {}
        contact_person = computed.get("contact_person")
        display_name = computed.get("display_name", "")
        email = computed.get("email", "")
        due_date = str(computed.get("due_date", ""))

        await query.edit_message_text("Sending…")

        if cb in ("deliver_email", "deliver_both"):
            try:
                await send_invoice_email(
                    email, invoice_number, pdf_bytes,
                    contact_person, display_name, due_date,
                )
                await query.message.reply_text(f"Invoice sent to {email}.")
            except Exception:
                log.exception("email_send.failed", invoice_number=invoice_number)
                await query.message.reply_text(
                    "Invoice generated but email failed to send. Here's your PDF."
                )

        if cb in ("deliver_telegram", "deliver_both"):
            await query.message.reply_document(
                document=pdf_bytes,
                filename=f"Invoice_{invoice_number}.pdf",
            )
        elif cb == "deliver_email":
            # Email-only: still send PDF via Telegram per spec (always delivered)
            await query.message.reply_document(
                document=pdf_bytes,
                filename=f"Invoice_{invoice_number}.pdf",
            )

        _sessions.pop(chat_id, None)
        log.info("session.delivered", chat_id=chat_id, invoice_number=invoice_number, method=cb)


def build_application() -> Application:
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))
    return app
