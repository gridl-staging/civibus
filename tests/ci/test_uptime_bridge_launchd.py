"""Rendered-plist execution contract for the uptime-bridge launchd job.

A launchd agent does not inherit an interactive shell's PATH, so the installed
job must carry an explicit search path or the scheduled bridge fails
command-not-found on bare ``gh`` / ``bd`` before reconciling any incident. These
tests drive the same rendering seam the installer uses and prove the rendered
job resolves both tools with no interactive shell environment.

The job also binds one Python interpreter. macOS ships an interpreter below the
repository's supported floor and puts it first on many PATHs, so these tests
additionally prove the installer selects a supported interpreter and fails
closed instead of rendering a job that cannot run.
"""

from __future__ import annotations

import importlib
import json
import plistlib
import shlex
import shutil
import stat
import subprocess
import sys
import tomllib
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.dev_repo_only(
    private_asset=(
        "scripts/uptime_bridge.plist.template, scripts/install_uptime_bridge_launchd.sh, "
        "and scripts/uptime_bridge_launchd.py"
    ),
    owner="uptime bridge launchd contract",
)

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_PATH = REPO_ROOT / "scripts" / "uptime_bridge.plist.template"
INSTALLER_PATH = REPO_ROOT / "scripts" / "install_uptime_bridge_launchd.sh"
INSTALLED_PLIST_RELATIVE_PATH = Path("Library/LaunchAgents/com.civibus.uptime-bridge.plist")
DEPLOYED_BRIDGE_RELATIVE_PATH = Path(".civibus/uptime_incident_bridge.py")

# System directories the installer needs for mkdir/id while its PATH is
# otherwise replaced by the stub directory under test.
SYSTEM_PATH_ENTRIES = ("/usr/bin", "/bin")


def _load_launchd_renderer() -> ModuleType:
    return importlib.import_module("scripts.uptime_bridge_launchd")


