"""Structural-contract tests for `docs/reference/keel/casual.md`.

The string assertions here are NOT string-duplication-test smell — they
ARE the contract the doc owes its readers (cross-link integrity, no
strict-mode-only artifact references, section presence).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CASUAL_MD = REPO_ROOT / "docs" / "reference" / "keel" / "casual.md"


# Numbered sections from the plan (Stage 3, "Doc structure").
# Each entry is a regex anchored at start-of-line that must match at least once.
_SECTION_REGEXES = [
    # 1. What this is + the one-liner
    r"^#+ .*[Ww]hat\s+this\s+is",
    # 2. Failure-mode catalog
    r"^#+ .*[Ff]ailure[- ]mode\s+catalog",
    # 3. Output discipline
    r"^#+ .*[Oo]utput\s+discipline",
    # 4. Fresh-context judge pass
    r"^#+ .*[Ff]resh[- ]context\s+judge",
    # 5. Closing template
    r"^#+ .*[Cc]losing\s+template",
    # 6. Waivers do not apply in casual mode
    r"^#+ .*[Ww]aivers",
    # 7. When NOT to use casual mode
    r"^#+ .*[Ww]hen\s+NOT\s+to\s+use",
]


def test_casual_md_exists() -> None:
    assert CASUAL_MD.is_file(), f"missing: {CASUAL_MD}"


def test_casual_md_under_250_lines() -> None:
    n = sum(1 for _ in CASUAL_MD.read_text(encoding="utf-8").splitlines())
    assert n < 250, f"casual.md too long: {n} lines (cap is 250)"


def test_casual_md_has_all_seven_numbered_sections() -> None:
    body = CASUAL_MD.read_text(encoding="utf-8")
    missing = [pat for pat in _SECTION_REGEXES if not re.search(pat, body, re.MULTILINE)]
    assert not missing, f"missing sections: {missing}"


_REQUIRED_PATHS = [
    "docs/reference/keel/CURRENT.md",
    "docs/reference/keel/historical_validation.md",
    "docs/reference/keel/layers.md",
    "docs/reference/keel/judge_prompts.md",
]


def test_casual_md_cross_link_integrity() -> None:
    body = CASUAL_MD.read_text(encoding="utf-8")
    for path in _REQUIRED_PATHS:
        assert path in body, f"casual.md does not reference {path}"
        assert (REPO_ROOT / path).exists(), f"referenced path missing in repo: {path}"


_FORBIDDEN_STRICT_ARTIFACTS = [
    "scripts/stage_close_gate.py",
    "matt session-close",
    "KEEL_AUTOPUBLISH_EVIDENCE",
]


def test_casual_md_does_not_reference_strict_only_artifacts() -> None:
    body = CASUAL_MD.read_text(encoding="utf-8")
    for token in _FORBIDDEN_STRICT_ARTIFACTS:
        assert token not in body, f"casual.md must not reference strict-mode-only token: {token}"


def test_casual_md_cross_links_to_enforcement_md() -> None:
    body = CASUAL_MD.read_text(encoding="utf-8")
    assert "enforcement.md" in body, "casual.md must cross-link to enforcement.md (per plan Stage 3 step 7)"
