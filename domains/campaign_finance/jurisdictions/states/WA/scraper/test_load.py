from __future__ import annotations

import csv
from collections import Counter
from contextlib import ExitStack
from datetime import date
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from domains.campaign_finance.jurisdictions._bulk_fixture_support import (
    BulkFixtureInterruption,
    bulk_fixture_entity_row_counts,
    bulk_fixture_row_counts,
    install_write_interrupt,
    suppress_first_writes,
)
from domains.campaign_finance.jurisdictions._test_helpers import (
    _source_record_count,
    clear_state_loader_records,
)
from domains.campaign_finance.jurisdictions.states.WA.scraper import load as wa_load
from domains.campaign_finance.jurisdictions.states.WA.scraper.load import (
    LoadResult,
    ensure_wa_data_source,
    filter_wa_contribution_page_changes,
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
from domains.campaign_finance.jurisdictions.states.WA.scraper.load_support import (
    WAIdentityAmbiguityError,
)
from domains.campaign_finance.jurisdictions.states.WA.scraper.load_test_support import (
    seed_wa_bulk_fixture,
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
_MIXED_INDEPENDENT_EXPENDITURES_PATH = _FIXTURE_DIR / "mixed_record_classes_independent_expenditures.csv"
_ONE_FILING_TWO_RECORD_CLASSES_PATH = _FIXTURE_DIR / "one_filing_two_record_classes_independent_expenditures.csv"
_SAMPLE_INDEPENDENT_EXPENDITURES_PATH = _FIXTURE_DIR / "sample_independent_expenditures.csv"
_SAMPLE_LOANS_PATH = _FIXTURE_DIR / "sample_loans.csv"
_WA_JURISDICTION = "state/WA"
_WA_STATE_CODE = "WA"
_C62_ORIGIN = "C6.2 - Itemized Expenditures"
_C63_ORIGIN = "C6.3 - Identified Entities"
_C65_ORIGIN = "C6.5 - Funding Sources"


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


def test_contribution_page_filter_uses_committed_source_hashes_as_resume_checkpoint(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    try:
        first_pass = load_wa_contributions_with_filings(db_conn, _SAMPLE_CONTRIBUTIONS_PATH, limit=2)
        changed_path = tmp_path / "changed.csv"

        page = filter_wa_contribution_page_changes(
            db_conn,
            _SAMPLE_CONTRIBUTIONS_PATH,
            changed_path,
        )

        assert first_pass.inserted == 2
        assert page.source_rows == 3
        assert page.changed_rows == 1
        assert page.path == changed_path
        assert [row["id"] for row in parse_contributions(changed_path)] == ["1003"]
    finally:
        db_conn.rollback()
        clear_state_loader_records(db_conn, jurisdiction=_WA_JURISDICTION, state_code=_WA_STATE_CODE)
        db_conn.commit()


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
            WHERE f.filing_fec_id IN ('WA-PDC:RPT-1001', 'WA-PDC:RPT-1002', 'WA-PDC:RPT-1003')
            ORDER BY t.transaction_identifier
            """,
        )
        transaction_rows = cursor.fetchall()

    assert {row["filing_fec_id"] for row in transaction_rows} == {
        "WA-PDC:RPT-1001",
        "WA-PDC:RPT-1002",
        "WA-PDC:RPT-1003",
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
            WHERE f.filing_fec_id IN ('WA-PDC:RPT-1001', 'WA-PDC:RPT-1002', 'WA-PDC:RPT-1003')
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
            WHERE f.filing_fec_id IN ('WA-PDC:RPT-2001', 'WA-PDC:RPT-2002')
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
            WHERE f.filing_fec_id IN ('WA-PDC:RPT-2001', 'WA-PDC:RPT-2002')
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
            WHERE f.filing_fec_id IN ('WA-PDC:RPT-3001', 'WA-PDC:RPT-3002')
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
            WHERE f.filing_fec_id IN ('WA-PDC:RPT-3001', 'WA-PDC:RPT-3002')
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
            WHERE f.filing_fec_id IN ('WA-PDC:RPT-IE-1001', 'WA-PDC:RPT-IE-1002')
            ORDER BY t.transaction_identifier
            """,
        )
        transaction_rows = cursor.fetchall()

    assert len(transaction_rows) == 2
    assert all(row["transaction_type"] == "Independent Expenditure" for row in transaction_rows)
    assert {row["support_oppose"] for row in transaction_rows} == {None}
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
            WHERE f.filing_fec_id IN ('WA-PDC:RPT-IE-1001', 'WA-PDC:RPT-IE-1002')
            """,
        )
        transaction_count = cursor.fetchone()["count"]

    assert transaction_count == 2


def test_load_wa_independent_expenditures_routes_each_record_class(
    db_conn: psycopg.Connection,
) -> None:
    data_source_id = ensure_wa_data_source(db_conn, data_type="independent_expenditures")

    result = load_wa_independent_expenditures_with_filings(db_conn, _MIXED_INDEPENDENT_EXPENDITURES_PATH)

    assert result.inserted == 7
    # The two C6.5 fixture rows are recognized but do not land a transaction, so they are
    # counted as skips by the relational pass — never as errors.
    assert result.skipped == 2
    assert result.errors == 0

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT sr.raw_fields->>'origin' AS origin,
                   COUNT(*) AS transaction_count,
                   SUM(t.amount) AS amount_sum,
                   ARRAY_AGG(DISTINCT t.transaction_type ORDER BY t.transaction_type) AS transaction_types
            FROM cf.transaction t
            JOIN core.source_record sr
              ON sr.id = t.source_record_id
            JOIN cf.filing f
              ON f.id = t.filing_id
            WHERE sr.data_source_id = %s
            GROUP BY sr.raw_fields->>'origin'
            """,
            (data_source_id,),
        )
        transaction_summary = {row["origin"]: row for row in cursor.fetchall()}

        cursor.execute(
            """
            SELECT sr.raw_fields->>'origin' AS origin,
                   sr.raw_fields->>'for_or_against' AS for_or_against,
                   t.id AS transaction_id,
                   t.support_oppose
            FROM core.source_record sr
            LEFT JOIN cf.transaction t
              ON t.source_record_id = sr.id
            WHERE sr.data_source_id = %s
            """,
            (data_source_id,),
        )
        source_rows = cursor.fetchall()

    assert set(transaction_summary) == {_C62_ORIGIN, _C63_ORIGIN}
    assert transaction_summary[_C62_ORIGIN]["transaction_count"] == 2
    assert transaction_summary[_C62_ORIGIN]["amount_sum"] == Decimal("9235.61")
    assert set(transaction_summary[_C62_ORIGIN]["transaction_types"]) == {
        "Independent Expenditure",
        "Independent Expenditure Ad",
    }
    assert transaction_summary[_C63_ORIGIN]["transaction_count"] == 3
    assert transaction_summary[_C63_ORIGIN]["amount_sum"] == Decimal("36237.86")
    assert set(transaction_summary[_C63_ORIGIN]["transaction_types"]) == {_C63_ORIGIN}
    assert all(
        not transaction_type.startswith(("1", "2"))
        for summary in transaction_summary.values()
        for transaction_type in summary["transaction_types"]
    )

    assert Counter(row["origin"] for row in source_rows) == {
        _C62_ORIGIN: 2,
        _C63_ORIGIN: 3,
        _C65_ORIGIN: 2,
    }
    assert {(row["for_or_against"], row["support_oppose"]) for row in source_rows if row["origin"] == _C63_ORIGIN} == {
        ("For", "S"),
        ("Against", "O"),
        (None, None),
    }
    assert {row["support_oppose"] for row in source_rows if row["origin"] == _C62_ORIGIN} == {None}
    assert all(row["transaction_id"] is None for row in source_rows if row["origin"] == _C65_ORIGIN)


def _wa_ie_filing_dates(conn: psycopg.Connection) -> dict[str, tuple[object, object]]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT filing_fec_id, receipt_date, accepted_date
            FROM cf.filing
            WHERE filing_fec_id IN ('WA-PDC:3072', 'WA-PDC:13720')
            """,
        )
        return {row["filing_fec_id"]: (row["receipt_date"], row["accepted_date"]) for row in cursor.fetchall()}


@pytest.mark.parametrize("reverse_row_order", [False, True])
def test_wa_ie_filing_date_is_record_class_independent(
    db_conn: psycopg.Connection,
    tmp_path: Path,
    reverse_row_order: bool,
) -> None:
    # The two record classes share a committee and year but carry distinct PDC report
    # numbers. Neither transaction date proves filing receipt or acceptance lifecycle.

    rows = list(csv.DictReader(_ONE_FILING_TWO_RECORD_CLASSES_PATH.open()))
    assert {row["origin"] for row in rows} == {_C62_ORIGIN, _C63_ORIGIN}
    assert {row["sponsor_id"] for row in rows} == {"115"}

    ordered_rows = list(reversed(rows)) if reverse_row_order else rows
    fixture_file = tmp_path / "one_filing_two_record_classes.csv"
    with open(fixture_file, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()), quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(ordered_rows)

    result = load_wa_independent_expenditures_with_filings(db_conn, fixture_file)

    assert result.inserted == 2
    assert result.skipped == 0
    assert result.errors == 0
    assert _wa_ie_filing_dates(db_conn) == {
        "WA-PDC:3072": (None, None),
        "WA-PDC:13720": (None, None),
    }


# --- Stage 4: the relational pass commits each completed batch mid-loop -------
#
# `_EXPECTED_DURABLE_BATCH_ROWS` is a frozen literal, deliberately NOT read from
# `wa_load._COMMIT_BATCH_ROWS`. The falsifiability probe for these specimens
# monkeypatches that module constant above the fixture size; an expectation derived
# from the live constant would move with the probe and they could never go red.

_EXPECTED_DURABLE_BATCH_ROWS = 1_000
_WA_BULK_ROW_COUNT = _EXPECTED_DURABLE_BATCH_ROWS + 1
# Rows whose provenance insert is suppressed, so the relational pass finds no source
# record for them, skips them, and must still count them towards the boundary.
_WA_SKIPPED_PROVENANCE_ROWS = 3
# The fixture gives every row a distinct contributor but one shared street and one
# shared committee, so a completed provenance pass writes exactly this footprint.
_WA_LOADED_ADDRESS_ROWS = 1
_WA_LOADED_COMMITTEE_ROWS = 1


def test_load_wa_with_filings_commits_relational_batch_mid_loop(
    db_conn: psycopg.Connection,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An interrupt after 1,000 relational rows leaves exactly those 1,000 durable.

    Before Stage 4 the relational pass committed once, at the end of the job, so this
    interruption discarded every linked row and an independent connection saw zero.
    """
    with ExitStack() as resources:
        fixture = seed_wa_bulk_fixture(resources, db_conn, tmp_path, row_count=_WA_BULK_ROW_COUNT)
        write_counts = install_write_interrupt(
            monkeypatch,
            wa_load,
            "_upsert_wa_transaction_with_filing",
            raise_after_writes=_EXPECTED_DURABLE_BATCH_ROWS,
        )

        with pytest.raises(BulkFixtureInterruption):
            load_wa_contributions_with_filings(db_conn, fixture.contributions_path)
        db_conn.rollback()

        # The source-record pass ran to completion and flushed all of its rows; the
        # relational pass was interrupted on row 1,001, so exactly its first full batch
        # of transactions is durable.
        assert write_counts["writes"] == _WA_BULK_ROW_COUNT
        source_record_count, transaction_count = bulk_fixture_row_counts(fixture)
        assert source_record_count == _WA_BULK_ROW_COUNT
        assert transaction_count == _EXPECTED_DURABLE_BATCH_ROWS

        # The completed provenance pass also created the contributor, address, and
        # committee rows behind those transactions. The stack's cleanup deletes them and
        # then re-reads this same count, so a cleanup that stops covering them — and
        # quietly grows the shared database on every run — fails this specimen.
        assert bulk_fixture_entity_row_counts(fixture) == {
            "person": _WA_BULK_ROW_COUNT,
            "organization": _WA_LOADED_COMMITTEE_ROWS,
            "address": _WA_LOADED_ADDRESS_ROWS,
            "committee": _WA_LOADED_COMMITTEE_ROWS,
        }


def test_load_wa_relational_batch_boundary_advances_on_skipped_rows(
    db_conn: psycopg.Connection,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rows the relational pass skips still advance its commit boundary.

    Three rows are denied a source record, so the relational pass skips them without
    writing anything. The boundary counts iterated rows rather than linked ones, so it
    still fires on iteration 1,000 — with only 997 transactions written by then. Counting
    linked rows instead would push the first commit three rows later, past the interrupt,
    and leave nothing durable.
    """
    with ExitStack() as resources:
        fixture = seed_wa_bulk_fixture(resources, db_conn, tmp_path, row_count=_WA_BULK_ROW_COUNT)
        suppress_first_writes(
            monkeypatch,
            wa_load,
            "try_insert_source_record",
            suppress_first=_WA_SKIPPED_PROVENANCE_ROWS,
        )
        expected_durable_transactions = _EXPECTED_DURABLE_BATCH_ROWS - _WA_SKIPPED_PROVENANCE_ROWS
        write_counts = install_write_interrupt(
            monkeypatch,
            wa_load,
            "_upsert_wa_transaction_with_filing",
            raise_after_writes=expected_durable_transactions,
        )

        with pytest.raises(BulkFixtureInterruption):
            load_wa_contributions_with_filings(db_conn, fixture.contributions_path)
        db_conn.rollback()

        assert write_counts["writes"] == expected_durable_transactions + 1
        source_record_count, transaction_count = bulk_fixture_row_counts(fixture)
        assert source_record_count == _WA_BULK_ROW_COUNT - _WA_SKIPPED_PROVENANCE_ROWS
        assert transaction_count == expected_durable_transactions


@pytest.mark.parametrize(
    ("loader", "fixture_path", "parser", "data_source_name", "dataset_id"),
    [
        (
            load_wa_contributions_with_filings,
            _SAMPLE_CONTRIBUTIONS_PATH,
            parse_contributions,
            "WA PDC Contributions",
            "kv7h-kjye",
        ),
        (
            load_wa_expenditures_with_filings,
            _SAMPLE_EXPENDITURES_PATH,
            parse_expenditures,
            "WA PDC Expenditures",
            "tijg-9zyp",
        ),
        (
            load_wa_independent_expenditures_with_filings,
            _SAMPLE_INDEPENDENT_EXPENDITURES_PATH,
            parse_independent_expenditures,
            "WA PDC Independent Expenditures",
            "67cp-h962",
        ),
        (
            load_wa_loans_with_filings,
            _SAMPLE_LOANS_PATH,
            parse_loans,
            "WA PDC Loans",
            "d2ig-r3q4",
        ),
    ],
)
def test_wa_native_identity_and_report_number_own_transaction_provenance(
    db_conn: psycopg.Connection,
    loader,
    fixture_path: Path,
    parser,
    data_source_name: str,
    dataset_id: str,
) -> None:
    source_rows = list(parser(fixture_path))
    expected = {
        (
            f"WA-PDC:{row['report_number']}",
            f"WA-PDC:{dataset_id}:{row['id']}",
            row["report_number"],
        )
        for row in source_rows
    }

    result = loader(db_conn, fixture_path)

    assert result.errors == 0
    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT f.filing_fec_id,
                   t.transaction_identifier,
                   transaction_source.source_record_key,
                   transaction_source.raw_fields->>'report_number' AS transaction_report_number,
                   filing_source.raw_fields->>'report_number' AS filing_report_number
            FROM cf.transaction AS t
            JOIN cf.filing AS f
              ON f.id = t.filing_id
            JOIN core.source_record AS transaction_source
              ON transaction_source.id = t.source_record_id
            JOIN core.source_record AS filing_source
              ON filing_source.id = f.source_record_id
            JOIN core.data_source AS data_source
              ON data_source.id = transaction_source.data_source_id
            WHERE data_source.name = %s
              AND transaction_source.superseded_by IS NULL
            ORDER BY t.transaction_identifier
            """,
            (data_source_name,),
        )
        persisted = cursor.fetchall()

    assert {
        (
            row["filing_fec_id"],
            row["transaction_identifier"],
            row["transaction_report_number"],
        )
        for row in persisted
    } == expected
    assert all(row["source_record_key"] == row["transaction_identifier"] for row in persisted)
    assert all(row["filing_report_number"] == row["transaction_report_number"] for row in persisted)


def test_wa_missing_report_number_retains_source_without_filing_claim(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    row = dict(_parsed_contribution_rows()[0])
    row["report_number"] = " "
    fixture_path = tmp_path / "missing_report_number.csv"
    with fixture_path.open("w", encoding="utf-8", newline="") as fixture_file:
        writer = csv.DictWriter(fixture_file, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)

    result = load_wa_contributions_with_filings(db_conn, fixture_path)

    assert result.inserted == 1
    assert result.errors == 1
    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT source_record_key, raw_fields->>'report_number' AS report_number
            FROM core.source_record AS source_record
            JOIN core.data_source AS data_source
              ON data_source.id = source_record.data_source_id
            WHERE data_source.name = 'WA PDC Contributions'
              AND source_record.superseded_by IS NULL
            """
        )
        source_records = cursor.fetchall()
        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM cf.filing AS filing
            JOIN cf.committee AS committee
              ON committee.id = filing.committee_id
            WHERE committee.state = 'WA'
            """
        )
        filing_count = cursor.fetchone()["count"]
        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM cf.transaction AS transaction
            JOIN cf.committee AS committee
              ON committee.id = transaction.committee_id
            WHERE committee.state = 'WA'
            """
        )
        transaction_count = cursor.fetchone()["count"]
        cursor.execute("SELECT COUNT(*) AS count FROM cf.committee WHERE state = 'WA'")
        committee_count = cursor.fetchone()["count"]

    assert source_records == [{"source_record_key": "WA-PDC:kv7h-kjye:1001", "report_number": " "}]
    assert filing_count == 0
    assert transaction_count == 0
    assert committee_count == 0


def test_wa_correction_supersedes_source_and_updates_one_transaction(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    original_row = dict(_parsed_contribution_rows()[0])
    fixture_path = tmp_path / "corrected_contribution.csv"

    def _write_row(row: dict[str, str | None]) -> None:
        with fixture_path.open("w", encoding="utf-8", newline="") as fixture_file:
            writer = csv.DictWriter(fixture_file, fieldnames=list(row))
            writer.writeheader()
            writer.writerow(row)

    _write_row(original_row)
    first_result = load_wa_contributions_with_filings(db_conn, fixture_path)
    assert first_result.errors == 0

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT transaction.id
            FROM cf.transaction AS transaction
            JOIN core.source_record AS source_record
              ON source_record.id = transaction.source_record_id
            WHERE source_record.raw_fields->>'id' = '1001'
            """
        )
        original_transaction_id = cursor.fetchone()["id"]

    corrected_row = dict(original_row)
    corrected_row["amount"] = "199.99"
    corrected_row["description"] = "Corrected contribution"
    _write_row(corrected_row)

    correction_result = load_wa_contributions_with_filings(db_conn, fixture_path)

    assert correction_result.inserted == 1
    assert correction_result.errors == 0
    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT source_record.id,
                   source_record.source_record_key,
                   source_record.superseded_by,
                   source_record.raw_fields->>'amount' AS amount
            FROM core.source_record AS source_record
            JOIN core.data_source AS data_source
              ON data_source.id = source_record.data_source_id
            WHERE data_source.name = 'WA PDC Contributions'
              AND source_record.raw_fields->>'id' = '1001'
            ORDER BY source_record.created_at, source_record.id
            """
        )
        source_revisions = cursor.fetchall()
        cursor.execute(
            """
            SELECT transaction.id,
                   transaction.transaction_identifier,
                   transaction.amount,
                   transaction.source_record_id,
                   source_record.superseded_by
            FROM cf.transaction AS transaction
            JOIN core.source_record AS source_record
              ON source_record.id = transaction.source_record_id
            WHERE source_record.source_record_key = 'WA-PDC:kv7h-kjye:1001'
            """
        )
        transactions = cursor.fetchall()

    active_source = next(row for row in source_revisions if row["superseded_by"] is None)
    superseded_source = next(row for row in source_revisions if row["superseded_by"] is not None)
    assert len(source_revisions) == 2
    assert {row["source_record_key"] for row in source_revisions} == {"WA-PDC:kv7h-kjye:1001"}
    assert active_source["amount"] == "199.99"
    assert superseded_source["superseded_by"] == active_source["id"]
    assert transactions == [
        {
            "id": original_transaction_id,
            "transaction_identifier": "WA-PDC:kv7h-kjye:1001",
            "amount": Decimal("199.99"),
            "source_record_id": active_source["id"],
            "superseded_by": None,
        }
    ]


def _write_wa_rows(fixture_path: Path, rows: list[dict[str, str | None]]) -> None:
    with fixture_path.open("w", encoding="utf-8", newline="") as fixture_file:
        writer = csv.DictWriter(fixture_file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _legacyize_wa_landed_claim(
    conn: psycopg.Connection,
    *,
    row: dict[str, str | None],
    data_source_id,
    data_type: str,
    memo_text: str | None = None,
) -> dict[str, object]:
    stable_key = wa_load._wa_source_record_key(row, data_type=data_type)
    record_class = wa_load._resolve_wa_ie_record_class(row, data_type)
    legacy_filing_fec_id = wa_load._build_wa_legacy_filing_fec_id(
        row,
        data_type,
        record_class=record_class,
    )
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT source_record.id AS source_record_id,
                   source_record.record_hash,
                   transaction.id AS transaction_id,
                   transaction.transaction_date,
                   filing.id AS filing_id,
                   (
                       SELECT COUNT(*)
                       FROM core.entity_source AS entity_source
                       WHERE entity_source.source_record_id = source_record.id
                   ) AS entity_source_count
            FROM core.source_record AS source_record
            JOIN cf.transaction AS transaction
              ON transaction.source_record_id = source_record.id
            JOIN cf.filing AS filing
              ON filing.id = transaction.filing_id
            WHERE source_record.data_source_id = %s
              AND source_record.source_record_key = %s
              AND source_record.superseded_by IS NULL
            """,
            (data_source_id, stable_key),
        )
        identity = cursor.fetchone()
        assert identity is not None
        cursor.execute(
            """
            UPDATE cf.filing
            SET filing_fec_id = %s,
                native_filing_id = %s,
                report_type = %s,
                receipt_date = %s,
                accepted_date = %s
            WHERE id = %s
            """,
            (
                legacy_filing_fec_id,
                legacy_filing_fec_id,
                data_type,
                identity["transaction_date"],
                identity["transaction_date"],
                identity["filing_id"],
            ),
        )
        cursor.execute(
            """
            UPDATE cf.transaction
            SET native_transaction_id = %s,
                transaction_identifier = %s,
                memo_text = %s
            WHERE id = %s
            """,
            (
                identity["record_hash"],
                identity["record_hash"],
                memo_text,
                identity["transaction_id"],
            ),
        )
        cursor.execute(
            "UPDATE core.source_record SET source_record_key = %s WHERE id = %s",
            (identity["record_hash"], identity["source_record_id"]),
        )
    return {**identity, "legacy_filing_fec_id": legacy_filing_fec_id}