def _make_fake_executable(directory: Path, name: str, body: str = "#!/bin/sh\nexit 0\n") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    tool = directory / name
    tool.write_text(body, encoding="utf-8")
    tool.chmod(tool.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return tool


def _recording_shim(exit_code: int) -> str:
    """Shell shim body that appends its arguments to the stub log, then exits."""
    return f'#!/bin/sh\nprintf \'%s\\n\' "$*" >> "$UPTIME_BRIDGE_STUB_LOG"\nexit {exit_code}\n'


def _beads_shim(ledger_path: Path) -> str:
    where_payload = shlex.quote(json.dumps({"path": str(ledger_path)}))
    return (
        "#!/bin/sh\n"
        'if [ "$1" = "where" ] && [ "$2" = "--json" ]; then\n'
        f"  printf '%s\\n' {where_payload}\n"
        "  exit 0\n"
        "fi\n"
        "exit 0\n"
    )


def _cwd_reporting_beads_shim() -> str:
    """bd stub that reports the ledger of whatever directory it is invoked from.

    ``bd where`` locates the ledger relative to its own working directory, so this
    stub proves which checkout the installer anchored discovery to: the rendered
    ``WorkingDirectory`` reflects the directory bd was actually run from, not the
    installer's caller cwd.
    """
    return (
        "#!/bin/sh\n"
        'if [ "$1" = "where" ] && [ "$2" = "--json" ]; then\n'
        '  printf \'{"path": "%s/.beads"}\\n\' "$(pwd -P)"\n'
        "  exit 0\n"
        "fi\n"
        "exit 0\n"
    )


def _installer_environment(stub_bin: Path | str, home: Path) -> dict[str, str]:
    return {
        "PATH": ":".join((str(stub_bin), *SYSTEM_PATH_ENTRIES)),
        "HOME": str(home),
        "UPTIME_BRIDGE_STUB_LOG": str(home / "stub.log"),
    }


def _run_installer(
    stub_bin: Path | str,
    home: Path,
    *,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/bash", str(INSTALLER_PATH)],
        env=_installer_environment(stub_bin, home),
        cwd=None if cwd is None else str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )


def _prepare_successful_installer(
    tmp_path: Path,
    *,
    supported_python_name: str = "python3",
) -> tuple[Path, Path, Path]:
    home = tmp_path / "home"
    home.mkdir()
    ledger_root = tmp_path / "durable_checkout"
    ledger_path = ledger_root / ".beads"
    ledger_path.mkdir(parents=True)
    stub_bin = tmp_path / "bin"
    if supported_python_name != "python3":
        _make_fake_executable(stub_bin, "python3", _recording_shim(exit_code=1))
    _make_fake_executable(stub_bin, supported_python_name, f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    _make_fake_executable(stub_bin, "gh")
    _make_fake_executable(stub_bin, "bd", _beads_shim(ledger_path))
    _make_fake_executable(stub_bin, "launchctl", _recording_shim(exit_code=0))
    return home, ledger_root, stub_bin


def _version_below_minimum() -> tuple[int, int]:
    major, minor = _load_launchd_renderer().MINIMUM_PYTHON_VERSION
    return (major, minor - 1)


def _render_with_tools(tmp_path: Path, tool_paths: dict[str, str]) -> str:
    launchd_renderer = _load_launchd_renderer()
    directories = launchd_renderer.resolve_tool_directories(tool_lookup=lambda tool: tool_paths[tool])
    search_path = launchd_renderer.build_launch_path(directories)
    return launchd_renderer.render_plist(
        TEMPLATE_PATH.read_text(encoding="utf-8"),
        {
            "__REPO_ROOT__": str(REPO_ROOT),
            "__BRIDGE_SCRIPT__": str(REPO_ROOT / "scripts" / "uptime_incident_bridge.py"),
            "__PYTHON_EXECUTABLE__": "/usr/bin/python3",
            "__LOG_DIRECTORY__": str(tmp_path / "logs"),
            "__SEARCH_PATH__": search_path,
        },
    )


def test_rendered_plist_environment_path_resolves_gh_and_bd(tmp_path: Path) -> None:
    gh_dir = tmp_path / "gh-home" / "bin"
    bd_dir = tmp_path / "bd-home" / "bin"
    gh_path = _make_fake_executable(gh_dir, "gh")
    bd_path = _make_fake_executable(bd_dir, "bd")

    rendered = _render_with_tools(tmp_path, {"gh": str(gh_path), "bd": str(bd_path)})

    parsed = plistlib.loads(rendered.encode("utf-8"))
    rendered_path = parsed["EnvironmentVariables"]["PATH"]
    assert str(gh_dir) in rendered_path.split(":")
    assert str(bd_dir) in rendered_path.split(":")

    # Model launchd/execvp resolution: no shell, only the rendered PATH. Both
    # tools must resolve to the rendered directories and be executable there.
    for tool, tool_dir in (("gh", gh_dir), ("bd", bd_dir)):
        resolved = shutil.which(tool, path=rendered_path)
        assert resolved is not None, f"{tool} did not resolve from the rendered launchd PATH"
        assert Path(resolved).parent == tool_dir
        completed = subprocess.run([resolved], env={"PATH": rendered_path}, check=False)
        assert completed.returncode == 0


def test_resolve_tool_directories_fails_closed_on_missing_tool() -> None:
    launchd_renderer = _load_launchd_renderer()
    with pytest.raises(LookupError):
        launchd_renderer.resolve_tool_directories(tool_lookup=lambda tool: None)


def test_render_plist_fails_closed_on_unresolved_placeholder() -> None:
    launchd_renderer = _load_launchd_renderer()
    with pytest.raises(ValueError):
        launchd_renderer.render_plist("<string>__SEARCH_PATH__</string>", {})


def test_minimum_python_version_matches_pyproject_requires_python() -> None:
    launchd_renderer = _load_launchd_renderer()
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    requires_python = pyproject["project"]["requires-python"]

    assert requires_python.startswith(">="), requires_python
    declared_floor = tuple(int(part) for part in requires_python.removeprefix(">=").strip().split("."))
    assert launchd_renderer.MINIMUM_PYTHON_VERSION == declared_floor


def test_probe_interpreter_version_reads_the_named_executables_version(tmp_path: Path) -> None:
    launchd_renderer = _load_launchd_renderer()
    shim = _make_fake_executable(tmp_path / "bin", "python3", '#!/bin/sh\necho "3 9"\n')

    assert launchd_renderer.probe_interpreter_version(str(shim)) == (3, 9)


def test_probe_interpreter_version_fails_closed_when_the_executable_errors(tmp_path: Path) -> None:
    launchd_renderer = _load_launchd_renderer()
    shim = _make_fake_executable(tmp_path / "bin", "python3", "#!/bin/sh\nexit 3\n")

    with pytest.raises(ValueError):
        launchd_renderer.probe_interpreter_version(str(shim))


def test_require_supported_interpreter_rejects_a_version_below_the_floor() -> None:
    launchd_renderer = _load_launchd_renderer()

    with pytest.raises(ValueError):
        launchd_renderer.require_supported_interpreter(
            "/usr/bin/python3",
            version_probe=lambda _: _version_below_minimum(),
        )


def test_require_supported_interpreter_accepts_the_floor_version() -> None:
    launchd_renderer = _load_launchd_renderer()

    launchd_renderer.require_supported_interpreter(
        "/usr/bin/python3",
        version_probe=lambda _: launchd_renderer.MINIMUM_PYTHON_VERSION,
    )


def test_check_interpreter_mode_rejects_a_running_interpreter_below_the_floor() -> None:
    launchd_renderer = _load_launchd_renderer()

    assert launchd_renderer.main(["--check-interpreter"], running_version=_version_below_minimum()) == 1


def test_check_interpreter_mode_accepts_a_supported_running_interpreter() -> None:
    launchd_renderer = _load_launchd_renderer()

    exit_code = launchd_renderer.main(
        ["--check-interpreter"],
        running_version=launchd_renderer.MINIMUM_PYTHON_VERSION,
    )

    assert exit_code == 0


def test_render_and_install_fails_closed_before_writing_an_unsupported_interpreters_plist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    launchd_renderer = _load_launchd_renderer()
    monkeypatch.setattr(launchd_renderer, "probe_interpreter_version", lambda _: _version_below_minimum())
    installed_path = tmp_path / "com.civibus.uptime-bridge.plist"

    with pytest.raises(ValueError):
        launchd_renderer.render_and_install(
            template_path=str(TEMPLATE_PATH),
            installed_path=str(installed_path),
            bridge_source_path=str(REPO_ROOT / "scripts" / "uptime_incident_bridge.py"),
            deployed_bridge_path=str(tmp_path / "uptime_incident_bridge.py"),
            python_executable="/usr/bin/python3",
            log_directory=str(tmp_path / "logs"),
        )

    assert not installed_path.exists()


def test_installer_fails_closed_when_no_candidate_interpreter_is_supported(tmp_path: Path) -> None:
    launchd_renderer = _load_launchd_renderer()
    home = tmp_path / "home"
    home.mkdir()
    stub_bin = tmp_path / "bin"
    _make_fake_executable(stub_bin, "python3", _recording_shim(exit_code=1))

    completed = _run_installer(stub_bin, home)

    assert completed.returncode != 0
    assert "interpreter" in completed.stderr
    assert not (home / INSTALLED_PLIST_RELATIVE_PATH).exists()
    # The installer must actually ask each candidate to judge itself rather than
    # trusting whichever python3 happens to sit first on PATH.
    probe_log = (home / "stub.log").read_text(encoding="utf-8")
    assert launchd_renderer.CHECK_INTERPRETER_FLAG in probe_log


def test_installer_renders_and_loads_the_job_with_a_supported_interpreter(tmp_path: Path) -> None:
    home, ledger_root, stub_bin = _prepare_successful_installer(tmp_path)

    completed = _run_installer(stub_bin, home)

    assert completed.returncode == 0, completed.stderr
    parsed = plistlib.loads((home / INSTALLED_PLIST_RELATIVE_PATH).read_bytes())
    assert parsed["ProgramArguments"] == [
        str(stub_bin / "python3"),
        str(home / DEPLOYED_BRIDGE_RELATIVE_PATH),
    ]
    assert parsed["WorkingDirectory"] == str(ledger_root)
    assert str(stub_bin.resolve()) in parsed["EnvironmentVariables"]["PATH"].split(":")
    assert "bootstrap" in (home / "stub.log").read_text(encoding="utf-8")


def test_installer_deploys_bridge_outside_the_source_worktree_and_uses_canonical_ledger_root(
    tmp_path: Path,
) -> None:
    home, ledger_root, stub_bin = _prepare_successful_installer(tmp_path)

    completed = _run_installer(stub_bin, home)

    assert completed.returncode == 0, completed.stderr
    deployed_bridge = home / DEPLOYED_BRIDGE_RELATIVE_PATH
    assert deployed_bridge.read_bytes() == (REPO_ROOT / "scripts" / "uptime_incident_bridge.py").read_bytes()
    parsed = plistlib.loads((home / INSTALLED_PLIST_RELATIVE_PATH).read_bytes())
    assert parsed["ProgramArguments"] == [str(stub_bin / "python3"), str(deployed_bridge)]
    assert parsed["WorkingDirectory"] == str(ledger_root)
    assert str(REPO_ROOT) not in parsed["ProgramArguments"]


def test_installer_discovers_a_newer_supported_versioned_interpreter(tmp_path: Path) -> None:
    home, _, stub_bin = _prepare_successful_installer(tmp_path, supported_python_name="python3.15")

    completed = _run_installer(stub_bin, home)

    assert completed.returncode == 0, completed.stderr
    parsed = plistlib.loads((home / INSTALLED_PLIST_RELATIVE_PATH).read_bytes())
    assert parsed["ProgramArguments"][0] == str(stub_bin / "python3.15")


def test_installer_renders_an_absolute_interpreter_from_a_relative_path_entry(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    ledger_root = tmp_path / "durable_checkout"
    (ledger_root / ".beads").mkdir(parents=True)
    relative_bin_name = "relative-bin"
    stub_bin = tmp_path / relative_bin_name
    _make_fake_executable(stub_bin, "python3.15", f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    _make_fake_executable(stub_bin, "gh")
    _make_fake_executable(stub_bin, "bd", _beads_shim(ledger_root / ".beads"))
    _make_fake_executable(stub_bin, "launchctl", _recording_shim(exit_code=0))

    completed = _run_installer(relative_bin_name, home, cwd=tmp_path)

    assert completed.returncode == 0, completed.stderr
    parsed = plistlib.loads((home / INSTALLED_PLIST_RELATIVE_PATH).read_bytes())
    rendered_python = Path(parsed["ProgramArguments"][0])
    assert rendered_python == (stub_bin / "python3.15").resolve()
    assert rendered_python.is_absolute()


def test_installer_preserves_empty_path_component_as_current_directory(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    ledger_root = tmp_path / "durable_checkout"
    (ledger_root / ".beads").mkdir(parents=True)
    stub_bin = tmp_path / "current-bin"
    _make_fake_executable(stub_bin, "python3.15", f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    _make_fake_executable(stub_bin, "gh")
    _make_fake_executable(stub_bin, "bd", _beads_shim(ledger_root / ".beads"))
    _make_fake_executable(stub_bin, "launchctl", _recording_shim(exit_code=0))

    completed = _run_installer("", home, cwd=stub_bin)

    assert completed.returncode == 0, completed.stderr
    parsed = plistlib.loads((home / INSTALLED_PLIST_RELATIVE_PATH).read_bytes())
    rendered_python = Path(parsed["ProgramArguments"][0])
    assert rendered_python == (stub_bin / "python3.15").resolve()
    assert rendered_python.is_absolute()


def test_installer_anchors_ledger_discovery_to_the_source_checkout_not_the_caller_cwd(
    tmp_path: Path,
) -> None:
    # Invoke the installer from an unrelated Beads checkout. Ledger discovery must
    # bind the Civibus source checkout the installer ships from, not whichever
    # checkout the operator happened to run the installer inside — otherwise the
    # scheduled job mutates the wrong ledger.
    home = tmp_path / "home"
    home.mkdir()
    unrelated_checkout = tmp_path / "unrelated_beads_checkout"
    (unrelated_checkout / ".beads").mkdir(parents=True)
    stub_bin = tmp_path / "bin"
    _make_fake_executable(stub_bin, "python3", f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    _make_fake_executable(stub_bin, "gh")
    _make_fake_executable(stub_bin, "bd", _cwd_reporting_beads_shim())
    _make_fake_executable(stub_bin, "launchctl", _recording_shim(exit_code=0))

    completed = _run_installer(stub_bin, home, cwd=unrelated_checkout)

    assert completed.returncode == 0, completed.stderr
    parsed = plistlib.loads((home / INSTALLED_PLIST_RELATIVE_PATH).read_bytes())
    assert parsed["WorkingDirectory"] == str(REPO_ROOT)
    assert parsed["WorkingDirectory"] != str(unrelated_checkout)


def test_render_and_install_leaves_deployed_bridge_untouched_when_plist_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An already-loaded launchd job executes the deployed bridge at a fixed path.
    # A failed plist write must not have already replaced that bridge, or the
    # running job silently switches to un-published code after a failed install.
    launchd_renderer = _load_launchd_renderer()
    deployed_bridge = tmp_path / "state" / "uptime_incident_bridge.py"
    deployed_bridge.parent.mkdir()
    original_bytes = b"# previously deployed bridge that an existing job still runs\n"
    deployed_bridge.write_bytes(original_bytes)
    installed_path = tmp_path / "com.civibus.uptime-bridge.plist"

    monkeypatch.setattr(launchd_renderer, "require_supported_interpreter", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        launchd_renderer,
        "resolve_required_tool_paths",
        lambda *args, **kwargs: {"gh": "/opt/tools/gh", "bd": "/opt/tools/bd"},
    )
    monkeypatch.setattr(
        launchd_renderer,
        "resolve_ledger_working_directory",
        lambda *args, **kwargs: str(tmp_path),
    )

    real_atomic_write = launchd_renderer._atomic_write

    def failing_plist_write(destination: Path, content: str) -> None:
        if Path(destination) == installed_path:
            raise OSError("simulated plist write failure")
        real_atomic_write(destination, content)

    monkeypatch.setattr(launchd_renderer, "_atomic_write", failing_plist_write)

    with pytest.raises(OSError):
        launchd_renderer.render_and_install(
            template_path=str(TEMPLATE_PATH),
            installed_path=str(installed_path),
            bridge_source_path=str(REPO_ROOT / "scripts" / "uptime_incident_bridge.py"),
            deployed_bridge_path=str(deployed_bridge),
            python_executable="/usr/bin/python3",
            log_directory=str(tmp_path / "logs"),
        )

    assert deployed_bridge.read_bytes() == original_bytes
    assert not installed_path.exists()
