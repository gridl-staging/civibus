from __future__ import annotations

import csv
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from domains.campaign_finance.jurisdictions.states.CA.scraper._load_config import CAFilingLookupEntry
from domains.campaign_finance.jurisdictions.states.CA.scraper.load import (
    LoadResult,
    _build_address,
    _ca_is_f496_independent_expenditure,
    ensure_ca_data_source,
    load_ca_member_directory_with_filings,
)

pytestmark = pytest.mark.integration

_FIXTURE_DIR = Path(__file__).parent / "test_fixtures" / "sample_archive"
_BASE_FILER_ID = "C12345"
_BASE_FILING_ID = "F100"
_BASE_FILING_ID_2 = "F200"
_ISOLATED_ID_COLUMNS_BY_MEMBER = {
    "CVR_CAMPAIGN_DISCLOSURE_CD.TSV": ("FILER_ID", "FILING_ID"),
    "FILERNAME_CD.TSV": ("XREF_FILER_ID",),
    "FILERS_CD.TSV": ("FILER_ID",),
    "EXPN_CD.TSV": ("FILING_ID",),
    "LOAN_CD.TSV": ("FILING_ID",),
    "RCPT_CD.TSV": ("FILING_ID",),
}


def _build_isolated_member_fixture(
    tmp_path: Path,
) -> tuple[Path, str, str, str, dict[str, tuple[str, str]]]:
    fixture_suffix = uuid4().hex[:8].upper()
    isolated_filer_id = f"C{fixture_suffix[:6]}"
    isolated_filing_id = f"F{fixture_suffix[:6]}"
    isolated_filing_id_2 = f"G{fixture_suffix[:6]}"
    isolated_member_dir = tmp_path / f"sample_archive_{fixture_suffix.lower()}"
    isolated_member_dir.mkdir(parents=True, exist_ok=True)

    replacements = {
        _BASE_FILER_ID: isolated_filer_id,
        _BASE_FILING_ID: isolated_filing_id,
        _BASE_FILING_ID_2: isolated_filing_id_2,
    }
    for fixture_path in sorted(_FIXTURE_DIR.glob("*.TSV")):
        with fixture_path.open(encoding="utf-8", newline="") as input_file:
            reader = csv.DictReader(input_file, delimiter="\t")
            assert reader.fieldnames is not None
            rows = list(reader)

        id_columns = _ISOLATED_ID_COLUMNS_BY_MEMBER.get(fixture_path.name, ())
        for row in rows:
            for column in id_columns:
                value = row.get(column)
                if value in replacements:
                    row[column] = replacements[value]

        output_path = isolated_member_dir / fixture_path.name
        with output_path.open("w", encoding="utf-8", newline="") as output_file:
            writer = csv.DictWriter(output_file, fieldnames=reader.fieldnames, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)

    expected_filing_fec_id = f"CA-{isolated_filer_id}-{isolated_filing_id}-0"
    expected_filing_fec_id_2 = f"CA-{isolated_filer_id}-{isolated_filing_id_2}-0"
    expected_by_identifier = {
        f"EXPN_CD:{isolated_filing_id}:0:E1": ("PRINT", "250.00"),
        f"EXPN_CD:{isolated_filing_id_2}:0:E2": ("Independent Expenditure", "5000.00"),
        f"LOAN_CD:{isolated_filing_id}:0:L1": ("LOAN", "1000.00"),
        f"RCPT_CD:{isolated_filing_id}:0:R1": ("CONTRIBUTION", "500.00"),
    }
    return (
        isolated_member_dir,
        isolated_filer_id,
        expected_filing_fec_id,
        expected_filing_fec_id_2,
        expected_by_identifier,
    )


