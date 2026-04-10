from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

# Public API entity types allowed as graph route targets.
GraphEntityType = Literal[
    "person",
    "org",
    "committee",
    "candidate",
    "office",
    "electoral_division",
    "contest",
    "candidacy",
    "officeholding",
]


@dataclass(frozen=True, slots=True)
class GraphEntitySpec:
    """Single graph entity mapping source for API, SQL, and AGE layers."""

    relational_entity_type: str
    relational_table: str
    age_label: str


# Single source of truth: API entity name → relational type/table + AGE label.
GRAPH_ENTITY_TYPE_SPECS: dict[str, GraphEntitySpec] = {
    "person": GraphEntitySpec(
        relational_entity_type="person",
        relational_table="core.person",
        age_label="Person",
    ),
    "org": GraphEntitySpec(
        relational_entity_type="organization",
        relational_table="core.organization",
        age_label="Organization",
    ),
    "committee": GraphEntitySpec(
        relational_entity_type="committee",
        relational_table="cf.committee",
        age_label="Committee",
    ),
    "candidate": GraphEntitySpec(
        relational_entity_type="candidate",
        relational_table="cf.candidate",
        age_label="Candidate",
    ),
    "office": GraphEntitySpec(
        relational_entity_type="office",
        relational_table="civic.office",
        age_label="Office",
    ),
    "electoral_division": GraphEntitySpec(
        relational_entity_type="electoral_division",
        relational_table="civic.electoral_division",
        age_label="ElectoralDivision",
    ),
    "contest": GraphEntitySpec(
        relational_entity_type="contest",
        relational_table="civic.contest",
        age_label="Contest",
    ),
    "candidacy": GraphEntitySpec(
        relational_entity_type="candidacy",
        relational_table="civic.candidacy",
        age_label="Candidacy",
    ),
    "officeholding": GraphEntitySpec(
        relational_entity_type="officeholding",
        relational_table="civic.officeholding",
        age_label="Officeholding",
    ),
}

# Kept as explicit dicts for easy import in routes/tests/query helpers.
GRAPH_ENTITY_TYPE_TO_RELATIONAL_ENTITY_TYPE: dict[str, str] = {
    api_entity_type: spec.relational_entity_type for api_entity_type, spec in GRAPH_ENTITY_TYPE_SPECS.items()
}

GRAPH_ENTITY_TYPE_TO_AGE_LABEL: dict[str, str] = {
    api_entity_type: spec.age_label for api_entity_type, spec in GRAPH_ENTITY_TYPE_SPECS.items()
}

_GRAPH_ONLY_AGE_LABEL_TO_NEIGHBOR_TYPE: dict[str, str] = {
    "Filing": "filing",
}

# Reverse mapping: AGE node label → API-friendly neighbor type name.
# Includes graph-only labels (e.g. Filing) that are valid neighbors but not
# top-level route targets.
AGE_LABEL_TO_NEIGHBOR_TYPE: dict[str, str] = {
    **{spec.age_label: api_entity_type for api_entity_type, spec in GRAPH_ENTITY_TYPE_SPECS.items()},
    **_GRAPH_ONLY_AGE_LABEL_TO_NEIGHBOR_TYPE,
}

# Stage 2 only exposes the graph relationships already materialized for the
# campaign-finance and ER graph surface. Later graph expansions must opt in
# explicitly instead of widening this public API accidentally.
GRAPH_ALLOWED_RELATIONSHIP_TYPES: frozenset[str] = frozenset(
    {
        "CONTRIBUTED_TO",
        "SPENT_ON",
        "AFFILIATED_WITH",
        "FILED",
        "HOLDS",
        "RUNS_IN",
        "CANDIDACY_OF",
        "REPRESENTS",
        "SAME_AS",
        "POSSIBLE_MATCH",
    }
)


class GraphNeighbor(BaseModel):
    """One neighbor of an entity in the knowledge graph."""

    entity_type: str
    entity_id: UUID
    name: str | None = None
    relationship_type: str
    direction: Literal["outbound", "inbound"]


class EntityRelationshipsResponse(BaseModel):
    """Graph neighborhood for a single entity."""

    entity_type: GraphEntityType
    entity_id: UUID
    neighbors: list[GraphNeighbor] = Field(default_factory=list)
    total_count: int = 0
