from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

EREntityType = Literal["person", "organization"]
ERDecisionLabel = Literal["match", "probable_match", "possible_match", "no_match"]


class ERClusterListParams(BaseModel):
    entity_type: EREntityType | None = None
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


class ClusterMemberResponse(BaseModel):
    entity_type: EREntityType
    entity_id: UUID
    is_canonical: bool
    canonical_name: str | None = None


class ERClusterSummaryResponse(BaseModel):
    id: UUID
    entity_type: EREntityType
    canonical_entity_id: UUID
    canonical_name: str | None = None
    cluster_confidence: float | None = None
    member_count: int


class ERClusterDetailResponse(ERClusterSummaryResponse):
    members: list[ClusterMemberResponse] = Field(default_factory=list)


class MatchDecisionResponse(BaseModel):
    id: UUID
    entity_type: EREntityType
    entity_id_a: UUID
    entity_id_b: UUID
    decision: ERDecisionLabel
    confidence: float
    decided_by: str
    decision_method: str
    match_evidence: dict[str, Any] | None = None
    decided_at: datetime


class ERDecisionCounts(BaseModel):
    match: int = 0
    probable_match: int = 0
    possible_match: int = 0
    no_match: int = 0


class ERSummaryResponse(BaseModel):
    total_active_clusters: int
    total_active_members: int
    total_active_matches: int
    decision_counts: ERDecisionCounts
