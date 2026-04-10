from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

SearchEntityType = Literal["person", "org", "committee", "candidate", "office"]


class SearchParams(BaseModel):
    q: str = Field(min_length=2, max_length=100)
    entity_type: SearchEntityType | None = None
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class SearchResult(BaseModel):
    entity_type: SearchEntityType
    entity_id: UUID
    name: str
