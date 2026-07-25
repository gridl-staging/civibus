from __future__ import annotations

import inspect
import os
import shutil
import shlex
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

PRIVATE_ANCESTOR_FIXTURE_NAME = "private_ancestor_fixture_root"

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "infra/scripts/env_lib.sh"
PRIVATE_FIXTURE_ROOTS_PARENT = REPO_ROOT / "test_support" / "ancestor_fixture_roots"
ANCESTOR_SENSITIVE_FIXTURE_SPECIMENS = (
    "test_source_sanitizes_poisoned_path_before_secret_guards",
    "test_prepend_private_local_bin_accepts_private_directory_once",
    "test_prepend_private_local_bin_skips_unsafe_entries_with_diagnostics",
)


def _run_env_lib_shell(script: str, *, path: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/bash", "-c", script],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PATH": path},
        timeout=10,
    )


def _source_env_lib_script(body: str) -> str:
    return f"""
    source {shlex.quote(str(SCRIPT_PATH))}
    {body}
    """


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _private_ancestor_fixture_root(specimen_name: str) -> Path:
    safe_specimen_name = "".join(character if character.isalnum() else "_" for character in specimen_name)
    root = PRIVATE_FIXTURE_ROOTS_PARENT / f"{safe_specimen_name}_{uuid.uuid4().hex}"
    root.mkdir(parents=True)
    root.chmod(0o700)

    probe_child = root / "probe_child"
    result = _run_env_lib_shell(
        _source_env_lib_script(
            f"""
            require_private_parent_directories {shlex.quote(str(probe_child))} 'fixture root' 'Refusing'
            """
        ),
        path="/usr/bin:/bin",
    )
    if result.returncode != 0:
        shutil.rmtree(root, ignore_errors=True)
        pytest.fail(f"private fixture root failed ancestor validation: {result.stderr}")
    return root


def _remove_private_ancestor_fixture_root(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)
    try:
        PRIVATE_FIXTURE_ROOTS_PARENT.rmdir()
    except OSError:
        pass


@pytest.fixture
def private_ancestor_fixture_root(request: pytest.FixtureRequest) -> Iterator[Path]:
    root = _private_ancestor_fixture_root(request.node.name)
    try:
        yield root
    finally:
        _remove_private_ancestor_fixture_root(root)


def _tests_requesting_private_ancestor_fixture_root() -> frozenset[str]:
    module = sys.modules[__name__]
    consumers = set()
    for name, obj in vars(module).items():
        if not name.startswith("test_") or not callable(obj):
            continue
        try:
            parameters = inspect.signature(obj).parameters
        except (TypeError, ValueError):
            continue
        if PRIVATE_ANCESTOR_FIXTURE_NAME in parameters:
            consumers.add(name)
    return frozenset(consumers)


def test_ancestor_sensitive_specimen_registry_matches_private_fixture_consumers() -> None:
    """Bind the specimen contract to reality: the declared registry must equal the
    set of tests that actually request ``private_ancestor_fixture_root``. Moving one
    specimen back to ``tmp_path`` drops it from the consumer set and fails here,
    which is exactly the world-writable ``/tmp`` ancestry regression this stage repairs."""
    assert _tests_requesting_private_ancestor_fixture_root() == frozenset(ANCESTOR_SENSITIVE_FIXTURE_SPECIMENS)


@pytest.mark.parametrize("specimen_name", ANCESTOR_SENSITIVE_FIXTURE_SPECIMENS)
def test_ancestor_sensitive_fixture_root_rejects_world_writable_ancestor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    specimen_name: str,
) -> None:
    unsafe_parent = tmp_path / "unsafe_parent"
    unsafe_parent.mkdir()
    unsafe_parent.chmod(0o1777)
    monkeypatch.setattr(sys.modules[__name__], "PRIVATE_FIXTURE_ROOTS_PARENT", unsafe_parent)

    with pytest.raises(pytest.fail.Exception, match="private fixture root failed ancestor validation") as failure:
        _private_ancestor_fixture_root(specimen_name)

    assert "parent directory writable by group/other" in str(failure.value)
    assert str(unsafe_parent) in str(failure.value)
    assert not any(unsafe_parent.iterdir())


