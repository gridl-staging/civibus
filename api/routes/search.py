from __future__ import annotations

import psycopg
from fastapi import APIRouter, Depends

from api.deps import get_db
from api.models import SearchParams, SearchResult
from api.queries import fetch_search_results

router = APIRouter()


@router.get("/search", response_model=list[SearchResult])
def search(
    params: SearchParams = Depends(),
    conn: psycopg.Connection = Depends(get_db),
) -> list[SearchResult]:
    search_rows = fetch_search_results(conn, params)
    return [SearchResult.model_validate(search_row) for search_row in search_rows]
