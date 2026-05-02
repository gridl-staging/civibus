
from __future__ import annotations

import json
from datetime import date
from typing import Any, Literal
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query

from api.deps import get_db
from api.models.civics import (
    CandidacyResponse,
    CandidacySummary,
    ContactSummary,
    CivicGeometryFeature,
    CivicGeometryFeatureCollection,
    CivicGeometryFeatureProperties,
    ContestResponse,
    OfficeCurrentHolderCard,
    ElectionContestSummary,
    ElectionDateAggregateResponse,
    OfficeListItem,
    OfficeRecentContestSummary,
    OfficeholdingTimelineSummary,
    OfficeholdingResponse,
    OfficeholderSummary,
    OfficeResponse,
    UpcomingElectionTimelineEntry,
)
from api.queries._common import fetch_entity_provenance
from api.queries.civics import (
    GeometryLevelLiteral,
    fetch_candidacy_detail,
    fetch_contacts_by_owner,
    fetch_contest_candidacies,
    fetch_contest_detail,
    fetch_country_state_geometries,
    fetch_election_contests_by_date,
    fetch_electoral_division_geometries,
    fetch_office_active_contest_count,
    fetch_jurisdiction_exists,
    fetch_office_detail,
    fetch_office_officeholders,
    fetch_office_recent_contests,
    fetch_officeholding_timeline,
    fetch_officeholding_detail,
    fetch_offices_by_jurisdiction,
    fetch_state_geometry,
    fetch_upcoming_election_contests,
)

router = APIRouter()
_WINNER_CANDIDACY_STATUSES = {"elected", "won", "winner"}
_EMPTY_MAP_CONTEXT: dict[str, str | UUID | None] = {
    "selected_electoral_division_id": None,
    "selected_electoral_division_type": None,
    "selected_electoral_division_state": None,
}


def _fetch_or_404(row: dict | None, not_found_detail: str) -> dict:
    if row is None:
        raise HTTPException(status_code=404, detail=not_found_detail)
    return row


def _map_context_from_row(row: dict[str, Any]) -> dict[str, str | UUID | None] | None:
    division_id = row.get("electoral_division_id")
    division_type = row.get("electoral_division_type")
    division_state = row.get("electoral_division_state")
    if division_id is None or division_type is None or division_state is None:
        return None
    return {
        "selected_electoral_division_id": division_id,
        "selected_electoral_division_type": division_type,
        "selected_electoral_division_state": division_state,
    }


def _first_map_context(
    contests: list[dict[str, Any]],
    officeholders: list[dict[str, Any]],
    timeline: list[dict[str, Any]],
) -> dict[str, str | UUID | None]:
    for row in contests + officeholders + timeline:
        map_context = _map_context_from_row(row)
        if map_context is not None:
            return map_context
    return _EMPTY_MAP_CONTEXT.copy()


@router.get("/offices/{office_id}", response_model=OfficeResponse)
def get_office(office_id: UUID, conn: psycopg.Connection = Depends(get_db)) -> OfficeResponse:
    row = _fetch_or_404(fetch_office_detail(conn, office_id), "Office not found")

    officeholders = fetch_office_officeholders(conn, office_id)
    row["current_officeholders"] = [OfficeholderSummary.model_validate(oh) for oh in officeholders]
    row["current_holder_card"] = OfficeCurrentHolderCard.model_validate(officeholders[0]) if len(officeholders) == 1 else None

    timeline = fetch_officeholding_timeline(conn, office_id)
    row["officeholding_timeline"] = [OfficeholdingTimelineSummary.model_validate(oh) for oh in timeline]

    recent_contests = fetch_office_recent_contests(conn, office_id)
    row["recent_contests"] = [OfficeRecentContestSummary.model_validate(contest) for contest in recent_contests]
    row.update(_first_map_context(recent_contests, officeholders, timeline))

    incomplete_states: list[str] = []
    if not officeholders:
        incomplete_states.append("no_officeholder")
    if fetch_office_active_contest_count(conn, office_id) == 0:
        incomplete_states.append("no_active_contest")
    row["incomplete_data_states"] = incomplete_states

    row["sources"] = fetch_entity_provenance(conn, "office", office_id)
    return OfficeResponse.model_validate(row)


@router.get("/contests/{contest_id}", response_model=ContestResponse)
def get_contest(contest_id: UUID, conn: psycopg.Connection = Depends(get_db)) -> ContestResponse:
    row = _fetch_or_404(fetch_contest_detail(conn, contest_id), "Contest not found")

    candidacies = fetch_contest_candidacies(conn, contest_id)
    row["candidacies"] = [CandidacySummary.model_validate(c) for c in candidacies]
    winner = next(
        (c for c in candidacies if str(c.get("status") or "").strip().lower() in _WINNER_CANDIDACY_STATUSES),
        None,
    )
    row["result_winner_candidacy_id"] = winner["candidacy_id"] if winner is not None else None
    row["result_winner_person_id"] = winner["person_id"] if winner is not None else None
    row["result_winner_person_name"] = winner["person_name"] if winner is not None else None

    row["sources"] = fetch_entity_provenance(conn, "contest", contest_id)
    return ContestResponse.model_validate(row)


