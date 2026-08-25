"""Tests for NY load module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, call
from uuid import uuid4

import psycopg

from domains.campaign_finance.ingest.filing_loader import generate_synthetic_committee_id
from domains.campaign_finance.jurisdictions.states.NY.scraper import load
from domains.campaign_finance.jurisdictions.states.NY.scraper import ny_load_test_support as ny_support
from domains.campaign_finance.jurisdictions.states.NY.scraper.extract import extract_ny_expenditure
from domains.campaign_finance.jurisdictions.states.NY.scraper.load import (
    load_ny_contributions_with_filings,
    load_ny_expenditures_with_filings,
    load_ny_independent_expenditures_with_filings,
)
from domains.campaign_finance.jurisdictions.states.NY.scraper.parse import parse_independent_expenditures

_FIXTURE_DIR = Path(__file__).parent / "test_fixtures"
_SAMPLE_CONTRIBUTIONS_PATH = _FIXTURE_DIR / "sample_contributions.csv"
_SAMPLE_EXPENDITURES_PATH = _FIXTURE_DIR / "sample_expenditures.csv"
_SAMPLE_IE_PATH = _FIXTURE_DIR / "sample_ie.csv"
_EXPECTED_DATA_TYPES = {"contributions", "expenditures", "independent_expenditures"}


def test_public_load_functions_dispatch_to_internal_loader(monkeypatch) -> None:
    """Public load wrappers should delegate to _load_ny_with_filings."""
    internal = MagicMock()
    monkeypatch.setattr(load, "_load_ny_with_filings", internal)
    conn = MagicMock()

    load_ny_contributions_with_filings(conn, _SAMPLE_CONTRIBUTIONS_PATH, limit=5)
    load_ny_expenditures_with_filings(conn, _SAMPLE_EXPENDITURES_PATH, limit=6)
    load_ny_independent_expenditures_with_filings(conn, _SAMPLE_IE_PATH, limit=7)

    assert internal.call_count == 3
    assert internal.call_args_list[0].kwargs["data_type"] == "contributions"
    assert internal.call_args_list[1].kwargs["data_type"] == "expenditures"
    assert internal.call_args_list[2].kwargs["data_type"] == "independent_expenditures"


def test_conn_commit_after_ensure_data_source(monkeypatch) -> None:
    """Regression: ensure_ny_data_source leaves conn IN_TRANSACTION.

    _load_ny_with_filings must call conn.commit() after ensure_ny_data_source
    so that _load_ny_rows sees IDLE transaction status and enables periodic
    commits every 1000 rows. Without this, NY's ~3.2M rows accumulate in one
    massive uncommitted transaction.
    """
    monkeypatch.setattr(load, "ensure_ny_data_source", MagicMock(return_value=1))
    monkeypatch.setattr(load, "_load_ny_file", MagicMock(return_value=MagicMock(errors=[])))
    monkeypatch.setattr(load, "_load_ny_relational_transactions", MagicMock(return_value=[]))
    monkeypatch.setattr(load, "validated_limit", MagicMock(return_value=None))

    conn = MagicMock()
    load._load_ny_with_filings(conn, _SAMPLE_CONTRIBUTIONS_PATH, data_type="contributions")

    assert call.commit() in conn.method_calls, "conn.commit() was never called — periodic commits will not fire"


def test_dispatch_tables_stay_in_lockstep() -> None:
    """All NY load dispatch tables should stay in lockstep on supported data types."""
    assert set(load._NY_ENTITY_KEYS) == _EXPECTED_DATA_TYPES
    assert set(load._NY_EXTRACT_FN) == _EXPECTED_DATA_TYPES
    assert set(load._NY_PARSER_FN) == _EXPECTED_DATA_TYPES
    assert set(load._NY_COUNTERPARTY_NAME_PATHS) == _EXPECTED_DATA_TYPES
    assert set(load._NY_COUNTERPARTY_EMPLOYER_PATH) == _EXPECTED_DATA_TYPES
    assert set(load._NY_ENTITY_ROLES) == _EXPECTED_DATA_TYPES
    assert set(load._NY_COUNTERPARTY_ROLES) == _EXPECTED_DATA_TYPES


def test_independent_expenditures_reuse_expenditure_dispatch_entries() -> None:
    """IE should reuse expenditure extraction/parsing and role mappings."""
    assert load._NY_EXTRACT_FN["independent_expenditures"] is extract_ny_expenditure
    assert load._NY_PARSER_FN["independent_expenditures"] is parse_independent_expenditures
    assert load._NY_ENTITY_KEYS["independent_expenditures"] == load._NY_ENTITY_KEYS["expenditures"]
    assert (
        load._NY_COUNTERPARTY_NAME_PATHS["independent_expenditures"] == load._NY_COUNTERPARTY_NAME_PATHS["expenditures"]
    )
    assert load._NY_ENTITY_ROLES["independent_expenditures"] == load._NY_ENTITY_ROLES["expenditures"]
    assert load._NY_COUNTERPARTY_ROLES["independent_expenditures"] == load._NY_COUNTERPARTY_ROLES["expenditures"]


def test_upsert_transaction_uses_canonical_ie_transaction_type(monkeypatch) -> None:
    """IE transaction type should use the canonical shared transaction label."""
    row = next(iter(parse_independent_expenditures(_SAMPLE_IE_PATH)))
    captured: dict[str, object] = {}

    monkeypatch.setattr(load, "resolve_transaction_counterparty_ids", MagicMock(return_value=(None, None)))
    monkeypatch.setattr(load, "_resolve_ny_transaction_address_id", MagicMock(return_value=None))

    def capture_upsert_transaction(_conn, transaction) -> None:  # noqa: ANN001
        captured["transaction"] = transaction

    monkeypatch.setattr(load, "upsert_transaction", capture_upsert_transaction)

    load._upsert_ny_transaction_with_filing(
        MagicMock(),
        row,
        filing_id=uuid4(),
        committee_id=uuid4(),
        source_record_id=uuid4(),
        data_type="independent_expenditures",
    )

    transaction = captured["transaction"]
    assert transaction.transaction_type == "Independent Expenditure"
    assert transaction.transaction_type != row["filing_sched_abbrev"]


def test_load_ny_independent_expenditures_is_idempotent_for_fixture_reruns(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    """Rerunning NY IE load should preserve source-record and transaction cardinality."""
    fixture = ny_support.write_ny_ie_fixture(tmp_path)
    # db_conn yields with BEGIN already executed; the loader must observe IDLE to
    # own its commits, otherwise nothing commits and the rerun proves nothing.
    db_conn.rollback()
    # Clean first so the insert count below is a claim about this run alone,
    # even if an earlier aborted run somehow committed these generated keys.
    ny_support.cleanup_ny_ie_fixture(fixture)

    try:
        first_result = load_ny_independent_expenditures_with_filings(db_conn, fixture.csv_path)
        counts_after_first_load = ny_support.fixture_row_counts(fixture)
        second_result = load_ny_independent_expenditures_with_filings(db_conn, fixture.csv_path)
        counts_after_rerun = ny_support.fixture_row_counts(fixture)

        assert first_result.inserted == 2
        assert first_result.skipped == 0
        assert first_result.errors == 0
        assert second_result.inserted == 0
        assert second_result.skipped == 2
        assert second_result.errors == 0

        # Idempotence is this cardinality holding across the rerun, counted by
        # the run's own generated keys rather than by every NY IE row the shared
        # dev database happens to hold.
        assert counts_after_first_load["source_record"] == 2
        assert counts_after_first_load["transaction"] == 2
        assert counts_after_rerun["source_record"] == 2
        assert counts_after_rerun["transaction"] == 2

        # The rerun leaves nothing behind either: cleanup scoped to the same
        # generated keys empties the footprint, read over an independent
        # connection so a leak cannot hide inside db_conn's transaction.
        ny_support.cleanup_ny_ie_fixture(fixture)
        counts_after_cleanup = ny_support.fixture_row_counts(fixture)
        assert counts_after_cleanup["source_record"] == 0
        assert counts_after_cleanup["transaction"] == 0
    finally:
        ny_support.cleanup_ny_ie_fixture(fixture)


# --- Synthetic NY IE fixture lifecycle -------------------------------------
#
# The static sample_ie.csv carries fixed identities, so two runs against the
# shared dev database resolve to — and then assert over — each other's rows.
# ny_load_test_support owns a per-run copy whose every identity-bearing column
# is unique, plus the leak-proof cleanup that removes exactly what one copy
# wrote. These tests prove both halves of that contract.

_PER_RUN_IDENTITY_PATHS = (
    "committee.id",
    "ny.filer_previous_id",
    "committee.name",
    "ny.trans_number",
    "payee.org_name",
    "payee.first_name",
    "payee.last_name",
)


def _column_values(csv_path: Path, semantic_path: str) -> list[str | None]:
    column = ny_support.ie_column(semantic_path)
    return [row[column] for row in parse_independent_expenditures(csv_path)]


def test_write_ny_ie_fixture_generates_distinct_per_run_identities(tmp_path: Path) -> None:
    """Two generated fixtures must share no identity the loader keys on."""
    first = ny_support.write_ny_ie_fixture(tmp_path)
    second = ny_support.write_ny_ie_fixture(tmp_path)

    sample_rows = [dict(row) for row in parse_independent_expenditures(_SAMPLE_IE_PATH)]
    first_rows = [dict(row) for row in parse_independent_expenditures(first.csv_path)]
    second_rows = [dict(row) for row in parse_independent_expenditures(second.csv_path)]

    # Cardinality is unchanged: the generated copy is the sample, re-identified.
    assert len(sample_rows) == 2
    assert len(first_rows) == len(sample_rows)
    assert len(second_rows) == len(sample_rows)

    # A populated identity column is re-identified per run; an empty one stays
    # empty, so row 1 keeps its organization payee and row 2 its person payee.
    for semantic_path in _PER_RUN_IDENTITY_PATHS:
        column = ny_support.ie_column(semantic_path)
        first_values = _column_values(first.csv_path, semantic_path)
        second_values = _column_values(second.csv_path, semantic_path)
        for index, sample_row in enumerate(sample_rows):
            if sample_row[column] is None:
                assert first_values[index] is None, f"{column} row {index} should stay empty"
                assert second_values[index] is None, f"{column} row {index} should stay empty"
                continue
            assert first_values[index] is not None
            assert first_values[index] != sample_row[column], f"{column} row {index} was not re-identified"
            assert first_values[index] != second_values[index], f"{column} row {index} collides across runs"

    # Every row gets a unique street, including row 1 whose sample street is empty:
    # without it row 1's raw_address collides across runs on city/state/zip alone.
    street_column = ny_support.ie_column("payee.address.street1")
    assert sample_rows[0][street_column] is None
    first_streets = _column_values(first.csv_path, "payee.address.street1")
    second_streets = _column_values(second.csv_path, "payee.address.street1")
    assert all(street is not None for street in first_streets)
    assert len(set(first_streets)) == len(first_streets)
    assert not set(first_streets) & set(second_streets)

    # Constrained formats survive re-identification.
    zip_column = ny_support.ie_column("payee.address.zip")
    first_zips = _column_values(first.csv_path, "payee.address.zip")
    assert first_zips == [sample_rows[0][zip_column], sample_rows[1][zip_column]]
    assert first_zips == ["12207", "10007"]

    # Derived loader identities are exactly what the written rows produce.
    assert first.filer_ids == [row[ny_support.ie_column("committee.id")] for row in first_rows]
    assert len(set(first.filer_ids)) == 2, "each row must have its own committee"
    assert first.source_record_keys == [load._ny_source_record_key(row) for row in first_rows]
    assert first.filing_fec_ids == [load._build_ny_filing_fec_id(row, "independent_expenditures") for row in first_rows]
    assert first.committee_fec_ids == [generate_synthetic_committee_id("NY", filer_id) for filer_id in first.filer_ids]
    assert first.transaction_identifiers == [row[ny_support.ie_column("ny.trans_number")] for row in first_rows]
    assert all(
        filing_fec_id.startswith("NY-") and filing_fec_id.endswith("-independent_expenditures")
        for filing_fec_id in first.filing_fec_ids
    )

    # No derived identity is shared between two runs.
    for attribute in ("source_record_keys", "filing_fec_ids", "transaction_identifiers", "committee_fec_ids"):
        first_identities = set(getattr(first, attribute))
        assert len(first_identities) == 2, f"{attribute} must be distinct within one fixture"
        assert not first_identities & set(getattr(second, attribute)), f"{attribute} collides across runs"

    assert first.csv_path != second.csv_path


# One fixture load writes: two source records, and — because each sample row has
# its own filer — two filings, two transactions and two committees. Row 1's payee
# is an organization and row 2's a person, so the organizations are that one
# payee plus the two committees, and each row now carries its own street.
_EXPECTED_FIXTURE_FOOTPRINT = {
    "source_record": 2,
    "filing": 2,
    "transaction": 2,
    "committee": 2,
    "person": 1,
    "organization": 3,
    "address": 2,
}
_EMPTY_FIXTURE_FOOTPRINT = dict.fromkeys(_EXPECTED_FIXTURE_FOOTPRINT, 0)


def test_cleanup_ny_ie_fixture_removes_only_its_committed_rows(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    """Cleanup must erase one fixture's whole footprint and nothing else's."""
    first = ny_support.write_ny_ie_fixture(tmp_path)
    second = ny_support.write_ny_ie_fixture(tmp_path)
    # db_conn yields with BEGIN already executed; the loader must observe IDLE to
    # own its commits, otherwise nothing commits and the test proves nothing.
    db_conn.rollback()
    ny_support.cleanup_ny_ie_fixture(first)
    ny_support.cleanup_ny_ie_fixture(second)

    try:
        load_ny_independent_expenditures_with_filings(db_conn, first.csv_path)
        load_ny_independent_expenditures_with_filings(db_conn, second.csv_path)

        # Every count is read back over an independent connection, so it also
        # proves the loader committed rather than holding rows in db_conn.
        first_counts = ny_support.fixture_row_counts(first)
        second_counts_before = ny_support.fixture_row_counts(second)
        data_source_count_before = ny_support.canonical_ie_data_source_count()

        assert first_counts == _EXPECTED_FIXTURE_FOOTPRINT
        assert second_counts_before == _EXPECTED_FIXTURE_FOOTPRINT
        assert data_source_count_before == 1

        ny_support.cleanup_ny_ie_fixture(first)

        assert ny_support.fixture_row_counts(first) == _EMPTY_FIXTURE_FOOTPRINT
        # Scope controls: the untouched fixture and the canonical data source
        # both survive a cleanup that names only the first fixture's identities.
        assert ny_support.fixture_row_counts(second) == second_counts_before
        assert ny_support.canonical_ie_data_source_count() == data_source_count_before
    finally:
        ny_support.cleanup_ny_ie_fixture(first)
        ny_support.cleanup_ny_ie_fixture(second)
