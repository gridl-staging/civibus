from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import psycopg
import pytest
from psycopg.rows import dict_row

from domains.campaign_finance.jurisdictions._test_helpers import (
    _source_record_count,
    clear_state_loader_records,
)
from domains.campaign_finance.jurisdictions.states.WA.scraper import load as wa_load
from domains.campaign_finance.jurisdictions.states.WA.scraper.load import (
    LoadResult,
    ensure_wa_data_source,
    load_wa_contribution,
    load_wa_contributions,
    load_wa_contributions_with_filings,
    load_wa_expenditure,
    load_wa_expenditures,
    load_wa_expenditures_with_filings,
    load_wa_independent_expenditures_with_filings,
    load_wa_loan,
    load_wa_loans,
    load_wa_loans_with_filings,
)
from domains.campaign_finance.jurisdictions.states.WA.scraper.parse import (
    parse_contributions,
    parse_expenditures,
    parse_independent_expenditures,
    parse_loans,
)

pytestmark = pytest.mark.integration

_FIXTURE_DIR = Path(__file__).parent / "test_fixtures"
_SAMPLE_CONTRIBUTIONS_PATH = _FIXTURE_DIR / "sample_contributions.csv"
_SAMPLE_EXPENDITURES_PATH = _FIXTURE_DIR / "sample_expenditures.csv"
_SAMPLE_INDEPENDENT_EXPENDITURES_PATH = _FIXTURE_DIR / "sample_independent_expenditures.csv"
_SAMPLE_LOANS_PATH = _FIXTURE_DIR / "sample_loans.csv"
_WA_JURISDICTION = "state/WA"
_WA_STATE_CODE = "WA"


def _parsed_contribution_rows() -> list[dict[str, str | None]]:
    return list(parse_contributions(_SAMPLE_CONTRIBUTIONS_PATH))


def _parsed_expenditure_rows() -> list[dict[str, str | None]]:
    return list(parse_expenditures(_SAMPLE_EXPENDITURES_PATH))


def _parsed_loan_rows() -> list[dict[str, str | None]]:
    return list(parse_loans(_SAMPLE_LOANS_PATH))


def _parsed_independent_expenditure_rows() -> list[dict[str, str | None]]:
    return list(parse_independent_expenditures(_SAMPLE_INDEPENDENT_EXPENDITURES_PATH))


