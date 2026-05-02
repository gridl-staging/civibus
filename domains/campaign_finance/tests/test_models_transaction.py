"""Unit tests for campaign-finance Transaction model."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
import pytest
from pydantic import ValidationError

from domains.campaign_finance.tests.model_payload_builders import (
    build_transaction_payload,
    build_uuid_string,
)
from domains.campaign_finance.types import Transaction


def _assert_transaction_validation_error(**overrides: object) -> None:
    with pytest.raises(ValidationError):
        Transaction.model_validate(build_transaction_payload(**overrides))


@pytest.mark.parametrize(
    "missing_field",
    ["filing_id", "committee_id", "transaction_type", "amount", "amendment_indicator"],
)
def test_transaction_requires_filing_committee_type_amount_and_indicator(missing_field: str):
    _assert_transaction_validation_error(**{missing_field: None})


def test_transaction_enforces_amendment_indicator_literal():
    _assert_transaction_validation_error(amendment_indicator="bad")
    _assert_transaction_validation_error(amendment_indicator="n")


def test_transaction_allows_nullable_stage2_fields_and_uuid_fk_parsing():
    transaction = Transaction.model_validate(
        build_transaction_payload(
            transaction_identifier="T123",
            sub_id=123456789,
            transaction_date=date(2024, 1, 15),
            contributor_name_raw="Jane Doe",
            contributor_employer="Acme, Inc",
            contributor_occupation="Engineer",
            contributor_city="Atlanta",
            contributor_state="GA",
            contributor_zip="30332",
            contributor_person_id=build_uuid_string(),
            contributor_organization_id=None,
            contributor_address_id=build_uuid_string(),
            recipient_candidate_id=build_uuid_string(),
            recipient_committee_id=build_uuid_string(),
            memo_text="Optional note",
            amended_by_transaction_id=build_uuid_string(),
            source_record_id=build_uuid_string(),
        )
    )
    assert transaction.transaction_identifier == "T123"
    assert transaction.sub_id == 123456789
    assert transaction.transaction_date == date(2024, 1, 15)
    assert transaction.contributor_name_raw == "Jane Doe"
    assert transaction.contributor_employer == "Acme, Inc"
    assert transaction.contributor_occupation == "Engineer"
    assert transaction.contributor_city == "Atlanta"
    assert transaction.contributor_state == "GA"
    assert transaction.contributor_zip == "30332"
    assert transaction.contributor_person_id is not None
    assert transaction.contributor_organization_id is None
    assert transaction.contributor_address_id is not None
    assert transaction.recipient_candidate_id is not None
    assert transaction.recipient_committee_id is not None
    assert transaction.memo_text == "Optional note"
    assert transaction.amended_by_transaction_id is not None
    assert transaction.source_record_id is not None


def test_transaction_enforces_contributor_mutual_exclusivity():
    _assert_transaction_validation_error(
        contributor_person_id=build_uuid_string(),
        contributor_organization_id=build_uuid_string(),
    )


@pytest.mark.parametrize(
    ("memo_code", "expected_is_memo"),
    [("X", True), ("x", True), ("Y", False), (None, False)],
)
def test_transaction_derive_is_memo_from_memo_code(
    memo_code: str | None,
    expected_is_memo: bool,
):
    transaction = Transaction.model_validate(build_transaction_payload(memo_code=memo_code))
    assert transaction.is_memo is expected_is_memo


def test_transaction_contributor_state_is_2_chars_when_present():
    _assert_transaction_validation_error(contributor_state="G")
    _assert_transaction_validation_error(contributor_state="GAC")


def test_transaction_date_is_reliable_defaults_to_true():
    assert Transaction.model_validate(build_transaction_payload()).date_is_reliable is True


def test_transaction_amount_uses_exact_numeric_scale():
    transaction = Transaction.model_validate(build_transaction_payload(amount="0.10"))

    assert transaction.amount == Decimal("0.10")
    assert isinstance(transaction.amount, Decimal)

    with pytest.raises(ValidationError):
        Transaction.model_validate(build_transaction_payload(amount="1.234"))


def test_transaction_round_trip_dump_and_validate():
    transaction = Transaction.model_validate(
        build_transaction_payload(
            amount="150.10",
            memo_code="X",
            contributor_state="CA",
            contributor_person_id=build_uuid_string(),
            recipient_committee_id=build_uuid_string(),
            sub_id=42,
            transaction_identifier="TR-42",
            transaction_date=date(2024, 5, 5),
            memo_text="text",
            amended_by_transaction_id=build_uuid_string(),
            source_record_id=build_uuid_string(),
        )
    )
    dumped = transaction.model_dump(mode="json")
    assert dumped["amount"] == "150.10"
    restored = Transaction.model_validate(dumped)
    assert restored == transaction


def test_transaction_back_ref_transaction_id_round_trip_and_default_none():
    baseline = Transaction.model_validate(build_transaction_payload())
    assert baseline.back_ref_transaction_id is None

    transaction = Transaction.model_validate(
        build_transaction_payload(
            transaction_identifier="TR-43",
            back_ref_transaction_id="SB-BACKREF-001",
            sub_id=43,
        )
    )
    dumped = transaction.model_dump(mode="json")
    assert dumped["back_ref_transaction_id"] == "SB-BACKREF-001"

    restored = Transaction.model_validate(dumped)
    assert restored.back_ref_transaction_id == "SB-BACKREF-001"
