"""Boundary tests for the shared line-budget owner (`test_support/line_budget.py`)."""

from __future__ import annotations

from pathlib import Path

import pytest

from test_support.line_budget import HARD_LINE_LIMIT, count_lines, oversized_modules

pytestmark = pytest.mark.unit


def _write_module(tmp_path: Path, name: str, line_count: int) -> Path:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join("x" for _ in range(line_count)) + "\n", encoding="utf-8")
    return path


def test_hard_line_limit_is_the_repository_ceiling() -> None:
    assert HARD_LINE_LIMIT == 800


def test_count_lines_counts_every_line(tmp_path: Path) -> None:
    assert count_lines(_write_module(tmp_path, "a.py", 137)) == 137


def test_file_at_exactly_the_budget_is_compliant(tmp_path: Path) -> None:
    """At-or-below 800 passes: 800 lines is the ceiling, not the first failure."""
    at_budget = _write_module(tmp_path, "at_budget.py", HARD_LINE_LIMIT)

    assert oversized_modules([at_budget]) == {}


def test_file_one_line_over_the_budget_is_reported(tmp_path: Path) -> None:
    over_budget = _write_module(tmp_path, "over_budget.py", HARD_LINE_LIMIT + 1)

    assert oversized_modules([over_budget]) == {"over_budget.py": 801}


def test_offenders_are_reported_with_counts_and_compliant_files_are_not(tmp_path: Path) -> None:
    paths = [
        _write_module(tmp_path, "small.py", 10),
        _write_module(tmp_path, "big.py", 1200),
        _write_module(tmp_path, "huge.py", 2000),
    ]

    assert oversized_modules(paths) == {"big.py": 1200, "huge.py": 2000}

    duplicate_names = [
        _write_module(tmp_path, "first/shared.py", 1200),
        _write_module(tmp_path, "second/shared.py", 10),
    ]
    with pytest.raises(ValueError, match="unique file names: shared.py"):
        oversized_modules(duplicate_names)


def test_explicit_budget_overrides_the_default_ceiling(tmp_path: Path) -> None:
    path = _write_module(tmp_path, "mid.py", 900)

    assert oversized_modules([path], budget=1200) == {}
    assert oversized_modules([path], budget=899) == {"mid.py": 900}


def test_empty_path_set_yields_no_offenders() -> None:
    """Callers, not this helper, own the non-empty discovery proof."""
    assert oversized_modules([]) == {}
