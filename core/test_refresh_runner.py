from __future__ import annotations

import json
import os
import signal
import threading
import zipfile
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Callable
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import psycopg
import pytest

from core import db
from core.refresh import job_builders, runner
from core.types.python.models import DataSource, RefreshRun
from core.refresh.test_job_builders import _EXPECTED_WEEKLY_FEDERAL_SCOPE_JOB_KEYS
from domains.campaign_finance.ingest.candidate_summary_loader import update_candidate_person_link
from domains.campaign_finance.ingest.federal_spine_loader import SpineLoadResult
from domains.civics.loaders.ncsbe_results import NcsbeResultsLoadSummary
from domains.civics.loaders.official_rosters.source_registry import list_nc_roster_source_metadata
from test_support.donor_search_fixture import (
    cleanup_donor_search_fixture,
    fetch_full_scope_donor_search_counts,
    seed_full_scope_skewed_donor_search_fixture,
)
from test_support.refresh_run_fixtures import (
    assert_single_in_flight_row,
    delete_refresh_runs_for_job,
    record_terminal_refresh_run,
    refresh_job_for_tests,
)


def _job_for_tests(
    *,
    key: str,
    run_callable: MagicMock | None = None,
    refresh_history_key: str | None = None,
    activity_denominator_result_field: str | None = None,
    data_source_names: tuple[str, ...] | None = None,
) -> runner.RefreshJob:
    overrides = {} if data_source_names is None else {"data_source_names": data_source_names}
    return refresh_job_for_tests(
        key,
        run_callable=run_callable,
        refresh_history_key=refresh_history_key,
        activity_denominator_result_field=activity_denominator_result_field,
        **overrides,
    )


_HISTORICAL_RECOVERY_STARTED_AT = datetime(2026, 8, 29, 23, 39, 28, tzinfo=timezone.utc)


def _historical_recovery_identity(
    **overrides: object,
) -> runner.HistoricalRefreshRecoveryIdentity:
    values: dict[str, object] = {
        "refresh_run_id": UUID("e00cb630-7024-4c5d-8c10-ef2a87e83db7"),
        "job_key": "state-wa-contributions",
        "domain": "campaign_finance",
        "jurisdiction": "state/WA",
        "filing_authority_type": "state",
        "filing_authority_code": "WA",
        "data_source_names": ("WA PDC Contributions",),
        "execution_origin": "operator_attended",
        "started_at": _HISTORICAL_RECOVERY_STARTED_AT,
        "app": "civibus-regional-refresh",
        "machine_id": "080d391a2ed098",
        "authority": "state/WA",
        "execution_plan": "regional-wa-scheduled",
        "database_host": "civibus-db.internal",
        "database_port": 5432,
        "database_name": "civibus",
    }
    values.update(overrides)
    return runner.HistoricalRefreshRecoveryIdentity(**values)


def _historical_running_attempt(
    identity: runner.HistoricalRefreshRecoveryIdentity,
    **overrides: object,
) -> RefreshRun:
    values: dict[str, object] = {
        "id": identity.refresh_run_id,
        "job_key": identity.job_key,
        "domain": identity.domain,
        "jurisdiction": identity.jurisdiction,
        "data_source_names": list(identity.data_source_names),
        "execution_origin": identity.execution_origin,
        "pull_status": "running",
        "started_at": identity.started_at,
        "completed_at": None,
        "metadata_updates": 0,
        "message": "Refresh job started",
    }
    values.update(overrides)
    return RefreshRun(**values)


def test_historical_recovery_classifies_only_exact_running_or_its_own_terminal_outcome() -> None:
    identity = _historical_recovery_identity()
    running = _historical_running_attempt(identity)

    assert runner._classify_historical_recovery_attempt(running, identity) == "running"

    completed_at = datetime(2026, 8, 30, 2, 0, tzinfo=timezone.utc)
    recovered = running.model_copy(
        update={
            "pull_status": "failed",
            "completed_at": completed_at,
            "message": runner._HISTORICAL_RECOVERY_MESSAGE,
            "error": runner._HISTORICAL_RECOVERY_ERROR,
        }
    )
    assert runner._classify_historical_recovery_attempt(recovered, identity) == "already_recovered"


@pytest.mark.parametrize(
    ("stored", "expected_error"),
    [
        (None, "missing"),
        (
            _historical_running_attempt(
                _historical_recovery_identity(),
                id=UUID("a00cb630-7024-4c5d-8c10-ef2a87e83db7"),
            ),
            "identity mismatch",
        ),
        (_historical_running_attempt(_historical_recovery_identity(), job_key="state-wa-loans"), "job identity"),
        (_historical_running_attempt(_historical_recovery_identity(), domain="civics"), "job identity"),
        (_historical_running_attempt(_historical_recovery_identity(), jurisdiction="state/OR"), "job identity"),
        (
            _historical_running_attempt(
                _historical_recovery_identity(),
                data_source_names=["WA PDC Expenditures"],
            ),
            "job identity",
        ),
        (
            _historical_running_attempt(_historical_recovery_identity(), execution_origin="scheduled"),
            "execution origin",
        ),
        (
            _historical_running_attempt(
                _historical_recovery_identity(),
                started_at=_HISTORICAL_RECOVERY_STARTED_AT + timedelta(seconds=1),
            ),
            "started_at",
        ),
        (
            _historical_running_attempt(
                _historical_recovery_identity(),
                pull_status="success",
                completed_at=datetime(2026, 8, 30, 2, 0, tzinfo=timezone.utc),
            ),
            "already terminal",
        ),
        (
            _historical_running_attempt(
                _historical_recovery_identity(),
                pull_status="failed",
                completed_at=datetime(2026, 8, 30, 2, 0, tzinfo=timezone.utc),
                message="some other failure",
                error="foreign terminal owner",
            ),
            "already terminal",
        ),
    ],
)
def test_historical_recovery_refuses_missing_foreign_mismatched_or_terminal_rows(
    stored: RefreshRun | None,
    expected_error: str,
) -> None:
    with pytest.raises(RuntimeError, match=expected_error):
        runner._classify_historical_recovery_attempt(stored, _historical_recovery_identity())


@pytest.mark.parametrize(
    ("rows", "expected_error"),
    [
        ([], "missing"),
        (
            [("WA PDC Contributions", "state", "OR")],
            "filing authority identity mismatch",
        ),
        (
            [
                ("WA PDC Contributions", "state", "WA"),
                ("WA PDC Contributions", "named_other", "WA-PDC"),
            ],
            "ambiguous",
        ),
        (
            [("WA PDC Expenditures", "state", "WA")],
            "data-source identity mismatch",
        ),
    ],
)
def test_historical_recovery_requires_exact_unambiguous_typed_data_source_identity(
    rows: list[tuple[str, str | None, str | None]],
    expected_error: str,
) -> None:
    with pytest.raises(RuntimeError, match=expected_error):
        runner._require_historical_recovery_data_source_identity(rows, _historical_recovery_identity())


def test_historical_recovery_builds_exact_existing_lifecycle_postcondition_shape() -> None:
    identity = _historical_recovery_identity()
    completed_at = datetime(2026, 8, 30, 2, 0, tzinfo=timezone.utc)
    attempt = _historical_running_attempt(identity).model_copy(
        update={
            "pull_status": "failed",
            "completed_at": completed_at,
            "message": runner._HISTORICAL_RECOVERY_MESSAGE,
            "error": runner._HISTORICAL_RECOVERY_ERROR,
        }
    )

    postcondition = runner.build_historical_recovery_postcondition(
        identity,
        attempt,
        running_refresh_rows=0,
        active_refresh_backends=0,
        long_idle_transactions=0,
        ungranted_locks=0,
    )

    assert postcondition == {
        "schema_version": 1,
        "app": "civibus-regional-refresh",
        "machine_id": "080d391a2ed098",
        "authority": "state/WA",
        "execution_plan": "regional-wa-scheduled",
        "refresh_run_id": "e00cb630-7024-4c5d-8c10-ef2a87e83db7",
        "job_key": "state-wa-contributions",
        "execution_origin": "operator_attended",
        "pull_status": "failed",
        "completed_at": "2026-08-30T02:00:00Z",
        "metadata_updates": 0,
        "running_refresh_rows": 0,
        "active_refresh_backends": 0,
        "long_idle_transactions": 0,
        "ungranted_locks": 0,
        "database": {"host": "civibus-db.internal", "port": 5432, "name": "civibus"},
    }
    assert json.dumps(postcondition, sort_keys=True) + "\n" == runner._serialize_refresh_postcondition(postcondition)


def test_historical_recovery_orders_preflight_advisory_row_lock_reproof_commit_and_postcondition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = _historical_recovery_identity()
    running = _historical_running_attempt(identity)
    terminal = running.model_copy(
        update={
            "pull_status": "failed",
            "completed_at": datetime(2026, 8, 30, 2, 0, tzinfo=timezone.utc),
            "message": runner._HISTORICAL_RECOVERY_MESSAGE,
            "error": runner._HISTORICAL_RECOVERY_ERROR,
        }
    )
    running_proof = runner._HistoricalRecoveryQuiescence(0, 0, 1, 0, 0)
    terminal_proof = runner._HistoricalRecoveryQuiescence(0, 0, 0, 0, 0)
    events: list[str] = []
    connection = MagicMock()
    connection.commit.side_effect = lambda: events.append("commit")
    connection.rollback.side_effect = lambda: events.append("rollback")
    attempts = iter((running, terminal))
    quiescence = iter((running_proof, running_proof, terminal_proof))

    monkeypatch.setattr(
        runner,
        "_require_historical_recovery_database_identity",
        lambda *args: events.append("database"),
    )
    monkeypatch.setattr(
        runner,
        "select_refresh_run",
        lambda *args: events.append("select") or next(attempts),
    )
    monkeypatch.setattr(
        runner,
        "_select_historical_recovery_data_source_rows",
        lambda *args: events.append("data_sources") or [("WA PDC Contributions", "state", "WA")],
    )
    monkeypatch.setattr(
        runner,
        "_read_historical_recovery_quiescence",
        lambda *args: events.append("quiescence") or next(quiescence),
    )
    monkeypatch.setattr(
        runner,
        "_try_acquire_historical_recovery_advisory_lock",
        lambda *args: events.append("advisory_lock") or True,
    )
    monkeypatch.setattr(
        runner,
        "_select_historical_recovery_attempt_for_update",
        lambda *args: events.append("row_lock") or running,
    )
    monkeypatch.setattr(
        runner,
        "_finish_refresh_run",
        lambda *args, **kwargs: events.append("finish"),
    )

    outcome = runner.recover_historical_refresh_attempt(connection, identity)

    assert outcome.already_terminal is False
    assert outcome.postcondition["pull_status"] == "failed"
    assert events == [
        "database",
        "select",
        "data_sources",
        "quiescence",
        "advisory_lock",
        "row_lock",
        "data_sources",
        "quiescence",
        "finish",
        "commit",
        "select",
        "data_sources",
        "quiescence",
        "rollback",
    ]


@pytest.mark.parametrize(
    ("proof", "expected_error"),
    [
        (runner._HistoricalRecoveryQuiescence(1, 1, 1, 0, 0), "exact historical refresh job"),
        (runner._HistoricalRecoveryQuiescence(0, 1, 1, 0, 0), "conflicting refresh backend"),
        (runner._HistoricalRecoveryQuiescence(0, 0, 2, 0, 0), "running-row quiescence mismatch"),
        (runner._HistoricalRecoveryQuiescence(0, 0, 1, 1, 0), "long-idle"),
        (runner._HistoricalRecoveryQuiescence(0, 0, 1, 0, 1), "ungranted"),
    ],
)
def test_historical_recovery_refuses_nonquiescent_backend_row_transaction_or_lock_state(
    proof: runner._HistoricalRecoveryQuiescence,
    expected_error: str,
) -> None:
    with pytest.raises(RuntimeError, match=expected_error):
        runner._require_historical_recovery_quiescence(proof, expected_running_refresh_rows=1)


def test_historical_recovery_rolls_back_when_attempt_changes_after_preflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = _historical_recovery_identity()
    running = _historical_running_attempt(identity)
    changed = running.model_copy(update={"message": "changed after preflight"})
    connection = MagicMock()
    finish_refresh_run = MagicMock()
    monkeypatch.setattr(runner, "_require_historical_recovery_database_identity", lambda *args: None)
    monkeypatch.setattr(runner, "select_refresh_run", lambda *args: running)
    monkeypatch.setattr(
        runner,
        "_select_historical_recovery_data_source_rows",
        lambda *args: [("WA PDC Contributions", "state", "WA")],
    )
    monkeypatch.setattr(
        runner,
        "_read_historical_recovery_quiescence",
        lambda *args: runner._HistoricalRecoveryQuiescence(0, 0, 1, 0, 0),
    )
    monkeypatch.setattr(runner, "_try_acquire_historical_recovery_advisory_lock", lambda *args: True)
    monkeypatch.setattr(runner, "_select_historical_recovery_attempt_for_update", lambda *args: changed)
    monkeypatch.setattr(runner, "_finish_refresh_run", finish_refresh_run)

    with pytest.raises(RuntimeError, match="changed after preflight|outcome identity mismatch"):
        runner.recover_historical_refresh_attempt(connection, identity)

    connection.rollback.assert_called_once_with()
    connection.commit.assert_not_called()
    finish_refresh_run.assert_not_called()


def test_historical_recovery_postcondition_persistence_is_exact_idempotent_and_no_overwrite(
    tmp_path: Path,
) -> None:
    identity = _historical_recovery_identity()
    terminal = _historical_running_attempt(identity).model_copy(
        update={
            "pull_status": "failed",
            "completed_at": datetime(2026, 8, 30, 2, 0, tzinfo=timezone.utc),
            "message": runner._HISTORICAL_RECOVERY_MESSAGE,
            "error": runner._HISTORICAL_RECOVERY_ERROR,
        }
    )
    postcondition = runner.build_historical_recovery_postcondition(
        identity,
        terminal,
        running_refresh_rows=0,
        active_refresh_backends=0,
        long_idle_transactions=0,
        ungranted_locks=0,
    )
    path = tmp_path / "postcondition.json"

    runner.persist_historical_recovery_postcondition(path, postcondition)
    runner.persist_historical_recovery_postcondition(path, postcondition)

    assert path.read_text(encoding="utf-8") == json.dumps(postcondition, sort_keys=True) + "\n"
    path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="different content"):
        runner.persist_historical_recovery_postcondition(path, postcondition)


def _historical_recovery_cli_args(postcondition_path: Path) -> list[str]:
    return [
        "--recover-refresh-run-id",
        "e00cb630-7024-4c5d-8c10-ef2a87e83db7",
        "--recover-job-key",
        "state-wa-contributions",
        "--recover-domain",
        "campaign_finance",
        "--recover-jurisdiction",
        "state/WA",
        "--recover-filing-authority-type",
        "state",
        "--recover-filing-authority-code",
        "WA",
        "--recover-data-source-name",
        "WA PDC Contributions",
        "--recover-execution-origin",
        "operator_attended",
        "--recover-started-at",
        "2026-08-29T23:39:28Z",
        "--recover-app",
        "civibus-regional-refresh",
        "--recover-machine-id",
        "080d391a2ed098",
        "--recover-authority",
        "state/WA",
        "--recover-execution-plan",
        "regional-wa-scheduled",
        "--recover-database-host",
        "civibus-db.internal",
        "--recover-database-port",
        "5432",
        "--recover-database-name",
        "civibus",
        "--recover-postcondition-json",
        str(postcondition_path),
    ]


def test_historical_recovery_cli_requires_and_dispatches_complete_expected_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: list[tuple[runner.HistoricalRefreshRecoveryIdentity, Path]] = []
    monkeypatch.setattr(
        runner,
        "_run_historical_recovery_cli",
        lambda identity, path: captured.append((identity, path)) or 0,
    )
    postcondition_path = tmp_path / "postcondition.json"

    exit_code = runner.main(_historical_recovery_cli_args(postcondition_path))

    assert exit_code == 0
    assert captured == [(_historical_recovery_identity(), postcondition_path)]


