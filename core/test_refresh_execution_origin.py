from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from core.refresh import job_builders, runner
from core.refresh.authority_execution_plan import (
    expected_runner_command,
    load_authority_execution_plan,
)
from test_support.refresh_run_fixtures import refresh_job_for_tests


_PROFILE_PATH = Path(__file__).resolve().parents[1] / "infra/fly/regional_refresh_machine_profile.json"
_AUTHORITY_PLAN = load_authority_execution_plan(_PROFILE_PATH)
_SCHEDULED_WA_PREFIX = "state-wa-"
_SCHEDULED_WA_KEYS = _AUTHORITY_PLAN.scheduled.job_keys
_WA_JOB_KEY = _SCHEDULED_WA_KEYS[0]
_SCHEDULED_ARGV = [
    "--authority-plan-json",
    str(_PROFILE_PATH),
    *expected_runner_command(_AUTHORITY_PLAN, mode="scheduled")[5:],
]
_CANARY_ARGV = [
    "--authority-plan-json",
    str(_PROFILE_PATH),
    *expected_runner_command(_AUTHORITY_PLAN, mode="canary")[5:],
]


def _job(key: str = _WA_JOB_KEY) -> runner.RefreshJob:
    return refresh_job_for_tests(key, jurisdiction="state/WA")


class _FakeConnection:
    def cursor(self) -> MagicMock:
        cursor_context = MagicMock()
        cursor_context.__enter__.return_value.fetchone.return_value = (True,)
        return cursor_context

    def close(self) -> None:
        pass


def _success(key: str = _WA_JOB_KEY) -> runner.RefreshRunResult:
    return runner.RefreshRunResult(key=key, status="success", metadata_updates=0, message="ok")


@pytest.mark.parametrize(
    "argv",
    [
        _SCHEDULED_ARGV,
        [
            "--execution-origin",
            "scheduled",
            "--execution-mode",
            "scheduled",
            "--authority-plan-json",
            str(_PROFILE_PATH),
        ],
        [
            "--execution-origin=scheduled",
            "--execution-mode=scheduled",
            f"--authority-plan-json={_PROFILE_PATH}",
        ],
    ],
)
def test_exact_scheduled_wa_plan_propagates_origin(
    monkeypatch: pytest.MonkeyPatch,
    argv: list[str],
) -> None:
    jobs = [_job(key) for key in _SCHEDULED_WA_KEYS]
    captured: dict[str, object] = {}

    def fake_build_refresh_plan(**kwargs: object) -> list[runner.RefreshJob]:
        captured["plan_kwargs"] = kwargs
        return jobs

    def fake_run_all_jobs(*args: object, **kwargs: object) -> list[runner.RefreshRunResult]:
        captured["jobs"] = args[1]
        captured["execution_origin"] = kwargs["execution_origin"]
        return [_success(key) for key in _SCHEDULED_WA_KEYS]

    monkeypatch.setattr(job_builders, "build_refresh_plan", fake_build_refresh_plan)
    monkeypatch.setattr(runner, "_acquire_runner_locks_for_jobs", lambda *args, **kwargs: [])
    monkeypatch.setattr(runner, "get_connection", lambda **kwargs: _FakeConnection())
    monkeypatch.setattr(runner, "run_all_jobs", fake_run_all_jobs)

    assert runner.main(argv) == 0
    assert captured["plan_kwargs"] == {
        "scope": "all",
        "parameters": runner.RunnerParameters(),
        "job_key_prefixes": (),
    }
    assert captured["jobs"] == jobs
    assert captured["execution_origin"] == "scheduled"


def test_exact_scheduled_prefix_selects_exactly_the_four_washington_jobs() -> None:
    jobs = job_builders.build_refresh_plan(
        scope="all",
        parameters=runner.RunnerParameters(),
        job_key_prefixes=(_SCHEDULED_WA_PREFIX,),
    )

    assert tuple(job.key for job in jobs) == _SCHEDULED_WA_KEYS


