"""Unit tests for the Contact pydantic model."""
from decimal import Decimal

import pytest
from pydantic import ValidationError

from models.schemas import Contact


class TestContact:
    def _full_data(self, **overrides):
        base = {
            "client_id": "aesthetic_radio",
            "display_name": "Aesthetic Radio HK",
            "address": "Unit 12, 5/F, 88 Test Road\nHong Kong",
            "contact_person": "Jane Doe",
            "email": "billing@aesthetic-radio.example.com",
            "default_description": "Invoice for AER booking",
            "default_service_description": "DJ set",
            "default_rate": Decimal("500"),
        }
        base.update(overrides)
        return base

    def test_valid_full_contact(self):
        c = Contact(**self._full_data())
        assert c.client_id == "aesthetic_radio"
        assert c.default_rate == Decimal("500")

    def test_valid_minimal_contact(self):
        c = Contact(
            client_id="client_a",
            display_name="Client A Ltd.",
            address="HK address",
        )
        assert c.contact_person is None
        assert c.email is None
        assert c.default_rate is None

    def test_client_id_rejects_uppercase(self):
        with pytest.raises(ValidationError, match="lowercase"):
            Contact(**self._full_data(client_id="ClientA"))

    def test_client_id_rejects_hyphen(self):
        with pytest.raises(ValidationError, match="lowercase"):
            Contact(**self._full_data(client_id="my-client"))

    def test_client_id_rejects_empty(self):
        with pytest.raises(ValidationError, match="lowercase"):
            Contact(**self._full_data(client_id=""))

    def test_client_id_rejects_space(self):
        with pytest.raises(ValidationError, match="lowercase"):
            Contact(**self._full_data(client_id="my client"))

    def test_email_rejects_no_at_sign(self):
        with pytest.raises(ValidationError, match="email"):
            Contact(**self._full_data(email="not-an-email"))

    def test_email_rejects_missing_tld(self):
        with pytest.raises(ValidationError, match="email"):
            Contact(**self._full_data(email="name@host"))

    def test_email_rejects_whitespace(self):
        with pytest.raises(ValidationError, match="email"):
            Contact(**self._full_data(email="name @host.com"))

    def test_email_accepts_none(self):
        c = Contact(**self._full_data(email=None))
        assert c.email is None

    def test_default_rate_rejects_zero(self):
        with pytest.raises(ValidationError, match="positive"):
            Contact(**self._full_data(default_rate=Decimal("0")))

    def test_default_rate_rejects_negative(self):
        with pytest.raises(ValidationError, match="positive"):
            Contact(**self._full_data(default_rate=Decimal("-100")))

    def test_default_rate_accepts_string(self):
        # PostgREST returns NUMERIC columns as strings; Pydantic v2 should coerce.
        c = Contact(**self._full_data(default_rate="500"))
        assert c.default_rate == Decimal("500")

    def test_model_dump_round_trip(self):
        original = Contact(**self._full_data())
        round_tripped = Contact(**original.model_dump())
        assert round_tripped == original


class TestContactAliases:
    """Aliases coercion (str → list) and serialization (list → str)."""

    def _full_data(self, **overrides):
        base = {
            "client_id": "aesthetic_radio",
            "display_name": "Aesthetic Radio HK",
            "address": "Unit 12, 5/F, 88 Test Road\nHong Kong",
        }
        base.update(overrides)
        return base

    def test_aliases_default_is_empty_list(self):
        c = Contact(**self._full_data())
        assert c.aliases == []

    def test_aliases_from_comma_separated_string(self):
        c = Contact(**self._full_data(aliases="AER, Aesthetic Radio, aesthetic"))
        assert c.aliases == ["AER", "Aesthetic Radio", "aesthetic"]

    def test_aliases_strips_whitespace(self):
        c = Contact(**self._full_data(aliases="  AER  ,  aesthetic  "))
        assert c.aliases == ["AER", "aesthetic"]

    def test_aliases_drops_empty_segments(self):
        c = Contact(**self._full_data(aliases="AER,,  ,aesthetic"))
        assert c.aliases == ["AER", "aesthetic"]

    def test_aliases_empty_string_is_empty_list(self):
        c = Contact(**self._full_data(aliases=""))
        assert c.aliases == []

    def test_aliases_none_is_empty_list(self):
        c = Contact(**self._full_data(aliases=None))
        assert c.aliases == []

    def test_aliases_accepts_list(self):
        c = Contact(**self._full_data(aliases=["AER", "aesthetic"]))
        assert c.aliases == ["AER", "aesthetic"]

    def test_aliases_serialize_back_to_comma_string(self):
        c = Contact(**self._full_data(aliases=["AER", "aesthetic"]))
        dumped = c.model_dump(mode="json")
        assert dumped["aliases"] == "AER, aesthetic"

    def test_aliases_serialize_empty_list_is_empty_string(self):
        c = Contact(**self._full_data())
        dumped = c.model_dump(mode="json")
        assert dumped["aliases"] == ""

    def test_aliases_round_trip_through_string(self):
        original = Contact(**self._full_data(aliases="AER, aesthetic"))
        serialized = original.model_dump(mode="json")
        restored = Contact.model_validate(
            {**self._full_data(), "aliases": serialized["aliases"]}
        )
        assert restored.aliases == ["AER", "aesthetic"]
