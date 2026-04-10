"""Civic domain API routes — offices, contests, candidacies, officeholdings, contacts."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query

from api.deps import get_db
from api.models.civics import (
    CandidacyResponse,
    CandidacySummary,
    ContactSummary,
    ContestResponse,
    OfficeListItem,
    OfficeholdingResponse,
    OfficeholderSummary,
    OfficeResponse,
)
from api.queries._common import fetch_entity_provenance
from api.queries.civics import (
    fetch_candidacy_detail,
    fetch_contacts_by_owner,
    fetch_contest_candidacies,
    fetch_contest_detail,
    fetch_jurisdiction_exists,
    fetch_office_detail,
    fetch_office_officeholders,
    fetch_officeholding_detail,
    fetch_offices_by_jurisdiction,
)

router = APIRouter()


def _fetch_or_404(row: dict | None, not_found_detail: str) -> dict:
    if row is None:
        raise HTTPException(status_code=404, detail=not_found_detail)
    return row


@router.get("/offices/{office_id}", response_model=OfficeResponse)
def get_office(office_id: UUID, conn: psycopg.Connection = Depends(get_db)) -> OfficeResponse:
    row = _fetch_or_404(fetch_office_detail(conn, office_id), "Office not found")

    officeholders = fetch_office_officeholders(conn, office_id)
    row["current_officeholders"] = [OfficeholderSummary.model_validate(oh) for oh in officeholders]

    incomplete_states: list[str] = []
    if not officeholders:
        incomplete_states.append("no_officeholder")
    row["incomplete_data_states"] = incomplete_states

    row["sources"] = fetch_entity_provenance(conn, "office", office_id)
    return OfficeResponse.model_validate(row)


@router.get("/contests/{contest_id}", response_model=ContestResponse)
def get_contest(contest_id: UUID, conn: psycopg.Connection = Depends(get_db)) -> ContestResponse:
    row = _fetch_or_404(fetch_contest_detail(conn, contest_id), "Contest not found")

    candidacies = fetch_contest_candidacies(conn, contest_id)
    row["candidacies"] = [CandidacySummary.model_validate(c) for c in candidacies]

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


ContactOwnerType = Literal["person", "organization", "office", "officeholding", "candidacy"]


@router.get("/contacts", response_model=list[ContactSummary])
def get_contacts(
    owner_type: ContactOwnerType = Query(...),
    owner_id: UUID = Query(...),
    conn: psycopg.Connection = Depends(get_db),
) -> list[ContactSummary]:
    rows = fetch_contacts_by_owner(conn, owner_type, owner_id)
    return [ContactSummary.model_validate(r) for r in rows]