def test_wa_legacy_hash_identity_migrates_without_reference_or_enrichment_loss(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    row = dict(_parsed_contribution_rows()[0])
    row.update(id="legacy-1001", report_number="LEGACY-RPT-1001")
    fixture_path = tmp_path / "legacy_contribution.csv"
    _write_wa_rows(fixture_path, [row])

    assert load_wa_contributions_with_filings(db_conn, fixture_path).errors == 0
    data_source_id = ensure_wa_data_source(db_conn, data_type="contributions")
    legacy = _legacyize_wa_landed_claim(
        db_conn,
        row=row,
        data_source_id=data_source_id,
        data_type="contributions",
        memo_text="preserve migrated enrichment",
    )
    result = load_wa_contributions_with_filings(db_conn, fixture_path)

    assert result.inserted == 0
    assert result.skipped == 1
    assert result.errors == 0
    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT source_record.id AS source_record_id,
                   source_record.source_record_key,
                   source_record.raw_fields,
                   transaction.id AS transaction_id,
                   transaction.transaction_identifier,
                   transaction.memo_text,
                   filing.id AS filing_id,
                   filing.filing_fec_id,
                   filing.report_type,
                   filing.receipt_date,
                   filing.accepted_date,
                   (
                       SELECT COUNT(*)
                       FROM core.entity_source AS entity_source
                       WHERE entity_source.source_record_id = source_record.id
                   ) AS entity_source_count
            FROM core.source_record AS source_record
            JOIN cf.transaction AS transaction
              ON transaction.source_record_id = source_record.id
            JOIN cf.filing AS filing
              ON filing.id = transaction.filing_id
            WHERE source_record.data_source_id = %s
            """,
            (data_source_id,),
        )
        migrated = cursor.fetchone()
        cursor.execute("SELECT COUNT(*) AS count FROM core.source_record WHERE data_source_id = %s", (data_source_id,))
        source_count = cursor.fetchone()["count"]
        cursor.execute("SELECT COUNT(*) AS count FROM cf.filing WHERE id = %s", (legacy["filing_id"],))
        legacy_filing_count = cursor.fetchone()["count"]

    assert source_count == 1
    assert migrated["source_record_id"] == legacy["source_record_id"]
    assert migrated["transaction_id"] == legacy["transaction_id"]
    assert migrated["source_record_key"] == "WA-PDC:kv7h-kjye:legacy-1001"
    assert migrated["transaction_identifier"] == migrated["source_record_key"]
    assert migrated["raw_fields"] == row
    assert migrated["memo_text"] == "preserve migrated enrichment"
    assert migrated["entity_source_count"] == legacy["entity_source_count"]
    assert migrated["filing_fec_id"] == "WA-PDC:LEGACY-RPT-1001"
    assert migrated["report_type"] is None
    assert migrated["receipt_date"] is None
    assert migrated["accepted_date"] is None
    assert legacy_filing_count == 0


def test_wa_legacy_migration_rolls_back_on_protected_filing_state(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    row = dict(_parsed_contribution_rows()[0])
    row.update(id="legacy-rollback", report_number="LEGACY-ROLLBACK")
    fixture_path = tmp_path / "legacy_rollback.csv"
    _write_wa_rows(fixture_path, [row])
    assert load_wa_contributions_with_filings(db_conn, fixture_path).errors == 0
    data_source_id = ensure_wa_data_source(db_conn, data_type="contributions")
    legacy = _legacyize_wa_landed_claim(
        db_conn,
        row=row,
        data_source_id=data_source_id,
        data_type="contributions",
    )
    with db_conn.cursor() as cursor:
        cursor.execute(
            "UPDATE cf.filing SET coverage_start_date = DATE '2025-01-01' WHERE id = %s",
            (legacy["filing_id"],),
        )
    with pytest.raises(WAIdentityAmbiguityError, match="non-loader-owned state"):
        load_wa_contributions_with_filings(db_conn, fixture_path)
    assert db_conn.info.transaction_status == psycopg.pq.TransactionStatus.INTRANS

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            "SELECT source_record_key FROM core.source_record WHERE id = %s",
            (legacy["source_record_id"],),
        )
        source_record_key = cursor.fetchone()["source_record_key"]
        cursor.execute(
            "SELECT filing_id, transaction_identifier FROM cf.transaction WHERE id = %s",
            (legacy["transaction_id"],),
        )
        transaction = cursor.fetchone()
        cursor.execute(
            "SELECT filing_fec_id, coverage_start_date FROM cf.filing WHERE id = %s",
            (legacy["filing_id"],),
        )
        filing = cursor.fetchone()
        cursor.execute("SELECT COUNT(*) AS count FROM cf.filing WHERE filing_fec_id = 'WA-PDC:LEGACY-ROLLBACK'")
        report_filing_count = cursor.fetchone()["count"]

    assert source_record_key == legacy["record_hash"]
    assert transaction == {
        "filing_id": legacy["filing_id"],
        "transaction_identifier": legacy["record_hash"],
    }
    assert filing == {
        "filing_fec_id": legacy["legacy_filing_fec_id"],
        "coverage_start_date": date.fromisoformat("2025-01-01"),
    }
    assert report_filing_count == 0


def test_wa_legacy_migration_rejects_duplicate_native_source_owners(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    row = dict(_parsed_contribution_rows()[0])
    row.update(id="legacy-duplicate", report_number="LEGACY-DUPLICATE")
    fixture_path = tmp_path / "legacy_duplicate.csv"
    _write_wa_rows(fixture_path, [row])
    assert load_wa_contributions_with_filings(db_conn, fixture_path).errors == 0
    data_source_id = ensure_wa_data_source(db_conn, data_type="contributions")
    legacy = _legacyize_wa_landed_claim(
        db_conn,
        row=row,
        data_source_id=data_source_id,
        data_type="contributions",
    )
    duplicate_row = dict(row)
    duplicate_row["amount"] = "999.99"
    duplicate_hash = wa_load._wa_record_hash(duplicate_row)
    with db_conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO core.source_record (
                data_source_id,
                source_record_key,
                source_url,
                raw_fields,
                pull_date,
                record_hash
            )
            VALUES (%s, %s, %s, %s, NOW(), %s)
            """,
            (
                data_source_id,
                duplicate_hash,
                duplicate_row["url"],
                Jsonb(duplicate_row),
                duplicate_hash,
            ),
        )

    with pytest.raises(WAIdentityAmbiguityError, match="multiple active rows"):
        load_wa_contributions_with_filings(db_conn, fixture_path)

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT source_record_key
            FROM core.source_record
            WHERE data_source_id = %s
            ORDER BY source_record_key
            """,
            (data_source_id,),
        )
        source_keys = [source["source_record_key"] for source in cursor.fetchall()]
        cursor.execute(
            "SELECT filing_id, transaction_identifier FROM cf.transaction WHERE id = %s",
            (legacy["transaction_id"],),
        )
        transaction = cursor.fetchone()

    assert source_keys == sorted([legacy["record_hash"], duplicate_hash])
    assert transaction == {
        "filing_id": legacy["filing_id"],
        "transaction_identifier": legacy["record_hash"],
    }


def test_wa_incomplete_legacy_c65_source_rekeys_without_filing_identity(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    row = next(
        dict(candidate)
        for candidate in parse_independent_expenditures(_MIXED_INDEPENDENT_EXPENDITURES_PATH)
        if candidate["origin"] == _C65_ORIGIN
    )
    row["election_year"] = ""
    row["date_received"] = ""
    fixture_path = tmp_path / "incomplete_c65.csv"
    _write_wa_rows(fixture_path, [row])
    assert load_wa_independent_expenditures_with_filings(db_conn, fixture_path).errors == 0
    data_source_id = ensure_wa_data_source(db_conn, data_type="independent_expenditures")
    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            "SELECT id, record_hash FROM core.source_record WHERE data_source_id = %s",
            (data_source_id,),
        )
        source = cursor.fetchone()
        cursor.execute(
            "UPDATE core.source_record SET source_record_key = %s WHERE id = %s",
            (source["record_hash"], source["id"]),
        )
    result = load_wa_independent_expenditures_with_filings(db_conn, fixture_path)

    assert result.errors == 0
    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            "SELECT id, source_record_key, raw_fields FROM core.source_record WHERE data_source_id = %s",
            (data_source_id,),
        )
        migrated_source = cursor.fetchone()
        cursor.execute(
            "SELECT COUNT(*) AS count FROM cf.transaction WHERE source_record_id = %s",
            (source["id"],),
        )
        transaction_count = cursor.fetchone()["count"]

    assert migrated_source["id"] == source["id"]
    assert migrated_source["source_record_key"] == f"WA-PDC:67cp-h962:{row['id']}"
    assert migrated_source["raw_fields"]["id"] == row["id"]
    assert migrated_source["raw_fields"]["election_year"] is None
    assert migrated_source["raw_fields"]["date_received"] is None
    assert transaction_count == 0


@pytest.mark.parametrize("missing_report_last", [False, True])
def test_wa_same_file_revisions_link_only_the_active_record_hash(
    db_conn: psycopg.Connection,
    tmp_path: Path,
    missing_report_last: bool,
) -> None:
    valid_row = dict(_parsed_contribution_rows()[0])
    valid_row.update(id="same-file-revision", report_number="SAME-FILE-REPORT")
    missing_report_row = dict(valid_row)
    missing_report_row.update(report_number=" ", amount="151.25")
    rows = [valid_row, missing_report_row] if missing_report_last else [missing_report_row, valid_row]
    fixture_path = tmp_path / f"same_file_{missing_report_last}.csv"
    _write_wa_rows(fixture_path, rows)

    result = load_wa_contributions_with_filings(db_conn, fixture_path)

    assert result.inserted == 2
    assert result.errors == (1 if missing_report_last else 0)
    data_source_id = ensure_wa_data_source(db_conn, data_type="contributions")
    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT id, superseded_by, raw_fields->>'report_number' AS report_number
            FROM core.source_record
            WHERE data_source_id = %s
            ORDER BY created_at, id
            """,
            (data_source_id,),
        )
        source_revisions = cursor.fetchall()
        cursor.execute(
            """
            SELECT filing.filing_fec_id, transaction.source_record_id
            FROM cf.transaction AS transaction
            JOIN cf.filing AS filing
              ON filing.id = transaction.filing_id
            JOIN core.source_record AS source_record
              ON source_record.id = transaction.source_record_id
            WHERE source_record.data_source_id = %s
            """,
            (data_source_id,),
        )
        claims = cursor.fetchall()

    active_source = next(source for source in source_revisions if source["superseded_by"] is None)
    assert len(source_revisions) == 2
    if missing_report_last:
        assert active_source["report_number"] == " "
        assert claims == []
    else:
        assert active_source["report_number"] == "SAME-FILE-REPORT"
        assert claims == [
            {
                "filing_fec_id": "WA-PDC:SAME-FILE-REPORT",
                "source_record_id": active_source["id"],
            }
        ]


