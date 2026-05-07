"""Tests for the guided /contacts delete <client_id> flow.

The delete flow lives in `bot.contact_flow` and is callback-driven (no
SessionMode of its own). These tests exercise the three entry points
(`_start_contact_delete`, `_execute_contact_delete_confirm`,
`_execute_contact_delete_cancel`) directly — the integrator wires them into
`handle_callback` per DELETE_INTEGRATION_NOTES.md.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import config
from bot.contact_flow import (
    _execute_contact_delete_cancel,
    _execute_contact_delete_confirm,
    _start_contact_delete,
)
from bot.handlers import _sessions
from models.schemas import Contact
from models.session import GENERATING, PENDING, Session

_CHAT_ID = int(config.ALLOWED_CHAT_IDS[0])


def _make_message_update(text: str):
    update = MagicMock()
    update.effective_chat.id = _CHAT_ID
    update.message.text = text
    update.message.reply_text = AsyncMock(return_value=MagicMock(message_id=99))
    return update


def _make_context(args=None):
    ctx = MagicMock()
    ctx.user_data = {}
    ctx.args = args
    ctx.job_queue = MagicMock()
    ctx.job_queue.get_jobs_by_name = MagicMock(return_value=[])
    ctx.job_queue.run_once = MagicMock()
    return ctx


def _make_callback(data):
    query = MagicMock()
    query.data = data
    query.message.chat_id = _CHAT_ID
    query.from_user.id = _CHAT_ID
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    update = MagicMock()
    update.callback_query = query
    return update, query


def _make_contact(client_id="client_a") -> Contact:
    return Contact(
        client_id=client_id,
        display_name="Client A Ltd.",
        address="HK",
    )


# ---------------------------------------------------------------------------
# Entry: /contacts delete <client_id>
# ---------------------------------------------------------------------------


async def test_delete_command_unknown_client_id():
    """get_contact returns None → graceful reply, no session created."""
    _sessions.clear()
    update = _make_message_update("/contacts delete missing_client")
    ctx = _make_context()
    with patch("bot.contact_flow.get_contact", new=AsyncMock(return_value=None)), \
         patch(
             "bot.contact_flow.count_invoices_for_contact",
             new=AsyncMock(return_value=0),
         ) as mock_count, \
         patch("bot.contact_flow.delete_contact", new=AsyncMock()) as mock_delete:
        await _start_contact_delete(update, ctx, _CHAT_ID, "missing_client")

    assert _CHAT_ID not in _sessions
    msg = update.message.reply_text.await_args[0][0]
    assert "No contact named missing_client" in msg
    mock_count.assert_not_awaited()
    mock_delete.assert_not_awaited()


async def test_delete_refuses_when_invoices_reference_contact():
    """count_invoices_for_contact > 0 → friendly refusal, no session, no delete."""
    _sessions.clear()
    update = _make_message_update("/contacts delete client_a")
    ctx = _make_context()
    with patch(
        "bot.contact_flow.get_contact", new=AsyncMock(return_value=_make_contact())
    ), patch(
        "bot.contact_flow.count_invoices_for_contact", new=AsyncMock(return_value=3)
    ), patch(
        "bot.contact_flow.delete_contact", new=AsyncMock()
    ) as mock_delete:
        await _start_contact_delete(update, ctx, _CHAT_ID, "client_a")

    assert _CHAT_ID not in _sessions
    msg = update.message.reply_text.await_args[0][0]
    assert "Cannot delete client_a" in msg
    assert "3 invoice(s)" in msg
    mock_delete.assert_not_awaited()


async def test_delete_command_safe_shows_confirm_keyboard():
    """count is 0 → session.delete_target set + confirm keyboard shown."""
    _sessions.clear()
    update = _make_message_update("/contacts delete client_a")
    ctx = _make_context()
    with patch(
        "bot.contact_flow.get_contact", new=AsyncMock(return_value=_make_contact())
    ), patch(
        "bot.contact_flow.count_invoices_for_contact", new=AsyncMock(return_value=0)
    ):
        await _start_contact_delete(update, ctx, _CHAT_ID, "client_a")

    assert _CHAT_ID in _sessions
    s = _sessions[_CHAT_ID]
    assert s.delete_target == "client_a"

    final_call = update.message.reply_text.await_args
    assert "Delete this contact" in final_call[0][0]
    assert final_call.kwargs.get("reply_markup") is not None


async def test_delete_command_blocked_when_invoice_generating():
    """Pre-existing GENERATING session preserved; user told to wait."""
    _sessions.clear()
    generating = Session()
    generating.state = GENERATING
    _sessions[_CHAT_ID] = generating

    update = _make_message_update("/contacts delete client_a")
    ctx = _make_context()
    # No DB calls expected once the GENERATING gate trips.
    with patch(
        "bot.contact_flow.get_contact", new=AsyncMock()
    ) as mock_get, patch(
        "bot.contact_flow.count_invoices_for_contact", new=AsyncMock()
    ) as mock_count, patch(
        "bot.contact_flow.delete_contact", new=AsyncMock()
    ) as mock_delete:
        await _start_contact_delete(update, ctx, _CHAT_ID, "client_a")

    assert _sessions[_CHAT_ID] is generating
    msg = update.message.reply_text.await_args[0][0]
    assert "being generated" in msg.lower() or "wait" in msg.lower()
    mock_get.assert_not_awaited()
    mock_count.assert_not_awaited()
    mock_delete.assert_not_awaited()


# ---------------------------------------------------------------------------
# `/contacts delete` with no second arg — usage hint
# ---------------------------------------------------------------------------
#
# The dispatcher (handlers.contacts_command) matches `args == ["delete"]` and
# replies with a usage line BEFORE calling _start_contact_delete. See
# DELETE_INTEGRATION_NOTES.md §2. Since the dispatcher branch is wired by the
# integrator, this test exercises the contract via the documented behaviour:
# entering the contact_flow function with an empty client_id is unsupported,
# so the dispatcher must short-circuit. We verify the spec by importing the
# notes contract.


async def test_delete_command_no_args_shows_usage():
    """`/contacts delete` with no client_id is short-circuited at the dispatcher
    with a usage hint and never calls into contact_flow."""
    from bot.handlers import contacts_command

    _sessions.clear()
    update = _make_message_update("/contacts delete")
    ctx = _make_context(args=["delete"])

    with patch(
        "bot.handlers._start_contact_delete", new=AsyncMock()
    ) as mock_start:
        await contacts_command(update, ctx)

    mock_start.assert_not_awaited()
    msg = update.message.reply_text.await_args.args[0]
    assert "Usage" in msg
    assert "/contacts delete <client_id>" in msg
    assert _CHAT_ID not in _sessions


# ---------------------------------------------------------------------------
# Confirm callback
# ---------------------------------------------------------------------------


async def test_delete_confirm_callback_runs_delete():
    """session.delete_target matches → re-check returns 0 → delete is awaited once."""
    _sessions.clear()
    s = Session()
    s.delete_target = "client_a"
    _sessions[_CHAT_ID] = s

    update, query = _make_callback("contact_delete_confirm:client_a")
    ctx = _make_context()
    with patch(
        "bot.contact_flow.count_invoices_for_contact", new=AsyncMock(return_value=0)
    ), patch(
        "bot.contact_flow.delete_contact", new=AsyncMock()
    ) as mock_delete:
        await _execute_contact_delete_confirm(query, s, _CHAT_ID, ctx, "client_a")

    mock_delete.assert_awaited_once_with("client_a")
    assert _CHAT_ID not in _sessions
    msg = query.edit_message_text.await_args[0][0]
    assert "Contact client_a deleted" in msg


async def test_delete_confirm_re_checks_invoice_count():
    """An invoice was inserted between command and confirm → refuse, no delete."""
    _sessions.clear()
    s = Session()
    s.delete_target = "client_a"
    _sessions[_CHAT_ID] = s

    update, query = _make_callback("contact_delete_confirm:client_a")
    ctx = _make_context()
    with patch(
        "bot.contact_flow.count_invoices_for_contact", new=AsyncMock(return_value=1)
    ), patch(
        "bot.contact_flow.delete_contact", new=AsyncMock()
    ) as mock_delete:
        await _execute_contact_delete_confirm(query, s, _CHAT_ID, ctx, "client_a")

    mock_delete.assert_not_awaited()
    assert _CHAT_ID not in _sessions
    msg = query.edit_message_text.await_args[0][0]
    assert "Cannot delete client_a" in msg
    assert "1 invoice(s)" in msg


async def test_delete_confirm_stale_callback_ignored():
    """session.delete_target != callback's client_id → silently ignore."""
    _sessions.clear()
    s = Session()
    s.delete_target = "other_client"
    _sessions[_CHAT_ID] = s

    update, query = _make_callback("contact_delete_confirm:client_a")
    ctx = _make_context()
    with patch(
        "bot.contact_flow.count_invoices_for_contact", new=AsyncMock()
    ) as mock_count, patch(
        "bot.contact_flow.delete_contact", new=AsyncMock()
    ) as mock_delete:
        await _execute_contact_delete_confirm(query, s, _CHAT_ID, ctx, "client_a")

    mock_delete.assert_not_awaited()
    mock_count.assert_not_awaited()
    # Session preserved; user can still tap Cancel.
    assert _sessions.get(_CHAT_ID) is s
    query.edit_message_text.assert_not_awaited()


