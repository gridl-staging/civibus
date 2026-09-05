from __future__ import annotations

from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from api.models._validation import POSTGRES_SIGNED_BIGINT_MAX

SearchEntityType = Literal["person", "org", "committee", "candidate", "office", "contest"]
SEARCH_QUERY_MAX_LENGTH = 100


class SearchParams(BaseModel):
    q: str = Field(min_length=2, max_length=SEARCH_QUERY_MAX_LENGTH)
    entity_type: SearchEntityType | None = None
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=POSTGRES_SIGNED_BIGINT_MAX)


class SearchResult(BaseModel):
    entity_type: SearchEntityType
    entity_id: UUID
    name: str
    state: str | None = None
    party: str | None = None
    office_name: str | None = None
    committee_type: str | None = None
    total_raised: Decimal | None = None


class SearchResponse(BaseModel):
    items: list[SearchResult]
    has_next: bool
