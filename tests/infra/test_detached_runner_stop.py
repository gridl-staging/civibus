"""Contract tests for `run_stop()` in infra/scripts/detached_runner.sh.

Covers termination of the verified wrapper-led process group, every fail-closed
refusal that the ownership guard enforces, and stop/status idempotence after a job
reaches a terminal receipt. The start, wait, status, and progress-probe contracts
live in tests/infra/test_detached_runner.py; both files share
tests/infra/detached_runner_helpers.py as their single helper owner.
"""

from __future__ import annotations

import contextlib
import dataclasses
import os
import shutil
import signal
import subprocess
import sys
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

import tests.infra.detached_runner_helpers as runner_helpers
from tests.infra.detached_runner_helpers import (
    _assert_control_is_running,
    _assert_pid_keeps_identity,
    _assert_recorded_wrapper_pgid,
    _assert_stop_refused_without_signaling,
    _fixture_command,
    _json_stdout,
    _observed_pgid,
    _observed_process_identity,
    _pid_is_alive,
    _process_tree_fixture_command,
    _reclaiming_test_owned_processes,
    _reused_pgid_stand_in,
    _run_runner,
    _signal_resistant_fixture,
    _start_job,
    _status,
    _stop_if_running,
    _StopRefusalExpectation,
    _term_resistant_grandchild_fixture,
    _terminate_exact_pid,
    _terminate_recorded_processes,
    _unrelated_control_process,
    _wait_for_exit_without_reaping,
    _wait_for_file,
    _wait_for_pid_file,
    _wait_for_pid_to_exit,
    _wait_for_process_tree,
    _write_executable,
    _write_group_liveness_bash_env,
)


_FIXTURE_STARTED_PROGRESS_ROW = '{"phase": "started", "rows": 1}'


class _SimulatedTime:
    """Deterministic stand-in for the helper module's `time`.

    `monotonic()` advances by `monotonic_advance_seconds` per read, modelling a
    scheduler jump; `sleep()` advances by `sleep_advance_seconds` when set,
    modelling a sleep that overshoots what it was asked for.
    """

    def __init__(self) -> None:
        self.elapsed_seconds = 0.0
        self.monotonic_advance_seconds = 0.0
        self.sleep_advance_seconds: float | None = None
        self.requested_sleeps: list[float] = []

    def monotonic(self) -> float:
        self.elapsed_seconds += self.monotonic_advance_seconds
        return self.elapsed_seconds

    def sleep(self, seconds: float) -> None:
        self.requested_sleeps.append(seconds)
        self.elapsed_seconds += self.sleep_advance_seconds or seconds


@pytest.fixture
def simulated_time(monkeypatch: pytest.MonkeyPatch) -> Iterator[_SimulatedTime]:
    clock = _SimulatedTime()
    monkeypatch.setattr(runner_helpers, "time", clock)
    yield clock


def test_control_liveness_proof_rejects_a_signalled_unreaped_control() -> None:
    """Guard the no-signal proof itself against zombie false positives.

    Every refusal test below concludes "nothing was signalled" from the control
    process still being alive. A PID probe cannot support that conclusion: a
    child killed but not yet reaped keeps its PID resolvable. This proves the
    shared assertion rejects exactly that state, so a regression that signals
    the control cannot pass as a refusal.
    """
    with _unrelated_control_process() as control:
        _assert_control_is_running(control)

        os.kill(control.pid, signal.SIGKILL)
        _wait_for_exit_without_reaping(control)
        assert _pid_is_alive(control.pid), "expected an unreaped zombie whose PID still resolves"

        with pytest.raises(AssertionError, match="was signalled"):
            _assert_control_is_running(control)