def test_wa_missing_report_correction_removes_prior_claim(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    valid_row = dict(_parsed_contribution_rows()[0])
    valid_row.update(id="missing-correction", report_number="PRIOR-REPORT")
    fixture_path = tmp_path / "missing_report_correction.csv"
    _write_wa_rows(fixture_path, [valid_row])
    assert load_wa_contributions_with_filings(db_conn, fixture_path).errors == 0

    corrected_row = dict(valid_row)
    corrected_row.update(report_number=" ", amount="152.25")
    _write_wa_rows(fixture_path, [corrected_row])
    result = load_wa_contributions_with_filings(db_conn, fixture_path)

    assert result.inserted == 1
    assert result.errors == 1
    data_source_id = ensure_wa_data_source(db_conn, data_type="contributions")
    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT raw_fields->>'report_number' AS report_number
            FROM core.source_record
            WHERE data_source_id = %s
              AND superseded_by IS NULL
            """,
            (data_source_id,),
        )
        active_source = cursor.fetchone()
        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM cf.transaction AS transaction
            JOIN core.source_record AS source_record
              ON source_record.id = transaction.source_record_id
            WHERE source_record.data_source_id = %s
            """,
            (data_source_id,),
        )
        transaction_count = cursor.fetchone()["count"]
        cursor.execute("SELECT COUNT(*) AS count FROM cf.filing WHERE filing_fec_id = 'WA-PDC:PRIOR-REPORT'")
        filing_count = cursor.fetchone()["count"]

    assert active_source["report_number"] == " "
    assert transaction_count == 0
    assert filing_count == 0