def test_scheduled_main_holds_both_lock_layers_runs_all_four_and_cleans_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    jobs = [_job(key) for key in _SCHEDULED_WA_KEYS]
    events: list[str] = []

    class Connection:
        def close(self) -> None:
            events.append("close")

    def acquire_local(
        selected: list[runner.RefreshJob],
        wait_seconds: float = 0.0,
        authority_ownership_lock_key: str | None = None,
    ) -> list[int]:
        assert tuple(job.key for job in selected) == _SCHEDULED_WA_KEYS
        assert authority_ownership_lock_key == _AUTHORITY_PLAN.ownership_lock_key
        events.append("local:4")
        return [11, 12, 13, 14]

    def acquire_database(
        connection: object,
        selected: list[runner.RefreshJob],
        *,
        authority_ownership_lock_key: str | None = None,
    ) -> bool:
        assert tuple(job.key for job in selected) == _SCHEDULED_WA_KEYS
        assert authority_ownership_lock_key == _AUTHORITY_PLAN.ownership_lock_key
        events.append("database:4")
        return True

    monkeypatch.setattr(job_builders, "build_refresh_plan", lambda **kwargs: jobs)
    monkeypatch.setattr(runner, "_acquire_runner_locks_for_jobs", acquire_local)
    monkeypatch.setattr(runner, "get_connection", lambda **kwargs: Connection())
    monkeypatch.setattr(runner, "_try_acquire_database_runner_locks", acquire_database)

    def run_all(
        connection: object, selected: list[runner.RefreshJob], **kwargs: object
    ) -> list[runner.RefreshRunResult]:
        events.append("run_all")
        assert selected == jobs
        assert kwargs["execution_origin"] == "scheduled"
        assert kwargs["stop_on_failure"] is False
        return [
            runner.RefreshRunResult(
                key=key,
                status="failed" if index == 0 else "success",
                metadata_updates=0,
                message="test",
            )
            for index, key in enumerate(_SCHEDULED_WA_KEYS)
        ]

    monkeypatch.setattr(runner, "run_all_jobs", run_all)
    monkeypatch.setattr(runner, "_release_runner_locks", lambda held: events.append(f"release:{held}"))

    assert runner.main(_SCHEDULED_ARGV) == 1
    assert events == [
        "local:4",
        "database:4",
        "run_all",
        "close",
        "release:[11, 12, 13, 14]",
    ]


def test_canary_main_is_exact_singleton_stop_on_failure_with_both_lock_layers_and_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = _job()
    events: list[str] = []

    class Connection:
        def close(self) -> None:
            events.append("close")

    def build_plan(**kwargs: object) -> list[runner.RefreshJob]:
        assert kwargs == {
            "scope": "all",
            "parameters": runner.RunnerParameters(),
            "job_key_prefixes": (),
        }
        return [job, *[_job(key) for key in _SCHEDULED_WA_KEYS[1:]]]

    def acquire_local(
        selected: list[runner.RefreshJob],
        wait_seconds: float = 0.0,
        authority_ownership_lock_key: str | None = None,
    ) -> list[int]:
        assert selected == [job]
        assert wait_seconds == 0.0
        assert authority_ownership_lock_key == _AUTHORITY_PLAN.ownership_lock_key
        events.append("local:contributions")
        return [11]

    def acquire_database(
        connection: object,
        selected: list[runner.RefreshJob],
        *,
        authority_ownership_lock_key: str | None = None,
    ) -> bool:
        assert selected == [job]
        assert authority_ownership_lock_key == _AUTHORITY_PLAN.ownership_lock_key
        events.append("database:contributions")
        return True

    def run_all(
        connection: object,
        selected: list[runner.RefreshJob],
        **kwargs: object,
    ) -> list[runner.RefreshRunResult]:
        assert selected == [job]
        assert kwargs["dry_run"] is False
        assert kwargs["force"] is False
        assert kwargs["execution_origin"] == "operator_attended"
        assert kwargs["stop_on_failure"] is True
        events.append("run:contributions")
        return [runner.RefreshRunResult(key=_WA_JOB_KEY, status="success", metadata_updates=1, message="ok")]

    monkeypatch.setattr(job_builders, "build_refresh_plan", build_plan)
    monkeypatch.setattr(runner, "_acquire_runner_locks_for_jobs", acquire_local)
    monkeypatch.setattr(runner, "get_connection", lambda **kwargs: Connection())
    monkeypatch.setattr(runner, "_try_acquire_database_runner_locks", acquire_database)
    monkeypatch.setattr(runner, "run_all_jobs", run_all)
    monkeypatch.setattr(runner, "_release_runner_locks", lambda held: events.append(f"release:{held}"))

    assert runner.main(_CANARY_ARGV) == 0
    assert events == [
        "local:contributions",
        "database:contributions",
        "run:contributions",
        "close",
        "release:[11]",
    ]


