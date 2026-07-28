"""Integration tests for NC SBE candidate-listing loader persistence."""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

import psycopg
import pytest

from core.db import select_active_source_record_by_key
from domains.civics.tests.ncsbe_candidate_listing_query_probe import (
    measure_candidate_listing_queries,
    write_candidate_listing_prefix,
)


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
ROW_IDENTITY_LOOKUP_FAMILIES = (
    "source_record_lookup",
    "office_lookup",
    "electoral_division_lookup",
    "contest_lookup",
    "person_lookup",
    "candidacy_lookup",
)
RERUN_FIXED_STATEMENT_BUDGET = 10
RERUN_PER_ROW_WRITE_BUDGET = 4


def _write_fixture_slice(tmp_path: Path, *, row_limit: int) -> Path:
    return write_candidate_listing_prefix(
        CSV_FIXTURE_PATH,
        tmp_path / "candidate_listing_slice.csv",
        row_limit=row_limit,
    )


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


def test_full_csv_query_amplification_contract(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    from domains.civics.loaders.ncsbe_candidate_listing import load_candidate_listing

    row_count = 100
    csv_path = _write_fixture_slice(tmp_path, row_limit=row_count)

    result = measure_candidate_listing_queries(
        db_conn,
        csv_path=csv_path,
        today=date(2026, 11, 3),
        load_candidate_listing=load_candidate_listing,
    )

    identity_lookup_count = sum(result.families[family] for family in ROW_IDENTITY_LOOKUP_FAMILIES)
    setwise_lookup_limit = len(ROW_IDENTITY_LOOKUP_FAMILIES)
    assert result.rows == row_count
    assert result.families["unknown"] == 0
    assert identity_lookup_count <= setwise_lookup_limit, (
        f"expected at most {setwise_lookup_limit} setwise identity lookups "
        f"for {row_count} rows; actual {identity_lookup_count}"
    )


def test_full_csv_rerun_query_amplification_contract(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    from domains.civics.loaders.ncsbe_candidate_listing import load_candidate_listing

    row_count = 100
    csv_path = _write_fixture_slice(tmp_path, row_limit=row_count)
    load_candidate_listing(db_conn, csv_path=csv_path, today=date(2026, 11, 3))

    result = measure_candidate_listing_queries(
        db_conn,
        csv_path=csv_path,
        today=date(2026, 11, 3),
        load_candidate_listing=load_candidate_listing,
    )

    rerun_statement_budget = RERUN_FIXED_STATEMENT_BUDGET + RERUN_PER_ROW_WRITE_BUDGET * row_count
    assert result.rows == row_count
    assert result.families["unknown"] == 0
    assert result.total_queries <= rerun_statement_budget, (
        f"expected at most {rerun_statement_budget} statements "
        f"({RERUN_FIXED_STATEMENT_BUDGET} fixed + "
        f"{RERUN_PER_ROW_WRITE_BUDGET} per row); actual {result.total_queries}"
    )


def test_load_candidate_listing_header_only_returns_zero_write_counters(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    from domains.civics.loaders.ncsbe_candidate_listing import load_candidate_listing

    headers, _source_rows = _read_csv_rows(CSV_FIXTURE_PATH)
    csv_path = _write_rows(tmp_path / "candidate_listing_empty.csv", headers=headers, rows=[])

    summary = load_candidate_listing(db_conn, csv_path=csv_path, today=date(2026, 11, 3))

    assert summary.rows_read == 0
    assert summary.rows_loaded == 0
    assert summary.rows_skipped_out_of_window == 0
    assert summary.offices_upserted == 0
    assert summary.electoral_divisions_upserted == 0
    assert summary.contests_upserted == 0
    assert summary.candidacies_upserted == 0
    assert summary.source_records_inserted == 0
    assert summary.source_records_reused == 0


def test_load_candidate_listing_reuses_duplicate_natural_keys_and_keeps_provenance(
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
    csv_path = _write_rows(tmp_path / "candidate_listing_duplicate_keys.csv", headers=headers, rows=rows)

    summary = load_candidate_listing(db_conn, csv_path=csv_path, today=date(2026, 11, 3))

    assert summary.rows_loaded == 2
    assert summary.offices_upserted == 1
    assert summary.electoral_divisions_upserted == 1
    assert summary.contests_upserted == 1
    assert summary.candidacies_upserted == 1
    assert summary.source_records_inserted == 2
    assert summary.source_records_reused == 0
    assert db_conn.execute(
        """
        SELECT
            entity_source.entity_type,
            COUNT(DISTINCT entity_source.entity_id),
            COUNT(DISTINCT entity_source.source_record_id)
        FROM core.entity_source AS entity_source
        JOIN core.source_record AS source_record
          ON source_record.id = entity_source.source_record_id
        WHERE entity_source.extraction_role IN (
            'office',
            'electoral_division',
            'contest',
            'candidacy'
        )
          AND source_record.source_url = %s
          AND source_record.raw_fields->>'name_on_ballot' = 'Daryl Farrow'
          AND source_record.raw_fields->>'county_name' = ANY(%s::text[])
        GROUP BY entity_source.entity_type
        ORDER BY entity_source.entity_type
        """,
        (
            CANONICAL_NCSBE_CANDIDATE_LISTING_SOURCE_URL,
            ["ALAMANCE", "ALEXANDER"],
        ),
    ).fetchall() == [
        ("candidacy", 1, 2),
        ("contest", 1, 2),
        ("electoral_division", 1, 2),
        ("office", 1, 2),
    ]
    assert (
        db_conn.execute(
            """
        SELECT COUNT(*)
        FROM core.person
        WHERE first_name = 'Daryl'
          AND last_name = 'Farrow'
        """
        ).fetchone()[0]
        == 1
    )


def test_load_candidate_listing_duplicate_candidacy_keeps_earlier_coalesced_values(
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
    rows[0]["candidacy_dt"] = "12/01/2025"
    rows[0]["party_candidate"] = "DEM"
    rows[1]["candidacy_dt"] = ""
    rows[1]["party_candidate"] = ""
    csv_path = _write_rows(
        tmp_path / "candidate_listing_duplicate_candidacy_coalesce.csv",
        headers=headers,
        rows=rows,
    )

    summary = load_candidate_listing(db_conn, csv_path=csv_path, today=date(2026, 11, 3))

    assert summary.rows_loaded == 2
    assert summary.candidacies_upserted == 1
    assert db_conn.execute(
        """
        SELECT c.party, c.filing_date, COUNT(DISTINCT es.source_record_id)
        FROM civic.candidacy AS c
        JOIN civic.contest AS ct ON ct.id = c.contest_id
        JOIN core.person AS p ON p.id = c.person_id
        JOIN core.entity_source AS es
          ON es.entity_type = 'candidacy'
         AND es.entity_id = c.id
         AND es.extraction_role = 'candidacy'
        WHERE ct.name = 'US SENATE'
          AND p.canonical_name = 'Daryl Farrow'
        GROUP BY c.id, c.party, c.filing_date
        """
    ).fetchone() == ("DEM", date(2025, 12, 1), 2)


def test_load_candidate_listing_preserves_office_reuse_count_for_division_bound_row(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    from domains.civics.ingest import upsert_electoral_division, upsert_office
    from domains.civics.loaders.ncsbe_candidate_listing import load_candidate_listing
    from domains.civics.types import ElectoralDivision, Office

    headers, source_rows = _read_csv_rows(CSV_FIXTURE_PATH)
    row = dict(source_rows[0])
    row["contest_name"] = "REVIEW COUNTER OFFICE"
    csv_path = _write_rows(
        tmp_path / "candidate_listing_division_bound_office.csv",
        headers=headers,
        rows=[row],
    )
    division_id = upsert_electoral_division(
        db_conn,
        ElectoralDivision(
            name="REVIEW COUNTER DIVISION",
            division_type="statewide",
            state="NC",
        ),
    )
    upsert_office(
        db_conn,
        Office(
            name=row["contest_name"],
            office_level="state",
            state="NC",
            electoral_division_id=division_id,
        ),
    )

    summary = load_candidate_listing(db_conn, csv_path=csv_path, today=date(2026, 11, 3))

    assert summary.rows_loaded == 1
    assert summary.offices_upserted == 0
    assert db_conn.execute(
        """
        SELECT
            COUNT(*),
            COUNT(*) FILTER (WHERE electoral_division_id IS NULL),
            BOOL_OR(electoral_division_id = %s)
        FROM civic.office
        WHERE office_level = 'state'
          AND state = 'NC'
          AND name = %s
        """,
        (division_id, row["contest_name"]),
    ).fetchone() == (2, 1, True)


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
    assert second.offices_upserted == 0
    assert second.electoral_divisions_upserted == 0
    assert second.contests_upserted == 0
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

    def _capture_stub_resolution(conn, people, addresses):  # type: ignore[no-untyped-def]
        observed_stub_calls.extend(
            (dict(person.identifiers), address) for person, address in zip(people, addresses, strict=True)
        )
        return core_db.resolve_people_by_name_and_zip(conn, people, addresses)

    monkeypatch.setattr(candidate_loader, "resolve_people_by_name_and_zip", _capture_stub_resolution)

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
