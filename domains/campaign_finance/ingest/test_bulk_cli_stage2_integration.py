from __future__ import annotations

from pathlib import Path
from uuid import UUID

import psycopg
import pytest

from domains.campaign_finance.ingest import bulk_cli
from domains.campaign_finance.ingest.bulk_loader import ensure_fec_bulk_data_source
from domains.campaign_finance.ingest.bulk_parser import ITCONT_COLUMNS
from domains.campaign_finance.ingest.test_bulk_loader_integration import (
    _PRIMARY_CYCLE,
    _fetch_link_rows,
    _select_source_record_ids,
    _write_fixture_file,
    BulkLoaderFixtureSet,
)
from domains.campaign_finance.ingest.test_bulk_loader_stage4_integration import Stage4FixtureSet
from domains.campaign_finance.quality.reconciliation import count_source_records

pytest_plugins = (
    "domains.campaign_finance.ingest.test_bulk_loader_integration",
    "domains.campaign_finance.ingest.test_bulk_loader_stage4_integration",
)


def _materialize_cycle_directory(
    tmp_path: Path,
    fixture_set: BulkLoaderFixtureSet,
    stage4_set: Stage4FixtureSet,
) -> Path:
    cycle_directory = tmp_path / "cycle"
    cycle_directory.mkdir()

    file_paths = {
        "cm": fixture_set.committee_path,
        "cn": fixture_set.candidate_path,
        "ccl": fixture_set.ccl_path,
        "itcont": stage4_set.itcont_path,
        "itpas2": stage4_set.itpas2_path,
    }

    for file_type, source_path in file_paths.items():
        target_path = cycle_directory / f"{file_type}_sample.txt"
        target_path.write_bytes(source_path.read_bytes())

    return cycle_directory


def _assert_full_cycle_phase_results(
    first_run: list[bulk_cli.LoadStepSummary],
    second_run: list[bulk_cli.LoadStepSummary],
    expected_inserted_by_type: dict[str, int],
) -> None:
    assert [step.file_type for step in first_run] == ["cm", "cn", "ccl", "itcont", "itpas2"]
    assert [step.file_type for step in second_run] == ["cm", "cn", "ccl", "itcont", "itpas2"]

    for step in first_run:
        expected_count = expected_inserted_by_type[step.file_type]
        assert (step.result.inserted, step.result.skipped, step.result.errors) == (expected_count, 0, 0)
    for step in second_run:
        expected_count = expected_inserted_by_type[step.file_type]
        assert (step.result.inserted, step.result.skipped, step.result.errors) == (0, expected_count, 0)