@pytest.mark.parametrize(
    "extra_argv",
    [
        ["--dry-run"],
        ["--force"],
        ["--no-lock"],
        ["--lock-wait-seconds", "0"],
        ["--fec-limit", "100"],
        ["--job-key-prefix", "state-wa-loans"],
        ["--scope", "all"],
        ["--execution-origin", "operator_attended"],
        ["--wa-contributions-canary"],
    ],
)
def test_canary_rejects_every_extra_option_before_plan_or_database(
    monkeypatch: pytest.MonkeyPatch,
    extra_argv: list[str],
) -> None:
    build_plan = MagicMock(side_effect=AssertionError("plan must not be built"))
    get_connection = MagicMock(side_effect=AssertionError("database must not open"))
    monkeypatch.setattr(job_builders, "build_refresh_plan", build_plan)
    monkeypatch.setattr(runner, "get_connection", get_connection)

    with pytest.raises(SystemExit) as exc_info:
        runner.main([*_CANARY_ARGV, *extra_argv])

    assert exc_info.value.code == 2
    build_plan.assert_not_called()
    get_connection.assert_not_called()


@pytest.mark.parametrize(
    "argv",
    [
        [
            "--scope",
            "all",
            "--job-key-prefix",
            _WA_JOB_KEY,
            "--execution-origin=scheduled",
            "--wa-contributions-canary",
        ],
        [
            "--scope",
            "all",
            "--job-key-prefix",
            "state-wa-",
            "--execution-origin",
            "operator_attended",
            "--wa-contributions-canary",
        ],
        ["--wa-contributions-canary"],
    ],
)
def test_canary_rejects_forged_origin_or_selection_before_plan(
    monkeypatch: pytest.MonkeyPatch,
    argv: list[str],
) -> None:
    build_plan = MagicMock(side_effect=AssertionError("plan must not be built"))
    monkeypatch.setattr(job_builders, "build_refresh_plan", build_plan)

    with pytest.raises(SystemExit) as exc_info:
        runner.main(argv)

    assert exc_info.value.code == 2
    build_plan.assert_not_called()


@pytest.mark.parametrize(
    "planned_keys",
    [
        [],
        ["state-wa-shadow"],
        [_WA_JOB_KEY, "state-wa-loans"],
        [_WA_JOB_KEY, _WA_JOB_KEY],
    ],
)
def test_canary_rejects_tampered_plan_before_lock_or_database(
    monkeypatch: pytest.MonkeyPatch,
    planned_keys: list[str],
) -> None:
    acquire_locks = MagicMock(side_effect=AssertionError("locks must not be acquired"))
    get_connection = MagicMock(side_effect=AssertionError("database must not open"))
    monkeypatch.setattr(job_builders, "build_refresh_plan", lambda **kwargs: [_job(key) for key in planned_keys])
    monkeypatch.setattr(runner, "_acquire_runner_locks_for_jobs", acquire_locks)
    monkeypatch.setattr(runner, "get_connection", get_connection)

    with pytest.raises(SystemExit) as exc_info:
        runner.main(_CANARY_ARGV)

    assert exc_info.value.code == 2
    acquire_locks.assert_not_called()
    get_connection.assert_not_called()


@pytest.mark.parametrize(
    "results",
    [
        [],
        [runner.RefreshRunResult(key=_WA_JOB_KEY, status="skipped", metadata_updates=0, message="cadence")],
        [runner.RefreshRunResult(key=_WA_JOB_KEY, status="success", metadata_updates=0, message="stale")],
        [runner.RefreshRunResult(key="state-wa-loans", status="success", metadata_updates=1, message="wrong")],
        [
            runner.RefreshRunResult(key=_WA_JOB_KEY, status="success", metadata_updates=1, message="ok"),
            runner.RefreshRunResult(key="state-wa-loans", status="success", metadata_updates=1, message="wrong"),
        ],
    ],
)
def test_canary_terminal_contract_rejects_missing_ledger_or_freshness_evidence(
    results: list[runner.RefreshRunResult],
) -> None:
    with pytest.raises(ValueError, match="canary"):
        runner._require_canary_result([_job()], results)


