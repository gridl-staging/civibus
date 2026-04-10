from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class DonorsWithPropertyResult(BaseModel):
    person_id: UUID
    canonical_name: str
    match_type: Literal["direct", "cluster"]


class DonorsWithPropertyParams(BaseModel):
    jurisdiction: str | None = None
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)