def test_historical_recovery_cli_refuses_incomplete_or_mixed_mode_options(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    dispatch = MagicMock()
    monkeypatch.setattr(runner, "_run_historical_recovery_cli", dispatch)
    complete = _historical_recovery_cli_args(tmp_path / "postcondition.json")
    started_at_index = complete.index("--recover-started-at")
    incomplete = complete[:started_at_index] + complete[started_at_index + 2 :]

    with pytest.raises(SystemExit) as missing:
        runner.main(incomplete)
    with pytest.raises(SystemExit) as mixed:
        runner.main([*complete, "--force"])

    assert missing.value.code == 2
    assert mixed.value.code == 2
    dispatch.assert_not_called()


def test_build_refresh_plan_all_scope_emits_canonical_stage6_job_keys() -> None:
    jobs = job_builders.build_refresh_plan(scope="all")
    job_keys = tuple(job.key for job in jobs)
    expected_job_keys = (
        "federal-fec-masters",
        "federal-fec-schedule-a",
        "federal-fec-committee-summary",
        "federal-congress-spine",
        "federal-fec-races",
        "federal-donor-search-rollup",
        "federal-fec-schedule-b",
        "federal-fec-schedule-e",
        "federal-enrichment",
        "federal-irs-527",
        "federal-geometry-probe",
        "state-al-contributions",
        "state-al-expenditures",
        "state-ca-refresh",
        "state-co-contributions",
        "state-co-expenditures",
        "state-fl-contributions",
        "state-fl-expenditures",
        "state-fl-transfers",
        "state-fl-other",
        "state-ga-contributions",
        "state-ga-expenditures",
        "state-il-contributions",
        "state-il-expenditures",
        "state-in-contributions",
        "state-in-expenditures",
        "state-ky-expenditures",
        "state-ky-contributions-5-17-2022",
        "state-ky-contributions-11-8-2022",
        "state-ky-contributions-5-16-2023",
        "state-ky-contributions-11-7-2023",
        "state-ky-contributions-5-21-2024",
        "state-ky-contributions-11-5-2024",
        "state-ky-contributions-5-19-2026",
        "state-la-contributions",
        "state-la-loans",
        "state-la-expenditures",
        "state-ma-contributions",
        "state-ma-expenditures",
        "state-mn-contributions",
        "state-mn-expenditures",
        "state-mn-independent_expenditures",
        "state-nc-committee-discovery",
        "civic-nc-candidate-listing",
        "state-ne-contributions",
        "state-ne-loans",
        "state-ne-expenditures",
        "state-nj-contributions",
        "state-ny-contributions",
        "state-ny-expenditures",
        "state-ny-independent_expenditures",
        "state-or-contributions",
        "state-or-expenditures",
        "state-pa-contributions",
        "state-pa-expenditures",
        "state-pa-debts",
        "state-pa-receipts",
        "state-tx-contributions",
        "state-tx-expenditures",
        "state-tx-loans",
        "state-va-contributions",
        "state-va-expenditures",
        "state-wa-contributions",
        "state-wa-expenditures",
        "state-wa-independent_expenditures",
        "state-wa-loans",
        "state-wi-transactions",
        "city-la-transactions",
        "city-nyc-transactions",
        "city-phl-contributions",
        "city-phl-expenditures",
        "city-sf-transactions",
        "civic-rosters-council-of-state-ag-comm",
        "civic-rosters-council-of-state-ag",
        "civic-rosters-council-of-state-auditor",
        "civic-rosters-nc-appeals",
        "civic-rosters-council-of-state-gov",
        "civic-rosters-council-of-state-ins-comm",
        "civic-rosters-council-of-state-labor-comm",
        "civic-rosters-council-of-state-lt-gov",
        "civic-rosters-council-of-state-sos",
        "civic-rosters-nc-senate",
        "civic-rosters-nc-supreme",
        "civic-rosters-council-of-state-supt",
        "civic-rosters-council-of-state-treasurer",
        "civic-rosters-us-house-nc",
        "civic-rosters-us-senate-nc-ii",
        "civic-rosters-us-senate-nc-iii",
    ) + tuple(f"civics-roster-{metadata.source_id}" for metadata in list_nc_roster_source_metadata())

    assert job_keys == expected_job_keys
    assert len(job_keys) == len(set(job_keys))
    assert len(job_keys) == 115
    assert "state-nc-ie-transactions" not in job_keys
    assert "state-nc-transactions" not in job_keys
    assert "state-nc-ie-document-index" not in job_keys
    assert "civics-nc-past-results-2022-2024" not in job_keys


def test_federal_plan_wires_committee_summary_after_schedule_a() -> None:
    job_keys = tuple(job.key for job in job_builders.build_refresh_plan(scope="federal"))

    assert job_keys.index("federal-fec-schedule-a") < job_keys.index("federal-fec-committee-summary")


def test_build_refresh_plan_adds_nc_jobs_from_independent_input_paths() -> None:
    committee_docs_path = Path("/tmp/stage5_nc_committee_docs_27075.csv")
    ie_document_index_path = Path("/tmp/stage5_nc_ie_document_index_27075.csv")

    jobs_without_nc = job_builders.build_refresh_plan(scope="all")
    jobs_with_transaction_nc = job_builders.build_refresh_plan(
        scope="all",
        parameters=runner.RunnerParameters(
            nc_committee_docs_path=committee_docs_path,
            nc_committee_id="STA-C3219N-C-001",
            nc_committee_name="NC REALTORS PAC",
        ),
    )
    jobs_with_ie_nc = job_builders.build_refresh_plan(
        scope="all",
        parameters=runner.RunnerParameters(
            nc_ie_document_index_path=ie_document_index_path,
        ),
    )
    jobs_with_both_nc = job_builders.build_refresh_plan(
        scope="all",
        parameters=runner.RunnerParameters(
            nc_committee_docs_path=committee_docs_path,
            nc_committee_id="STA-C3219N-C-001",
            nc_committee_name="NC REALTORS PAC",
            nc_ie_document_index_path=ie_document_index_path,
        ),
    )

    job_keys_without_nc = {job.key for job in jobs_without_nc}
    job_keys_with_transaction_nc = {job.key for job in jobs_with_transaction_nc}
    job_keys_with_ie_nc = {job.key for job in jobs_with_ie_nc}
    job_keys_with_both_nc = {job.key for job in jobs_with_both_nc}

    assert len(job_keys_without_nc) == 115
    assert len(job_keys_with_transaction_nc) == 116
    assert len(job_keys_with_ie_nc) == 117
    assert len(job_keys_with_both_nc) == 118
    assert "state-nc-ie-transactions" not in job_keys_without_nc
    assert "state-nc-ie-transactions" not in job_keys_with_transaction_nc
    assert "state-nc-ie-transactions" in job_keys_with_ie_nc
    assert "state-nc-ie-transactions" in job_keys_with_both_nc
    assert "state-nc-ie-document-index" not in job_keys_without_nc
    assert "state-nc-ie-document-index" not in job_keys_with_transaction_nc
    assert "state-nc-ie-document-index" in job_keys_with_ie_nc
    assert "state-nc-ie-document-index" in job_keys_with_both_nc
    assert "state-nc-transactions" not in job_keys_without_nc
    assert "state-nc-transactions" in job_keys_with_transaction_nc
    assert "state-nc-transactions" not in job_keys_with_ie_nc
    assert "state-nc-transactions" in job_keys_with_both_nc
    assert "civics-nc-past-results-2022-2024" not in job_keys_without_nc
    assert "civics-nc-past-results-2022-2024" not in job_keys_with_transaction_nc
    assert "civics-nc-past-results-2022-2024" not in job_keys_with_ie_nc
    assert "civics-nc-past-results-2022-2024" not in job_keys_with_both_nc


def test_build_refresh_plan_wires_federal_schedule_a_bulk_job_parameters(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo_root = tmp_path / "fec-cache-root"
    connection = MagicMock()
    data_source_id = UUID("6f93a177-c7ca-4a16-88e6-932245a1ddaf")
    load_result = object()

    def _fake_download(url: str, destination_path: Path) -> tuple[Path, object]:
        with zipfile.ZipFile(destination_path, "w") as archive:
            archive.writestr("itcont24.txt", "ignored")
        return destination_path, None

    urlretrieve = MagicMock(side_effect=_fake_download)
    ensure_fec_bulk_data_source = MagicMock(return_value=data_source_id)
    dispatch_load = MagicMock(return_value=load_result)
    get_connection = MagicMock(return_value=connection)

    monkeypatch.setattr(job_builders, "_REPO_ROOT", repo_root)
    monkeypatch.setattr(job_builders, "urlretrieve", urlretrieve)
    monkeypatch.setattr(job_builders, "get_connection", get_connection)
    monkeypatch.setattr(job_builders, "ensure_fec_bulk_data_source", ensure_fec_bulk_data_source)
    monkeypatch.setattr(job_builders, "dispatch_load", dispatch_load)

    jobs = job_builders.build_refresh_plan(
        scope="all",
        parameters=runner.RunnerParameters(fec_cycle=2024, fec_limit=50),
    )
    jobs_by_key = {job.key: job for job in jobs}
    job = jobs_by_key["federal-fec-schedule-a"]

    result = job.run_callable()

    assert result == load_result
    assert job.data_source_names == (job_builders.FEC_BULK_DATA_SOURCE_NAME,)
    assert urlretrieve.call_args.args[0] == job_builders.fec_baseline_url(2024, "itcont")
    assert Path(urlretrieve.call_args.args[1]).name == "itcont24.zip.part"

    get_connection.assert_called_once_with()
    connection.transaction.assert_called_once_with()
    ensure_fec_bulk_data_source.assert_called_once_with(connection)
    connection.close.assert_called_once_with()

    dispatch_load.assert_called_once()
    dispatch_call = dispatch_load.call_args.kwargs
    config = dispatch_call["config"]
    request = dispatch_call["request"]

    assert dispatch_call["conn"] is connection
    assert dispatch_call["data_source_id"] == data_source_id
    assert config.mode == "single"
    assert config.cycle == 2024
    assert config.file_type == "itcont"
    assert config.batch_size == 1000
    assert config.limit == 50
    assert config.graph_enabled is False
    assert config.with_transactions is False
    assert config.transactions_only is True
    assert config.spine_only is True
    assert config.min_date == date(2022, 1, 1)
    assert request.file_type == "itcont"
    assert request.path == config.path
    assert request.path == repo_root / "data" / "fec" / "bulk" / "2024" / "itcont24.zip"


def test_federal_schedule_a_reuses_cached_bulk_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cached_file = tmp_path / "data" / "fec" / "bulk" / "2024" / "itcont24.zip"
    cached_file.parent.mkdir(parents=True)
    cached_file.write_bytes(b"cached")
    connection = MagicMock()

    monkeypatch.setattr(job_builders, "_REPO_ROOT", tmp_path)
    monkeypatch.setattr(job_builders, "urlretrieve", MagicMock())
    monkeypatch.setattr(job_builders, "get_connection", MagicMock(return_value=connection))
    monkeypatch.setattr(job_builders, "ensure_fec_bulk_data_source", MagicMock(return_value=uuid4()))
    dispatch_load = MagicMock(return_value=object())
    monkeypatch.setattr(job_builders, "dispatch_load", dispatch_load)

    jobs = job_builders.build_refresh_plan(
        scope="all",
        parameters=runner.RunnerParameters(fec_cycle=2024, fec_limit=50),
    )
    {job.key: job for job in jobs}["federal-fec-schedule-a"].run_callable()

    job_builders.urlretrieve.assert_not_called()
    assert dispatch_load.call_args.kwargs["request"].path == cached_file


def test_federal_schedule_a_uses_refresh_data_dir_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    refresh_data_dir = tmp_path / "fly-data"
    connection = MagicMock()
    load_result = object()

    def _fake_download(url: str, destination_path: Path) -> tuple[Path, object]:
        with zipfile.ZipFile(destination_path, "w") as archive:
            archive.writestr("itcont24.txt", "ignored")
        return destination_path, None

    monkeypatch.setenv("CIVIBUS_REFRESH_DATA_DIR", str(refresh_data_dir))
    monkeypatch.setattr(job_builders, "urlretrieve", MagicMock(side_effect=_fake_download))
    monkeypatch.setattr(job_builders, "get_connection", MagicMock(return_value=connection))
    monkeypatch.setattr(job_builders, "ensure_fec_bulk_data_source", MagicMock(return_value=uuid4()))
    dispatch_load = MagicMock(return_value=load_result)
    monkeypatch.setattr(job_builders, "dispatch_load", dispatch_load)

    jobs = job_builders.build_refresh_plan(
        scope="federal",
        parameters=runner.RunnerParameters(fec_cycle=2024, fec_limit=50),
    )
    result = {job.key: job for job in jobs}["federal-fec-schedule-a"].run_callable()

    assert result == load_result
    assert dispatch_load.call_args.kwargs["request"].path == (
        refresh_data_dir / "fec" / "bulk" / "2024" / "itcont24.zip"
    )


def test_federal_temporary_refresh_directory_uses_refresh_data_dir_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    refresh_data_dir = tmp_path / "fly-data"
    monkeypatch.setenv("CIVIBUS_REFRESH_DATA_DIR", str(refresh_data_dir))

    with job_builders._temporary_refresh_directory(prefix="refresh-contract-") as temp_dir:
        temp_dir_path = Path(temp_dir)
        assert temp_dir_path.parent == refresh_data_dir / "tmp"
        assert temp_dir_path.name.startswith("refresh-contract-")
        assert temp_dir_path.exists()

    assert not temp_dir_path.exists()


def test_build_refresh_plan_wires_federal_schedule_b_job_parameters(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock()
    data_source_id = UUID("6f93a177-c7ca-4a16-88e6-932245a1ddaf")
    load_result = object()

    def _fake_download(url: str, destination_path: Path) -> tuple[Path, object]:
        with zipfile.ZipFile(destination_path, "w") as archive:
            archive.writestr("oppexp24.txt", "ignored")
        return destination_path, None

    urlretrieve = MagicMock(side_effect=_fake_download)
    ensure_fec_bulk_data_source = MagicMock(return_value=data_source_id)
    dispatch_load = MagicMock(return_value=load_result)
    get_connection = MagicMock(return_value=connection)

    monkeypatch.setattr(job_builders, "urlretrieve", urlretrieve)
    monkeypatch.setattr(job_builders, "get_connection", get_connection)
    monkeypatch.setattr(job_builders, "ensure_fec_bulk_data_source", ensure_fec_bulk_data_source)
    monkeypatch.setattr(job_builders, "dispatch_load", dispatch_load)

    jobs = job_builders.build_refresh_plan(
        scope="all",
        parameters=runner.RunnerParameters(fec_cycle=2024, fec_limit=50),
    )
    jobs_by_key = {job.key: job for job in jobs}

    result = jobs_by_key["federal-fec-schedule-b"].run_callable()

    assert result is load_result
    assert urlretrieve.call_args.args[0] == job_builders.fec_schedule_b_url(2024)
    assert Path(urlretrieve.call_args.args[1]).name == "oppexp24.zip"

    get_connection.assert_called_once_with()
    connection.transaction.assert_called_once_with()
    ensure_fec_bulk_data_source.assert_called_once_with(connection)
    connection.close.assert_called_once_with()

    dispatch_load.assert_called_once()
    dispatch_call = dispatch_load.call_args.kwargs
    config = dispatch_call["config"]
    request = dispatch_call["request"]

    assert dispatch_call["conn"] is connection
    assert dispatch_call["data_source_id"] == data_source_id
    assert config.mode == "single"
    assert config.cycle == 2024
    assert config.file_type == "schedule_b"
    assert config.batch_size == 1000
    assert config.limit == 50
    assert config.graph_enabled is False
    assert config.with_transactions is False
    assert request.file_type == "schedule_b"
    assert request.path == config.path


def test_build_refresh_plan_loads_schedule_e_for_every_active_cycle(monkeypatch: pytest.MonkeyPatch) -> None:
    """Schedule E must cover the same active-cycle window Schedule A does.

    Loading only the current cycle left the previous cycle with no independent
    expenditures at all, so every candidate in a 2024 race reported "outside
    spending not loaded" no matter how much was actually spent on it.
    """
    connection = MagicMock()
    data_source_id = UUID("6f93a177-c7ca-4a16-88e6-932245a1ddaf")
    load_results = [object(), object()]

    urlretrieve = MagicMock()
    ensure_fec_bulk_data_source = MagicMock(return_value=data_source_id)
    dispatch_load = MagicMock(side_effect=load_results)
    get_connection = MagicMock(return_value=connection)

    monkeypatch.setattr(job_builders, "urlretrieve", urlretrieve)
    monkeypatch.setattr(job_builders, "get_connection", get_connection)
    monkeypatch.setattr(job_builders, "ensure_fec_bulk_data_source", ensure_fec_bulk_data_source)
    monkeypatch.setattr(job_builders, "dispatch_load", dispatch_load)

    jobs = job_builders.build_refresh_plan(
        scope="all",
        parameters=runner.RunnerParameters(fec_cycle=2026, fec_limit=50),
    )
    jobs_by_key = {job.key: job for job in jobs}

    result = jobs_by_key["federal-fec-schedule-e"].run_callable()

    # The same two cycles Schedule A loads, from the same owner, in the same order.
    assert job_builders._active_fec_transaction_cycles(2026) == (2024, 2026)
    assert [call.args[0] for call in urlretrieve.call_args_list] == [
        job_builders.fec_schedule_e_url(2024),
        job_builders.fec_schedule_e_url(2026),
    ]
    assert [Path(call.args[1]).name for call in urlretrieve.call_args_list] == [
        "independent_expenditure_2024.csv",
        "independent_expenditure_2026.csv",
    ]
    assert result == load_results

    get_connection.assert_called_once_with()
    ensure_fec_bulk_data_source.assert_called_once_with(connection)
    connection.close.assert_called_once_with()

    assert dispatch_load.call_count == 2
    dispatched_cycles = [call.kwargs["config"].cycle for call in dispatch_load.call_args_list]
    assert dispatched_cycles == [2024, 2026]
    for call in dispatch_load.call_args_list:
        config = call.kwargs["config"]
        assert call.kwargs["conn"] is connection
        assert call.kwargs["data_source_id"] == data_source_id
        assert config.mode == "single"
        assert config.file_type == "schedule_e"
        assert config.batch_size == 1000
        assert config.limit is None
        assert config.graph_enabled is False
        assert config.with_transactions is False
        assert call.kwargs["request"].file_type == "schedule_e"
        assert call.kwargs["request"].path == config.path


def test_build_refresh_plan_wires_federal_fec_masters_job_parameters(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock()
    data_source_id = UUID("6f93a177-c7ca-4a16-88e6-932245a1ddaf")
    load_results = [object(), object(), object(), object()]
    downloaded_payloads = {
        "cm": "cm24.txt",
        "cn": "cn24.txt",
        "ccl": "ccl24.txt",
        "weball": "weball24.txt",
    }

    def _fake_download(url: str, destination_path: Path) -> tuple[Path, object]:
        file_type = destination_path.stem.removesuffix("24")
        with zipfile.ZipFile(destination_path, "w") as archive:
            archive.writestr(downloaded_payloads[file_type], "ignored")
        return destination_path, None

    urlretrieve = MagicMock(side_effect=_fake_download)
    ensure_fec_bulk_data_source = MagicMock(return_value=data_source_id)
    dispatch_load = MagicMock(side_effect=load_results)
    get_connection = MagicMock(return_value=connection)

    monkeypatch.setattr(job_builders, "urlretrieve", urlretrieve)
    monkeypatch.setattr(job_builders, "get_connection", get_connection)
    monkeypatch.setattr(job_builders, "ensure_fec_bulk_data_source", ensure_fec_bulk_data_source)
    monkeypatch.setattr(job_builders, "dispatch_load", dispatch_load)

    jobs = job_builders.build_refresh_plan(
        scope="all",
        parameters=runner.RunnerParameters(fec_cycle=2024, fec_limit=50),
    )
    job = {candidate.key: candidate for candidate in jobs}["federal-fec-masters"]

    result = job.run_callable()

    assert result == load_results
    assert job.domain == "campaign_finance"
    assert job.jurisdiction == "federal/fec"
    assert job.cadence == "weekly"
    assert job.data_source_names == (job_builders.FEC_BULK_DATA_SOURCE_NAME,)
    assert job.refresh_history_key == "federal-fec-masters"
    assert [call.args[0] for call in urlretrieve.call_args_list] == [
        job_builders.fec_baseline_url(2024, "cm"),
        job_builders.fec_baseline_url(2024, "cn"),
        job_builders.fec_baseline_url(2024, "ccl"),
        job_builders.fec_weball_url(2024),
    ]
    downloaded_paths = [Path(call.args[1]) for call in urlretrieve.call_args_list]
    assert [path.name for path in downloaded_paths] == ["cm24.zip", "cn24.zip", "ccl24.zip", "weball24.zip"]

    get_connection.assert_called_once_with()
    connection.transaction.assert_called_once_with()
    ensure_fec_bulk_data_source.assert_called_once_with(connection)
    connection.close.assert_called_once_with()

    assert dispatch_load.call_count == 4
    assert [call.kwargs["conn"] for call in dispatch_load.call_args_list] == [connection] * 4
    assert [call.kwargs["data_source_id"] for call in dispatch_load.call_args_list] == [data_source_id] * 4
    assert [call.kwargs["request"].file_type for call in dispatch_load.call_args_list] == [
        "cm",
        "cn",
        "ccl",
        "weball",
    ]
    assert [call.kwargs["request"].path for call in dispatch_load.call_args_list] == downloaded_paths

    for file_type, path, call in zip(("cm", "cn", "ccl", "weball"), downloaded_paths, dispatch_load.call_args_list):
        assert call.kwargs["config"] == job_builders.CliConfig(
            mode="single",
            cycle=2024,
            file_type=file_type,
            path=path,
            directory=None,
            batch_size=1000,
            limit=None,
            graph_enabled=False,
            with_transactions=False,
        )
        assert call.kwargs["request"].path == path


def test_build_refresh_plan_wires_federal_congress_spine_job_callable(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []
    raw_entries = [{"id": {"bioguide": "A000001"}}]
    adapted_legislators = object()
    historical_entries = [{"id": {"bioguide": "OLD0001"}}]
    vacancy_predecessors = object()
    data_source_id = UUID("a5eb7397-d8c9-41ee-8a7a-4179114819c1")
    load_result = object()

    class _Transaction:
        def __enter__(self) -> None:
            events.append("transaction_enter")

        def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
            events.append("transaction_exit")

    class _Connection:
        def transaction(self) -> _Transaction:
            events.append("transaction")
            return _Transaction()

        def close(self) -> None:
            events.append("close")

    connection = _Connection()

    def _fetch_legislators_entries() -> list[dict[str, object]]:
        events.append("fetch")
        return raw_entries

    def _adapt_legislators_yaml(entries: list[dict[str, object]]) -> object:
        events.append("adapt")
        assert entries is raw_entries
        return adapted_legislators

    def _fetch_historical_entries() -> list[dict[str, object]]:
        events.append("fetch_historical")
        return historical_entries

    def _select_most_recent_vacancy_predecessors(adapted: object, history: list[dict[str, object]]) -> object:
        events.append("select_vacancies")
        assert adapted is adapted_legislators
        assert history is historical_entries
        return vacancy_predecessors

    def _get_connection() -> _Connection:
        events.append("get_connection")
        return connection

    def _ensure_federal_spine_data_source(conn: _Connection) -> UUID:
        events.append("ensure_data_source")
        assert conn is connection
        return data_source_id

    def _load_federal_spine(conn: _Connection, adapted: object, *, data_source_id: UUID) -> object:
        events.append("load")
        assert conn is connection
        assert adapted is adapted_legislators
        assert data_source_id == UUID("a5eb7397-d8c9-41ee-8a7a-4179114819c1")
        return load_result

    def _load_vacancy_predecessors(conn: _Connection, predecessors: object, *, data_source_id: UUID) -> int:
        events.append("load_vacancies")
        assert conn is connection
        assert predecessors is vacancy_predecessors
        assert data_source_id == UUID("a5eb7397-d8c9-41ee-8a7a-4179114819c1")
        return 5

    monkeypatch.setattr(job_builders, "fetch_legislators_entries", _fetch_legislators_entries)
    monkeypatch.setattr(job_builders, "adapt_legislators_yaml", _adapt_legislators_yaml)
    monkeypatch.setattr(job_builders, "fetch_historical_entries", _fetch_historical_entries)
    monkeypatch.setattr(
        job_builders,
        "select_most_recent_vacancy_predecessors",
        _select_most_recent_vacancy_predecessors,
    )
    monkeypatch.setattr(job_builders, "get_connection", _get_connection)
    monkeypatch.setattr(job_builders, "ensure_federal_spine_data_source", _ensure_federal_spine_data_source)
    monkeypatch.setattr(job_builders, "load_federal_spine", _load_federal_spine)
    monkeypatch.setattr(job_builders, "load_vacancy_predecessors", _load_vacancy_predecessors)

    job = job_builders.build_refresh_plan(scope="all", job_key_prefixes=("federal-congress-spine",))[0]

    result = job.run_callable()

    assert result is load_result
    assert job.domain == "campaign_finance"
    assert job.jurisdiction == "federal/congress"
    assert job.cadence == "weekly"
    assert job.data_source_names == (job_builders.FEDERAL_SPINE_DATA_SOURCE_NAME,)
    assert events == [
        "fetch",
        "adapt",
        "fetch_historical",
        "select_vacancies",
        "get_connection",
        "transaction",
        "transaction_enter",
        "ensure_data_source",
        "load",
        "load_vacancies",
        "transaction_exit",
        "close",
    ]


def test_federal_congress_spine_job_closes_connection_when_load_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []
    load_error = RuntimeError("load failed")

    class _Transaction:
        def __enter__(self) -> None:
            events.append("transaction_enter")

        def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
            events.append("transaction_exit")

    class _Connection:
        def transaction(self) -> _Transaction:
            events.append("transaction")
            return _Transaction()

        def close(self) -> None:
            events.append("close")

    connection = _Connection()

    monkeypatch.setattr(job_builders, "fetch_legislators_entries", lambda: [])
    monkeypatch.setattr(job_builders, "adapt_legislators_yaml", lambda entries: object())
    monkeypatch.setattr(job_builders, "fetch_historical_entries", lambda: [])
    monkeypatch.setattr(
        job_builders,
        "select_most_recent_vacancy_predecessors",
        lambda adapted, history: object(),
    )
    monkeypatch.setattr(job_builders, "get_connection", lambda: connection)
    monkeypatch.setattr(
        job_builders, "ensure_federal_spine_data_source", lambda conn: UUID("8878d325-f9f3-4e06-8f55-d5a7de1f7f67")
    )

    def _load_federal_spine(conn: _Connection, adapted: object, *, data_source_id: UUID) -> object:
        events.append("load")
        raise load_error

    monkeypatch.setattr(job_builders, "load_federal_spine", _load_federal_spine)
    monkeypatch.setattr(job_builders, "load_vacancy_predecessors", lambda conn, predecessors, *, data_source_id: 0)
    job = job_builders.build_refresh_plan(scope="all", job_key_prefixes=("federal-congress-spine",))[0]

    with pytest.raises(RuntimeError, match="load failed"):
        job.run_callable()

    assert events == ["transaction", "transaction_enter", "load", "transaction_exit", "close"]


def test_federal_fec_masters_uses_refresh_run_history_for_cadence_gate() -> None:
    job = job_builders.build_refresh_plan(scope="all", job_key_prefixes=("federal-fec-masters",))[0]
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = (datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),)

    latest_pull_at = runner.select_latest_pull_at(connection, job)

    assert latest_pull_at == datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    query = cursor.execute.call_args.args[0]
    params = cursor.execute.call_args.args[1]
    assert "FROM core.refresh_run" in query
    assert "job_key = %s" in query
    assert "pull_status = ANY(%s)" in query
    assert params == ("federal-fec-masters", ["success"])


def test_public_cadence_selector_data_source_branch_uses_runner_data_source_identity() -> None:
    job = _job_for_tests(
        key="state-co-contributions",
        refresh_history_key=None,
        data_source_names=("TRACER Bulk Download — Contributions",),
    )
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = (datetime(2026, 6, 2, 12, 0, tzinfo=timezone.utc),)

    latest_pull_at = runner.select_latest_pull_at(connection, job)

    assert latest_pull_at == datetime(2026, 6, 2, 12, 0, tzinfo=timezone.utc)
    query = cursor.execute.call_args.args[0]
    params = cursor.execute.call_args.args[1]
    assert "FROM core.data_source" in query
    assert "MAX(last_pull_at)" in query
    assert "domain = %s" in query
    assert "jurisdiction = %s" in query
    assert "name = ANY(%s)" in query
    assert params == (
        "campaign_finance",
        "state/CO",
        ["TRACER Bulk Download — Contributions"],
    )


def test_select_latest_completed_run_returns_newer_failed_attempt_not_older_success() -> None:
    job = _job_for_tests(key="state-co-contributions", refresh_history_key="state-co-cadence-history")
    completed_at = datetime(2026, 6, 3, 12, 0, tzinfo=timezone.utc)
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = (completed_at, "crashed", "legacy_unknown", 11, 22, 33, 44, 55, "boom")

    latest_run = runner.select_latest_completed_run(connection, job)

    assert latest_run == {
        "completed_at": completed_at,
        "pull_status": "crashed",
        "execution_origin": "legacy_unknown",
        "inserted_count": 11,
        "skipped_count": 22,
        "quarantined_count": 33,
        "superseded_count": 44,
        "error_count": 55,
        "error": "boom",
    }
    query = cursor.execute.call_args.args[0]
    params = cursor.execute.call_args.args[1]
    normalized_query = " ".join(query.split())
    assert (
        "SELECT completed_at, pull_status, execution_origin, inserted_count, skipped_count, quarantined_count, "
        "superseded_count, error_count, error FROM core.refresh_run"
    ) in normalized_query
    assert "job_key = %s" in query
    assert "completed_at IS NOT NULL" in query
    assert "ORDER BY completed_at DESC, created_at DESC, id DESC" in normalized_query
    assert "pull_status = ANY" not in query
    assert params == ("state-co-contributions",)


def test_select_latest_completed_run_returns_none_without_completed_row() -> None:
    job = _job_for_tests(key="state-co-contributions")
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = None

    assert runner.select_latest_completed_run(connection, job) is None


def test_select_latest_completed_run_filters_by_job_key_not_refresh_history_key() -> None:
    job = _job_for_tests(key="state-co-contributions", refresh_history_key="state-co-cadence-history")
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = None

    runner.select_latest_completed_run(connection, job)

    assert cursor.execute.call_args.args[1] == ("state-co-contributions",)


def test_refresh_history_key_cadence_gate_ignores_crashed_runs() -> None:
    job = job_builders.build_refresh_plan(scope="all", job_key_prefixes=("federal-fec-masters",))[0]
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = (None,)

    latest_pull_at = runner._select_latest_pull_at(connection, job)

    assert latest_pull_at is None
    query = cursor.execute.call_args.args[0]
    params = cursor.execute.call_args.args[1]
    assert "pull_status = ANY(%s)" in query
    assert params == ("federal-fec-masters", ["success"])


def test_federal_fec_masters_refresh_history_key_cadence_gate_ignores_degraded_runs() -> None:
    job = job_builders.build_refresh_plan(scope="all", job_key_prefixes=("federal-fec-masters",))[0]
    degraded_completed_at = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)

    class _Cursor:
        def __enter__(self) -> _Cursor:
            return self

        def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
            return None

        def execute(self, query: str, params: tuple[str, list[str]]) -> None:
            self.query = query
            self.params = params

        def fetchone(self) -> tuple[datetime | None]:
            _, accepted_pull_statuses = self.params
            if "degraded" in accepted_pull_statuses:
                return (degraded_completed_at,)
            return (None,)

    class _Connection:
        def __init__(self) -> None:
            self.cursor_instance = _Cursor()

        def cursor(self) -> _Cursor:
            return self.cursor_instance

    connection = _Connection()

    latest_pull_at = runner._select_latest_pull_at(connection, job)  # type: ignore[arg-type]

    assert latest_pull_at is None
    assert "pull_status = ANY(%s)" in connection.cursor_instance.query
    assert connection.cursor_instance.params == ("federal-fec-masters", ["success"])


def test_build_refresh_plan_orders_federal_jobs_by_stage_critical_prerequisites() -> None:
    """Stage 2 prerequisite contract: federal-fec-masters must run before every
    federal job that depends on the FEC master tables, and federal-enrichment
    must run after the upstream federal jobs that produce the people, FEC
    transactions, and Schedule E rows it joins on.

    This test deliberately checks only stage-critical prerequisites — the full
    federal key inventory (and its incidental tuple order) is owned by the
    prefix-filter contract in core/refresh/test_job_builders.py.
    """
    job_keys = [job.key for job in job_builders.build_refresh_plan(scope="all")]
    job_index = {job_key: position for position, job_key in enumerate(job_keys)}

    masters_dependents = (
        "federal-fec-schedule-a",
        "federal-fec-committee-summary",
        "federal-congress-spine",
        "federal-fec-schedule-b",
        "federal-fec-schedule-e",
        "federal-enrichment",
    )
    for dependent_key in masters_dependents:
        assert dependent_key in job_index, (
            f"Stage 2 prerequisite contract requires federal job {dependent_key!r} in the plan"
        )
        assert job_index["federal-fec-masters"] < job_index[dependent_key], (
            f"federal-fec-masters must precede {dependent_key} so master tables exist before dependents run"
        )

    assert job_index["federal-fec-schedule-a"] < job_index["federal-fec-committee-summary"], (
        "federal-fec-schedule-a must precede committee-summary derived aggregate population "
        "so stored aggregates include the newest itemized transactions"
    )

    enrichment_prerequisites = (
        "federal-congress-spine",
        "federal-fec-schedule-b",
        "federal-fec-schedule-e",
    )
    for prerequisite_key in enrichment_prerequisites:
        assert job_index[prerequisite_key] < job_index["federal-enrichment"], (
            f"{prerequisite_key} must precede federal-enrichment so enrichment joins on populated upstream rows"
        )


def test_build_refresh_plan_federal_scope_emits_only_ordered_federal_jobs() -> None:
    jobs = job_builders.build_refresh_plan(scope="federal")
    job_keys = tuple(job.key for job in jobs)

    assert job_keys == _EXPECTED_WEEKLY_FEDERAL_SCOPE_JOB_KEYS
    assert not any(job_key.startswith(("state-", "city-", "civic-", "civics-")) for job_key in job_keys)


def test_build_refresh_plan_includes_fec_and_state_jobs() -> None:
    jobs = job_builders.build_refresh_plan(scope="all")

    jurisdictions = {job.jurisdiction for job in jobs}
    jobs_by_key = {job.key: job for job in jobs}
    assert "federal/fec" in jurisdictions
    assert "state/AL" in jurisdictions
    assert "state/CA" in jurisdictions
    assert "state/CO" in jurisdictions
    assert "state/GA" in jurisdictions
    assert "state/IL" in jurisdictions
    assert "state/IN" in jurisdictions
    assert "state/KY" in jurisdictions
    assert "state/LA" in jurisdictions
    assert "state/MN" in jurisdictions
    assert "state/NE" in jurisdictions
    assert "state/OR" in jurisdictions
    assert "state/PA" in jurisdictions
    assert "state/TX" in jurisdictions
    assert "state/WA" in jurisdictions
    assert "state/WI" in jurisdictions
    assert "state/NJ" in jurisdictions
    assert "state/NC" in jurisdictions
    assert "federal/officeholder/house" in jurisdictions
    assert "federal/officeholder/senate" in jurisdictions

    assert jobs_by_key["state-tx-contributions"].data_source_names == ("TEC Campaign Finance — Contributions",)
    assert jobs_by_key["state-tx-expenditures"].data_source_names == ("TEC Campaign Finance — Expenditures",)
    assert jobs_by_key["state-tx-loans"].data_source_names == ("TEC Campaign Finance — Loans",)

    assert jobs_by_key["state-al-contributions"].data_source_names == ("AL FCPA Campaign Finance — Contributions",)
    assert jobs_by_key["state-al-expenditures"].data_source_names == ("AL FCPA Campaign Finance — Expenditures",)
    assert jobs_by_key["state-il-contributions"].data_source_names == ("IL SBE Campaign Disclosure — Receipts",)
    assert jobs_by_key["state-il-expenditures"].data_source_names == ("IL SBE Campaign Disclosure — Expenditures",)
    assert jobs_by_key["state-pa-contributions"].data_source_names == ("PA DOS Campaign Finance — Contributions",)
    assert jobs_by_key["state-pa-expenditures"].data_source_names == ("PA DOS Campaign Finance — Expenditures",)
    assert jobs_by_key["state-pa-debts"].data_source_names == ("PA DOS Campaign Finance — Debt",)
    assert jobs_by_key["state-pa-receipts"].data_source_names == ("PA DOS Campaign Finance — Receipts",)
    assert "state-pa-filings" not in jobs_by_key
    assert jobs_by_key["state-ne-contributions"].data_source_names == (
        "NE NADC Campaign Finance — Contributions and Loans",
    )
    assert jobs_by_key["state-ne-expenditures"].data_source_names == ("NE NADC Campaign Finance — Expenditures",)
    assert jobs_by_key["state-ne-loans"].data_source_names == ("NE NADC Campaign Finance — Contributions and Loans",)
    assert jobs_by_key["state-in-contributions"].data_source_names == ("IN IED Campaign Finance - Contributions",)
    assert jobs_by_key["state-in-expenditures"].data_source_names == ("IN IED Campaign Finance - Expenditures",)
    # KY contributions use election-date scoping — check one representative job
    assert jobs_by_key["state-ky-contributions-5-19-2026"].data_source_names == (
        "KY KREF Campaign Finance — Contributions",
    )
    assert jobs_by_key["state-ky-expenditures"].data_source_names == ("KY KREF Campaign Finance — Expenditures",)
    assert jobs_by_key["state-la-contributions"].data_source_names == ("LA Ethics Campaign Finance — Contributions",)
    assert jobs_by_key["state-la-expenditures"].data_source_names == ("LA Ethics Campaign Finance — Expenditures",)
    assert jobs_by_key["state-la-loans"].data_source_names == ("LA Ethics Campaign Finance — Loans",)
    assert jobs_by_key["state-ma-contributions"].data_source_names == (
        "MA OCPF Report Items (Contributions + Expenditures)",
    )
    assert jobs_by_key["state-ma-expenditures"].data_source_names == (
        "MA OCPF Report Items (Contributions + Expenditures)",
    )
    assert jobs_by_key["state-nj-contributions"].data_source_names == ("ELEC Reports and Data Search Export API",)
    assert jobs_by_key["state-ny-contributions"].data_source_names == ("NY BoE Contributions",)
    assert jobs_by_key["state-ny-expenditures"].data_source_names == ("NY BoE Expenditures",)
    assert jobs_by_key["state-or-contributions"].data_source_names == ("OR ORESTAR Campaign Finance — Contributions",)
    assert jobs_by_key["state-or-expenditures"].data_source_names == ("OR ORESTAR Campaign Finance — Expenditures",)


def test_build_refresh_plan_uses_config_cadence_values() -> None:
    jobs = job_builders.build_refresh_plan(scope="all")
    cadence_by_source = {source_name: job.cadence for job in jobs for source_name in job.data_source_names}

    assert cadence_by_source["CAL-ACCESS Raw Data Export"] == "daily"
    assert cadence_by_source["TRACER Bulk Download — Contributions"] == "weekly"
    assert cadence_by_source["Georgia Campaign Portal — Contributions Search Export"] == "continuous"
    assert cadence_by_source["IL SBE Campaign Disclosure — Receipts"] == "continuous"
    assert cadence_by_source["IL SBE Campaign Disclosure — Expenditures"] == "continuous"
    assert cadence_by_source["IN IED Campaign Finance - Contributions"] == "weekly"
    assert cadence_by_source["IN IED Campaign Finance - Expenditures"] == "weekly"
    assert cadence_by_source["AL FCPA Campaign Finance — Contributions"] == "daily"
    assert cadence_by_source["AL FCPA Campaign Finance — Expenditures"] == "daily"
    assert cadence_by_source["KY KREF Campaign Finance — Contributions"] == "weekly"
    assert cadence_by_source["KY KREF Campaign Finance — Expenditures"] == "weekly"
    assert cadence_by_source["LA Ethics Campaign Finance — Contributions"] == "daily"
    assert cadence_by_source["LA Ethics Campaign Finance — Expenditures"] == "daily"
    assert cadence_by_source["LA Ethics Campaign Finance — Loans"] == "daily"
    assert cadence_by_source["MA OCPF Report Items (Contributions + Expenditures)"] == "daily"
    assert cadence_by_source["MN CFB Contributions (All)"] == "quarterly"
    assert cadence_by_source["NE NADC Campaign Finance — Contributions and Loans"] == "weekly"
    assert cadence_by_source["NE NADC Campaign Finance — Expenditures"] == "weekly"
    assert cadence_by_source["NY BoE Contributions"] == "daily"
    assert cadence_by_source["NY BoE Expenditures"] == "daily"
    assert cadence_by_source["NY BoE Independent Expenditures"] == "daily"
    assert cadence_by_source["OR ORESTAR Campaign Finance — Contributions"] == "weekly"
    assert cadence_by_source["OR ORESTAR Campaign Finance — Expenditures"] == "weekly"
    assert cadence_by_source["WA PDC Contributions"] == "daily"
    assert cadence_by_source["ELEC Reports and Data Search Export API"] == "quarterly"


def test_build_refresh_plan_includes_nc_ie_with_dedicated_ie_path() -> None:
    ie_document_index_path = Path("/tmp/nc-ie-document-index.csv")

    jobs = job_builders.build_refresh_plan(
        scope="all",
        parameters=runner.RunnerParameters(
            nc_ie_document_index_path=ie_document_index_path,
        ),
    )

    jurisdictions = {job.jurisdiction for job in jobs}
    cadence_by_source = {source_name: job.cadence for job in jobs for source_name in job.data_source_names}

    assert "state/NC" in jurisdictions
    assert cadence_by_source["North Carolina SBoE IE Document Index"] == "weekly"


def test_build_refresh_plan_omits_nc_ie_transactions_without_manual_paths() -> None:
    jobs = job_builders.build_refresh_plan(scope="all")

    jobs_by_key = {job.key: job for job in jobs}
    assert "state-nc-ie-transactions" not in jobs_by_key


def test_build_refresh_plan_includes_nc_transactions_with_committee_docs_path() -> None:
    committee_docs_path = Path("/tmp/nc-committee-docs.csv")

    jobs = job_builders.build_refresh_plan(
        scope="all",
        parameters=runner.RunnerParameters(
            nc_committee_docs_path=committee_docs_path,
            nc_committee_id="STA-C3219N-C-001",
            nc_committee_name="NC REALTORS PAC",
        ),
    )

    jurisdictions = {job.jurisdiction for job in jobs}
    cadence_by_source = {source_name: job.cadence for job in jobs for source_name in job.data_source_names}

    assert "state/NC" in jurisdictions
    assert cadence_by_source["North Carolina SBoE Transaction Search"] == "daily"


def test_build_refresh_plan_rejects_nc_runner_request_without_explicit_committee_scope() -> None:
    committee_docs_path = Path("/tmp/nc-committee-docs.csv")

    with pytest.raises(ValueError, match="requires both nc_committee_id and nc_committee_name"):
        job_builders.build_refresh_plan(
            scope="all",
            parameters=runner.RunnerParameters(nc_committee_docs_path=committee_docs_path),
        )


def test_build_refresh_plan_includes_fl_jobs_in_all_scope() -> None:
    jobs = job_builders.build_refresh_plan(scope="all")

    jurisdictions = {job.jurisdiction for job in jobs}
    jobs_by_key = {job.key: job for job in jobs}

    assert "state/FL" in jurisdictions

    assert jobs_by_key["state-fl-contributions"].data_source_names == ("FL DOS Campaign Finance - Contributions",)
    assert jobs_by_key["state-fl-expenditures"].data_source_names == ("FL DOS Campaign Finance - Expenditures",)
    assert jobs_by_key["state-fl-transfers"].data_source_names == ("FL DOS Campaign Finance - Transfers",)
    assert jobs_by_key["state-fl-other"].data_source_names == ("FL DOS Campaign Finance - Other Disbursements",)

    assert jobs_by_key["state-fl-contributions"].cadence == "daily"
    assert jobs_by_key["state-fl-expenditures"].cadence == "daily"
    assert jobs_by_key["state-fl-transfers"].cadence == "daily"
    assert jobs_by_key["state-fl-other"].cadence == "daily"
    assert {job.key for job in jobs if job.jurisdiction == "state/FL"} == {
        "state-fl-contributions",
        "state-fl-expenditures",
        "state-fl-transfers",
        "state-fl-other",
    }


def test_build_refresh_plan_excludes_fl_officeholder_directory_sources() -> None:
    jobs = job_builders.build_refresh_plan(scope="all")
    fl_source_names = {
        source_name for job in jobs if job.jurisdiction == "state/FL" for source_name in job.data_source_names
    }

    assert "FL Senate Officeholder Directory" not in fl_source_names
    assert "FL House Representatives Directory (Blocked in Datacenter)" not in fl_source_names


def test_build_refresh_plan_priority_scope_excludes_fl() -> None:
    jobs = job_builders.build_refresh_plan(scope="priority")
    jurisdictions = {job.jurisdiction for job in jobs}
    source_names = {source_name for job in jobs for source_name in job.data_source_names}

    assert "state/FL" not in jurisdictions
    for fl_source in (
        "FL DOS Campaign Finance - Contributions",
        "FL DOS Campaign Finance - Expenditures",
        "FL DOS Campaign Finance - Transfers",
        "FL DOS Campaign Finance - Other Disbursements",
    ):
        assert fl_source not in source_names


def test_build_refresh_plan_priority_scope_includes_tx_and_excludes_non_priority_sources() -> None:
    jobs = job_builders.build_refresh_plan(scope="priority")
    source_names = {source_name for job in jobs for source_name in job.data_source_names}
    jurisdictions = {job.jurisdiction for job in jobs}
    cadence_by_source = {source_name: job.cadence for job in jobs for source_name in job.data_source_names}

    assert source_names == {
        "AL FCPA Campaign Finance — Contributions",
        "AL FCPA Campaign Finance — Expenditures",
        "CAL-ACCESS Raw Data Export",
        "KY KREF Campaign Finance — Contributions",
        "KY KREF Campaign Finance — Expenditures",
        "LA Ethics Campaign Finance — Contributions",
        "LA Ethics Campaign Finance — Expenditures",
        "LA Ethics Campaign Finance — Loans",
        "NE NADC Campaign Finance — Contributions and Loans",
        "NE NADC Campaign Finance — Expenditures",
        "OR ORESTAR Campaign Finance — Contributions",
        "OR ORESTAR Campaign Finance — Expenditures",
        "TRACER Bulk Download — Contributions",
        "TRACER Bulk Download — Expenditures",
        "Georgia Campaign Portal — Contributions Search Export",
        "Georgia Campaign Portal — Expenditures Search Export",
        "TEC Campaign Finance — Contributions",
        "TEC Campaign Finance — Expenditures",
        "TEC Campaign Finance — Loans",
        job_builders.FEDERAL_SPINE_DATA_SOURCE_NAME,
        job_builders.FEDERAL_ENRICHMENT_DATA_SOURCE_NAME,
        "ncsbe_candidate_listing_2026",
    }
    assert "federal/congress" in jurisdictions
    assert "state/TX" in jurisdictions
    assert "state/NC" in jurisdictions
    assert set(cadence_by_source.values()) == {"daily", "quarterly", "weekly"}

    for excluded_source in (
        "FEC Schedule A API",
        "MN CFB Contributions (All)",
        "PA DOS Campaign Finance — Contributions",
        "WA PDC Contributions",
        "TRACER Bulk Download — Loans",
    ):
        assert excluded_source not in source_names


def test_build_refresh_plan_priority_scope_includes_federal_congress_spine() -> None:
    jobs = job_builders.build_refresh_plan(scope="priority")
    spine_jobs = [job for job in jobs if job.key == "federal-congress-spine"]

    assert len(spine_jobs) == 1
    spine_job = spine_jobs[0]
    assert spine_job.domain == "campaign_finance"
    assert spine_job.jurisdiction == "federal/congress"
    assert spine_job.cadence == "weekly"
    assert spine_job.data_source_names == (job_builders.FEDERAL_SPINE_DATA_SOURCE_NAME,)


def test_build_refresh_plan_priority_scope_includes_nc_ie_with_dedicated_ie_path() -> None:
    ie_document_index_path = Path("/tmp/nc-ie-document-index.csv")

    jobs = job_builders.build_refresh_plan(
        scope="priority",
        parameters=runner.RunnerParameters(
            nc_ie_document_index_path=ie_document_index_path,
        ),
    )
    source_names = {source_name for job in jobs for source_name in job.data_source_names}
    jurisdictions = {job.jurisdiction for job in jobs}
    cadence_by_source = {source_name: job.cadence for job in jobs for source_name in job.data_source_names}

    assert "North Carolina SBoE IE Document Index" in source_names
    assert "state/NC" in jurisdictions
    assert cadence_by_source["North Carolina SBoE IE Document Index"] == "daily"


def test_build_refresh_plan_can_be_filtered_to_wa_job_prefix() -> None:
    jobs = job_builders.build_refresh_plan(scope="all", job_key_prefixes=("state-wa",))

    assert [job.key for job in jobs] == [
        "state-wa-contributions",
        "state-wa-expenditures",
        "state-wa-independent_expenditures",
        "state-wa-loans",
    ]


def test_build_refresh_plan_can_be_filtered_to_federal_congress_spine_job() -> None:
    jobs = job_builders.build_refresh_plan(scope="all", job_key_prefixes=("federal-congress-spine",))

    assert [job.key for job in jobs] == ["federal-congress-spine"]


def test_build_refresh_plan_job_key_prefix_filter_preserves_matching_fec_and_nc_jobs() -> None:
    committee_docs_path = Path("/tmp/nc-committee-docs.csv")
    ie_document_index_path = Path("/tmp/nc-ie-document-index.csv")

    jobs = job_builders.build_refresh_plan(
        scope="all",
        parameters=runner.RunnerParameters(
            nc_committee_docs_path=committee_docs_path,
            nc_committee_id="STA-C3219N-C-001",
            nc_committee_name="NC REALTORS PAC",
            nc_ie_document_index_path=ie_document_index_path,
        ),
        job_key_prefixes=("federal-fec", "state-nc"),
    )

    assert [job.key for job in jobs] == [
        "federal-fec-masters",
        "federal-fec-schedule-a",
        "federal-fec-committee-summary",
        "federal-fec-races",
        "federal-fec-schedule-b",
        "federal-fec-schedule-e",
        "state-nc-ie-document-index",
        "state-nc-ie-transactions",
        "state-nc-committee-discovery",
        "state-nc-transactions",
    ]


def test_build_refresh_plan_job_key_prefix_filter_rejects_empty_match() -> None:
    with pytest.raises(ValueError, match="No refresh jobs matched job_key_prefixes"):
        job_builders.build_refresh_plan(scope="all", job_key_prefixes=("state-zz",))


def test_should_run_job_honors_daily_cadence_window() -> None:
    now = datetime(2026, 3, 21, 16, 0, tzinfo=timezone.utc)
    job = _job_for_tests(key="co-contributions")

    assert runner.should_run_job(job, last_pull_at=None, now=now) is True
    assert runner.should_run_job(job, last_pull_at=now - timedelta(hours=12), now=now) is False
    assert runner.should_run_job(job, last_pull_at=now - timedelta(days=2), now=now) is True


_PARTIAL_RUN_MANUAL_RECOVERY_AT = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)
_PARTIAL_RUN_STALE_MASTERS_AT = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
_PARTIAL_RUN_SCHEDULED_AT = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)
_FULL_SCOPE_OFFICEHOLDER_MONEY_COVERAGE = 518


def _cleanup_refresh_runner_partial_run_fixture(
    connection: psycopg.Connection,
    *,
    job_keys: list[str],
    started_at: datetime,
) -> None:
    connection.execute(
        "DELETE FROM core.refresh_run WHERE job_key = ANY(%s) AND started_at = %s",
        (job_keys, started_at),
    )


def _successful_single_update_loader_result() -> SimpleNamespace:
    return SimpleNamespace(inserted=1, skipped=0, quarantined=0, superseded=0, errors=0)


def _build_real_plan_with_inert_callables(
    *,
    masters_run_callable: MagicMock,
) -> tuple[list[runner.RefreshJob], dict[str, MagicMock]]:
    jobs = job_builders.build_refresh_plan(scope="federal")
    assert tuple(job.key for job in jobs) == _EXPECTED_WEEKLY_FEDERAL_SCOPE_JOB_KEYS

    callables_by_key: dict[str, MagicMock] = {}
    replaced_jobs: list[runner.RefreshJob] = []
    for job in jobs:
        run_callable = (
            masters_run_callable
            if job.key == "federal-fec-masters"
            else MagicMock(name=job.key, return_value=_successful_loader_result())
        )
        callables_by_key[job.key] = run_callable
        replaced_jobs.append(replace(job, run_callable=run_callable))
    return replaced_jobs, callables_by_key


def _partial_run_last_pull_by_key(
    jobs: list[runner.RefreshJob],
    *,
    now: datetime,
) -> dict[str, datetime]:
    return {
        job.key: now - timedelta(days=8) if job.key == "federal-fec-masters" else now - timedelta(days=1)
        for job in jobs
    }


def _expected_masters_partial_run_eligibility(jobs: list[runner.RefreshJob]) -> dict[str, bool]:
    return {job.key: job.key == "federal-fec-masters" or job.cadence == "continuous" for job in jobs}


def _assert_real_plan_call_counts(
    jobs: list[runner.RefreshJob],
    callables_by_key: dict[str, MagicMock],
) -> None:
    callables_by_key["federal-fec-masters"].assert_called_once_with()
    for job in jobs:
        run_callable = callables_by_key[job.key]
        if job.key == "federal-fec-masters":
            continue
        if job.cadence == "continuous":
            run_callable.assert_called_once_with()
        else:
            run_callable.assert_not_called()


def _assert_masters_partial_run_results(results: list[runner.RefreshRunResult]) -> None:
    assert [(result.key, result.status) for result in results] == [
        ("federal-fec-masters", "success"),
        ("federal-fec-schedule-a", "success"),
        ("federal-fec-committee-summary", "skipped"),
        ("federal-congress-spine", "skipped"),
        ("federal-fec-races", "skipped"),
        ("federal-donor-search-rollup", "skipped"),
        ("federal-fec-schedule-b", "success"),
        ("federal-fec-schedule-e", "success"),
        ("federal-enrichment", "skipped"),
        ("federal-geometry-probe", "skipped"),
        ("federal-fec-masters", "failed"),
    ]
    spine_result = results[3]
    alarm = results[-1]
    assert spine_result.key == "federal-congress-spine"
    assert spine_result.status == "skipped"
    assert alarm.status == "failed"
    assert "federal-fec-masters" in alarm.message
    assert "federal-congress-spine" in alarm.message
    assert int(any(result.status in runner._FAILING_STATUSES for result in results)) == 1


def _federal_masters_and_spine_jobs() -> tuple[runner.RefreshJob, runner.RefreshJob]:
    jobs = job_builders.build_refresh_plan(
        scope="all",
        job_key_prefixes=("federal-fec-masters", "federal-congress-spine"),
    )
    assert tuple(job.key for job in jobs) == ("federal-fec-masters", "federal-congress-spine")
    return jobs[0], jobs[1]


def _weekly_pair_eligibility_by_key(
    last_pull_by_key: dict[str, datetime | None],
    *,
    now: datetime = _PARTIAL_RUN_SCHEDULED_AT,
) -> dict[str, bool]:
    return {
        job.key: runner.should_run_job(job, last_pull_at=last_pull_by_key[job.key], now=now)
        for job in _federal_masters_and_spine_jobs()
    }


def _successful_loader_result() -> SimpleNamespace:
    return SimpleNamespace(inserted=3, skipped=0, quarantined=0, superseded=0, errors=0)


def _run_weekly_pair_main(
    monkeypatch: pytest.MonkeyPatch,
    *,
    last_pull_by_key: dict[str, datetime | None],
) -> tuple[int, list[runner.RefreshRunResult], dict[str, MagicMock]]:
    callables_by_key: dict[str, MagicMock] = {}
    jobs = []
    for job in _federal_masters_and_spine_jobs():
        run_callable = MagicMock(return_value=_successful_loader_result())
        callables_by_key[job.key] = run_callable
        jobs.append(replace(job, run_callable=run_callable))

    streamed_results: list[runner.RefreshRunResult] = []
    original_format_result_line = runner._format_result_line

    class _Connection:
        def commit(self) -> None:
            return None

        def rollback(self) -> None:
            return None

        def close(self) -> None:
            return None

    def _capture_result_line(result: runner.RefreshRunResult) -> str:
        streamed_results.append(result)
        return original_format_result_line(result)

    monkeypatch.setattr(job_builders, "build_refresh_plan", lambda **kwargs: jobs)
    monkeypatch.setattr(runner, "get_connection", lambda **overrides: _Connection())
    monkeypatch.setattr(runner, "_utc_now", lambda: _PARTIAL_RUN_SCHEDULED_AT)
    monkeypatch.setattr(runner, "_select_latest_pull_at", lambda connection, job: last_pull_by_key[job.key])
    monkeypatch.setattr(runner, "_recent_nonempty_activity_counts", lambda *args, **kwargs: [])
    monkeypatch.setattr(runner, "_select_data_source_id", lambda *args, **kwargs: None)
    monkeypatch.setattr(runner, "_record_refresh_run", lambda *args, **kwargs: None)
    # run_job now writes the attempt row twice, and the stub connection has no cursor.
    monkeypatch.setattr(runner, "insert_refresh_run", lambda *args, **kwargs: None)
    monkeypatch.setattr(runner, "update_refresh_run", lambda *args, **kwargs: None)
    monkeypatch.setattr(runner, "_format_result_line", _capture_result_line)

    exit_code = runner.main(
        [
            "--no-lock",
            "--job-key-prefix",
            "federal-fec-masters",
            "--job-key-prefix",
            "federal-congress-spine",
        ]
    )

    return exit_code, streamed_results, callables_by_key


@pytest.mark.integration
def test_masters_with_spine_skipped_preserves_officeholder_money_coverage(
    monkeypatch: pytest.MonkeyPatch,
    committing_db_conn: psycopg.Connection,
) -> None:
    fixed_run_at = datetime(2099, 1, 11, 12, 0, tzinfo=timezone.utc)
    fixture_ids = None
    plan_job_keys = list(_EXPECTED_WEEKLY_FEDERAL_SCOPE_JOB_KEYS)

    try:
        committing_db_conn.rollback()
        cleanup_donor_search_fixture(committing_db_conn)
        _cleanup_refresh_runner_partial_run_fixture(
            committing_db_conn,
            job_keys=plan_job_keys,
            started_at=fixed_run_at,
        )
        committing_db_conn.commit()

        fixture_ids = seed_full_scope_skewed_donor_search_fixture(committing_db_conn)
        officeholder_money_coverage = fetch_full_scope_donor_search_counts(committing_db_conn).linked_people
        assert fixture_ids.counts.linked_people == _FULL_SCOPE_OFFICEHOLDER_MONEY_COVERAGE
        assert officeholder_money_coverage == _FULL_SCOPE_OFFICEHOLDER_MONEY_COVERAGE
        assert officeholder_money_coverage > 0
        committing_db_conn.commit()

        def _run_masters_link_update() -> SimpleNamespace:
            assert fixture_ids is not None
            update_candidate_person_link(
                committing_db_conn,
                fec_candidate_id="S6NC00000",
                person_id=fixture_ids.secondary_recipient.person_id,
            )
            return _successful_single_update_loader_result()

        masters_run_callable = MagicMock(side_effect=_run_masters_link_update)
        jobs, callables_by_key = _build_real_plan_with_inert_callables(
            masters_run_callable=masters_run_callable,
        )
        last_pull_by_key = _partial_run_last_pull_by_key(jobs, now=fixed_run_at)

        assert {
            job.key: runner.should_run_job(job, last_pull_at=last_pull_by_key[job.key], now=fixed_run_at)
            for job in jobs
        } == _expected_masters_partial_run_eligibility(jobs)

        monkeypatch.setattr(runner, "_utc_now", lambda: fixed_run_at)
        monkeypatch.setattr(runner, "_select_latest_pull_at", lambda connection, job: last_pull_by_key[job.key])
        results = runner.run_all_jobs(committing_db_conn, jobs, now=fixed_run_at)

        officeholder_money_coverage = fetch_full_scope_donor_search_counts(committing_db_conn).linked_people
        assert officeholder_money_coverage == _FULL_SCOPE_OFFICEHOLDER_MONEY_COVERAGE
        _assert_masters_partial_run_results(results)
        _assert_real_plan_call_counts(jobs, callables_by_key)
    finally:
        committing_db_conn.rollback()
        cleanup_donor_search_fixture(committing_db_conn)
        _cleanup_refresh_runner_partial_run_fixture(
            committing_db_conn,
            job_keys=plan_job_keys,
            started_at=fixed_run_at,
        )
        committing_db_conn.commit()


def test_main_flags_weekly_federal_partial_run_when_masters_runs_without_congress_spine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    last_pull_by_key = {
        "federal-fec-masters": _PARTIAL_RUN_STALE_MASTERS_AT,
        "federal-congress-spine": _PARTIAL_RUN_MANUAL_RECOVERY_AT,
    }

    assert _weekly_pair_eligibility_by_key(last_pull_by_key) == {
        "federal-fec-masters": True,
        "federal-congress-spine": False,
    }

    exit_code, results, callables_by_key = _run_weekly_pair_main(
        monkeypatch,
        last_pull_by_key=last_pull_by_key,
    )

    assert [(result.key, result.status) for result in results] == [
        ("federal-fec-masters", "success"),
        ("federal-congress-spine", "skipped"),
        ("federal-fec-masters", "failed"),
    ]
    callables_by_key["federal-fec-masters"].assert_called_once_with()
    callables_by_key["federal-congress-spine"].assert_not_called()
    assert exit_code == 1, (
        "runner.main() must fail the federal result family when weekly federal prerequisites split: "
        "federal-fec-masters ran but federal-congress-spine stayed inside the 2026-07-25 recovery freshness window"
    )


def test_weekly_federal_partial_run_alarm_names_jobs_and_cadence_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    last_pull_by_key = {
        "federal-fec-masters": _PARTIAL_RUN_STALE_MASTERS_AT,
        "federal-congress-spine": _PARTIAL_RUN_MANUAL_RECOVERY_AT,
    }

    _, results, _ = _run_weekly_pair_main(
        monkeypatch,
        last_pull_by_key=last_pull_by_key,
    )

    alarm = results[-1]
    assert alarm.status == "failed"
    assert "federal-fec-masters" in alarm.message
    assert "federal-congress-spine" in alarm.message
    assert _PARTIAL_RUN_STALE_MASTERS_AT.isoformat() in alarm.message
    assert _PARTIAL_RUN_MANUAL_RECOVERY_AT.isoformat() in alarm.message
    assert alarm.error == alarm.message


def test_weekly_federal_partial_run_alarm_status_drives_main_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert runner._FAILING_STATUSES == frozenset({"crashed", "degraded", "empty", "failed"})

    jobs = [
        replace(job, run_callable=MagicMock(return_value=_successful_loader_result()))
        for job in _federal_masters_and_spine_jobs()
    ]
    connection = MagicMock()
    record_refresh_run = MagicMock()
    last_pull_by_key = {
        "federal-fec-masters": _PARTIAL_RUN_STALE_MASTERS_AT,
        "federal-congress-spine": _PARTIAL_RUN_MANUAL_RECOVERY_AT,
    }
    monkeypatch.setattr(runner, "_utc_now", lambda: _PARTIAL_RUN_SCHEDULED_AT)
    monkeypatch.setattr(runner, "_record_refresh_run", record_refresh_run)

    alarm = runner._record_repair_pair_alarm(
        connection,
        jobs[0],
        jobs[1],
        last_pull_at_by_key=last_pull_by_key,
    )

    assert alarm.status == "failed"
    assert alarm.status in runner._FAILING_STATUSES
    record_refresh_run.assert_called_once()
    connection.commit.assert_called_once_with()
    connection.rollback.assert_not_called()

    failing_connection = MagicMock()
    monkeypatch.setattr(runner, "_record_refresh_run", MagicMock(side_effect=RuntimeError("ledger write boom")))

    failed_alarm = runner._record_repair_pair_alarm(
        failing_connection,
        jobs[0],
        jobs[1],
        last_pull_at_by_key=last_pull_by_key,
    )

    assert failed_alarm.status == "failed"
    assert failed_alarm.status in runner._FAILING_STATUSES
    assert "alarm ledger recording failed: ledger write boom" in failed_alarm.error
    failing_connection.commit.assert_not_called()
    failing_connection.rollback.assert_called_once_with()


def test_weekly_federal_partial_run_alarm_records_failed_zero_activity_ledger_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    jobs = [
        replace(job, run_callable=MagicMock(return_value=_successful_loader_result()))
        for job in _federal_masters_and_spine_jobs()
    ]
    connection = MagicMock()
    insert_refresh_run = MagicMock()
    last_pull_by_key = {
        "federal-fec-masters": _PARTIAL_RUN_STALE_MASTERS_AT,
        "federal-congress-spine": _PARTIAL_RUN_MANUAL_RECOVERY_AT,
    }
    monkeypatch.setattr(runner, "_utc_now", lambda: _PARTIAL_RUN_SCHEDULED_AT)
    monkeypatch.setattr(runner, "_select_latest_pull_at", lambda connection, job: last_pull_by_key[job.key])
    monkeypatch.setattr(runner, "_recent_nonempty_activity_counts", lambda *args, **kwargs: [])
    monkeypatch.setattr(runner, "_select_data_source_id", lambda *args, **kwargs: None)
    monkeypatch.setattr(runner, "insert_refresh_run", insert_refresh_run)

    results = runner.run_all_jobs(
        connection,
        jobs,
        now=_PARTIAL_RUN_SCHEDULED_AT,
    )

    alarm = results[-1]
    alarm_run = insert_refresh_run.call_args_list[-1].args[1]
    assert alarm.status == "failed"
    assert alarm_run.job_key == "federal-fec-masters"
    assert alarm_run.domain == jobs[0].domain
    assert alarm_run.jurisdiction == jobs[0].jurisdiction
    assert alarm_run.data_source_names == list(jobs[0].data_source_names)
    assert alarm_run.pull_status == "failed"
    assert alarm_run.inserted_count == 0
    assert alarm_run.skipped_count == 0
    assert alarm_run.quarantined_count == 0
    assert alarm_run.superseded_count == 0
    assert alarm_run.error_count == 0
    assert alarm_run.metadata_updates == 0
    assert alarm_run.message == alarm.message
    assert alarm_run.error == alarm.error == alarm.message


@pytest.mark.integration
def test_weekly_federal_partial_run_alarm_persists_to_real_refresh_run_table(
    monkeypatch: pytest.MonkeyPatch,
    db_conn: psycopg.Connection,
) -> None:
    alarm_at = datetime(2099, 1, 10, 12, 0, tzinfo=timezone.utc)
    last_pull_by_key = {
        "federal-fec-masters": datetime(2099, 1, 1, 12, 0, tzinfo=timezone.utc),
        "federal-congress-spine": datetime(2099, 1, 9, 12, 0, tzinfo=timezone.utc),
    }
    jobs = [
        replace(job, run_callable=MagicMock(return_value=_successful_loader_result()))
        for job in _federal_masters_and_spine_jobs()
    ]
    monkeypatch.setattr(runner, "_utc_now", lambda: alarm_at)
    monkeypatch.setattr(runner, "_select_latest_pull_at", lambda connection, job: last_pull_by_key[job.key])
    monkeypatch.setattr(runner, "_recent_nonempty_activity_counts", lambda *args, **kwargs: [])
    monkeypatch.setattr(runner, "_select_data_source_id", lambda *args, **kwargs: None)

    try:
        results = runner.run_all_jobs(db_conn, jobs, now=alarm_at)

        with db_conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT pull_status, inserted_count, skipped_count,
                       quarantined_count, superseded_count, error_count,
                       metadata_updates, message, error
                FROM core.refresh_run
                WHERE job_key = 'federal-fec-masters'
                  AND started_at = %s
                  AND pull_status = 'failed'
                """,
                (alarm_at,),
            )
            alarm_row = cursor.fetchone()

        assert alarm_row == (
            "failed",
            0,
            0,
            0,
            0,
            0,
            0,
            results[-1].message,
            results[-1].message,
        )
    finally:
        db_conn.execute(
            "DELETE FROM core.refresh_run WHERE job_key = ANY(%s) AND started_at = %s",
            (["federal-fec-masters", "federal-congress-spine"], alarm_at),
        )
        db_conn.commit()


def test_main_allows_weekly_federal_pair_when_both_jobs_execute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    last_pull_by_key = {
        "federal-fec-masters": None,
        "federal-congress-spine": None,
    }

    assert _weekly_pair_eligibility_by_key(last_pull_by_key) == {
        "federal-fec-masters": True,
        "federal-congress-spine": True,
    }

    exit_code, results, callables_by_key = _run_weekly_pair_main(
        monkeypatch,
        last_pull_by_key=last_pull_by_key,
    )

    assert [(result.key, result.status) for result in results] == [
        ("federal-fec-masters", "success"),
        ("federal-congress-spine", "success"),
    ]
    callables_by_key["federal-fec-masters"].assert_called_once_with()
    callables_by_key["federal-congress-spine"].assert_called_once_with()
    assert exit_code == 0


def test_main_allows_weekly_federal_pair_when_both_jobs_skip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    last_pull_by_key = {
        "federal-fec-masters": _PARTIAL_RUN_MANUAL_RECOVERY_AT,
        "federal-congress-spine": _PARTIAL_RUN_MANUAL_RECOVERY_AT,
    }

    assert _weekly_pair_eligibility_by_key(last_pull_by_key) == {
        "federal-fec-masters": False,
        "federal-congress-spine": False,
    }

    exit_code, results, callables_by_key = _run_weekly_pair_main(
        monkeypatch,
        last_pull_by_key=last_pull_by_key,
    )

    assert [(result.key, result.status) for result in results] == [
        ("federal-fec-masters", "skipped"),
        ("federal-congress-spine", "skipped"),
    ]
    callables_by_key["federal-fec-masters"].assert_not_called()
    callables_by_key["federal-congress-spine"].assert_not_called()
    assert exit_code == 0


def test_run_job_dry_run_skips_callable_and_metadata_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock()
    run_callable = MagicMock()
    job = _job_for_tests(key="dry-run-job", run_callable=run_callable)
    sync_data_source_metadata = MagicMock()
    insert_refresh_run = MagicMock()

    monkeypatch.setattr(runner, "sync_data_source_metadata", sync_data_source_metadata)
    monkeypatch.setattr(runner, "insert_refresh_run", insert_refresh_run)

    result = runner.run_job(connection, job, dry_run=True)

    assert result.status == "dry_run"
    assert result.metadata_updates == 0
    run_callable.assert_not_called()
    sync_data_source_metadata.assert_not_called()
    # A dry run must leave no attempt row behind, in flight or otherwise.
    insert_refresh_run.assert_not_called()
    connection.commit.assert_not_called()


def test_run_job_syncs_metadata_through_shared_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock()
    run_callable = MagicMock()
    job = _job_for_tests(
        key="metadata-job",
        run_callable=run_callable,
        data_source_names=("TRACER Bulk Download — Contributions",),
    )
    data_source_id = UUID("baf6456e-cf99-47c1-8738-b77f8cfb3f82")
    select_data_source_id = MagicMock(return_value=data_source_id)
    sync_data_source_metadata = MagicMock(return_value=42)

    monkeypatch.setattr(runner, "_select_data_source_id", select_data_source_id)
    monkeypatch.setattr(runner, "sync_data_source_metadata", sync_data_source_metadata)

    result = runner.run_job(connection, job)

    assert result.status == "success"
    assert result.metadata_updates == 1
    run_callable.assert_called_once_with()
    select_data_source_id.assert_called_once_with(
        connection,
        domain="campaign_finance",
        jurisdiction="state/CO",
        name="TRACER Bulk Download — Contributions",
    )
    sync_data_source_metadata.assert_called_once_with(
        connection,
        data_source_id,
        pull_status="success",
        commit=False,
    )


def test_civic_roster_job_cadence_gate_and_metadata_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime(2026, 4, 29, 12, 0, tzinfo=timezone.utc)
    jobs = job_builders.build_refresh_plan(scope="all", job_key_prefixes=("civic-rosters-us-house-nc",))
    roster_job = jobs[0]
    connection = MagicMock()
    run_callable = MagicMock(return_value=SimpleNamespace(inserted=1, skipped=0, quarantined=0, superseded=0, errors=0))
    hydrated_job = runner.RefreshJob(
        key=roster_job.key,
        domain=roster_job.domain,
        jurisdiction=roster_job.jurisdiction,
        cadence=roster_job.cadence,
        data_source_names=roster_job.data_source_names,
        run_callable=run_callable,
    )
    data_source_id = UUID("89ce5ea6-6cff-45f8-8bdb-ac840a4d3b6a")
    sync_data_source_metadata = MagicMock()

    monkeypatch.setattr(runner, "_record_refresh_run", MagicMock())
    monkeypatch.setattr(runner, "_select_data_source_id", MagicMock(return_value=data_source_id))
    monkeypatch.setattr(runner, "sync_data_source_metadata", sync_data_source_metadata)

    skipped_result = runner._run_gated_job(
        connection,
        hydrated_job,
        last_pull_at=now - timedelta(days=1),
        now=now,
    )
    assert skipped_result.status == "skipped"
    run_callable.assert_not_called()
    sync_data_source_metadata.assert_not_called()

    run_result = runner._run_gated_job(
        connection,
        hydrated_job,
        last_pull_at=now - timedelta(days=8),
        now=now,
    )
    assert run_result.status == "success"
    run_callable.assert_called_once_with()
    runner._select_data_source_id.assert_called_with(
        connection,
        domain="civics",
        jurisdiction="federal/officeholder/house",
        name="US House Officeholder Directory (NC)",
    )
    sync_data_source_metadata.assert_called_once_with(
        connection,
        data_source_id,
        pull_status="success",
        commit=False,
    )


def test_run_job_includes_loader_counts_in_success_message(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock()
    run_callable = MagicMock(
        return_value=SimpleNamespace(inserted=12, skipped=3, quarantined=1, superseded=0, errors=0)
    )
    job = _job_for_tests(key="counted-job", run_callable=run_callable)

    monkeypatch.setattr(runner, "_select_data_source_id", MagicMock(return_value=None))
    monkeypatch.setattr(runner, "sync_data_source_metadata", MagicMock())

    result = runner.run_job(connection, job)

    assert result.status == "success"
    assert result.message == "Refresh job succeeded: inserted=12 skipped=3 quarantined=1 superseded=0 errors=0"


class _RefreshRunCallRecorder:
    """Record ledger writes, callable execution, and transaction boundaries in call order.

    The attempt lifecycle is defined by ordering — the start row must be committed
    before the job runs — so counting calls is not enough to prove it.
    """

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.connection = MagicMock()
        self.connection.commit.side_effect = lambda: self.calls.append("commit")
        self.connection.rollback.side_effect = lambda: self.calls.append("rollback")
        self.insert_refresh_run = MagicMock(side_effect=lambda connection, refresh_run: self.calls.append("insert"))
        self.update_refresh_run = MagicMock(side_effect=lambda connection, refresh_run: self.calls.append("update"))

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(runner, "insert_refresh_run", self.insert_refresh_run)
        monkeypatch.setattr(runner, "update_refresh_run", self.update_refresh_run)
        monkeypatch.setattr(
            runner,
            "_select_started_attempt_for_update",
            lambda connection, refresh_run_id: self.started_run,
        )

    def recording_callable(self, *, result: object = None, error: Exception | None = None) -> MagicMock:
        def _run() -> object:
            self.calls.append("run_callable")
            if error is not None:
                raise error
            return result

        return MagicMock(side_effect=_run)

    @property
    def started_run(self) -> RefreshRun:
        return self.insert_refresh_run.call_args.args[1]

    @property
    def finished_run(self) -> RefreshRun:
        return self.update_refresh_run.call_args.args[1]


def test_run_job_commits_running_attempt_row_before_executing_callable(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = _RefreshRunCallRecorder()
    job = _job_for_tests(key="in-flight-job", run_callable=recorder.recording_callable())

    recorder.install(monkeypatch)
    monkeypatch.setattr(runner, "_select_data_source_id", MagicMock(return_value=None))
    monkeypatch.setattr(runner, "sync_data_source_metadata", MagicMock())

    result = runner.run_job(recorder.connection, job)

    assert recorder.calls == ["insert", "commit", "run_callable", "update"]
    started_run = recorder.started_run
    assert started_run.job_key == "in-flight-job"
    assert started_run.pull_status == "running"
    assert started_run.completed_at is None
    assert started_run.message == "Refresh job started"
    assert started_run.error is None
    assert started_run.inserted_count == 0
    assert started_run.skipped_count == 0
    assert started_run.quarantined_count == 0
    assert started_run.superseded_count == 0
    assert started_run.error_count == 0
    assert started_run.metadata_updates == 0
    assert result.status == "success"


def test_run_job_finishes_the_attempt_row_it_started(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = _RefreshRunCallRecorder()
    loader_result = SimpleNamespace(inserted=7, skipped=1, quarantined=0, superseded=0, errors=0)
    job = _job_for_tests(key="finished-job", run_callable=recorder.recording_callable(result=loader_result))

    recorder.install(monkeypatch)
    monkeypatch.setattr(runner, "_select_data_source_id", MagicMock(return_value=None))
    monkeypatch.setattr(runner, "_recent_nonempty_activity_counts", MagicMock(return_value=[]))
    monkeypatch.setattr(runner, "sync_data_source_metadata", MagicMock())

    result = runner.run_job(recorder.connection, job)

    recorder.update_refresh_run.assert_called_once()
    finished_run = recorder.finished_run
    assert finished_run.id == recorder.started_run.id
    assert finished_run.job_key == "finished-job"
    assert finished_run.pull_status == "success"
    assert finished_run.completed_at is not None
    assert finished_run.started_at == recorder.started_run.started_at
    assert finished_run.inserted_count == 7
    assert finished_run.skipped_count == 1
    assert finished_run.message == result.message


def test_run_job_fails_without_executing_callable_when_start_row_cannot_be_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = MagicMock()
    run_callable = MagicMock()
    job = _job_for_tests(key="unstartable-job", run_callable=run_callable)

    monkeypatch.setattr(runner, "insert_refresh_run", MagicMock(side_effect=RuntimeError("start write boom")))
    monkeypatch.setattr(runner, "update_refresh_run", MagicMock())
    monkeypatch.setattr(runner, "_select_data_source_id", MagicMock(return_value=None))
    monkeypatch.setattr(runner, "sync_data_source_metadata", MagicMock())

    result = runner.run_job(connection, job)

    assert result.status == "failed"
    assert result.message == "Refresh-run start recording failed"
    assert result.error == "start write boom"
    assert result.metadata_updates == 0
    # An attempt we could not record must not run, or the ledger under-reports work done.
    run_callable.assert_not_called()
    connection.rollback.assert_called_once_with()
    runner.update_refresh_run.assert_not_called()


@pytest.mark.integration
def test_run_job_leaves_running_row_readable_when_finish_update_fails(
    monkeypatch: pytest.MonkeyPatch,
    db_conn: psycopg.Connection,
) -> None:
    job_key = "finish-update-failure-job"
    started_at = datetime(2099, 2, 1, 12, 0, tzinfo=timezone.utc)
    job = _job_for_tests(key=job_key, run_callable=MagicMock(return_value=_successful_loader_result()))

    monkeypatch.setattr(runner, "_utc_now", lambda: started_at)
    monkeypatch.setattr(runner, "_select_data_source_id", lambda *args, **kwargs: None)
    monkeypatch.setattr(runner, "update_refresh_run", MagicMock(side_effect=RuntimeError("finish write boom")))

    try:
        result = runner.run_job(db_conn, job)

        assert result.status == "failed"
        assert result.message == "Refresh-run recording failed"
        assert result.error == "finish write boom"

        db_conn.rollback()
        with db_conn.cursor() as cursor:
            cursor.execute(
                "SELECT pull_status, completed_at, message FROM core.refresh_run WHERE job_key = %s",
                (job_key,),
            )
            rows = cursor.fetchall()

        # The operator needs the in-flight row to survive for diagnosis; the committed
        # start row is exactly what a later rollback can no longer erase.
        assert rows == [("running", None, "Refresh job started")]
    finally:
        delete_refresh_runs_for_job(db_conn, job_key)


def test_run_job_finishes_attempt_as_failed_after_rolling_back_a_metadata_sync_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _RefreshRunCallRecorder()
    job = _job_for_tests(key="metadata-failure-job", run_callable=recorder.recording_callable())

    recorder.install(monkeypatch)
    monkeypatch.setattr(runner, "_select_data_source_id", MagicMock(return_value=uuid4()))
    monkeypatch.setattr(
        runner,
        "sync_data_source_metadata",
        MagicMock(side_effect=RuntimeError("metadata write boom")),
    )

    result = runner.run_job(recorder.connection, job)

    # The sync failure aborted the runner transaction, so the UPDATE is only legal
    # after the rollback; the trailing commit makes the terminal row durable.
    assert recorder.calls == ["insert", "commit", "run_callable", "rollback", "update", "commit"]
    finished_run = recorder.finished_run
    assert finished_run.id == recorder.started_run.id
    assert finished_run.pull_status == "failed"
    assert finished_run.completed_at is not None
    assert finished_run.message == "Metadata sync failed"
    assert finished_run.error == "metadata write boom"
    assert result.status == "failed"
    assert result.message == "Metadata sync failed"
    assert result.error == "metadata write boom"


def test_run_job_reports_metadata_sync_failure_even_when_finishing_the_attempt_also_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = MagicMock()
    job = _job_for_tests(key="double-failure-job", run_callable=MagicMock())

    insert_refresh_run = MagicMock()
    monkeypatch.setattr(runner, "insert_refresh_run", insert_refresh_run)
    monkeypatch.setattr(runner, "update_refresh_run", MagicMock(side_effect=RuntimeError("finish write boom")))
    monkeypatch.setattr(
        runner,
        "_select_started_attempt_for_update",
        lambda connection, refresh_run_id: insert_refresh_run.call_args.args[1],
    )
    monkeypatch.setattr(runner, "_select_data_source_id", MagicMock(return_value=uuid4()))
    monkeypatch.setattr(
        runner,
        "sync_data_source_metadata",
        MagicMock(side_effect=RuntimeError("metadata write boom")),
    )

    result = runner.run_job(connection, job)

    # The original failure remains first, and exact terminal-finalization failure is explicit.
    assert result.status == "failed"
    assert result.message == "Metadata sync failed"
    assert result.error == "metadata write boom; terminal finalization refused: finish write boom"


@pytest.mark.integration
def test_crashed_attempt_row_is_committed_in_place_over_the_started_row(
    monkeypatch: pytest.MonkeyPatch,
    db_conn: psycopg.Connection,
) -> None:
    job_key = "crashed-attempt-survives-job"
    run_at = datetime(2099, 2, 2, 12, 0, tzinfo=timezone.utc)
    job = _job_for_tests(key=job_key, run_callable=MagicMock(side_effect=RuntimeError("loader boom")))

    monkeypatch.setattr(runner, "_utc_now", lambda: run_at)
    monkeypatch.setattr(runner, "_select_data_source_id", lambda *args, **kwargs: None)

    try:
        results = runner.run_all_jobs(db_conn, [job], force=True)
        assert [result.status for result in results] == ["crashed"]

        # A rollback after the run proves the writes are durable rather than pending:
        # _finalize_job_transaction commits crashed outcomes, and the start row was
        # already committed before the callable ran.
        db_conn.rollback()
        with db_conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT pull_status, started_at, completed_at, error_count, message, error
                FROM core.refresh_run
                WHERE job_key = %s
                """,
                (job_key,),
            )
            rows = cursor.fetchall()

        # Exactly one row: the attempt finished in place instead of inserting a second.
        assert rows == [("crashed", run_at, run_at, 1, "loader boom", "loader boom")]
    finally:
        delete_refresh_runs_for_job(db_conn, job_key)


