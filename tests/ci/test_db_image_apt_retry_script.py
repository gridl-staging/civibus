"""Behavioral contract for the database image's apt install owner.

`infra/db/install_postgres_extensions.sh` is the single owner of "install the
PostGIS and AGE extension packages into the Postgres base image". The Dockerfile
delegates to it so the retry behaviour can be executed and asserted here rather
than only read as text.

These tests EXECUTE the script against a stub `apt-get` on `PATH`. That matters:
the defect this script exists to prevent is a *transient* upstream failure that
a text assertion cannot distinguish from a working retry. Only a behavioural
test can tell "retried and recovered" apart from "ran once and gave up", and
only a behavioural test can prove the guard still fails when the failure is
permanent.

Anchored incident: 2026-08-05. Staging Integration run 30972647556 attempt 1
died 23 seconds in at `make db-up` because deb.debian.org served a truncated
`libkmlengine1_1.3.0-10_amd64.deb` ("File has unexpected size (20136 != 74428).
Mirror sync in progress?"). No civibus code participated. Attempt 2 re-ran the
identical commit and passed. That single transient failure was recorded as a
hard deploy blocker across four artifacts and stranded a fix for a 48-hour
production outage for roughly twelve hours.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALL_SCRIPT_PATH = REPO_ROOT / "infra/db/install_postgres_extensions.sh"
DOCKERFILE_PATH = REPO_ROOT / "infra/db/Dockerfile"

# The extension packages the image exists to provide. PostGIS backs the
# geometry work and AGE backs the legacy graph stack; dropping either silently
# would leave a database that starts fine and fails at query time.
REQUIRED_PACKAGES = (
    "postgresql-18-postgis-3",
    "postgresql-18-postgis-3-scripts",
    "postgresql-18-age",
)


def _write_stub_apt(directory: Path, *, fail_install_times: int, argv_log: Path) -> None:
    """Install a fake `apt-get` that fails `install` the first N times.

    The failure is modelled on the real one: a nonzero exit from the `install`
    verb while `update` itself succeeds. A counter file survives across the
    separate `apt-get` processes the script spawns, which is what lets a single
    stub express "transient for N attempts, then fine".
    """
    counter = directory / "install_attempts"
    counter.write_text("0", encoding="utf-8")

    stub = directory / "apt-get"
    stub.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                f'printf "%s\\n" "$*" >> {argv_log}',
                'if [[ "${1:-}" == "install" ]]; then',
                f'  attempts="$(cat {counter})"',
                "  attempts=$((attempts + 1))",
                f'  printf "%s" "$attempts" > {counter}',
                f"  if (( attempts <= {fail_install_times} )); then",
                '    echo "E: Failed to fetch ... File has unexpected size" >&2',
                "    exit 100",
                "  fi",
                "fi",
                "exit 0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)


def _run_script(stub_dir: Path) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    # Put the stub first so the script resolves it instead of any real apt-get,
    # and keep coreutils reachable for rm/sleep.
    environment["PATH"] = f"{stub_dir}:{environment.get('PATH', '')}"
    # Keep the test fast: the script must honour a configurable backoff rather
    # than hardcoding a sleep that makes its own contract untestable.
    environment["APT_RETRY_SLEEP_SECONDS"] = "0"
    # Redirect the index cleanup at a throwaway directory. Without this the
    # script would rm -rf the *host's* /var/lib/apt/lists on a Linux runner --
    # a test with a real side effect on the machine running it.
    lists_dir = stub_dir / "apt_lists"
    lists_dir.mkdir(exist_ok=True)
    environment["APT_LISTS_DIR"] = str(lists_dir)
    return subprocess.run(
        ["bash", str(INSTALL_SCRIPT_PATH)],
        capture_output=True,
        text=True,
        env=environment,
        check=False,
    )


def _install_invocations(argv_log: Path) -> list[str]:
    if not argv_log.is_file():
        return []
    return [line for line in argv_log.read_text(encoding="utf-8").splitlines() if line.startswith("install")]


def _argv_lines(argv_log: Path) -> list[str]:
    if not argv_log.is_file():
        return []
    return [line for line in argv_log.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_install_script_exists_and_is_executable_by_bash() -> None:
    assert INSTALL_SCRIPT_PATH.is_file(), "infra/db/install_postgres_extensions.sh must exist"


def test_clean_first_attempt_installs_once_and_succeeds(tmp_path: Path) -> None:
    """No retries when nothing fails — a retry loop must not add work."""
    argv_log = tmp_path / "argv.log"
    _write_stub_apt(tmp_path, fail_install_times=0, argv_log=argv_log)

    result = _run_script(tmp_path)

    assert result.returncode == 0, result.stderr
    assert len(_install_invocations(argv_log)) == 1, _argv_lines(argv_log)


def test_transient_mirror_failure_is_retried_and_recovers(tmp_path: Path) -> None:
    """The 2026-08-05 failure shape: two bad attempts, then a good one."""
    argv_log = tmp_path / "argv.log"
    _write_stub_apt(tmp_path, fail_install_times=2, argv_log=argv_log)

    result = _run_script(tmp_path)

    assert result.returncode == 0, result.stderr
    assert len(_install_invocations(argv_log)) == 3, _argv_lines(argv_log)


def test_each_retry_refreshes_the_package_index_first(tmp_path: Path) -> None:
    """`update` must precede every `install`.

    "Mirror sync in progress" means the cached index names a file the mirror
    cannot yet serve. Retrying the install against that same stale index just
    reproduces the failure, so the refresh is the load-bearing half of the
    retry and is asserted separately from the retry count.
    """
    argv_log = tmp_path / "argv.log"
    _write_stub_apt(tmp_path, fail_install_times=2, argv_log=argv_log)

    result = _run_script(tmp_path)

    assert result.returncode == 0, result.stderr
    verbs = [line.split()[0] for line in _argv_lines(argv_log)]
    installs = [index for index, verb in enumerate(verbs) if verb == "install"]
    assert installs, verbs
    for index in installs:
        assert "update" in verbs[:index], f"install at position {index} ran with no preceding update: {verbs}"
        # The nearest preceding verb must be the refresh for *this* attempt.
        assert verbs[index - 1] == "update", f"install at position {index} did not refresh first: {verbs}"


def test_persistent_failure_still_fails_the_build(tmp_path: Path) -> None:
    """The guard must remain able to fail.

    A retry loop that swallows a permanent breakage would turn a broken base
    image into a green build, which is strictly worse than the flake it
    replaces.
    """
    argv_log = tmp_path / "argv.log"
    _write_stub_apt(tmp_path, fail_install_times=99, argv_log=argv_log)

    result = _run_script(tmp_path)

    assert result.returncode != 0
    attempts = len(_install_invocations(argv_log))
    assert 1 < attempts <= 10, f"expected a bounded retry budget, got {attempts} attempts"


def test_every_required_extension_package_is_installed(tmp_path: Path) -> None:
    """Package set is asserted from the executed command, not from file text."""
    argv_log = tmp_path / "argv.log"
    _write_stub_apt(tmp_path, fail_install_times=0, argv_log=argv_log)

    result = _run_script(tmp_path)

    assert result.returncode == 0, result.stderr
    install_line = _install_invocations(argv_log)[0]
    for package in REQUIRED_PACKAGES:
        assert package in install_line, f"{package} missing from: {install_line}"
    assert "--no-install-recommends" in install_line, install_line


def test_dockerfile_delegates_to_the_install_script(tmp_path: Path) -> None:
    """The Dockerfile must route through the tested owner, not a second copy.

    Two apt invocations — one here and one inline — would mean the retry
    behaviour proven above governs only half the builds.
    """
    dockerfile_text = DOCKERFILE_PATH.read_text(encoding="utf-8")
    code = "\n".join(line for line in dockerfile_text.splitlines() if not line.lstrip().startswith("#"))

    assert "install_postgres_extensions.sh" in code, code
    assert "apt-get install" not in code, "Dockerfile must not carry a second, untested apt install path"
