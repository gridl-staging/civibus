from __future__ import annotations

from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException

from api.deps import get_db
from api.models import OrgResponse, PersonResponse, PersonSlugResult
from api.queries import fetch_entity_provenance, fetch_one_row, fetch_persons_by_slug

router = APIRouter()

_PERSON_SELECT_SQL = """
    SELECT
        id,
        canonical_name,
        name_variants,
        first_name,
        middle_name,
        last_name,
        suffix,
        date_of_birth,
        year_of_birth,
        identifiers,
        primary_address_id,
        er_cluster_id,
        er_confidence
    FROM core.person
    WHERE id = %s
"""

_ORGANIZATION_SELECT_SQL = """
    SELECT
        id,
        canonical_name,
        name_variants,
        org_type,
        identifiers,
        registered_state,
        formation_date,
        dissolution_date,
        primary_address_id,
        er_cluster_id,
        er_confidence
    FROM core.organization
    WHERE id = %s
"""


def _build_entity_response(
    conn: psycopg.Connection,
    *,
    query: str,
    entity_id: UUID,
    entity_type: str,
    not_found_detail: str,
    response_model: type[PersonResponse] | type[OrgResponse],
) -> PersonResponse | OrgResponse:
    entity_row = fetch_one_row(conn, query=query, row_id=entity_id)
    if entity_row is None:
        raise HTTPException(status_code=404, detail=not_found_detail)
    entity_row["sources"] = fetch_entity_provenance(conn, entity_type, entity_id)
    return response_model.model_validate(entity_row)


@router.get("/person/by-slug/{slug}", response_model=list[PersonSlugResult])
def get_person_by_slug(slug: str, conn: psycopg.Connection = Depends(get_db)) -> list[PersonSlugResult]:
    person_rows = fetch_persons_by_slug(conn, slug)
    return [PersonSlugResult.model_validate(person_row) for person_row in person_rows]


@router.get("/person/{person_id}", response_model=PersonResponse)
def get_person(person_id: UUID, conn: psycopg.Connection = Depends(get_db)) -> PersonResponse:
    return _build_entity_response(
        conn,
        query=_PERSON_SELECT_SQL,
        entity_id=person_id,
        entity_type="person",
        not_found_detail="Person not found",
        response_model=PersonResponse,
    )


@router.get("/org/{organization_id}", response_model=OrgResponse)
def get_organization(organization_id: UUID, conn: psycopg.Connection = Depends(get_db)) -> OrgResponse:
    return _build_entity_response(
        conn,
        query=_ORGANIZATION_SELECT_SQL,
        entity_id=organization_id,
        entity_type="organization",
        not_found_detail="Organization not found",
        response_model=OrgResponse,
    )