def test_canary_terminal_contract_accepts_one_fresh_success() -> None:
    runner._require_canary_result(
        [_job()], [runner.RefreshRunResult(key=_WA_JOB_KEY, status="success", metadata_updates=1, message="ok")]
    )


@pytest.mark.parametrize(
    "extra_argv",
    [
        ["--dry-run"],
        ["--force"],
        ["--no-lock"],
        ["--lock-wait-seconds", "0"],
        ["--fec-limit", "100"],
        ["--fec-cycle", "2026"],
        ["--pa-year", "2026"],
        ["--co-year", "2026"],
    ],
)
def test_scheduled_wa_plan_rejects_every_extra_option_before_plan_or_database(
    monkeypatch: pytest.MonkeyPatch,
    extra_argv: list[str],
) -> None:
    build_plan = MagicMock(side_effect=AssertionError("plan must not be built"))
    get_connection = MagicMock(side_effect=AssertionError("database must not open"))
    monkeypatch.setattr(job_builders, "build_refresh_plan", build_plan)
    monkeypatch.setattr(runner, "get_connection", get_connection)

    with pytest.raises(SystemExit) as exc_info:
        runner.main([*_SCHEDULED_ARGV, *extra_argv])

    assert exc_info.value.code == 2
    build_plan.assert_not_called()
    get_connection.assert_not_called()


@pytest.mark.parametrize(
    "argv",
    [
        ["--scope", "federal", "--job-key-prefix", _WA_JOB_KEY, "--execution-origin", "scheduled"],
        ["--scope", "priority", "--job-key-prefix", _WA_JOB_KEY, "--execution-origin", "scheduled"],
        ["--scope", "all", "--execution-origin", "scheduled"],
        ["--scope", "all", "--job-key-prefix", _WA_JOB_KEY, "--execution-origin", "scheduled"],
        ["--scope", "all", "--job-key-prefix", "state-wa", "--execution-origin", "scheduled"],
        ["--scope", "all", "--job-key-prefix", "state-", "--execution-origin", "scheduled"],
        ["--scope", "all", "--job-key-prefix", "federal-", "--execution-origin", "scheduled"],
        [
            "--scope",
            "all",
            "--job-key-prefix",
            _SCHEDULED_WA_PREFIX,
            "--job-key-prefix",
            _SCHEDULED_WA_PREFIX,
            "--execution-origin",
            "scheduled",
        ],
        [
            "--scope",
            "all",
            "--job-key-prefix",
            _WA_JOB_KEY,
            "--job-key-prefix",
            "state-wa-loans",
            "--execution-origin",
            "scheduled",
        ],
    ],
)
def test_scheduled_wa_plan_rejects_forged_selection_before_plan(
    monkeypatch: pytest.MonkeyPatch,
    argv: list[str],
) -> None:
    build_plan = MagicMock(side_effect=AssertionError("plan must not be built"))
    monkeypatch.setattr(job_builders, "build_refresh_plan", build_plan)

    with pytest.raises(SystemExit) as exc_info:
        runner.main(argv)

    assert exc_info.value.code == 2
    build_plan.assert_not_called()


def test_legacy_unknown_cannot_be_claimed_from_cli() -> None:
    with pytest.raises(SystemExit) as exc_info:
        runner.main(["--execution-origin", "legacy_unknown"])

    assert exc_info.value.code == 2


@pytest.mark.parametrize(
    "planned_keys",
    [
        [],
        [_WA_JOB_KEY],
        list(_SCHEDULED_WA_KEYS[:-1]),
        [*_SCHEDULED_WA_KEYS, _SCHEDULED_WA_KEYS[-1]],
    ],
)
def test_scheduled_wa_plan_rejects_tampered_plan_before_lock_or_database(
    monkeypatch: pytest.MonkeyPatch,
    planned_keys: list[str],
) -> None:
    acquire_locks = MagicMock(side_effect=AssertionError("locks must not be acquired"))
    get_connection = MagicMock(side_effect=AssertionError("database must not open"))
    monkeypatch.setattr(job_builders, "build_refresh_plan", lambda **kwargs: [_job(key) for key in planned_keys])
    monkeypatch.setattr(runner, "_acquire_runner_locks_for_jobs", acquire_locks)
    monkeypatch.setattr(runner, "get_connection", get_connection)

    with pytest.raises(SystemExit) as exc_info:
        runner.main(_SCHEDULED_ARGV)

    assert exc_info.value.code == 2
    acquire_locks.assert_not_called()
    get_connection.assert_not_called()


