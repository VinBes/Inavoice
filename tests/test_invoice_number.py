"""Tests 2.1–2.2: invoice number generation with mocked Supabase RPC."""
from unittest.mock import MagicMock, patch

import pytest

from db.invoices import next_invoice_number


def _make_rpc_mock(counter_value: int) -> MagicMock:
    mock_response = MagicMock()
    mock_response.data = counter_value
    mock_client = MagicMock()
    mock_client.rpc.return_value.execute.return_value = mock_response
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
