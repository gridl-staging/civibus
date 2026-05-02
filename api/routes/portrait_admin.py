from __future__ import annotations

from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException

from api.deps import get_db
from core import db

router = APIRouter()


@router.post("/admin/portraits/{portrait_id}/takedown")
def request_portrait_takedown(
    portrait_id: UUID,
    conn: psycopg.Connection = Depends(get_db),
) -> dict[str, object]:
    portrait = db.mark_person_portrait_takedown_requested(conn, portrait_id)
    if portrait is None:
        raise HTTPException(status_code=404, detail="Portrait not found")
    return {"id": str(portrait.id), "status": portrait.status}
