from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

import psycopg
import pytest

from core.db import insert_data_source, insert_entity_source, insert_organization, insert_person, insert_source_record
from core.types.python.models import DataSource, Organization, Person, SourceRecord, compute_record_hash, utc_now

from domains.campaign_finance.ingest.bulk_transaction_loader import (
    build_filing_from_contribution,
    build_transaction_from_contribution,
    resolve_source_record_id,
)

pytestmark = pytest.mark.integration

_TEST_COMMITTEE_PREFIX = "test-btl-committee-"
_TEST_DATA_SOURCE_PREFIX = "Test BTL Source "
_TEST_SOURCE_RECORD_KEY_PREFIX = "test-btl-sr-"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _insert_test_committee(conn: psycopg.Connection, fec_id: str, name: str) -> UUID:
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO cf.committee (fec_committee_id, name) VALUES (%s, %s) RETURNING id",
            (fec_id, name),
        )
        return cursor.fetchone()[0]


def _insert_test_candidate(conn: psycopg.Connection, fec_id: str, name: str) -> UUID:
    office = fec_id[0]  # H, S, or P prefix
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO cf.candidate (fec_candidate_id, name, office) VALUES (%s, %s, %s) RETURNING id",
            (fec_id, name, office),
        )
        return cursor.fetchone()[0]


def _insert_test_data_source(conn: psycopg.Connection, label: str) -> UUID:
    ds = DataSource(
        domain="campaign_finance",
        jurisdiction="test/btl",
        name=f"{_TEST_DATA_SOURCE_PREFIX}{label}",
        source_url="https://example.test/btl",
    )
    insert_data_source(conn, ds)
    return ds.id


def _insert_test_source_record(conn: psycopg.Connection, data_source_id: UUID, key: str) -> UUID:
    raw_fields = {"test_key": key}
    sr = SourceRecord(
        data_source_id=data_source_id,
        source_record_key=f"{_TEST_SOURCE_RECORD_KEY_PREFIX}{key}",
        raw_fields=raw_fields,
        pull_date=utc_now(),
        record_hash=compute_record_hash(raw_fields),
    )
    return insert_source_record(conn, sr)


def _base_contribution_record(
    *,
    committee_fec_id: str = "C00100001",
    image_number: str | None = "202402019123456789",
    file_number: str | None = "1900001",
    amendment_indicator: str = "N",
    report_type: str = "Q1",
    transaction_type: str = "15",
    transaction_identifier: str | None = "A1001",
    sub_id: str | None = "900000000000001",
    memo_code: str | None = None,
    memo_text: str | None = None,
    contribution_receipt_amount: float | None = 250.00,
    contribution_receipt_date: str | None = "2024-01-15",
    contributor_name: str | None = "GARCIA, JOSE L",
    contributor_city: str | None = "MIAMI",
    contributor_state: str | None = "FL",
    contributor_zip: str | None = "331010001",
    contributor_employer: str | None = "ACME ENERGY",
    contributor_occupation: str | None = "ENGINEER",
    entity_type: str | None = "IND",
    other_id: str | None = None,
    **extra: object,
) -> dict[str, object]:
    record: dict[str, object] = {
        "committee_id": committee_fec_id,
        "image_number": image_number,
        "file_number": file_number,
        "amendment_indicator": amendment_indicator,
        "report_type": report_type,
        "transaction_type": transaction_type,
        "transaction_identifier": transaction_identifier,
        "sub_id": sub_id,
        "memo_code": memo_code,
        "memo_text": memo_text,
        "contribution_receipt_amount": contribution_receipt_amount,
        "contribution_receipt_date": contribution_receipt_date,
        "contributor_name": contributor_name,
        "contributor_city": contributor_city,
        "contributor_state": contributor_state,
        "contributor_zip": contributor_zip,
        "contributor_employer": contributor_employer,
        "contributor_occupation": contributor_occupation,
        "entity_type": entity_type,
        "other_id": other_id,
    }
    record.update(extra)
    return record


# ===========================================================================
# build_filing_from_contribution tests
# ===========================================================================