def _source_record_urls(conn: psycopg.Connection, data_source_id) -> list[str]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT source_url
            FROM core.source_record
            WHERE data_source_id = %s
            ORDER BY created_at, id
            """,
            (data_source_id,),
        )
        return [row["source_url"] for row in cursor.fetchall()]


@pytest.fixture(autouse=True)
def _isolate_wa_loader_state(db_conn: psycopg.Connection) -> None:
    clear_state_loader_records(db_conn, jurisdiction=_WA_JURISDICTION, state_code=_WA_STATE_CODE)


def test_ensure_wa_data_source_is_idempotent(db_conn: psycopg.Connection) -> None:
    first_id = ensure_wa_data_source(db_conn, data_type="contributions")
    second_id = ensure_wa_data_source(db_conn, data_type="contributions")

    assert first_id == second_id


def test_ensure_wa_data_source_uses_distinct_names_per_data_type(db_conn: psycopg.Connection) -> None:
    contribution_source_id = ensure_wa_data_source(db_conn, data_type="contributions")
    expenditure_source_id = ensure_wa_data_source(db_conn, data_type="expenditures")
    loan_source_id = ensure_wa_data_source(db_conn, data_type="loans")

    assert contribution_source_id != expenditure_source_id
    assert expenditure_source_id != loan_source_id


def test_load_wa_contribution_row_deduplicates_by_source_record_key(db_conn: psycopg.Connection) -> None:
    row = _parsed_contribution_rows()[0]
    data_source_id = ensure_wa_data_source(db_conn, data_type="contributions")

    first_insert = load_wa_contribution(db_conn, row, data_source_id)
    second_insert = load_wa_contribution(db_conn, row, data_source_id)

    assert first_insert is True
    assert second_insert is False
    assert _source_record_count(db_conn, data_source_id) == 1


def test_load_wa_contribution_preserves_row_level_source_url(db_conn: psycopg.Connection) -> None:
    row = _parsed_contribution_rows()[0]
    data_source_id = ensure_wa_data_source(db_conn, data_type="contributions")

    inserted = load_wa_contribution(db_conn, row, data_source_id)

    assert inserted is True
    assert _source_record_urls(db_conn, data_source_id) == [row["url"]]


def test_load_wa_expenditure_row_deduplicates_by_source_record_key(db_conn: psycopg.Connection) -> None:
    row = _parsed_expenditure_rows()[0]
    data_source_id = ensure_wa_data_source(db_conn, data_type="expenditures")

    first_insert = load_wa_expenditure(db_conn, row, data_source_id)
    second_insert = load_wa_expenditure(db_conn, row, data_source_id)

    assert first_insert is True
    assert second_insert is False
    assert _source_record_count(db_conn, data_source_id) == 1


def test_load_wa_loan_row_deduplicates_by_source_record_key(db_conn: psycopg.Connection) -> None:
    row = _parsed_loan_rows()[0]
    data_source_id = ensure_wa_data_source(db_conn, data_type="loans")

    first_insert = load_wa_loan(db_conn, row, data_source_id)
    second_insert = load_wa_loan(db_conn, row, data_source_id)

    assert first_insert is True
    assert second_insert is False
    assert _source_record_count(db_conn, data_source_id) == 1


def test_load_wa_contributions_batch_loads_fixture(db_conn: psycopg.Connection) -> None:
    data_source_id = ensure_wa_data_source(db_conn, data_type="contributions")

    result = load_wa_contributions(db_conn, _SAMPLE_CONTRIBUTIONS_PATH, data_source_id=data_source_id)

    assert isinstance(result, LoadResult)
    assert result.inserted == 3
    assert result.skipped == 0
    assert result.quarantined == 0
    assert result.errors == 0


def test_load_wa_expenditures_batch_loads_fixture(db_conn: psycopg.Connection) -> None:
    data_source_id = ensure_wa_data_source(db_conn, data_type="expenditures")

    result = load_wa_expenditures(db_conn, _SAMPLE_EXPENDITURES_PATH, data_source_id=data_source_id)

    assert isinstance(result, LoadResult)
    assert result.inserted == 2
    assert result.skipped == 0
    assert result.quarantined == 0
    assert result.errors == 0


def test_load_wa_loans_batch_loads_fixture(db_conn: psycopg.Connection) -> None:
    data_source_id = ensure_wa_data_source(db_conn, data_type="loans")

    result = load_wa_loans(db_conn, _SAMPLE_LOANS_PATH, data_source_id=data_source_id)

    assert isinstance(result, LoadResult)
    assert result.inserted == 2
    assert result.skipped == 0
    assert result.quarantined == 0
    assert result.errors == 0


def test_load_wa_contributions_rolls_back_partial_row_failures(
    db_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_source_id = ensure_wa_data_source(db_conn, data_type="contributions")

    def _raise_after_source_record(*args, **kwargs) -> None:
        raise RuntimeError("boom after source record insert")

    monkeypatch.setattr(wa_load, "_load_wa_transaction_entities", _raise_after_source_record)

    result = load_wa_contributions(db_conn, _SAMPLE_CONTRIBUTIONS_PATH, data_source_id=data_source_id, limit=1)

    assert result.inserted == 0
    assert result.skipped == 0
    assert result.errors == 1
    assert _source_record_count(db_conn, data_source_id) == 0


def test_load_wa_contributions_with_filings_rolls_back_relational_row_failures(
    db_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_source_id = ensure_wa_data_source(db_conn, data_type="contributions")

    def _raise_during_relational_link(*args, **kwargs) -> None:
        raise RuntimeError("boom during filing-linked transaction upsert")

    monkeypatch.setattr(wa_load, "_upsert_wa_transaction_with_filing", _raise_during_relational_link)

    result = load_wa_contributions_with_filings(db_conn, _SAMPLE_CONTRIBUTIONS_PATH, limit=1)

    assert result.inserted == 1
    assert result.skipped == 0
    assert result.errors == 1
    assert _source_record_count(db_conn, data_source_id) == 1

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            "SELECT COUNT(*) AS count FROM cf.filing f JOIN cf.committee c ON c.id = f.committee_id WHERE c.state = 'WA'"
        )
        filing_count = cursor.fetchone()["count"]
        cursor.execute(
            "SELECT COUNT(*) AS count FROM cf.transaction t JOIN cf.committee c ON c.id = t.committee_id WHERE c.state = 'WA'"
        )
        transaction_count = cursor.fetchone()["count"]
        cursor.execute("SELECT COUNT(*) AS count FROM cf.committee WHERE state = 'WA'")
        committee_count = cursor.fetchone()["count"]

    assert filing_count == 0
    assert transaction_count == 0
    assert committee_count == 0


def test_load_wa_contributions_with_filings_builds_relational_rows(db_conn: psycopg.Connection) -> None:
    result = load_wa_contributions_with_filings(db_conn, _SAMPLE_CONTRIBUTIONS_PATH)

    assert result.inserted + result.skipped == 3
    assert result.errors == 0

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT f.filing_fec_id,
                   t.transaction_identifier,
                   t.contributor_address_id,
                   (
                       SELECT es.entity_id
                       FROM core.entity_source es
                       WHERE es.source_record_id = t.source_record_id
                         AND es.entity_type = 'address'
                         AND es.extraction_role = 'contributor_address'
                       LIMIT 1
                   ) AS expected_contributor_address_id
            FROM cf.transaction t
            JOIN cf.filing f
              ON f.id = t.filing_id
            WHERE f.filing_fec_id LIKE 'WA-%-contributions'
            ORDER BY t.transaction_identifier
            """,
        )
        transaction_rows = cursor.fetchall()

    assert {row["filing_fec_id"] for row in transaction_rows} == {
        "WA-9001-2025-contributions",
        "WA-9002-2025-contributions",
    }
    assert len(transaction_rows) == 3
    for row in transaction_rows:
        assert row["contributor_address_id"] == row["expected_contributor_address_id"]

    rerun_result = load_wa_contributions_with_filings(db_conn, _SAMPLE_CONTRIBUTIONS_PATH)
    assert rerun_result.inserted == 0
    assert rerun_result.skipped == 3
    assert rerun_result.errors == 0

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM cf.transaction t
            JOIN cf.filing f
              ON f.id = t.filing_id
            WHERE f.filing_fec_id LIKE 'WA-%-contributions'
            """,
        )
        transaction_count = cursor.fetchone()["count"]

    assert transaction_count == 3


def test_load_wa_expenditures_with_filings_maps_type_and_amount(db_conn: psycopg.Connection) -> None:
    result = load_wa_expenditures_with_filings(db_conn, _SAMPLE_EXPENDITURES_PATH)

    assert result.inserted + result.skipped == 2
    assert result.errors == 0

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT transaction_type,
                   amount,
                   contributor_address_id,
                   (
                       SELECT es.entity_id
                       FROM core.entity_source es
                       WHERE es.source_record_id = t.source_record_id
                         AND es.entity_type = 'address'
                         AND es.extraction_role = 'payee_address'
                       LIMIT 1
                   ) AS expected_contributor_address_id
            FROM cf.transaction t
            JOIN cf.filing f
              ON f.id = t.filing_id
            WHERE f.filing_fec_id LIKE 'WA-%-expenditures'
            ORDER BY amount DESC
            LIMIT 1
            """,
        )
        row = cursor.fetchone()

    assert row is not None
    assert row["transaction_type"] == "Advertising"
    assert row["amount"] == Decimal("315.25")
    assert row["contributor_address_id"] == row["expected_contributor_address_id"]

    rerun_result = load_wa_expenditures_with_filings(db_conn, _SAMPLE_EXPENDITURES_PATH)
    assert rerun_result.inserted == 0
    assert rerun_result.skipped == 2
    assert rerun_result.errors == 0

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM cf.transaction t
            JOIN cf.filing f
              ON f.id = t.filing_id
            WHERE f.filing_fec_id LIKE 'WA-%-expenditures'
            """,
        )
        transaction_count = cursor.fetchone()["count"]

    assert transaction_count == 2


def test_load_wa_loans_with_filings_maps_type_and_amount(db_conn: psycopg.Connection) -> None:
    result = load_wa_loans_with_filings(db_conn, _SAMPLE_LOANS_PATH)

    assert result.inserted + result.skipped == 2
    assert result.errors == 0

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT transaction_type,
                   amount,
                   contributor_address_id,
                   recipient_committee_id,
                   (
                       SELECT es.entity_id
                       FROM core.entity_source es
                       WHERE es.source_record_id = t.source_record_id
                         AND es.entity_type = 'address'
                         AND es.extraction_role = 'lender_address'
                       LIMIT 1
                   ) AS expected_contributor_address_id,
                   (
                       SELECT es.entity_id
                       FROM core.entity_source es
                       WHERE es.source_record_id = t.source_record_id
                         AND es.entity_type = 'organization'
                         AND es.extraction_role = 'borrower'
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
            WHERE f.filing_fec_id LIKE 'WA-%-loans'
            ORDER BY amount DESC
            LIMIT 1
            """,
        )
        row = cursor.fetchone()

    assert row is not None
    assert row["transaction_type"] == "New"
    assert row["amount"] == Decimal("1000.00")
    assert row["contributor_address_id"] == row["expected_contributor_address_id"]
    assert row["linked_committee_organization_id"] == row["expected_committee_organization_id"]

    rerun_result = load_wa_loans_with_filings(db_conn, _SAMPLE_LOANS_PATH)
    assert rerun_result.inserted == 0
    assert rerun_result.skipped == 2
    assert rerun_result.errors == 0

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM cf.transaction t
            JOIN cf.filing f
              ON f.id = t.filing_id
            WHERE f.filing_fec_id LIKE 'WA-%-loans'
            """,
        )
        transaction_count = cursor.fetchone()["count"]

    assert transaction_count == 2


def test_load_wa_expenditures_with_filings_handles_missing_transaction_type(
    tmp_path: Path,
    db_conn: psycopg.Connection,
) -> None:
    """Regression: live WA Socrata expenditure data sometimes has empty 'code' column.
    load_wa_expenditures_with_filings must not crash — it should default to 'expenditure'."""
    rows = _parsed_expenditure_rows()
    row = dict(rows[0])
    row["code"] = ""

    fixture_file = tmp_path / "expenditure_missing_code.csv"
    import csv

    with open(fixture_file, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(row.keys()))
        writer.writeheader()
        writer.writerow(row)

    result = load_wa_expenditures_with_filings(db_conn, fixture_file)

    assert result.inserted == 1
    assert result.errors == 0


def test_load_wa_independent_expenditures_with_filings_maps_support_oppose(
    db_conn: psycopg.Connection,
) -> None:
    result = load_wa_independent_expenditures_with_filings(db_conn, _SAMPLE_INDEPENDENT_EXPENDITURES_PATH)

    assert result.inserted + result.skipped == 2
    assert result.errors == 0

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT t.transaction_type, t.support_oppose, t.amount
            FROM cf.transaction t
            JOIN cf.filing f
              ON f.id = t.filing_id
            WHERE f.filing_fec_id LIKE 'WA-%-independent_expenditures'
            ORDER BY t.transaction_identifier
            """,
        )
        transaction_rows = cursor.fetchall()

    assert len(transaction_rows) == 2
    assert all(row["transaction_type"] == "Independent Expenditure" for row in transaction_rows)
    assert {row["support_oppose"] for row in transaction_rows} == {"S", "O"}
    assert {row["amount"] for row in transaction_rows} == {Decimal("500.00"), Decimal("350.00")}

    rerun_result = load_wa_independent_expenditures_with_filings(db_conn, _SAMPLE_INDEPENDENT_EXPENDITURES_PATH)
    assert rerun_result.inserted == 0
    assert rerun_result.skipped == 2
    assert rerun_result.errors == 0

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM cf.transaction t
            JOIN cf.filing f
              ON f.id = t.filing_id
            WHERE f.filing_fec_id LIKE 'WA-%-independent_expenditures'
            """,
        )
        transaction_count = cursor.fetchone()["count"]

    assert transaction_count == 2
