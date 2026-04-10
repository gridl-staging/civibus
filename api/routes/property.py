from __future__ import annotations

from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException

from api.deps import get_db
from api.models import ParcelDetailResponse, ParcelListParams, ParcelSummaryResponse
from api.queries import fetch_parcel_detail, fetch_parcel_list
from api.routes.validation import build_query_params_dependency

router = APIRouter()

_build_parcel_list_params = build_query_params_dependency(ParcelListParams)


@router.get("/parcels/{parcel_id}", response_model=ParcelDetailResponse)
def get_parcel(parcel_id: UUID, conn: psycopg.Connection = Depends(get_db)) -> ParcelDetailResponse:
    parcel_row = fetch_parcel_detail(conn, parcel_id)
    if parcel_row is None:
        raise HTTPException(status_code=404, detail="Parcel not found")
    return ParcelDetailResponse.model_validate(parcel_row)


@router.get("/parcels", response_model=list[ParcelSummaryResponse])
def list_parcels(
    params: ParcelListParams = Depends(_build_parcel_list_params),
    conn: psycopg.Connection = Depends(get_db),
) -> list[ParcelSummaryResponse]:
    parcel_rows = fetch_parcel_list(conn, params)
    return [ParcelSummaryResponse.model_validate(parcel_row) for parcel_row in parcel_rows]
