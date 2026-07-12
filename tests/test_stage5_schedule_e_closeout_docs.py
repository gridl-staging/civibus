from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_stage5_docs_closeout_contract() -> None:
    roadmap = (REPO_ROOT / "ROADMAP.md").read_text(encoding="utf-8")
    bulk_doc = (REPO_ROOT / "docs" / "reference" / "research" / "fec-bulk-data.md").read_text(encoding="utf-8")

    assert "SPENT_SUPPORTING" not in roadmap
    assert "SPENT_OPPOSING" not in roadmap
    assert "Graph edge types `SUPPORTS`, `OPPOSES`, and `RUNS_IN` remain deferred." not in roadmap
    assert "Deferred: SUPPORTS, OPPOSES, RUNS_IN." not in roadmap
    assert "See [fec-schedule-e-format.md](fec-schedule-e-format.md)." in bulk_doc
