"""Integration tests for fixture-backed federal FEC closeout evidence orchestration."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import psycopg
import pytest

from domains.campaign_finance.ingest import bulk_cli
from domains.campaign_finance.ingest.test_bulk_cli_stage2_integration import _materialize_cycle_directory
from domains.campaign_finance.ingest.test_bulk_loader_integration import BulkLoaderFixtureSet
from domains.campaign_finance.ingest.test_bulk_loader_stage4_integration import Stage4FixtureSet
from domains.campaign_finance.quality import fec_closeout
from domains.campaign_finance.quality.reconciliation import count_source_records

pytest_plugins = (
    "domains.campaign_finance.ingest.test_bulk_loader_integration",
    "domains.campaign_finance.ingest.test_bulk_loader_stage4_integration",
)


def _count_table_rows_scoped_to_data_source(
    conn: psycopg.Connection,
    table_name: str,
    data_source_id: UUID,
) -> int:
    with conn.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT COUNT(*)
            FROM {table_name} row
            JOIN core.source_record source_record
              ON source_record.id = row.source_record_id
            WHERE source_record.data_source_id = %s
              AND source_record.superseded_by IS NULL
            """,  # noqa: S608
            (data_source_id,),
        )
        return cursor.fetchone()[0]


@pytest.mark.integration
def test_run_fec_closeout_collects_scoped_counts_and_quality_report(
    bulk_loader_conn: psycopg.Connection,
    bulk_loader_fixture_set: BulkLoaderFixtureSet,
    stage4_fixture_set: Stage4FixtureSet,
    tmp_path: Path,
) -> None:
    cycle_directory = _materialize_cycle_directory(tmp_path, bulk_loader_fixture_set, stage4_fixture_set)
    artifact_path = tmp_path / "closeout_evidence.json"
    config = fec_closeout.FecCloseoutConfig(
        cycle=2024,
        directory=cycle_directory,
        artifact_path=artifact_path,
        batch_size=2,
        transaction_limit=None,
        graph_enabled=False,
    )

    evidence = fec_closeout.run_fec_closeout(bulk_loader_conn, config)
    fec_closeout.write_evidence_artifact(evidence, artifact_path)
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))

    data_source_id = UUID(payload["data_source_id"])
    assert [step["file_type"] for step in payload["ingest_steps"]] == list(bulk_cli.FULL_CYCLE_FILE_ORDER)
    assert payload["quality_report"]["jurisdiction_filter"] == "federal/fec"
    assert set(payload["baseline_urls"].keys()) == set(bulk_cli.FULL_CYCLE_FILE_ORDER)
    assert payload["scoped_table_counts"]["cf.committee"] == _count_table_rows_scoped_to_data_source(
        bulk_loader_conn,
        "cf.committee",
        data_source_id,
    )
    assert payload["scoped_table_counts"]["cf.candidate"] == _count_table_rows_scoped_to_data_source(
        bulk_loader_conn,
        "cf.candidate",
        data_source_id,
    )
    assert payload["scoped_table_counts"]["cf.candidate_committee_link"] == _count_table_rows_scoped_to_data_source(
        bulk_loader_conn,
        "cf.candidate_committee_link",
        data_source_id,
    )
    assert payload["scoped_table_counts"]["core.source_record_active"] == count_source_records(
        bulk_loader_conn,
        data_source_id,
    )
