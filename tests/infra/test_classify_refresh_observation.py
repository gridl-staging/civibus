from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from infra.scripts import classify_refresh_observation as classifier
from infra.scripts.classify_refresh_observation import (
    FAILED_EXIT_CODE,
    NO_OP_EXIT_CODE,
    OBSERVED_SOURCE_JOB_KEYS,
    PARTIAL_EXIT_CODE,
    ObservationError,
    classify_refresh_observation,
    parse_machine_run,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
CLASSIFIER_PATH = REPO_ROOT / "infra/scripts/classify_refresh_observation.py"
FIXTURE_DIR = Path(__file__).with_name("fixtures")
KNOWN_MACHINE_STATUS = FIXTURE_DIR / "refresh_2026_07_28_machine_status.txt"
KNOWN_BEFORE = FIXTURE_DIR / "refresh_2026_07_28_data_sources_before.html"
KNOWN_AFTER = FIXTURE_DIR / "refresh_2026_07_28_data_sources_after.html"

SOURCE_NAMES = tuple(OBSERVED_SOURCE_JOB_KEYS)
SPINE_SOURCE = "US Congress Legislators (unitedstates/congress-legislators)"
FEC_SOURCE = "FEC Bulk Data"
IRS_SOURCE = "IRS Form 8872 Political Organizations"


def _machine_status(
    *,
    start: str = "2026-08-04T18:53:01.519Z",
    stop: str = "2026-08-04T20:20:08.066Z",
    exit_code: int = 0,
    oom_killed: bool = False,
    requested_stop: bool = False,
) -> str:
    return (
        "Events\nSTATE EVENT SOURCE TIMESTAMP INFO\n"
        f"stopped exit flyd {stop} exit_code={exit_code},"
        f"oom_killed={str(oom_killed).lower()},requested_stop={str(requested_stop).lower()}\n"
        f"started start flyd {start}\n"
    )


def _source_html(pulls: dict[str, str | None], *, extra_row: str = "") -> str:
    rows = []
    for name in SOURCE_NAMES:
        timestamp = pulls[name] or "unknown"
        jurisdiction = "federal/irs_527" if name == IRS_SOURCE else "federal/congress"
        rows.append(f"<tr><td>{name}</td><td>{jurisdiction}</td><td>{timestamp}</td></tr>")
    return (
        "<html><table><thead><tr><th>Name</th><th>Jurisdiction</th><th>Last pull at</th></tr></thead>"
        f"<tbody>{''.join(rows)}{extra_row}</tbody></table></html>"
    )


def _run_cli(
    tmp_path: Path,
    machine_status: str,
    before_html: str,
    after_html: str,
    refresh_history: dict[str, str | None] | None = None,
) -> subprocess.CompletedProcess[str]:
    input_paths = []
    for filename, content in (
        ("machine.txt", machine_status),
        ("before.html", before_html),
        ("after.html", after_html),
    ):
        path = tmp_path / filename
        path.write_text(content, encoding="utf-8")
        input_paths.append(path)

    stub_bin = tmp_path / "stub_bin"
    stub_bin.mkdir()
    for command in ("flyctl", "curl", "docker", "psql"):
        stub = stub_bin / command
        stub.write_text(f"#!/bin/sh\necho unexpected-{command} >&2\nexit 97\n", encoding="utf-8")
        stub.chmod(0o755)
    environment = os.environ.copy()
    environment["PATH"] = f"{stub_bin}:/usr/bin:/bin"

    command = [
        sys.executable,
        str(CLASSIFIER_PATH),
        "--machine-status",
        str(input_paths[0]),
        "--before",
        str(input_paths[1]),
        "--after",
        str(input_paths[2]),
    ]
    if refresh_history is not None:
        refresh_history_path = tmp_path / "refresh_history.json"
        refresh_history_path.write_text(json.dumps(refresh_history), encoding="utf-8")
        command.extend(["--refresh-history", str(refresh_history_path)])

    return subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )


def _payload(result: subprocess.CompletedProcess[str]) -> dict[str, str]:
    assert result.stderr == ""
    assert result.stdout.count("\n") == 1
    assert sum(result.stdout.count(verdict) for verdict in ("FULL", "PARTIAL", "NO_OP", "FAILED")) == 1
    return json.loads(result.stdout)


