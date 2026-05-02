"""Stage 5 checklist + roadmap update assertions.

Each maps to a `grep -q ...` shell equivalent. They verify the
checklist/roadmap edits landed; they do NOT assert exact body wording
(that would be string duplication).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKLIST = REPO_ROOT / "docs" / "keel" / "checklist.md"
ROADMAP = REPO_ROOT / "docs" / "keel" / "roadmap.md"


def test_checklist_references_casual_md() -> None:
    body = CHECKLIST.read_text(encoding="utf-8")
    assert "casual.md" in body


def test_checklist_parking_lot_names_activation_lane() -> None:
    body = CHECKLIST.read_text(encoding="utf-8")
    assert "Activation lane" in body, "checklist parking lot must name the deferred Activation lane"


def test_roadmap_has_casual_mode_section() -> None:
    body = ROADMAP.read_text(encoding="utf-8")
    assert "Casual mode" in body


def test_roadmap_references_casual_md() -> None:
    body = ROADMAP.read_text(encoding="utf-8")
    assert "casual.md" in body


def test_checklist_session_log_has_today_entry() -> None:
    body = CHECKLIST.read_text(encoding="utf-8")
    # New session-log entry for casual-mode landing dated today.
    assert re.search(r"^### 2026-04-26\b", body, re.MULTILINE), \
        "checklist must have a 2026-04-26 session-log entry summarizing casual-mode landing"
