"""Tests for db/contacts.py — verifies Contact validation at the DB boundary."""
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from db.contacts import delete_contact, get_contact, list_contacts, upsert_contact
from models.schemas import Contact


def _valid_row(**overrides):
    base = {
        "client_id": "client_a",
        "display_name": "Client A Ltd.",
        "address": "Test Address",
        "contact_person": None,
        "email": "billing@client-a.example.com",
        "default_description": "Invoice for Client A",
        "default_service_description": "Service for Client A",
        "default_rate": "500",  # PostgREST returns NUMERIC as string
    }
    base.update(overrides)
    return base


def _patched_client_with_select(rows):
    """Build a mock supabase client whose table().select().eq().execute() returns `rows`."""
    client = MagicMock()
    execute = MagicMock()
    execute.data = rows
    chain = client.table.return_value.select.return_value
    chain.eq.return_value.execute.return_value = execute
    chain.order.return_value.execute.return_value = execute
    return client


async def test_get_contact_returns_contact_when_found():
    client = _patched_client_with_select([_valid_row()])
    with patch("db.contacts.get_client", return_value=client):
        result = await get_contact("client_a")
    assert isinstance(result, Contact)
    assert result.client_id == "client_a"
    assert result.default_rate == Decimal("500")


async def test_get_contact_returns_none_when_not_found():
    client = _patched_client_with_select([])
    with patch("db.contacts.get_client", return_value=client):
        result = await get_contact("missing_client")
    assert result is None


async def test_get_contact_raises_on_invalid_row():
    bad = _valid_row(client_id="Bad ID")  # uppercase + space → fails slug regex
    client = _patched_client_with_select([bad])
    with patch("db.contacts.get_client", return_value=client):
        with pytest.raises(ValidationError):
            await get_contact("client_a")


async def test_list_contacts_returns_list_of_contacts():
    rows = [_valid_row(client_id="client_a"), _valid_row(client_id="client_b")]
    client = _patched_client_with_select(rows)
    with patch("db.contacts.get_client", return_value=client):
        result = await list_contacts()
    assert len(result) == 2
    assert all(isinstance(c, Contact) for c in result)
    assert {c.client_id for c in result} == {"client_a", "client_b"}


async def test_list_contacts_raises_on_invalid_row():
    rows = [_valid_row(), _valid_row(client_id="BAD")]
    client = _patched_client_with_select(rows)
    with patch("db.contacts.get_client", return_value=client):
        with pytest.raises(ValidationError):
            await list_contacts()


async def test_upsert_contact_serializes_to_json_dict():
    """Supabase client must receive a plain dict with Decimal serialized."""
    client = MagicMock()
    upsert_chain = client.table.return_value.upsert
    upsert_chain.return_value.execute.return_value = MagicMock()

    contact = Contact(
        client_id="new_client",
        display_name="New Client",
        address="HK",
        default_rate=Decimal("750"),
    )
    with patch("db.contacts.get_client", return_value=client):
        await upsert_contact(contact)

    # First positional arg is the payload dict
    args, kwargs = upsert_chain.call_args
    payload = args[0]
    assert payload["client_id"] == "new_client"
    assert payload["display_name"] == "New Client"
    # mode="json" stringifies Decimal so PostgREST is happy with NUMERIC column
    assert isinstance(payload["default_rate"], str)
    assert Decimal(payload["default_rate"]) == Decimal("750")
    assert kwargs.get("on_conflict") == "client_id"


async def test_delete_contact_invokes_delete_eq():
    """Verify the supabase chain `.table('contacts').delete().eq('client_id', X).execute()`."""
    client = MagicMock()
    delete_chain = client.table.return_value.delete
    eq_chain = delete_chain.return_value.eq
    eq_chain.return_value.execute.return_value = MagicMock()

    with patch("db.contacts.get_client", return_value=client):
        await delete_contact("client_a")

    client.table.assert_called_with("contacts")
    delete_chain.assert_called_once_with()
    eq_chain.assert_called_once_with("client_id", "client_a")
    eq_chain.return_value.execute.assert_called_once_with()