@pytest.mark.parametrize(
    ("expected_identity", "diagnostic_category"),
    [("", "invalid expected identity"), ("expected command", "identity unavailable")],
)
def test_pid_identity_hold_observes_exactly_when_the_expectation_is_usable(
    monkeypatch: pytest.MonkeyPatch,
    simulated_time: _SimulatedTime,
    expected_identity: str,
    diagnostic_category: str,
) -> None:
    """Refuse an empty expectation unobserved, and observe for a usable one.

    An empty expectation would match a PID whose command cannot be read at all,
    so it is refused before anything is observed. Every clock read here lands
    past the requested hold, so a hold that consulted the clock ahead of its
    first observation would return having vacuously held an identity it never
    saw.
    """
    pid = 4101
    observed_pids: list[int] = []
    simulated_time.monotonic_advance_seconds = 1.0
    monkeypatch.setattr(
        runner_helpers, "_observed_process_identity", lambda observed_pid: observed_pids.append(observed_pid) or ""
    )

    with pytest.raises(AssertionError) as raised:
        _assert_pid_keeps_identity(pid, expected_identity, hold_seconds=0.5)

    assert f"PID {pid}" in str(raised.value)
    assert diagnostic_category in str(raised.value)
    assert observed_pids == ([pid] if expected_identity else [])


@pytest.mark.parametrize("lost_identity", ["", "different command"])
@pytest.mark.parametrize("hold_seconds", [0, 0.1])
def test_pid_identity_hold_rejects_identity_loss_anywhere_in_the_hold(
    monkeypatch: pytest.MonkeyPatch,
    simulated_time: _SimulatedTime,
    lost_identity: str,
    hold_seconds: float,
) -> None:
    """Reject a lost identity at the first observation and at the deadline.

    A zero hold loses the identity before the hold starts; the longer hold
    matches until the simulated clock -- which overshoots each sleep -- reaches
    its deadline, so there the refusal comes from the deadline sample.
    """
    pid = 4102
    expected_identity = "expected command"
    simulated_time.sleep_advance_seconds = 0.06

    def observe_identity(observed_pid: int) -> str:
        return lost_identity if simulated_time.elapsed_seconds >= hold_seconds else expected_identity

    monkeypatch.setattr(runner_helpers, "_observed_process_identity", observe_identity)

    with pytest.raises(AssertionError) as raised:
        _assert_pid_keeps_identity(pid, expected_identity, hold_seconds=hold_seconds)

    assert f"PID {pid}" in str(raised.value)
    assert ("identity unavailable" if not lost_identity else "identity mismatch") in str(raised.value)


@pytest.mark.parametrize("successful_observations_before_error", [0, 1])
def test_pid_identity_hold_preserves_observation_exceptions(
    monkeypatch: pytest.MonkeyPatch,
    simulated_time: _SimulatedTime,
    successful_observations_before_error: int,
) -> None:
    expected_identity = "expected command"
    sentinel_error = RuntimeError("sentinel observation error")
    successful_observations = 0

    def observe_identity(pid: int) -> str:
        nonlocal successful_observations
        if successful_observations == successful_observations_before_error:
            raise sentinel_error
        successful_observations += 1
        return expected_identity

    monkeypatch.setattr(runner_helpers, "_observed_process_identity", observe_identity)

    with pytest.raises(RuntimeError) as raised:
        _assert_pid_keeps_identity(4103, expected_identity, hold_seconds=0.1)

    assert raised.value is sentinel_error


def test_pid_identity_hold_reports_collected_zero_exit_as_unavailable() -> None:
    with subprocess.Popen([sys.executable, "-c", "pass"]) as collected_child:
        pid = collected_child.pid
        return_code = collected_child.wait(timeout=5)

    assert return_code == 0
    with pytest.raises(AssertionError) as raised:
        _assert_pid_keeps_identity(pid, "expected command", hold_seconds=0)

    diagnostic = str(raised.value)
    assert f"PID {pid}" in diagnostic
    assert "identity unavailable" in diagnostic
    assert "signal" not in diagnostic
    assert "exit" not in diagnostic


