"""
Stub summary for jun04_3pm_4_congress_directory_ui/civibus_dev/api/routes/entities.py.
"""

from __future__ import annotations

from typing import TypeVar
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError

from api.deps import get_db
from api.models import OrgResponse, PersonResponse, PersonSlugResult
from api.portrait_policy import suppress_non_reusable_portrait_url
from api.queries import fetch_entity_provenance, fetch_one_row, fetch_persons_by_slug
from api.queries.civics import fetch_candidacies_for_person, fetch_current_office_for_person

router = APIRouter()

_ENTITY_DETAIL_ERROR_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {"detail": {"type": "string"}},
    "required": ["detail"],
    "additionalProperties": False,
}
_ENTITY_DETAIL_OPENAPI_ERROR_RESPONSES = {
    404: {
        "description": "No entity matches the requested identifier.",
        "content": {"application/json": {"schema": _ENTITY_DETAIL_ERROR_RESPONSE_SCHEMA}},
    },
    502: {
        "description": "The stored entity record violates the response contract and cannot be served.",
        "content": {"application/json": {"schema": _ENTITY_DETAIL_ERROR_RESPONSE_SCHEMA}},
    },
}

_PERSON_SELECT_SQL = """
    SELECT
        p.id,
        p.canonical_name,
        p.name_variants,
        p.first_name,
        p.middle_name,
        p.last_name,
        p.suffix,
        p.occupation,
        p.education,
        p.bio_text,
        p.bio_source_url,
        p.bio_license,
        p.bio_pulled_at,
        p.date_of_birth,
        p.year_of_birth,
        p.identifiers,
        p.primary_address_id,
        p.er_cluster_id,
        p.er_confidence,
        pp.status AS portrait_status,
        pp.rights_status AS portrait_rights_status,
        pp.source_image_url AS portrait_source_image_url,
        pp.mime_type AS portrait_mime_type,
        pp.width_px AS portrait_width_px,
        pp.height_px AS portrait_height_px
    FROM core.person p
    LEFT JOIN LATERAL (
        SELECT
            status,
            rights_status,
            source_image_url,
            mime_type,
            width_px,
            height_px
        FROM core.person_portrait
        WHERE person_id = p.id
          AND status = 'active'
        ORDER BY updated_at DESC, id ASC
        LIMIT 1
    ) pp ON TRUE
    WHERE p.id = %s
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

_PERSON_PORTRAIT_COLUMN_TO_RESPONSE_KEY = {
    "portrait_status": "status",
    "portrait_rights_status": "rights_status",
    "portrait_source_image_url": "source_image_url",
    "portrait_mime_type": "mime_type",
    "portrait_width_px": "width_px",
    "portrait_height_px": "height_px",
}

_EntityResponseT = TypeVar("_EntityResponseT", PersonResponse, OrgResponse)


def _build_entity_response(
    conn: psycopg.Connection,
    *,
    query: str,
    entity_id: UUID,
    entity_type: str,
    not_found_detail: str,
    response_model: type[_EntityResponseT],
) -> _EntityResponseT:
    entity_row = fetch_one_row(conn, query=query, row_id=entity_id)
    if entity_row is None:
        raise HTTPException(status_code=404, detail=not_found_detail)
    if entity_type == "person":
        portrait_status = entity_row.get("portrait_status")
        portrait_payload = {
            response_key: entity_row.pop(column_name, None)
            for column_name, response_key in _PERSON_PORTRAIT_COLUMN_TO_RESPONSE_KEY.items()
        }
        portrait_payload["source_image_url"] = suppress_non_reusable_portrait_url(
            portrait_payload.get("source_image_url"),
            portrait_payload.get("rights_status"),
        )
        entity_row["portrait"] = portrait_payload if portrait_status is not None else None
        entity_row["current_office"] = fetch_current_office_for_person(conn, entity_id)
        # The person -> race surface (civibus-x8b). The query resolves through
        # candidacy.candidate_number -> cf.candidate.fec_candidate_id as well
        # as person_id, because production splits chamber-switching incumbents
        # across a spine person and an FEC-only shadow person row.
        entity_row["candidacies"] = fetch_candidacies_for_person(conn, entity_id)
    entity_row["sources"] = fetch_entity_provenance(conn, entity_type, entity_id)
    try:
        return response_model.model_validate(entity_row)
    except ValidationError as exc:
        # Stored columns are schema-legal at the table but can hold shapes the
        # response contract rejects (e.g. a JSON-array ``identifiers`` where the
        # model requires an object). Surface that as a typed 502 rather than
        # letting the ValidationError escape as an untyped 500. The response
        # model stays strict; we never widen it to accept the dishonest shape.
        raise HTTPException(
            status_code=502,
            detail=(f"Stored {entity_type} record does not satisfy the response contract and cannot be served."),
        ) from exc


@router.get("/person/by-slug/{slug}", response_model=list[PersonSlugResult])
def get_person_by_slug(slug: str, conn: psycopg.Connection = Depends(get_db)) -> list[PersonSlugResult]:
    person_rows = fetch_persons_by_slug(conn, slug)
    return [PersonSlugResult.model_validate(person_row) for person_row in person_rows]


@router.get(
    "/person/{person_id}",
    response_model=PersonResponse,
    responses=_ENTITY_DETAIL_OPENAPI_ERROR_RESPONSES,
)
def get_person(person_id: UUID, conn: psycopg.Connection = Depends(get_db)) -> PersonResponse:
    return _build_entity_response(
        conn,
        query=_PERSON_SELECT_SQL,
        entity_id=person_id,
        entity_type="person",
        not_found_detail="Person not found",
        response_model=PersonResponse,
    )


@router.get(
    "/org/{organization_id}",
    response_model=OrgResponse,
    responses=_ENTITY_DETAIL_OPENAPI_ERROR_RESPONSES,
)
def get_organization(organization_id: UUID, conn: psycopg.Connection = Depends(get_db)) -> OrgResponse:
    return _build_entity_response(
        conn,
        query=_ORGANIZATION_SELECT_SQL,
        entity_id=organization_id,
        entity_type="organization",
        not_found_detail="Organization not found",
        response_model=OrgResponse,
    )
