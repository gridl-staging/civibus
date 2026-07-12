"""Cross-doc bidirectional contract for casual.md ↔ enforcement.md."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
README = REPO_ROOT / "docs" / "reference" / "keel" / "README.md"
CASUAL = REPO_ROOT / "docs" / "reference" / "keel" / "casual.md"
ENFORCEMENT = REPO_ROOT / "docs" / "reference" / "keel" / "enforcement.md"


def test_readme_has_two_modes_section_heading() -> None:
    body = README.read_text(encoding="utf-8")
    # Anchor to start-of-line so the substring "Two modes" inside a sentence
    # cannot satisfy the test.
    assert re.search(r"^#+ Two modes\b", body, re.MULTILINE), "README.md must contain a `## Two modes` section heading"


def test_readme_names_both_modes() -> None:
    body = README.read_text(encoding="utf-8")
    assert "casual.md" in body, "README.md must reference casual.md"
    assert "enforcement.md" in body, "README.md must reference enforcement.md"


def test_casual_md_forward_link_to_enforcement() -> None:
    body = CASUAL.read_text(encoding="utf-8")
    assert "enforcement.md" in body


def test_enforcement_md_back_link_to_casual() -> None:
    body = ENFORCEMENT.read_text(encoding="utf-8")
    assert "casual.md" in body, "enforcement.md must back-link to casual.md"