def test_pid_identity_hold_covers_full_window_and_final_observation(
    monkeypatch: pytest.MonkeyPatch,
    simulated_time: _SimulatedTime,
) -> None:
    expected_identity = "expected command"
    observation_times: list[float] = []

    def observe_identity(pid: int) -> str:
        if not observation_times:
            simulated_time.elapsed_seconds += 0.4
        observation_times.append(simulated_time.elapsed_seconds)
        return expected_identity

    monkeypatch.setattr(runner_helpers, "_observed_process_identity", observe_identity)

    _assert_pid_keeps_identity(4106, expected_identity)

    initial_observation_completed_at = observation_times[0]
    required_deadline = initial_observation_completed_at + 1.0
    assert observation_times[-1] >= required_deadline
    assert observation_times[-1] - initial_observation_completed_at >= 1.0
    assert set(simulated_time.requested_sleeps) == {0.05}


@contextlib.contextmanager
def _release_gated_fixture(
    tmp_path: Path, *, exit_code: int, capture_stdout: bool = False
) -> Iterator[tuple[subprocess.Popen[str], Path, Path]]:
    """Run a release-gated fixture command directly, past its first progress row.

    Yields the process with its progress file and release marker. The marker is
    spelled with a space and an apostrophe so a caller that interpolated the
    path into a shell word instead of passing it through would fail here rather
    than in the runner tests that share the same fixture command.
    """
    progress_path = tmp_path / "progress.jsonl"
    release_path = tmp_path / "release path's marker"
    process = subprocess.Popen(
        _fixture_command(exit_code=exit_code, sleep_seconds="0.01", release_path=release_path),
        env={**os.environ, "DETACHED_RUNNER_PROGRESS_FILE": str(progress_path)},
        stdout=subprocess.PIPE if capture_stdout else None,
        text=True,
    )
    try:
        assert _wait_for_file(progress_path) == _FIXTURE_STARTED_PROGRESS_ROW
        yield process, progress_path, release_path
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)


def test_fixture_command_release_controls_completion(tmp_path: Path) -> None:
    with _release_gated_fixture(tmp_path, exit_code=7, capture_stdout=True) as (process, progress_path, release_path):
        with pytest.raises(subprocess.TimeoutExpired):
            process.wait(timeout=0.2)

        release_path.touch()
        assert process.wait(timeout=5) == 7
        assert progress_path.read_text(encoding="utf-8").splitlines() == [
            _FIXTURE_STARTED_PROGRESS_ROW,
            '{"phase": "finished", "rows": 2}',
        ]
        assert process.stdout is not None
        assert process.stdout.read().splitlines() == ["fixture stdout start", "fixture final log"]


def test_fixture_command_release_preserves_sigterm(tmp_path: Path) -> None:
    with _release_gated_fixture(tmp_path, exit_code=0) as (process, _, release_path):
        assert not release_path.exists()
        process.terminate()
        assert process.wait(timeout=5) == -signal.SIGTERM
        assert not release_path.exists()


@dataclasses.dataclass
class _RecordedProcessFixture:
    """The recorded-teardown job, plus the identities its assertions corrupt.

    `pids` and `identities` fill in as the lifecycle below reaches them, so a
    setup failure still leaves teardown an accurate record of what to undo.
    """

    test_dir: Path
    pids: dict[str, int] = dataclasses.field(default_factory=dict)
    identities: dict[Path, bytes] = dataclasses.field(default_factory=dict)

    @property
    def job_dir(self) -> Path:
        return self.test_dir / "jobs" / "recorded_teardown_guard"

    @property
    def release_path(self) -> Path:
        return self.test_dir / "fixture release's marker"

    @property
    def identity_paths(self) -> tuple[Path, ...]:
        return (self.job_dir / "process_identity", self.job_dir / "child_process_identity")

    def corrupt_recorded_identities(self) -> None:
        for path in self.identities:
            path.write_text("definitely-not-the-recorded-command\n", encoding="utf-8")

    def restore_recorded_identities(self) -> None:
        for path in self.identity_paths:
            if path.exists() and path not in self.identities:
                self.identities[path] = path.read_bytes()
        for path, identity in self.identities.items():
            path.write_bytes(identity)

    def wait_for_recorded_exits(self) -> None:
        for pid_name in ("child_pid", "pid"):
            if pid_name in self.pids:
                _wait_for_pid_to_exit(self.pids[pid_name])


