"""Contract tests for the same-name `start` critical section of
infra/scripts/detached_runner.sh.

`run_start` clears and rewrites one job directory's pid/pgid/process_identity,
so two same-name starts that interleave that section leave the job named after
one wrapper and the other orphaned under the same name. The runner serializes
them with a per-job start lock; this module owns the proof and the exact
refusal the losing start prints.

These live beside rather than inside tests/infra/test_detached_runner.py only
because that module is already at the repository's file-size ceiling.
"""

from __future__ import annotations

import concurrent.futures
import os
import shutil
import shlex
import subprocess
import sys
from pathlib import Path

from tests.infra.detached_runner_helpers import (
    SCRIPT_PATH,
    _assert_recorded_wrapper_pgid,
    _fixture_command,
    _json_stdout,
    _observed_process_identity,
    _run_runner,
    _runner_path_without_session_launcher,
    _status,
    _stop_if_running,
    _terminate_exact_pid,
    _terminate_recorded_processes,
    _wait_for_file,
    _write_executable,
)

# The exact refusal the losing same-name start prints, pinned in full so the
# runner keeps one wording for the case instead of near-copies that can drift.
_CONCURRENT_START_REFUSAL = "another start for this job holds the start lock; wait for it to finish or retry"
# Holds the winning start inside the critical section long enough that both
# starts are provably in it at once. Orders of magnitude above the stagger
# between the two threads below, and well inside the runner's 5.0s readiness
# window, so the winner still adopts its wrapper normally.
_UNREADY_WRAPPER_SECONDS = 2.0


def _path_with_delayed_setsid(tmp_path: Path) -> str:
    """Prepend a `setsid` that stalls before isolating, widening the section."""
    stub_bin = tmp_path / "bin"
    stub_bin.mkdir()
    _write_executable(
        stub_bin / "setsid",
        f"""#!{sys.executable}
import os
import sys
import time

time.sleep({_UNREADY_WRAPPER_SECONDS})
os.setsid()
os.execvp(sys.argv[1], sys.argv[1:])
""",
    )
    return f"{stub_bin}{os.pathsep}{os.environ['PATH']}"


def _live_wrapper_pids(job_dir: Path) -> list[int]:
    """Return every live wrapper process that names `job_dir` on its command line.

    The wrapper is a re-exec of the runner with the job directory as an
    argument, so a second wrapper under one job name is directly observable —
    and that orphan is the concrete harm an interleaved start leaves behind.
    Re-observing each snapshot candidate excludes a process that exited between
    `ps` producing its row and this assertion consuming it; a persistent orphan
    still carries the exact marker on both observations.
    """
    listing = subprocess.run(
        ["ps", "-A", "-ww", "-o", "pid=,command="],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    marker = f"__run_wrapper {job_dir} "
    candidate_pids = [int(line.split(None, 1)[0]) for line in listing.stdout.splitlines() if marker in line]
    return sorted(pid for pid in candidate_pids if marker in _observed_process_identity(pid))


def test_concurrent_same_name_starts_adopt_exactly_one_wrapper(tmp_path: Path) -> None:
    job_root = tmp_path / "jobs"
    job_name = "racejob"
    job_dir = job_root / job_name
    extra_env = {
        "DETACHED_RUNNER_FORCE_PYTHON_SESSION": "0",
        "PATH": _path_with_delayed_setsid(tmp_path),
    }

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(
                _run_runner,
                job_root,
                "start",
                job_name,
                "--",
                # Long enough that the payload cannot exit on its own between
                # `start` returning and the assertions below; teardown stops it.
                "sleep",
                "30",
                extra_env=extra_env,
                timeout_seconds=30,
            )
            for _ in range(2)
        ]
        results = [future.result() for future in futures]

    adopted = [result for result in results if result.returncode == 0]
    refused = [result for result in results if result.returncode != 0]
    try:
        assert len(adopted) == 1, [result.stderr for result in results]
        assert [result.returncode for result in refused] == [3]
        assert _CONCURRENT_START_REFUSAL in refused[0].stderr

        adopted_pid = _json_stdout(adopted[0])["pid"]
        assert int((job_dir / "pid").read_text(encoding="utf-8").strip()) == adopted_pid
        assert (job_dir / "process_identity").read_text(encoding="utf-8").strip() == _observed_process_identity(
            adopted_pid
        )
        _assert_recorded_wrapper_pgid(job_dir, adopted_pid)
        assert _status(job_root, job_name)["alive"] is True
        assert _live_wrapper_pids(job_dir) == [adopted_pid]
    finally:
        _stop_if_running(job_root, job_name)
        for result in adopted:
            _terminate_exact_pid(_json_stdout(result)["pid"])
        _terminate_recorded_processes(job_dir)


