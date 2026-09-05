from __future__ import annotations

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query

from api.deps import DATABASE_UNAVAILABLE_DETAIL, get_db
from api.models import DonorSearchResponse
from api.models._validation import POSTGRES_SIGNED_BIGINT_MAX
from api.models.search import SEARCH_QUERY_MAX_LENGTH
from api.queries import DONOR_SEARCH_MAX_LIMIT, DonorSearchRollupUnavailableError, search_donors

router = APIRouter()

_DONOR_SEARCH_ROLLUP_UNAVAILABLE_CODE = "donor_search_rollup_unavailable"
_DONOR_SEARCH_UNAVAILABLE_OPENAPI_RESPONSE = {
    "description": "Donor search is unavailable.",
    "content": {
        "application/json": {
            "schema": {
                "oneOf": [
                    {
                        "type": "object",
                        "properties": {
                            "detail": {
                                "type": "object",
                                "properties": {
                                    "code": {
                                        "type": "string",
                                        "enum": [_DONOR_SEARCH_ROLLUP_UNAVAILABLE_CODE],
                                    }
                                },
                                "required": ["code"],
                                "additionalProperties": False,
                            }
                        },
                        "required": ["detail"],
                        "additionalProperties": False,
                    },
                    {
                        "type": "object",
                        "properties": {
                            "detail": {
                                "type": "string",
                                "enum": [DATABASE_UNAVAILABLE_DETAIL],
                            }
                        },
                        "required": ["detail"],
                        "additionalProperties": False,
                    },
                ]
            }
        }
    },
}


@router.get(
    "/donors/search",
    response_model=DonorSearchResponse,
    responses={503: _DONOR_SEARCH_UNAVAILABLE_OPENAPI_RESPONSE},
)
def donor_search(
    q: str = Query(..., max_length=SEARCH_QUERY_MAX_LENGTH),
    by: str = Query("name"),
    limit: int = Query(20, ge=1, le=DONOR_SEARCH_MAX_LIMIT),
    offset: int = Query(0, ge=0, le=POSTGRES_SIGNED_BIGINT_MAX),
    conn: psycopg.Connection = Depends(get_db),
) -> DonorSearchResponse:
    try:
        payload = search_donors(conn, q=q, by=by, limit=limit, offset=offset)
    except DonorSearchRollupUnavailableError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": _DONOR_SEARCH_ROLLUP_UNAVAILABLE_CODE,
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return DonorSearchResponse.model_validate(payload)