def _assert_stage4_recipient_entity_sources(
    conn: psycopg.Connection,
    source_record_ids: list[UUID],
    expected_count: int,
) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM core.entity_source
            WHERE source_record_id = ANY(%s)
              AND entity_type = 'organization'
              AND extraction_role = 'recipient'
            """,
            (source_record_ids,),
        )
        recipient_count = cursor.fetchone()[0]

    assert recipient_count == expected_count


def _assert_full_cycle_database_rows(
    conn: psycopg.Connection,
    data_source_id: UUID,
    bulk_loader_fixture_set: BulkLoaderFixtureSet,
    stage4_fixture_set: Stage4FixtureSet,
) -> None:
    expected_source_keys = [
        *bulk_loader_fixture_set.source_record_keys((_PRIMARY_CYCLE,)),
        *stage4_fixture_set.contribution_sub_ids,
        *stage4_fixture_set.committee_transaction_sub_ids,
    ]
    source_record_ids = _select_source_record_ids(conn, data_source_id, expected_source_keys)
    assert len(source_record_ids) == len(expected_source_keys)

    contribution_source_record_ids = _select_source_record_ids(
        conn,
        data_source_id,
        stage4_fixture_set.contribution_sub_ids,
    )
    committee_transaction_source_record_ids = _select_source_record_ids(
        conn,
        data_source_id,
        stage4_fixture_set.committee_transaction_sub_ids,
    )
    _assert_stage4_recipient_entity_sources(
        conn,
        contribution_source_record_ids,
        len(stage4_fixture_set.itcont_rows),
    )
    _assert_stage4_recipient_entity_sources(
        conn,
        committee_transaction_source_record_ids,
        len(stage4_fixture_set.itpas2_rows),
    )

    link_rows = _fetch_link_rows(conn, data_source_id, bulk_loader_fixture_set.linkage_ids)
    assert len(link_rows) == len(bulk_loader_fixture_set.ccl_rows)
    for row in link_rows:
        assert row["candidate_election_year"] == _PRIMARY_CYCLE
        assert row["fec_election_year"] == _PRIMARY_CYCLE
        assert row["period_start"].year == _PRIMARY_CYCLE
        assert row["period_end"].year == _PRIMARY_CYCLE + 1

    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) FROM cf.committee WHERE fec_committee_id = ANY(%s)",
            (bulk_loader_fixture_set.committee_ids,),
        )
        committee_count = cursor.fetchone()[0]
        cursor.execute(
            "SELECT COUNT(*) FROM cf.candidate WHERE fec_candidate_id = ANY(%s)",
            (bulk_loader_fixture_set.candidate_ids,),
        )
        candidate_count = cursor.fetchone()[0]

    assert committee_count == len(bulk_loader_fixture_set.committee_rows)
    assert candidate_count == len(bulk_loader_fixture_set.candidate_rows)


def _fetch_data_source_metadata(conn: psycopg.Connection, data_source_id: UUID) -> dict[str, object]:
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT record_count, last_pull_at, last_pull_status FROM core.data_source WHERE id = %s",
            (data_source_id,),
        )
        row = cursor.fetchone()
    assert row is not None
    return {"record_count": row[0], "last_pull_at": row[1], "last_pull_status": row[2]}


@pytest.mark.integration
def test_load_full_cycle_is_idempotent(
    bulk_loader_conn: psycopg.Connection,
    bulk_loader_fixture_set: BulkLoaderFixtureSet,
    stage4_fixture_set: Stage4FixtureSet,
    tmp_path: Path,
) -> None:
    data_source_id = ensure_fec_bulk_data_source(bulk_loader_conn)
    cycle_directory = _materialize_cycle_directory(tmp_path, bulk_loader_fixture_set, stage4_fixture_set)
    resolved_paths = bulk_cli.resolve_full_cycle_directory(cycle_directory)
    config = bulk_cli.CliConfig(
        mode="full",
        cycle=2024,
        file_type=None,
        path=None,
        directory=cycle_directory,
        batch_size=2,
        limit=None,
        graph_enabled=False,
    )

    first_run = bulk_cli.load_full_cycle(
        conn=bulk_loader_conn,
        config=config,
        data_source_id=data_source_id,
        resolved_paths=resolved_paths,
    )
    second_run = bulk_cli.load_full_cycle(
        conn=bulk_loader_conn,
        config=config,
        data_source_id=data_source_id,
        resolved_paths=resolved_paths,
    )

    expected_inserted_by_type = {
        "cm": len(bulk_loader_fixture_set.committee_rows),
        "cn": len(bulk_loader_fixture_set.candidate_rows),
        "ccl": len(bulk_loader_fixture_set.ccl_rows),
        "itcont": len(stage4_fixture_set.itcont_rows),
        "itpas2": len(stage4_fixture_set.itpas2_rows),
    }

    _assert_full_cycle_phase_results(first_run, second_run, expected_inserted_by_type)
    _assert_full_cycle_database_rows(
        bulk_loader_conn,
        data_source_id,
        bulk_loader_fixture_set,
        stage4_fixture_set,
    )


@pytest.mark.integration
def test_full_cycle_with_limit_loads_all_reference_files_but_caps_transactions(
    bulk_loader_conn: psycopg.Connection,
    bulk_loader_fixture_set: BulkLoaderFixtureSet,
    stage4_fixture_set: Stage4FixtureSet,
    tmp_path: Path,
) -> None:
    data_source_id = ensure_fec_bulk_data_source(bulk_loader_conn)
    cycle_directory = _materialize_cycle_directory(tmp_path, bulk_loader_fixture_set, stage4_fixture_set)
    resolved_paths = bulk_cli.resolve_full_cycle_directory(cycle_directory)
    config = bulk_cli.CliConfig(
        mode="full",
        cycle=2024,
        file_type=None,
        path=None,
        directory=cycle_directory,
        batch_size=2,
        limit=1,
        graph_enabled=False,
    )

    summaries = bulk_cli.load_full_cycle(
        conn=bulk_loader_conn,
        config=config,
        data_source_id=data_source_id,
        resolved_paths=resolved_paths,
    )

    results = {summary.file_type: summary.result for summary in summaries}

    assert results["cm"].inserted == len(bulk_loader_fixture_set.committee_rows)
    assert results["cn"].inserted == len(bulk_loader_fixture_set.candidate_rows)
    assert results["ccl"].inserted == len(bulk_loader_fixture_set.ccl_rows)
    assert results["itcont"].inserted == 1
    assert results["itpas2"].inserted == 1


@pytest.mark.integration
def test_finalize_full_cycle_metadata_after_successful_full_cycle(
    bulk_loader_conn: psycopg.Connection,
    bulk_loader_fixture_set: BulkLoaderFixtureSet,
    stage4_fixture_set: Stage4FixtureSet,
    tmp_path: Path,
) -> None:
    data_source_id = ensure_fec_bulk_data_source(bulk_loader_conn)
    cycle_directory = _materialize_cycle_directory(tmp_path, bulk_loader_fixture_set, stage4_fixture_set)
    resolved_paths = bulk_cli.resolve_full_cycle_directory(cycle_directory)
    config = bulk_cli.CliConfig(
        mode="full",
        cycle=2024,
        file_type=None,
        path=None,
        directory=cycle_directory,
        batch_size=2,
        limit=None,
        graph_enabled=False,
    )

    summaries = bulk_cli.load_full_cycle(
        conn=bulk_loader_conn,
        config=config,
        data_source_id=data_source_id,
        resolved_paths=resolved_paths,
    )
    outcome = bulk_cli.finalize_full_cycle_metadata(bulk_loader_conn, data_source_id, summaries)

    metadata = _fetch_data_source_metadata(bulk_loader_conn, data_source_id)
    active_count = count_source_records(bulk_loader_conn, data_source_id)

    assert metadata["record_count"] == active_count
    assert metadata["record_count"] > 0
    assert metadata["last_pull_status"] == "success"
    assert outcome.pull_status == "success"
    assert outcome.record_count == active_count
    assert metadata["last_pull_at"] is not None


@pytest.mark.integration
def test_finalize_full_cycle_metadata_marks_partial_when_full_cycle_rerun_has_row_errors(
    bulk_loader_conn: psycopg.Connection,
    bulk_loader_fixture_set: BulkLoaderFixtureSet,
    stage4_fixture_set: Stage4FixtureSet,
    tmp_path: Path,
) -> None:
    data_source_id = ensure_fec_bulk_data_source(bulk_loader_conn)
    cycle_directory = _materialize_cycle_directory(tmp_path, bulk_loader_fixture_set, stage4_fixture_set)
    resolved_paths = bulk_cli.resolve_full_cycle_directory(cycle_directory)
    config = bulk_cli.CliConfig(
        mode="full",
        cycle=2024,
        file_type=None,
        path=None,
        directory=cycle_directory,
        batch_size=2,
        limit=None,
        graph_enabled=False,
    )

    bulk_cli.load_full_cycle(
        conn=bulk_loader_conn,
        config=config,
        data_source_id=data_source_id,
        resolved_paths=resolved_paths,
    )
    active_count_before = count_source_records(bulk_loader_conn, data_source_id)

    bad_itcont_rows = [
        {**stage4_fixture_set.itcont_rows[0], "CMTE_ID": ""},
        *stage4_fixture_set.itcont_rows[1:],
    ]
    bad_itcont_path = tmp_path / "itcont_with_row_error.txt"
    _write_fixture_file(bad_itcont_path, ITCONT_COLUMNS, bad_itcont_rows)

    rerun_summaries = bulk_cli.load_full_cycle(
        conn=bulk_loader_conn,
        config=config,
        data_source_id=data_source_id,
        resolved_paths={**resolved_paths, "itcont": bad_itcont_path},
    )
    outcome = bulk_cli.finalize_full_cycle_metadata(bulk_loader_conn, data_source_id, rerun_summaries)

    metadata = _fetch_data_source_metadata(bulk_loader_conn, data_source_id)
    active_count_after = count_source_records(bulk_loader_conn, data_source_id)

    assert metadata["last_pull_status"] == "partial"
    assert metadata["record_count"] == active_count_after
    assert active_count_after == active_count_before
    assert outcome.pull_status == "partial"
    assert outcome.record_count == active_count_after


@pytest.mark.integration
def test_finalize_full_cycle_metadata_rerun_idempotency(
    bulk_loader_conn: psycopg.Connection,
    bulk_loader_fixture_set: BulkLoaderFixtureSet,
    stage4_fixture_set: Stage4FixtureSet,
    tmp_path: Path,
) -> None:
    data_source_id = ensure_fec_bulk_data_source(bulk_loader_conn)
    cycle_directory = _materialize_cycle_directory(tmp_path, bulk_loader_fixture_set, stage4_fixture_set)
    resolved_paths = bulk_cli.resolve_full_cycle_directory(cycle_directory)
    config = bulk_cli.CliConfig(
        mode="full",
        cycle=2024,
        file_type=None,
        path=None,
        directory=cycle_directory,
        batch_size=2,
        limit=None,
        graph_enabled=False,
    )

    summaries_1 = bulk_cli.load_full_cycle(
        conn=bulk_loader_conn,
        config=config,
        data_source_id=data_source_id,
        resolved_paths=resolved_paths,
    )
    outcome_1 = bulk_cli.finalize_full_cycle_metadata(bulk_loader_conn, data_source_id, summaries_1)
    count_after_first = _fetch_data_source_metadata(bulk_loader_conn, data_source_id)["record_count"]

    summaries_2 = bulk_cli.load_full_cycle(
        conn=bulk_loader_conn,
        config=config,
        data_source_id=data_source_id,
        resolved_paths=resolved_paths,
    )
    outcome_2 = bulk_cli.finalize_full_cycle_metadata(bulk_loader_conn, data_source_id, summaries_2)
    count_after_second = _fetch_data_source_metadata(bulk_loader_conn, data_source_id)["record_count"]

    active_count = count_source_records(bulk_loader_conn, data_source_id)
    assert count_after_first == count_after_second
    assert count_after_second == active_count
    assert outcome_1.record_count == outcome_2.record_count == active_count
