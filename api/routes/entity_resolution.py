from __future__ import annotations

from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException

from api.deps import get_db
from api.models import (
    ERClusterDetailResponse,
    ERClusterListParams,
    ERClusterSummaryResponse,
    ERSummaryResponse,
    MatchDecisionResponse,
)
from api.models.entity_resolution import EREntityType
from api.queries import (
    fetch_entity_matches,
    fetch_er_cluster_detail,
    fetch_er_cluster_list,
    fetch_er_summary,
)
from api.routes.validation import build_query_params_dependency

router = APIRouter()

_build_cluster_list_params = build_query_params_dependency(ERClusterListParams)


@router.get("/er/clusters", response_model=list[ERClusterSummaryResponse])
def list_er_clusters(
    params: ERClusterListParams = Depends(_build_cluster_list_params),
    conn: psycopg.Connection = Depends(get_db),
) -> list[ERClusterSummaryResponse]:
    cluster_rows = fetch_er_cluster_list(conn, params)
    return [ERClusterSummaryResponse.model_validate(cluster_row) for cluster_row in cluster_rows]


@router.get("/er/clusters/{cluster_id}", response_model=ERClusterDetailResponse)
def get_er_cluster(
    cluster_id: UUID,
    conn: psycopg.Connection = Depends(get_db),
) -> ERClusterDetailResponse:
    cluster_row = fetch_er_cluster_detail(conn, cluster_id)
    if cluster_row is None:
        raise HTTPException(status_code=404, detail="ER cluster not found")
    return ERClusterDetailResponse.model_validate(cluster_row)


@router.get("/er/summary", response_model=ERSummaryResponse)
def get_er_summary(conn: psycopg.Connection = Depends(get_db)) -> ERSummaryResponse:
    summary_row = fetch_er_summary(conn)
    return ERSummaryResponse.model_validate(summary_row)


@router.get("/er/{entity_type}/{entity_id}/matches", response_model=list[MatchDecisionResponse])
def get_entity_matches(
    entity_type: EREntityType,
    entity_id: UUID,
    conn: psycopg.Connection = Depends(get_db),
) -> list[MatchDecisionResponse]:
    match_rows = fetch_entity_matches(conn, entity_type, entity_id)
    return [MatchDecisionResponse.model_validate(match_row) for match_row in match_rows]