def _ca_data_source_count(conn: psycopg.Connection) -> int:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM core.data_source
            WHERE domain = 'campaign_finance'
              AND jurisdiction = 'state/CA'
              AND name = 'CAL-ACCESS Raw Data Export'
            """
        )
        return cursor.fetchone()["count"]


def test_ensure_ca_data_source_is_idempotent(db_conn: psycopg.Connection) -> None:
    first_id = ensure_ca_data_source(db_conn)
    second_id = ensure_ca_data_source(db_conn)

    assert isinstance(first_id, UUID)
    assert second_id == first_id
    assert _ca_data_source_count(db_conn) == 1


def test_load_ca_member_directory_with_filings_builds_relational_rows_and_is_idempotent(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    (
        isolated_member_dir,
        expected_filer_id,
        expected_filing_fec_id,
        _expected_filing_fec_id_2,
        expected_by_identifier,
    ) = _build_isolated_member_fixture(tmp_path)
    expected_transaction_identifiers = sorted(expected_by_identifier)

    def _fetch_relational_snapshot() -> tuple[int, int, list[dict[str, object]]]:
        with db_conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT COUNT(*) AS count
                FROM cf.filing
                WHERE filing_fec_id = %s
                """,
                (expected_filing_fec_id,),
            )
            filing_count = cursor.fetchone()["count"]

            cursor.execute(
                """
                SELECT COUNT(*) AS count
                FROM cf.committee c
                JOIN core.organization o
                  ON o.id = c.organization_id
                WHERE c.state = 'CA'
                  AND o.identifiers ->> 'ca_filer_id' = %s
                """,
                (expected_filer_id,),
            )
            committee_count = cursor.fetchone()["count"]

            cursor.execute(
                """
                SELECT t.transaction_identifier,
                       t.transaction_type,
                       t.amount::text AS amount,
                       f.filing_fec_id,
                       t.source_record_id,
                       t.contributor_person_id,
                       t.contributor_organization_id,
                       t.contributor_address_id,
                       (
                           SELECT es.entity_id
                           FROM core.entity_source es
                           WHERE es.source_record_id = t.source_record_id
                             AND es.entity_type = 'person'
                             AND es.extraction_role IN ('donor', 'payee', 'lender')
                           LIMIT 1
                       ) AS expected_contributor_person_id,
                       (
                           SELECT es.entity_id
                           FROM core.entity_source es
                           WHERE es.source_record_id = t.source_record_id
                             AND es.entity_type = 'organization'
                             AND es.extraction_role IN ('contributor', 'payee', 'lender')
                           LIMIT 1
                       ) AS expected_contributor_organization_id,
                       (
                           SELECT es.entity_id
                           FROM core.entity_source es
                           WHERE es.source_record_id = t.source_record_id
                             AND es.entity_type = 'address'
                             AND es.extraction_role IN ('donor_address', 'payee_address', 'lender_address')
                           LIMIT 1
                       ) AS expected_contributor_address_id,
                       (
                           SELECT es.entity_id
                           FROM core.entity_source es
                           WHERE es.source_record_id = t.source_record_id
                             AND es.entity_type = 'organization'
                             AND es.extraction_role IN ('recipient', 'payer', 'borrower')
                           LIMIT 1
                       ) AS linked_committee_organization_id,
                       (
                           SELECT c.organization_id
                           FROM cf.committee c
                           WHERE c.id = t.recipient_committee_id
                       ) AS expected_committee_organization_id
                FROM cf.transaction t
                JOIN cf.filing f
                  ON f.id = t.filing_id
                WHERE t.transaction_identifier = ANY(%s)
                ORDER BY t.transaction_identifier
                """,
                (expected_transaction_identifiers,),
            )
            return filing_count, committee_count, cursor.fetchall()

    first_result = load_ca_member_directory_with_filings(db_conn, isolated_member_dir)

    assert isinstance(first_result, LoadResult)
    assert first_result.inserted == 4
    assert first_result.skipped == 0
    assert first_result.quarantined == 0
    assert first_result.superseded == 0
    assert first_result.errors == 0

    filing_count, committee_count, transaction_rows = _fetch_relational_snapshot()
    data_source_id = ensure_ca_data_source(db_conn)
    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT id, source_record_key, record_hash, raw_fields
            FROM core.source_record
            WHERE data_source_id = %s
              AND source_record_key = ANY(%s)
              AND superseded_by IS NULL
            ORDER BY source_record_key
            """,
            (data_source_id, expected_transaction_identifiers),
        )
        source_record_snapshot = cursor.fetchall()

    assert filing_count == 1
    assert committee_count == 1
    assert [row["transaction_identifier"] for row in transaction_rows] == expected_transaction_identifiers
    assert [row["source_record_key"] for row in source_record_snapshot] == expected_transaction_identifiers

    expected_filing_fec_ids = {expected_filing_fec_id, _expected_filing_fec_id_2}
    for row in transaction_rows:
        expected_type, expected_amount = expected_by_identifier[row["transaction_identifier"]]
        assert row["transaction_type"] == expected_type
        assert row["amount"] == expected_amount
        assert row["filing_fec_id"] in expected_filing_fec_ids
        assert row["contributor_person_id"] == row["expected_contributor_person_id"]
        assert row["contributor_organization_id"] == row["expected_contributor_organization_id"]
        assert row["contributor_address_id"] == row["expected_contributor_address_id"]
        assert row["linked_committee_organization_id"] == row["expected_committee_organization_id"]

    rerun_result = load_ca_member_directory_with_filings(db_conn, isolated_member_dir)
    assert rerun_result.inserted == 0
    assert rerun_result.skipped == 4
    assert rerun_result.quarantined == 0
    assert rerun_result.superseded == 0
    assert rerun_result.errors == 0

    rerun_filing_count, rerun_committee_count, rerun_transaction_rows = _fetch_relational_snapshot()
    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT id, source_record_key, record_hash, raw_fields
            FROM core.source_record
            WHERE data_source_id = %s
              AND source_record_key = ANY(%s)
              AND superseded_by IS NULL
            ORDER BY source_record_key
            """,
            (data_source_id, expected_transaction_identifiers),
        )
        rerun_source_record_snapshot = cursor.fetchall()

    assert rerun_filing_count == filing_count
    assert rerun_committee_count == committee_count
    assert rerun_transaction_rows == transaction_rows
    assert rerun_source_record_snapshot == source_record_snapshot


