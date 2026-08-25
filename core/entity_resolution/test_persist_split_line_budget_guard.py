"""Line-budget guard for persist-cluster replacement test owners."""

from __future__ import annotations

from pathlib import Path

import pytest

from test_support.line_budget import HARD_LINE_LIMIT, oversized_modules

pytestmark = pytest.mark.unit

_PUBLICATION_OWNER = "test_persist_cluster_publication.py"
_ABSORPTION_PATTERN = "test_person_absorption_*.py"
_OWNER_PATTERNS = (
    _PUBLICATION_OWNER,
    _ABSORPTION_PATTERN,
)
# Every owner the Stage 3-8 split produced. Pinning the names — not just the
# globs — keeps the guard fail-closed: renaming a family off its prefix drops it
# out of the glob, and a glob-only check would stay green while silently
# stopping watching those files.
_KNOWN_ABSORPTION_OWNERS = frozenset(
    {
        "test_person_absorption_atomicity_summary.py",
        "test_person_absorption_biography_bundle.py",
        "test_person_absorption_civic_conflicts.py",
        "test_person_absorption_contact_address.py",
        "test_person_absorption_direct_dependents.py",
        "test_person_absorption_history_blockers.py",
        "test_person_absorption_provenance.py",
        "test_person_absorption_scalar_fields.py",
    }
)
_KNOWN_OWNERS = _KNOWN_ABSORPTION_OWNERS | {_PUBLICATION_OWNER}


def _persist_split_owner_paths() -> list[Path]:
    owner_dir = Path(__file__).parent
    return sorted(
        {path for pattern in _OWNER_PATTERNS for path in owner_dir.glob(pattern)},
        key=lambda path: path.name,
    )


def test_every_owner_pattern_matches_at_least_one_file() -> None:
    """No owner pattern may go empty: an empty glob must be red, not silent."""
    owner_dir = Path(__file__).parent
    matches_per_pattern = {
        pattern: sorted(path.name for path in owner_dir.glob(pattern)) for pattern in _OWNER_PATTERNS
    }

    empty_patterns = [pattern for pattern, matches in matches_per_pattern.items() if not matches]

    assert not empty_patterns, f"Persist split owner patterns matched nothing: {empty_patterns}"


def test_persist_split_replacement_owners_are_discoverable() -> None:
    """The line-budget guard must fail closed if owner globs stop matching."""
    owner_names = {path.name for path in _persist_split_owner_paths()}

    assert owner_names
    assert _PUBLICATION_OWNER in owner_names
    missing_owners = sorted(_KNOWN_OWNERS - owner_names)
    assert not missing_owners, f"Persist split replacement owners are no longer discoverable: {missing_owners}"


def test_persist_split_replacement_owners_stay_under_line_budget() -> None:
    """Replacement assertion owners must stay at or below the line budget."""
    offenders = oversized_modules(_persist_split_owner_paths())

    assert not offenders, f"Persist split replacement owners exceed {HARD_LINE_LIMIT} lines: {offenders}"
