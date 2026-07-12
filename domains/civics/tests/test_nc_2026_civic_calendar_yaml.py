"""Contract tests for the NC 2026 civic calendar YAML payload."""

from __future__ import annotations

from datetime import date
from pathlib import Path
import re
from uuid import UUID

import yaml

from domains.civics.types import Contest, Election, FilingDeadline, Office, ReportingPeriod

_NC_CALENDAR_PATH = Path(__file__).resolve().parent.parent / "data" / "nc_2026_civic_calendar.yaml"
_ZERO_UUID = UUID("00000000-0000-0000-0000-000000000000")
_DISTRICT_KEY_PATTERN = re.compile(
    r"^nc_(house_district_\d+|school_district_\d+|municipal_[a-z0-9_]+|county_[a-z0-9_]+)$"
)


def _load_nc_calendar() -> dict[str, list[dict[str, object]]]:
    with _NC_CALENDAR_PATH.open(encoding="utf-8") as fh:
        payload = yaml.safe_load(fh) or {}
    return payload


def _strip_division_lookup_keys(row: dict[str, object]) -> dict[str, object]:
    normalized = dict(row)
    normalized.pop("office_key", None)
    normalized.pop("election_key", None)
    normalized.pop("parent_election_key", None)
    normalized.pop("electoral_division_key", None)
    return normalized


def test_nc_calendar_has_required_top_level_sections() -> None:
    payload = _load_nc_calendar()
    assert set(payload.keys()) == {"offices", "elections", "contests", "filing_deadlines", "reporting_periods"}


def test_nc_calendar_rows_validate_against_civic_models() -> None:
    payload = _load_nc_calendar()

    offices = [Office.model_validate(_strip_division_lookup_keys(row)) for row in payload["offices"]]
    office_ids = {office.id for office in offices}

    elections = [Election.model_validate(_strip_division_lookup_keys(row)) for row in payload["elections"]]
    election_ids = {election.id for election in elections}

    contests = [Contest.model_validate(_strip_division_lookup_keys(row)) for row in payload["contests"]]
    filing_deadlines = [
        FilingDeadline.model_validate(_strip_division_lookup_keys(row)) for row in payload["filing_deadlines"]
    ]
    reporting_periods = [ReportingPeriod.model_validate(row) for row in payload["reporting_periods"]]

    for contest in contests:
        assert contest.office_id in office_ids
        assert contest.election_id in election_ids

    for filing_deadline in filing_deadlines:
        assert filing_deadline.election_id in election_ids
        assert filing_deadline.office_id in office_ids

    for reporting_period in reporting_periods:
        assert reporting_period.election_id in election_ids


def test_nc_calendar_respects_civic_sql_natural_keys() -> None:
    payload = _load_nc_calendar()

    office_models = [Office.model_validate(_strip_division_lookup_keys(row)) for row in payload["offices"]]
    office_keys = {
        (
            office.office_level,
            office.state or "",
            office.name,
            office.electoral_division_id or _ZERO_UUID,
        )
        for office in office_models
    }
    assert len(office_models) == len(office_keys)

    election_models = [Election.model_validate(_strip_division_lookup_keys(row)) for row in payload["elections"]]
    election_keys = {
        (
            election.jurisdiction_scope,
            election.state or "",
            election.county or "",
            election.municipality or "",
            election.election_date,
            election.election_type,
            election.is_special,
            election.office_id or _ZERO_UUID,
            election.electoral_division_id or _ZERO_UUID,
        )
        for election in election_models
    }
    assert len(election_models) == len(election_keys)

    contest_models = [Contest.model_validate(_strip_division_lookup_keys(row)) for row in payload["contests"]]
    contest_keys = {
        (
            contest.office_id,
            contest.electoral_division_id or _ZERO_UUID,
            contest.election_date or date.min,
            contest.election_type,
        )
        for contest in contest_models
    }
    assert len(contest_models) == len(contest_keys)

    filing_models = [
        FilingDeadline.model_validate(_strip_division_lookup_keys(row)) for row in payload["filing_deadlines"]
    ]
    filing_keys = {
        (
            filing.election_id,
            filing.office_id,
            filing.electoral_division_id or _ZERO_UUID,
            filing.deadline_kind,
        )
        for filing in filing_models
    }
    assert len(filing_models) == len(filing_keys)

    reporting_models = [ReportingPeriod.model_validate(row) for row in payload["reporting_periods"]]
    reporting_keys = {(reporting.election_id, reporting.period_name) for reporting in reporting_models}
    assert len(reporting_models) == len(reporting_keys)


def test_nc_calendar_contains_stable_division_lookup_keys() -> None:
    payload = _load_nc_calendar()
    seeded_keys = [
        row.get("electoral_division_key") for row in payload["offices"] + payload["elections"] + payload["contests"]
    ]

    assert "nc_municipal_durham" in seeded_keys
    assert any(key == "nc_house_district_3" for key in seeded_keys)
    assert any(key == "nc_school_district_681" for key in seeded_keys)
    assert any(key == "nc_county_durham" for key in seeded_keys)
    assert all(isinstance(key, str) and _DISTRICT_KEY_PATTERN.match(key) for key in seeded_keys)