def test_load_ca_member_directory_clears_preexisting_outer_transaction_and_commits(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    """Regression: clear stale outer txn so loader can manage commits safely."""
    isolated_member_dir, _, _, _, _ = _build_isolated_member_fixture(tmp_path)

    # Start a transaction before entering the loader; this reproduces the
    # stale non-IDLE connection state seen during interrupted live runs.
    with db_conn.cursor() as cursor:
        cursor.execute("SELECT 1")
    assert db_conn.info.transaction_status == psycopg.pq.TransactionStatus.INTRANS

    result = load_ca_member_directory_with_filings(db_conn, isolated_member_dir)

    assert isinstance(result, LoadResult)
    assert result.inserted == 4
    assert result.errors == 0
    assert db_conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE


def test_load_ca_member_directory_with_filings_rejects_negative_limit(
    db_conn: psycopg.Connection,
) -> None:
    with pytest.raises(ValueError, match="limit must be greater than or equal to 0"):
        load_ca_member_directory_with_filings(db_conn, _FIXTURE_DIR, limit=-1)


def test_load_ca_member_directory_reingest_keeps_filing_linked_to_active_source_record(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    isolated_member_dir, _, expected_filing_fec_id, _, _ = _build_isolated_member_fixture(tmp_path)
    cvr_path = isolated_member_dir / "CVR_CAMPAIGN_DISCLOSURE_CD.TSV"
    data_source_id = ensure_ca_data_source(db_conn)

    first_result = load_ca_member_directory_with_filings(db_conn, isolated_member_dir)
    assert first_result.errors == 0

    with cvr_path.open(encoding="utf-8", newline="") as input_file:
        reader = csv.DictReader(input_file, delimiter="\t")
        assert reader.fieldnames is not None
        cvr_rows = list(reader)

    assert cvr_rows
    source_record_key = f"CVR_CAMPAIGN_DISCLOSURE_CD:{cvr_rows[0]['FILING_ID']}:{cvr_rows[0]['AMEND_ID']}"
    cvr_rows[0]["RPT_DATE"] = "02/15/2025"

    with cvr_path.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=reader.fieldnames, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(cvr_rows)

    second_result = load_ca_member_directory_with_filings(db_conn, isolated_member_dir)
    third_result = load_ca_member_directory_with_filings(db_conn, isolated_member_dir)
    assert second_result.errors == 0
    assert third_result.errors == 0

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT source_record_id
            FROM cf.filing
            WHERE filing_fec_id = %s
            """,
            (expected_filing_fec_id,),
        )
        filing_row = cursor.fetchone()

        cursor.execute(
            """
            SELECT COUNT(*) FILTER (WHERE superseded_by IS NULL) AS active_count,
                   COUNT(*) FILTER (WHERE superseded_by IS NOT NULL) AS superseded_count,
                   (ARRAY_AGG(id) FILTER (WHERE superseded_by IS NULL))[1] AS active_source_record_id
            FROM core.source_record
            WHERE data_source_id = %s
              AND source_record_key = %s
            """,
            (data_source_id, source_record_key),
        )
        source_record_state = cursor.fetchone()

    assert filing_row is not None
    assert source_record_state is not None
    assert source_record_state["active_count"] == 1
    assert source_record_state["superseded_count"] == 1
    assert filing_row["source_record_id"] == source_record_state["active_source_record_id"]


def test_load_ca_member_directory_skips_malformed_cvr_rows_missing_filing_id(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    isolated_member_dir, _, _, _, _ = _build_isolated_member_fixture(tmp_path)
    cvr_path = isolated_member_dir / "CVR_CAMPAIGN_DISCLOSURE_CD.TSV"

    with cvr_path.open(encoding="utf-8", newline="") as input_file:
        reader = csv.DictReader(input_file, delimiter="\t")
        assert reader.fieldnames is not None
        cvr_rows = list(reader)

    assert cvr_rows
    for cvr_row in cvr_rows:
        cvr_row["FILING_ID"] = ""

    with cvr_path.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=reader.fieldnames, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(cvr_rows)

    result = load_ca_member_directory_with_filings(db_conn, isolated_member_dir)

    assert isinstance(result, LoadResult)
    assert result.inserted == 0
    assert result.skipped == 4
    assert result.quarantined == 0
    assert result.superseded == 0
    assert result.errors == 0


def test_load_ca_member_directory_falls_back_to_amendment_zero_when_transaction_amendment_missing(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    (
        isolated_member_dir,
        _expected_filer_id,
        expected_filing_fec_id,
        _expected_filing_fec_id_2,
        expected_by_identifier,
    ) = _build_isolated_member_fixture(tmp_path)
    rcpt_path = isolated_member_dir / "RCPT_CD.TSV"

    with rcpt_path.open(encoding="utf-8", newline="") as input_file:
        reader = csv.DictReader(input_file, delimiter="\t")
        assert reader.fieldnames is not None
        rcpt_rows = list(reader)

    assert rcpt_rows
    rcpt_rows[0]["AMEND_ID"] = "1"

    with rcpt_path.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=reader.fieldnames, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rcpt_rows)

    result = load_ca_member_directory_with_filings(db_conn, isolated_member_dir)

    rcpt_identifier = next(identifier for identifier in expected_by_identifier if identifier.startswith("RCPT_CD:"))
    rcpt_parts = rcpt_identifier.split(":")
    amended_rcpt_identifier = f"{rcpt_parts[0]}:{rcpt_parts[1]}:1:{rcpt_parts[3]}"

    assert result.inserted == 4
    assert result.skipped == 0
    assert result.errors == 0

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT t.transaction_identifier, f.filing_fec_id
            FROM cf.transaction t
            JOIN cf.filing f ON f.id = t.filing_id
            WHERE t.transaction_identifier = %s
            """,
            (amended_rcpt_identifier,),
        )
        row = cursor.fetchone()

    assert row is not None
    assert row["transaction_identifier"] == amended_rcpt_identifier
    assert row["filing_fec_id"] == expected_filing_fec_id


def test_f496_filing_classifies_expn_as_independent_expenditure(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    """EXPN_CD rows under F496 CVR filings should have transaction_type='Independent Expenditure'."""
    (
        isolated_member_dir,
        _expected_filer_id,
        expected_filing_fec_id,
        expected_filing_fec_id_2,
        expected_by_identifier,
    ) = _build_isolated_member_fixture(tmp_path)

    result = load_ca_member_directory_with_filings(db_conn, isolated_member_dir)
    assert result.errors == 0

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT t.transaction_identifier,
                   t.transaction_type,
                   f.filing_fec_id
            FROM cf.transaction t
            JOIN cf.filing f ON f.id = t.filing_id
            WHERE f.filing_fec_id IN (%s, %s)
              AND t.transaction_identifier LIKE 'EXPN_CD:%%'
            ORDER BY t.transaction_identifier
            """,
            (expected_filing_fec_id, expected_filing_fec_id_2),
        )
        expn_rows = cursor.fetchall()

    assert len(expn_rows) == 2

    # F460 expenditure retains original type
    f460_row = next(r for r in expn_rows if r["filing_fec_id"] == expected_filing_fec_id)
    assert f460_row["transaction_type"] == "PRINT"

    # F496 expenditure is classified as Independent Expenditure
    f496_row = next(r for r in expn_rows if r["filing_fec_id"] == expected_filing_fec_id_2)
    assert f496_row["transaction_type"] == "Independent Expenditure"


@pytest.mark.parametrize(
    ("raw_zip", "expected_zip5", "expected_zip4"),
    (
        ("95814-1234", "95814", "1234"),
        ("926562601", "92656", "2601"),
        ("95814", "95814", None),
    ),
)
def test_build_address_accepts_live_zip_variants(
    raw_zip: str,
    expected_zip5: str | None,
    expected_zip4: str | None,
) -> None:
    address = _build_address("Sacramento", "ca", raw_zip)

    assert address is not None
    assert address.city == "SACRAMENTO"
    assert address.state == "CA"
    assert address.zip5 == expected_zip5
    assert address.zip4 == expected_zip4


def test_build_address_drops_invalid_zip_parts_without_raising() -> None:
    address = _build_address("Sacramento", "CA", "ABC-XYZ")

    assert address is not None
    assert address.zip5 is None
    assert address.zip4 is None


# --- Unit tests for _ca_is_f496_independent_expenditure (no DB required) ---


def _make_filing_entry(form_type: str | None = None) -> CAFilingLookupEntry:
    return CAFilingLookupEntry(
        filing_id=uuid4(),
        committee_id=uuid4(),
        committee_organization_id=uuid4(),
        amendment_indicator="O",
        source_record_id=uuid4(),
        form_type=form_type,
    )


def test_f496_ie_true_for_expn_cd_with_f496_form_type() -> None:
    assert _ca_is_f496_independent_expenditure("EXPN_CD", _make_filing_entry("F496")) is True


def test_f496_ie_true_case_insensitive() -> None:
    assert _ca_is_f496_independent_expenditure("EXPN_CD", _make_filing_entry("f496")) is True


def test_f496_ie_false_for_wrong_table() -> None:
    assert _ca_is_f496_independent_expenditure("RCPT_CD", _make_filing_entry("F496")) is False


def test_f496_ie_false_for_none_form_type() -> None:
    assert _ca_is_f496_independent_expenditure("EXPN_CD", _make_filing_entry(None)) is False


def test_f496_ie_false_for_non_f496_form_type() -> None:
    assert _ca_is_f496_independent_expenditure("EXPN_CD", _make_filing_entry("F460")) is False