@pytest.mark.integration
def test_recent_nonempty_activity_counts_ignores_an_in_flight_running_row(
    db_conn: psycopg.Connection,
) -> None:
    job_key = "in-flight-median-job"
    history_at = datetime(2099, 2, 3, 12, 0, tzinfo=timezone.utc)
    lookback_floor = history_at - timedelta(days=runner._DEGRADED_LOOKBACK_DAYS)
    job = _job_for_tests(key=job_key)

    try:
        # Pre-clear as well as clean up: a killed run's leaked rows would otherwise wedge
        # the vacuity guard below permanently red.
        delete_refresh_runs_for_job(db_conn, job_key)
        record_terminal_refresh_run(
            db_conn,
            job,
            pull_status="success",
            completed_at=history_at,
            counts={"inserted": 500, "skipped": 0, "quarantined": 0, "superseded": 0, "errors": 0},
        )
        db_conn.commit()

        counts_without_in_flight_row = runner._recent_nonempty_activity_counts(
            db_conn,
            job,
            completed_after=lookback_floor,
        )

        runner._start_refresh_run(db_conn, job, started_at=history_at + timedelta(days=1))
        # Guards against a vacuous pass: the in-flight row really is in the table.
        assert_single_in_flight_row(db_conn, job_key)

        counts_with_in_flight_row = runner._recent_nonempty_activity_counts(
            db_conn,
            job,
            completed_after=lookback_floor,
        )

        assert counts_without_in_flight_row == [500]
        # A zero-count running row must not drag the degraded-volume median down.
        assert counts_with_in_flight_row == counts_without_in_flight_row
    finally:
        delete_refresh_runs_for_job(db_conn, job_key)


