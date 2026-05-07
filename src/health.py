"""Tiny HTTP listener for Railway / uptime probes plus the Resend webhook receiver.

Runs in a daemon thread alongside Telegram polling so the bot exposes:

- `GET /healthz` and `GET /` — uptime probe (200 JSON {"status":"ok"})
- `POST /webhooks/resend` — Resend delivery event receiver

The webhook handler verifies the svix signature (skipped in MOCK_MODE), parses
the event with Pydantic, and dispatches to ``handle_resend_event`` — which is a
pure async function exposed for unit tests so we don't have to mock HTTP.
"""
import asyncio
import json
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Iterable

import structlog
from pydantic import TypeAdapter, ValidationError
from svix.webhooks import Webhook, WebhookVerificationError

import config
from db.invoices import find_by_email_id, update_email_delivery
from models.schemas import (
    ResendBouncedEvent,
    ResendComplainedEvent,
    ResendDeliveredEvent,
    ResendWebhookEvent,
)

log = structlog.get_logger()

_OK_PAYLOAD = json.dumps({"status": "ok"}).encode()
_WEBHOOK_OK_PAYLOAD = json.dumps({"ok": True}).encode()
_RESEND_EVENT_ADAPTER = TypeAdapter(ResendWebhookEvent)


async def handle_resend_event(
    event: ResendWebhookEvent,
    *,
    bot,
    allowed_chat_ids: Iterable[int],
) -> None:
    """Pure async dispatcher — invoked from the HTTP thread via run_coroutine_threadsafe.

    Looks up the invoice by Resend's email_id, updates delivery status, and
    broadcasts a Telegram message on bounce/complaint events. Idempotent: a
    duplicate bounced/complained event for the same invoice is ignored after
    the first broadcast.
    """
    email_id = event.data.email_id
    row = await find_by_email_id(email_id)
    if row is None:
        # Unknown email_id — could be a stray retry from before we tracked ids,
        # or for an invoice that never persisted its id. Ack and move on.
        log.info("resend_webhook.unknown_email_id", event_type=event.type)
        return

    invoice_number = row["invoice_number"]
    now = datetime.now(timezone.utc)

    if isinstance(event, ResendDeliveredEvent):
        await update_email_delivery(invoice_number, "delivered", now)
        log.info(
            "resend_webhook.delivered",
            invoice_number=invoice_number,
        )
        return

    if isinstance(event, ResendBouncedEvent):
        if row.get("email_delivery_status") == "bounced":
            log.info(
                "resend_webhook.bounced.duplicate",
                invoice_number=invoice_number,
            )
            return
        await update_email_delivery(invoice_number, "bounced", now)
        bounce_message = (
            event.data.bounce.message if event.data.bounce else None
        ) or "(no details)"
        text = f"⚠️ Invoice {invoice_number} bounced. {bounce_message}"
        log.info(
            "resend_webhook.bounced",
            invoice_number=invoice_number,
            bounce_message=bounce_message,
        )
        if bot is not None:
            for chat_id in allowed_chat_ids:
                await bot.send_message(chat_id, text)
        return

    if isinstance(event, ResendComplainedEvent):
        if row.get("email_delivery_status") == "complained":
            log.info(
                "resend_webhook.complained.duplicate",
                invoice_number=invoice_number,
            )
            return
        await update_email_delivery(invoice_number, "complained", now)
        text = f"⚠️ Invoice {invoice_number} marked as spam by recipient."
        log.info(
            "resend_webhook.complained",
            invoice_number=invoice_number,
        )
        if bot is not None:
            for chat_id in allowed_chat_ids:
                await bot.send_message(chat_id, text)
        return


class _HealthHandler(BaseHTTPRequestHandler):
    # Set by start_health_server when the server is launched from the bot's
    # asyncio loop. Tests that only need /healthz can leave these as None.
    bot = None
    loop: asyncio.AbstractEventLoop | None = None

    def do_GET(self) -> None:  # noqa: N802 — http.server interface
        if self.path in ("/healthz", "/"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(_OK_PAYLOAD)))
            self.end_headers()
            self.wfile.write(_OK_PAYLOAD)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self) -> None:  # noqa: N802 — http.server interface
        if self.path == "/webhooks/resend":
            self._handle_resend_webhook()
        else:
            self.send_response(404)
            self.end_headers()

    def _handle_resend_webhook(self) -> None:
        # No bot/loop available (test path that only spun up health server) →
        # 503 so the caller doesn't think the webhook silently succeeded.
        if self.bot is None or self.loop is None:
            self.send_response(503)
            self.end_headers()
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length else b""

            if not config.MOCK_MODE:
                wh = Webhook(config.RESEND_WEBHOOK_SECRET)
                try:
                    wh.verify(raw, dict(self.headers))
                except WebhookVerificationError:
                    log.info("resend_webhook.bad_signature")
                    self.send_response(400)
                    self.end_headers()
                    return

            try:
                body = json.loads(raw)
            except json.JSONDecodeError:
                log.info("resend_webhook.bad_json")
                self.send_response(400)
                self.end_headers()
                return

            try:
                event = _RESEND_EVENT_ADAPTER.validate_python(body)
            except ValidationError:
                # Resend may send event types we don't handle (e.g.
                # email.opened). Returning 4xx makes Resend retry forever, so
                # ack with 200 and log INFO.
                log.info(
                    "resend_webhook.unhandled_event_type",
                    event_type=body.get("type") if isinstance(body, dict) else None,
                )
                self._ack()
                return

            future = asyncio.run_coroutine_threadsafe(
                handle_resend_event(
                    event,
                    bot=self.bot,
                    allowed_chat_ids=config.ALLOWED_CHAT_IDS,
                ),
                self.loop,
            )
            future.result(timeout=10)

            self._ack()
        except Exception:
            # Last-resort guard: never let the HTTP thread die. 500 with no
            # body so Resend retries; details only in logs.
            log.exception("resend_webhook.unhandled_error")
            try:
                self.send_response(500)
                self.end_headers()
            except Exception:
                pass

    def _ack(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(_WEBHOOK_OK_PAYLOAD)))
        self.end_headers()
        self.wfile.write(_WEBHOOK_OK_PAYLOAD)

    def version_string(self) -> str:
        # Suppress the default `Server: BaseHTTP/x.y Python/z.z.z` header so
        # neither health probes nor webhook responses disclose the runtime.
        return ""

    def log_message(self, *args, **kwargs) -> None:
        # Silence default stderr access logs (GET and POST); structlog handles app logs.
        return


def start_health_server(
    port: int,
    *,
    bot=None,
    loop: asyncio.AbstractEventLoop | None = None,
) -> None:
    """Launch the health/webhook HTTP server in a daemon thread.

    When ``bot`` and ``loop`` are provided (the production path), the
    ``/webhooks/resend`` POST route is enabled. Without them (the test path
    that only needs /healthz), POST routes return 503.
    """
    _HealthHandler.bot = bot
    _HealthHandler.loop = loop
    server = HTTPServer(("0.0.0.0", port), _HealthHandler)
    threading.Thread(
        target=server.serve_forever, name="health-server", daemon=True
    ).start()
    log.info("health.started", port=port, webhook_enabled=bot is not None)