class TestBuildFilingFromContribution:
    """Pure builder: contribution record -> Filing model."""

    def test_uses_image_number_as_filing_fec_id(self, db_conn: psycopg.Connection) -> None:
        _insert_test_committee(db_conn, "C00100001", f"{_TEST_COMMITTEE_PREFIX}img")
        record = _base_contribution_record(
            image_number="202402019123456789",
            file_number="1900001",
        )
        filing = build_filing_from_contribution(db_conn, record)
        assert filing.filing_fec_id == "202402019123456789"

    def test_falls_back_to_file_number_when_image_number_missing(self, db_conn: psycopg.Connection) -> None:
        _insert_test_committee(db_conn, "C00100001", f"{_TEST_COMMITTEE_PREFIX}file")
        record = _base_contribution_record(
            image_number=None,
            file_number="1900001",
        )
        filing = build_filing_from_contribution(db_conn, record)
        assert filing.filing_fec_id == "1900001"

    def test_falls_back_to_synthetic_when_both_missing(self, db_conn: psycopg.Connection) -> None:
        _insert_test_committee(db_conn, "C00100001", f"{_TEST_COMMITTEE_PREFIX}synth")
        record = _base_contribution_record(
            image_number=None,
            file_number=None,
            amendment_indicator="N",
            report_type="Q1",
        )
        filing = build_filing_from_contribution(db_conn, record)
        assert filing.filing_fec_id == "FEC-C00100001-Q1-N"

    def test_maps_amendment_indicator(self, db_conn: psycopg.Connection) -> None:
        _insert_test_committee(db_conn, "C00100001", f"{_TEST_COMMITTEE_PREFIX}amend")
        record = _base_contribution_record(amendment_indicator="A")
        filing = build_filing_from_contribution(db_conn, record)
        assert filing.amendment_indicator == "A"

    def test_missing_amendment_indicator_raises_value_error(self, db_conn: psycopg.Connection) -> None:
        _insert_test_committee(db_conn, "C00100001", f"{_TEST_COMMITTEE_PREFIX}noamend")
        record = _base_contribution_record(amendment_indicator=None)
        with pytest.raises(ValueError, match="amendment_indicator"):
            build_filing_from_contribution(db_conn, record)

    def test_maps_report_type(self, db_conn: psycopg.Connection) -> None:
        _insert_test_committee(db_conn, "C00100001", f"{_TEST_COMMITTEE_PREFIX}rpt")
        record = _base_contribution_record(report_type="Q2")
        filing = build_filing_from_contribution(db_conn, record)
        assert filing.report_type == "Q2"

    def test_missing_report_type_raises_for_synthetic_filing_id(self, db_conn: psycopg.Connection) -> None:
        _insert_test_committee(db_conn, "C00100001", f"{_TEST_COMMITTEE_PREFIX}norpt")
        record = _base_contribution_record(image_number=None, file_number=None, report_type=None)
        with pytest.raises(ValueError, match="report_type"):
            build_filing_from_contribution(db_conn, record)

    def test_resolves_committee_id_from_fec_id(self, db_conn: psycopg.Connection) -> None:
        committee_id = _insert_test_committee(db_conn, "C00100001", f"{_TEST_COMMITTEE_PREFIX}resolve")
        record = _base_contribution_record(committee_fec_id="C00100001")
        filing = build_filing_from_contribution(db_conn, record)
        assert filing.committee_id == committee_id

    def test_raises_when_committee_not_found(self, db_conn: psycopg.Connection) -> None:
        record = _base_contribution_record(committee_fec_id="C99999999")
        with pytest.raises(ValueError, match="committee"):
            build_filing_from_contribution(db_conn, record)

    def test_attaches_source_record_id(self, db_conn: psycopg.Connection) -> None:
        _insert_test_committee(db_conn, "C00100001", f"{_TEST_COMMITTEE_PREFIX}sr")
        source_record_id = uuid4()
        record = _base_contribution_record()
        filing = build_filing_from_contribution(db_conn, record, source_record_id=source_record_id)
        assert filing.source_record_id == source_record_id


# ===========================================================================
# build_transaction_from_contribution tests
# ===========================================================================


