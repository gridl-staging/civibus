from __future__ import annotations

import importlib.util
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SYNC_GUARD_PATH = REPO_ROOT / ".debbie" / "verify_sync_source.py"
DEBBIE_CONFIG_PATH = REPO_ROOT / ".debbie.toml"


@dataclass(frozen=True)
class SyncRepository:
    root: Path
    older_commit: str
    authorized_commit: str


def _git(repository: Path, *arguments: str, input_text: str | None = None) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        input=input_text,
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.fixture
def sync_repository(tmp_path: Path) -> SyncRepository:
    repository = tmp_path / "sync-source"
    guard_directory = repository / ".debbie"
    guard_directory.mkdir(parents=True)
    if SYNC_GUARD_PATH.exists():
        shutil.copy2(SYNC_GUARD_PATH, guard_directory / SYNC_GUARD_PATH.name)

    _write(
        repository / ".debbie.toml",
        """\
[sync]
files = ["selected.txt"]

[[sync.dirs]]
path = "selected_dir/"
exclude = ["*.excluded"]
""",
    )
    _write(repository / "selected.txt", "selected baseline\n")
    _write(repository / "selected_dir" / "included.txt", "directory baseline\n")
    _write(repository / "selected_dir" / "ignored.excluded", "excluded baseline\n")
    _write(repository / "unselected.txt", "unselected baseline\n")

    _git(repository, "init")
    _git(repository, "config", "user.email", "ci@example.invalid")
    _git(repository, "config", "user.name", "CI Fixture")
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", "older baseline")
    older_commit = _git(repository, "rev-parse", "HEAD")

    _write(repository / "selected.txt", "selected authorized\n")
    _write(repository / "selected_dir" / "included.txt", "directory authorized\n")
    _write(repository / "selected_dir" / "ignored.excluded", "excluded authorized\n")
    _write(repository / "unselected.txt", "unselected authorized\n")
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", "authorized source")
    authorized_commit = _git(repository, "rev-parse", "HEAD")

    return SyncRepository(repository, older_commit, authorized_commit)