def test_wa_c65_correction_removes_prior_claim(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    landed_row = dict(_parsed_independent_expenditure_rows()[0])
    landed_row.update(id="c65-correction", report_number="C65-CORRECTION")
    fixture_path = tmp_path / "c65_correction.csv"
    _write_wa_rows(fixture_path, [landed_row])
    assert load_wa_independent_expenditures_with_filings(db_conn, fixture_path).errors == 0

    c65_row = dict(landed_row)
    c65_row["origin"] = _C65_ORIGIN
    c65_row["report_number"] = " "
    _write_wa_rows(fixture_path, [c65_row])
    result = load_wa_independent_expenditures_with_filings(db_conn, fixture_path)

    assert result.inserted == 1
    assert result.skipped == 1
    assert result.errors == 0
    data_source_id = ensure_wa_data_source(db_conn, data_type="independent_expenditures")
    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT raw_fields->>'origin' AS origin
            FROM core.source_record
            WHERE data_source_id = %s
              AND superseded_by IS NULL
            """,
            (data_source_id,),
        )
        active_source = cursor.fetchone()
        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM cf.transaction AS transaction
            JOIN core.source_record AS source_record
              ON source_record.id = transaction.source_record_id
            WHERE source_record.data_source_id = %s
            """,
            (data_source_id,),
        )
        transaction_count = cursor.fetchone()["count"]
        cursor.execute("SELECT COUNT(*) AS count FROM cf.filing WHERE filing_fec_id = 'WA-PDC:C65-CORRECTION'")
        filing_count = cursor.fetchone()["count"]

    assert active_source["origin"] == _C65_ORIGIN
    assert transaction_count == 0
    assert filing_count == 0


