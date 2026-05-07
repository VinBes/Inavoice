"""Tests for the Resend webhook receiver in src/health.py.

The webhook dispatch logic is exposed as a pure async function
``handle_resend_event`` so most cases can be tested without spinning up the
HTTP server. The two HTTP-level cases are the MOCK_MODE accept path and the
prod-mode signature rejection path.
"""
import json
import socket
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import HTTPServer
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import TypeAdapter

import config
from health import _HealthHandler, handle_resend_event, start_health_server
from models.schemas import ResendWebhookEvent


_RESEND_EVENT_ADAPTER = TypeAdapter(ResendWebhookEvent)


def _delivered_event(email_id="evt_abc"):
    return _RESEND_EVENT_ADAPTER.validate_python({
        "type": "email.delivered",
        "created_at": "2026-05-08T10:00:00Z",
        "data": {"email_id": email_id},
    })


def _bounced_event(email_id="evt_abc", message="mailbox full"):
    return _RESEND_EVENT_ADAPTER.validate_python({
        "type": "email.bounced",
        "created_at": "2026-05-08T10:00:00Z",
        "data": {
            "email_id": email_id,
            "bounce": {
                "message": message,
                "subType": "Suppressed",
                "type": "Permanent",
            },
        },
    })


def _complained_event(email_id="evt_abc"):
    return _RESEND_EVENT_ADAPTER.validate_python({
        "type": "email.complained",
        "created_at": "2026-05-08T10:00:00Z",
        "data": {"email_id": email_id},
    })


# ---------------------------------------------------------------------------
# Pure dispatcher tests — handle_resend_event
# ---------------------------------------------------------------------------


async def test_delivered_event_updates_invoice_no_broadcast():
    bot = MagicMock()
    bot.send_message = AsyncMock()

    row = {"invoice_number": "ZARAFFA26-1", "email_delivery_status": None}
    with (
        patch("health.find_by_email_id", AsyncMock(return_value=row)) as find,
        patch("health.update_email_delivery", AsyncMock()) as upd,
    ):
        await handle_resend_event(
            _delivered_event(), bot=bot, allowed_chat_ids=[111, 222]
        )

    find.assert_awaited_once_with("evt_abc")
    assert upd.await_args.args[0] == "ZARAFFA26-1"
    assert upd.await_args.args[1] == "delivered"
    assert isinstance(upd.await_args.args[2], datetime)
    bot.send_message.assert_not_awaited()


async def test_bounced_event_broadcasts_to_all_allowed_chat_ids():
    bot = MagicMock()
    bot.send_message = AsyncMock()

    row = {"invoice_number": "ZARAFFA26-1", "email_delivery_status": None}
    with (
        patch("health.find_by_email_id", AsyncMock(return_value=row)),
        patch("health.update_email_delivery", AsyncMock()) as upd,
    ):
        await handle_resend_event(
            _bounced_event(message="mailbox full"),
            bot=bot,
            allowed_chat_ids=[111, 222, 333],
        )

    assert upd.await_args.args[1] == "bounced"
    assert bot.send_message.await_count == 3
    sent_chat_ids = {call.args[0] for call in bot.send_message.await_args_list}
    assert sent_chat_ids == {111, 222, 333}
    text = bot.send_message.await_args_list[0].args[1]
    assert "ZARAFFA26-1" in text
    assert "mailbox full" in text
    assert "bounced" in text.lower()


async def test_complained_event_broadcasts():
    bot = MagicMock()
    bot.send_message = AsyncMock()

    row = {"invoice_number": "ZARAFFA26-1", "email_delivery_status": None}
    with (
        patch("health.find_by_email_id", AsyncMock(return_value=row)),
        patch("health.update_email_delivery", AsyncMock()) as upd,
    ):
        await handle_resend_event(
            _complained_event(), bot=bot, allowed_chat_ids=[111, 222]
        )

    assert upd.await_args.args[1] == "complained"
    assert bot.send_message.await_count == 2
    text = bot.send_message.await_args_list[0].args[1]
    assert "ZARAFFA26-1" in text
    assert "spam" in text.lower()


async def test_bounced_event_idempotent_when_already_bounced():
    bot = MagicMock()
    bot.send_message = AsyncMock()

    row = {"invoice_number": "ZARAFFA26-1", "email_delivery_status": "bounced"}
    with (
        patch("health.find_by_email_id", AsyncMock(return_value=row)),
        patch("health.update_email_delivery", AsyncMock()) as upd,
    ):
        await handle_resend_event(
            _bounced_event(), bot=bot, allowed_chat_ids=[111, 222]
        )

    upd.assert_not_awaited()
    bot.send_message.assert_not_awaited()


async def test_unknown_email_id_silently_acks():
    bot = MagicMock()
    bot.send_message = AsyncMock()

    with (
        patch("health.find_by_email_id", AsyncMock(return_value=None)),
        patch("health.update_email_delivery", AsyncMock()) as upd,
    ):
        # Must not raise.
        await handle_resend_event(
            _delivered_event(), bot=bot, allowed_chat_ids=[111]
        )

    upd.assert_not_awaited()
    bot.send_message.assert_not_awaited()


