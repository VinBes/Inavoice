"""Tests for the MOCK_MODE alias matcher in services.llm_parser.

`_load_mock_response` extends the contact-matching loop to also match any
alias substring (case-insensitive). The matcher then loads the first fixture
that begins with `<client_id>_`. The Aliases field is also rendered into the
prompt by `_build_client_list` as ` (also: alias1, alias2)`.
"""
from decimal import Decimal

import pytest

from models.schemas import Contact
from services.llm_parser import _build_client_list, _load_mock_response


def _aer_contact() -> Contact:
    return Contact(
        client_id="aesthetic_radio",
        display_name="Aesthetic Radio HK",
        address="HK address",
        aliases="AER, aesthetic",
    )


def _client_a_contact() -> Contact:
    return Contact(
        client_id="client_a",
        display_name="Client A Ltd.",
        address="123 Test Road",
        default_rate=Decimal("500"),
    )


def test_build_client_list_appends_aliases():
    """A contact with aliases is rendered as `(also: …)` in the prompt block."""
    line = _build_client_list([_aer_contact()])
    assert '"aesthetic_radio" → Aesthetic Radio HK' in line
    assert "(also: AER, aesthetic)" in line


def test_build_client_list_no_aliases_omits_suffix():
    """A contact with no aliases renders without the `(also: …)` suffix."""
    line = _build_client_list([_client_a_contact()])
    assert "(also:" not in line


def test_build_client_list_handles_string_aliases_dict():
    """A raw dict from Supabase has aliases as a comma-separated string."""
    line = _build_client_list([
        {"client_id": "x", "display_name": "X Ltd.", "aliases": "X1, X2"}
    ])
    assert "(also: X1, X2)" in line


def test_load_mock_response_matches_on_alias():
    """The matcher resolves a contact when only an alias appears in the text."""
    result = _load_mock_response("invoice for AER tonight at 500/hr", [_aer_contact()])
    assert result.client_id == "aesthetic_radio"


def test_load_mock_response_alias_match_is_case_insensitive():
    result = _load_mock_response("aesthetic gig next friday", [_aer_contact()])
    assert result.client_id == "aesthetic_radio"


def test_load_mock_response_no_alias_match_falls_back_to_unknown():
    """If neither client_id, display_name, nor any alias matches, the matcher
    falls back to the unknown_client fixture."""
    contact = _aer_contact()
    result = _load_mock_response("invoice for someone else for 1000 flat", [contact])
    # unknown_client.json has client_id=None
    assert result.client_id is None


def test_load_mock_response_still_matches_display_name():
    """Adding aliases must not break existing client_id / display_name matching."""
    result = _load_mock_response(
        "invoice for Aesthetic Radio HK tonight",
        [_aer_contact()],
    )
    assert result.client_id == "aesthetic_radio"