@router.get("/candidacies/{candidacy_id}", response_model=CandidacyResponse)
def get_candidacy(candidacy_id: UUID, conn: psycopg.Connection = Depends(get_db)) -> CandidacyResponse:
    row = _fetch_or_404(fetch_candidacy_detail(conn, candidacy_id), "Candidacy not found")
    row["sources"] = fetch_entity_provenance(conn, "candidacy", candidacy_id)
    return CandidacyResponse.model_validate(row)


@router.get("/officeholdings/{officeholding_id}", response_model=OfficeholdingResponse)
def get_officeholding(officeholding_id: UUID, conn: psycopg.Connection = Depends(get_db)) -> OfficeholdingResponse:
    row = _fetch_or_404(fetch_officeholding_detail(conn, officeholding_id), "Officeholding not found")
    row["sources"] = fetch_entity_provenance(conn, "officeholding", officeholding_id)
    return OfficeholdingResponse.model_validate(row)


@router.get("/jurisdictions/{jurisdiction_id}/offices", response_model=list[OfficeListItem])
def get_jurisdiction_offices(jurisdiction_id: UUID, conn: psycopg.Connection = Depends(get_db)) -> list[OfficeListItem]:
    if not fetch_jurisdiction_exists(conn, jurisdiction_id):
        raise HTTPException(status_code=404, detail="Jurisdiction not found")
    rows = fetch_offices_by_jurisdiction(conn, jurisdiction_id)
    return [OfficeListItem.model_validate(r) for r in rows]


@router.get("/elections/timeline/upcoming", response_model=list[UpcomingElectionTimelineEntry])
def get_upcoming_elections_timeline(conn: psycopg.Connection = Depends(get_db)) -> list[UpcomingElectionTimelineEntry]:
    contests = fetch_upcoming_election_contests(conn)
    grouped: dict[date, list[ElectionContestSummary]] = {}
    for contest in contests:
        election_date = contest["election_date"]
        grouped.setdefault(election_date, []).append(ElectionContestSummary.model_validate(contest))
    return [
        UpcomingElectionTimelineEntry(date=election_date, contests=grouped[election_date])
        for election_date in sorted(grouped)
    ]


@router.get("/elections/{election_date}", response_model=ElectionDateAggregateResponse)
def get_election_date_aggregate(
    election_date: date, conn: psycopg.Connection = Depends(get_db)
) -> ElectionDateAggregateResponse:
    contests = [
        ElectionContestSummary.model_validate(row) for row in fetch_election_contests_by_date(conn, election_date)
    ]
    return ElectionDateAggregateResponse(
        date=election_date,
        total_contests=len(contests),
        total_candidacies=sum(contest.candidate_count for contest in contests),
        contests=contests,
    )


ContactOwnerType = Literal["person", "organization", "office", "officeholding", "candidacy"]
LandingGeometryLevel = Literal["country", "state"]


def _as_geojson_feature(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "Feature",
        "geometry": row["geometry"],
        "properties": {
            "state": row["state"],
            "name": row["name"],
            "division_type": row["division_type"],
            "boundary_year": row["boundary_year"],
        },
    }


@router.get("/geometry")
def get_geometry(
    level: LandingGeometryLevel = Query(...),
    state: str | None = Query(default=None, pattern=r"^[A-Z]{2}$"),
    conn: psycopg.Connection = Depends(get_db),
) -> dict[str, Any]:
    # Keep HTTP contract ownership in routes, while geometry reads stay in queries.civics.
    if level == "country":
        rows = fetch_country_state_geometries(conn)
        return {"type": "FeatureCollection", "features": [_as_geojson_feature(row) for row in rows]}

    if state is None:
        raise HTTPException(status_code=422, detail="state is required when level=state")

    row = fetch_state_geometry(conn, state)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Geometry not found for state {state}")
    return {"type": "FeatureCollection", "features": [_as_geojson_feature(row)]}


@router.get("/civics/geometry", response_model=CivicGeometryFeatureCollection)
def get_civics_geometry(
    level: GeometryLevelLiteral = Query(...),
    state: str = Query(..., min_length=2, max_length=2, pattern="^[A-Za-z]{2}$"),
    conn: psycopg.Connection = Depends(get_db),
) -> CivicGeometryFeatureCollection:
    rows = fetch_electoral_division_geometries(conn, level=level, state=state.upper())
    features: list[CivicGeometryFeature] = []
    for row in rows:
        geometry_payload = row["geometry"]
        if isinstance(geometry_payload, str):
            geometry_payload = json.loads(geometry_payload)
        features.append(
            CivicGeometryFeature(
                geometry=geometry_payload,
                properties=CivicGeometryFeatureProperties(
                    id=row["id"],
                    name=row["name"],
                    division_type=row["division_type"],
                    state=row["state"],
                    district_number=row["district_number"],
                    boundary_year=row["boundary_year"],
                ),
            )
        )
    return CivicGeometryFeatureCollection(features=features)


@router.get("/contacts", response_model=list[ContactSummary])
def get_contacts(
    owner_type: ContactOwnerType = Query(...),
    owner_id: UUID = Query(...),
    conn: psycopg.Connection = Depends(get_db),
) -> list[ContactSummary]:
    rows = fetch_contacts_by_owner(conn, owner_type, owner_id)
    return [ContactSummary.model_validate(r) for r in rows]
