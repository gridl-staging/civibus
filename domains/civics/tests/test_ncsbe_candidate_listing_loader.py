"""Integration tests for NC SBE candidate-listing loader persistence."""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

import psycopg
import pytest

from core.db import select_active_source_record_by_key


pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[3]
CSV_FIXTURE_PATH = (
    REPO_ROOT
    / "docs"
    / "reference"
    / "research"
    / "artifacts"
    / "nc_2026_civic_calendar_probe_2026_04_25"
    / "local_candidate_listing_2026.csv"
)
CANONICAL_NCSBE_CANDIDATE_LISTING_SOURCE_ID = "ncsbe_candidate_listing_2026"
CANONICAL_NCSBE_CANDIDATE_LISTING_SOURCE_URL = (
    "https://s3.amazonaws.com/dl.ncsbe.gov/Elections/2026/Candidate%20Filing/Candidate_Listing_2026.csv"
)


def _write_fixture_slice(tmp_path: Path, *, row_limit: int) -> Path:
    csv_path = tmp_path / "candidate_listing_slice.csv"
    with CSV_FIXTURE_PATH.open("r", encoding="utf-8", newline="") as source_file:
        reader = csv.DictReader(source_file)
        assert reader.fieldnames is not None
        selected_rows = []
        for index, row in enumerate(reader):
            if index >= row_limit:
                break
            selected_rows.append(row)
        headers = list(reader.fieldnames)

    with csv_path.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=headers)
        writer.writeheader()
        writer.writerows(selected_rows)
    return csv_path