def test_wa_report_number_correction_removes_vacated_report_filing(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    original_row = dict(_parsed_contribution_rows()[0])
    original_row.update(id="report-correction", report_number="REPORT-A")
    fixture_path = tmp_path / "report_number_correction.csv"
    _write_wa_rows(fixture_path, [original_row])
    assert load_wa_contributions_with_filings(db_conn, fixture_path).errors == 0
    data_source_id = ensure_wa_data_source(db_conn, data_type="contributions")
    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT transaction.id
            FROM cf.transaction AS transaction
            JOIN core.source_record AS source_record
              ON source_record.id = transaction.source_record_id
            WHERE source_record.data_source_id = %s
            """,
            (data_source_id,),
        )
        transaction_id = cursor.fetchone()["id"]

    corrected_row = dict(original_row)
    corrected_row.update(report_number="REPORT-B", amount="154.25")
    _write_wa_rows(fixture_path, [corrected_row])
    result = load_wa_contributions_with_filings(db_conn, fixture_path)

    assert result.inserted == 1
    assert result.errors == 0
    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT transaction.id,
                   filing.filing_fec_id,
                   source_record.raw_fields->>'report_number' AS report_number,
                   source_record.superseded_by
            FROM cf.transaction AS transaction
            JOIN cf.filing AS filing
              ON filing.id = transaction.filing_id
            JOIN core.source_record AS source_record
              ON source_record.id = transaction.source_record_id
            WHERE source_record.data_source_id = %s
            """,
            (data_source_id,),
        )
        transaction = cursor.fetchone()
        cursor.execute(
            """
            SELECT filing_fec_id
            FROM cf.filing
            WHERE filing_fec_id IN ('WA-PDC:REPORT-A', 'WA-PDC:REPORT-B')
            """
        )
        filing_ids = [row["filing_fec_id"] for row in cursor.fetchall()]

    assert transaction == {
        "id": transaction_id,
        "filing_fec_id": "WA-PDC:REPORT-B",
        "report_number": "REPORT-B",
        "superseded_by": None,
    }
    assert filing_ids == ["WA-PDC:REPORT-B"]