async def test_delete_confirm_db_failure_reports_friendly_error():
    """delete_contact raises → friendly error message, session cleared."""
    _sessions.clear()
    s = Session()
    s.delete_target = "client_a"
    _sessions[_CHAT_ID] = s

    update, query = _make_callback("contact_delete_confirm:client_a")
    ctx = _make_context()
    with patch(
        "bot.contact_flow.count_invoices_for_contact", new=AsyncMock(return_value=0)
    ), patch(
        "bot.contact_flow.delete_contact",
        new=AsyncMock(side_effect=RuntimeError("FK violation")),
    ):
        await _execute_contact_delete_confirm(query, s, _CHAT_ID, ctx, "client_a")

    assert _CHAT_ID not in _sessions
    msg = query.edit_message_text.await_args[0][0]
    assert "Failed to delete" in msg


# ---------------------------------------------------------------------------
# Cancel callback
# ---------------------------------------------------------------------------


async def test_delete_cancel_clears_session():
    """Cancel tap clears the session and replies 'Deletion cancelled.'."""
    _sessions.clear()
    s = Session()
    s.delete_target = "client_a"
    _sessions[_CHAT_ID] = s

    update, query = _make_callback("contact_delete_cancel")
    ctx = _make_context()
    await _execute_contact_delete_cancel(query, s, _CHAT_ID, ctx)

    assert _CHAT_ID not in _sessions
    msg = query.edit_message_text.await_args[0][0]
    assert "cancelled" in msg.lower()
