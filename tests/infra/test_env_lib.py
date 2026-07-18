from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "infra/scripts/env_lib.sh"


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


def test_source_sanitizes_poisoned_path_before_secret_guards(tmp_path: Path) -> None:
    poisoned_bin = tmp_path / "poisoned_bin"
    private_bin = tmp_path / "private_bin"
    env_file = tmp_path / "secrets.env"
    stat_marker = tmp_path / "fake_stat_ran"
    dirname_marker = tmp_path / "fake_dirname_ran"

    poisoned_bin.mkdir()
    poisoned_bin.chmod(0o777)
    private_bin.mkdir()
    private_bin.chmod(0o700)
    env_file.write_text("POSTGRES_PASSWORD=secret\n", encoding="utf-8")
    env_file.chmod(0o600)

    _write_executable(
        poisoned_bin / "stat",
        f'#!/bin/bash\ntouch {stat_marker}\nexec /usr/bin/stat "$@"\n',
    )
    _write_executable(
        poisoned_bin / "dirname",
        f'#!/bin/bash\ntouch {dirname_marker}\nexec /usr/bin/dirname "$@"\n',
    )

    inherited_path = f"{poisoned_bin}{os.pathsep}{private_bin}"
    result = _run_env_lib_shell(
        f"""
        source {SCRIPT_PATH}
        printf 'PATH=%s\\n' "$PATH"
        require_private_env_file {env_file}
        """,
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


def test_prepend_private_local_bin_accepts_private_directory_once(tmp_path: Path) -> None:
    private_bin = tmp_path / "private_bin"
    base_bin = tmp_path / "base_bin"
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


def test_prepend_private_local_bin_skips_unsafe_entries_with_diagnostics(tmp_path: Path) -> None:
    base_bin = tmp_path / "base_bin"
    non_directory = tmp_path / "regular_file"
    symlinked_dir = tmp_path / "symlinked_dir"
    symlink_target = tmp_path / "symlink_target"
    group_writable = tmp_path / "group_writable"
    world_writable = tmp_path / "world_writable"
    unsafe_parent = tmp_path / "unsafe_parent"
    unsafe_child = unsafe_parent / "bin"

    for directory in [base_bin, symlink_target, group_writable, world_writable, unsafe_child]:
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
