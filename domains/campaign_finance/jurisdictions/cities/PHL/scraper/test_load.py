"""Integration tests for PHL pass-1 source-record loader.

These tests run against the live `civibus` DB on Hetzner inside the
`db_conn` fixture's BEGIN/ROLLBACK transaction, so writes are rolled
back at test exit and never touch production data.
"""

from __future__ import annotations

import json
from pathlib import Path

import psycopg
import pytest

from domains.campaign_finance.jurisdictions.cities.PHL.scraper.load import (
    ensure_phl_contributions_data_source,
    ensure_phl_expenditures_data_source,
    load_phl_relational,
    load_phl_source_records,
)

pytestmark = pytest.mark.integration

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
_CONTRIBUTIONS_FIXTURE = FIXTURES_DIR / "campfin_contributions_sample_2026_04_25.json"
_EXPENDITURES_FIXTURE = FIXTURES_DIR / "campfin_expenditures_sample_2026_04_25.json"


def _fixture_to_jsonl(src_json: Path, dest_jsonl: Path) -> int:
    """Convert a Carto-format JSON fixture (with `rows` array) into JSONL."""
    payload = json.loads(src_json.read_text(encoding="utf-8"))
    rows = payload["rows"]
    with dest_jsonl.open("w", encoding="utf-8") as fp:
        for row in rows:
            fp.write(json.dumps(row, default=str) + "\n")
    return len(rows)


def test_ensure_phl_contributions_data_source_returns_uuid(
    db_conn: psycopg.Connection,
) -> None:
    """The data-source upsert path must return a UUID and be idempotent."""
    first_id = ensure_phl_contributions_data_source(db_conn)
    second_id = ensure_phl_contributions_data_source(db_conn)
    assert first_id == second_id, "ensure_*_data_source must be idempotent"


def test_ensure_phl_contributions_and_expenditures_data_sources_are_distinct(
    db_conn: psycopg.Connection,
) -> None:
    """Contributions and expenditures must be SEPARATE data_source rows so
    downstream queries can filter by source name."""
    contrib_id = ensure_phl_contributions_data_source(db_conn)
    exp_id = ensure_phl_expenditures_data_source(db_conn)
    assert contrib_id != exp_id


