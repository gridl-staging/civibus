"""Integration tests for the NC civic-calendar bootstrap loader."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from uuid import UUID

import psycopg
import pytest
import yaml

from domains.civics.types import ElectoralDivision, Office


pytestmark = pytest.mark.integration


def _write_calendar_yaml(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def _ensure_nc_office(conn: psycopg.Connection, office_id: UUID) -> None:
    from domains.civics.ingest import upsert_office

    upsert_office(
        conn,
        Office(
            id=office_id,
            name=f"nc_statewide_{office_id.hex[:8]}",
            office_level="state",
            state="NC",
        ),
    )


def _ensure_division(
    conn: psycopg.Connection,
    *,
    name: str,
    division_type: str,
    district_number: str | None = None,
) -> UUID:
    from domains.civics.ingest import upsert_electoral_division

    return upsert_electoral_division(
        conn,
        ElectoralDivision(
            name=name,
            division_type=division_type,
            state="NC",
            district_number=district_number,
        ),
    )


def _bootstrap_payload(office_id: UUID) -> dict[str, object]:
    county_office_id = UUID("5df89dc1-45cc-4f2f-858d-68febbaf13b2")
    municipal_office_id = UUID("340cf0e7-1d84-441f-b9b5-155c7a0e2bf7")
    school_office_id = UUID("27440525-e762-4f40-8e18-1456d1ca93fd")
    primary_id = UUID("9c055fde-9fd8-4f88-8e66-6c68f88566a8")
    runoff_id = UUID("7f8e289c-5c9b-4c7c-b3e5-58f1ebaa4400")
    general_id = UUID("2724cbc0-f391-4d9a-a5be-2c6de9303638")
    county_contest_id = UUID("4f9cd09d-9182-4d18-9c52-5af50ba9bcd0")
    municipal_contest_id = UUID("f9207f52-ff33-47ee-8ca5-f0c149f6d630")
    school_contest_id = UUID("0a184f39-6e04-406e-b8e0-6d03bf8f4f2d")

    return {
        "offices": [
            {
                "id": str(county_office_id),
                "name": "durham_county_commissioner",
                "office_level": "county",
                "state": "NC",
                "title": "County Commissioner",
                "electoral_division_key": "nc_county_durham",
            },
            {
                "id": str(municipal_office_id),
                "name": "durham_nc_city_council_member",
                "office_level": "municipal",
                "state": "NC",
                "title": "City Council Member",
                "electoral_division_key": "nc_municipal_durham",
            },
            {
                "id": str(school_office_id),
                "name": "nc_school_board_member_681",
                "office_level": "school_board",
                "state": "NC",
                "title": "School Board Member",
                "electoral_division_key": "nc_school_district_681",
            },
        ],
        "elections": [
            {
                "id": str(primary_id),
                "election_key": "nc_2026_primary",
                "jurisdiction_scope": "state",
                "state": "NC",
                "county": None,
                "municipality": None,
                "election_date": "2026-03-03",
                "election_type": "primary",
                "is_special": False,
                "office_id": str(office_id),
                "electoral_division_key": "nc_house_district_3",
            },
            {
                "id": str(runoff_id),
                "election_key": "nc_2026_runoff",
                "parent_election_key": "nc_2026_primary",
                "jurisdiction_scope": "state",
                "state": "NC",
                "county": None,
                "municipality": None,
                "election_date": "2026-05-12",
                "election_type": "runoff",
                "is_special": False,
                "office_id": str(office_id),
                "electoral_division_key": "nc_house_district_3",
            },
            {
                "id": str(general_id),
                "election_key": "nc_2026_general",
                "jurisdiction_scope": "state",
                "state": "NC",
                "county": None,
                "municipality": None,
                "election_date": "2026-11-03",
                "election_type": "general",
                "is_special": False,
                "office_id": str(office_id),
                "electoral_division_key": "nc_house_district_3",
            },
        ],
        "contests": [
            {
                "id": str(county_contest_id),
                "name": "Durham County Commissioner General 2026",
                "election_key": "nc_2026_general",
                "election_date": "2026-11-03",
                "election_type": "general",
                "office_id": str(county_office_id),
                "electoral_division_key": "nc_county_durham",
            },
            {
                "id": str(municipal_contest_id),
                "name": "Durham City Council General 2026",
                "election_key": "nc_2026_general",
                "election_date": "2026-11-03",
                "election_type": "general",
                "office_id": str(municipal_office_id),
                "electoral_division_key": "nc_municipal_durham",
            },
            {
                "id": str(school_contest_id),
                "name": "NC School Board District 681 General 2026",
                "election_key": "nc_2026_general",
                "election_date": "2026-11-03",
                "election_type": "general",
                "office_id": str(school_office_id),
                "electoral_division_key": "nc_school_district_681",
            },
        ],
        "filing_deadlines": [
            {
                "election_key": "nc_2026_primary",
                "office_id": str(office_id),
                "electoral_division_key": "nc_house_district_3",
                "jurisdiction_scope": "state",
                "state": "NC",
                "county": None,
                "municipality": None,
                "deadline_at": "2025-12-19T17:00:00-05:00",
                "deadline_kind": "candidate_filing",
            }
        ],
        "reporting_periods": [
            {
                "election_key": "nc_2026_primary",
                "period_name": "2026 Primary Election 48-Hour",
                "period_start": "2026-02-15",
                "period_end": "2026-03-03",
                "report_due_date": "2026-03-03",
                "is_pre_election": True,
                "is_post_election": False,
                "disclosure_kind": "special",
            }
        ],
    }


def test_bootstrap_inserts_primary_runoff_and_is_idempotent(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    from domains.civics.loaders.nc_calendar import load_nc_civic_calendar

    office_id = UUID("8f00ac62-07f9-42bd-b5b6-6ec9a4ca0f0d")
    _ensure_nc_office(db_conn, office_id)
    expected_county_division_id = _ensure_division(db_conn, name="nc_county_durham", division_type="county")
    expected_municipal_division_id = _ensure_division(db_conn, name="nc_municipal_durham", division_type="municipal")
    expected_school_division_id = _ensure_division(
        db_conn,
        name="nc_school_district_681",
        division_type="school_district",
        district_number="681",
    )
    expected_house_division_id = _ensure_division(
        db_conn,
        name="nc_house_district_3",
        division_type="state_legislative_lower",
        district_number="03",
    )

    payload = _bootstrap_payload(office_id)
    yaml_path = _write_calendar_yaml(tmp_path / "nc_2026_test_calendar.yaml", payload)

    first = load_nc_civic_calendar(db_conn, year=2026, calendar_path=yaml_path)
    second = load_nc_civic_calendar(db_conn, year=2026, calendar_path=yaml_path)

    assert first.office_count == second.office_count == 3
    assert first.election_count == second.election_count == 3
    assert first.contest_count == second.contest_count == 3
    assert first.filing_deadline_count == second.filing_deadline_count == 1
    assert first.reporting_period_count == second.reporting_period_count == 1
    assert first.unresolved_office_seed_count == second.unresolved_office_seed_count == 0
    assert first.unresolved_contest_seed_count == second.unresolved_contest_seed_count == 0
    assert first.election_ids_by_key["nc_2026_primary"] == second.election_ids_by_key["nc_2026_primary"]
    assert first.election_ids_by_key["nc_2026_runoff"] == second.election_ids_by_key["nc_2026_runoff"]
    assert first.parent_election_links["nc_2026_runoff"] == first.election_ids_by_key["nc_2026_primary"]

    runoff_row = db_conn.execute(
        "SELECT election_type FROM civic.election WHERE id = %s",
        (first.election_ids_by_key["nc_2026_runoff"],),
    ).fetchone()
    assert runoff_row == ("runoff",)

    deadline_row = db_conn.execute(
        "SELECT deadline_date, electoral_division_id FROM civic.filing_deadline WHERE election_id = %s",
        (first.election_ids_by_key["nc_2026_primary"],),
    ).fetchone()
    assert deadline_row == (date(2025, 12, 19), expected_house_division_id)

    office_divisions = {
        row[0]: row[1]
        for row in db_conn.execute(
            "SELECT name, electoral_division_id FROM civic.office WHERE name IN (%s, %s, %s)",
            ("durham_county_commissioner", "durham_nc_city_council_member", "nc_school_board_member_681"),
        ).fetchall()
    }
    assert office_divisions == {
        "durham_county_commissioner": expected_county_division_id,
        "durham_nc_city_council_member": expected_municipal_division_id,
        "nc_school_board_member_681": expected_school_division_id,
    }

    contest_rows = db_conn.execute(
        """
        SELECT name, electoral_division_id
        FROM civic.contest
        WHERE name IN (
            'Durham County Commissioner General 2026',
            'Durham City Council General 2026',
            'NC School Board District 681 General 2026'
        )
        ORDER BY name
        """
    ).fetchall()
    assert contest_rows == [
        ("Durham City Council General 2026", expected_municipal_division_id),
        ("Durham County Commissioner General 2026", expected_county_division_id),
        ("NC School Board District 681 General 2026", expected_school_division_id),
    ]

    election_division_row = db_conn.execute(
        "SELECT electoral_division_id FROM civic.election WHERE id = %s",
        (first.election_ids_by_key["nc_2026_primary"],),
    ).fetchone()
    assert election_division_row == (expected_house_division_id,)


def test_loader_cli_missing_yaml_returns_nonzero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from domains.civics.loaders.nc_calendar import main

    exit_code = main(["--year", "2026", "--calendar-path", str(tmp_path / "missing.yaml")])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "Calendar YAML file not found" in captured.err


def test_loader_cli_invalid_yaml_returns_nonzero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from domains.civics.loaders.nc_calendar import main

    broken_yaml = tmp_path / "broken.yaml"
    broken_yaml.write_text("elections: [\n", encoding="utf-8")

    exit_code = main(["--year", "2026", "--calendar-path", str(broken_yaml)])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "Failed to parse calendar YAML" in captured.err


def test_loader_cli_unresolved_election_linkage_returns_nonzero(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from domains.civics.loaders.nc_calendar import main

    office_id = UUID("8f00ac62-07f9-42bd-b5b6-6ec9a4ca0f0d")
    payload = _bootstrap_payload(office_id)
    canonical_office_id = payload["offices"][0]["id"]
    for row in payload["offices"]:
        row["electoral_division_key"] = None
    for row in payload["elections"]:
        row["office_id"] = canonical_office_id
        row["electoral_division_key"] = None
    for row in payload["contests"]:
        row["office_id"] = canonical_office_id
        row["electoral_division_key"] = None
    payload["filing_deadlines"] = [
        {
            "election_key": "missing_election",
            "office_id": canonical_office_id,
            "electoral_division_key": None,
            "jurisdiction_scope": "state",
            "state": "NC",
            "county": None,
            "municipality": None,
            "deadline_at": "2025-12-19T17:00:00-05:00",
            "deadline_kind": "candidate_filing",
        }
    ]
    yaml_path = _write_calendar_yaml(tmp_path / "bad_linkage.yaml", payload)

    exit_code = main(["--year", "2026", "--calendar-path", str(yaml_path)])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "Unresolved election linkage" in captured.err


def test_loader_reports_unresolved_office_and_contest_rows_without_rewriting_resolved_rows(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    from domains.civics.loaders.nc_calendar import load_nc_civic_calendar

    office_id = UUID("8f00ac62-07f9-42bd-b5b6-6ec9a4ca0f0d")
    _ensure_nc_office(db_conn, office_id)
    _ensure_division(db_conn, name="nc_county_durham", division_type="county")
    _ensure_division(db_conn, name="nc_municipal_durham", division_type="municipal")
    _ensure_division(
        db_conn,
        name="nc_school_district_681",
        division_type="school_district",
        district_number="681",
    )
    _ensure_division(
        db_conn,
        name="nc_house_district_3",
        division_type="state_legislative_lower",
        district_number="03",
    )

    payload = _bootstrap_payload(office_id)
    yaml_path = _write_calendar_yaml(tmp_path / "nc_2026_mixed_calendar.yaml", payload)
    first = load_nc_civic_calendar(db_conn, year=2026, calendar_path=yaml_path)
    assert first.unresolved_office_seed_count == 0
    assert first.unresolved_contest_seed_count == 0

    payload["offices"][0]["electoral_division_key"] = "nc_county_missing"
    payload["contests"][0]["electoral_division_key"] = "nc_county_missing"
    mixed_yaml_path = _write_calendar_yaml(tmp_path / "nc_2026_unresolved_calendar.yaml", payload)
    second = load_nc_civic_calendar(db_conn, year=2026, calendar_path=mixed_yaml_path)

    assert second.unresolved_office_seed_count == 1
    assert second.unresolved_contest_seed_count == 1
    preserved_row = db_conn.execute(
        """
        SELECT electoral_division_id
        FROM civic.office
        WHERE name = 'durham_county_commissioner'
        """
    ).fetchone()
    assert preserved_row is not None


def test_loader_reports_unresolved_election_and_deadline_rows_without_null_writes(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    from domains.civics.loaders.nc_calendar import load_nc_civic_calendar

    office_id = UUID("8f00ac62-07f9-42bd-b5b6-6ec9a4ca0f0d")
    _ensure_nc_office(db_conn, office_id)
    _ensure_division(db_conn, name="nc_county_durham", division_type="county")
    _ensure_division(db_conn, name="nc_municipal_durham", division_type="municipal")
    _ensure_division(
        db_conn,
        name="nc_school_district_681",
        division_type="school_district",
        district_number="681",
    )
    _ensure_division(
        db_conn,
        name="nc_house_district_3",
        division_type="state_legislative_lower",
        district_number="03",
    )

    payload = _bootstrap_payload(office_id)
    payload["elections"].append(
        {
            "id": "f6f53cca-d593-4ee9-85b5-2c50a6b7c858",
            "election_key": "nc_2026_special_missing_division",
            "jurisdiction_scope": "state",
            "state": "NC",
            "county": None,
            "municipality": None,
            "election_date": "2026-08-11",
            "election_type": "special",
            "is_special": True,
            "office_id": str(office_id),
            "electoral_division_key": "nc_house_district_missing",
        }
    )
    payload["filing_deadlines"].append(
        {
            "election_key": "nc_2026_primary",
            "office_id": str(office_id),
            "electoral_division_key": "nc_house_district_missing",
            "jurisdiction_scope": "state",
            "state": "NC",
            "county": None,
            "municipality": None,
            "deadline_at": "2026-01-11T17:00:00-05:00",
            "deadline_kind": "candidate_withdrawal",
        }
    )
    mixed_yaml_path = _write_calendar_yaml(tmp_path / "nc_2026_unresolved_election_deadline.yaml", payload)
    summary = load_nc_civic_calendar(db_conn, year=2026, calendar_path=mixed_yaml_path)

    assert summary.unresolved_election_seed_count == 1
    assert summary.unresolved_filing_deadline_seed_count == 1
    missing_election_row = db_conn.execute(
        "SELECT 1 FROM civic.election WHERE id = %s",
        ("f6f53cca-d593-4ee9-85b5-2c50a6b7c858",),
    ).fetchone()
    assert missing_election_row is None
    missing_deadline_row = db_conn.execute(
        """
        SELECT 1
        FROM civic.filing_deadline
        WHERE election_id = %s
          AND deadline_kind = 'candidate_withdrawal'
        """,
        (summary.election_ids_by_key["nc_2026_primary"],),
    ).fetchone()
    assert missing_deadline_row is None


def test_loader_skips_dependents_of_skipped_unresolved_elections_without_abort(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    from domains.civics.loaders.nc_calendar import load_nc_civic_calendar

    office_id = UUID("8f00ac62-07f9-42bd-b5b6-6ec9a4ca0f0d")
    _ensure_nc_office(db_conn, office_id)
    _ensure_division(db_conn, name="nc_county_durham", division_type="county")
    _ensure_division(db_conn, name="nc_municipal_durham", division_type="municipal")
    _ensure_division(
        db_conn,
        name="nc_school_district_681",
        division_type="school_district",
        district_number="681",
    )
    _ensure_division(
        db_conn,
        name="nc_house_district_3",
        division_type="state_legislative_lower",
        district_number="03",
    )

    payload = _bootstrap_payload(office_id)
    payload["elections"].append(
        {
            "id": "48fe0cdf-abca-4836-a67f-80f8ac743612",
            "election_key": "nc_2026_special_missing_division",
            "jurisdiction_scope": "state",
            "state": "NC",
            "county": None,
            "municipality": None,
            "election_date": "2026-08-11",
            "election_type": "special",
            "is_special": True,
            "office_id": str(office_id),
            "electoral_division_key": "nc_house_district_missing",
        }
    )
    payload["elections"].append(
        {
            "id": "cf546e70-e7ea-46cd-b907-e8988e427945",
            "election_key": "nc_2026_special_runoff",
            "parent_election_key": "nc_2026_special_missing_division",
            "jurisdiction_scope": "state",
            "state": "NC",
            "county": None,
            "municipality": None,
            "election_date": "2026-09-15",
            "election_type": "runoff",
            "is_special": True,
            "office_id": str(office_id),
            "electoral_division_key": "nc_house_district_3",
        }
    )
    payload["contests"].append(
        {
            "id": "d9fed1ce-132a-4582-86fd-76707184a2d7",
            "name": "NC Special Missing Division Contest",
            "election_key": "nc_2026_special_missing_division",
            "election_date": "2026-08-11",
            "election_type": "special",
            "office_id": str(office_id),
            "electoral_division_key": "nc_house_district_3",
        }
    )
    payload["filing_deadlines"].append(
        {
            "election_key": "nc_2026_special_missing_division",
            "office_id": str(office_id),
            "electoral_division_key": "nc_house_district_3",
            "jurisdiction_scope": "state",
            "state": "NC",
            "county": None,
            "municipality": None,
            "deadline_at": "2026-07-11T17:00:00-05:00",
            "deadline_kind": "candidate_filing",
        }
    )
    payload["reporting_periods"].append(
        {
            "election_key": "nc_2026_special_missing_division",
            "period_name": "2026 Special Missing Division 48-Hour",
            "period_start": "2026-07-01",
            "period_end": "2026-08-11",
            "report_due_date": "2026-08-11",
            "is_pre_election": True,
            "is_post_election": False,
            "disclosure_kind": "special",
        }
    )

    mixed_yaml_path = _write_calendar_yaml(tmp_path / "nc_2026_unresolved_dependents.yaml", payload)
    summary = load_nc_civic_calendar(db_conn, year=2026, calendar_path=mixed_yaml_path)

    assert summary.unresolved_election_seed_count == 3
    assert summary.unresolved_contest_seed_count == 1
    assert summary.unresolved_filing_deadline_seed_count == 1
    assert "nc_2026_special_missing_division" not in summary.election_ids_by_key
    assert "nc_2026_special_runoff" not in summary.election_ids_by_key

    missing_contest_row = db_conn.execute(
        "SELECT 1 FROM civic.contest WHERE name = %s",
        ("NC Special Missing Division Contest",),
    ).fetchone()
    assert missing_contest_row is None
    missing_deadline_row = db_conn.execute(
        """
        SELECT 1
        FROM civic.filing_deadline
        WHERE deadline_kind = 'candidate_filing'
          AND election_id NOT IN (
              SELECT id
              FROM civic.election
              WHERE election_type = 'primary'
          )
        """
    ).fetchone()
    assert missing_deadline_row is None
    missing_reporting_row = db_conn.execute(
        "SELECT 1 FROM civic.reporting_period WHERE period_name = %s",
        ("2026 Special Missing Division 48-Hour",),
    ).fetchone()
    assert missing_reporting_row is None


def test_loader_skips_explicit_election_id_dependents_of_skipped_elections_without_abort(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    from domains.civics.loaders.nc_calendar import load_nc_civic_calendar

    office_id = UUID("8f00ac62-07f9-42bd-b5b6-6ec9a4ca0f0d")
    _ensure_nc_office(db_conn, office_id)
    _ensure_division(db_conn, name="nc_county_durham", division_type="county")
    _ensure_division(db_conn, name="nc_municipal_durham", division_type="municipal")
    _ensure_division(
        db_conn,
        name="nc_school_district_681",
        division_type="school_district",
        district_number="681",
    )
    _ensure_division(
        db_conn,
        name="nc_house_district_3",
        division_type="state_legislative_lower",
        district_number="03",
    )

    skipped_election_id = "6f6bc713-cf85-40a1-b69d-6f5d434cf08d"
    payload = _bootstrap_payload(office_id)
    payload["elections"].append(
        {
            "id": skipped_election_id,
            "election_key": "nc_2026_special_missing_division_via_id",
            "jurisdiction_scope": "state",
            "state": "NC",
            "county": None,
            "municipality": None,
            "election_date": "2026-08-11",
            "election_type": "special",
            "is_special": True,
            "office_id": str(office_id),
            "electoral_division_key": "nc_house_district_missing",
        }
    )
    payload["contests"].append(
        {
            "id": "bf5b3117-d3f9-4740-8f49-169fcf1fc6f6",
            "name": "NC Special Missing Division Contest Via Id",
            "election_id": skipped_election_id,
            "election_date": "2026-08-11",
            "election_type": "special",
            "office_id": str(office_id),
            "electoral_division_key": "nc_house_district_3",
        }
    )
    payload["filing_deadlines"].append(
        {
            "election_id": skipped_election_id,
            "office_id": str(office_id),
            "electoral_division_key": "nc_house_district_3",
            "jurisdiction_scope": "state",
            "state": "NC",
            "county": None,
            "municipality": None,
            "deadline_at": "2026-07-11T17:00:00-05:00",
            "deadline_kind": "candidate_filing",
        }
    )
    payload["reporting_periods"].append(
        {
            "election_id": skipped_election_id,
            "period_name": "2026 Special Missing Division 48-Hour Via Id",
            "period_start": "2026-07-01",
            "period_end": "2026-08-11",
            "report_due_date": "2026-08-11",
            "is_pre_election": True,
            "is_post_election": False,
            "disclosure_kind": "special",
        }
    )

    mixed_yaml_path = _write_calendar_yaml(tmp_path / "nc_2026_unresolved_dependents_by_id.yaml", payload)
    summary = load_nc_civic_calendar(db_conn, year=2026, calendar_path=mixed_yaml_path)

    assert summary.unresolved_election_seed_count == 2
    assert summary.unresolved_contest_seed_count == 1
    assert summary.unresolved_filing_deadline_seed_count == 1
    assert "nc_2026_special_missing_division_via_id" not in summary.election_ids_by_key

    missing_contest_row = db_conn.execute(
        "SELECT 1 FROM civic.contest WHERE name = %s",
        ("NC Special Missing Division Contest Via Id",),
    ).fetchone()
    assert missing_contest_row is None
    missing_deadline_row = db_conn.execute(
        """
        SELECT 1
        FROM civic.filing_deadline
        WHERE election_id = %s
          AND deadline_kind = 'candidate_filing'
        """,
        (skipped_election_id,),
    ).fetchone()
    assert missing_deadline_row is None
    missing_reporting_row = db_conn.execute(
        "SELECT 1 FROM civic.reporting_period WHERE period_name = %s",
        ("2026 Special Missing Division 48-Hour Via Id",),
    ).fetchone()
    assert missing_reporting_row is None


def test_loader_skips_explicit_election_id_dependents_of_second_order_skipped_elections_without_abort(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    from domains.civics.loaders.nc_calendar import load_nc_civic_calendar

    office_id = UUID("2d6ed7e1-3d57-4f60-8674-f01cc64f1044")
    _ensure_nc_office(db_conn, office_id)
    _ensure_division(db_conn, name="nc_county_durham", division_type="county")
    _ensure_division(db_conn, name="nc_municipal_durham", division_type="municipal")
    _ensure_division(
        db_conn,
        name="nc_school_district_681",
        division_type="school_district",
        district_number="681",
    )
    _ensure_division(
        db_conn,
        name="nc_house_district_3",
        division_type="state_legislative_lower",
        district_number="03",
    )

    skipped_parent_election_id = "7bc6f2b6-7136-4562-b66d-e8b4e87f5861"
    skipped_child_election_id = "f1a72fa7-02f1-4a34-9485-f2f0a28dfa4f"
    payload = _bootstrap_payload(office_id)
    payload["elections"].append(
        {
            "id": skipped_parent_election_id,
            "election_key": "nc_2026_special_missing_parent_division",
            "jurisdiction_scope": "state",
            "state": "NC",
            "county": None,
            "municipality": None,
            "election_date": "2026-08-11",
            "election_type": "special",
            "is_special": True,
            "office_id": str(office_id),
            "electoral_division_key": "nc_house_district_missing",
        }
    )
    payload["elections"].append(
        {
            "id": skipped_child_election_id,
            "election_key": "nc_2026_special_missing_child_via_parent_skip",
            "parent_election_key": "nc_2026_special_missing_parent_division",
            "jurisdiction_scope": "state",
            "state": "NC",
            "county": None,
            "municipality": None,
            "election_date": "2026-09-11",
            "election_type": "runoff",
            "is_special": True,
            "office_id": str(office_id),
            "electoral_division_key": "nc_house_district_3",
        }
    )
    payload["contests"].append(
        {
            "id": "f5a80dae-c644-4607-8dd1-96a31381b78d",
            "name": "NC Special Missing Child Contest Via Id",
            "election_id": skipped_child_election_id,
            "election_date": "2026-09-11",
            "election_type": "runoff",
            "office_id": str(office_id),
            "electoral_division_key": "nc_house_district_3",
        }
    )
    payload["filing_deadlines"].append(
        {
            "election_id": skipped_child_election_id,
            "office_id": str(office_id),
            "electoral_division_key": "nc_house_district_3",
            "jurisdiction_scope": "state",
            "state": "NC",
            "county": None,
            "municipality": None,
            "deadline_at": "2026-08-28T17:00:00-05:00",
            "deadline_kind": "candidate_filing",
        }
    )
    payload["reporting_periods"].append(
        {
            "election_id": skipped_child_election_id,
            "period_name": "2026 Special Missing Child 48-Hour Via Id",
            "period_start": "2026-08-20",
            "period_end": "2026-09-11",
            "report_due_date": "2026-09-11",
            "is_pre_election": True,
            "is_post_election": False,
            "disclosure_kind": "special",
        }
    )

    mixed_yaml_path = _write_calendar_yaml(
        tmp_path / "nc_2026_second_order_unresolved_dependents_by_id.yaml",
        payload,
    )
    summary = load_nc_civic_calendar(db_conn, year=2026, calendar_path=mixed_yaml_path)

    assert summary.unresolved_election_seed_count == 3
    assert summary.unresolved_contest_seed_count == 1
    assert summary.unresolved_filing_deadline_seed_count == 1
    assert "nc_2026_special_missing_parent_division" not in summary.election_ids_by_key
    assert "nc_2026_special_missing_child_via_parent_skip" not in summary.election_ids_by_key

    missing_contest_row = db_conn.execute(
        "SELECT 1 FROM civic.contest WHERE name = %s",
        ("NC Special Missing Child Contest Via Id",),
    ).fetchone()
    assert missing_contest_row is None
    missing_deadline_row = db_conn.execute(
        """
        SELECT 1
        FROM civic.filing_deadline
        WHERE election_id = %s
          AND deadline_kind = 'candidate_filing'
        """,
        (skipped_child_election_id,),
    ).fetchone()
    assert missing_deadline_row is None
    missing_reporting_row = db_conn.execute(
        "SELECT 1 FROM civic.reporting_period WHERE period_name = %s",
        ("2026 Special Missing Child 48-Hour Via Id",),
    ).fetchone()
    assert missing_reporting_row is None