def test_wa_report_collision_rolls_back_reference_changes(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    first_row = dict(_parsed_contribution_rows()[0])
    first_row.update(id="collision-first", report_number="COLLISION-REPORT")
    fixture_path = tmp_path / "report_collision.csv"
    _write_wa_rows(fixture_path, [first_row])
    assert load_wa_contributions_with_filings(db_conn, fixture_path).errors == 0
    data_source_id = ensure_wa_data_source(db_conn, data_type="contributions")
    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT filing.id AS filing_id,
                   filing.committee_id,
                   filing.source_record_id,
                   transaction.id AS transaction_id
            FROM cf.filing AS filing
            JOIN cf.transaction AS transaction
              ON transaction.filing_id = filing.id
            WHERE filing.filing_fec_id = 'WA-PDC:COLLISION-REPORT'
            """
        )
        before = cursor.fetchone()
    conflicting_row = dict(_parsed_contribution_rows()[1])
    conflicting_row.update(id="collision-second", report_number="COLLISION-REPORT")
    _write_wa_rows(fixture_path, [conflicting_row])
    with pytest.raises(WAIdentityAmbiguityError, match="persisted committee"):
        load_wa_contributions_with_filings(db_conn, fixture_path)
    assert db_conn.info.transaction_status == psycopg.pq.TransactionStatus.INTRANS

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT filing.id AS filing_id,
                   filing.committee_id,
                   filing.source_record_id,
                   transaction.id AS transaction_id
            FROM cf.filing AS filing
            JOIN cf.transaction AS transaction
              ON transaction.filing_id = filing.id
            WHERE filing.filing_fec_id = 'WA-PDC:COLLISION-REPORT'
            """
        )
        after = cursor.fetchone()
        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM cf.transaction AS transaction
            JOIN core.source_record AS source_record
              ON source_record.id = transaction.source_record_id
            WHERE source_record.data_source_id = %s
            """,
            (data_source_id,),
        )
        transaction_count = cursor.fetchone()["count"]

    assert after == before
    assert transaction_count == 1


def test_wa_report_provenance_rejects_cross_source_owner(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    row = dict(_parsed_contribution_rows()[0])
    row.update(id="foreign-source-owner", report_number="FOREIGN-SOURCE-REPORT")
    fixture_path = tmp_path / "foreign_source_owner.csv"
    _write_wa_rows(fixture_path, [row])
    assert load_wa_contributions_with_filings(db_conn, fixture_path).errors == 0
    data_source_id = ensure_wa_data_source(db_conn, data_type="contributions")

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT filing.id AS filing_id,
                   filing.source_record_id,
                   transaction.id AS transaction_id
            FROM cf.filing AS filing
            JOIN cf.transaction AS transaction
              ON transaction.filing_id = filing.id
            WHERE filing.filing_fec_id = 'WA-PDC:FOREIGN-SOURCE-REPORT'
            """
        )
        original = cursor.fetchone()
        cursor.execute(
            """
            INSERT INTO core.data_source (
                domain,
                jurisdiction,
                filing_authority_type,
                filing_authority_code,
                name,
                source_url,
                source_format
            )
            VALUES (
                'campaign_finance',
                'state/OR',
                'state',
                'OR',
                'Foreign report owner fixture',
                'https://example.invalid',
                'csv'
            )
            RETURNING id
            """
        )
        foreign_data_source_id = cursor.fetchone()["id"]
        cursor.execute(
            """
            INSERT INTO core.source_record (
                data_source_id,
                source_record_key,
                source_url,
                raw_fields,
                pull_date,
                record_hash
            )
            SELECT %s,
                   'foreign-report-owner',
                   source_url,
                   raw_fields,
                   pull_date,
                   record_hash
            FROM core.source_record
            WHERE id = %s
            RETURNING id
            """,
            (foreign_data_source_id, original["source_record_id"]),
        )
        foreign_source_record_id = cursor.fetchone()["id"]
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with db_conn.transaction():
            with db_conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE cf.filing SET source_record_id = %s WHERE id = %s",
                    (foreign_source_record_id, original["filing_id"]),
                )

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            "SELECT source_record_id FROM cf.filing WHERE id = %s",
            (original["filing_id"],),
        )
        filing_source_record_id = cursor.fetchone()["source_record_id"]
        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM cf.transaction AS transaction
            JOIN core.source_record AS source_record
              ON source_record.id = transaction.source_record_id
            WHERE source_record.data_source_id = %s
            """,
            (data_source_id,),
        )
        transaction_count = cursor.fetchone()["count"]

    assert filing_source_record_id == original["source_record_id"]
    assert transaction_count == 1


def test_wa_multirow_report_filing_source_advances_on_owner_correction(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    owner_row = dict(_parsed_contribution_rows()[0])
    owner_row.update(id="report-owner", report_number="SHARED-REPORT")
    peer_row = dict(_parsed_contribution_rows()[1])
    peer_row.update(id="report-peer", report_number="SHARED-REPORT", committee_id=owner_row["committee_id"])
    fixture_path = tmp_path / "shared_report_correction.csv"
    _write_wa_rows(fixture_path, [owner_row, peer_row])
    assert load_wa_contributions_with_filings(db_conn, fixture_path).errors == 0

    corrected_owner = dict(owner_row)
    corrected_owner["amount"] = "153.25"
    _write_wa_rows(fixture_path, [peer_row, corrected_owner])
    assert load_wa_contributions_with_filings(db_conn, fixture_path).errors == 0

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT filing.source_record_id,
                   source_record.raw_fields->>'id' AS native_id,
                   source_record.superseded_by
            FROM cf.filing AS filing
            JOIN core.source_record AS source_record
              ON source_record.id = filing.source_record_id
            WHERE filing.filing_fec_id = 'WA-PDC:SHARED-REPORT'
            """
        )
        filing_source = cursor.fetchone()

    assert filing_source["native_id"] == "report-owner"
    assert filing_source["superseded_by"] is None

    source_only_owner = dict(corrected_owner)
    source_only_owner.update(report_number=" ", amount="155.25")
    _write_wa_rows(fixture_path, [peer_row, source_only_owner])
    source_only_result = load_wa_contributions_with_filings(db_conn, fixture_path)
    assert source_only_result.errors == 1

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT filing_source.raw_fields->>'id' AS filing_source_native_id,
                   filing_source.superseded_by,
                   COUNT(transaction.id) AS transaction_count,
                   ARRAY_AGG(transaction_source.raw_fields->>'id') AS transaction_source_native_ids
            FROM cf.filing AS filing
            JOIN core.source_record AS filing_source
              ON filing_source.id = filing.source_record_id
            JOIN cf.transaction AS transaction
              ON transaction.filing_id = filing.id
            JOIN core.source_record AS transaction_source
              ON transaction_source.id = transaction.source_record_id
            WHERE filing.filing_fec_id = 'WA-PDC:SHARED-REPORT'
            GROUP BY filing_source.id
            """
        )
        surviving_report = cursor.fetchone()

    assert surviving_report == {
        "filing_source_native_id": "report-peer",
        "superseded_by": None,
        "transaction_count": 1,
        "transaction_source_native_ids": ["report-peer"],
    }


def test_wa_multirow_missing_report_correction_removes_all_prior_claims(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    first_row = dict(_parsed_contribution_rows()[0])
    first_row.update(id="missing-multi-first", report_number="MISSING-MULTI")
    second_row = dict(_parsed_contribution_rows()[1])
    second_row.update(
        id="missing-multi-second",
        report_number="MISSING-MULTI",
        committee_id=first_row["committee_id"],
    )
    fixture_path = tmp_path / "multirow_missing_report.csv"
    _write_wa_rows(fixture_path, [first_row, second_row])
    assert load_wa_contributions_with_filings(db_conn, fixture_path).errors == 0

    missing_first = dict(first_row)
    missing_first.update(report_number=" ", amount="156.25")
    missing_second = dict(second_row)
    missing_second.update(report_number=" ", amount="157.25")
    _write_wa_rows(fixture_path, [missing_first, missing_second])
    result = load_wa_contributions_with_filings(db_conn, fixture_path)

    assert result.inserted == 2
    assert result.errors == 2
    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute("SELECT COUNT(*) AS count FROM cf.filing WHERE filing_fec_id = 'WA-PDC:MISSING-MULTI'")
        filing_count = cursor.fetchone()["count"]
        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM cf.transaction AS transaction
            JOIN core.source_record AS source_record
              ON source_record.id = transaction.source_record_id
            JOIN core.data_source AS data_source
              ON data_source.id = source_record.data_source_id
            WHERE data_source.name = 'WA PDC Contributions'
            """
        )
        transaction_count = cursor.fetchone()["count"]

    assert filing_count == 0
    assert transaction_count == 0
