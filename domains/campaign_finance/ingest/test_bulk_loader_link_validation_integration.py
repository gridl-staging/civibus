from __future__ import annotations

from pathlib import Path

import psycopg
import pytest

from domains.campaign_finance.ingest.bulk_loader import ensure_fec_bulk_data_source, load_candidate_committee_links
from domains.campaign_finance.ingest.bulk_parser import CCL_COLUMNS
from domains.campaign_finance.ingest.test_bulk_loader_integration import (
    _PRIMARY_CYCLE,
    _load_committees_and_candidates,
    _write_fixture_file,
    BulkLoaderFixtureSet,
)

pytest_plugins = ("domains.campaign_finance.ingest.test_bulk_loader_integration",)
pytestmark = pytest.mark.integration


def test_load_candidate_committee_links_keeps_invalid_year_rows_as_errors(
    bulk_loader_conn: psycopg.Connection,
    bulk_loader_fixture_set: BulkLoaderFixtureSet,
    tmp_path: Path,
) -> None:
    data_source_id = ensure_fec_bulk_data_source(bulk_loader_conn)
    _load_committees_and_candidates(bulk_loader_conn, bulk_loader_fixture_set, data_source_id)

    invalid_rows = [dict(row) for row in bulk_loader_fixture_set.ccl_rows]
    invalid_linkage_id = invalid_rows[0]["LINKAGE_ID"]
    invalid_rows[0]["CAND_ELECTION_YR"] = "INVALID"
    invalid_fixture_path = tmp_path / "ccl_with_invalid_year.txt"
    _write_fixture_file(invalid_fixture_path, CCL_COLUMNS, invalid_rows)

    first_result = load_candidate_committee_links(
        bulk_loader_conn,
        invalid_fixture_path,
        cycle=_PRIMARY_CYCLE,
        data_source_id=data_source_id,
        batch_size=2,
    )
    second_result = load_candidate_committee_links(
        bulk_loader_conn,
        invalid_fixture_path,
        cycle=_PRIMARY_CYCLE,
        data_source_id=data_source_id,
        batch_size=2,
    )

    assert (first_result.inserted, first_result.skipped, first_result.errors) == (4, 0, 1)
    assert (second_result.inserted, second_result.skipped, second_result.errors) == (0, 4, 1)

    with bulk_loader_conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM core.source_record
            WHERE data_source_id = %s
              AND source_record_key = %s
            """,
            (data_source_id, f"ccl:{_PRIMARY_CYCLE}:{invalid_linkage_id}"),
        )
        assert cursor.fetchone()[0] == 0