def test_known_2026_07_28_masters_only_run_is_partial_and_fails_closed(tmp_path: Path) -> None:
    machine_text = KNOWN_MACHINE_STATUS.read_text(encoding="utf-8")
    before_html = KNOWN_BEFORE.read_text(encoding="utf-8")
    after_html = KNOWN_AFTER.read_text(encoding="utf-8")

    run = parse_machine_run(machine_text)
    result = _run_cli(tmp_path, machine_text, before_html, after_html)
    payload = _payload(result)

    assert run.start_at == datetime(2026, 7, 28, 18, 53, 1, 519000, tzinfo=timezone.utc)
    assert run.stop_at == datetime(2026, 7, 28, 19, 20, 8, 66000, tzinfo=timezone.utc)
    assert run.exit_code == 0
    assert result.returncode == PARTIAL_EXIT_CODE
    assert payload["verdict"] == "PARTIAL"
    assert "FEC Bulk Data" in payload["reason"]
    assert SPINE_SOURCE in payload["reason"]
    assert "2026-07-28T18:53:01.519000Z/2026-07-28T19:20:08.066000Z" in payload["reason"]


def test_full_when_all_eligible_sources_advance_and_parked_source_does_not(tmp_path: Path) -> None:
    before = {name: "2026-07-27T00:00:00Z" for name in SOURCE_NAMES}
    before[IRS_SOURCE] = None
    after = {name: "2026-08-04T19:15:00Z" for name in SOURCE_NAMES}
    after[IRS_SOURCE] = None
    refresh_history = {
        "federal-fec-masters": "2026-07-27T00:00:00Z",
        "federal-fec-committee-summary": "2026-07-27T00:00:00Z",
        "federal-fec-races": "2026-07-27T00:00:00Z",
    }

    result = _run_cli(
        tmp_path,
        _machine_status(),
        _source_html(before),
        _source_html(after),
        refresh_history,
    )
    payload = _payload(result)

    assert result.returncode == 0
    assert payload["verdict"] == "FULL"
    assert "advanced=[" in payload["reason"]
    assert f"skipped=[{IRS_SOURCE}]" in payload["reason"]


def test_no_op_when_no_observed_source_is_eligible_or_advances(monkeypatch: pytest.MonkeyPatch) -> None:
    pulls = {name: "2026-08-03T00:00:00Z" for name in SOURCE_NAMES}
    pulls[IRS_SOURCE] = None
    run_start = datetime(2026, 8, 4, 18, 53, 1, 519000, tzinfo=timezone.utc)
    plan = classifier.build_refresh_plan(scope="federal", now=run_start)
    always_due_fec_jobs = {
        "federal-fec-schedule-a",
        "federal-fec-schedule-b",
        "federal-fec-schedule-e",
    }
    plan = [job for job in plan if job.key not in always_due_fec_jobs]
    monkeypatch.setattr(classifier, "build_refresh_plan", lambda **_kwargs: plan)

    classification = classify_refresh_observation(
        _machine_status(),
        _source_html(pulls),
        _source_html(pulls),
        refresh_history_completed_at_by_job_key={
            "federal-fec-masters": datetime(2026, 8, 3, tzinfo=timezone.utc),
            "federal-fec-committee-summary": datetime(2026, 8, 3, tzinfo=timezone.utc),
            "federal-fec-races": datetime(2026, 8, 3, tzinfo=timezone.utc),
        },
    )

    assert classifier._exit_code(classification.verdict) == NO_OP_EXIT_CODE
    assert classification.verdict == "NO_OP"
    assert "eligible=[]" in classification.reason
    assert "advanced=[]" in classification.reason


def test_active_fec_bulk_jobs_make_unchanged_source_a_failure() -> None:
    pulls = {name: "2026-08-03T00:00:00Z" for name in SOURCE_NAMES}
    pulls[IRS_SOURCE] = None

    classification = classify_refresh_observation(
        _machine_status(),
        _source_html(pulls),
        _source_html(pulls),
        refresh_history_completed_at_by_job_key={
            "federal-fec-masters": datetime(2026, 8, 3, tzinfo=timezone.utc),
            "federal-fec-committee-summary": datetime(2026, 8, 3, tzinfo=timezone.utc),
            "federal-fec-races": datetime(2026, 8, 3, tzinfo=timezone.utc),
        },
    )

    assert classification.verdict == "FAILED"
    assert "eligible sources did not advance: FEC Bulk Data" in classification.reason