class TestBuildTransactionFromContribution:
    """Pure builder: contribution record + filing_id -> Transaction model."""

    def test_maps_sub_id_as_integer(self, db_conn: psycopg.Connection) -> None:
        committee_id = _insert_test_committee(db_conn, "C00100001", f"{_TEST_COMMITTEE_PREFIX}subid")
        filing_id = uuid4()
        record = _base_contribution_record(sub_id="900000000000001")
        txn = build_transaction_from_contribution(
            db_conn,
            record,
            filing_id=filing_id,
            committee_id=committee_id,
        )
        assert txn.sub_id == 900000000000001
        assert isinstance(txn.sub_id, int)

    def test_maps_transaction_identifier_from_tran_id(self, db_conn: psycopg.Connection) -> None:
        committee_id = _insert_test_committee(db_conn, "C00100001", f"{_TEST_COMMITTEE_PREFIX}tranid")
        filing_id = uuid4()
        record = _base_contribution_record(transaction_identifier="A1001")
        txn = build_transaction_from_contribution(
            db_conn,
            record,
            filing_id=filing_id,
            committee_id=committee_id,
        )
        assert txn.transaction_identifier == "A1001"

    def test_maps_amount_as_decimal(self, db_conn: psycopg.Connection) -> None:
        committee_id = _insert_test_committee(db_conn, "C00100001", f"{_TEST_COMMITTEE_PREFIX}amt")
        filing_id = uuid4()
        record = _base_contribution_record(contribution_receipt_amount=250.50)
        txn = build_transaction_from_contribution(
            db_conn,
            record,
            filing_id=filing_id,
            committee_id=committee_id,
        )
        assert txn.amount == Decimal("250.50")

    def test_missing_amount_raises_value_error(self, db_conn: psycopg.Connection) -> None:
        committee_id = _insert_test_committee(db_conn, "C00100001", f"{_TEST_COMMITTEE_PREFIX}noamt")
        filing_id = uuid4()
        record = _base_contribution_record(contribution_receipt_amount=None)
        with pytest.raises(ValueError, match="contribution_receipt_amount"):
            build_transaction_from_contribution(
                db_conn,
                record,
                filing_id=filing_id,
                committee_id=committee_id,
            )

    def test_invalid_amount_raises_value_error(self, db_conn: psycopg.Connection) -> None:
        committee_id = _insert_test_committee(db_conn, "C00100001", f"{_TEST_COMMITTEE_PREFIX}badamt")
        filing_id = uuid4()
        record = _base_contribution_record(contribution_receipt_amount="not-a-number")
        with pytest.raises(ValueError, match="contribution_receipt_amount"):
            build_transaction_from_contribution(
                db_conn,
                record,
                filing_id=filing_id,
                committee_id=committee_id,
            )

    def test_maps_amendment_indicator(self, db_conn: psycopg.Connection) -> None:
        committee_id = _insert_test_committee(db_conn, "C00100001", f"{_TEST_COMMITTEE_PREFIX}txnamend")
        filing_id = uuid4()
        record = _base_contribution_record(amendment_indicator="A")
        txn = build_transaction_from_contribution(
            db_conn,
            record,
            filing_id=filing_id,
            committee_id=committee_id,
        )
        assert txn.amendment_indicator == "A"

    def test_maps_transaction_type(self, db_conn: psycopg.Connection) -> None:
        committee_id = _insert_test_committee(db_conn, "C00100001", f"{_TEST_COMMITTEE_PREFIX}txntype")
        filing_id = uuid4()
        record = _base_contribution_record(transaction_type="15E")
        txn = build_transaction_from_contribution(
            db_conn,
            record,
            filing_id=filing_id,
            committee_id=committee_id,
        )
        assert txn.transaction_type == "15E"

    def test_missing_transaction_type_raises_value_error(self, db_conn: psycopg.Connection) -> None:
        committee_id = _insert_test_committee(db_conn, "C00100001", f"{_TEST_COMMITTEE_PREFIX}notype")
        filing_id = uuid4()
        record = _base_contribution_record(transaction_type=None)
        with pytest.raises(ValueError, match="transaction_type"):
            build_transaction_from_contribution(
                db_conn,
                record,
                filing_id=filing_id,
                committee_id=committee_id,
            )

    def test_maps_contributor_fields(self, db_conn: psycopg.Connection) -> None:
        committee_id = _insert_test_committee(db_conn, "C00100001", f"{_TEST_COMMITTEE_PREFIX}contrib")
        filing_id = uuid4()
        record = _base_contribution_record(
            contributor_name="LEE, MAYA",
            contributor_city="AUSTIN",
            contributor_state="TX",
            contributor_zip="733010123",
            contributor_employer="LONE STAR TECH",
            contributor_occupation="ANALYST",
        )
        txn = build_transaction_from_contribution(
            db_conn,
            record,
            filing_id=filing_id,
            committee_id=committee_id,
        )
        assert txn.contributor_name_raw == "LEE, MAYA"
        assert txn.contributor_city == "AUSTIN"
        assert txn.contributor_state == "TX"
        assert txn.contributor_zip == "733010123"
        assert txn.contributor_employer == "LONE STAR TECH"
        assert txn.contributor_occupation == "ANALYST"

    def test_maps_memo_fields(self, db_conn: psycopg.Connection) -> None:
        committee_id = _insert_test_committee(db_conn, "C00100001", f"{_TEST_COMMITTEE_PREFIX}memo")
        filing_id = uuid4()
        record = _base_contribution_record(memo_code="X", memo_text="REFUND CHECK RETURNED")
        txn = build_transaction_from_contribution(
            db_conn,
            record,
            filing_id=filing_id,
            committee_id=committee_id,
        )
        assert txn.memo_code == "X"
        assert txn.memo_text == "REFUND CHECK RETURNED"
        assert txn.is_memo is True

    def test_maps_transaction_date(self, db_conn: psycopg.Connection) -> None:
        committee_id = _insert_test_committee(db_conn, "C00100001", f"{_TEST_COMMITTEE_PREFIX}date")
        filing_id = uuid4()
        record = _base_contribution_record(contribution_receipt_date="2024-01-15")
        txn = build_transaction_from_contribution(
            db_conn,
            record,
            filing_id=filing_id,
            committee_id=committee_id,
        )
        assert str(txn.transaction_date) == "2024-01-15"

    def test_none_sub_id_stays_none(self, db_conn: psycopg.Connection) -> None:
        committee_id = _insert_test_committee(db_conn, "C00100001", f"{_TEST_COMMITTEE_PREFIX}nosub")
        filing_id = uuid4()
        record = _base_contribution_record(sub_id=None, transaction_identifier="A1001")
        txn = build_transaction_from_contribution(
            db_conn,
            record,
            filing_id=filing_id,
            committee_id=committee_id,
        )
        assert txn.sub_id is None

    def test_non_numeric_sub_id_raises_value_error(self, db_conn: psycopg.Connection) -> None:
        committee_id = _insert_test_committee(db_conn, "C00100001", f"{_TEST_COMMITTEE_PREFIX}badsub")
        filing_id = uuid4()
        record = _base_contribution_record(sub_id="not-a-number")
        with pytest.raises(ValueError, match="sub_id must be numeric"):
            build_transaction_from_contribution(
                db_conn,
                record,
                filing_id=filing_id,
                committee_id=committee_id,
            )

    def test_resolves_candidate_from_candidate_fec_id(self, db_conn: psycopg.Connection) -> None:
        committee_id = _insert_test_committee(db_conn, "C00100001", f"{_TEST_COMMITTEE_PREFIX}cand")
        candidate_id = _insert_test_candidate(db_conn, "H0NC01001", "Test BTL Candidate Rivers")
        filing_id = uuid4()
        record = _base_contribution_record(candidate_fec_id="H0NC01001")
        txn = build_transaction_from_contribution(
            db_conn,
            record,
            filing_id=filing_id,
            committee_id=committee_id,
        )
        assert txn.recipient_candidate_id == candidate_id

    def test_missing_candidate_fec_id_leaves_recipient_none(self, db_conn: psycopg.Connection) -> None:
        committee_id = _insert_test_committee(db_conn, "C00100001", f"{_TEST_COMMITTEE_PREFIX}nocand")
        filing_id = uuid4()
        record = _base_contribution_record()  # itcont — no candidate_fec_id
        txn = build_transaction_from_contribution(
            db_conn,
            record,
            filing_id=filing_id,
            committee_id=committee_id,
        )
        assert txn.recipient_candidate_id is None

    def test_resolves_recipient_committee_from_other_id(self, db_conn: psycopg.Connection) -> None:
        committee_id = _insert_test_committee(db_conn, "C00100001", f"{_TEST_COMMITTEE_PREFIX}rcpt")
        recipient_committee_id = _insert_test_committee(db_conn, "C00100004", f"{_TEST_COMMITTEE_PREFIX}rcpt2")
        filing_id = uuid4()
        record = _base_contribution_record(other_id="C00100004")
        txn = build_transaction_from_contribution(
            db_conn,
            record,
            filing_id=filing_id,
            committee_id=committee_id,
        )
        assert txn.recipient_committee_id == recipient_committee_id

    def test_attaches_source_record_id(self, db_conn: psycopg.Connection) -> None:
        committee_id = _insert_test_committee(db_conn, "C00100001", f"{_TEST_COMMITTEE_PREFIX}txnsr")
        filing_id = uuid4()
        source_record_id = uuid4()
        record = _base_contribution_record()
        txn = build_transaction_from_contribution(
            db_conn,
            record,
            filing_id=filing_id,
            committee_id=committee_id,
            source_record_id=source_record_id,
        )
        assert txn.source_record_id == source_record_id

    def test_resolves_contributor_person_id_from_existing_provenance(self, db_conn: psycopg.Connection) -> None:
        committee_id = _insert_test_committee(db_conn, "C00100001", f"{_TEST_COMMITTEE_PREFIX}donorfk")
        filing_id = uuid4()
        data_source_id = _insert_test_data_source(db_conn, "donor-fk")
        source_record_id = _insert_test_source_record(db_conn, data_source_id, "donor-fk")
        person_id = insert_person(
            db_conn,
            Person(canonical_name="Test BTL Donor", first_name="Test", last_name="Donor"),
        )
        insert_entity_source(db_conn, "person", person_id, source_record_id, "donor")

        txn = build_transaction_from_contribution(
            db_conn,
            _base_contribution_record(),
            filing_id=filing_id,
            committee_id=committee_id,
            source_record_id=source_record_id,
        )

        assert txn.contributor_person_id == person_id
        assert txn.contributor_organization_id is None

    def test_resolves_contributor_organization_id_from_existing_provenance(
        self,
        db_conn: psycopg.Connection,
    ) -> None:
        committee_id = _insert_test_committee(db_conn, "C00100001", f"{_TEST_COMMITTEE_PREFIX}orgfk")
        filing_id = uuid4()
        data_source_id = _insert_test_data_source(db_conn, "org-fk")
        source_record_id = _insert_test_source_record(db_conn, data_source_id, "org-fk")
        organization_id = insert_organization(
            db_conn,
            Organization(canonical_name="Test BTL Contributor Org"),
        )
        insert_entity_source(db_conn, "organization", organization_id, source_record_id, "contributor")

        txn = build_transaction_from_contribution(
            db_conn,
            _base_contribution_record(entity_type="ORG"),
            filing_id=filing_id,
            committee_id=committee_id,
            source_record_id=source_record_id,
        )

        assert txn.contributor_person_id is None
        assert txn.contributor_organization_id == organization_id


