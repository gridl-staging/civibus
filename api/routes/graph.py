from __future__ import annotations

from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException

from api.deps import get_db
from api.models import EntityRelationshipsResponse, GraphNeighbor
from api.models.graph import GraphEntityType
from api.queries_graph import fetch_entity_relationships

router = APIRouter()


@router.get(
    "/graph/{entity_type}/{entity_id}/relationships",
    response_model=EntityRelationshipsResponse,
)
def get_entity_relationships(
    entity_type: GraphEntityType,
    entity_id: UUID,
    conn: psycopg.Connection = Depends(get_db),
) -> EntityRelationshipsResponse:
    """Return the graph neighborhood of an entity."""
    try:
        neighbors_raw = fetch_entity_relationships(conn, entity_type, entity_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    neighbors = [GraphNeighbor.model_validate(n) for n in neighbors_raw]
    return EntityRelationshipsResponse(
        entity_type=entity_type,
        entity_id=entity_id,
        neighbors=neighbors,
        total_count=len(neighbors),
    )
