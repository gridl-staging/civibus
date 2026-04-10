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
from domains.campaign_finance.jurisdictions.states.MN.scraper import load as mn_load
from domains.campaign_finance.jurisdictions.states.MN.scraper.load import (
    LoadResult,
    ensure_mn_data_source,
    load_mn_contribution,
    load_mn_contributions,
    load_mn_contributions_with_filings,
    load_mn_expenditure,
    load_mn_expenditures,
    load_mn_expenditures_with_filings,
    load_mn_independent_expenditures_with_filings,
)
from domains.campaign_finance.jurisdictions.states.MN.scraper.parse import parse_contributions, parse_expenditures

pytestmark = pytest.mark.integration

_FIXTURE_DIR = Path(__file__).parent / "test_fixtures"
_SAMPLE_CONTRIBUTIONS_PATH = _FIXTURE_DIR / "sample_contributions.csv"
_SAMPLE_EXPENDITURES_PATH = _FIXTURE_DIR / "sample_expenditures.csv"
_SAMPLE_INDEPENDENT_EXPENDITURES_PATH = _FIXTURE_DIR / "sample_independent_expenditures.csv"
_MN_JURISDICTION = "state/MN"
_MN_STATE_CODE = "MN"


def _parsed_contribution_rows() -> list[dict[str, str | None]]:
    return list(parse_contributions(_SAMPLE_CONTRIBUTIONS_PATH))


def _parsed_expenditure_rows() -> list[dict[str, str | None]]:
    return list(parse_expenditures(_SAMPLE_EXPENDITURES_PATH))


@pytest.fixture(autouse=True)
def _isolate_mn_loader_state(db_conn: psycopg.Connection) -> None:
    clear_state_loader_records(db_conn, jurisdiction=_MN_JURISDICTION, state_code=_MN_STATE_CODE)


def test_ensure_mn_data_source_is_idempotent(db_conn: psycopg.Connection) -> None:
    first_id = ensure_mn_data_source(db_conn, data_type="contributions")
    second_id = ensure_mn_data_source(db_conn, data_type="contributions")

    assert first_id == second_id


def test_ensure_mn_data_source_uses_distinct_names_per_data_type(db_conn: psycopg.Connection) -> None:
    contribution_source_id = ensure_mn_data_source(db_conn, data_type="contributions")
    expenditure_source_id = ensure_mn_data_source(db_conn, data_type="expenditures")

    assert contribution_source_id != expenditure_source_id


def test_load_mn_contribution_row_deduplicates_by_source_record_key(db_conn: psycopg.Connection) -> None:
    row = _parsed_contribution_rows()[0]
    data_source_id = ensure_mn_data_source(db_conn, data_type="contributions")

    first_insert = load_mn_contribution(db_conn, row, data_source_id)
    second_insert = load_mn_contribution(db_conn, row, data_source_id)

    assert first_insert is True
    assert second_insert is False
    assert _source_record_count(db_conn, data_source_id) == 1


def test_load_mn_expenditure_row_deduplicates_by_source_record_key(db_conn: psycopg.Connection) -> None:
    row = _parsed_expenditure_rows()[0]
    data_source_id = ensure_mn_data_source(db_conn, data_type="expenditures")

    first_insert = load_mn_expenditure(db_conn, row, data_source_id)
    second_insert = load_mn_expenditure(db_conn, row, data_source_id)

    assert first_insert is True
    assert second_insert is False
    assert _source_record_count(db_conn, data_source_id) == 1


