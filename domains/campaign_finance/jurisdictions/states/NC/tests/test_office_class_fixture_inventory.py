from __future__ import annotations

from pathlib import Path

from _test_helpers import markdown_table_under_heading, read
from test_office_universe_inventory import (
    REQUIRED_COLUMNS,
    EVIDENCE_TOKEN_BY_FIXTURE_SLUG,
    UNIVERSE_DOC_PATH,
)


REPO_ROOT = Path(__file__).resolve().parents[6]
PER_OFFICE_CLASS_DIR = Path(__file__).resolve().parent / "fixtures" / "per_office_class"


def _in_scope_rows() -> list[dict[str, str]]:
    headers, rows = markdown_table_under_heading(read(UNIVERSE_DOC_PATH), "Universe Table")
    assert headers == REQUIRED_COLUMNS
    return [row for row in rows if row["scope_decision"].startswith("Include")]


def _artifact_basenames(row: dict[str, str]) -> list[str]:
    return [Path(path.strip()).name for path in row["artifact_paths"].split(";") if path.strip()]


def test_in_scope_universe_rows_have_exactly_one_fixture_directory() -> None:
    rows = _in_scope_rows()
    assert rows, "Universe Table must have at least one in-scope row"

    for row in rows:
        slug = row["fixture_slug"]
        slug_dir = PER_OFFICE_CLASS_DIR / slug
        assert slug_dir.is_dir(), f"missing per_office_class fixture directory for slug={slug}"


def test_per_office_class_directories_match_in_scope_fixture_slugs_exactly() -> None:
    rows = _in_scope_rows()
    expected_slugs = {row["fixture_slug"] for row in rows}

    assert PER_OFFICE_CLASS_DIR.is_dir(), f"missing per_office_class fixture root: {PER_OFFICE_CLASS_DIR}"
    actual_slug_dirs = {child.name for child in PER_OFFICE_CLASS_DIR.iterdir() if child.is_dir()}

    extras = actual_slug_dirs - expected_slugs
    missing = expected_slugs - actual_slug_dirs
    assert not extras, f"unexpected per_office_class directories: {sorted(extras)}"
    assert not missing, f"missing per_office_class directories: {sorted(missing)}"


def test_each_fixture_directory_has_exactly_one_html_and_one_csv_evidence_file() -> None:
    rows = _in_scope_rows()

    for row in rows:
        slug = row["fixture_slug"]
        slug_dir = PER_OFFICE_CLASS_DIR / slug
        files = sorted(child for child in slug_dir.iterdir() if child.is_file())

        suffixes = sorted(child.suffix.lower() for child in files)
        assert suffixes == [".csv", ".html"], (
            f"slug={slug} must contain exactly one .html and one .csv evidence file; found {suffixes}"
        )

        expected_basenames = set(_artifact_basenames(row))
        actual_basenames = {child.name for child in files}
        assert actual_basenames == expected_basenames, (
            f"slug={slug} evidence files {sorted(actual_basenames)} do not match Stage 1 "
            f"artifact_paths {sorted(expected_basenames)}"
        )


def test_each_fixture_directory_retains_expected_evidence_token() -> None:
    rows = _in_scope_rows()

    for row in rows:
        slug = row["fixture_slug"]
        token = EVIDENCE_TOKEN_BY_FIXTURE_SLUG.get(slug)
        if token is None:
            continue
        slug_dir = PER_OFFICE_CLASS_DIR / slug
        contains_token = any(
            token in child.read_text(encoding="utf-8", errors="ignore")
            for child in slug_dir.iterdir()
            if child.is_file()
        )
        assert contains_token, f"slug={slug} per_office_class directory missing evidence token {token!r}"