@contextlib.contextmanager
def _recorded_process_lifecycle(
    fixture: _RecordedProcessFixture,
    *,
    readiness_assertion: Callable[[], None] | None = None,
) -> Iterator[_RecordedProcessFixture]:
    """Start the recorded-teardown job and guarantee it is reaped afterwards.

    Teardown is registered on an `ExitStack` before the job starts, so every
    step still runs -- and runs even if an earlier step raises -- however far
    setup or the body got.
    """
    with contextlib.ExitStack() as teardown:
        # Callbacks unwind last-registered-first, so this reads bottom-up:
        # restore identities, sweep the recorded PIDs, release the fixture
        # command, then wait out both processes.
        teardown.callback(fixture.wait_for_recorded_exits)
        teardown.callback(fixture.release_path.touch)
        teardown.callback(_terminate_recorded_processes, fixture.job_dir)
        teardown.callback(fixture.restore_recorded_identities)

        job = _start_job(
            fixture.test_dir / "jobs",
            "recorded_teardown_guard",
            *_fixture_command(exit_code=0, sleep_seconds="0.01", release_path=fixture.release_path),
        )
        fixture.pids["pid"] = job.wrapper_pid
        fixture.pids["child_pid"] = _wait_for_pid_file(fixture.job_dir / "child_pid")
        if readiness_assertion is not None:
            readiness_assertion()
        for path in fixture.identity_paths:
            _wait_for_file(path)
            fixture.identities[path] = path.read_bytes()
        assert _wait_for_file(fixture.job_dir / "progress.jsonl") == _FIXTURE_STARTED_PROGRESS_ROW
        for pid_name, identity_path in zip(("pid", "child_pid"), fixture.identity_paths, strict=True):
            expected_identity = fixture.identities[identity_path].decode().strip()
            assert expected_identity
            assert _observed_process_identity(fixture.pids[pid_name]) == expected_identity
        assert not fixture.release_path.exists()
        yield fixture


