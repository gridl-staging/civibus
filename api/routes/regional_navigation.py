"""HTTP routes for the bounded regional navigation projection."""

from __future__ import annotations

from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query

from api.deps import get_db
from api.models.regional_navigation import (
    RegionalChildKind,
    RegionalNavigationListResponse,
    RegionalNavigationNode,
    RegionalNodeKind,
)
from api.queries.regional_navigation import (
    list_regional_navigation_children,
    resolve_regional_navigation_node,
    search_regional_navigation_nodes,
)

router = APIRouter()

StateCodeQuery = Annotated[str, Query(min_length=2, max_length=2, pattern=r"^[A-Z]{2}$")]
SlugQuery = Annotated[
    str | None,
    Query(min_length=1, max_length=100, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$"),
]


@router.get("/regional-navigation/resolve", response_model=RegionalNavigationNode)
def resolve_regional_navigation(
    kind: RegionalNodeKind,
    state_code: StateCodeQuery,
    slug: SlugQuery = None,
    conn: psycopg.Connection = Depends(get_db),
) -> RegionalNavigationNode:
    node = resolve_regional_navigation_node(kind=kind, state_code=state_code, slug=slug, conn=conn)
    if node is None:
        raise HTTPException(status_code=404, detail="Regional navigation node not found.")
    return node


@router.get("/regional-navigation/search", response_model=RegionalNavigationListResponse)
def search_regional_navigation(
    q: Annotated[str, Query(min_length=2, max_length=100)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    conn: psycopg.Connection = Depends(get_db),
) -> RegionalNavigationListResponse:
    if len(q.strip()) < 2:
        raise HTTPException(status_code=422, detail="Search query must contain at least two non-space characters.")
    return RegionalNavigationListResponse(
        items=search_regional_navigation_nodes(query=q, limit=limit, conn=conn),
        # States are complete for the existing 50-state + DC presentation owner.
        # All non-state route families remain intentionally bounded.
        incomplete_node_kinds=["county", "municipality", "school_district", "special_district"],
        has_unsafe_omissions=True,
    )


@router.get("/regional-navigation/children", response_model=RegionalNavigationListResponse)
def get_regional_navigation_children(
    state_code: StateCodeQuery,
    kind: RegionalChildKind,
) -> RegionalNavigationListResponse:
    return RegionalNavigationListResponse(
        items=list_regional_navigation_children(state_code=state_code, kind=kind),
        incomplete_node_kinds=[kind],
        has_unsafe_omissions=True,
    )
