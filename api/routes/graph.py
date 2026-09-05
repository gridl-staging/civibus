from __future__ import annotations

from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request

from api.deps import get_db
from api.middleware.logging import record_handled_exception_type
from api.models import EntityRelationshipsResponse, GraphNeighbor
from api.models.graph import GraphEntityType
from api.queries_graph import GraphEntityNotFoundError, fetch_entity_relationships

router = APIRouter()
_GRAPH_ENTITY_NOT_FOUND_DETAIL = "Graph entity not found"


@router.get(
    "/graph/{entity_type}/{entity_id}/relationships",
    response_model=EntityRelationshipsResponse,
    responses={
        404: {
            "description": "The requested graph entity was not found.",
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "detail": {
                                "type": "string",
                                "const": _GRAPH_ENTITY_NOT_FOUND_DETAIL,
                            }
                        },
                        "required": ["detail"],
                        "additionalProperties": False,
                    }
                }
            },
        }
    },
)
def get_entity_relationships(
    request: Request,
    entity_type: GraphEntityType,
    entity_id: UUID,
    conn: psycopg.Connection = Depends(get_db),
) -> EntityRelationshipsResponse:
    """Return the graph neighborhood of an entity."""
    try:
        neighbors_raw = fetch_entity_relationships(conn, entity_type, entity_id)
    except GraphEntityNotFoundError as exc:
        record_handled_exception_type(request, exc)
        raise HTTPException(status_code=404, detail=_GRAPH_ENTITY_NOT_FOUND_DETAIL) from exc

    neighbors = [GraphNeighbor.model_validate(n) for n in neighbors_raw]
    return EntityRelationshipsResponse(
        entity_type=entity_type,
        entity_id=entity_id,
        neighbors=neighbors,
        total_count=len(neighbors),
    )