def test_recorded_process_teardown_requires_a_matching_recorded_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prove the shared teardown signals only PIDs it can still prove are ours.

    `_terminate_recorded_processes()` is what the refusal tests fall back on
    once they have proved a recorded PID is gone, so its guard has to hold in
    both directions. It must refuse a recorded PID whose observed command no
    longer matches what start recorded — under PID reuse that number names
    somebody else — and it must still terminate one that does match. A guard
    that only ever skipped would pass this file's teardowns while quietly
    leaking every job process onto this shared host.
    """
    fixture = _RecordedProcessFixture(tmp_path)
    termination_calls: list[int] = []
    terminate_exact_pid = runner_helpers._terminate_exact_pid

    def record_termination(pid: int) -> None:
        termination_calls.append(pid)
        terminate_exact_pid(pid)

    monkeypatch.setattr(runner_helpers, "_terminate_exact_pid", record_termination)
    with _recorded_process_lifecycle(fixture):
        fixture.corrupt_recorded_identities()
        _terminate_recorded_processes(fixture.job_dir)
        assert termination_calls == []
        wrapper_identity = fixture.identities[fixture.job_dir / "process_identity"].decode().strip()
        _assert_pid_keeps_identity(fixture.pids["pid"], wrapper_identity)
        assert termination_calls == []
        assert not fixture.release_path.exists()

        fixture.restore_recorded_identities()
        _terminate_recorded_processes(fixture.job_dir)
        assert fixture.pids["child_pid"] in termination_calls
        assert set(termination_calls) <= set(fixture.pids.values())
        fixture.wait_for_recorded_exits()
        assert not fixture.release_path.exists()


@pytest.mark.parametrize("failure_point", ["readiness", "before_corruption", "after_corruption"])
def test_recorded_process_teardown_assertion_failure_cleanup(tmp_path: Path, failure_point: str) -> None:
    fixture = _RecordedProcessFixture(tmp_path)
    sentinel_message = f"sentinel failure at {failure_point}"

    def readiness_assertion() -> None:
        if failure_point == "readiness":
            raise AssertionError(sentinel_message)

    with pytest.raises(AssertionError, match=sentinel_message):
        with _recorded_process_lifecycle(fixture, readiness_assertion=readiness_assertion):
            if failure_point == "before_corruption":
                raise AssertionError(sentinel_message)
            fixture.corrupt_recorded_identities()
            raise AssertionError(sentinel_message)

    assert fixture.identities
    assert all(path.read_bytes() == identity for path, identity in fixture.identities.items())
    assert fixture.release_path.exists()
    assert set(fixture.pids) == {"pid", "child_pid"}
    fixture.wait_for_recorded_exits()


def test_reclaim_signals_only_the_test_owned_pids_still_tracked(tmp_path: Path) -> None:
    """Prove the shared reclaim drops a PID whose exit the test body proved.

    Every success-path teardown below hands its fixture PIDs to this seam.
    Once `confirm_exited()` has proven a PID gone, that number may already
    belong to somebody else, so the `finally` reclaim must not signal it. Both
    directions are asserted: a seam that signalled nothing would also pass the
    no-signal half while leaking a 300-second sleeper onto this shared host
    every time a test body failed before proving its fixtures dead.
    """
    job_dir = tmp_path / "jobs" / "reclaim_guard"
    job_dir.mkdir(parents=True)

    with _unrelated_control_process() as discarded, _unrelated_control_process() as retained:
        discarded_identity = _observed_process_identity(discarded.pid)
        assert discarded_identity, "sentinel process must be observable before the reclaim"

        with _reclaiming_test_owned_processes(job_dir) as reclaim:
            reclaim.track(discarded.pid, retained.pid)
            reclaim.discard_proven_dead(discarded.pid)

        # `wait()` rather than a PID probe: a signalled-but-unreaped child stays
        # a zombie whose PID still resolves, and only the reaped status names
        # the signal that ended it.
        assert retained.wait(timeout=5) == -signal.SIGKILL
        _assert_pid_keeps_identity(discarded.pid, discarded_identity)
        _assert_control_is_running(discarded)


def test_reclaim_kills_each_tracked_pid_once_in_deepest_first_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, int | Path]] = []
    job_dir = tmp_path / "jobs" / "ordered_reclaim"
    monkeypatch.setattr(
        runner_helpers,
        "_kill_exact_pid",
        lambda pid: events.append(("kill", pid)),
    )
    monkeypatch.setattr(
        runner_helpers,
        "_terminate_recorded_processes",
        lambda recorded_job_dir: events.append(("recorded_sweep", recorded_job_dir)),
    )
    reclaimer = runner_helpers._OwnedProcessReclaimer(job_dir)
    reclaimer.track(101, 202)
    reclaimer.track(303, 202)

    reclaimer.reclaim()
    reclaimer.reclaim()

    assert events == [
        ("kill", 303),
        ("kill", 202),
        ("kill", 101),
        ("recorded_sweep", job_dir),
        ("recorded_sweep", job_dir),
    ]


def test_reclaim_refuses_to_track_a_pid_with_broadcast_signal_semantics() -> None:
    """Prove the reclaim's only signal source can hold nothing but exact PIDs.

    `os.kill` reads 0 as the caller's entire process group and -1 as every
    process the user can signal, so a single non-positive number turns this
    teardown from an exact-PID reclaim into a broadcast across a host that runs
    concurrent workers. Tracked PIDs arrive from parsing a fixture-written
    file, and `int("0")` parses, so intake is the last point that can still
    tell an exact PID from a broadcast one. The rejected batch is asserted to
    leave nothing tracked, because a guard that refused after storing would
    still hand the number to `reclaim()`.
    """
    reclaimer = runner_helpers._OwnedProcessReclaimer(Path("unused_job_dir"))

    for broadcast_pid in (0, -1, -os.getpid()):
        with pytest.raises(AssertionError, match="exact PID"):
            reclaimer.track(os.getpid(), broadcast_pid)

    assert reclaimer._live_pids == []


def test_stop_refuses_when_recorded_process_identity_does_not_match(tmp_path: Path) -> None:
    job = _start_job(tmp_path / "jobs", "identity_guard", *_fixture_command(exit_code=0, sleep_seconds="2.0"))

    identity_path = job.job_dir / "process_identity"
    recorded_identity = identity_path.read_text(encoding="utf-8")
    identity_path.write_text("definitely-not-the-recorded-command\n", encoding="utf-8")

    status_payload = _status(job.job_root, job.job_name)
    assert status_payload["alive"] is False
    assert status_payload["exit_code"] is None

    with _unrelated_control_process() as control:
        _assert_stop_refused_without_signaling(
            _StopRefusalExpectation(job=job, expected_reason="process identity mismatch"), control=control
        )

    identity_path.write_text(recorded_identity, encoding="utf-8")
    _stop_if_running(job.job_root, job.job_name)


def test_stop_kills_verified_group_when_term_does_not_finish(tmp_path: Path) -> None:
    child_pid_path = tmp_path / "child.pid"
    job = _start_job(tmp_path / "jobs", "term_resistant", *_signal_resistant_fixture(child_pid_path))
    child_pid = _wait_for_pid_file(child_pid_path)

    with _reclaiming_test_owned_processes(job.job_dir) as reclaim:
        reclaim.track(child_pid)
        stop = _run_runner(
            job.job_root,
            "stop",
            job.job_name,
            extra_env={"DETACHED_RUNNER_STOP_GRACE_SECONDS": "1"},
            timeout_seconds=4,
        )
        assert stop.returncode == 0, stop.stderr
        reclaim.confirm_exited(child_pid)

        status_payload = _status(job.job_root, job.job_name)
        assert status_payload["alive"] is False
        assert status_payload["exit_code"] == 143


def test_stop_writes_receipt_when_group_drains_after_kill_wait(tmp_path: Path) -> None:
    child_pid_path = tmp_path / "child.pid"
    bash_env = tmp_path / "bash_env"
    liveness_state = tmp_path / "group_liveness_count"
    job = _start_job(tmp_path / "jobs", "kill_timeout_receipt", *_signal_resistant_fixture(child_pid_path))
    child_pid = _wait_for_pid_file(child_pid_path)
    _write_group_liveness_bash_env(bash_env, liveness_state, live_checks=40)

    with _reclaiming_test_owned_processes(job.job_dir) as reclaim:
        reclaim.track(job.wrapper_pid, child_pid)
        stop = _run_runner(
            job.job_root,
            "stop",
            job.job_name,
            extra_env={
                "BASH_ENV": str(bash_env),
                "DETACHED_RUNNER_STOP_GRACE_SECONDS": "2",
                "DETACHED_RUNNER_TEST_PGID": str(job.wrapper_pid),
            },
            timeout_seconds=7,
        )
        assert stop.returncode == 0, stop.stderr
        status_payload = _json_stdout(stop)
        assert status_payload["alive"] is False
        assert status_payload["exit_code"] == 143
        assert (job.job_dir / "exit_code").read_text(encoding="utf-8") == "143\n"


def test_stop_kills_group_when_descendant_survives_term(tmp_path: Path) -> None:
    tree_dir = tmp_path / "tree"
    job = _start_job(tmp_path / "jobs", "term_resistant_grandchild", *_term_resistant_grandchild_fixture(tree_dir))
    child_pid = _wait_for_pid_file(tree_dir / "child.pid")
    grandchild_pid = _wait_for_pid_file(tree_dir / "grandchild.pid")

    with _reclaiming_test_owned_processes(job.job_dir) as reclaim:
        reclaim.track(child_pid, grandchild_pid)
        _assert_recorded_wrapper_pgid(job.job_dir, job.wrapper_pid)
        recorded_pgid = int((job.job_dir / "pgid").read_text(encoding="utf-8").strip())
        assert int(_wait_for_file(tree_dir / "child.pgid")) == recorded_pgid
        assert int(_wait_for_file(tree_dir / "grandchild.pgid")) == recorded_pgid

        stop = _run_runner(
            job.job_root,
            "stop",
            job.job_name,
            extra_env={"DETACHED_RUNNER_STOP_GRACE_SECONDS": "1"},
            timeout_seconds=4,
        )
        assert stop.returncode == 0, stop.stderr
        reclaim.confirm_exited(child_pid)
        reclaim.confirm_exited(grandchild_pid)

        status_payload = _status(job.job_root, job.job_name)
        assert status_payload["alive"] is False
        assert status_payload["exit_code"] == 143


@pytest.mark.parametrize("metadata_name", ["pid", "process_identity", "pgid"])
def test_stop_refuses_when_required_stop_metadata_is_missing(
    tmp_path: Path,
    metadata_name: str,
) -> None:
    # `_start_job` captures the wrapper PID before metadata is mutated: the
    # "pid" case deletes the only recorded copy, so cleanup cannot read it back.
    job = _start_job(
        tmp_path / "jobs", "missing_stop_metadata_guard", *_fixture_command(exit_code=0, sleep_seconds="2.0")
    )

    with _unrelated_control_process() as control:
        try:
            (job.job_dir / metadata_name).unlink()

            _assert_stop_refused_without_signaling(
                _StopRefusalExpectation(job=job, expected_reason="incomplete process metadata"), control=control
            )
        finally:
            _terminate_exact_pid(job.wrapper_pid)


def test_stop_refuses_when_recorded_pid_points_at_an_unrelated_live_process(tmp_path: Path) -> None:
    job = _start_job(tmp_path / "jobs", "reused_pid_guard", *_fixture_command(exit_code=0, sleep_seconds="2.0"))

    with _unrelated_control_process() as control:
        try:
            # Stand-in for PID reuse: the recorded PID now names an unrelated
            # live process while the recorded identity still describes the
            # wrapper.
            (job.job_dir / "pid").write_text(f"{control.pid}\n", encoding="utf-8")

            _assert_stop_refused_without_signaling(
                _StopRefusalExpectation(job=job, expected_reason="process identity mismatch"), control=control
            )
        finally:
            _terminate_exact_pid(job.wrapper_pid)


def test_stop_refuses_when_recorded_pgid_does_not_match_wrapper_pid(tmp_path: Path) -> None:
    job = _start_job(tmp_path / "jobs", "recorded_pgid_guard", *_fixture_command(exit_code=0, sleep_seconds="2.0"))

    with _unrelated_control_process() as control:
        # Stand-in for PGID reuse: record a process group that is real and live,
        # led by an unrelated session leader.
        reused_pgid = _reused_pgid_stand_in(control, wrapper_pid=job.wrapper_pid)
        (job.job_dir / "pgid").write_text(f"{reused_pgid}\n", encoding="utf-8")

        _assert_stop_refused_without_signaling(
            _StopRefusalExpectation(
                job=job,
                expected_reason=f"wrapper PID {job.wrapper_pid} no longer leads recorded process group {reused_pgid}",
            ),
            control=control,
        )
    _terminate_recorded_processes(job.job_dir)


def test_stop_refuses_when_observed_pgid_does_not_match_wrapper_pid(tmp_path: Path) -> None:
    stub_bin = tmp_path / "bin"
    job = _start_job(tmp_path / "jobs", "observed_pgid_guard", *_fixture_command(exit_code=0, sleep_seconds="2.0"))
    real_ps = shutil.which("ps")
    assert real_ps is not None
    stub_bin.mkdir()

    with _unrelated_control_process() as control:
        # The wrapper now appears to sit in a process group that is real and
        # live, led by an unrelated session leader.
        reused_pgid = _reused_pgid_stand_in(control, wrapper_pid=job.wrapper_pid)
        _write_executable(
            stub_bin / "ps",
            f"""#!/usr/bin/env bash