@pytest.mark.integration
def test_refresh_history_cadence_clock_ignores_an_in_flight_running_row(
    db_conn: psycopg.Connection,
) -> None:
    # key == refresh_history_key mirrors the real federal-fec-masters shape
    # (job_builders.py:1005). _build_refresh_run writes every row under job.key, but the
    # refresh_history cadence branch reads WHERE job_key = job.refresh_history_key, so an
    # unequal pair would make the terminal row unreadable and prove exclusion by a job_key
    # mismatch instead of the completed_at/pull_status filter under test.
    job_key = "in-flight-cadence-job"
    job = _job_for_tests(key=job_key, refresh_history_key=job_key)
    terminal_at = datetime(2099, 3, 1, 12, 0, tzinfo=timezone.utc)

    try:
        delete_refresh_runs_for_job(db_conn, job_key)
        record_terminal_refresh_run(
            db_conn,
            job,
            pull_status="success",
            completed_at=terminal_at,
            counts={"inserted": 500, "skipped": 0, "quarantined": 0, "superseded": 0, "errors": 0},
        )
        db_conn.commit()

        cadence_without_in_flight_row = runner.select_latest_pull_at(db_conn, job)

        runner._start_refresh_run(db_conn, job, started_at=terminal_at + timedelta(days=1))
        # Vacuity guard, scoped to the key the cadence branch actually reads: the in-flight
        # row is present under refresh_history_key, so a byte-identical clock proves the
        # completed_at/pull_status filter — not a job_key mismatch.
        assert_single_in_flight_row(db_conn, job.refresh_history_key)

        cadence_with_in_flight_row = runner.select_latest_pull_at(db_conn, job)

        assert cadence_without_in_flight_row == terminal_at
        # The newer running row's started_at must not advance the cadence clock.
        assert cadence_with_in_flight_row == cadence_without_in_flight_row
    finally:
        delete_refresh_runs_for_job(db_conn, job_key)