def _plant_start_lock(job_dir: Path, *, starter_pid: str | None = None, starter_identity: str = "") -> Path:
    """Create a start lock for `job_dir` recording `starter_pid`, and return it.

    Omitting the starter models an incomplete lock whose in-lock metadata was
    interrupted before publication.
    """
    lock_path = job_dir / "start.lock"
    lock_path.mkdir(parents=True)
    if starter_pid is not None:
        (lock_path / "starter_pid").write_text(f"{starter_pid}\n", encoding="utf-8")
        (lock_path / "starter_identity").write_text(f"{starter_identity}\n", encoding="utf-8")
    return lock_path


def _plant_start_lock_claim(job_dir: Path, starter_pid: int, starter_identity: str) -> Path:
    claim_path = job_dir / f"start.lock.claim.{starter_pid}"
    claim_path.mkdir()
    (claim_path / "starter_pid").write_text(f"{starter_pid}\n", encoding="utf-8")
    (claim_path / "starter_identity").write_text(f"{starter_identity}\n", encoding="utf-8")
    return claim_path


def _reaped_pid() -> int:
    """Return the PID of a process that has exited and been reaped.

    Both non-matching identity verdicts reclaim the lock, so this stays
    deterministic even in the rare case where the number is reused before the
    assertion runs: whatever inherits it is not running the recorded identity.
    """
    finished = subprocess.Popen([sys.executable, "-c", ""])
    finished.wait(timeout=10)
    return finished.pid


def _path_with_paused_start_lock_chmod(tmp_path: Path, lock_path: Path, marker: Path) -> str:
    """Pause immediately after `mkdir start.lock` creates an incomplete claim."""
    real_chmod = shutil.which("chmod")
    assert real_chmod is not None, "chmod is required to run the runner"
    stub_bin = tmp_path / "paused_lock_bin"
    stub_bin.mkdir()
    _write_executable(
        stub_bin / "chmod",
        f"""#!{sys.executable}
import os
import sys
import time

if sys.argv[-1] == {str(lock_path)!r}:
    with open({str(marker)!r}, "w", encoding="utf-8") as handle:
        handle.write(f"{{os.getpid()}}\\n")
    time.sleep(30)
os.execv({real_chmod!r}, [{real_chmod!r}, *sys.argv[1:]])
""",
    )
    return f"{stub_bin}{os.pathsep}{os.environ['PATH']}"


def _path_with_paused_reclaim_lock_chmod(tmp_path: Path, reclaim_path: Path, marker: Path) -> str:
    """Pause the first reclaimer after creating its mutex but before publication."""
    real_chmod = shutil.which("chmod")
    assert real_chmod is not None, "chmod is required to run the runner"
    stub_bin = tmp_path / "paused_reclaim_bin"
    stub_bin.mkdir()
    _write_executable(
        stub_bin / "chmod",
        f"""#!{sys.executable}
import os
import sys
import time

if sys.argv[-1] == {str(reclaim_path)!r} and not os.path.exists({str(marker)!r}):
    with open({str(marker)!r}, "x", encoding="utf-8") as handle:
        handle.write(f"{{os.getpid()}}\\n")
    time.sleep(30)
os.execv({real_chmod!r}, [{real_chmod!r}, *sys.argv[1:]])
""",
    )
    return f"{stub_bin}{os.pathsep}{os.environ['PATH']}"