# ===========================================================================
# resolve_source_record_id tests
# ===========================================================================


class TestResolveSourceRecordId:
    """Resolver for backfill: look up existing source_record by active key."""

    def test_returns_id_for_existing_active_record(self, db_conn: psycopg.Connection) -> None:
        ds_id = _insert_test_data_source(db_conn, "resolve-existing")
        sr_id = _insert_test_source_record(db_conn, ds_id, "resolve-existing-key")
        result = resolve_source_record_id(db_conn, ds_id, f"{_TEST_SOURCE_RECORD_KEY_PREFIX}resolve-existing-key")
        assert result == sr_id

    def test_returns_none_for_missing_record(self, db_conn: psycopg.Connection) -> None:
        ds_id = _insert_test_data_source(db_conn, "resolve-missing")
        result = resolve_source_record_id(db_conn, ds_id, "nonexistent-key")
        assert result is None

    def test_returns_none_for_superseded_record(self, db_conn: psycopg.Connection) -> None:
        ds_id = _insert_test_data_source(db_conn, "resolve-superseded")
        sr_id = _insert_test_source_record(db_conn, ds_id, "resolve-superseded-key")
        # Mark as superseded
        with db_conn.cursor() as cursor:
            cursor.execute(
                "UPDATE core.source_record SET superseded_by = %s WHERE id = %s",
                (sr_id, sr_id),
            )
        result = resolve_source_record_id(
            db_conn,
            ds_id,
            f"{_TEST_SOURCE_RECORD_KEY_PREFIX}resolve-superseded-key",
        )
        assert result is None
