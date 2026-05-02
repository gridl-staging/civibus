"""Shared payload builders for civic model tests."""

from __future__ import annotations

from datetime import date
from uuid import uuid4


def _payload_with_overrides(defaults: dict[str, object], overrides: dict[str, object]) -> dict[str, object]:
    payload = defaults.copy()
    payload.update(overrides)
    return payload


def build_uuid_string() -> str:
    return str(uuid4())


def build_valid_period_payload(
    start: date = date(2024, 1, 1),
    end: date = date(2025, 1, 1),
) -> dict[str, date]:
    return {"start_date": start, "end_date": end}


def build_office_payload(**overrides: object) -> dict[str, object]:
    return _payload_with_overrides(
        {
            "name": "US House of Representatives",
            "office_level": "federal",
        },
        overrides,
    )


def build_electoral_division_payload(**overrides: object) -> dict[str, object]:
    return _payload_with_overrides(
        {
            "name": "NC Congressional District 1",
            "division_type": "congressional_district",
            "is_container": False,
            "state": "NC",
        },
        overrides,
    )


def build_contest_payload(**overrides: object) -> dict[str, object]:
    return _payload_with_overrides(
        {
            "name": "NC-01 2024 General",
            "election_type": "general",
            "office_id": build_uuid_string(),
            "candidate_list_incomplete": False,
        },
        overrides,
    )


def build_election_payload(**overrides: object) -> dict[str, object]:
    return _payload_with_overrides(
        {
            "jurisdiction_scope": "state",
            "state": "NC",
            "election_date": "2024-11-05",
            "election_type": "general",
            "is_special": False,
        },
        overrides,
    )


def build_filing_deadline_payload(**overrides: object) -> dict[str, object]:
    return _payload_with_overrides(
        {
            "election_id": build_uuid_string(),
            "office_id": build_uuid_string(),
            "jurisdiction_scope": "state",
            "state": "NC",
            "deadline_date": "2024-03-01",
            "deadline_kind": "candidate_filing",
        },
        overrides,
    )


def build_reporting_period_payload(**overrides: object) -> dict[str, object]:
    return _payload_with_overrides(
        {
            "election_id": build_uuid_string(),
            "period_name": "pre_general_q3",
            "period_start": "2024-07-01",
            "period_end": "2024-09-30",
            "report_due_date": "2024-10-15",
            "is_pre_election": True,
        },
        overrides,
    )


def build_candidacy_payload(**overrides: object) -> dict[str, object]:
    return _payload_with_overrides(
        {
            "person_id": build_uuid_string(),
            "contest_id": build_uuid_string(),
        },
        overrides,
    )


def build_candidacy_mvp_fields_payload(**overrides: object) -> dict[str, object]:
    return _payload_with_overrides(
        {
            "name_on_ballot": "ALEX EXAMPLE",
            "is_unexpired_term": True,
            "raw_fields": {"native_candidate_id": "123", "district": "01"},
            "committee_id": build_uuid_string(),
        },
        overrides,
    )


def build_contest_result_payload(**overrides: object) -> dict[str, object]:
    return _payload_with_overrides(
        {
            "contest_id": build_uuid_string(),
            "candidate_name_on_ballot": "ALEX EXAMPLE",
            "election_date": "2024-11-05",
        },
        overrides,
    )


def build_officeholding_payload(**overrides: object) -> dict[str, object]:
    return _payload_with_overrides(
        {
            "person_id": build_uuid_string(),
            "office_id": build_uuid_string(),
        },
        overrides,
    )


def build_office_roster_link_payload(**overrides: object) -> dict[str, object]:
    return _payload_with_overrides(
        {
            "office_id": build_uuid_string(),
            "data_source_id": build_uuid_string(),
        },
        overrides,
    )


def build_office_browse_status_payload(**overrides: object) -> dict[str, object]:
    return _payload_with_overrides(
        {
            "office_id": build_uuid_string(),
            "has_officeholder": True,
            "has_active_contest": True,
        },
        overrides,
    )