@pytest.mark.integration
def test_select_latest_completed_run_ignores_an_in_flight_running_row(
    db_conn: psycopg.Connection,
) -> None:
    job_key = "in-flight-latest-completed-job"
    job = _job_for_tests(key=job_key, refresh_history_key=job_key)
    terminal_at = datetime(2099, 3, 2, 12, 0, tzinfo=timezone.utc)

    try:
        delete_refresh_runs_for_job(db_conn, job_key)
        record_terminal_refresh_run(
            db_conn,
            job,
            pull_status="degraded",
            completed_at=terminal_at,
            counts={"inserted": 7, "skipped": 3, "quarantined": 1, "superseded": 2, "errors": 4},
            error="low volume",
        )
        db_conn.commit()

        latest_without_in_flight_row = runner.select_latest_completed_run(db_conn, job)

        runner._start_refresh_run(db_conn, job, started_at=terminal_at + timedelta(days=1))
        assert_single_in_flight_row(db_conn, job_key)

        latest_with_in_flight_row = runner.select_latest_completed_run(db_conn, job)

        assert latest_without_in_flight_row == {
            "completed_at": terminal_at,
            "pull_status": "degraded",
            "execution_origin": "legacy_unknown",
            "inserted_count": 7,
            "skipped_count": 3,
            "quarantined_count": 1,
            "superseded_count": 2,
            "error_count": 4,
            "error": "low volume",
        }
        # The newer running row carries no completed_at, so the terminal attempt still wins
        # and every returned field is unchanged.
        assert latest_with_in_flight_row == latest_without_in_flight_row
    finally:
        delete_refresh_runs_for_job(db_conn, job_key)


@pytest.mark.integration
def test_start_refresh_run_running_row_leaves_data_source_cadence_clock_untouched(
    db_conn: psycopg.Connection,
) -> None:
    # A non-refresh_history job reads its cadence clock from core.data_source.last_pull_at.
    # _start_refresh_run writes only core.refresh_run, so the data_source branch of
    # _select_latest_pull_at must be unmoved by an in-flight attempt. A real data_source
    # row with a known last_pull_at gives the guard teeth: the pre-running-row clock is a
    # concrete timestamp, so a regression that made _start_refresh_run sync data_source
    # metadata would move it and turn the equality red.
    job_key = "in-flight-data-source-cadence-job"
    # A synthetic source name, never a natural key a production loader owns: the pre-clear
    # DELETE and the seeded row below must not be able to touch real provenance data.
    job = _job_for_tests(
        key=job_key,
        refresh_history_key=None,
        data_source_names=("In-flight cadence guard source",),
    )
    assert runner.cadence_last_pull_owner(job) == "data_source"
    seeded_last_pull_at = datetime(2099, 3, 3, 6, 0, tzinfo=timezone.utc)
    data_source = DataSource(
        domain=job.domain,
        jurisdiction=job.jurisdiction,
        name=job.data_source_names[0],
        source_url="https://example.invalid/in-flight-cadence-guard",
        last_pull_at=seeded_last_pull_at,
        last_pull_status="success",
    )

    try:
        delete_refresh_runs_for_job(db_conn, job_key)
        # Clear any row a prior interrupted run of this test leaked, so try_insert seeds ours.
        db_conn.execute(
            "DELETE FROM core.data_source WHERE domain = %s AND jurisdiction = %s AND name = %s",
            (data_source.domain, data_source.jurisdiction, data_source.name),
        )
        seeded_id = db.try_insert_data_source(db_conn, data_source)
        db_conn.commit()
        assert seeded_id == data_source.id

        cadence_without_in_flight_row = runner.select_latest_pull_at(db_conn, job)
        # The clock is a concrete seeded timestamp, not None, so the equality below can fail.
        assert cadence_without_in_flight_row == seeded_last_pull_at

        runner._start_refresh_run(db_conn, job, started_at=datetime(2099, 3, 3, 12, 0, tzinfo=timezone.utc))
        assert_single_in_flight_row(db_conn, job_key)

        cadence_with_in_flight_row = runner.select_latest_pull_at(db_conn, job)

        # _start_refresh_run wrote no data_source row, so the seeded cadence clock is unmoved.
        assert cadence_with_in_flight_row == seeded_last_pull_at
        assert cadence_with_in_flight_row == cadence_without_in_flight_row
    finally:
        delete_refresh_runs_for_job(db_conn, job_key)
        db_conn.execute("DELETE FROM core.data_source WHERE id = %s", (data_source.id,))
        db_conn.commit()


def test_run_job_records_federal_spine_result_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock()
    spine_result = SpineLoadResult()
    spine_result.house.inserted = 435
    spine_result.senate.inserted = 100
    spine_result.delegate.inserted = 6
    spine_result.delegate.skipped = 1
    spine_result.vice_president.errors = 1
    run_callable = MagicMock(return_value=spine_result)
    job = _job_for_tests(key="federal-congress-spine", run_callable=run_callable)
    insert_refresh_run = MagicMock()
    update_refresh_run = MagicMock()

    monkeypatch.setattr(runner, "_select_data_source_id", MagicMock(return_value=None))
    monkeypatch.setattr(runner, "sync_data_source_metadata", MagicMock())
    monkeypatch.setattr(runner, "insert_refresh_run", insert_refresh_run)
    monkeypatch.setattr(runner, "update_refresh_run", update_refresh_run)

    result = runner.run_job(connection, job)

    assert result.status == "degraded"
    assert (
        result.message
        == "Refresh job completed with loader errors: inserted=541 skipped=1 quarantined=0 superseded=0 errors=1"
    )
    refresh_run = update_refresh_run.call_args.args[1]
    assert refresh_run.pull_status == "degraded"
    assert refresh_run.inserted_count == 541
    assert refresh_run.skipped_count == 1
    assert refresh_run.quarantined_count == 0
    assert refresh_run.superseded_count == 0
    assert refresh_run.error_count == 1


def test_run_job_keeps_generic_success_message_when_callable_returns_non_loader_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = MagicMock()
    run_callable = MagicMock(return_value=object())
    job = _job_for_tests(key="generic-job", run_callable=run_callable)

    monkeypatch.setattr(runner, "_select_data_source_id", MagicMock(return_value=None))
    monkeypatch.setattr(runner, "sync_data_source_metadata", MagicMock())

    result = runner.run_job(connection, job)

    assert result.status == "success"
    assert result.message == "Refresh job succeeded"


def test_run_job_maps_ncsbe_refresh_summary_to_loader_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock()
    run_callable = MagicMock(
        return_value=NcsbeResultsLoadSummary(
            source_record_count=3,
            result_row_count=14,
            contest_count=5,
            source_record_ids_by_file={},
        )
    )
    job = _job_for_tests(key="ncsbe-summary-job", run_callable=run_callable)
    insert_refresh_run = MagicMock()
    update_refresh_run = MagicMock()

    monkeypatch.setattr(runner, "_select_data_source_id", MagicMock(return_value=None))
    monkeypatch.setattr(runner, "sync_data_source_metadata", MagicMock())
    monkeypatch.setattr(runner, "insert_refresh_run", insert_refresh_run)
    monkeypatch.setattr(runner, "update_refresh_run", update_refresh_run)

    result = runner.run_job(connection, job)

    assert result.status == "success"
    assert result.message == "Refresh job succeeded: inserted=14 skipped=0 quarantined=0 superseded=0 errors=0"
    refresh_run = update_refresh_run.call_args.args[1]
    assert refresh_run.inserted_count == 14
    assert refresh_run.skipped_count == 0
    assert refresh_run.quarantined_count == 0
    assert refresh_run.superseded_count == 0
    assert refresh_run.error_count == 0