def _run_with_runner_libraries(job_dir: Path, body: str) -> subprocess.CompletedProcess[str]:
    """Run `body` with the runner's job-state and ownership libraries sourced.

    The lock's race-resolution rules only run when two starts collide inside
    them, which no test can schedule. Calling the shell functions directly is
    what makes those branches provable rather than merely reasoned about.
    """
    library_dir = SCRIPT_PATH.parent
    script = "\n".join(
        [
            "set -euo pipefail",
            f"job_root={shlex.quote(str(job_dir.parent))}",
            f"source {shlex.quote(str(library_dir / 'detached_runner_job_state_lib.sh'))}",
            f"source {shlex.quote(str(library_dir / 'detached_runner_ownership_lib.sh'))}",
            body,
        ]
    )
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False, timeout=10)


def test_start_refuses_while_the_recorded_starter_is_alive(tmp_path: Path) -> None:
    job_root = tmp_path / "jobs"
    job_name = "live_starter_lock"
    job_dir = job_root / job_name
    lock_path = _plant_start_lock(
        job_dir,
        starter_pid=str(os.getpid()),
        starter_identity=_observed_process_identity(os.getpid()),
    )

    refused = _run_runner(job_root, "start", job_name, "--", *_fixture_command(exit_code=0))

    assert refused.returncode == 3
    assert _CONCURRENT_START_REFUSAL in refused.stderr
    # The refused start holds nothing, so it must neither release the holder's
    # lock nor adopt any metadata of its own.
    assert lock_path.is_dir()
    assert not (job_dir / "pid").exists()
    assert not (job_dir / "cmd").exists()


def test_start_refuses_an_incomplete_lock_while_its_claimant_is_alive(tmp_path: Path) -> None:
    job_root = tmp_path / "jobs"
    job_name = "unrecorded_starter_lock"
    job_dir = job_root / job_name
    lock_path = _plant_start_lock(job_dir)
    claim_path = _plant_start_lock_claim(job_dir, os.getpid(), _observed_process_identity(os.getpid()))

    refused = _run_runner(job_root, "start", job_name, "--", *_fixture_command(exit_code=0))

    assert refused.returncode == 3
    assert _CONCURRENT_START_REFUSAL in refused.stderr
    assert lock_path.is_dir()
    assert claim_path.is_dir()
    assert not (job_dir / "pid").exists()


def test_start_reclaims_a_start_lock_whose_starter_is_gone(tmp_path: Path) -> None:
    """A lock nobody could ever clear would wedge the job name permanently."""
    job_root = tmp_path / "jobs"
    job_name = "dead_starter_lock"
    job_dir = job_root / job_name
    lock_path = _plant_start_lock(
        job_dir,
        starter_pid=str(_reaped_pid()),
        starter_identity="detached_runner.sh start dead_starter_lock",
    )

    start = _run_runner(job_root, "start", job_name, "--", *_fixture_command(exit_code=0))

    try:
        assert start.returncode == 0, start.stderr
        # Released on the way out, so the next start finds the name free.
        assert not lock_path.exists()
    finally:
        _stop_if_running(job_root, job_name)
        _terminate_recorded_processes(job_dir)


