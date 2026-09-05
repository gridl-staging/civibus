from __future__ import annotations

from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, Query

from api.deps import get_db
from api.models import DonorsWithPropertyParams, DonorsWithPropertyResult
from api.queries import fetch_donors_with_property

router = APIRouter()


@router.get("/investigate/donors-with-property", response_model=list[DonorsWithPropertyResult])
def list_donors_with_property(
    params: Annotated[DonorsWithPropertyParams, Query()],
    conn: psycopg.Connection = Depends(get_db),
) -> list[DonorsWithPropertyResult]:
    rows = fetch_donors_with_property(conn, params)
    return [DonorsWithPropertyResult.model_validate(row) for row in rows]
