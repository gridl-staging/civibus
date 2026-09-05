"""Environment and structural contracts for the detached runner test harness."""

from __future__ import annotations

import atexit
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from test_support.line_budget import oversized_modules
from tests.infra.detached_runner_helpers import (
    REPO_ROOT,
    SCRIPT_PATH,
    _BASHPID_PROBE,
    _bash_defines_bashpid,
    _runner_env,
    _supported_bash,
    _supported_bash_shim_directory,
    _write_executable,
)

_KNOWN_SOURCED_RUNNER_LIBRARIES = frozenset(
    {
        "detached_runner_job_state_lib.sh",
        "detached_runner_ownership_lib.sh",
        "detached_runner_launch_lib.sh",
    }
)
_RUNNER_SOURCE_LINE = re.compile(r'^source "\$\{script_dir\}/([^"]+)"$', re.MULTILINE)


def _runner_sourced_library_names() -> set[str]:
    return set(_RUNNER_SOURCE_LINE.findall(SCRIPT_PATH.read_text(encoding="utf-8")))


# The harness's own Python modules, matched rather than listed, so a module
# extracted out of an oversized one inherits the ceiling the moment it lands
# instead of when someone remembers to add it to a list here.
_HARNESS_MODULE_GLOBS = ("detached_runner*.py", "test_detached_runner*.py")


def _harness_module_paths() -> list[Path]:
    directory = Path(__file__).resolve().parent
    return sorted({path for glob in _HARNESS_MODULE_GLOBS for path in directory.glob(glob)})