def test_nc_calendar_exposes_candidate_listing_filing_window_boundaries() -> None:
    from domains.civics.loaders.nc_calendar import resolve_candidate_listing_filing_windows

    filing_windows = resolve_candidate_listing_filing_windows(year=2026)
    assert len(filing_windows) == 1
    assert filing_windows[0].start_date == date(2025, 12, 1)
    assert filing_windows[0].end_date == date(2025, 12, 19)


def test_nc_calendar_resolves_candidate_listing_refresh_cadence_from_filing_window() -> None:
    from domains.civics.loaders.nc_calendar import resolve_candidate_listing_refresh_cadence

    assert resolve_candidate_listing_refresh_cadence(year=2026, on_date=date(2025, 12, 2)) == "daily"
    assert resolve_candidate_listing_refresh_cadence(year=2026, on_date=date(2025, 12, 18)) == "daily"
    assert resolve_candidate_listing_refresh_cadence(year=2026, on_date=date(2026, 4, 30)) == "quarterly"


def test_disjoint_filing_windows_do_not_collapse_into_one_daily_span(tmp_path: Path) -> None:
    """Two separate filing periods must produce two distinct windows; the gap between
    them must resolve to quarterly cadence, not daily."""
    from domains.civics.loaders.nc_calendar import (
        resolve_candidate_listing_filing_windows,
        resolve_candidate_listing_refresh_cadence,
    )

    election_a = "9c055fde-9fd8-4f88-8e66-6c68f88566a8"
    election_b = "2724cbc0-f391-4d9a-a5be-2c6de9303638"
    office_id = "8f00ac62-07f9-42bd-b5b6-6ec9a4ca0f0d"
    payload = {
        "offices": [],
        "elections": [
            {
                "id": election_a,
                "jurisdiction_scope": "state",
                "state": "NC",
                "county": None,
                "municipality": None,
                "election_date": "2026-03-03",
                "election_type": "primary",
                "is_special": False,
                "office_id": None,
                "electoral_division_id": None,
            },
            {
                "id": election_b,
                "jurisdiction_scope": "state",
                "state": "NC",
                "county": None,
                "municipality": None,
                "election_date": "2026-11-03",
                "election_type": "general",
                "is_special": False,
                "office_id": None,
                "electoral_division_id": None,
            },
        ],
        "contests": [],
        "filing_deadlines": [
            {
                "election_id": election_a,
                "office_id": office_id,
                "electoral_division_id": None,
                "jurisdiction_scope": "state",
                "state": "NC",
                "county": None,
                "municipality": None,
                "deadline_date": "2025-12-01",
                "deadline_kind": "candidate_filing_open",
            },
            {
                "election_id": election_a,
                "office_id": office_id,
                "electoral_division_id": None,
                "jurisdiction_scope": "state",
                "state": "NC",
                "county": None,
                "municipality": None,
                "deadline_date": "2025-12-19",
                "deadline_kind": "candidate_filing",
            },
            {
                "election_id": election_b,
                "office_id": office_id,
                "electoral_division_id": None,
                "jurisdiction_scope": "state",
                "state": "NC",
                "county": None,
                "municipality": None,
                "deadline_date": "2026-07-01",
                "deadline_kind": "candidate_filing_open",
            },
            {
                "election_id": election_b,
                "office_id": office_id,
                "electoral_division_id": None,
                "jurisdiction_scope": "state",
                "state": "NC",
                "county": None,
                "municipality": None,
                "deadline_date": "2026-07-15",
                "deadline_kind": "candidate_filing",
            },
        ],
        "reporting_periods": [],
    }
    calendar_path = tmp_path / "nc_2026_civic_calendar.yaml"
    calendar_path.write_text(yaml.safe_dump(payload), encoding="utf-8")

    windows = resolve_candidate_listing_filing_windows(calendar_path=calendar_path)
    assert len(windows) == 2
    sorted_windows = sorted(windows, key=lambda window: window.start_date)
    assert sorted_windows[0].start_date == date(2025, 12, 1)
    assert sorted_windows[0].end_date == date(2025, 12, 19)
    assert sorted_windows[1].start_date == date(2026, 7, 1)
    assert sorted_windows[1].end_date == date(2026, 7, 15)

    assert resolve_candidate_listing_refresh_cadence(calendar_path=calendar_path, on_date=date(2025, 12, 10)) == "daily"
    assert resolve_candidate_listing_refresh_cadence(calendar_path=calendar_path, on_date=date(2026, 7, 10)) == "daily"
    assert (
        resolve_candidate_listing_refresh_cadence(calendar_path=calendar_path, on_date=date(2026, 4, 1)) == "quarterly"
    )
