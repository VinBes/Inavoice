import pytest
from decimal import Decimal
from datetime import timezone

from pydantic import ValidationError

from models.schemas import LLMLineItem, LLMOutput
from models.session import Session, PENDING, CONFIRMED, GENERATING, COMPLETE, CANCELLED


# ---------------------------------------------------------------------------
# LLMLineItem
# ---------------------------------------------------------------------------

class TestLLMLineItem:
    def _hourly(self, **overrides):
        base = {
            "service_date": "26/04/2026",
            "service_description": "DJ set",
            "time_start": "22:00",
            "time_end": "02:00",
            "rate": Decimal("500"),
            "rate_type": "hourly",
        }
        base.update(overrides)
        return LLMLineItem(**base)

    def test_valid_hourly(self):
        item = self._hourly()
        assert item.rate_type == "hourly"
        assert item.total is None

    def test_valid_flat(self):
        item = LLMLineItem(
            service_date="01/05/2026",
            rate=Decimal("2000"),
            rate_type="flat",
        )
        assert item.rate_type == "flat"
        assert item.time_start is None
        assert item.time_end is None
        assert item.total is None

    def test_total_is_always_none(self):
        # LLM must output null; passing a number should be rejected
        with pytest.raises(ValidationError):
            LLMLineItem(
                service_date="01/05/2026",
                rate_type="flat",
                total=2000,  # type: ignore[arg-type]
            )

    def test_service_date_rejects_iso_format(self):
        with pytest.raises(ValidationError, match="service_date must be DD/MM/YYYY"):
            self._hourly(service_date="2026-04-26")

    def test_service_date_rejects_plain_text(self):
        with pytest.raises(ValidationError, match="service_date must be DD/MM/YYYY"):
            self._hourly(service_date="Apr 26")

    def test_time_start_rejects_am_pm_format(self):
        with pytest.raises(ValidationError, match="time field must be HH:MM"):
            self._hourly(time_start="10pm")

    def test_time_end_rejects_single_digit_minutes(self):
        with pytest.raises(ValidationError, match="time field must be HH:MM"):
            self._hourly(time_end="22:0")

    def test_rate_type_rejects_invalid_value(self):
        with pytest.raises(ValidationError):
            self._hourly(rate_type="per_hour")  # type: ignore[arg-type]

    def test_optional_fields_default_to_none(self):
        item = LLMLineItem(service_date="01/05/2026", rate_type="flat")
        assert item.service_description is None
        assert item.rate is None


# ---------------------------------------------------------------------------
# LLMOutput
# ---------------------------------------------------------------------------

class TestLLMOutput:
    def _line_item_data(self):
        return {
            "service_date": "26/04/2026",
            "rate_type": "flat",
            "rate": 2000,
        }

    def test_valid_output(self):
        out = LLMOutput(line_items=[self._line_item_data()])
        assert out.client_id is None
        assert out.missing_fields == []
        assert len(out.line_items) == 1

    def test_missing_fields_defaults_to_empty_list(self):
        out = LLMOutput(line_items=[self._line_item_data()])
        assert out.missing_fields == []

    def test_missing_fields_populated(self):
        out = LLMOutput(
            client_id=None,
            line_items=[self._line_item_data()],
            missing_fields=["client_id", "rate"],
        )
        assert "client_id" in out.missing_fields

    def test_all_optional_fields_none(self):
        out = LLMOutput(line_items=[self._line_item_data()])
        assert out.client_id is None
        assert out.description is None


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

class TestSession:
    def test_defaults_to_pending(self):
        s = Session()
        assert s.state == PENDING

    def test_llm_call_count_starts_at_zero(self):
        assert Session().llm_call_count == 0

    def test_invoice_number_defaults_to_none(self):
        assert Session().invoice_number is None

    def test_message_id_defaults_to_none(self):
        assert Session().message_id is None

    def test_parsed_data_defaults_to_none(self):
        assert Session().parsed_data is None

    def test_created_at_is_timezone_aware(self):
        s = Session()
        assert s.created_at.tzinfo is not None
        assert s.created_at.tzinfo == timezone.utc

    def test_last_active_is_timezone_aware(self):
        s = Session()
        assert s.last_active.tzinfo is not None

    def test_state_constants_defined(self):
        assert PENDING == "PENDING"
        assert CONFIRMED == "CONFIRMED"
        assert GENERATING == "GENERATING"
        assert COMPLETE == "COMPLETE"
        assert CANCELLED == "CANCELLED"

    def test_state_can_be_updated(self):
        s = Session()
        s.state = CONFIRMED
        assert s.state == CONFIRMED