def _read_csv_rows(csv_path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with csv_path.open("r", encoding="utf-8", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        assert reader.fieldnames is not None
        return list(reader.fieldnames), list(reader)


def _write_rows(csv_path: Path, *, headers: list[str], rows: list[dict[str, str]]) -> Path:
    with csv_path.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)
    return csv_path


def _rows_for_contest_counties(
    *,
    contest_name: str,
    candidate_name: str,
    counties: set[str],
) -> tuple[list[str], list[dict[str, str]]]:
    headers, source_rows = _read_csv_rows(CSV_FIXTURE_PATH)
    selected_rows: list[dict[str, str]] = []
    for row in source_rows:
        if row["contest_name"].strip() != contest_name:
            continue
        if row["name_on_ballot"].strip() != candidate_name:
            continue
        if row["county_name"].strip() not in counties:
            continue
        selected_rows.append(dict(row))
    return headers, selected_rows


def test_load_candidate_listing_persists_known_answer_with_parent_rows(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    from domains.civics.loaders.ncsbe_candidate_listing import load_candidate_listing

    csv_path = _write_fixture_slice(tmp_path, row_limit=80)

    summary = load_candidate_listing(
        db_conn,
        csv_path=csv_path,
        today=date(2026, 11, 3),
    )

    assert summary.rows_read == 80
    assert summary.rows_loaded == 80
    assert summary.rows_skipped_out_of_window == 0
    assert summary.candidacies_upserted > 0
    assert summary.contests_upserted > 0

    row = db_conn.execute(
        """
        SELECT
            o.name,
            d.name,
            ct.name,
            c.name_on_ballot,
            c.is_unexpired_term,
            c.committee_id,
            c.raw_fields->>'party_candidate'
        FROM civic.candidacy c
        JOIN civic.contest ct ON ct.id = c.contest_id
        JOIN civic.office o ON o.id = ct.office_id
        JOIN civic.electoral_division d ON d.id = ct.electoral_division_id
        JOIN core.person p ON p.id = c.person_id
        WHERE p.canonical_name = 'Daryl Farrow'
          AND d.name = 'NC'
          AND ct.name = 'US SENATE'
        LIMIT 1
        """
    ).fetchone()

    assert row is not None
    assert row[0] == "US SENATE"
    assert row[1] == "NC"
    assert row[2] == "US SENATE"
    assert row[3] == "Daryl Farrow"
    assert row[4] is False
    assert row[5] is None
    assert row[6] == "DEM"


def test_load_candidate_listing_is_rerun_safe_with_single_active_source_record_per_key(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    from domains.civics.loaders.ncsbe_candidate_listing import load_candidate_listing

    csv_path = _write_fixture_slice(tmp_path, row_limit=50)

    first = load_candidate_listing(
        db_conn,
        csv_path=csv_path,
        today=date(2026, 11, 3),
    )
    second = load_candidate_listing(
        db_conn,
        csv_path=csv_path,
        today=date(2026, 11, 3),
    )

    assert first.rows_loaded == second.rows_loaded == 50
    assert first.candidacies_upserted > 0
    assert second.candidacies_upserted == 0
    assert second.source_records_inserted == 0
    assert second.source_records_reused == second.rows_loaded

    data_source_row = db_conn.execute(
        """
        SELECT id, source_url
        FROM core.data_source
        WHERE domain = 'civics'
          AND jurisdiction = 'NC'
          AND name = %s
        """,
        (CANONICAL_NCSBE_CANDIDATE_LISTING_SOURCE_ID,),
    ).fetchone()
    assert data_source_row is not None
    data_source_id = data_source_row[0]
    assert data_source_row[1] == CANONICAL_NCSBE_CANDIDATE_LISTING_SOURCE_URL

    data_source_count = db_conn.execute(
        """
        SELECT COUNT(*)
        FROM core.data_source
        WHERE domain = 'civics'
          AND jurisdiction = 'NC'
          AND name = %s
        """,
        (CANONICAL_NCSBE_CANDIDATE_LISTING_SOURCE_ID,),
    ).fetchone()[0]
    assert data_source_count == 1

    duplicate_active_keys = db_conn.execute(
        """
        SELECT source_record_key
        FROM core.source_record
        WHERE data_source_id = %s
          AND superseded_by IS NULL
          AND source_record_key LIKE %s
        GROUP BY source_record_key
        HAVING COUNT(*) > 1
        """,
        (data_source_id, f"{CANONICAL_NCSBE_CANDIDATE_LISTING_SOURCE_ID}:%"),
    ).fetchall()
    assert duplicate_active_keys == []

    active_record_data_source_count = db_conn.execute(
        """
        SELECT COUNT(DISTINCT data_source_id)
        FROM core.source_record
        WHERE superseded_by IS NULL
          AND source_record_key LIKE %s
        """,
        (f"{CANONICAL_NCSBE_CANDIDATE_LISTING_SOURCE_ID}:%",),
    ).fetchone()[0]
    assert active_record_data_source_count == 1

    sample_key_row = db_conn.execute(
        """
        SELECT source_record_key
        FROM core.source_record
        WHERE data_source_id = %s
          AND superseded_by IS NULL
          AND source_record_key LIKE %s
        ORDER BY source_record_key ASC
        LIMIT 1
        """,
        (data_source_id, f"{CANONICAL_NCSBE_CANDIDATE_LISTING_SOURCE_ID}:%"),
    ).fetchone()
    assert sample_key_row is not None

    active_source_record = select_active_source_record_by_key(
        db_conn,
        data_source_id=data_source_id,
        source_record_key=sample_key_row[0],
    )
    assert active_source_record is not None


def test_load_candidate_listing_person_stub_resolution_and_five_year_window(
    db_conn: psycopg.Connection,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core import db as core_db
    import domains.civics.loaders.ncsbe_candidate_listing as candidate_loader

    headers, source_rows = _read_csv_rows(CSV_FIXTURE_PATH)
    current_row = dict(source_rows[1])
    old_row = dict(source_rows[2])
    old_row["election_dt"] = "11/08/2016"
    old_row["name_on_ballot"] = "Old Candidate Example"
    old_row["first_name"] = "OLD"
    old_row["middle_name"] = ""
    old_row["last_name"] = "CANDIDATE"
    old_row["party_candidate"] = "DEM"
    old_row["party_contest"] = "OLD-CMTE"

    csv_path = _write_rows(tmp_path / "candidate_listing_window.csv", headers=headers, rows=[current_row, old_row])

    observed_stub_calls: list[tuple[dict[str, str], object]] = []

    def _capture_stub_resolution(conn, person, address):  # type: ignore[no-untyped-def]
        observed_stub_calls.append((dict(person.identifiers), address))
        return core_db.resolve_person_by_name_and_zip(conn, person, address)

    monkeypatch.setattr(candidate_loader, "resolve_person_by_name_and_zip", _capture_stub_resolution)

    summary = candidate_loader.load_candidate_listing(
        db_conn,
        csv_path=csv_path,
        today=date(2026, 11, 3),
    )

    assert summary.rows_read == 2
    assert summary.rows_loaded == 1
    assert summary.rows_skipped_out_of_window == 1
    assert summary.candidacies_upserted == 1

    assert observed_stub_calls
    assert all(call[0] == {"civic_candidacy_stub": "true"} for call in observed_stub_calls)
    assert all(call[1] is None for call in observed_stub_calls)

    old_person_exists = db_conn.execute(
        "SELECT EXISTS(SELECT 1 FROM core.person WHERE canonical_name = %s)",
        ("Old Candidate Example",),
    ).fetchone()[0]
    assert old_person_exists is False


def test_load_candidate_listing_does_not_derive_committee_id_from_party_contest(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    from domains.civics.loaders.ncsbe_candidate_listing import load_candidate_listing

    headers, source_rows = _read_csv_rows(CSV_FIXTURE_PATH)
    mutated_row = dict(source_rows[0])
    mutated_row["party_contest"] = "a6f3c214-bb7a-4be0-a1ec-f2b4ef6fd7c0"
    mutated_row["name_on_ballot"] = "Committee Mapping Guardrail"
    mutated_row["first_name"] = "COMMITTEE"
    mutated_row["middle_name"] = ""
    mutated_row["last_name"] = "GUARDRAIL"

    csv_path = _write_rows(tmp_path / "candidate_listing_committee_guardrail.csv", headers=headers, rows=[mutated_row])

    summary = load_candidate_listing(
        db_conn,
        csv_path=csv_path,
        today=date(2026, 11, 3),
    )

    assert summary.rows_loaded == 1
    persisted_row = db_conn.execute(
        """
        SELECT c.committee_id, c.raw_fields->>'party_contest'
        FROM civic.candidacy c
        JOIN core.person p ON p.id = c.person_id
        WHERE p.canonical_name = 'Committee Mapping Guardrail'
        LIMIT 1
        """
    ).fetchone()
    assert persisted_row is not None
    assert persisted_row[0] is None
    assert persisted_row[1] == "a6f3c214-bb7a-4be0-a1ec-f2b4ef6fd7c0"


def test_load_candidate_listing_collapses_repeated_statewide_contests_across_counties(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    from domains.civics.loaders.ncsbe_candidate_listing import load_candidate_listing

    headers, rows = _rows_for_contest_counties(
        contest_name="US SENATE",
        candidate_name="Daryl Farrow",
        counties={"ALAMANCE", "ALEXANDER"},
    )
    assert len(rows) == 2

    csv_path = _write_rows(tmp_path / "candidate_listing_us_senate_two_counties.csv", headers=headers, rows=rows)
    summary = load_candidate_listing(
        db_conn,
        csv_path=csv_path,
        today=date(2026, 11, 3),
    )
    assert summary.rows_loaded == 2

    contest_rows = db_conn.execute(
        """
        SELECT d.division_type, d.name, COUNT(*) AS contest_count
        FROM civic.contest ct
        JOIN civic.electoral_division d ON d.id = ct.electoral_division_id
        WHERE ct.name = 'US SENATE'
        GROUP BY d.division_type, d.name
        """
    ).fetchall()
    assert contest_rows == [("statewide", "NC", 1)]

    candidacy_count = db_conn.execute(
        """
        SELECT COUNT(*)
        FROM civic.candidacy c
        JOIN civic.contest ct ON ct.id = c.contest_id
        JOIN core.person p ON p.id = c.person_id
        WHERE ct.name = 'US SENATE'
          AND p.canonical_name = 'Daryl Farrow'
        """
    ).fetchone()[0]
    assert candidacy_count == 1


def test_load_candidate_listing_collapses_nc_state_senate_district_across_counties(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    from domains.civics.loaders.ncsbe_candidate_listing import load_candidate_listing

    headers, rows = _rows_for_contest_counties(
        contest_name="NC STATE SENATE DISTRICT 01",
        candidate_name="Cole Johnson",
        counties={"BERTIE", "CAMDEN"},
    )
    assert len(rows) == 2

    csv_path = _write_rows(tmp_path / "candidate_listing_nc_senate_two_counties.csv", headers=headers, rows=rows)
    summary = load_candidate_listing(
        db_conn,
        csv_path=csv_path,
        today=date(2026, 11, 3),
    )
    assert summary.rows_loaded == 2

    contest_rows = db_conn.execute(
        """
        SELECT d.division_type, d.name, d.district_number, COUNT(*) AS contest_count
        FROM civic.contest ct
        JOIN civic.electoral_division d ON d.id = ct.electoral_division_id
        WHERE ct.name = 'NC STATE SENATE DISTRICT 01'
        GROUP BY d.division_type, d.name, d.district_number
        """
    ).fetchall()
    assert contest_rows == [("state_legislative_upper", "NC SENATE DISTRICT 1", "1", 1)]

    candidacy_count = db_conn.execute(
        """
        SELECT COUNT(*)
        FROM civic.candidacy c
        JOIN civic.contest ct ON ct.id = c.contest_id
        JOIN core.person p ON p.id = c.person_id
        WHERE ct.name = 'NC STATE SENATE DISTRICT 01'
          AND p.canonical_name = 'Cole Johnson'
        """
    ).fetchone()[0]
    assert candidacy_count == 1


def test_load_candidate_listing_repairs_prefixed_statewide_state_senate_rows_on_rerun(
    db_conn: psycopg.Connection,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import domains.civics.loaders.ncsbe_candidate_listing as candidate_loader

    headers, rows = _rows_for_contest_counties(
        contest_name="NC STATE SENATE DISTRICT 01",
        candidate_name="Cole Johnson",
        counties={"BERTIE", "CAMDEN"},
    )
    assert len(rows) == 2

    csv_path = _write_rows(tmp_path / "candidate_listing_nc_senate_replay.csv", headers=headers, rows=rows)

    original_derive_scope = candidate_loader._derive_division_scope

    def _derive_scope_with_prefixed_bug(
        parsed_row: candidate_loader.CandidateListingRow,
    ) -> candidate_loader._DivisionScope:
        if parsed_row.contest_name == "NC STATE SENATE DISTRICT 01":
            return candidate_loader._DivisionScope(division_name="NC", division_type="statewide")
        return original_derive_scope(parsed_row)

    monkeypatch.setattr(candidate_loader, "_derive_division_scope", _derive_scope_with_prefixed_bug)
    buggy_summary = candidate_loader.load_candidate_listing(
        db_conn,
        csv_path=csv_path,
        today=date(2026, 11, 3),
    )
    assert buggy_summary.rows_loaded == 2
    monkeypatch.setattr(candidate_loader, "_derive_division_scope", original_derive_scope)

    repaired_summary = candidate_loader.load_candidate_listing(
        db_conn,
        csv_path=csv_path,
        today=date(2026, 11, 3),
    )
    assert repaired_summary.rows_loaded == 2
    assert repaired_summary.candidacies_upserted == 0

    contest_rows = db_conn.execute(
        """
        SELECT d.division_type, d.name, d.district_number, COUNT(*)
        FROM civic.contest ct
        JOIN civic.electoral_division d ON d.id = ct.electoral_division_id
        WHERE ct.name = 'NC STATE SENATE DISTRICT 01'
        GROUP BY d.division_type, d.name, d.district_number
        ORDER BY d.division_type, d.name, d.district_number
        """
    ).fetchall()
    assert contest_rows == [("state_legislative_upper", "NC SENATE DISTRICT 1", "1", 1)]

    candidacy_rows = db_conn.execute(
        """
        SELECT p.canonical_name, COUNT(*)
        FROM civic.candidacy c
        JOIN civic.contest ct ON ct.id = c.contest_id
        JOIN core.person p ON p.id = c.person_id
        WHERE ct.name = 'NC STATE SENATE DISTRICT 01'
        GROUP BY p.canonical_name
        ORDER BY p.canonical_name
        """
    ).fetchall()
    assert candidacy_rows == [("Cole Johnson", 1)]