def test_start_reclaims_an_incomplete_claim_after_its_starter_is_killed(tmp_path: Path) -> None:
    job_root = tmp_path / "jobs"
    job_name = "killed_incomplete_starter"
    job_dir = job_root / job_name
    lock_path = job_dir / "start.lock"
    paused_marker = tmp_path / "starter_paused"
    env = {
        **os.environ,
        "DETACHED_RUNNER_ROOT": str(job_root),
        "PATH": _path_with_paused_start_lock_chmod(tmp_path, lock_path, paused_marker),
    }
    starter = subprocess.Popen(
        ["bash", str(SCRIPT_PATH), "start", job_name, "--", "sleep", "30"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    paused_chmod_pid: int | None = None
    try:
        paused_chmod_pid = int(_wait_for_file(paused_marker))
        assert lock_path.is_dir()
        assert not (lock_path / "starter_pid").exists()
        claim_paths = list(job_dir.glob("start.lock.claim.*"))
        assert len(claim_paths) == 1
        assert (claim_paths[0] / "starter_pid").read_text(encoding="utf-8").strip() == str(starter.pid)
    finally:
        if starter.poll() is None:
            starter.kill()
        if paused_chmod_pid is not None:
            _terminate_exact_pid(paused_chmod_pid)
        starter.communicate(timeout=10)

    replacement = _run_runner(job_root, "start", job_name, "--", *_fixture_command(exit_code=0))

    try:
        assert replacement.returncode == 0, replacement.stderr
        assert not lock_path.exists()
    finally:
        _stop_if_running(job_root, job_name)
        _terminate_recorded_processes(job_dir)


def test_successful_start_releases_the_lock_it_claimed(tmp_path: Path) -> None:
    job_root = tmp_path / "jobs"
    job_name = "released_lock"
    job_dir = job_root / job_name

    start = _run_runner(job_root, "start", job_name, "--", *_fixture_command(exit_code=0))

    try:
        assert start.returncode == 0, start.stderr
        assert not (job_dir / "start.lock").exists()
    finally:
        _stop_if_running(job_root, job_name)
        _terminate_recorded_processes(job_dir)


def test_failed_start_releases_the_lock_before_exiting(tmp_path: Path) -> None:
    """Every mid-section exit must free the job name; one that did not would wedge it.

    The launcher refusal is the cheapest of the section's failure exits to
    reach deterministically, and it fails from the same position under the lock
    as the adoption refusals that follow it.
    """
    job_root = tmp_path / "jobs"
    job_name = "failed_start_lock"
    job_dir = job_root / job_name
    stub_bin = tmp_path / "bin"
    stub_bin.mkdir()

    failed = _run_runner(
        job_root,
        "start",
        job_name,
        "--",
        "sleep",
        "30",
        extra_env={
            "DETACHED_RUNNER_FORCE_PYTHON_SESSION": "0",
            "PATH": _runner_path_without_session_launcher(stub_bin),
        },
    )

    assert failed.returncode == 1
    assert "no session-isolating launcher is available" in failed.stderr
    assert not (job_dir / "start.lock").exists()


def test_discarding_a_start_lock_clears_only_the_starter_it_names(tmp_path: Path) -> None:
    """The reclaim carries the lock aside, so it must put back one it misjudged.

    A claimant that cannot prove its own process identity must retain its
    external claim so another starter cannot misclassify the live lock as an
    abandoned incomplete publication.

    Two starters judging the same dead holder both reach the discard; whichever
    loses the rename must leave the winner's fresh lock exactly as it found it,
    or the reclaim would reintroduce the interleaving the lock prevents.
    """
    job_dir = tmp_path / "jobs" / "discard_job"
    job_dir.mkdir(parents=True)
    quoted_job_dir = shlex.quote(str(job_dir))

    unidentifiable = _run_with_runner_libraries(
        job_dir,
        f"""observed_process_identity() {{ printf '\\n'; }}
if acquire_start_lock {quoted_job_dir} $$; then echo acquired; else echo refused; fi
collect_start_lock_claim_paths {quoted_job_dir}
printf 'identity=<%s>\\n' "$(start_lock_starter_identity {quoted_job_dir})"
printf 'claim_count=%s\\n' "${{#START_LOCK_CLAIM_PATHS[@]}}"
release_start_lock
if [[ -e {quoted_job_dir}/start.lock ]]; then echo released=no; else echo released=yes; fi""",
    )

    assert unidentifiable.returncode == 0, unidentifiable.stderr
    assert unidentifiable.stdout.splitlines() == [
        "acquired",
        "identity=<>",
        "claim_count=1",
        "released=yes",
    ]

    misjudged = _run_with_runner_libraries(
        job_dir,
        f"""claim_start_lock {quoted_job_dir} 4242 'fresh starter identity'
if discard_start_lock_held_by {quoted_job_dir} 999999; then echo discarded; else echo refused; fi""",
    )

    assert misjudged.returncode == 0, misjudged.stderr
    assert misjudged.stdout.split() == ["refused"]
    lock_path = job_dir / "start.lock"
    assert (lock_path / "starter_pid").read_text(encoding="utf-8").strip() == "4242"
    assert (lock_path / "starter_identity").read_text(encoding="utf-8").strip() == "fresh starter identity"
    assert list(job_dir.glob("start.lock.detached.*")) == []

    matched = _run_with_runner_libraries(
        job_dir,
        f"""if discard_start_lock_held_by {quoted_job_dir} 4242; then echo discarded; else echo refused; fi""",
    )

    assert matched.returncode == 0, matched.stderr
    assert matched.stdout.split() == ["discarded"]
    assert not lock_path.exists()
    assert list(job_dir.glob("start.lock.detached.*")) == []


def test_reclaim_mutex_blocks_a_second_reclaimer_from_displacing_the_lock(tmp_path: Path) -> None:
    """A reclaimer must not create a vacancy while another stale reclaim runs."""
    job_dir = tmp_path / "jobs" / "serialized_reclaim"
    job_dir.mkdir(parents=True)
    stale_pid = _reaped_pid()
    _plant_start_lock(
        job_dir,
        starter_pid=str(stale_pid),
        starter_identity="detached_runner.sh start serialized_reclaim",
    )
    quoted_job_dir = shlex.quote(str(job_dir))

    refused = _run_with_runner_libraries(
        job_dir,
        f"""claim_start_lock_reclaim {quoted_job_dir} $$ "$(observed_process_identity $$)"
if acquire_start_lock {quoted_job_dir} $$ "$(observed_process_identity $$)"; then echo acquired; else echo refused; fi
if claim_start_lock {quoted_job_dir} 4242 'third starter identity'; then echo third-acquired; else echo third-refused; fi
detached_count=0
for detached_path in {quoted_job_dir}/start.lock.detached.*; do
  [[ -e "${{detached_path}}" || -L "${{detached_path}}" ]] || continue
  detached_count=$((detached_count + 1))
done
printf 'detached_count=%s\\n' "${{detached_count}}"
printf 'holder=%s\\n' "$(start_lock_starter_pid {quoted_job_dir})"
release_start_lock_reclaim""",
    )

    assert refused.returncode == 0, refused.stderr
    assert refused.stdout.splitlines() == [
        "refused",
        "third-refused",
        "detached_count=0",
        f"holder={stale_pid}",
    ]

    acquired = _run_with_runner_libraries(
        job_dir,
        f"""if acquire_start_lock {quoted_job_dir} $$ "$(observed_process_identity $$)"; then echo acquired; else echo refused; fi
printf 'holder=%s\\n' "$(start_lock_starter_pid {quoted_job_dir})"
release_start_lock""",
    )

    assert acquired.returncode == 0, acquired.stderr
    assert acquired.stdout.splitlines()[0] == "acquired"
    assert acquired.stdout.splitlines()[1].startswith("holder=")
    assert acquired.stdout.splitlines()[1] != f"holder={stale_pid}"
    assert not (job_dir / "start.lock").exists()
    assert list(job_dir.glob("start.lock.detached.*")) == []


def test_start_recovers_after_a_reclaim_mutex_holder_is_killed(tmp_path: Path) -> None:
    """A killed reclaimer must not permanently wedge the same job name."""
    job_root = tmp_path / "jobs"
    job_name = "killed_reclaimer"
    job_dir = job_root / job_name
    reclaim_path = job_dir / "start.lock.reclaim"
    paused_marker = tmp_path / "reclaimer_paused"
    stale_pid = _reaped_pid()
    _plant_start_lock(
        job_dir,
        starter_pid=str(stale_pid),
        starter_identity="detached_runner.sh start killed_reclaimer",
    )
    env = {
        **os.environ,
        "DETACHED_RUNNER_ROOT": str(job_root),
        "PATH": _path_with_paused_reclaim_lock_chmod(tmp_path, reclaim_path, paused_marker),
    }
    reclaimer = subprocess.Popen(
        ["bash", str(SCRIPT_PATH), "start", job_name, "--", "sleep", "30"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    paused_chmod_pid: int | None = None
    try:
        paused_chmod_pid = int(_wait_for_file(paused_marker))
        assert reclaim_path.is_dir()
        reclaimer.kill()
        _terminate_exact_pid(paused_chmod_pid)
        reclaimer.communicate(timeout=10)
    finally:
        if reclaimer.poll() is None:
            reclaimer.kill()
        if paused_chmod_pid is not None:
            _terminate_exact_pid(paused_chmod_pid)

    replacement = _run_runner(
        job_root,
        "start",
        job_name,
        "--",
        "sleep",
        "30",
        extra_env={"PATH": env["PATH"]},
    )

    try:
        assert replacement.returncode == 0, replacement.stderr
        adopted_pid = _json_stdout(replacement)["pid"]
        for _ in range(20):
            live_wrapper_pids = _live_wrapper_pids(job_dir)
            if live_wrapper_pids == [adopted_pid]:
                break
            subprocess.run(["sleep", "0.05"], check=True, timeout=1)
        assert live_wrapper_pids == [adopted_pid]
        assert not reclaim_path.exists()
    finally:
        _stop_if_running(job_root, job_name)
        _terminate_recorded_processes(job_dir)


def test_reclaim_mutex_release_does_not_delete_another_owners_mutex(tmp_path: Path) -> None:
    """A stale EXIT trap cannot release a replacement reclaimer's mutex.

    An identity-less but live pre-claim must also block reclaim rather than let
    a contender discard its incomplete lock.
    """
    job_dir = tmp_path / "jobs" / "reclaim_release_ownership"
    job_dir.mkdir(parents=True)
    quoted_job_dir = shlex.quote(str(job_dir))

    incomplete_lock = _plant_start_lock(job_dir)
    live_blank_claim = _plant_start_lock_claim(job_dir, os.getpid(), "")
    refused = _run_with_runner_libraries(
        job_dir,
        f"""if acquire_start_lock {quoted_job_dir} $$; then echo acquired; else echo refused; fi""",
    )

    assert refused.returncode == 0, refused.stderr
    assert refused.stdout.splitlines() == ["refused"]
    assert incomplete_lock.is_dir()
    assert live_blank_claim.is_dir()

    released = _run_with_runner_libraries(
        job_dir,
        f"""claim_start_lock_reclaim {quoted_job_dir} 555 'live reclaim owner identity'
HELD_START_LOCK_RECLAIM_STARTER_PID=999
HELD_START_LOCK_RECLAIM_STARTER_IDENTITY='different reclaim owner identity'
release_start_lock_reclaim
printf 'holder=%s\\n' "$(start_lock_reclaim_starter_pid {quoted_job_dir})"
printf 'identity=%s\\n' "$(start_lock_reclaim_starter_identity {quoted_job_dir})"
""",
    )

    assert released.returncode == 0, released.stderr
    assert released.stdout.splitlines() == ["holder=555", "identity=live reclaim owner identity"]
    reclaim_path = job_dir / "start.lock.reclaim"
    assert (reclaim_path / "starter_pid").read_text(encoding="utf-8").strip() == "555"
    assert (reclaim_path / "starter_identity").read_text(encoding="utf-8").strip() == "live reclaim owner identity"


def test_release_does_not_delete_a_lock_another_starter_now_holds(tmp_path: Path) -> None:
    """Release is keyed to the starter identity, not just a remembered path."""
    job_dir = tmp_path / "jobs" / "release_ownership"
    job_dir.mkdir(parents=True)
    quoted_job_dir = shlex.quote(str(job_dir))

    released = _run_with_runner_libraries(
        job_dir,
        f"""claim_start_lock {quoted_job_dir} 555 'live holder identity'
HELD_START_LOCK_STARTER_PID=999
HELD_START_LOCK_STARTER_IDENTITY='different starter identity'
release_start_lock
printf 'holder=%s\\n' "$(start_lock_starter_pid {quoted_job_dir})"
printf 'identity=%s\\n' "$(start_lock_starter_identity {quoted_job_dir})"
release_start_lock""",
    )

    assert released.returncode == 0, released.stderr
    assert released.stdout.splitlines() == ["holder=555", "identity=live holder identity"]
    lock_path = job_dir / "start.lock"
    assert (lock_path / "starter_pid").read_text(encoding="utf-8").strip() == "555"
    assert (lock_path / "starter_identity").read_text(encoding="utf-8").strip() == "live holder identity"
