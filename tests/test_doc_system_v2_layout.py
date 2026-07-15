from __future__ import annotations

import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _git_ls_files(path: str) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", path],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def test_decisions_are_root_owned_with_frontmatter_and_line_budget() -> None:
    decisions_dir = REPO_ROOT / "decisions"

    assert decisions_dir.is_dir()
    assert not (REPO_ROOT / "docs" / "decisions").exists()

    decision_files = sorted(decisions_dir.glob("*.md"))
    assert len(decision_files) == 13
    for decision_file in decision_files:
        lines = decision_file.read_text(encoding="utf-8").splitlines()
        assert len(lines) <= 200, decision_file.name
        assert lines[:1] == ["---"], decision_file.name
        assert any(line.startswith("status: ") for line in lines[:10]), decision_file.name
        assert any(line.startswith("date: ") for line in lines[:10]), decision_file.name


def test_docs_top_level_uses_only_v2_quadrants() -> None:
    docs_dir = REPO_ROOT / "docs"

    top_level_markdown = sorted(path.name for path in docs_dir.glob("*.md"))
    assert top_level_markdown == ["protocols.md"]

    top_level_dirs = sorted(path.name for path in docs_dir.iterdir() if path.is_dir())
    assert top_level_dirs == ["howto", "live-state", "reference"]

    for tracked_dir in ("decisions", "docs/howto", "docs/live-state"):
        assert _git_ls_files(tracked_dir), f"{tracked_dir} has no tracked files"


def test_protocols_routes_resolve_to_v2_owners() -> None:
    protocols = (REPO_ROOT / "docs" / "protocols.md").read_text(encoding="utf-8")

    assert len(protocols.splitlines()) <= 100
    assert "docs/" + "anchors/{SCOPE}.md" not in protocols
    for legacy_path in ("keel", "specs", "operations", "research", "screen_specs"):
        legacy_path = f"docs/{legacy_path}"
        assert legacy_path not in protocols
    for v2_path in (
        "docs/reference/anchors/",
        "docs/reference/keel",
        "docs/reference/specs",
        "docs/howto/operations",
        "docs/reference/research",
        "docs/reference/screen_specs",
    ):
        assert v2_path in protocols


def test_no_v2_suffix_markdown_remains() -> None:
    v2_files = list(REPO_ROOT.glob("**/*_v2.md"))

    assert v2_files == []
