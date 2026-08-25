"""Canonical owner for the repository's hard file-size ceiling.

Several maintainability guards (`core/entity_resolution/`,
`domains/campaign_finance/quality/`, `tests/`) enforce the same 800-line hard
limit. Before this module each site re-declared the literal and two of them
disagreed on the comparison, so a file at exactly 800 lines was a failure under
one guard and a pass under the others. The repository rule is at-or-below 800:
a file is compliant at 800 lines and only an over-budget file fails.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

HARD_LINE_LIMIT = 800


def count_lines(path: Path) -> int:
    """Return the line count used by every line-budget guard."""
    return len(path.read_text(encoding="utf-8").splitlines())


def oversized_modules(paths: Iterable[Path], budget: int = HARD_LINE_LIMIT) -> dict[str, int]:
    """Map file name -> line count for every path strictly over ``budget``.

    Each path is read exactly once. An empty result means every path complied;
    callers still own the fail-closed proof that ``paths`` was non-empty. File
    names must be unique because they are the keys in the returned mapping.
    """
    line_counts: dict[str, int] = {}
    for path in paths:
        if path.name in line_counts:
            raise ValueError(f"Line-budget paths must have unique file names: {path.name}")
        line_counts[path.name] = count_lines(path)
    return {name: line_count for name, line_count in line_counts.items() if line_count > budget}