def test_run_job_maps_dictionary_loader_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock()
    run_callable = MagicMock(return_value={"inserted": 4, "skipped": 2, "quarantined": 0, "superseded": 0, "errors": 0})
    job = _job_for_tests(key="mapping-counts-job", run_callable=run_callable)
    insert_refresh_run = MagicMock()
    update_refresh_run = MagicMock()

    monkeypatch.setattr(runner, "_select_data_source_id", MagicMock(return_value=None))
    monkeypatch.setattr(runner, "sync_data_source_metadata", MagicMock())
    monkeypatch.setattr(runner, "insert_refresh_run", insert_refresh_run)
    monkeypatch.setattr(runner, "update_refresh_run", update_refresh_run)

    result = runner.run_job(connection, job)

    assert result.status == "success"
    assert result.message == "Refresh job succeeded: inserted=4 skipped=2 quarantined=0 superseded=0 errors=0"
    refresh_run = update_refresh_run.call_args.args[1]
    assert refresh_run.inserted_count == 4
    assert refresh_run.skipped_count == 2


def test_run_job_aggregates_loader_counts_from_multi_file_result(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock()
    run_callable = MagicMock(
        return_value=[
            SimpleNamespace(inserted=10, skipped=1, quarantined=0, superseded=0, errors=0),
            SimpleNamespace(inserted=20, skipped=2, quarantined=1, superseded=0, errors=0),
            SimpleNamespace(inserted=30, skipped=3, quarantined=0, superseded=1, errors=1),
        ]
    )
    job = _job_for_tests(key="multi-file-job", run_callable=run_callable)
    insert_refresh_run = MagicMock()
    update_refresh_run = MagicMock()

    monkeypatch.setattr(runner, "_select_data_source_id", MagicMock(return_value=None))
    monkeypatch.setattr(runner, "sync_data_source_metadata", MagicMock())
    monkeypatch.setattr(runner, "insert_refresh_run", insert_refresh_run)
    monkeypatch.setattr(runner, "update_refresh_run", update_refresh_run)

    result = runner.run_job(connection, job)

    assert result.status == "degraded"
    assert (
        result.message
        == "Refresh job completed with loader errors: inserted=60 skipped=6 quarantined=1 superseded=1 errors=1"
    )
    refresh_run = update_refresh_run.call_args.args[1]
    assert refresh_run.pull_status == "degraded"
    assert refresh_run.inserted_count == 60
    assert refresh_run.skipped_count == 6
    assert refresh_run.quarantined_count == 1
    assert refresh_run.superseded_count == 1
    assert refresh_run.error_count == 1


def test_run_job_records_empty_pull_status_for_zero_activity_loader_result(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock()
    run_callable = MagicMock(return_value=SimpleNamespace(inserted=0, skipped=0, quarantined=0, superseded=0, errors=0))
    job = _job_for_tests(key="empty-job", run_callable=run_callable)
    insert_refresh_run = MagicMock()
    update_refresh_run = MagicMock()
    sync_data_source_metadata = MagicMock()

    monkeypatch.setattr(runner, "_select_data_source_id", MagicMock(return_value=None))
    monkeypatch.setattr(runner, "sync_data_source_metadata", sync_data_source_metadata)
    monkeypatch.setattr(runner, "insert_refresh_run", insert_refresh_run)
    monkeypatch.setattr(runner, "update_refresh_run", update_refresh_run)

    result = runner.run_job(connection, job)

    assert result.status == "empty"
    assert result.message == "Refresh job completed with no inserted rows"
    assert update_refresh_run.call_args.args[1].pull_status == "empty"
    # Honest reruns must NOT backfill a fake success state into core.data_source.
    sync_data_source_metadata.assert_not_called()


def test_complete_source_marker_cannot_promote_freshness_for_a_foreign_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = MagicMock()
    run_callable = MagicMock(
        return_value=SimpleNamespace(
            inserted=0,
            skipped=0,
            quarantined=0,
            superseded=0,
            errors=0,
            source_complete=True,
            source_row_count=6_358_218,
        )
    )
    job = _job_for_tests(key="state-wa-loans", run_callable=run_callable)
    sync_data_source_metadata = MagicMock()
    monkeypatch.setattr(runner, "insert_refresh_run", MagicMock())
    monkeypatch.setattr(runner, "update_refresh_run", MagicMock())
    monkeypatch.setattr(runner, "sync_data_source_metadata", sync_data_source_metadata)

    result = runner.run_job(connection, job)

    assert result.status == "empty"
    sync_data_source_metadata.assert_not_called()


def test_run_job_records_success_pull_status_for_skipped_only_loader_result(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock()
    run_callable = MagicMock(
        return_value=SimpleNamespace(inserted=0, skipped=37, quarantined=0, superseded=0, errors=0)
    )
    job = _job_for_tests(key="skipped-only-job", run_callable=run_callable)
    insert_refresh_run = MagicMock()
    update_refresh_run = MagicMock()
    sync_data_source_metadata = MagicMock()

    monkeypatch.setattr(runner, "_select_data_source_id", MagicMock(return_value=None))
    monkeypatch.setattr(runner, "_recent_nonempty_activity_counts", MagicMock(return_value=[120, 140, 160]))
    monkeypatch.setattr(runner, "sync_data_source_metadata", sync_data_source_metadata)
    monkeypatch.setattr(runner, "insert_refresh_run", insert_refresh_run)
    monkeypatch.setattr(runner, "update_refresh_run", update_refresh_run)

    result = runner.run_job(connection, job)

    assert result.status == "success"
    assert result.message == "Refresh job succeeded: inserted=0 skipped=37 quarantined=0 superseded=0 errors=0"
    refresh_run = update_refresh_run.call_args.args[1]
    assert refresh_run.pull_status == "success"
    assert refresh_run.inserted_count == 0
    assert refresh_run.skipped_count == 37


def test_recent_nonempty_activity_counts_include_processed_non_insert_rows() -> None:
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = [(40_589,), (21_836,)]
    job = _job_for_tests(key="federal-fec-masters")
    completed_after = datetime(2026, 6, 24, tzinfo=timezone.utc)

    activity_counts = runner._recent_nonempty_activity_counts(
        connection,
        job,
        completed_after=completed_after,
    )

    assert activity_counts == [40_589, 21_836]
    query = " ".join(cursor.execute.call_args.args[0].split())
    assert (
        "SELECT inserted_count + skipped_count + quarantined_count + superseded_count FROM core.refresh_run"
    ) in query
    assert cursor.execute.call_args.args[1] == ("federal-fec-masters", completed_after)


def test_recent_nonempty_activity_counts_uses_job_key_for_historical_volume_fallback() -> None:
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = [(526,)]
    job = _job_for_tests(key="generic-materialization-job")
    completed_after = datetime(2026, 6, 24, tzinfo=timezone.utc)

    activity_counts = runner._recent_nonempty_activity_counts(
        connection,
        job,
        completed_after=completed_after,
    )

    assert activity_counts == [526]
    assert cursor.execute.call_args.args[1] == ("generic-materialization-job", completed_after)


def test_run_job_records_degraded_when_loader_reports_errors_even_with_bulk_activity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = MagicMock()
    run_callable = MagicMock(
        return_value=SimpleNamespace(inserted=175, skipped=40_414, quarantined=0, superseded=0, errors=1)
    )
    job = _job_for_tests(key="federal-fec-masters", run_callable=run_callable)
    insert_refresh_run = MagicMock()
    update_refresh_run = MagicMock()
    sync_data_source_metadata = MagicMock()

    monkeypatch.setattr(runner, "_select_data_source_id", MagicMock(return_value=None))
    monkeypatch.setattr(runner, "_recent_nonempty_activity_counts", MagicMock(return_value=[21_836]))
    monkeypatch.setattr(runner, "sync_data_source_metadata", sync_data_source_metadata)
    monkeypatch.setattr(runner, "insert_refresh_run", insert_refresh_run)
    monkeypatch.setattr(runner, "update_refresh_run", update_refresh_run)

    result = runner.run_job(connection, job)

    assert result.status == "degraded"
    assert result.message == (
        "Refresh job completed with loader errors: inserted=175 skipped=40414 quarantined=0 superseded=0 errors=1"
    )
    sync_data_source_metadata.assert_not_called()
    assert update_refresh_run.call_args.args[1].pull_status == "degraded"


def test_run_job_records_degraded_pull_status_when_activity_is_below_recent_median(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = MagicMock()
    run_callable = MagicMock(
        return_value=SimpleNamespace(inserted=80, skipped=5, quarantined=0, superseded=0, errors=0)
    )
    job = _job_for_tests(key="degraded-job", run_callable=run_callable)
    insert_refresh_run = MagicMock()
    update_refresh_run = MagicMock()
    sync_data_source_metadata = MagicMock()

    monkeypatch.setattr(runner, "_select_data_source_id", MagicMock(return_value=None))
    monkeypatch.setattr(runner, "_recent_nonempty_activity_counts", MagicMock(return_value=[180, 200, 220]))
    monkeypatch.setattr(runner, "sync_data_source_metadata", sync_data_source_metadata)
    monkeypatch.setattr(runner, "insert_refresh_run", insert_refresh_run)
    monkeypatch.setattr(runner, "update_refresh_run", update_refresh_run)

    result = runner.run_job(connection, job)

    assert result.status == "degraded"
    assert result.message == "Refresh job completed below historical volume threshold: activity=85 median=200"
    sync_data_source_metadata.assert_not_called()
    assert update_refresh_run.call_args.args[1].pull_status == "degraded"


def test_derive_pull_status_compares_incremental_enrichment_with_like_for_like_history() -> None:
    """Federal enrichment uses the selected population as its current workload."""
    connection = MagicMock()
    job = _job_for_tests(
        key="federal-enrichment",
        activity_denominator_result_field="selected",
    )
    execution_result = {
        "selected": 540,
        "inserted": 525,
        "skipped": 0,
        "quarantined": 0,
        "superseded": 0,
        "errors": 0,
    }

    status, counts, message = runner._derive_pull_status(
        connection,
        job,
        execution_error=None,
        execution_result=execution_result,
        completed_at=datetime(2026, 7, 25, 3, 21, 16, tzinfo=timezone.utc),
    )

    connection.cursor.assert_not_called()
    assert status == "success"
    assert counts == {
        "inserted": 525,
        "skipped": 0,
        "quarantined": 0,
        "superseded": 0,
        "errors": 0,
    }
    assert message == (
        "Refresh job succeeded: inserted=525 skipped=0 quarantined=0 superseded=0 errors=0 activity=525 denominator=540"
    )


def test_derive_pull_status_degrades_incremental_enrichment_below_selected_denominator() -> None:
    connection = MagicMock()
    job = _job_for_tests(
        key="federal-enrichment",
        activity_denominator_result_field="due",
    )

    status, counts, message = runner._derive_pull_status(
        connection,
        job,
        execution_error=None,
        execution_result={
            "selected": 539,
            "due": 100,
            "completed": 10,
            "processed": 539,
            "inserted": 100,
            "skipped": 0,
            "quarantined": 0,
            "superseded": 0,
            "errors": 0,
        },
        completed_at=datetime(2026, 7, 25, 3, 21, 16, tzinfo=timezone.utc),
    )

    connection.cursor.assert_not_called()
    assert status == "degraded"
    assert counts == {
        "inserted": 100,
        "skipped": 0,
        "quarantined": 0,
        "superseded": 0,
        "errors": 0,
    }
    assert message == "Refresh job completed below configured volume threshold: activity=10 denominator=100"


def test_derive_pull_status_fails_closed_for_invalid_configured_denominator() -> None:
    connection = MagicMock()
    job = _job_for_tests(
        key="federal-enrichment",
        activity_denominator_result_field="due",
    )

    status, counts, message = runner._derive_pull_status(
        connection,
        job,
        execution_error=None,
        execution_result={
            "inserted": 525,
            "skipped": 0,
            "quarantined": 0,
            "superseded": 0,
            "errors": 0,
        },
        completed_at=datetime(2026, 7, 25, 3, 21, 16, tzinfo=timezone.utc),
    )

    connection.cursor.assert_not_called()
    assert status == "degraded"
    assert counts == {
        "inserted": 525,
        "skipped": 0,
        "quarantined": 0,
        "superseded": 0,
        "errors": 0,
    }
    assert message == "Refresh job configured invalid activity denominator: field=due"

    zero_denominator_job = _job_for_tests(
        key="generic-configured-job",
        activity_denominator_result_field="selected",
    )
    status, _, message = runner._derive_pull_status(
        connection,
        zero_denominator_job,
        execution_error=None,
        execution_result={
            "selected": 0,
            "inserted": 0,
            "skipped": 0,
            "quarantined": 0,
            "superseded": 0,
            "errors": 0,
        },
        completed_at=datetime(2026, 7, 25, 3, 21, 16, tzinfo=timezone.utc),
    )

    assert status == "degraded"
    assert message == "Refresh job configured invalid activity denominator: field=selected"


def test_derive_pull_status_fails_closed_for_configured_denominator_without_loader_counts() -> None:
    connection = MagicMock()
    job = _job_for_tests(
        key="federal-enrichment",
        activity_denominator_result_field="due",
    )

    status, counts, message = runner._derive_pull_status(
        connection,
        job,
        execution_error=None,
        execution_result={"selected": 540, "due": 540},
        completed_at=datetime(2026, 7, 25, 3, 21, 16, tzinfo=timezone.utc),
    )

    connection.cursor.assert_not_called()
    assert status == "degraded"
    assert counts == {
        "inserted": 0,
        "skipped": 0,
        "quarantined": 0,
        "superseded": 0,
        "errors": 0,
    }
    assert message == "Refresh job configured activity denominator but loader counts are unavailable: field=due"


def test_derive_pull_status_fails_closed_for_empty_counts_with_invalid_configured_denominator() -> None:
    connection = MagicMock()
    job = _job_for_tests(
        key="federal-enrichment",
        activity_denominator_result_field="due",
    )

    status, counts, message = runner._derive_pull_status(
        connection,
        job,
        execution_error=None,
        execution_result={
            "selected": 539,
            "due": -1,
            "inserted": 0,
            "skipped": 0,
            "quarantined": 0,
            "superseded": 0,
            "errors": 0,
        },
        completed_at=datetime(2026, 7, 25, 3, 21, 16, tzinfo=timezone.utc),
    )

    connection.cursor.assert_not_called()
    assert status == "degraded"
    assert counts == {
        "inserted": 0,
        "skipped": 0,
        "quarantined": 0,
        "superseded": 0,
        "errors": 0,
    }
    assert message == "Refresh job configured invalid activity denominator: field=due"

    status, counts, message = runner._derive_pull_status(
        connection,
        job,
        execution_error=None,
        execution_result={
            "selected": 539,
            "due": 1,
            "completed": 2,
            "processed": 539,
            "inserted": 2,
            "skipped": 0,
            "quarantined": 0,
            "superseded": 0,
            "errors": 0,
        },
        completed_at=datetime(2026, 7, 25, 3, 21, 16, tzinfo=timezone.utc),
    )

    assert status == "degraded"
    assert counts["inserted"] == 2
    assert message == "Refresh job configured inconsistent enrichment progress summary"


def test_derive_pull_status_succeeds_for_zero_due_incremental_enrichment() -> None:
    connection = MagicMock()
    job = _job_for_tests(
        key="federal-enrichment",
        activity_denominator_result_field="due",
    )

    status, counts, message = runner._derive_pull_status(
        connection,
        job,
        execution_error=None,
        execution_result={
            "selected": 539,
            "due": 0,
            "completed": 0,
            "processed": 539,
            "inserted": 0,
            "skipped": 0,
            "quarantined": 0,
            "superseded": 0,
            "errors": 0,
        },
        completed_at=datetime(2026, 7, 25, 3, 21, 16, tzinfo=timezone.utc),
    )

    connection.cursor.assert_not_called()
    assert status == "success"
    assert counts == {
        "inserted": 0,
        "skipped": 0,
        "quarantined": 0,
        "superseded": 0,
        "errors": 0,
    }
    assert (
        message
        == "Refresh job succeeded: inserted=0 skipped=0 quarantined=0 superseded=0 errors=0 activity=0 denominator=0"
    )

    status, _, message = runner._derive_pull_status(
        connection,
        job,
        execution_error=None,
        execution_result={
            "selected": 539,
            "due": 0,
            "processed": 539,
            "inserted": 0,
            "skipped": 0,
            "quarantined": 0,
            "superseded": 0,
            "errors": 0,
        },
        completed_at=datetime(2026, 7, 25, 3, 21, 16, tzinfo=timezone.utc),
    )

    assert status == "degraded"
    assert message == "Refresh job configured invalid enrichment progress summary"


def test_derive_pull_status_degrades_zero_due_enrichment_with_incomplete_roster_loop() -> None:
    connection = MagicMock()
    job = _job_for_tests(
        key="federal-enrichment",
        activity_denominator_result_field="due",
    )

    status, counts, message = runner._derive_pull_status(
        connection,
        job,
        execution_error=None,
        execution_result={
            "selected": 539,
            "due": 0,
            "completed": 0,
            "processed": 0,
            "inserted": 0,
            "skipped": 0,
            "quarantined": 0,
            "superseded": 0,
            "errors": 0,
        },
        completed_at=datetime(2026, 7, 25, 3, 21, 16, tzinfo=timezone.utc),
    )

    connection.cursor.assert_not_called()
    assert status == "degraded"
    assert counts == {
        "inserted": 0,
        "skipped": 0,
        "quarantined": 0,
        "superseded": 0,
        "errors": 0,
    }
    assert message == "Refresh job did not process selected roster: processed=0 selected=539"


def test_derive_pull_status_degrades_zero_due_enrichment_with_empty_roster() -> None:
    connection = MagicMock()
    job = _job_for_tests(
        key="federal-enrichment",
        activity_denominator_result_field="due",
    )

    status, counts, message = runner._derive_pull_status(
        connection,
        job,
        execution_error=None,
        execution_result={
            "selected": 0,
            "due": 0,
            "completed": 0,
            "processed": 0,
            "inserted": 0,
            "skipped": 0,
            "quarantined": 0,
            "superseded": 0,
            "errors": 0,
        },
        completed_at=datetime(2026, 7, 25, 3, 21, 16, tzinfo=timezone.utc),
    )

    connection.cursor.assert_not_called()
    assert status == "degraded"
    assert counts == {
        "inserted": 0,
        "skipped": 0,
        "quarantined": 0,
        "superseded": 0,
        "errors": 0,
    }
    assert message == "Refresh job configured empty selected roster"


def test_run_job_records_crashed_pull_status_on_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock()
    run_callable = MagicMock(side_effect=RuntimeError("boom"))
    job = _job_for_tests(key="crashed-job", run_callable=run_callable)
    insert_refresh_run = MagicMock()
    update_refresh_run = MagicMock()
    sync_data_source_metadata = MagicMock()

    monkeypatch.setattr(runner, "_select_data_source_id", MagicMock(return_value=None))
    monkeypatch.setattr(runner, "sync_data_source_metadata", sync_data_source_metadata)
    monkeypatch.setattr(runner, "insert_refresh_run", insert_refresh_run)
    monkeypatch.setattr(runner, "update_refresh_run", update_refresh_run)

    result = runner.run_job(connection, job)

    assert result.status == "crashed"
    assert result.error == "boom"
    sync_data_source_metadata.assert_not_called()
    assert update_refresh_run.call_args.args[1].pull_status == "crashed"


def test_run_all_jobs_isolates_failures_and_continues(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock()
    first_callable = MagicMock(side_effect=RuntimeError("boom"))
    second_callable = MagicMock()
    first_job = _job_for_tests(key="first", run_callable=first_callable)
    second_job = _job_for_tests(key="second", run_callable=second_callable)

    monkeypatch.setattr(runner, "_select_data_source_id", MagicMock(return_value=None))
    monkeypatch.setattr(runner, "sync_data_source_metadata", MagicMock())

    results = runner.run_all_jobs(connection, [first_job, second_job], dry_run=False, force=True)

    assert [result.status for result in results] == ["crashed", "success"]
    first_callable.assert_called_once_with()
    second_callable.assert_called_once_with()


def test_run_all_jobs_stops_after_failure_when_requested(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock()
    first_job = _job_for_tests(key="first")
    second_job = _job_for_tests(key="second")
    first_result = runner.RefreshRunResult(
        key="first",
        status="degraded",
        metadata_updates=0,
        message="below historical threshold",
    )
    second_result = runner.RefreshRunResult(
        key="second",
        status="success",
        metadata_updates=1,
        message="should not run",
    )
    run_job = MagicMock(side_effect=[first_result, second_result])
    streamed: list[runner.RefreshRunResult] = []

    monkeypatch.setattr(runner, "run_job", run_job)

    results = runner.run_all_jobs(
        connection,
        [first_job, second_job],
        dry_run=False,
        force=True,
        on_result=streamed.append,
        stop_on_failure=True,
    )

    assert results == [first_result]
    assert streamed == [first_result]
    run_job.assert_called_once_with(
        connection,
        first_job,
        dry_run=False,
        execution_origin="legacy_unknown",
        on_heartbeat=None,
        heartbeat_interval_seconds=runner._HEARTBEAT_INTERVAL_SECONDS,
    )
    connection.commit.assert_called_once_with()


def test_run_all_jobs_continues_after_quarantined_activity_when_stop_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = MagicMock()
    quarantined_callable = MagicMock(
        return_value=SimpleNamespace(inserted=0, skipped=0, quarantined=1, superseded=0, errors=0)
    )
    next_callable = MagicMock(
        return_value=SimpleNamespace(inserted=1, skipped=0, quarantined=0, superseded=0, errors=0)
    )
    jobs = [
        _job_for_tests(key="quarantined", run_callable=quarantined_callable),
        _job_for_tests(key="next", run_callable=next_callable),
    ]

    monkeypatch.setattr(runner, "_select_data_source_id", MagicMock(return_value=None))
    monkeypatch.setattr(runner, "_recent_nonempty_activity_counts", MagicMock(return_value=[]))
    monkeypatch.setattr(runner, "sync_data_source_metadata", MagicMock())
    monkeypatch.setattr(runner, "insert_refresh_run", MagicMock())

    results = runner.run_all_jobs(connection, jobs, force=True, stop_on_failure=True)

    assert [result.status for result in results] == ["success", "success"]
    assert results[0].message == "Refresh job succeeded: inserted=0 skipped=0 quarantined=1 superseded=0 errors=0"
    quarantined_callable.assert_called_once_with()
    next_callable.assert_called_once_with()


def test_run_all_jobs_stops_after_loader_errors_when_stop_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock()
    error_callable = MagicMock(
        return_value=SimpleNamespace(inserted=0, skipped=0, quarantined=0, superseded=0, errors=1)
    )
    next_callable = MagicMock(
        return_value=SimpleNamespace(inserted=1, skipped=0, quarantined=0, superseded=0, errors=0)
    )
    jobs = [
        _job_for_tests(key="loader-error", run_callable=error_callable),
        _job_for_tests(key="next", run_callable=next_callable),
    ]

    monkeypatch.setattr(runner, "_select_data_source_id", MagicMock(return_value=None))
    monkeypatch.setattr(runner, "sync_data_source_metadata", MagicMock())
    monkeypatch.setattr(runner, "insert_refresh_run", MagicMock())

    results = runner.run_all_jobs(connection, jobs, force=True, stop_on_failure=True)

    assert [result.status for result in results] == ["degraded"]
    assert results[0].message == (
        "Refresh job completed with loader errors: inserted=0 skipped=0 quarantined=0 superseded=0 errors=1"
    )
    error_callable.assert_called_once_with()
    next_callable.assert_not_called()


def test_run_all_jobs_commits_after_successful_job(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock()
    job = _job_for_tests(key="commit-check")
    result = runner.RefreshRunResult(
        key="commit-check",
        status="success",
        metadata_updates=1,
        message="Refresh job succeeded",
    )
    run_job = MagicMock(return_value=result)
    monkeypatch.setattr(runner, "run_job", run_job)

    results = runner.run_all_jobs(connection, [job], dry_run=False, force=True)

    assert [item.status for item in results] == ["success"]
    connection.commit.assert_called_once_with()
    connection.rollback.assert_not_called()


def test_run_all_jobs_rolls_back_failed_job_result(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock()
    job = _job_for_tests(key="rollback-check")
    result = runner.RefreshRunResult(
        key="rollback-check",
        status="failed",
        metadata_updates=0,
        message="Refresh-run recording failed",
        error="boom",
    )
    run_job = MagicMock(return_value=result)
    monkeypatch.setattr(runner, "run_job", run_job)

    results = runner.run_all_jobs(connection, [job], dry_run=False, force=True)

    assert [item.status for item in results] == ["failed"]
    connection.rollback.assert_called_once_with()
    connection.commit.assert_not_called()


def test_run_all_jobs_isolates_gating_failures_and_continues(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock()
    first_job = _job_for_tests(key="first")
    second_job = _job_for_tests(key="second")
    second_result = runner.RefreshRunResult(
        key="second",
        status="success",
        metadata_updates=1,
        message="Refresh job succeeded",
    )
    select_latest_pull_at = MagicMock(side_effect=[RuntimeError("metadata read failed"), None])
    run_job = MagicMock(return_value=second_result)

    monkeypatch.setattr(runner, "_select_latest_pull_at", select_latest_pull_at)
    monkeypatch.setattr(runner, "run_job", run_job)

    results = runner.run_all_jobs(connection, [first_job, second_job], dry_run=False, force=False)

    assert [result.status for result in results] == ["failed", "success"]
    assert results[0].message == "Refresh orchestration failed"
    assert results[0].error == "metadata read failed"
    run_job.assert_called_once_with(
        connection,
        second_job,
        dry_run=False,
        execution_origin="legacy_unknown",
        on_heartbeat=None,
        heartbeat_interval_seconds=runner._HEARTBEAT_INTERVAL_SECONDS,
    )


def test_run_all_jobs_streams_results_via_on_result_callback(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock()
    job_a = _job_for_tests(key="job-a")
    job_b = _job_for_tests(key="job-b")
    result_a = runner.RefreshRunResult(key="job-a", status="success", metadata_updates=1, message="ok")
    result_b = runner.RefreshRunResult(key="job-b", status="failed", metadata_updates=0, message="err", error="boom")
    run_job = MagicMock(side_effect=[result_a, result_b])
    monkeypatch.setattr(runner, "run_job", run_job)

    streamed: list[runner.RefreshRunResult] = []
    results = runner.run_all_jobs(connection, [job_a, job_b], force=True, on_result=streamed.append)

    assert streamed == results
    assert [r.key for r in streamed] == ["job-a", "job-b"]


def test_run_all_jobs_force_skips_cadence_lookup_and_executes_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock()
    first_job = _job_for_tests(key="first")
    second_job = _job_for_tests(key="second")
    first_result = runner.RefreshRunResult(
        key="first",
        status="success",
        metadata_updates=1,
        message="Refresh job succeeded",
    )
    second_result = runner.RefreshRunResult(
        key="second",
        status="success",
        metadata_updates=1,
        message="Refresh job succeeded",
    )
    select_latest_pull_at = MagicMock(side_effect=RuntimeError("should not be called in force mode"))
    run_job = MagicMock(side_effect=[first_result, second_result])

    monkeypatch.setattr(runner, "_select_latest_pull_at", select_latest_pull_at)
    monkeypatch.setattr(runner, "run_job", run_job)

    results = runner.run_all_jobs(connection, [first_job, second_job], dry_run=False, force=True)

    assert [result.status for result in results] == ["success", "success"]
    select_latest_pull_at.assert_not_called()
    assert run_job.call_count == 2


def test_build_argument_parser_accepts_civic_candidate_listing_flags() -> None:
    parser = runner.build_argument_parser()

    args = parser.parse_args(
        [
            "--dry-run",
            "--job-key-prefix",
            "civic-nc-candidate-listing",
            "--job-key-prefix",
            "state-nc",
            "--year-from",
            "2023",
            "--candidate-listing-path",
            "/tmp/nc-candidate-listing.csv",
        ]
    )

    assert args.job_key_prefixes == ["civic-nc-candidate-listing", "state-nc"]
    assert args.year_from == 2023
    assert args.candidate_listing_path == Path("/tmp/nc-candidate-listing.csv")


def test_build_argument_parser_accepts_federal_scope() -> None:
    parser = runner.build_argument_parser()

    args = parser.parse_args(["--scope", "federal"])

    assert args.scope == "federal"


def test_main_threads_civic_candidate_listing_parameters_to_runner_and_job_builder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def _fake_build_refresh_plan(*, scope: str, parameters: runner.RunnerParameters, job_key_prefixes: tuple[str, ...]):
        captured["scope"] = scope
        captured["parameters"] = parameters
        captured["job_key_prefixes"] = job_key_prefixes
        return []

    monkeypatch.setattr(job_builders, "build_refresh_plan", _fake_build_refresh_plan)
    monkeypatch.setattr(runner, "run_all_jobs", lambda *args, **kwargs: [])

    exit_code = runner.main(
        [
            "--dry-run",
            "--job-key-prefix",
            "civic-nc-candidate-listing",
            "--year-from",
            "2022",
            "--candidate-listing-path",
            "/tmp/candidate_listing_fixture.csv",
        ]
    )

    assert exit_code == 0
    assert captured["scope"] == "all"
    assert captured["job_key_prefixes"] == ("civic-nc-candidate-listing",)
    parameters = captured["parameters"]
    assert isinstance(parameters, runner.RunnerParameters)
    assert parameters.year_from == 2022
    assert parameters.candidate_listing_path == Path("/tmp/candidate_listing_fixture.csv")


def _federal_result(key: str, status: str) -> runner.RefreshRunResult:
    return runner.RefreshRunResult(key=key, status=status, metadata_updates=0, message=f"{status} for {key}")


def test_main_threads_federal_prefix_to_build_refresh_plan_and_exits_zero_on_all_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    all_success_results = [
        _federal_result("federal-fec-schedule-a", "success"),
        _federal_result("federal-fec-masters", "success"),
        _federal_result("federal-congress-spine", "success"),
        _federal_result("federal-fec-schedule-b", "success"),
        _federal_result("federal-fec-schedule-e", "success"),
        _federal_result("federal-enrichment", "success"),
        _federal_result("federal-irs-527", "success"),
    ]

    def _fake_build_refresh_plan(*, scope: str, parameters: runner.RunnerParameters, job_key_prefixes: tuple[str, ...]):
        captured["scope"] = scope
        captured["parameters"] = parameters
        captured["job_key_prefixes"] = job_key_prefixes
        return []

    monkeypatch.setattr(job_builders, "build_refresh_plan", _fake_build_refresh_plan)
    monkeypatch.setattr(runner, "run_all_jobs", lambda *args, **kwargs: all_success_results)

    exit_code = runner.main(["--dry-run", "--force", "--job-key-prefix", "federal-"])

    assert exit_code == 0
    assert captured["job_key_prefixes"] == ("federal-",)
    assert captured["scope"] == "all"


def test_main_threads_federal_scope_to_build_refresh_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def _fake_build_refresh_plan(*, scope: str, parameters: runner.RunnerParameters, job_key_prefixes: tuple[str, ...]):
        captured["scope"] = scope
        captured["parameters"] = parameters
        captured["job_key_prefixes"] = job_key_prefixes
        return []

    monkeypatch.setattr(job_builders, "build_refresh_plan", _fake_build_refresh_plan)
    monkeypatch.setattr(runner, "run_all_jobs", lambda *args, **kwargs: [])

    exit_code = runner.main(["--dry-run", "--scope", "federal"])

    assert exit_code == 0
    assert captured["scope"] == "federal"
    assert captured["job_key_prefixes"] == ()
    assert isinstance(captured["parameters"], runner.RunnerParameters)


def test_main_builds_refresh_plan_before_acquiring_per_job_locks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    events: list[str] = []
    job = _job_for_tests(key="state-wa-contributions")
    primary_base_lock_path = tmp_path / "civibus-refresh-runner.lock"
    expected_key_lock_path = tmp_path / "civibus-refresh-runner-state-wa-contributions.lock"
    acquired_fds: list[int] = []
    release_runner_locks = runner._release_runner_locks

    class FakeConnection:
        def close(self) -> None:
            events.append("close")

    def _fake_build_refresh_plan(
        *,
        scope: str,
        parameters: runner.RunnerParameters,
        job_key_prefixes: tuple[str, ...],
    ) -> list[runner.RefreshJob]:
        events.append("build_refresh_plan")
        assert scope == "all"
        assert job_key_prefixes == ("state-wa-contributions",)
        return [job]

    def _fake_acquire_runner_lock(lock_path: Path, wait_seconds: float = 0.0) -> int:
        events.append(f"acquire:{lock_path.name}")
        assert wait_seconds == 0.0
        assert lock_path == expected_key_lock_path
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
        acquired_fds.append(fd)
        return fd

    def _fake_get_connection(**overrides: object) -> FakeConnection:
        events.append("get_connection")
        return FakeConnection()

    def _fake_acquire_database_runner_locks(
        connection: object,
        jobs: list[runner.RefreshJob],
    ) -> bool:
        events.append("acquire_database_locks")
        assert isinstance(connection, FakeConnection)
        assert jobs == [job]
        return True

    def _fake_run_all_jobs(
        connection: object,
        jobs: list[runner.RefreshJob],
        dry_run: bool,
        force: bool,
        execution_origin: str,
        on_result: object,
        stop_on_failure: bool = False,
        on_heartbeat: object = None,
    ) -> list[runner.RefreshRunResult]:
        events.append("run_all_jobs")
        # main() must hand the heartbeat the same stdout owner the result stream uses.
        assert on_heartbeat is runner._emit_stdout_line
        assert connection is not None
        assert jobs == [job]
        assert dry_run is False
        assert force is False
        assert execution_origin == "legacy_unknown"
        assert stop_on_failure is False
        assert callable(on_result)
        result = runner.RefreshRunResult(
            key=job.key,
            status="success",
            metadata_updates=0,
            message="ok\nline2",
            error="\x1b[31mboom\x1b[0m",
        )
        on_result(result)
        return [result]

    def _fake_release_runner_locks(held: list[int]) -> None:
        events.append("release")
        assert held == acquired_fds
        release_runner_locks(held)

    monkeypatch.setattr(runner, "_RUNNER_LOCK_PATH", primary_base_lock_path)
    monkeypatch.setattr(runner, "_fallback_runner_lock_path", lambda: tmp_path / "fallback.lock")
    monkeypatch.setattr(runner, "_acquire_runner_lock", _fake_acquire_runner_lock)
    monkeypatch.setattr(job_builders, "build_refresh_plan", _fake_build_refresh_plan)
    monkeypatch.setattr(runner, "get_connection", _fake_get_connection)
    monkeypatch.setattr(runner, "_try_acquire_database_runner_locks", _fake_acquire_database_runner_locks)
    monkeypatch.setattr(runner, "run_all_jobs", _fake_run_all_jobs)
    monkeypatch.setattr(runner, "_release_runner_locks", _fake_release_runner_locks)

    try:
        exit_code = runner.main(["--scope", "all", "--job-key-prefix", "state-wa-contributions"])
    finally:
        for fd in acquired_fds:
            try:
                os.close(fd)
            except OSError:
                pass

    assert exit_code == 0
    assert events == [
        "build_refresh_plan",
        "acquire:civibus-refresh-runner-state-wa-contributions.lock",
        "get_connection",
        "acquire_database_locks",
        "run_all_jobs",
        "close",
        "release",
    ]
    captured = capsys.readouterr()
    assert captured.out == (
        "state-wa-contributions: status=success metadata_updates=0 message=ok\\nline2 error=\\x1b[31mboom\\x1b[0m\n"
    )


def test_main_enables_fail_fast_for_federal_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    job = _job_for_tests(key="federal-fec-masters")

    class FakeConnection:
        def close(self) -> None:
            pass

    def _fake_run_all_jobs(*args: object, **kwargs: object) -> list[runner.RefreshRunResult]:
        captured["jobs"] = args[1]
        captured["stop_on_failure"] = kwargs["stop_on_failure"]
        captured["execution_origin"] = kwargs["execution_origin"]
        return [runner.RefreshRunResult(key=job.key, status="success", metadata_updates=0, message="ok")]

    monkeypatch.setattr(job_builders, "build_refresh_plan", lambda **kwargs: [job])
    monkeypatch.setattr(runner, "get_connection", lambda **overrides: FakeConnection())
    monkeypatch.setattr(runner, "run_all_jobs", _fake_run_all_jobs)

    exit_code = runner.main(["--scope", "federal", "--no-lock"])

    assert exit_code == 0
    assert captured["jobs"] == [job]
    assert captured["stop_on_failure"] is True
    assert captured["execution_origin"] == "legacy_unknown"


@pytest.mark.parametrize("failing_status", ["empty", "degraded", "failed", "crashed"])
def test_main_returns_non_zero_when_any_federal_result_is_failing(
    monkeypatch: pytest.MonkeyPatch,
    failing_status: str,
) -> None:
    mixed_results = [
        _federal_result("federal-fec-schedule-a", "success"),
        _federal_result("federal-fec-masters", failing_status),
        _federal_result("federal-congress-spine", "success"),
    ]
    monkeypatch.setattr(
        job_builders,
        "build_refresh_plan",
        lambda **kwargs: [],
    )
    monkeypatch.setattr(runner, "run_all_jobs", lambda *args, **kwargs: mixed_results)

    exit_code = runner.main(["--dry-run", "--force", "--job-key-prefix", "federal-"])

    assert exit_code == 1, (
        f"runner.main() must exit non-zero when any federal result is {failing_status!r} so an honest "
        "rerun cannot silently look successful"
    )


# ---------------------------------------------------------------------------
# In-flight heartbeat emission
# ---------------------------------------------------------------------------

_HEARTBEAT_STARTED_AT = datetime(2099, 3, 1, 9, 0, tzinfo=timezone.utc)


class _FakeHeartbeatClock:
    """A clock that only ever moves when the fake stop event reports a timeout."""

    def __init__(self, started_at: datetime) -> None:
        self._now = started_at

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)


class _FakeHeartbeatStopEvent:
    """Stand-in for ``threading.Event`` that scripts waits instead of sleeping.

    ``wait`` reports a timeout (``False``) once per scripted interval, advancing the
    optional fake clock by the interval, and reports stop (``True``) forever after, so
    the worker thread always terminates without a real sleep.
    """

    def __init__(self, *, timeout_returns: int, clock: _FakeHeartbeatClock | None = None) -> None:
        self._remaining_timeouts = timeout_returns
        self._clock = clock
        self._stopped = threading.Event()
        self.wait_calls = 0
        self.set_calls = 0

    def wait(self, timeout: float) -> bool:
        self.wait_calls += 1
        if self._stopped.is_set() or self._remaining_timeouts <= 0:
            return True
        self._remaining_timeouts -= 1
        if self._clock is not None:
            self._clock.advance(timeout)
        return False

    def set(self) -> None:
        self.set_calls += 1
        self._stopped.set()


def _live_heartbeat_threads() -> list[threading.Thread]:
    return [thread for thread in threading.enumerate() if thread.name.startswith("refresh-heartbeat-")]


def _heartbeat_for_tests(
    *,
    stop_event: _FakeHeartbeatStopEvent,
    clock: _FakeHeartbeatClock,
    emit: Callable[[str], None],
    job_key: str = "state-pa-expenditures",
    refresh_run_id: UUID | None = None,
    interval_seconds: float = 60.0,
    started_at: datetime | None = None,
) -> runner._JobHeartbeat:
    return runner._JobHeartbeat(
        runner._HeartbeatAttempt(
            job_key=job_key,
            refresh_run_id=refresh_run_id if refresh_run_id is not None else UUID(int=7),
            started_at=started_at if started_at is not None else _HEARTBEAT_STARTED_AT,
        ),
        interval_seconds=interval_seconds,
        now_fn=clock.now,
        emit=emit,
        event_factory=lambda: stop_event,
    )


def test_job_heartbeat_emits_one_line_per_elapsed_interval() -> None:
    emitted: list[str] = []
    clock = _FakeHeartbeatClock(_HEARTBEAT_STARTED_AT)
    stop_event = _FakeHeartbeatStopEvent(timeout_returns=3, clock=clock)
    run_id = UUID("11111111-2222-3333-4444-555555555555")

    with _heartbeat_for_tests(
        stop_event=stop_event,
        clock=clock,
        emit=emitted.append,
        refresh_run_id=run_id,
        interval_seconds=60.0,
    ):
        pass

    assert emitted == [
        f"state-pa-expenditures: heartbeat elapsed_s=60 refresh_run_id={run_id} message=Refresh job in flight",
        f"state-pa-expenditures: heartbeat elapsed_s=120 refresh_run_id={run_id} message=Refresh job in flight",
        f"state-pa-expenditures: heartbeat elapsed_s=180 refresh_run_id={run_id} message=Refresh job in flight",
    ]


def test_job_heartbeat_emits_nothing_when_job_finishes_before_first_interval() -> None:
    emitted: list[str] = []
    clock = _FakeHeartbeatClock(_HEARTBEAT_STARTED_AT)
    stop_event = _FakeHeartbeatStopEvent(timeout_returns=0, clock=clock)

    with _heartbeat_for_tests(stop_event=stop_event, clock=clock, emit=emitted.append):
        pass

    assert emitted == []


def test_job_heartbeat_stops_and_joins_its_worker_on_context_exit() -> None:
    emitted: list[str] = []
    clock = _FakeHeartbeatClock(_HEARTBEAT_STARTED_AT)
    stop_event = _FakeHeartbeatStopEvent(timeout_returns=3, clock=clock)

    heartbeat = _heartbeat_for_tests(stop_event=stop_event, clock=clock, emit=emitted.append)
    with heartbeat:
        pass

    assert len(emitted) == 3
    assert stop_event.set_calls == 1
    # The worker is joined, not merely signalled, so nothing can emit after the context exits.
    assert not heartbeat._worker.is_alive()
    assert _live_heartbeat_threads() == []
    assert len(emitted) == 3


def test_job_heartbeat_line_is_distinguishable_from_result_line() -> None:
    emitted: list[str] = []
    clock = _FakeHeartbeatClock(_HEARTBEAT_STARTED_AT)
    stop_event = _FakeHeartbeatStopEvent(timeout_returns=1, clock=clock)

    with _heartbeat_for_tests(stop_event=stop_event, clock=clock, emit=emitted.append, job_key="state-pa"):
        pass

    result_line = runner._format_result_line(
        runner.RefreshRunResult(key="state-pa", status="success", metadata_updates=2, message="ok")
    )
    (heartbeat_line,) = emitted
    assert "heartbeat" in heartbeat_line
    assert "heartbeat" not in result_line
    # Heartbeats carry no verdict, so the result-only fields must never appear on one.
    assert "status=" not in heartbeat_line
    assert "metadata_updates=" not in heartbeat_line


def test_job_heartbeat_elapsed_is_measured_from_the_attempt_row_started_at() -> None:
    """``elapsed_s`` must mean the same thing here as in ``core.refresh_run``.

    The attempt row's ``started_at`` is stamped before the start row is inserted and committed,
    so a heartbeat that timed itself from its own construction would under-report elapsed time by
    however long that commit took.
    """
    emitted: list[str] = []
    started_at = _HEARTBEAT_STARTED_AT
    # The heartbeat is constructed 45s after the attempt row was stamped, mimicking a slow commit.
    clock = _FakeHeartbeatClock(started_at + timedelta(seconds=45))
    stop_event = _FakeHeartbeatStopEvent(timeout_returns=1, clock=clock)

    with _heartbeat_for_tests(
        stop_event=stop_event,
        clock=clock,
        emit=emitted.append,
        interval_seconds=60.0,
        started_at=started_at,
    ):
        pass

    (heartbeat_line,) = emitted
    assert "elapsed_s=105 " in heartbeat_line


def test_job_heartbeat_rejects_a_non_positive_interval_before_starting_a_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _FakeHeartbeatClock(_HEARTBEAT_STARTED_AT)
    stop_event = _FakeHeartbeatStopEvent(timeout_returns=1, clock=clock)

    with pytest.raises(ValueError, match="interval_seconds"):
        _heartbeat_for_tests(stop_event=stop_event, clock=clock, emit=lambda line: None, interval_seconds=0)

    assert _live_heartbeat_threads() == []

    recorder = _RefreshRunCallRecorder()
    run_callable = recorder.recording_callable()
    job = _job_for_tests(key="invalid-heartbeat-job", run_callable=run_callable)
    recorder.install(monkeypatch)

    result = runner.run_job(
        recorder.connection,
        job,
        on_heartbeat=lambda line: None,
        heartbeat_interval_seconds=0,
    )

    assert result.status == "failed"
    assert result.message == "Refresh execution orchestration failed"
    assert result.error == "heartbeat interval_seconds must be positive, got 0"
    run_callable.assert_not_called()
    assert recorder.calls == ["insert", "commit", "rollback", "update", "commit"]
    assert recorder.finished_run.id == recorder.started_run.id
    assert recorder.finished_run.pull_status == "failed"
    assert recorder.finished_run.completed_at is not None


def test_emit_stdout_line_escapes_non_printable_characters(capsys: pytest.CaptureFixture[str]) -> None:
    runner._emit_stdout_line("state-pa: message=we\x07ird")

    assert capsys.readouterr().out == "state-pa: message=we\\x07ird\n"


def test_emit_stdout_line_writes_the_whole_line_in_one_write(monkeypatch: pytest.MonkeyPatch) -> None:
    """A heartbeat worker shares stdout with the job thread's own prints.

    ``print`` writes the text and the newline separately, so a heartbeat landing between the two
    would split a concurrent line. One write per emitted line removes that interleaving.
    """
    writes: list[str] = []
    fake_stdout = SimpleNamespace(write=writes.append, flush=lambda: None)
    monkeypatch.setattr(runner.sys, "stdout", fake_stdout)

    runner._emit_stdout_line("state-pa-expenditures: heartbeat elapsed_s=60")

    assert writes == ["state-pa-expenditures: heartbeat elapsed_s=60\n"]


def _install_fake_heartbeat_event(
    monkeypatch: pytest.MonkeyPatch,
    *,
    timeout_returns: int,
) -> _FakeHeartbeatStopEvent:
    stop_event = _FakeHeartbeatStopEvent(timeout_returns=timeout_returns)
    monkeypatch.setattr(runner, "_new_heartbeat_stop_event", lambda: stop_event)
    return stop_event


def test_run_job_starts_heartbeat_after_start_row_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = _RefreshRunCallRecorder()
    job = _job_for_tests(key="heartbeat-job", run_callable=recorder.recording_callable())
    emitted: list[str] = []

    def _emit(line: str) -> None:
        recorder.calls.append("heartbeat")
        emitted.append(line)

    recorder.install(monkeypatch)
    monkeypatch.setattr(runner, "_select_data_source_id", MagicMock(return_value=None))
    monkeypatch.setattr(runner, "sync_data_source_metadata", MagicMock())
    _install_fake_heartbeat_event(monkeypatch, timeout_returns=1)

    result = runner.run_job(recorder.connection, job, on_heartbeat=_emit, heartbeat_interval_seconds=30.0)

    assert result.status == "success"
    # The heartbeat may only start once the in-flight row is durable, so operators never
    # see liveness for an attempt the ledger has no row for.
    assert recorder.calls[:2] == ["insert", "commit"]
    assert recorder.calls.count("heartbeat") == 1
    assert recorder.calls.index("heartbeat") > recorder.calls.index("commit")
    (heartbeat_line,) = emitted
    assert f"refresh_run_id={recorder.started_run.id}" in heartbeat_line
    assert heartbeat_line.startswith("heartbeat-job: heartbeat ")


def test_run_job_dry_run_emits_no_heartbeat(monkeypatch: pytest.MonkeyPatch) -> None:
    job = _job_for_tests(key="dry-run-job", run_callable=MagicMock())
    emitted: list[str] = []
    factory = MagicMock(side_effect=AssertionError("dry runs must not create a heartbeat worker"))
    monkeypatch.setattr(runner, "_new_heartbeat_stop_event", factory)

    result = runner.run_job(MagicMock(), job, dry_run=True, on_heartbeat=emitted.append)

    assert result.status == "dry_run"
    assert emitted == []
    factory.assert_not_called()


def test_run_job_without_heartbeat_callback_creates_no_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = _RefreshRunCallRecorder()
    job = _job_for_tests(key="silent-job", run_callable=recorder.recording_callable())

    recorder.install(monkeypatch)
    monkeypatch.setattr(runner, "_select_data_source_id", MagicMock(return_value=None))
    monkeypatch.setattr(runner, "sync_data_source_metadata", MagicMock())
    factory = MagicMock(side_effect=AssertionError("no heartbeat callback means no worker thread"))
    monkeypatch.setattr(runner, "_new_heartbeat_stop_event", factory)

    result = runner.run_job(recorder.connection, job)

    assert result.status == "success"
    factory.assert_not_called()
    assert _live_heartbeat_threads() == []


def test_run_job_stops_heartbeat_before_returning(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = _RefreshRunCallRecorder()
    job = _job_for_tests(key="stopped-heartbeat-job", run_callable=recorder.recording_callable())
    emitted: list[str] = []

    recorder.install(monkeypatch)
    monkeypatch.setattr(runner, "_select_data_source_id", MagicMock(return_value=None))
    monkeypatch.setattr(runner, "sync_data_source_metadata", MagicMock())
    stop_event = _install_fake_heartbeat_event(monkeypatch, timeout_returns=2)

    runner.run_job(recorder.connection, job, on_heartbeat=emitted.append)

    assert len(emitted) == 2
    assert stop_event.set_calls == 1
    assert _live_heartbeat_threads() == []


def test_run_job_stops_heartbeat_before_returning_on_the_failed_attempt_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _RefreshRunCallRecorder()
    job = _job_for_tests(key="failed-heartbeat-job", run_callable=recorder.recording_callable())
    emitted: list[str] = []

    recorder.install(monkeypatch)
    monkeypatch.setattr(runner, "_select_data_source_id", MagicMock(return_value=uuid4()))
    monkeypatch.setattr(
        runner,
        "sync_data_source_metadata",
        MagicMock(side_effect=RuntimeError("metadata boom")),
    )
    stop_event = _install_fake_heartbeat_event(monkeypatch, timeout_returns=2)

    result = runner.run_job(recorder.connection, job, on_heartbeat=emitted.append)

    assert result.status == "failed"
    assert result.message == "Metadata sync failed"
    assert len(emitted) == 2
    assert stop_event.set_calls == 1
    assert _live_heartbeat_threads() == []


@pytest.mark.parametrize("controlled_signal", [signal.SIGTERM, signal.SIGINT])
def test_run_job_controlled_signal_rolls_back_and_terminally_fails_exact_started_attempt(
    monkeypatch: pytest.MonkeyPatch,
    controlled_signal: signal.Signals,
) -> None:
    recorder = _RefreshRunCallRecorder()
    previous_handler = signal.getsignal(controlled_signal)

    def _write_then_interrupt() -> object:
        recorder.calls.append("partial_write")
        installed_handler = signal.getsignal(controlled_signal)
        assert callable(installed_handler), "a started attempt must install its controlled-signal handler"
        installed_handler(controlled_signal, None)
        raise AssertionError("the controlled signal handler must interrupt the active write")

    job = _job_for_tests(
        key="state-wa-contributions",
        run_callable=MagicMock(side_effect=_write_then_interrupt),
    )
    recorder.install(monkeypatch)

    result = runner.run_job(recorder.connection, job, execution_origin="operator_attended")

    expected_signal_name = signal.Signals(controlled_signal).name
    assert result.status == "failed"
    assert result.metadata_updates == 0
    assert result.message == f"Refresh attempt interrupted by {expected_signal_name}"
    assert recorder.calls == ["insert", "commit", "partial_write", "rollback", "update", "commit"]
    assert recorder.finished_run.id == recorder.started_run.id
    assert recorder.finished_run.job_key == "state-wa-contributions"
    assert recorder.finished_run.execution_origin == "operator_attended"
    assert recorder.finished_run.pull_status == "failed"
    assert recorder.finished_run.completed_at is not None
    assert recorder.finished_run.metadata_updates == 0
    assert signal.getsignal(controlled_signal) is previous_handler


def test_started_attempt_signal_handler_finalizes_only_once_when_signal_repeats(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _RefreshRunCallRecorder()

    def _repeat_signal() -> object:
        installed_handler = signal.getsignal(signal.SIGTERM)
        assert callable(installed_handler)
        try:
            installed_handler(signal.SIGTERM, None)
        except BaseException:
            installed_handler(signal.SIGTERM, None)
            raise
        raise AssertionError("the first controlled signal must interrupt")

    job = _job_for_tests(key="state-wa-contributions", run_callable=MagicMock(side_effect=_repeat_signal))
    recorder.install(monkeypatch)

    result = runner.run_job(recorder.connection, job, execution_origin="operator_attended")

    assert result.status == "failed"
    assert recorder.calls.count("rollback") == 1
    assert recorder.calls.count("update") == 1
    assert recorder.calls.count("commit") == 2


def test_controlled_signal_during_metadata_write_rolls_back_without_freshness_promotion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _RefreshRunCallRecorder()
    job = _job_for_tests(
        key="state-wa-contributions",
        run_callable=recorder.recording_callable(result=_successful_loader_result()),
    )
    recorder.install(monkeypatch)
    monkeypatch.setattr(runner, "_select_data_source_id", MagicMock(return_value=UUID(int=38)))

    def _interrupt_metadata(*_args: object, **_kwargs: object) -> None:
        recorder.calls.append("metadata_partial_write")
        installed_handler = signal.getsignal(signal.SIGTERM)
        assert callable(installed_handler)
        installed_handler(signal.SIGTERM, None)

    monkeypatch.setattr(runner, "sync_data_source_metadata", MagicMock(side_effect=_interrupt_metadata))

    result = runner.run_job(recorder.connection, job, execution_origin="operator_attended")

    assert result.status == "failed"
    assert result.metadata_updates == 0
    assert recorder.calls == [
        "insert",
        "commit",
        "run_callable",
        "metadata_partial_write",
        "rollback",
        "update",
        "commit",
    ]
    assert recorder.finished_run.pull_status == "failed"
    assert recorder.finished_run.metadata_updates == 0


@pytest.mark.parametrize(
    ("override", "expected_error"),
    [
        ({"job_key": "state-wa-loans"}, "job identity"),
        ({"execution_origin": "scheduled"}, "execution origin"),
        ({"pull_status": "success", "completed_at": _HEARTBEAT_STARTED_AT}, "already terminal"),
    ],
)
def test_interrupted_attempt_ownership_refuses_foreign_or_terminal_rows(
    override: dict[str, object],
    expected_error: str,
) -> None:
    job = _job_for_tests(key="state-wa-contributions")
    started_at = _HEARTBEAT_STARTED_AT
    stored = RefreshRun(
        id=UUID(int=37),
        job_key=job.key,
        domain=job.domain,
        jurisdiction=job.jurisdiction,
        data_source_names=list(job.data_source_names),
        execution_origin="operator_attended",
        pull_status="running",
        started_at=started_at,
        completed_at=None,
        message="Refresh job started",
    ).model_copy(update=override)

    with pytest.raises(RuntimeError, match=expected_error):
        runner._require_exact_started_attempt(
            stored,
            refresh_run_id=UUID(int=37),
            job=job,
            started_at=started_at,
            execution_origin="operator_attended",
        )


@pytest.mark.integration
def test_controlled_signal_during_real_postgres_write_rolls_back_and_closes_exact_attempt(
    committing_db_conn: psycopg.Connection,
) -> None:
    db_conn = committing_db_conn
    job_key = "r36-signal-active-write-proof"
    delete_refresh_runs_for_job(db_conn, job_key)
    db_conn.execute("CREATE TABLE IF NOT EXISTS core.r36_signal_probe (value INTEGER NOT NULL)")
    db_conn.execute("TRUNCATE core.r36_signal_probe")
    db_conn.commit()
    write_started = threading.Event()
    signal_sent = threading.Event()

    def _send_signal_after_write() -> None:
        assert write_started.wait(timeout=5)
        os.kill(os.getpid(), signal.SIGTERM)
        signal_sent.set()

    sender = threading.Thread(target=_send_signal_after_write, name="r36-signal-sender")

    def _write_then_signal() -> None:
        db_conn.execute("INSERT INTO core.r36_signal_probe (value) VALUES (36)")
        write_started.set()
        installed_handler = signal.getsignal(signal.SIGTERM)
        assert callable(installed_handler)
        assert threading.current_thread() is threading.main_thread()
        assert installed_handler.__module__ == runner.__name__
        threading.Event().wait(timeout=5)
        raise AssertionError("SIGTERM must interrupt the active PostgreSQL write")

    job = _job_for_tests(key=job_key, run_callable=MagicMock(side_effect=_write_then_signal))
    try:
        sender.start()
        result = runner.run_job(db_conn, job, execution_origin="operator_attended")

        assert result.status == "failed"
        assert result.metadata_updates == 0
        assert result.message == "Refresh attempt interrupted by SIGTERM"
        assert result.error == "controlled SIGTERM interrupted the active refresh attempt"
        assert signal_sent.wait(timeout=1)
        assert db_conn.execute("SELECT COUNT(*) FROM core.r36_signal_probe").fetchone() == (0,)
        terminal_row = db_conn.execute(
            """
            SELECT pull_status, completed_at IS NOT NULL, metadata_updates, execution_origin
            FROM core.refresh_run
            WHERE job_key = %s
            """,
            (job_key,),
        ).fetchone()
        assert terminal_row == ("failed", True, 0, "operator_attended")
    finally:
        sender.join(timeout=1)
        assert not sender.is_alive()
        db_conn.rollback()
        delete_refresh_runs_for_job(db_conn, job_key)
        db_conn.execute("DROP TABLE IF EXISTS core.r36_signal_probe")
        db_conn.commit()


def test_main_heartbeat_lines_do_not_change_exit_code_or_result_stream(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    job = _job_for_tests(
        key="state-pa-expenditures",
        run_callable=MagicMock(return_value=_successful_loader_result()),
    )
    streamed_results: list[runner.RefreshRunResult] = []
    original_format_result_line = runner._format_result_line

    def _capture_result_line(result: runner.RefreshRunResult) -> str:
        streamed_results.append(result)
        return original_format_result_line(result)

    monkeypatch.setattr(job_builders, "build_refresh_plan", lambda **kwargs: [job])
    monkeypatch.setattr(runner, "get_connection", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(runner, "_select_latest_pull_at", lambda connection, job: None)
    monkeypatch.setattr(runner, "_recent_nonempty_activity_counts", lambda *args, **kwargs: [])
    monkeypatch.setattr(runner, "_select_data_source_id", lambda *args, **kwargs: None)
    monkeypatch.setattr(runner, "sync_data_source_metadata", MagicMock(return_value=1))
    monkeypatch.setattr(runner, "insert_refresh_run", lambda *args, **kwargs: None)
    monkeypatch.setattr(runner, "update_refresh_run", lambda *args, **kwargs: None)
    monkeypatch.setattr(runner, "_format_result_line", _capture_result_line)
    _install_fake_heartbeat_event(monkeypatch, timeout_returns=2)

    exit_code = runner.main(["--no-lock", "--force"])

    stdout_lines = capsys.readouterr().out.splitlines()
    heartbeat_lines = [line for line in stdout_lines if " heartbeat " in line]
    result_lines = [line for line in stdout_lines if " status=" in line]

    assert exit_code == 0
    assert len(heartbeat_lines) == 2
    assert len(result_lines) == 1
    # Heartbeats are operator aid printed while the job is in flight; the single terminal
    # result line still closes the job's stdout story.
    assert stdout_lines == heartbeat_lines + result_lines
    assert [(result.key, result.status) for result in streamed_results] == [("state-pa-expenditures", "success")]


# ---------------------------------------------------------------------------
# Per-job connection identity
# ---------------------------------------------------------------------------


def _ambient_application_name() -> str | None:
    """Read the application name a connection opened right now would carry."""
    # build_connection_parameters() is typed for every override value (str | int);
    # application_name is always textual, so narrow it here rather than at each caller.
    value = db.build_connection_parameters().get("application_name")
    return None if value is None else str(value)


def _identity_observing_job(
    key: str,
    observed: list[str | None],
    *,
    error: Exception | None = None,
) -> runner.RefreshJob:
    """Build a job whose callable records the ambient identity it runs under."""

    def _run() -> object:
        observed.append(_ambient_application_name())
        if error is not None:
            raise error
        return None

    return _job_for_tests(key=key, run_callable=MagicMock(side_effect=_run))


def test_execute_job_scopes_the_connection_identity_to_the_job_key() -> None:
    observed: list[str | None] = []
    job = _identity_observing_job("state-pa-expenditures", observed)

    outcome = runner._execute_job(MagicMock(), job)

    assert observed == ["refresh:state-pa-expenditures"]
    assert outcome.error is None
    # The scope is execution-local: nothing outside the callable inherits the job identity.
    assert "application_name" not in db.build_connection_parameters()


def test_execute_job_gives_each_sequential_job_its_own_connection_identity() -> None:
    observed: list[str | None] = []
    connection = MagicMock()

    runner._execute_job(connection, _identity_observing_job("state-co-contributions", observed))
    runner._execute_job(connection, _identity_observing_job("federal-fec-masters", observed))

    assert observed == ["refresh:state-co-contributions", "refresh:federal-fec-masters"]
    assert "application_name" not in db.build_connection_parameters()


def test_execute_job_restores_the_ambient_identity_when_the_callable_raises() -> None:
    observed: list[str | None] = []
    job = _identity_observing_job("state-ca-contributions", observed, error=RuntimeError("boom"))

    with db.connection_identity("refresh:enclosing-owner"):
        outcome = runner._execute_job(MagicMock(), job)
        # A crashed job must not strand its own identity on the enclosing scope.
        assert _ambient_application_name() == "refresh:enclosing-owner"

    assert observed == ["refresh:state-ca-contributions"]
    assert outcome.pull_status == "crashed"
    assert str(outcome.error) == "boom"
    assert "application_name" not in db.build_connection_parameters()


@pytest.mark.parametrize(
    "over_limit_key",
    [
        "state-" + "a" * 60,
        "state-" + "\u00e9" * 40,
    ],
    ids=["ascii", "multibyte"],
)
def test_execute_job_bounds_an_over_limit_job_key_instead_of_crashing(over_limit_key: str) -> None:
    # A data-driven source id could push `refresh:<key>` past PostgreSQL's 63-byte
    # application_name ceiling, including across a multibyte UTF-8 boundary. That
    # must not turn a healthy job into a `crashed` ledger row for a naming reason.
    observed: list[str | None] = []
    job = _identity_observing_job(over_limit_key, observed)

    outcome = runner._execute_job(MagicMock(), job)

    assert outcome.error is None
    assert outcome.pull_status != "crashed"
    (identity,) = observed
    assert identity is not None
    assert identity.startswith("refresh:")
    assert len(identity.encode("utf-8")) <= db.APPLICATION_NAME_LIMIT_BYTES


def test_scoped_connection_identity_stays_distinct_for_distinct_over_limit_keys() -> None:
    # Two keys that truncate to the same prefix must still resolve to different
    # identities so `pg_stat_activity` can tell their sessions apart.
    shared_prefix = "civics-roster-" + "a" * 50
    first = runner._scoped_connection_identity(shared_prefix + "-one")
    second = runner._scoped_connection_identity(shared_prefix + "-two")

    assert first != second
    assert len(first.encode("utf-8")) <= db.APPLICATION_NAME_LIMIT_BYTES
    assert len(second.encode("utf-8")) <= db.APPLICATION_NAME_LIMIT_BYTES


def test_scoped_connection_identity_leaves_within_limit_keys_verbatim() -> None:
    assert runner._scoped_connection_identity("state-pa-expenditures") == "refresh:state-pa-expenditures"


def test_main_opens_the_orchestration_connection_with_the_runner_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = _job_for_tests(key="federal-fec-masters")
    open_overrides: list[dict[str, object]] = []

    class FakeConnection:
        def close(self) -> None:
            pass

    def _fake_get_connection(**overrides: object) -> FakeConnection:
        open_overrides.append(dict(overrides))
        return FakeConnection()

    monkeypatch.setattr(job_builders, "build_refresh_plan", lambda **kwargs: [job])
    monkeypatch.setattr(runner, "get_connection", _fake_get_connection)
    monkeypatch.setattr(
        runner,
        "run_all_jobs",
        lambda *args, **kwargs: [
            runner.RefreshRunResult(key=job.key, status="success", metadata_updates=0, message="ok")
        ],
    )

    exit_code = runner.main(["--scope", "federal", "--no-lock"])

    assert exit_code == 0
    # The shared orchestration connection is one long-lived session; it carries the runner's
    # own identity rather than any job's.
    assert open_overrides == [{"application_name": "refresh:runner"}]


def test_heartbeat_worker_never_opens_a_database_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    """The heartbeat worker stays DB-free, so no connection is opened off the job thread.

    The job's own callable opens one, which is what makes this guard able to fail: the spy
    proves it records opens and which thread made them.
    """
    recorder = _RefreshRunCallRecorder()
    opens: list[tuple[str, str | None]] = []
    emitted: list[str] = []

    def _spy_get_connection(**overrides: object) -> MagicMock:
        opens.append((threading.current_thread().name, _ambient_application_name()))
        return MagicMock()

    def _run() -> object:
        recorder.calls.append("run_callable")
        db.get_connection()
        return None

    job = _job_for_tests(key="heartbeat-db-free-job", run_callable=MagicMock(side_effect=_run))
    recorder.install(monkeypatch)
    monkeypatch.setattr(runner, "get_connection", _spy_get_connection)
    monkeypatch.setattr(db, "get_connection", _spy_get_connection)
    monkeypatch.setattr(runner, "_select_data_source_id", MagicMock(return_value=None))
    monkeypatch.setattr(runner, "sync_data_source_metadata", MagicMock())
    _install_fake_heartbeat_event(monkeypatch, timeout_returns=1)

    result = runner.run_job(recorder.connection, job, on_heartbeat=emitted.append, heartbeat_interval_seconds=30.0)

    assert result.status == "success"
    assert len(emitted) == 1
    assert opens == [(threading.current_thread().name, "refresh:heartbeat-db-free-job")]
    assert not any(thread_name.startswith("refresh-heartbeat-") for thread_name, _ in opens)