def test_unmapped_active_fec_bulk_job_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    run_start = datetime(2026, 8, 4, 18, 53, 1, 519000, tzinfo=timezone.utc)
    plan = classifier.build_refresh_plan(scope="federal", now=run_start)
    schedule_a = next(job for job in plan if job.key == "federal-fec-schedule-a")
    plan.append(replace(schedule_a, key="federal-fec-unmapped"))
    monkeypatch.setattr(classifier, "build_refresh_plan", lambda **_kwargs: plan)
    pulls = {name: "2026-08-03T00:00:00Z" for name in SOURCE_NAMES}
    pulls[IRS_SOURCE] = None

    with pytest.raises(ObservationError) as error:
        classify_refresh_observation(
            _machine_status(),
            _source_html(pulls),
            _source_html(pulls),
            refresh_history_completed_at_by_job_key={
                "federal-fec-masters": datetime(2026, 8, 3, tzinfo=timezone.utc),
                "federal-fec-committee-summary": datetime(2026, 8, 3, tzinfo=timezone.utc),
                "federal-fec-races": datetime(2026, 8, 3, tzinfo=timezone.utc),
            },
        )

    assert "active jobs missing from observation mapping: federal-fec-unmapped" in str(error.value)


@pytest.mark.parametrize(
    ("case", "expected_reason"),
    [
        ("nonzero_exit", "exit_code=7"),
        ("oom", "oom_killed=true"),
        ("requested_stop", "requested_stop=true"),
        ("crash", "crash"),
        ("missing_start", "start/stop pair"),
        ("missing_stop", "start/stop pair"),
        ("unknown_source", "unknown federal source"),
        ("malformed_timestamp", "malformed timestamp"),
        ("unparseable", "unparseable Machine status"),
    ],
)
def test_failed_cases_fail_closed(tmp_path: Path, case: str, expected_reason: str) -> None:
    pulls = {name: "2026-07-27T00:00:00Z" for name in SOURCE_NAMES}
    pulls[IRS_SOURCE] = None
    machine = _machine_status()
    before = _source_html(pulls)
    after = _source_html(pulls)

    if case == "nonzero_exit":
        machine = _machine_status(exit_code=7)
    elif case == "oom":
        machine = _machine_status(oom_killed=True)
    elif case == "requested_stop":
        machine = _machine_status(requested_stop=True)
    elif case == "crash":
        machine = machine.replace("stopped exit", "crashed crash").replace("exit_code=0,", "")
    elif case == "missing_start":
        machine = "\n".join(line for line in machine.splitlines() if not line.startswith("started"))
    elif case == "missing_stop":
        machine = "\n".join(line for line in machine.splitlines() if not line.startswith("stopped"))
    elif case == "unknown_source":
        row = "<tr><td>Unknown Federal Feed</td><td>federal/other</td><td>2026-07-27T00:00:00Z</td></tr>"
        before = _source_html(pulls, extra_row=row)
    elif case == "malformed_timestamp":
        before = before.replace("2026-07-27T00:00:00Z", "not-a-date", 1)
    elif case == "unparseable":
        machine = "not a fly Machine status artifact"

    result = _run_cli(tmp_path, machine, before, after)
    payload = _payload(result)

    assert result.returncode == FAILED_EXIT_CODE
    assert payload["verdict"] == "FAILED"
    assert expected_reason in payload["reason"]


def test_machine_run_does_not_cross_intervening_terminal_event() -> None:
    machine_status = (
        "Events\nSTATE EVENT SOURCE TIMESTAMP INFO\n"
        "stopped exit flyd 2026-08-04T20:20:08.066Z "
        "exit_code=0,oom_killed=false,requested_stop=false\n"
        "stopped exit flyd 2026-08-01T20:20:08.066Z "
        "exit_code=0,oom_killed=false,requested_stop=false\n"
        "started start flyd 2026-08-01T18:53:01.519Z\n"
    )

    with pytest.raises(ObservationError, match="missing start/stop pair for latest Machine run"):
        parse_machine_run(machine_status)


def test_successful_run_with_eligible_sources_but_no_advances_is_failed() -> None:
    pulls = {name: "2026-07-27T00:00:00Z" for name in SOURCE_NAMES}
    pulls[IRS_SOURCE] = None

    classification = classify_refresh_observation(
        _machine_status(),
        _source_html(pulls),
        _source_html(pulls),
        refresh_history_completed_at_by_job_key={
            "federal-fec-masters": datetime(2026, 7, 27, tzinfo=timezone.utc),
            "federal-fec-committee-summary": datetime(2026, 7, 27, tzinfo=timezone.utc),
            "federal-fec-races": datetime(2026, 7, 27, tzinfo=timezone.utc),
        },
    )

    assert classification.verdict == "FAILED"
    assert "eligible sources did not advance" in classification.reason


