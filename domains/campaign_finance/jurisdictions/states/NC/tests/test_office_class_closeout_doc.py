from __future__ import annotations

from collections import Counter
from pathlib import Path

from _test_helpers import markdown_table_under_heading, read
from test_office_class_fixture_inventory import _in_scope_rows
from test_office_universe_inventory import REQUIRED_COLUMNS, UNIVERSE_DOC_PATH


REPO_ROOT = Path(__file__).resolve().parents[6]
CLOSEOUT_DOC_PATH = REPO_ROOT / "docs" / "reference" / "research" / "nc_office_coverage_closeout_2026_04_24.md"
EXPECTED_CLOSEOUT_COLUMNS = [
    "office_class",
    "fixture_slug",
    "fixture_status",
    "proof_tests",
    "gap_artifacts",
    "final_notes",
]


def _stage1_rows_by_office_class() -> dict[str, dict[str, str]]:
    headers, rows = markdown_table_under_heading(read(UNIVERSE_DOC_PATH), "Universe Table")
    assert headers == REQUIRED_COLUMNS
    return {row["office_class"]: row for row in _in_scope_rows()}


def test_closeout_doc_matrix_tracks_stage1_office_classes_once_with_required_fields() -> None:
    stage1_rows_by_class = _stage1_rows_by_office_class()

    headers, rows = markdown_table_under_heading(read(CLOSEOUT_DOC_PATH), "Coverage Matrix")
    assert headers == EXPECTED_CLOSEOUT_COLUMNS

    closeout_office_classes = [row["office_class"] for row in rows]
    class_counts = Counter(closeout_office_classes)

    assert set(closeout_office_classes) == set(stage1_rows_by_class)
    assert all(count == 1 for count in class_counts.values())

    for row in rows:
        office_class = row["office_class"]
        stage1_row = stage1_rows_by_class[office_class]

        assert row["fixture_slug"] == stage1_row["fixture_slug"]
        assert row["fixture_status"].strip()
        assert row["proof_tests"].strip()
        assert "test_office_class_coverage.py::" in row["proof_tests"]
        assert row["gap_artifacts"].strip()
        assert row["gap_artifacts"].startswith("docs/reference/research/artifacts/2026_04_24_nc_office_universe/")
        assert row["final_notes"].strip()