def test_load_mn_independent_expenditures_with_filings_maps_support_oppose(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    result = load_mn_independent_expenditures_with_filings(db_conn, _SAMPLE_INDEPENDENT_EXPENDITURES_PATH)

    assert result.inserted + result.skipped == 2
    assert result.errors == 0

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT f.filing_fec_id,
                   t.transaction_type,
                   t.amount,
                   t.support_oppose
            FROM cf.transaction t
            JOIN cf.filing f
              ON f.id = t.filing_id
            WHERE f.filing_fec_id LIKE 'MN-%-independent_expenditures'
            ORDER BY t.amount DESC
            """,
        )
        transaction_rows = cursor.fetchall()

    assert len(transaction_rows) == 2
    assert transaction_rows[0]["filing_fec_id"] == "MN-9101-2025-independent_expenditures"
    assert transaction_rows[0]["transaction_type"] == "Independent Expenditure"
    assert transaction_rows[0]["amount"] == Decimal("4500.00")
    assert transaction_rows[0]["support_oppose"] == "S"
    assert transaction_rows[1]["filing_fec_id"] == "MN-9102-2025-independent_expenditures"
    assert transaction_rows[1]["transaction_type"] == "Independent Expenditure"
    assert transaction_rows[1]["amount"] == Decimal("875.25")
    assert transaction_rows[1]["support_oppose"] == "O"

    rerun_result = load_mn_independent_expenditures_with_filings(db_conn, _SAMPLE_INDEPENDENT_EXPENDITURES_PATH)
    assert rerun_result.inserted == 0
    assert rerun_result.skipped == 2
    assert rerun_result.errors == 0

    clear_state_loader_records(db_conn, jurisdiction=_MN_JURISDICTION, state_code=_MN_STATE_CODE)
    invalid_fixture_path = tmp_path / "invalid_mn_independent_expenditures.csv"
    invalid_fixture_path.write_text(
        _SAMPLE_INDEPENDENT_EXPENDITURES_PATH.read_text(encoding="utf-8").replace(",Against,", ",Neutral,", 1),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Unsupported MN independent expenditure support/oppose value"):
        load_mn_independent_expenditures_with_filings(db_conn, invalid_fixture_path)


def test_load_mn_contributions_batch_loads_fixture(db_conn: psycopg.Connection) -> None:
    data_source_id = ensure_mn_data_source(db_conn, data_type="contributions")

    result = load_mn_contributions(db_conn, _SAMPLE_CONTRIBUTIONS_PATH, data_source_id=data_source_id)

    assert isinstance(result, LoadResult)
    assert result.inserted == 3
    assert result.skipped == 0
    assert result.quarantined == 0
    assert result.errors == 0


def test_load_mn_expenditures_batch_loads_fixture(db_conn: psycopg.Connection) -> None:
    data_source_id = ensure_mn_data_source(db_conn, data_type="expenditures")

    result = load_mn_expenditures(db_conn, _SAMPLE_EXPENDITURES_PATH, data_source_id=data_source_id)

    assert isinstance(result, LoadResult)
    assert result.inserted == 2
    assert result.skipped == 0
    assert result.quarantined == 0
    assert result.errors == 0


def test_load_mn_contributions_rolls_back_partial_row_failures(
    db_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_source_id = ensure_mn_data_source(db_conn, data_type="contributions")

    def _raise_after_source_record(*args, **kwargs) -> None:
        raise RuntimeError("boom after source record insert")

    monkeypatch.setattr(mn_load, "_load_mn_transaction_entities", _raise_after_source_record)

    result = load_mn_contributions(db_conn, _SAMPLE_CONTRIBUTIONS_PATH, data_source_id=data_source_id, limit=1)

    assert result.inserted == 0
    assert result.skipped == 0
    assert result.errors == 1
    assert _source_record_count(db_conn, data_source_id) == 0


def test_load_mn_contributions_with_filings_builds_relational_rows(db_conn: psycopg.Connection) -> None:
    result = load_mn_contributions_with_filings(db_conn, _SAMPLE_CONTRIBUTIONS_PATH)

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
            WHERE f.filing_fec_id LIKE 'MN-%-contributions'
            ORDER BY t.transaction_identifier
            """,
        )
        transaction_rows = cursor.fetchall()

    assert {row["filing_fec_id"] for row in transaction_rows} == {
        "MN-9001-2025-contributions",
        "MN-9002-2025-contributions",
    }
    assert len(transaction_rows) == 3
    for row in transaction_rows:
        assert row["contributor_address_id"] == row["expected_contributor_address_id"]

    rerun_result = load_mn_contributions_with_filings(db_conn, _SAMPLE_CONTRIBUTIONS_PATH)
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
            WHERE f.filing_fec_id LIKE 'MN-%-contributions'
            """,
        )
        transaction_count = cursor.fetchone()["count"]

    assert transaction_count == 3


def test_load_mn_expenditures_with_filings_maps_type_and_amount(db_conn: psycopg.Connection) -> None:
    result = load_mn_expenditures_with_filings(db_conn, _SAMPLE_EXPENDITURES_PATH)

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
            WHERE f.filing_fec_id LIKE 'MN-%-expenditures'
            ORDER BY amount DESC
            LIMIT 1
            """,
        )
        row = cursor.fetchone()

    assert row is not None
    assert row["transaction_type"] == "Operating Expenditure"
    assert row["amount"] == Decimal("315.25")
    assert row["contributor_address_id"] == row["expected_contributor_address_id"]

    rerun_result = load_mn_expenditures_with_filings(db_conn, _SAMPLE_EXPENDITURES_PATH)
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
            WHERE f.filing_fec_id LIKE 'MN-%-expenditures'
            """,
        )
        transaction_count = cursor.fetchone()["count"]

    assert transaction_count == 2