def test_programmatic_scheduled_origin_rejects_non_wa_jobs_before_ledger() -> None:
    with pytest.raises(ValueError, match="authority execution plan"):
        runner.run_all_jobs(
            SimpleNamespace(),
            [_job("federal-fec-masters")],
            execution_origin="scheduled",
        )


def test_programmatic_scheduled_origin_runs_all_exact_jobs_after_an_earlier_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = MagicMock()
    jobs = [_job(key) for key in _SCHEDULED_WA_KEYS]
    run_job = MagicMock(
        side_effect=[
            _success(_SCHEDULED_WA_KEYS[0]),
            runner.RefreshRunResult(key=_SCHEDULED_WA_KEYS[1], status="failed", metadata_updates=0, message="test"),
            _success(_SCHEDULED_WA_KEYS[2]),
            _success(_SCHEDULED_WA_KEYS[3]),
        ],
    )
    monkeypatch.setattr(runner, "_select_latest_pull_at", MagicMock(return_value=None))
    monkeypatch.setattr(runner, "run_job", run_job)

    results = runner.run_all_jobs(
        connection,
        jobs,
        execution_origin="scheduled",
        execution_plan=_AUTHORITY_PLAN,
        execution_mode="scheduled",
    )

    assert [(result.key, result.status) for result in results] == [
        (_SCHEDULED_WA_KEYS[0], "success"),
        (_SCHEDULED_WA_KEYS[1], "failed"),
        (_SCHEDULED_WA_KEYS[2], "success"),
        (_SCHEDULED_WA_KEYS[3], "success"),
    ]
    assert run_job.call_count == 4
    assert all(call.kwargs["execution_origin"] == "scheduled" for call in run_job.call_args_list)
    assert all(call.kwargs["execution_plan"] == _AUTHORITY_PLAN for call in run_job.call_args_list)
    assert all(call.kwargs["execution_mode"] == "scheduled" for call in run_job.call_args_list)


def test_programmatic_unknown_origin_rejects_before_ledger() -> None:
    connection = MagicMock()

    with pytest.raises(ValueError, match="Unsupported execution origin"):
        runner.run_all_jobs(
            connection,
            [_job()],
            execution_origin="cron",  # type: ignore[arg-type]
        )

    connection.cursor.assert_not_called()


@pytest.mark.parametrize("kwargs", [{"force": True}, {"dry_run": True}])
def test_programmatic_scheduled_origin_rejects_non_execution_modes_before_work(
    kwargs: dict[str, bool],
) -> None:
    connection = MagicMock()
    run_callable = MagicMock()
    jobs = [refresh_job_for_tests(key, run_callable=run_callable) for key in _SCHEDULED_WA_KEYS]

    with pytest.raises(ValueError, match="planned execution"):
        runner.run_all_jobs(
            connection,
            jobs,
            execution_origin="scheduled",
            execution_plan=_AUTHORITY_PLAN,
            execution_mode="scheduled",
            **kwargs,
        )

    connection.cursor.assert_not_called()
    run_callable.assert_not_called()


def test_programmatic_scheduled_run_job_rejects_dry_run_before_ledger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    insert_refresh_run = MagicMock()
    monkeypatch.setattr(runner, "insert_refresh_run", insert_refresh_run)

    with pytest.raises(ValueError, match="planned execution"):
        runner.run_job(
            MagicMock(),
            _job(),
            dry_run=True,
            execution_origin="operator_attended",
            execution_plan=_AUTHORITY_PLAN,
            execution_mode="canary",
        )

    insert_refresh_run.assert_not_called()


def test_programmatic_scheduled_run_job_rejects_a_job_outside_exact_set_before_ledger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    insert_refresh_run = MagicMock()
    monkeypatch.setattr(runner, "insert_refresh_run", insert_refresh_run)

    with pytest.raises(ValueError, match="scheduled"):
        runner.run_job(MagicMock(), _job("state-wa-shadow"), execution_origin="scheduled")

    insert_refresh_run.assert_not_called()


