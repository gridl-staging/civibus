"""Unit tests for campaign-finance CommitteeSummary model."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import get_args
from uuid import UUID

import pytest
from pydantic import ValidationError

from domains.campaign_finance.tests.model_payload_builders import (
    build_committee_summary_payload,
    build_uuid_string,
)
from domains.campaign_finance.types import CommitteeSummary


def _committee_summary_money_fields() -> list[str]:
    return [
        name
        for name, field_info in CommitteeSummary.model_fields.items()
        if _annotation_contains_decimal(field_info.annotation)
    ]


def _annotation_contains_decimal(annotation: object) -> bool:
    if annotation is Decimal:
        return True
    return any(_annotation_contains_decimal(argument) for argument in get_args(annotation))


def _assert_committee_summary_validation_error(**overrides: object) -> None:
    with pytest.raises(ValidationError):
        CommitteeSummary.model_validate(build_committee_summary_payload(**overrides))


@pytest.mark.parametrize("missing_field", ["committee_id", "cycle"])
def test_committee_summary_requires_committee_id_and_cycle(missing_field: str) -> None:
    _assert_committee_summary_validation_error(**{missing_field: None})


def test_committee_summary_allows_optional_source_record_id() -> None:
    without_source = CommitteeSummary.model_validate(build_committee_summary_payload(source_record_id=None))
    with_source = CommitteeSummary.model_validate(build_committee_summary_payload(source_record_id=build_uuid_string()))

    assert without_source.source_record_id is None
    assert isinstance(with_source.source_record_id, UUID)


def test_committee_summary_preserves_official_money_fields_as_decimals() -> None:
    summary = CommitteeSummary.model_validate(
        build_committee_summary_payload(
            total_receipts="12345.67",
            total_disbursements="2345.60",
            cash_on_hand="10000.07",
            individual_itemized_contributions="100.10",
            individual_unitemized_contributions="200.20",
            independent_expenditures="300.30",
        )
    )

    assert summary.total_receipts == Decimal("12345.67")
    assert summary.total_disbursements == Decimal("2345.60")
    assert summary.cash_on_hand == Decimal("10000.07")
    assert summary.individual_itemized_contributions == Decimal("100.10")
    assert summary.individual_unitemized_contributions == Decimal("200.20")
    assert summary.independent_expenditures == Decimal("300.30")


@pytest.mark.parametrize("invalid_amount", ["1.999", "1234567890123.45"])
def test_committee_summary_rejects_amounts_outside_numeric_14_2_contract(invalid_amount: str) -> None:
    rejected_fields = []

    for money_field in _committee_summary_money_fields():
        with pytest.raises(ValidationError):
            CommitteeSummary.model_validate(build_committee_summary_payload(**{money_field: invalid_amount}))
        rejected_fields.append(money_field)

    assert "total_receipts" in rejected_fields
    assert "cash_on_hand" in rejected_fields


def test_committee_summary_parses_coverage_dates() -> None:
    summary = CommitteeSummary.model_validate(
        build_committee_summary_payload(
            coverage_start_date="2024-01-01",
            coverage_end_date="2024-12-31",
        )
    )

    assert summary.coverage_start_date == date(2024, 1, 1)
    assert summary.coverage_end_date == date(2024, 12, 31)


def test_committee_summary_rejects_reversed_coverage_dates() -> None:
    _assert_committee_summary_validation_error(
        coverage_start_date="2024-12-31",
        coverage_end_date="2024-01-01",
    )


@pytest.mark.parametrize("extra_field", ["candidate_fec_id", "fec_election_year"])
def test_committee_summary_rejects_extra_candidate_relationship_fields(extra_field: str) -> None:
    _assert_committee_summary_validation_error(**{extra_field: "CANDIDATE-MIRROR"})


def test_committee_summary_round_trip_json_dump_and_validate() -> None:
    summary = CommitteeSummary.model_validate(
        build_committee_summary_payload(
            source_record_id=build_uuid_string(),
            total_receipts="12345.67",
            coverage_start_date="2024-01-01",
        )
    )

    dumped_json = summary.model_dump_json()
    restored = CommitteeSummary.model_validate_json(dumped_json)

    assert restored == summary
    assert restored.total_receipts == Decimal("12345.67")
    assert restored.coverage_start_date == date(2024, 1, 1)
