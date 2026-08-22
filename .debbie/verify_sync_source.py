#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fnmatch
import subprocess
import sys
import tomllib
from collections.abc import Iterable
from pathlib import Path


def _existing_file_paths(repository_root: Path) -> tuple[Path, ...]:
    return tuple(
        path.relative_to(repository_root)
        for path in repository_root.rglob("*")
        if (path.is_file() or path.is_symlink()) and ".git" not in path.relative_to(repository_root).parts
    )


def _is_selected_directory_path(
    relative_path: Path,
    directory_path: Path,
    exclude_patterns: tuple[str, ...],
) -> bool:
    try:
        path_within_directory = relative_path.relative_to(directory_path)
    except ValueError:
        return False
    return bool(path_within_directory.parts) and not any(
        fnmatch.fnmatch(path_part, pattern) for path_part in path_within_directory.parts for pattern in exclude_patterns
    )


def debbie_selected_paths(
    repository_root: Path,
    config_path: Path,
    candidate_paths: Iterable[Path] | None = None,
) -> tuple[Path, ...]:
    """Return existing or supplied paths selected by the Debbie sync config."""
    sync_config = tomllib.loads(config_path.read_text(encoding="utf-8"))["sync"]
    selected_files = {Path(path) for path in sync_config.get("files", ())}
    selected_directories = tuple(
        (
            Path(directory["path"].rstrip("/")),
            tuple(directory.get("exclude", ())),
        )
        for directory in sync_config.get("dirs", ())
    )
    candidates = candidate_paths if candidate_paths is not None else _existing_file_paths(repository_root)

    return tuple(
        sorted(
            {
                relative_path
                for candidate_path in candidates
                if (relative_path := Path(candidate_path)) in selected_files
                or any(
                    _is_selected_directory_path(relative_path, directory_path, exclude_patterns)
                    for directory_path, exclude_patterns in selected_directories
                )
            },
            key=lambda path: path.as_posix(),
        )
    )


def _run_git(repository_root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=repository_root,
        capture_output=True,
        text=True,
        check=False,
    )


def _resolve_commit(repository_root: Path, authorized_sha: str) -> str:
    resolved = _run_git(repository_root, "rev-parse", "--verify", f"{authorized_sha}^{{commit}}")
    if resolved.returncode != 0:
        raise ValueError(f"authorized SHA is not a valid commit: {authorized_sha}")
    return resolved.stdout.strip()


def _git_candidate_paths(repository_root: Path) -> tuple[Path, ...]:
    # NUL delimiters preserve filenames containing newlines and prevent Git's
    # display quoting from changing which paths the Debbie config selects.
    head_paths = _run_git(repository_root, "ls-tree", "-r", "-z", "--name-only", "HEAD")
    # Enumerate index and untracked paths, gitignored ones included: Debbie sync
    # selects by config path, not by gitignore, so every publishable addition must
    # be checked for drift whether it is unstaged, staged, or ignored.
    working_paths = _run_git(repository_root, "ls-files", "-z", "--cached", "--others")
    if head_paths.returncode != 0 or working_paths.returncode != 0:
        raise RuntimeError("could not enumerate repository paths")
    return tuple(Path(path) for path in (*head_paths.stdout.split("\x00"), *working_paths.stdout.split("\x00")) if path)


def _selected_path_drift(repository_root: Path, selected_paths: tuple[Path, ...]) -> str:
    if not selected_paths:
        return ""
    status = _run_git(
        repository_root,
        # Treat Debbie-selected filenames literally. Otherwise a filename that
        # begins with Git pathspec magic (for example `:(exclude)`) can alter
        # the match and hide its own drift from this publish guard.
        "--literal-pathspecs",
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
        # --ignored so a gitignored selected path surfaces as drift (`!!`); git status
        # otherwise suppresses ignored files even when named explicitly in the pathspec.
        "--ignored=matching",
        "--",
        *(path.as_posix() for path in selected_paths),
    )
    if status.returncode != 0:
        raise RuntimeError("could not compare Debbie-selected paths with HEAD")
    return status.stdout.replace("\x00", "\n").strip()


def _repository_root() -> Path:
    resolved = _run_git(Path.cwd(), "rev-parse", "--show-toplevel")
    if resolved.returncode != 0:
        raise RuntimeError("current directory is not inside a git repository")
    return Path(resolved.stdout.strip())


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the git source authorized for Debbie sync")
    parser.add_argument("--authorized-sha", required=True)
    arguments = parser.parse_args()

    try:
        repository_root = _repository_root()
        authorized_commit = _resolve_commit(repository_root, arguments.authorized_sha)
        head_commit = _resolve_commit(repository_root, "HEAD")
        if head_commit != authorized_commit:
            raise ValueError(
                f"HEAD does not match the authorized SHA: HEAD={head_commit} authorized={authorized_commit}"
            )
        selected_paths = debbie_selected_paths(
            repository_root,
            repository_root / ".debbie.toml",
            _git_candidate_paths(repository_root),
        )
        drift = _selected_path_drift(repository_root, selected_paths)
        if drift:
            raise ValueError(f"Debbie-selected paths differ from HEAD:\n{drift}")
    except (KeyError, OSError, RuntimeError, tomllib.TOMLDecodeError, ValueError) as error:
        print(f"Debbie sync source verification failed: {error}", file=sys.stderr)
        return 1

    print(f"Debbie sync source verified at {authorized_commit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
