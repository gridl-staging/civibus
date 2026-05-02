from __future__ import annotations

import psycopg
from fastapi import APIRouter, Depends

from api.deps import get_db
from api.models import CoverageRegistryResponse, DataSourceMetadataResponse
from api.queries.metadata import fetch_data_sources_metadata, fetch_runtime_coverage_registry

router = APIRouter()


@router.get("/data-sources", response_model=list[DataSourceMetadataResponse])
def get_data_sources(conn: psycopg.Connection = Depends(get_db)) -> list[DataSourceMetadataResponse]:
    rows = fetch_data_sources_metadata(conn)
    return [DataSourceMetadataResponse.model_validate(row) for row in rows]


@router.get("/coverage/registry", response_model=list[CoverageRegistryResponse])
def get_runtime_coverage_registry(conn: psycopg.Connection = Depends(get_db)) -> list[CoverageRegistryResponse]:
    rows = fetch_runtime_coverage_registry(conn)
    return [CoverageRegistryResponse.model_validate(row) for row in rows]