async def test_unknown_event_type_skipped():
    """Resend may send event types we don't subscribe to (e.g. email.opened)
    — Pydantic discriminator rejects them; the HTTP layer translates that to
    a 200 ack. Here we assert TypeAdapter raises so the HTTP handler's
    ValidationError branch is the right gate."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _RESEND_EVENT_ADAPTER.validate_python({
            "type": "email.opened",
            "created_at": "2026-05-08T10:00:00Z",
            "data": {"email_id": "evt_abc"},
        })


async def test_unknown_event_type_via_http_returns_200():
    """End-to-end: posting an unhandled event type yields HTTP 200 (no retries)."""
    bot = MagicMock()
    loop = MagicMock()  # never used because handler short-circuits before dispatch

    port = _free_port()
    server = _start_server(port, bot=bot, loop=loop)
    try:
        body = json.dumps({
            "type": "email.opened",
            "created_at": "2026-05-08T10:00:00Z",
            "data": {"email_id": "evt_abc"},
        }).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/webhooks/resend",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert resp.status == 200
            payload = json.loads(resp.read())
            assert payload == {"ok": True}
    finally:
        server.shutdown()


# ---------------------------------------------------------------------------
# HTTP layer tests
# ---------------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_server(port: int, *, bot, loop) -> HTTPServer:
    """Start a server bound only to 127.0.0.1 for tests (start_health_server
    binds 0.0.0.0). Same handler class, same dispatch."""
    _HealthHandler.bot = bot
    _HealthHandler.loop = loop
    server = HTTPServer(("127.0.0.1", port), _HealthHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    # Give the listen socket a moment to be ready.
    time.sleep(0.05)
    return server


async def test_signature_verification_skipped_in_mock_mode():
    """MOCK_MODE is true in conftest; webhook accepts a body without svix
    headers and dispatches it."""
    assert config.MOCK_MODE is True

    # Fake an event loop that runs the coroutine inline so we don't need PTB.
    import asyncio as _asyncio

    real_loop = _asyncio.new_event_loop()
    loop_thread = threading.Thread(
        target=real_loop.run_forever, daemon=True
    )
    loop_thread.start()

    bot = MagicMock()
    bot.send_message = AsyncMock()

    port = _free_port()
    server = _start_server(port, bot=bot, loop=real_loop)
    try:
        with (
            patch(
                "health.find_by_email_id",
                AsyncMock(return_value={
                    "invoice_number": "ZARAFFA26-7",
                    "email_delivery_status": None,
                }),
            ),
            patch("health.update_email_delivery", AsyncMock()) as upd,
        ):
            body = json.dumps({
                "type": "email.delivered",
                "created_at": "2026-05-08T10:00:00Z",
                "data": {"email_id": "evt_xyz"},
            }).encode()
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/webhooks/resend",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                assert resp.status == 200
                assert json.loads(resp.read()) == {"ok": True}
            assert upd.await_args.args[1] == "delivered"
    finally:
        server.shutdown()
        real_loop.call_soon_threadsafe(real_loop.stop)


async def test_signature_verification_rejects_bad_signature_in_prod_mode(
    monkeypatch,
):
    """Outside MOCK_MODE the handler must call svix.Webhook.verify and a
    WebhookVerificationError surfaces as HTTP 400."""
    monkeypatch.setattr(config, "MOCK_MODE", False)

    bot = MagicMock()
    loop = MagicMock()  # not reached because verify fails before dispatch

    port = _free_port()
    server = _start_server(port, bot=bot, loop=loop)
    try:
        body = json.dumps({
            "type": "email.delivered",
            "created_at": "2026-05-08T10:00:00Z",
            "data": {"email_id": "evt_xyz"},
        }).encode()
        # Missing svix-id / svix-timestamp / svix-signature → verify fails.
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/webhooks/resend",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            urllib.request.urlopen(req, timeout=5)
        assert excinfo.value.code == 400
    finally:
        server.shutdown()


async def test_post_to_unknown_path_404():
    bot = MagicMock()
    loop = MagicMock()
    port = _free_port()
    server = _start_server(port, bot=bot, loop=loop)
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/not-a-webhook",
            data=b"{}",
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            urllib.request.urlopen(req, timeout=5)
        assert excinfo.value.code == 404
    finally:
        server.shutdown()


async def test_post_without_bot_returns_503():
    """If start_health_server was called without bot/loop (legacy test path),
    the webhook route returns 503 instead of crashing the handler thread."""
    port = _free_port()
    _HealthHandler.bot = None
    _HealthHandler.loop = None
    server = HTTPServer(("127.0.0.1", port), _HealthHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    time.sleep(0.05)
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/webhooks/resend",
            data=b"{}",
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            urllib.request.urlopen(req, timeout=5)
        assert excinfo.value.code == 503
    finally:
        server.shutdown()
