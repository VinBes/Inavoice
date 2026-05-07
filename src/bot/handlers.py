from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

import structlog
from telegram import BotCommand, Update
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
from bot.contact_flow import (
    _execute_contact_confirm,
    _start_contact_add,
    handle_contact_add_message,
)
from bot.formatting import format_confirmation
from bot.keyboards import confirm_keyboard
from db.contacts import get_contact, list_contacts
from db.invoices import list_recent_invoices
from models.session import CANCELLED, COMPLETE, CONFIRMED, GENERATING, PENDING, Session
from services.email_sender import send_invoice_email
from services.invoice_service import (
    InvoiceNotFoundError,
    create_invoice,
    merge_and_compute,
    resend_invoice,
)
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


_HELP_TEXT = (
    f"Inavoice — voice-to-invoice bot. (env: {config.DEPLOY_ENV})\n\n"
    "Send an invoice description as text (dictate via Wispr Flow on device "
    "for voice input). I'll parse it, show a preview, and generate the PDF "
    "after you confirm.\n\n"
    "Example:\n"
    "  \"Invoice for aesthetic_radio for tonight 22:00 to 02:00 at 500 per hour\"\n\n"
    "Commands:\n"
    "  /start — greeting + known clients\n"
    "  /contacts — list known client IDs\n"
    "  /contacts add — add a new client (guided)\n"
    "  /invoices — list the 10 most recent invoices\n"
    "  /resend <number> [email] — re-deliver a past invoice (Telegram only by default)\n"
    "  /cancel — cancel the current session\n"
    "  /help — show this message"
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _auth(update.effective_chat.id):
        return
    contacts = await list_contacts()
    lines = [
        f"👋 Inavoice ready. (env: {config.DEPLOY_ENV})",
        "",
        "Dictate or type an invoice description and I'll handle the rest.",
        "",
        "Example:",
        '  "Invoice for {client} for tonight 22:00 to 02:00 at 500 per hour"',
        "",
    ]
    if contacts:
        lines.append("Known clients:")
        for c in contacts:
            lines.append(f"  • {c.client_id} → {c.display_name}")
        lines.append("")
    lines.append("Type /help for the full command list.")
    await update.message.reply_text("\n".join(lines))


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _auth(update.effective_chat.id):
        return
    await update.message.reply_text(_HELP_TEXT)


async def contacts_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not _auth(chat_id):
        return
    args = context.args or []
    if args == ["add"]:
        await _start_contact_add(update, context, chat_id)
        return
    if args:
        await update.message.reply_text(
            "Usage: /contacts (list known clients) or /contacts add (guided setup)"
        )
        return
    contacts = await list_contacts()
    if not contacts:
        await update.message.reply_text("No contacts found.")
        return
    lines = ["Known clients:"]
    for c in contacts:
        lines.append(f"  • {c.client_id} → {c.display_name}")
    await update.message.reply_text("\n".join(lines))


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not _auth(chat_id):
        return
    for job in context.job_queue.get_jobs_by_name(f"timeout_{chat_id}"):
        job.schedule_removal()
    had_session = _sessions.pop(chat_id, None) is not None
    if had_session:
        await update.message.reply_text("Invoice cancelled. Send a new description to start over.")
        log.info("session.cancelled", chat_id=chat_id, source="command")
    else:
        await update.message.reply_text("No active invoice session.")


async def invoices_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _auth(update.effective_chat.id):
        return
    rows = await list_recent_invoices(limit=10)
    if not rows:
        await update.message.reply_text("No invoices yet.")
        return
    lines = ["Recent invoices:"]
    for r in rows:
        lines.append(
            f"  • {r['invoice_number']} · {r['invoice_date']} · "
            f"{r['client_id']} · {_fmt_amount(r['subtotal'])} HKD"
        )
    await update.message.reply_text("\n".join(lines))


async def resend_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not _auth(chat_id):
        return
    args = context.args or []
    if not args:
        await update.message.reply_text(
            "Usage: /resend <invoice_number> [email]\n"
            "Example: /resend ZARAFFA26-3 email"
        )
        return
    if len(args) > 2:
        await update.message.reply_text(
            "Too many arguments. Use: /resend <invoice_number> [email]"
        )
        return
    invoice_number = args[0]
    send_email = False
    if len(args) == 2:
        if args[1] == "email":
            send_email = True
        else:
            await update.message.reply_text(
                f"Unknown option `{args[1]}`. Use: /resend <invoice_number> [email]"
            )
            return

    try:
        result = await resend_invoice(invoice_number, send_email=send_email)
    except InvoiceNotFoundError:
        await update.message.reply_text(f"Invoice {invoice_number} not found.")
        return
    except Exception:
        log.exception("resend.failed", invoice_number=invoice_number, chat_id=chat_id)
        await update.message.reply_text(
            "Failed to retrieve the invoice. Try again in a minute."
        )
        return

    # Pre-PDF status text — drive off the typed status, not message truthiness,
    # so adding new statuses later forces a deliberate UX choice.
    if result.email_status == "sent":
        await update.message.reply_text(
            f"Invoice {result.invoice_number} re-sent by email."
        )
    elif result.email_status in ("skipped_no_email", "failed"):
        await update.message.reply_text(result.email_status_message or "")

    await update.message.reply_document(
        document=result.pdf_bytes,
        filename=f"Invoice_{result.invoice_number}.pdf",
    )
    log.info(
        "resend.delivered",
        invoice_number=result.invoice_number,
        chat_id=chat_id,
        email_status=result.email_status,
    )


async def handle_unsupported(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply when the user sends a non-text message (voice, photo, document, etc.)."""
    if not _auth(update.effective_chat.id):
        return
    await update.message.reply_text(
        "I can only process text right now. Voice transcription is not supported "
        "on the server — dictate via Wispr Flow on your device, then send the "
        "transcribed text. Type /help for examples."
    )


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

    if session.mode == "add_contact":
        await handle_contact_add_message(update, context, session, chat_id)
        return

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
    has_email = bool(data.get("email"))
    msg = await update.message.reply_text(
        format_confirmation(data), reply_markup=confirm_keyboard(has_email)
    )
    session.message_id = msg.message_id
    _reset_timeout(chat_id, context)
    log.info("session.pending", chat_id=chat_id, client_id=data["client_id"])


async def _execute_confirm(
    query,
    session: Session,
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    send_email: bool,
) -> None:
    """Run the full confirm pipeline: claim number → PDF → upload → save → deliver.

    Atomic from the user's perspective: one tap, one outcome. No interim state
    shared between callbacks, so a process restart cannot strand a partially
    delivered invoice.
    """
    # Cancel the pending session-timeout job; without this the user would get
    # a spurious "session expired" message ~30 minutes after a successful
    # delivery (the job that handle_message scheduled is still queued).
    for job in context.job_queue.get_jobs_by_name(f"timeout_{chat_id}"):
        job.schedule_removal()

    session.state = GENERATING
    await query.edit_message_text("Generating your invoice…")

    computed = session.computed_data or {}
    if computed.get("total") is None:
        await query.edit_message_text(
            "Invoice total is missing — please start over."
        )
        _sessions.pop(chat_id, None)
        return

    try:
        invoice_number, pdf_bytes = await create_invoice(computed)
    except Exception:
        log.exception("create_invoice.failed", chat_id=chat_id)
        await query.edit_message_text(
            "Failed to generate the PDF. This is a system error — try again."
        )
        _sessions.pop(chat_id, None)
        return

    session.invoice_number = invoice_number
    session.state = COMPLETE

    if send_email:
        email = computed.get("email")
        try:
            await send_invoice_email(
                email,
                invoice_number,
                pdf_bytes,
                computed.get("contact_person"),
                computed.get("display_name", ""),
                str(computed.get("due_date", "")),
            )
            await query.edit_message_text(
                f"Invoice {invoice_number} ready. Emailed and sending PDF here…"
            )
        except Exception as e:
            log.error(
                "email_send.failed",
                invoice_number=invoice_number,
                error_type=type(e).__name__,
                error=str(e),
            )
            await query.edit_message_text(
                f"Invoice {invoice_number} ready. Email failed — sending PDF here only."
            )
    else:
        await query.edit_message_text(
            f"Invoice {invoice_number} ready. Sending PDF…"
        )

    await query.message.reply_document(
        document=pdf_bytes,
        filename=f"Invoice_{invoice_number}.pdf",
    )

    _sessions.pop(chat_id, None)
    log.info(
        "session.delivered",
        chat_id=chat_id,
        invoice_number=invoice_number,
        send_email=send_email,
    )


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

    if cb in ("confirm", "confirm_telegram", "confirm_email"):
        if session is None or session.state != PENDING:
            await query.answer("Already processing your invoice.", show_alert=True)
            return
        await query.answer()
        await _execute_confirm(
            query, session, chat_id, context, send_email=(cb == "confirm_email")
        )

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

    elif cb == "contact_confirm":
        if session is None or session.mode != "add_contact":
            await query.answer("No contact setup in progress.", show_alert=True)
            return
        await query.answer()
        await _execute_contact_confirm(query, session, chat_id, context)

    elif cb == "contact_cancel":
        await query.answer()
        for job in context.job_queue.get_jobs_by_name(f"timeout_{chat_id}"):
            job.schedule_removal()
        _sessions.pop(chat_id, None)
        await query.edit_message_text("Contact setup cancelled.")
        log.info("contact_add.cancelled", chat_id=chat_id, source="button")


def _fmt_amount(value) -> str:
    """Format a numeric amount (Decimal or string from PostgREST) for display.

    Returns "?" if the value is None or unparseable — `subtotal` is NOT NULL in
    the schema, so this should never happen, but a malformed row should not
    crash /invoices.
    """
    if value is None:
        return "?"
    try:
        return format(Decimal(str(value)).normalize(), "f")
    except (InvalidOperation, ValueError):
        return "?"


BOT_COMMANDS: list[BotCommand] = [
    BotCommand("start", "Show welcome message"),
    BotCommand("help", "How to dictate an invoice"),
    BotCommand("contacts", "List saved contacts (or `/contacts add`)"),
    BotCommand("invoices", "List recent invoices"),
    BotCommand("resend", "Resend a recent invoice"),
    BotCommand("cancel", "Cancel the current draft"),
]


async def _register_commands(app: Application) -> None:
    await app.bot.set_my_commands(BOT_COMMANDS)


def build_application() -> Application:
    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(_register_commands)
        .build()
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("contacts", contacts_command))
    app.add_handler(CommandHandler("invoices", invoices_command))
    app.add_handler(CommandHandler("resend", resend_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(~filters.TEXT & ~filters.COMMAND, handle_unsupported))
    app.add_handler(CallbackQueryHandler(handle_callback))
    return app
