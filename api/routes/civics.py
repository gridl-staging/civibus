"""
Stub summary for jun04_3pm_4_congress_directory_ui/civibus_dev/api/routes/civics.py.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from collections.abc import Iterable
from typing import Any, Literal
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query

from api.deps import get_db
from api.models.campaign_finance import PublicMemberMoneySummary
from api.models.civics import (
    CandidacyResponse,
    CandidacySummary,
    ContactSummary,
    CongressMemberSummary,
    CivicGeometryFeature,
    CivicGeometryFeatureCollection,
    CivicGeometryFeatureProperties,
    ContestCandidateMoneyResponse,
    ContestCandidateMoneyRow,
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
from api.queries.campaign_finance import (
    SUPPORTED_COMMITTEE_SUMMARY_CYCLES,
    SelectedCycle,
    fetch_candidate_ie_summaries,
    fetch_candidate_public_money_summaries,
    resolve_selected_cycle,
)
from api.queries.civics import (
    GeometryLevelLiteral,
    fetch_candidacy_detail,
    fetch_contacts_by_owner,
    fetch_contest_candidacies,
    fetch_contest_candidate_links,
    fetch_contest_detail,
    fetch_country_state_geometries,
    fetch_current_federal_members,
    election_date_is_within_publish_horizon,
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
from api.routes.public_federal import (
    CANDIDATE_SUMMARY_UNAVAILABLE_OPENAPI_RESPONSE,
    build_public_federal_money_rows,
    public_ie_totals,
    public_money_totals,
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
    row["current_holder_card"] = (
        OfficeCurrentHolderCard.model_validate(officeholders[0]) if len(officeholders) == 1 else None
    )

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


@router.get("/contests/{contest_id}/candidate-money", response_model=ContestCandidateMoneyResponse)
def get_contest_candidate_money(
    contest_id: UUID,
    cycle: int | None = Query(
        default=None,
        json_schema_extra={"enum": SUPPORTED_COMMITTEE_SUMMARY_CYCLES},
    ),
    conn: psycopg.Connection = Depends(get_db),
) -> ContestCandidateMoneyResponse:
    """Return the money scoreboard for every candidacy in one contest.

    Fixed cost, three batched queries, regardless of how many candidates run:
    the candidacy-to-FEC-candidate join, then the shared public-money summary
    and independent-expenditure summary fetchers that the congress directory
    already uses. This replaces a web-layer fan-out of 4N+1 HTTP calls that
    measured ~18s on a 21-candidacy Senate contest.
    """
    _fetch_or_404(fetch_contest_detail(conn, contest_id), "Contest not found")

    try:
        selected_cycle = resolve_selected_cycle(cycle)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    links = fetch_contest_candidate_links(conn, contest_id)
    # Only candidacies that resolved to a real cf.candidate row can have money.
    linked = [link for link in links if link["candidate_id"] is not None]
    candidate_refs = [(link["candidate_id"], link["candidate_name"]) for link in linked]
    candidate_ids = [link["candidate_id"] for link in linked]

    summaries_by_candidate = fetch_candidate_public_money_summaries(conn, candidate_refs, selected_cycle)
    ie_summaries_by_candidate = fetch_candidate_ie_summaries(conn, candidate_ids, selected_cycle)

    rows = [
        _contest_candidate_money_row(
            link,
            summary=summaries_by_candidate.get(link["candidate_id"]),
            ie_summary=ie_summaries_by_candidate.get(link["candidate_id"]),
            selected_cycle=selected_cycle,
        )
        for link in links
    ]
    # Scoreboard order: biggest raiser first. Unknown money sorts last rather
    # than tying with a genuine zero, and name breaks ties deterministically.
    rows.sort(key=lambda row: (row.total_raised is None, -(row.total_raised or Decimal("0")), row.person_name))

    return ContestCandidateMoneyResponse(
        contest_id=contest_id,
        selected_cycle=selected_cycle.selected_cycle,
        candidate_count=len(rows),
        # Same owner as the outside-spending rollups below, for the same reason:
        # summing only known values floored at Decimal("0.00") could not tell a
        # race that raised nothing from a race nobody had measured, and it
        # published the second as the first.
        total_raised=_known_money_total(row.total_raised for row in rows),
        # Sum only what is known, and stay None when nothing is: a race where no
        # Schedule E was loaded has no total, and printing "$0.00 supporting"
        # as the headline would be the loudest false claim on the page.
        total_ie_support=_known_money_total(row.ie_support_total for row in rows),
        total_ie_oppose=_known_money_total(row.ie_oppose_total for row in rows),
        has_unknown_candidate_money=any(row.total_raised is None for row in rows),
        has_unknown_candidate_ie=any(row.ie_support_total is None for row in rows),
        rows=rows,
    )


def _known_money_total(values: Iterable[Decimal | None]) -> Decimal | None:
    """Total the known values, or None when none of them are known."""
    known = [value for value in values if value is not None]
    return sum(known, Decimal("0.00")) if known else None


def _contest_candidate_money_row(
    link: dict[str, Any],
    *,
    summary: dict[str, Any] | None,
    ie_summary: dict[str, Any] | None,
    selected_cycle: SelectedCycle,
) -> ContestCandidateMoneyRow:
    """Build one scoreboard row, leaving unknown money unknown.

    ``public_money_totals`` is the shared owner of "given this summary's
    coverage state, which totals should a public surface show" — the same rule
    the congress directory uses — so a race page and a member page can never
    disagree about the same candidate's headline figure.
    """
    base = {
        "candidacy_id": link["candidacy_id"],
        "person_id": link["person_id"],
        "person_name": link["person_name"],
        "party": link["party"],
        "status": link["status"],
        "incumbent_challenge": link["incumbent_challenge"],
        "fec_candidate_id": link["fec_candidate_id"],
        "candidate_id": link["candidate_id"],
        "candidate_name": link["candidate_name"],
        "candidate_slug": link["candidate_slug"],
        "candidate_slug_is_unique": bool(link["candidate_slug_is_unique"]),
        "candidate_identity_is_safe": bool(link["candidate_identity_is_safe"]),
        # ``public_ie_totals`` is the outside-spending half of the same shared
        # owner, so the race page and the member page cannot disagree about
        # whether a candidate's $0.00 is measured or missing.
        **public_ie_totals(ie_summary),
    }
    if summary is None:
        # No ``cf.candidate`` row, so no committee could have filed a Schedule A
        # against this candidacy. Routed through the same owner with ``None`` as
        # the outside-spending half above, so both halves of the row state the
        # absence the same way instead of one of them relying on has_fec_money.
        return ContestCandidateMoneyRow.model_validate({**base, "has_fec_money": False, **public_money_totals(None)})

    return ContestCandidateMoneyRow.model_validate({**base, "has_fec_money": True, **public_money_totals(summary)})


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


@router.get("/congress/members", response_model=list[CongressMemberSummary])
def get_congress_members(conn: psycopg.Connection = Depends(get_db)) -> list[CongressMemberSummary]:
    rows = fetch_current_federal_members(conn)
    for row in rows:
        row["person_detail_path"] = f"/person/{row['person_id']}"
    return [CongressMemberSummary.model_validate(row) for row in rows]


@router.get(
    "/congress/money-summaries",
    response_model=list[PublicMemberMoneySummary],
    responses=CANDIDATE_SUMMARY_UNAVAILABLE_OPENAPI_RESPONSE,
)
def get_congress_member_money_summaries(
    conn: psycopg.Connection = Depends(get_db),
) -> list[PublicMemberMoneySummary]:
    return build_public_federal_money_rows(conn)


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
    # A beyond-horizon date is the corrupt filer-typo class (/election/2929-11-08):
    # its rows are already excluded by the query's horizon bound, and the date
    # itself answers 404 rather than an empty 200 so search engines drop the
    # corrupt URLs the pre-fix sitemap submitted. In-horizon dates with no
    # contests keep the empty 200 that election_date.md's Empty state contracts,
    # so the probe only runs on the empty path.
    if not contests and not election_date_is_within_publish_horizon(conn, election_date):
        raise HTTPException(status_code=404, detail="No published election on this date")
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


@router.get(
    "/civics/geometry",
    response_model=CivicGeometryFeatureCollection,
    responses={
        404: {
            "description": "No geometry is available for the requested level and state.",
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "properties": {"detail": {"type": "string"}},
                        "required": ["detail"],
                        "additionalProperties": False,
                    }
                }
            },
        }
    },
)
def get_civics_geometry(
    level: GeometryLevelLiteral = Query(...),
    state: str = Query(..., min_length=2, max_length=2, pattern="^[A-Za-z]{2}$"),
    conn: psycopg.Connection = Depends(get_db),
) -> CivicGeometryFeatureCollection:
    rows = fetch_electoral_division_geometries(conn, level=level, state=state.upper())
    if not rows:
        raise HTTPException(status_code=404, detail=f"Geometry not found for {level} in state {state.upper()}")
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