def _run_guard(repository: SyncRepository, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["uv", "run", "python", ".debbie/verify_sync_source.py", *arguments],
        cwd=repository.root,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _load_guard_module(script_path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location("debbie_verify_sync_source", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_rejects_restored_selected_paths_when_head_is_stale(sync_repository: SyncRepository) -> None:
    _git(sync_repository.root, "checkout", "--detach", sync_repository.older_commit)
    _git(
        sync_repository.root,
        "restore",
        "--source",
        sync_repository.authorized_commit,
        "--",
        "selected.txt",
        "selected_dir/included.txt",
    )
    assert (sync_repository.root / "selected.txt").read_text(encoding="utf-8") == "selected authorized\n"
    assert (sync_repository.root / "selected_dir" / "included.txt").read_text(encoding="utf-8") == (
        "directory authorized\n"
    )

    completed = _run_guard(
        sync_repository,
        "--authorized-sha",
        sync_repository.authorized_commit,
    )

    assert completed.returncode != 0
    assert "HEAD does not match the authorized SHA" in completed.stderr


@pytest.mark.parametrize("authorized_sha", ["not-a-sha", "0000000000000000000000000000000000000000"])
def test_rejects_malformed_or_unknown_authorized_sha(
    sync_repository: SyncRepository,
    authorized_sha: str,
) -> None:
    completed = _run_guard(sync_repository, "--authorized-sha", authorized_sha)

    assert completed.returncode != 0
    assert "authorized SHA is not a valid commit" in completed.stderr


def test_rejects_non_commit_authorized_object(sync_repository: SyncRepository) -> None:
    blob_sha = _git(sync_repository.root, "hash-object", "-w", "selected.txt")

    completed = _run_guard(sync_repository, "--authorized-sha", blob_sha)

    assert completed.returncode != 0
    assert "authorized SHA is not a valid commit" in completed.stderr


def test_requires_authorized_sha(sync_repository: SyncRepository) -> None:
    completed = _run_guard(sync_repository)

    assert completed.returncode != 0
    assert "--authorized-sha" in completed.stderr
    assert "required" in completed.stderr


def test_allows_unselected_and_excluded_drift_at_authorized_head(sync_repository: SyncRepository) -> None:
    _write(sync_repository.root / "unselected.txt", "dirty but unselected\n")
    _write(sync_repository.root / "selected_dir" / "ignored.excluded", "dirty but excluded\n")

    completed = _run_guard(
        sync_repository,
        "--authorized-sha",
        sync_repository.authorized_commit,
    )

    assert completed.returncode == 0, completed.stderr


def test_rejects_selected_path_drift_at_authorized_head(sync_repository: SyncRepository) -> None:
    _write(sync_repository.root / "selected_dir" / "included.txt", "dirty selected content\n")

    completed = _run_guard(
        sync_repository,
        "--authorized-sha",
        sync_repository.authorized_commit,
    )

    assert completed.returncode != 0
    assert "Debbie-selected paths differ from HEAD" in completed.stderr
    assert "selected_dir/included.txt" in completed.stderr


def test_rejects_gitignored_selected_path_at_authorized_head(sync_repository: SyncRepository) -> None:
    _write(sync_repository.root / ".gitignore", "selected_dir/secret.txt\n")
    _git(sync_repository.root, "add", ".gitignore")
    _git(sync_repository.root, "commit", "-m", "ignore selected secret")
    authorized_commit = _git(sync_repository.root, "rev-parse", "HEAD")
    _write(sync_repository.root / "selected_dir" / "secret.txt", "uncommitted publishable content\n")

    completed = _run_guard(sync_repository, "--authorized-sha", authorized_commit)

    assert completed.returncode != 0, completed.stdout
    assert "Debbie-selected paths differ from HEAD" in completed.stderr
    assert "selected_dir/secret.txt" in completed.stderr

    _git(sync_repository.root, "add", "--force", "selected_dir/secret.txt")

    staged_completed = _run_guard(sync_repository, "--authorized-sha", authorized_commit)

    assert staged_completed.returncode != 0, staged_completed.stdout
    assert "Debbie-selected paths differ from HEAD" in staged_completed.stderr
    assert "selected_dir/secret.txt" in staged_completed.stderr

    _git(sync_repository.root, "restore", "--staged", "selected_dir/secret.txt")
    (sync_repository.root / "selected_dir" / "secret.txt").unlink()
    _write(
        sync_repository.root / ".debbie.toml",
        """\
[sync]
files = ["selected.txt"]

[[sync.dirs]]
path = "selected_dir/"
exclude = ["*.excluded"]

[[sync.dirs]]
path = ":(exclude)selected_magic/"
""",
    )
    _write(
        sync_repository.root / ".gitignore",
        "selected_dir/secret.txt\n:(exclude)selected_magic/secret.txt\n",
    )
    _git(sync_repository.root, "add", ".debbie.toml", ".gitignore")
    _git(sync_repository.root, "commit", "-m", "select pathspec-shaped directory")
    authorized_commit = _git(sync_repository.root, "rev-parse", "HEAD")
    _write(
        sync_repository.root / ":(exclude)selected_magic" / "secret.txt",
        "uncommitted pathspec-shaped content\n",
    )

    pathspec_completed = _run_guard(sync_repository, "--authorized-sha", authorized_commit)

    assert pathspec_completed.returncode != 0, pathspec_completed.stdout
    assert "Debbie-selected paths differ from HEAD" in pathspec_completed.stderr
    assert ":(exclude)selected_magic/secret.txt" in pathspec_completed.stderr

    (sync_repository.root / ":(exclude)selected_magic" / "secret.txt").unlink()
    _write(sync_repository.root / ".git" / "info" / "exclude", "selected_dir/*\n")
    newline_path = sync_repository.root / "selected_dir" / "secret\nname.txt"
    _write(newline_path, "uncommitted newline-bearing content\n")

    newline_completed = _run_guard(sync_repository, "--authorized-sha", authorized_commit)

    assert newline_completed.returncode != 0, newline_completed.stdout
    assert "Debbie-selected paths differ from HEAD" in newline_completed.stderr
    assert "selected_dir/secret\nname.txt" in newline_completed.stderr


def test_selected_paths_are_derived_from_debbie_config(sync_repository: SyncRepository) -> None:
    guard_module = _load_guard_module(sync_repository.root / ".debbie" / "verify_sync_source.py")

    selected_paths = guard_module.debbie_selected_paths(
        sync_repository.root,
        sync_repository.root / ".debbie.toml",
    )

    assert selected_paths == (
        Path("selected.txt"),
        Path("selected_dir/included.txt"),
    )
