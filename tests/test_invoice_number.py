"""Tests 2.1–2.2: invoice number generation with mocked Supabase RPC.

Also covers the db.invoices read/update helpers added for /invoices and /resend:
list_recent_invoices, get_invoice, update_last_resent_at, download_pdf.
"""
from unittest.mock import MagicMock, patch

import pytest

from db.invoices import (
    download_pdf,
    get_invoice,
    list_recent_invoices,
    next_invoice_number,
    update_last_resent_at,
)


def _make_rpc_mock(counter_value: int) -> MagicMock:
    mock_response = MagicMock()
    mock_response.data = counter_value
    mock_client = MagicMock()
    mock_client.rpc.return_value.execute.return_value = mock_response
    return mock_client


def _make_select_mock(rows: list) -> MagicMock:
    """Mock for .table().select().order().limit().execute() chain."""
    mock_response = MagicMock()
    mock_response.data = rows
    mock_client = MagicMock()
    chain = mock_client.table.return_value.select.return_value
    chain.order.return_value.limit.return_value.execute.return_value = mock_response
    chain.eq.return_value.execute.return_value = mock_response
    return mock_client


def _make_update_mock() -> MagicMock:
    """Mock for .table().update().eq().execute() chain."""
    mock_client = MagicMock()
    mock_client.table.return_value.update.return_value.eq.return_value.execute.return_value = (
        MagicMock()
    )
    return mock_client


def _make_storage_download_mock(pdf_bytes: bytes) -> MagicMock:
    """Mock for .storage.from_(bucket).download(path) — returns raw bytes."""
    mock_client = MagicMock()
    mock_client.storage.from_.return_value.download.return_value = pdf_bytes
    return mock_client


# ---------------------------------------------------------------------------
# Test 2.1 — Sequential numbering
# ---------------------------------------------------------------------------

async def test_2_1_sequential_numbering():
    mock_client = _make_rpc_mock(1)
    with patch("db.invoices.get_client", return_value=mock_client):
        result = await next_invoice_number(2026)

    assert result == "ZARAFFA26-1"
    mock_client.rpc.assert_called_once_with(
        "increment_invoice_counter", {"p_year": 2026}
    )


async def test_2_1_second_invoice():
    mock_client = _make_rpc_mock(2)
    with patch("db.invoices.get_client", return_value=mock_client):
        result = await next_invoice_number(2026)

    assert result == "ZARAFFA26-2"


# ---------------------------------------------------------------------------
# Test 2.2 — Year rollover
# ---------------------------------------------------------------------------

async def test_2_2_year_rollover():
    mock_client = _make_rpc_mock(1)
    with patch("db.invoices.get_client", return_value=mock_client):
        result = await next_invoice_number(2027)

    assert result == "ZARAFFA27-1"
    mock_client.rpc.assert_called_once_with(
        "increment_invoice_counter", {"p_year": 2027}
    )


async def test_2_2_large_counter():
    mock_client = _make_rpc_mock(42)
    with patch("db.invoices.get_client", return_value=mock_client):
        result = await next_invoice_number(2026)

    assert result == "ZARAFFA26-42"


# ---------------------------------------------------------------------------
# list_recent_invoices
# ---------------------------------------------------------------------------

async def test_list_recent_invoices_returns_rows():
    rows = [
        {"invoice_number": "ZARAFFA26-3", "invoice_date": "2026-04-12",
         "client_id": "client_a", "subtotal": "1500"},
    ]
    mock_client = _make_select_mock(rows)
    with patch("db.invoices.get_client", return_value=mock_client):
        result = await list_recent_invoices(limit=10)

    assert result == rows
    mock_client.table.assert_called_once_with("invoices")
    # Order DESC and limit applied
    chain = mock_client.table.return_value.select.return_value
    chain.order.assert_called_once_with("created_at", desc=True)
    chain.order.return_value.limit.assert_called_once_with(10)


async def test_list_recent_invoices_empty():
    mock_client = _make_select_mock([])
    with patch("db.invoices.get_client", return_value=mock_client):
        result = await list_recent_invoices(limit=10)
    assert result == []


# ---------------------------------------------------------------------------
# get_invoice
# ---------------------------------------------------------------------------

async def test_get_invoice_found():
    rows = [{"invoice_number": "ZARAFFA26-3", "client_id": "client_a"}]
    mock_client = _make_select_mock(rows)
    with patch("db.invoices.get_client", return_value=mock_client):
        result = await get_invoice("ZARAFFA26-3")
    assert result == rows[0]


async def test_get_invoice_not_found_returns_none():
    mock_client = _make_select_mock([])
    with patch("db.invoices.get_client", return_value=mock_client):
        result = await get_invoice("ZARAFFA99-99")
    assert result is None


# ---------------------------------------------------------------------------
# update_last_resent_at
# ---------------------------------------------------------------------------

async def test_update_last_resent_at_writes_iso_timestamp():
    mock_client = _make_update_mock()
    with patch("db.invoices.get_client", return_value=mock_client):
        await update_last_resent_at("ZARAFFA26-3")

    update_call = mock_client.table.return_value.update.call_args
    payload = update_call.args[0]
    assert "last_resent_at" in payload
    # ISO 8601 with timezone (datetime.isoformat output)
    assert "T" in payload["last_resent_at"]
    mock_client.table.assert_called_once_with("invoices")
    eq_call = mock_client.table.return_value.update.return_value.eq.call_args
    assert eq_call.args == ("invoice_number", "ZARAFFA26-3")


# ---------------------------------------------------------------------------
# download_pdf
# ---------------------------------------------------------------------------

async def test_download_pdf_returns_bytes_from_storage():
    mock_client = _make_storage_download_mock(b"%PDF-1.7 fake")
    with patch("db.invoices.get_client", return_value=mock_client):
        result = await download_pdf("2026/ZARAFFA26-3.pdf")

    assert result == b"%PDF-1.7 fake"
    mock_client.storage.from_.assert_called_once_with("invoices")
    mock_client.storage.from_.return_value.download.assert_called_once_with(
        "2026/ZARAFFA26-3.pdf"
    )
