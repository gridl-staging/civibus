"""Unit tests for campaign-finance Filing model."""

from __future__ import annotations

from datetime import date
import pytest
from pydantic import ValidationError

from domains.campaign_finance.tests.model_payload_builders import (
    build_filing_payload,
    build_uuid_string,
)
from domains.campaign_finance.types import Filing


def _assert_filing_validation_error(**overrides: object) -> None:
    with pytest.raises(ValidationError):
        Filing.model_validate(build_filing_payload(**overrides))


@pytest.mark.parametrize(
    "missing_field",
    ["filing_fec_id", "committee_id", "amendment_indicator"],
)
def test_filing_requires_filing_fec_id_committee_and_amendment_indicator(missing_field: str):
    _assert_filing_validation_error(**{missing_field: None})


def test_filing_enforces_amendment_indicator_literal():
    _assert_filing_validation_error(amendment_indicator="N/A")
    _assert_filing_validation_error(amendment_indicator="a")


def test_filing_allows_optional_fields_and_fk_uuid_parsing():
    filing = Filing.model_validate(
        build_filing_payload(
            amendment_indicator="A",
            candidate_id=build_uuid_string(),
            election_id=build_uuid_string(),
            report_type="Q1",
            filing_name="Quarterly report",
            coverage_start_date=date(2024, 1, 1),
            coverage_end_date=date(2024, 3, 31),
            due_date=date(2024, 4, 15),
            receipt_date=date(2024, 4, 10),
            accepted_date=date(2024, 4, 12),
            amended_from_filing_id=build_uuid_string(),
            source_record_id=build_uuid_string(),
        )
    )

    assert filing.candidate_id is not None
    assert filing.election_id is not None
    assert filing.report_type == "Q1"
    assert filing.filing_name == "Quarterly report"
    assert filing.coverage_start_date == date(2024, 1, 1)
    assert filing.coverage_end_date == date(2024, 3, 31)
    assert filing.due_date == date(2024, 4, 15)
    assert filing.receipt_date == date(2024, 4, 10)
    assert filing.accepted_date == date(2024, 4, 12)
    assert filing.amended_from_filing_id is not None
    assert filing.source_record_id is not None


def test_filing_validates_coverage_range_and_parent_indicator():
    _assert_filing_validation_error(
        coverage_start_date=date(2024, 4, 1),
        coverage_end_date=date(2024, 3, 31),
    )

    Filing.model_validate(
        build_filing_payload(
            amendment_indicator="A",
            amended_from_filing_id=build_uuid_string(),
        )
    )
    Filing.model_validate(
        build_filing_payload(
            amendment_indicator="T",
            amended_from_filing_id=build_uuid_string(),
        )
    )
    _assert_filing_validation_error(
        amendment_indicator="N",
        amended_from_filing_id=build_uuid_string(),
    )


def test_filing_days_late_computes_exact_greatest_formula():
    with_receipt_and_due = Filing.model_validate(
        build_filing_payload(
            due_date=date(2024, 4, 1),
            receipt_date=date(2024, 3, 30),
        )
    )
    assert with_receipt_and_due.days_late == 0

    on_time = Filing.model_validate(
        build_filing_payload(
            due_date=date(2024, 4, 1),
            receipt_date=date(2024, 4, 1),
        )
    )
    assert on_time.days_late == 0

    late = Filing.model_validate(
        build_filing_payload(
            due_date=date(2024, 4, 1),
            receipt_date=date(2024, 4, 10),
        )
    )
    assert late.days_late == 9


def test_filing_days_late_requires_both_dates():
    assert Filing.model_validate(build_filing_payload(due_date=date(2024, 4, 1))).days_late is None
    assert Filing.model_validate(build_filing_payload(receipt_date=date(2024, 4, 10))).days_late is None


def test_filing_is_amended_derives_from_indicator():
    assert Filing.model_validate(build_filing_payload(amendment_indicator="A")).is_amended is True
    assert Filing.model_validate(build_filing_payload(amendment_indicator="N")).is_amended is False
    assert Filing.model_validate(build_filing_payload(amendment_indicator="T")).is_amended is False


def test_filing_generated_fields_ignore_direct_input_values():
    filing = Filing.model_validate(
        build_filing_payload(
            amendment_indicator="N",
            due_date=date(2024, 2, 1),
            receipt_date=date(2024, 2, 10),
            is_amended="stale",
            days_late="stale",
        )
    )

    assert filing.is_amended is False
    assert filing.days_late == 9


def test_filing_round_trip_dump_and_validate():
    filing = Filing.model_validate(
        build_filing_payload(
            amendment_indicator="A",
            amended_from_filing_id=build_uuid_string(),
            coverage_start_date=date(2024, 1, 1),
            coverage_end_date=date(2024, 1, 31),
            due_date=date(2024, 2, 1),
            receipt_date=date(2024, 2, 1),
            candidate_id=build_uuid_string(),
            election_id=build_uuid_string(),
        )
    )
    dumped = filing.model_dump(mode="json")
    schema = Filing.model_json_schema()

    assert dumped["is_amended"] is True
    assert dumped["days_late"] == 0
    assert "is_amended" in schema["properties"]
    assert "days_late" in schema["properties"]

    restored = Filing.model_validate(dumped)
    assert restored == filing