def test_runner_environment_resolves_bash_to_an_interpreter_that_defines_bashpid(tmp_path: Path) -> None:
    """Prove the runner is handed a usable bash by name, not only by path.

    `run_wrapper` reads BASHPID, which bash only defines from 4.0 and macOS
    ships 3.2 as /bin/bash ahead of any newer install. The runner re-execs
    itself as plain `bash`, so pointing only the outer invocation at a
    supported interpreter still strands every launch on "did not become
    ready". The PATH-override case is asserted because the launcher-isolation
    tests replace PATH wholesale, dropping any prefix applied before the merge.
    """
    stripped_bin = tmp_path / "stripped_bin"
    stripped_bin.mkdir()
    job_root = tmp_path / "jobs"

    for env in (_runner_env(job_root), _runner_env(job_root, {"PATH": str(stripped_bin)})):
        resolved_bash = shutil.which("bash", path=env["PATH"])
        assert resolved_bash is not None, "runner PATH resolves no bash at all"
        assert os.path.realpath(resolved_bash) == os.path.realpath(_supported_bash())

    probe = subprocess.run(
        [_supported_bash(), "-c", _BASHPID_PROBE],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert probe.returncode == 0, probe.stderr
    assert probe.stdout.strip().isdigit(), "the resolved bash does not define BASHPID"


def test_bash_probe_answers_false_for_candidates_that_cannot_define_bashpid(tmp_path: Path) -> None:
    """Prove the probe skips an unusable candidate instead of raising on it.

    `_supported_bash()` walks every PATH entry and relies on this probe to
    reject whatever is not a BASHPID-defining interpreter. `os.access` grants
    X_OK to a directory as well, so a PATH entry holding a directory named
    `bash` reaches the probe; letting that OSError escape would abort every
    test in this harness rather than moving on to the next entry. The positive
    case is asserted alongside, because a probe that only ever said False would
    pass the rejection half while leaving the harness with no bash at all.
    """
    directory_candidate = tmp_path / "bash"
    directory_candidate.mkdir()
    assert os.access(directory_candidate, os.X_OK), "a directory is expected to read as executable"
    assert _bash_defines_bashpid(str(directory_candidate)) is False

    assert _bash_defines_bashpid(str(tmp_path / "absent_bash")) is False

    silent_candidate = tmp_path / "silent_bash"
    _write_executable(silent_candidate, "#!/usr/bin/env bash\nexit 0\n")
    assert _bash_defines_bashpid(str(silent_candidate)) is False

    assert _bash_defines_bashpid(_supported_bash()) is True


def test_supported_bash_shim_is_registered_for_process_exit_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    registrations: list[tuple[object, tuple[object, ...], dict[str, object]]] = []
    monkeypatch.setattr(
        atexit,
        "register",
        lambda function, *args, **kwargs: registrations.append((function, args, kwargs)),
    )
    _supported_bash_shim_directory.cache_clear()

    shim_directory = Path(_supported_bash_shim_directory())

    try:
        assert registrations == [(shutil.rmtree, (shim_directory,), {"ignore_errors": True})]
    finally:
        shutil.rmtree(shim_directory, ignore_errors=True)
        _supported_bash_shim_directory.cache_clear()


def test_runner_and_every_library_it_sources_stay_within_the_line_budget() -> None:
    """Hold the runner and its libraries to the repository's file-size ceiling.

    The set under budget is discovered from the runner's own `source` lines, so
    a library inherits the ceiling the moment the runner depends on it rather
    than when someone remembers to list it here. Asserting each discovered path
    exists keeps the guard fail-closed: a typo in a `source` line would
    otherwise shrink the budgeted set to a passing one.
    """
    sourced_names = _runner_sourced_library_names()
    budgeted_paths = [SCRIPT_PATH, *(SCRIPT_PATH.parent / name for name in sourced_names)]
    for path in budgeted_paths:
        assert path.is_file(), f"detached_runner.sh sources a path that does not exist: {path}"

    assert oversized_modules(budgeted_paths) == {}


def test_detached_runner_harness_modules_stay_within_the_line_budget() -> None:
    """Hold the harness's own Python modules to the repository's file-size ceiling.

    The guard above budgets what the runner sources; this one budgets what tests
    it, so a helper module that grows past the ceiling reds here rather than
    being noticed by a reviewer. Asserting that discovery still finds one module
    per glob keeps the guard fail-closed: a glob that stopped matching would
    otherwise shrink the budgeted set to a vacuously passing one.
    """
    harness_modules = _harness_module_paths()
    directory = Path(__file__).resolve().parent

    for anchor in ("detached_runner_helpers.py", Path(__file__).name):
        assert directory / anchor in harness_modules, f"harness module discovery no longer matches {anchor}"

    assert oversized_modules(harness_modules) == {}


def test_runner_sourced_library_discovery_is_fail_closed() -> None:
    assert _runner_sourced_library_names() == _KNOWN_SOURCED_RUNNER_LIBRARIES


def test_runner_shellcheck_directives_require_source_following_lint() -> None:
    runner_source = SCRIPT_PATH.read_text(encoding="utf-8")
    source_directives = [
        line
        for line in runner_source.splitlines()
        if line.startswith("# shellcheck source=infra/scripts/detached_runner_")
    ]

    assert len(source_directives) == len(_KNOWN_SOURCED_RUNNER_LIBRARIES)
    assert all("disable=SC1091" not in line for line in source_directives)


def test_runner_trap_callbacks_suppress_both_shellcheck_codes() -> None:
    runner_source = SCRIPT_PATH.read_text(encoding="utf-8")
    wrapper = re.search(r"^run_wrapper\(\) \{\n(.*?)^\}", runner_source, re.MULTILINE | re.DOTALL)
    assert wrapper is not None, "run_wrapper function is missing"
    wrapper_body = wrapper.group(1)

    for callback_name in ("write_cleanup_receipt_on_exit", "forward_signal"):
        callback = re.search(rf"^  {callback_name}\(\) \{{$", wrapper_body, re.MULTILINE)
        assert callback is not None, f"{callback_name} function is missing from run_wrapper"
        preceding_lines = wrapper_body[: callback.start()].splitlines()
        assert preceding_lines, f"{callback_name} has no adjacent ShellCheck directive"
        directive = re.fullmatch(
            r"  # shellcheck disable=(SC\d+(?:,SC\d+)*)(?:[ \t]+#.*)?",
            preceding_lines[-1],
        )
        assert directive is not None, f"{callback_name} has no adjacent function-scoped ShellCheck directive"
        suppressed_codes = set(directive.group(1).split(","))
        assert {"SC2317", "SC2329"} <= suppressed_codes, f"{callback_name}: {suppressed_codes}"


def test_runner_and_its_sourced_libraries_lint_clean_under_check_sourced() -> None:
    """Run the lint gate here so the flag that reaches the libraries lives in code.

    `-x` alone only makes sourced definitions visible while analysing the
    top-level file; shellcheck reports findings from inside a sourced file only
    under `--check-sourced`. A prose-only `-x` gate therefore leaves most of the
    runner's shell lines unlinted while reading as full coverage, so the command
    is executed by this test rather than quoted in a checklist.
    """
    shellcheck = shutil.which("shellcheck")
    assert shellcheck is not None, "shellcheck is required to lint the detached runner and its libraries"

    result = subprocess.run(
        [shellcheck, "-x", "--check-sourced", "-S", "style", str(SCRIPT_PATH)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout or result.stderr
