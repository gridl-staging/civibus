from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import psycopg
import pytest
from jsonschema.validators import validator_for

from core.refresh import gate_l5, runner
from test_support.refresh_run_fixtures import (
    assert_single_in_flight_row,
    delete_refresh_runs_completed_on,
    delete_refresh_runs_for_job,
    record_terminal_refresh_run,
    refresh_job_for_tests,
)


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_build_evidence_marks_fail_when_any_non_success_runs_exist(tmp_path: Path) -> None:
    evidence_path = gate_l5.write_l5_evidence(
        counts={"crashed": 1, "empty": 2, "degraded": 0, "failed": 0, "success": 4},
        total_runs=7,
        repo_sha="57f90d75",
        produced_at=datetime(2026, 4, 24, 18, 0, tzinfo=timezone.utc),
        evidence_root=tmp_path,
        evidence_date=date(2026, 4, 24),
    )

    payload = _read_json(evidence_path)

    assert evidence_path == tmp_path / "global" / "2026-04-24.json"
    assert payload["status"] == "fail"
    assert payload["scope"] == "global"
    assert payload["total_runs"] == 7
    assert payload["status_counts"] == {"crashed": 1, "empty": 2, "degraded": 0, "failed": 0, "success": 4}


def test_failed_refresh_run_is_counted_and_fails_evidence(tmp_path: Path) -> None:
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = [("failed", 1), ("success", 1)]

    counts, total_runs = gate_l5.summarize_refresh_runs(connection, evidence_date=date(2026, 8, 27))
    evidence_path = gate_l5.write_l5_evidence(
        counts=counts,
        total_runs=total_runs,
        repo_sha="ede0bf0f",
        produced_at=datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc),
        evidence_root=tmp_path,
        evidence_date=date(2026, 8, 27),
    )
    payload = _read_json(evidence_path)

    assert counts == {"crashed": 0, "empty": 0, "degraded": 0, "failed": 1, "success": 1}
    assert total_runs == 2
    assert payload["status"] == "fail"
    assert payload["status_counts"] == counts

    schema = _read_json(Path(__file__).resolve().parents[2] / "evidence_schemas" / "L5.json")
    validator_for(schema)(schema).validate(payload)


def test_build_evidence_marks_pass_when_all_runs_are_success(tmp_path: Path) -> None:
    evidence_path = gate_l5.write_l5_evidence(
        counts={"crashed": 0, "empty": 0, "degraded": 0, "failed": 0, "success": 5},
        total_runs=5,
        repo_sha="57f90d75",
        produced_at=datetime(2026, 4, 24, 18, 0, tzinfo=timezone.utc),
        evidence_root=tmp_path,
        evidence_date=date(2026, 4, 24),
    )

    payload = _read_json(evidence_path)

    assert payload["status"] == "pass"
    assert payload["gate_command"] == "make gate-L5"


@pytest.mark.integration
def test_summarize_refresh_runs_excludes_an_in_flight_running_row(
    db_conn: psycopg.Connection,
) -> None:
    # A running row has no completed_at, so the window's completed_at >=/< predicate must
    # drop it: an in-flight job can never change L5 counts, verdict, or status-key set.
    job_key = "l5-in-flight-job"
    job = refresh_job_for_tests(job_key)
    evidence_date = date(2099, 4, 1)
    window_at = datetime(2099, 4, 1, 12, 0, tzinfo=timezone.utc)

    try:
        # summarize_refresh_runs has no job_key filter, so it reads global window state.
        # Own the sentinel window outright before seeding, and clear this job's own rows
        # (the running row has no completed_at, so the window clear cannot reach it) —
        # otherwise a killed run's leaked rows wedge the exact-count assertion and the
        # vacuity guard below permanently red.
        delete_refresh_runs_completed_on(db_conn, evidence_date)
        delete_refresh_runs_for_job(db_conn, job_key)
        record_terminal_refresh_run(db_conn, job, pull_status="success", completed_at=window_at)
        record_terminal_refresh_run(db_conn, job, pull_status="success", completed_at=window_at + timedelta(hours=1))
        record_terminal_refresh_run(db_conn, job, pull_status="crashed", completed_at=window_at + timedelta(hours=2))
        db_conn.commit()

        counts_without_in_flight, total_without_in_flight = gate_l5.summarize_refresh_runs(
            db_conn, evidence_date=evidence_date
        )

        # started_at inside the window but completed_at IS NULL — the schema invariant
        # forbids setting completed_at on a running row, and the window filters on it.
        runner._start_refresh_run(db_conn, job, started_at=window_at + timedelta(hours=3))
        # Vacuity guard: the running row really is committed, so before/after equality
        # cannot pass on a missing insert.
        assert_single_in_flight_row(db_conn, job_key)

        counts_with_in_flight, total_with_in_flight = gate_l5.summarize_refresh_runs(
            db_conn, evidence_date=evidence_date
        )

        assert counts_without_in_flight == {
            "crashed": 1,
            "empty": 0,
            "degraded": 0,
            "failed": 0,
            "success": 2,
        }
        assert total_without_in_flight == 3
        # The running row is excluded: counts, total, key-set, and verdict are all unmoved.
        assert counts_with_in_flight == counts_without_in_flight
        assert total_with_in_flight == total_without_in_flight
        assert set(counts_with_in_flight) == set(gate_l5._STATUS_KEYS)
        assert "running" not in counts_with_in_flight
        verdict_before = gate_l5._evidence_status(counts=counts_without_in_flight, total_runs=total_without_in_flight)
        verdict_after = gate_l5._evidence_status(counts=counts_with_in_flight, total_runs=total_with_in_flight)
        assert verdict_before == verdict_after == "fail"
    finally:
        delete_refresh_runs_for_job(db_conn, job_key)