def test_load_phl_source_records_inserts_one_per_unique_row(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    """Pass-1 load: every unique row in the fixture should produce exactly
    one source_record in core.source_record."""
    jsonl = tmp_path / "phl_contrib.jsonl"
    expected_rows = _fixture_to_jsonl(_CONTRIBUTIONS_FIXTURE, jsonl)
    assert expected_rows == 5

    result = load_phl_source_records(db_conn, jsonl, is_expenditure=False)

    assert result.inserted == 5, (
        f"expected 5 unique rows inserted; got inserted={result.inserted}, "
        f"skipped={result.skipped}, errors={result.errors}, quarantined={result.quarantined}"
    )
    assert result.errors == 0
    assert result.quarantined == 0


def test_load_phl_source_records_is_idempotent(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    """Re-running the loader against the same JSONL must report 0 inserted +
    N skipped on the second pass — proves the (data_source_id, record_hash)
    dedupe contract."""
    jsonl = tmp_path / "phl_contrib.jsonl"
    _fixture_to_jsonl(_CONTRIBUTIONS_FIXTURE, jsonl)

    first = load_phl_source_records(db_conn, jsonl, is_expenditure=False)
    second = load_phl_source_records(db_conn, jsonl, is_expenditure=False)

    assert first.inserted == 5
    assert second.inserted == 0
    assert second.skipped == 5


def test_load_phl_source_records_skips_malformed_jsonl_lines(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    """A malformed JSONL line (truncated JSON, trailing `]`, garbage)
    must NOT abort the load — the loader should skip the bad line and
    keep going. This protects against partial-write recovery and
    accidental shell concatenation artifacts in the JSONL file."""
    jsonl = tmp_path / "phl_mixed_lines.jsonl"
    good = {
        "transaction_id": "GOOD-1",
        "transaction_amount": 75,
        "transaction_date": "2026-04-01",
        "filer_name": "Good", "donor_name": "Good Donor",
    }
    with jsonl.open("w", encoding="utf-8") as fp:
        fp.write(json.dumps(good) + "\n")
        fp.write("{this is not valid json at all\n")  # malformed
        fp.write("]\n")  # trailing-bracket curl artifact
        fp.write(json.dumps(good | {"transaction_id": "GOOD-2"}) + "\n")
        fp.write("\n")  # blank line — already handled by existing logic
        fp.write("null\n")  # valid JSON but not a dict
        fp.write(json.dumps(good | {"transaction_id": "GOOD-3"}) + "\n")

    result = load_phl_source_records(db_conn, jsonl, is_expenditure=False)

    # 3 well-formed dict lines should succeed; the 3 malformed/non-dict
    # lines should be skipped without raising.
    assert result.inserted == 3, (
        f"expected 3 inserts from 3 valid JSONL lines; got inserted={result.inserted}, "
        f"skipped={result.skipped}, errors={result.errors}, quarantined={result.quarantined}"
    )
    assert result.errors == 0


def test_load_phl_source_records_quarantines_malformed_rows(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    """Rows that fail Pydantic validation (e.g. amount='not-a-number') must
    be QUARANTINED, not error the whole batch."""
    jsonl = tmp_path / "phl_mixed.jsonl"
    rows = [
        {"transaction_id": "T1", "transaction_amount": 100, "transaction_date": "2026-04-01",
         "filer_name": "Good Filer", "donor_name": "Good Donor"},
        {"transaction_id": "T2", "transaction_amount": "not-a-number",
         "transaction_date": "2026-04-02",
         "filer_name": "Bad", "donor_name": "Bad"},
        {"transaction_id": "T3", "transaction_amount": 250, "transaction_date": "2026-04-03",
         "filer_name": "Good Filer 2", "donor_name": "Good Donor 2"},
    ]
    with jsonl.open("w", encoding="utf-8") as fp:
        for row in rows:
            fp.write(json.dumps(row) + "\n")

    result = load_phl_source_records(db_conn, jsonl, is_expenditure=False)

    assert result.inserted == 2
    assert result.quarantined == 1
    assert result.errors == 0


def test_load_phl_source_records_separate_counters_for_contrib_vs_expenditure(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    """Loading the same row under both contribution and expenditure data
    sources should produce TWO source records (different data_source_id),
    not one — the dedupe key is (data_source_id, record_hash)."""
    jsonl_contrib = tmp_path / "phl_contrib.jsonl"
    jsonl_exp = tmp_path / "phl_exp.jsonl"
    _fixture_to_jsonl(_CONTRIBUTIONS_FIXTURE, jsonl_contrib)
    _fixture_to_jsonl(_EXPENDITURES_FIXTURE, jsonl_exp)

    contrib_result = load_phl_source_records(db_conn, jsonl_contrib, is_expenditure=False)
    exp_result = load_phl_source_records(db_conn, jsonl_exp, is_expenditure=True)

    assert contrib_result.inserted == 5
    assert exp_result.inserted == 5
    # Different data sources, so independent dedupe — both inserts succeed.


def test_load_phl_source_records_respects_limit(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    """A `limit` argument should bound the number of rows the loader processes."""
    jsonl = tmp_path / "phl_contrib.jsonl"
    _fixture_to_jsonl(_CONTRIBUTIONS_FIXTURE, jsonl)

    result = load_phl_source_records(db_conn, jsonl, is_expenditure=False, limit=2)
    assert result.inserted == 2


# ---------------------------------------------------------------------------
# Pass 2 — relational loader
# ---------------------------------------------------------------------------


def test_load_phl_relational_requires_pass1_provenance_first(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    """Pass 2 looks up the pass-1 source_record_id by record_hash. If pass 1
    has not been run for this row, pass 2 must SKIP rather than create an
    orphan filing/transaction with NULL provenance."""
    jsonl = tmp_path / "phl_contrib.jsonl"
    _fixture_to_jsonl(_CONTRIBUTIONS_FIXTURE, jsonl)

    # Skip pass 1 entirely; jump straight to pass 2.
    result = load_phl_relational(db_conn, jsonl, is_expenditure=False)

    assert result.inserted == 0, (
        f"pass 2 must skip rows without pass-1 provenance; got inserted={result.inserted}"
    )
    assert result.skipped == 5
    assert result.errors == 0


def test_load_phl_relational_inserts_committee_filing_transaction_after_pass1(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    """Two-pass end-to-end: pass 1 populates source_record, pass 2 produces
    cf.committee + cf.filing + cf.transaction rows linked to that
    provenance. Asserts (a) every fixture row materializes a transaction,
    (b) every transaction carries a non-null source_record_id."""
    jsonl = tmp_path / "phl_contrib.jsonl"
    _fixture_to_jsonl(_CONTRIBUTIONS_FIXTURE, jsonl)

    pass1 = load_phl_source_records(db_conn, jsonl, is_expenditure=False)
    assert pass1.inserted == 5

    pass2 = load_phl_relational(db_conn, jsonl, is_expenditure=False)
    assert pass2.inserted == 5
    assert pass2.skipped == 0
    assert pass2.errors == 0

    # Every transaction inserted by pass 2 must link back to a source_record
    # (the one inserted by pass 1) — provenance is non-negotiable.
    rows = db_conn.execute(
        """
        SELECT count(*) AS total,
               count(*) FILTER (WHERE source_record_id IS NOT NULL) AS with_provenance
        FROM cf.transaction
        WHERE filing_id IN (
            SELECT id FROM cf.filing WHERE filing_fec_id LIKE 'PHL-%'
        )
        """
    ).fetchone()
    assert rows is not None
    total, with_provenance = rows[0], rows[1]
    assert total == 5, f"expected 5 PHL transactions, got {total}"
    assert with_provenance == total, (
        f"every PHL transaction must carry provenance; missing on {total - with_provenance}"
    )


def test_load_phl_relational_is_idempotent(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    """Re-running pass 2 must produce no new transactions (the
    (filing_id, transaction_identifier) upsert key must dedupe).

    The real test is that the visible row count is unchanged BETWEEN
    the first and second pass-2 runs — querying after both runs would
    just compare two identical post-state snapshots and trivially pass
    even if the second pass duplicated every row in between.
    """
    jsonl = tmp_path / "phl_contrib.jsonl"
    _fixture_to_jsonl(_CONTRIBUTIONS_FIXTURE, jsonl)
    load_phl_source_records(db_conn, jsonl, is_expenditure=False)

    first = load_phl_relational(db_conn, jsonl, is_expenditure=False)
    assert first.inserted == 5

    count_after_first_row = db_conn.execute(
        "SELECT count(*) FROM cf.transaction WHERE filing_id IN "
        "(SELECT id FROM cf.filing WHERE filing_fec_id LIKE 'PHL-%')"
    ).fetchone()
    assert count_after_first_row is not None
    count_after_first = count_after_first_row[0]
    assert count_after_first == 5, (
        f"pass-2 first run should produce 5 cf.transaction rows under PHL-% "
        f"filings; got {count_after_first}"
    )

    # Now run pass 2 again and assert the count is unchanged. This is the
    # real idempotency check: did the second run add any rows or did
    # ON CONFLICT DO UPDATE / DO NOTHING dedupe correctly?
    second = load_phl_relational(db_conn, jsonl, is_expenditure=False)

    count_after_second_row = db_conn.execute(
        "SELECT count(*) FROM cf.transaction WHERE filing_id IN "
        "(SELECT id FROM cf.filing WHERE filing_fec_id LIKE 'PHL-%')"
    ).fetchone()
    assert count_after_second_row is not None
    count_after_second = count_after_second_row[0]
    assert count_after_second == count_after_first, (
        f"pass-2 idempotency violated: count went {count_after_first} -> "
        f"{count_after_second} (second run should add 0 new rows). "
        f"second.inserted reported {second.inserted}, errors {second.errors}."
    )
