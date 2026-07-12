from __future__ import annotations

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query

from api.deps import get_db
from api.models import DonorSearchResponse
from api.queries import search_donors

router = APIRouter()


@router.get("/donors/search", response_model=DonorSearchResponse)
def donor_search(
    q: str = Query(...),
    by: str = Query("name"),
    limit: int = Query(20),
    offset: int = Query(0),
    conn: psycopg.Connection = Depends(get_db),
) -> DonorSearchResponse:
    try:
        payload = search_donors(conn, q=q, by=by, limit=limit, offset=offset)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return DonorSearchResponse.model_validate(payload)
