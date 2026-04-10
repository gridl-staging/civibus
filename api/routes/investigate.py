from __future__ import annotations

import psycopg
from fastapi import APIRouter, Depends

from api.deps import get_db
from api.models import DonorsWithPropertyParams, DonorsWithPropertyResult
from api.queries import fetch_donors_with_property
from api.routes.validation import build_query_params_dependency

router = APIRouter()

_build_donors_with_property_params = build_query_params_dependency(DonorsWithPropertyParams)


@router.get("/investigate/donors-with-property", response_model=list[DonorsWithPropertyResult])
def list_donors_with_property(
    params: DonorsWithPropertyParams = Depends(_build_donors_with_property_params),
    conn: psycopg.Connection = Depends(get_db),
) -> list[DonorsWithPropertyResult]:
    rows = fetch_donors_with_property(conn, params)
    return [DonorsWithPropertyResult.model_validate(row) for row in rows]