def test_source_sanitizes_poisoned_path_before_secret_guards(
    private_ancestor_fixture_root: Path,
) -> None:
    poisoned_bin = private_ancestor_fixture_root / "poisoned_bin"
    private_bin = private_ancestor_fixture_root / "private_bin"
    env_file = private_ancestor_fixture_root / "secrets.env"
    stat_marker = private_ancestor_fixture_root / "fake_stat_ran"
    dirname_marker = private_ancestor_fixture_root / "fake_dirname_ran"

    poisoned_bin.mkdir()
    poisoned_bin.chmod(0o777)
    private_bin.mkdir()
    private_bin.chmod(0o700)
    env_file.write_text("POSTGRES_PASSWORD=secret\n", encoding="utf-8")
    env_file.chmod(0o600)

    _write_executable(
        poisoned_bin / "stat",
        f'#!/bin/bash\ntouch {shlex.quote(str(stat_marker))}\nexec /usr/bin/stat "$@"\n',
    )
    _write_executable(
        poisoned_bin / "dirname",
        f'#!/bin/bash\ntouch {shlex.quote(str(dirname_marker))}\nexec /usr/bin/dirname "$@"\n',
    )

    inherited_path = f"{poisoned_bin}{os.pathsep}{private_bin}"
    result = _run_env_lib_shell(
        _source_env_lib_script(
            f"""
            printf 'PATH=%s\\n' "$PATH"
            require_private_env_file {shlex.quote(str(env_file))}
            """
        ),
        path=inherited_path,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [f"PATH={private_bin}"]
    assert not stat_marker.exists()
    assert not dirname_marker.exists()


def test_sanitize_inherited_path_keeps_private_absolute_directories_in_order(
    tmp_path: Path,
) -> None:
    first_private = tmp_path / "first_private"
    second_private = tmp_path / "second_private"
    regular_file = tmp_path / "regular_file"
    symlinked_dir = tmp_path / "symlinked_dir"
    symlink_target = tmp_path / "symlink_target"
    group_writable = tmp_path / "group_writable"
    world_writable = tmp_path / "world_writable"

    for directory in [first_private, second_private, symlink_target, group_writable, world_writable]:
        directory.mkdir()
        directory.chmod(0o700)
    regular_file.write_text("not a directory\n", encoding="utf-8")
    regular_file.chmod(0o600)
    symlinked_dir.symlink_to(symlink_target, target_is_directory=True)
    group_writable.chmod(0o720)
    world_writable.chmod(0o702)

    rejected_entries = [
        "",
        ".",
        "relative_bin",
        str(tmp_path / "missing"),
        str(regular_file),
        str(symlinked_dir),
        str(group_writable),
        str(world_writable),
        "",
    ]
    inherited_path = os.pathsep.join(
        [
            rejected_entries[0],
            str(first_private),
            *rejected_entries[1:5],
            str(second_private),
            *rejected_entries[5:],
        ]
    )
    result = _run_env_lib_shell(
        _source_env_lib_script(
            f"""
            PATH={shlex.quote(inherited_path)}
            sanitize_inherited_path
            printf '%s\\n' "$PATH"
            """
        ),
        path="/usr/bin:/bin",
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        f"{first_private}{os.pathsep}{second_private}",
    ]


def test_sanitize_inherited_path_falls_back_to_trusted_system_path(tmp_path: Path) -> None:
    regular_file = tmp_path / "regular_file"
    world_writable = tmp_path / "world_writable"
    symlinked_dir = tmp_path / "symlinked_dir"
    symlink_target = tmp_path / "symlink_target"
    regular_file.write_text("not a directory\n", encoding="utf-8")
    regular_file.chmod(0o600)
    world_writable.mkdir()
    world_writable.chmod(0o777)
    symlink_target.mkdir()
    symlink_target.chmod(0o700)
    symlinked_dir.symlink_to(symlink_target, target_is_directory=True)

    inherited_path = os.pathsep.join(
        [
            "",
            ".",
            "relative_bin",
            str(tmp_path / "missing"),
            str(regular_file),
            str(symlinked_dir),
            str(world_writable),
            "",
        ]
    )
    result = _run_env_lib_shell(
        _source_env_lib_script(
            f"""
            PATH={shlex.quote(inherited_path)}
            sanitize_inherited_path
            printf 'PATH=%s\\n' "$PATH"
            command -v stat
            command -v dirname
            """
        ),
        path="/usr/bin:/bin",
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["PATH=/usr/bin:/bin", "/usr/bin/stat", "/usr/bin/dirname"]


def test_prepend_private_local_bin_accepts_private_directory_once(
    private_ancestor_fixture_root: Path,
) -> None:
    private_bin = private_ancestor_fixture_root / "private_bin"
    base_bin = private_ancestor_fixture_root / "base_bin"
    private_bin.mkdir()
    private_bin.chmod(0o700)
    base_bin.mkdir()
    base_bin.chmod(0o700)

    result = _run_env_lib_shell(
        _source_env_lib_script(
            f"""
            PATH={shlex.quote(str(base_bin))}
            prepend_private_local_bin {shlex.quote(str(private_bin))}
            prepend_private_local_bin {shlex.quote(str(private_bin))}
            printf '%s\\n' "$PATH"
            """
        ),
        path="/usr/bin:/bin",
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [f"{private_bin}{os.pathsep}{base_bin}"]


def test_prepend_private_local_bin_missing_and_empty_are_no_ops(tmp_path: Path) -> None:
    base_bin = tmp_path / "base_bin"
    base_bin.mkdir()
    base_bin.chmod(0o700)

    result = _run_env_lib_shell(
        _source_env_lib_script(
            f"""
            PATH={shlex.quote(str(base_bin))}
            prepend_private_local_bin ''
            prepend_private_local_bin {shlex.quote(str(tmp_path / "missing"))}
            printf '%s\\n' "$PATH"
            """
        ),
        path="/usr/bin:/bin",
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [str(base_bin)]
    assert result.stderr == ""


def test_prepend_private_local_bin_skips_unsafe_entries_with_diagnostics(
    private_ancestor_fixture_root: Path,
) -> None:
    base_bin = private_ancestor_fixture_root / "base_bin"
    non_directory = private_ancestor_fixture_root / "regular_file"
    symlinked_dir = private_ancestor_fixture_root / "symlinked_dir"
    symlink_target = private_ancestor_fixture_root / "symlink_target"
    group_writable = private_ancestor_fixture_root / "group_writable"
    world_writable = private_ancestor_fixture_root / "world_writable"
    unsafe_parent = private_ancestor_fixture_root / "unsafe_parent"
    unsafe_child = unsafe_parent / "bin"

    for directory in [
        base_bin,
        symlink_target,
        group_writable,
        world_writable,
        unsafe_child,
    ]:
        directory.mkdir(parents=True)
        directory.chmod(0o700)
    non_directory.write_text("not a directory\n", encoding="utf-8")
    non_directory.chmod(0o600)
    symlinked_dir.symlink_to(symlink_target, target_is_directory=True)
    group_writable.chmod(0o720)
    world_writable.chmod(0o702)
    unsafe_parent.chmod(0o777)

    result = _run_env_lib_shell(
        _source_env_lib_script(
            f"""
            PATH={shlex.quote(str(base_bin))}
            prepend_private_local_bin {shlex.quote(str(non_directory))}
            prepend_private_local_bin {shlex.quote(str(symlinked_dir))}
            prepend_private_local_bin {shlex.quote(str(group_writable))}
            prepend_private_local_bin {shlex.quote(str(world_writable))}
            prepend_private_local_bin {shlex.quote(str(unsafe_child))}
            printf '%s\\n' "$PATH"
            """
        ),
        path="/usr/bin:/bin",
    )

    assert result.returncode == 0
    assert result.stdout.splitlines() == [str(base_bin)]
    assert "Skipping non-directory PATH entry" in result.stderr
    assert "Skipping symlinked PATH entry" in result.stderr
    assert result.stderr.count("Skipping PATH entry writable by group/other") == 2
    assert "Skipping PATH entry with parent directory writable by group/other" in result.stderr