def test_refresh_history_key_eligibility_does_not_proxy_from_data_sources(tmp_path: Path) -> None:
    pulls = {name: "2026-08-03T00:00:00Z" for name in SOURCE_NAMES}
    pulls[IRS_SOURCE] = None
    refresh_history = {
        "federal-fec-masters": "2026-08-03T00:00:00Z",
        "federal-fec-committee-summary": "2026-08-03T00:00:00Z",
        "federal-fec-races": "2026-07-27T00:00:00Z",
    }

    result = _run_cli(
        tmp_path,
        _machine_status(),
        _source_html(pulls),
        _source_html(pulls),
        refresh_history,
    )
    payload = _payload(result)

    assert result.returncode == FAILED_EXIT_CODE
    assert payload["verdict"] == "FAILED"
    assert "eligible sources did not advance:" in payload["reason"]
    assert "FEC Federal Races" in payload["reason"]


def test_post_run_refresh_history_evidence_fails_closed(tmp_path: Path) -> None:
    before = {name: "2026-07-27T00:00:00Z" for name in SOURCE_NAMES}
    before[IRS_SOURCE] = None
    after = {name: "2026-08-04T19:15:00Z" for name in SOURCE_NAMES}
    after[IRS_SOURCE] = None
    refresh_history = {
        "federal-fec-masters": "2026-08-04T19:15:00Z",
        "federal-fec-races": "2026-07-27T00:00:00Z",
    }

    result = _run_cli(
        tmp_path,
        _machine_status(),
        _source_html(before),
        _source_html(after),
        refresh_history,
    )
    payload = _payload(result)

    assert result.returncode == FAILED_EXIT_CODE
    assert payload["verdict"] == "FAILED"
    assert "post-run refresh-history timestamp for federal-fec-masters" in payload["reason"]
    assert "2026-08-04T18:53:01.519000Z" in payload["reason"]


@pytest.mark.parametrize(
    ("capture", "contaminated_at", "expected_reason"),
    [
        (
            "before",
            "2026-08-04T19:15:00Z",
            "before timestamp for FEC Bulk Data is later than Machine start",
        ),
        (
            "after",
            "2026-08-04T20:30:00Z",
            "after timestamp for FEC Bulk Data is later than Machine stop",
        ),
    ],
)
def test_non_bracketing_data_source_evidence_fails_closed(
    capture: str,
    contaminated_at: str,
    expected_reason: str,
) -> None:
    before = {name: "2026-07-27T00:00:00Z" for name in SOURCE_NAMES}
    before[IRS_SOURCE] = None
    after = {name: "2026-08-04T19:15:00Z" for name in SOURCE_NAMES}
    after[IRS_SOURCE] = None
    if capture == "before":
        before[FEC_SOURCE] = contaminated_at
        after[FEC_SOURCE] = contaminated_at
    else:
        after[FEC_SOURCE] = contaminated_at

    with pytest.raises(ObservationError) as error:
        classify_refresh_observation(
            _machine_status(),
            _source_html(before),
            _source_html(after),
            refresh_history_completed_at_by_job_key={
                "federal-fec-masters": datetime(2026, 7, 27, tzinfo=timezone.utc),
                "federal-fec-races": datetime(2026, 7, 27, tzinfo=timezone.utc),
            },
        )

    assert expected_reason in str(error.value)


def test_missing_refresh_history_key_evidence_fails_closed(tmp_path: Path) -> None:
    pulls = {name: "2026-08-03T00:00:00Z" for name in SOURCE_NAMES}
    pulls[IRS_SOURCE] = None
    refresh_history = {
        "federal-fec-masters": "2026-08-03T00:00:00Z",
        "federal-fec-committee-summary": "2026-08-03T00:00:00Z",
    }

    result = _run_cli(
        tmp_path,
        _machine_status(),
        _source_html(pulls),
        _source_html(pulls),
        refresh_history,
    )
    payload = _payload(result)

    assert result.returncode == FAILED_EXIT_CODE
    assert payload["verdict"] == "FAILED"
    assert "cannot prove refresh-history cadence for FEC Federal Races" in payload["reason"]


def test_classifier_source_is_artifact_only_and_reuses_cadence_owner() -> None:
    source = CLASSIFIER_PATH.read_text(encoding="utf-8")

    assert "should_run_job" in source
    assert "build_refresh_plan" in source
    assert "cadence_last_pull_owner" in source
    for forbidden in ("flyctl", "curl", "docker", "psql", "get_connection", "_CADENCE_INTERVALS", "timedelta"):
        assert forbidden not in source