if [[ "$*" == "-p {job.wrapper_pid} -o pgid=" ]]; then
  printf '%s\\n' {reused_pgid}
  exit 0
fi
exec {real_ps} "$@"
""",
        )

        refused = _assert_stop_refused_without_signaling(
            _StopRefusalExpectation(
                job=job,
                expected_reason=(
                    f"wrapper PID {job.wrapper_pid} no longer leads recorded process group {job.wrapper_pid}"
                ),
            ),
            control=control,
            extra_env={"PATH": f"{stub_bin}{os.pathsep}{os.environ['PATH']}"},
        )
        assert f"observed PGID: {reused_pgid}" in refused.stderr
    _terminate_recorded_processes(job.job_dir)


def test_stop_terminates_owned_process_tree(tmp_path: Path) -> None:
    job_root = tmp_path / "jobs"
    job_name = "process_tree_stop"
    tree_dir = tmp_path / "tree"

    with _unrelated_control_process() as control, _reclaiming_test_owned_processes(job_root / job_name) as reclaim:
        job = _start_job(job_root, job_name, *_process_tree_fixture_command(tree_dir))
        owned_pids = _wait_for_process_tree(tree_dir)
        reclaim.track(*owned_pids.values())
        _assert_recorded_wrapper_pgid(job.job_dir, job.wrapper_pid)

        recorded_pgid = int((job.job_dir / "pgid").read_text(encoding="utf-8").strip())
        for level, pid in owned_pids.items():
            assert _observed_pgid(pid) == recorded_pgid, level
            assert int((tree_dir / f"{level}.pgid").read_text(encoding="utf-8").strip()) == recorded_pgid
        assert _observed_pgid(control.pid) != recorded_pgid

        stop = _run_runner(job.job_root, "stop", job.job_name)
        assert stop.returncode == 0, stop.stderr

        for pid in owned_pids.values():
            reclaim.confirm_exited(pid)
        _assert_control_is_running(control)

        status_payload = _status(job.job_root, job.job_name)
        assert status_payload["alive"] is False
        assert status_payload["exit_code"] == 143


def test_stop_and_status_are_idempotent_after_termination(tmp_path: Path) -> None:
    job = _start_job(tmp_path / "jobs", "idempotent_stop", *_fixture_command(exit_code=0, sleep_seconds="5.0"))
    exit_code_path = job.job_dir / "exit_code"

    with _unrelated_control_process() as control:
        try:
            stop = _run_runner(job.job_root, "stop", job.job_name)
            assert stop.returncode == 0, stop.stderr
            assert exit_code_path.read_text(encoding="utf-8").strip() == "143"

            _assert_stop_refused_without_signaling(
                _StopRefusalExpectation(
                    job=job,
                    expected_reason=f"wrapper PID {job.wrapper_pid} is no longer observable",
                    expect_wrapper_alive=False,
                ),
                control=control,
            )
            # The refusal returns before write_stop_receipt_once(), so the
            # receipt recorded by the first stop must survive untouched.
            assert exit_code_path.read_text(encoding="utf-8").strip() == "143"

            for _ in range(2):
                status_payload = _status(job.job_root, job.job_name)
                assert status_payload["alive"] is False
                assert status_payload["exit_code"] == 143
        finally:
            # The refusal above proved this wrapper PID is gone, so signalling
            # it directly could only reach whatever inherited the number. The
            # shared teardown owner signals a recorded PID only while it still
            # carries its recorded identity.
            _terminate_recorded_processes(job.job_dir)


def test_stop_after_normal_completion_preserves_receipt(tmp_path: Path) -> None:
    job = _start_job(tmp_path / "jobs", "completed_job_stop", *_fixture_command(exit_code=0, sleep_seconds="0.3"))
    exit_code_path = job.job_dir / "exit_code"

    wait = _run_runner(job.job_root, "wait", job.job_name, "--poll-seconds", "1", "--timeout-seconds", "5")
    assert wait.returncode == 0, wait.stderr
    # `wait` returns as soon as the receipt appears, but the wrapper can still be
    # observable for a moment afterwards; stopping then would legitimately
    # succeed. Wait out the wrapper so the refusal below is deterministic.
    _wait_for_pid_to_exit(job.wrapper_pid)

    with _unrelated_control_process() as control:
        _assert_stop_refused_without_signaling(
            _StopRefusalExpectation(
                job=job,
                expected_reason=f"wrapper PID {job.wrapper_pid} is no longer observable",
                expect_wrapper_alive=False,
            ),
            control=control,
        )
        # A fail-closed refusal must never overwrite a genuine completion
        # receipt with the stop receipt's 143.
        assert exit_code_path.read_text(encoding="utf-8").strip() == "0"
