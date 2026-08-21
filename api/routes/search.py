from __future__ import annotations

import psycopg
from fastapi import APIRouter, Depends

from api.deps import get_db
from api.models import SearchParams, SearchResponse, SearchResult
from api.queries import fetch_search_results

router = APIRouter()


@router.get("/search", response_model=SearchResponse)
def search(
    params: SearchParams = Depends(),
    conn: psycopg.Connection = Depends(get_db),
) -> SearchResponse:
    search_page = fetch_search_results(conn, params)
    search_results = [SearchResult.model_validate(search_row) for search_row in search_page["items"]]
    return SearchResponse.model_validate({"items": search_results, "has_next": search_page["has_next"]})