def test_omitted_origin_stays_legacy_unknown_and_explicit_manual_is_attended(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_origins: list[str] = []
    job = _job()

    def fake_run_all_jobs(*args: object, **kwargs: object) -> list[runner.RefreshRunResult]:
        captured_origins.append(str(kwargs["execution_origin"]))
        return [_success()]

    monkeypatch.setattr(job_builders, "build_refresh_plan", lambda **kwargs: [job])
    monkeypatch.setattr(runner, "_acquire_runner_locks_for_jobs", lambda *args, **kwargs: [])
    monkeypatch.setattr(runner, "get_connection", lambda **kwargs: _FakeConnection())
    monkeypatch.setattr(runner, "run_all_jobs", fake_run_all_jobs)

    assert runner.main(["--scope", "all", "--job-key-prefix", _WA_JOB_KEY]) == 0
    assert (
        runner.main(
            [
                "--scope",
                "all",
                "--job-key-prefix",
                _WA_JOB_KEY,
                "--execution-origin",
                "operator_attended",
            ]
        )
        == 0
    )

    assert captured_origins == ["legacy_unknown", "operator_attended"]


def test_start_and_finish_attempt_keep_declared_execution_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inserted = MagicMock()
    updated = MagicMock()
    connection = SimpleNamespace(commit=MagicMock())
    job = _job()
    started_at = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)
    completed_at = datetime(2026, 8, 27, 12, 5, tzinfo=timezone.utc)
    monkeypatch.setattr(runner, "insert_refresh_run", inserted)
    monkeypatch.setattr(runner, "update_refresh_run", updated)

    run_id = runner._start_refresh_run(
        connection,
        job,
        started_at=started_at,
        execution_origin="scheduled",
    )
    runner._finish_refresh_run(
        connection,
        run_id,
        job,
        pull_status="success",
        counts={"inserted": 1, "skipped": 0, "quarantined": 0, "superseded": 0, "errors": 0},
        started_at=started_at,
        completed_at=completed_at,
        metadata_updates=1,
        message="ok",
        error=None,
        execution_origin="scheduled",
    )

    assert inserted.call_args.args[1].execution_origin == "scheduled"
    assert updated.call_args.args[1].execution_origin == "scheduled"


def test_run_job_propagates_planned_canary_origin_through_the_exact_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inserted = MagicMock()
    updated = MagicMock()
    connection = SimpleNamespace(commit=MagicMock(), rollback=MagicMock())
    job = _job()
    outcome = runner._JobOutcome(
        pull_status="success",
        counts={"inserted": 1, "skipped": 0, "quarantined": 0, "superseded": 0, "errors": 0},
        message="ok",
        completed_at=datetime(2026, 8, 27, 12, 5, tzinfo=timezone.utc),
        error=None,
    )
    monkeypatch.setattr(runner, "insert_refresh_run", inserted)
    monkeypatch.setattr(runner, "update_refresh_run", updated)
    monkeypatch.setattr(runner, "_execute_job", MagicMock(return_value=outcome))
    monkeypatch.setattr(runner, "_sync_job_metadata", MagicMock(return_value=0))

    result = runner.run_job(
        connection,
        job,
        execution_origin="operator_attended",
        execution_plan=_AUTHORITY_PLAN,
        execution_mode="canary",
    )

    assert result.status == "success"
    assert inserted.call_args.args[1].execution_origin == "operator_attended"
    assert updated.call_args.args[1].execution_origin == "operator_attended"
    runner._execute_job.assert_called_once_with(connection, job)


@pytest.mark.parametrize(
    ("origin_kwargs", "expected_origin"),
    [
        ({}, "legacy_unknown"),
        ({"execution_origin": "operator_attended"}, "operator_attended"),
    ],
)
def test_repair_pair_alarm_propagates_declared_or_default_origin(
    monkeypatch: pytest.MonkeyPatch,
    origin_kwargs: dict[str, str],
    expected_origin: str,
) -> None:
    disturbing_job = _job("federal-fec-masters")
    repair_job = _job("federal-congress-spine")
    recorded = MagicMock()
    connection = MagicMock()
    observed_at = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(runner, "_utc_now", lambda: observed_at)
    monkeypatch.setattr(runner, "_record_refresh_run", recorded)

    result = runner._record_repair_pair_alarm(
        connection,
        disturbing_job,
        repair_job,
        last_pull_at_by_key={
            disturbing_job.key: observed_at,
            repair_job.key: observed_at,
        },
        **origin_kwargs,
    )

    assert result.status == "failed"
    assert recorded.call_args.kwargs["execution_origin"] == expected_origin
