"""The one ephemeral projection owner for campaign-finance status views.

This package holds the read-only projection contracts shared by the future
``product-status``, ``region-status``, and ``coverage-status`` views. It is the single
owner of the projection envelope, its mutually exclusive outcomes, and the pure
municipality owner-composition resolver. It projects the canonical coverage-registry
and lifecycle owners without copying, caching, or redefining their facts.
"""

from __future__ import annotations

from domains.campaign_finance.coverage.status.models import (
    MISSING_OBSERVATION_REASON,
    NOT_APPLICABLE,
    UNKNOWN,
    FieldProvenance,
    JsonSerializableValue,
    ObservationInput,
    OriginLiteral,
    ProjectedField,
    ProjectionOutcome,
    ProjectionReport,
    Refusal,
    StatusProjectionModel,
    UnknownFact,
    build_projected_field,
    refuse,
)
from domains.campaign_finance.coverage.status.municipality import (
    MunicipalityBranchLiteral,
    RegionOwnerIndex,
    RegionOwnerResolution,
    RegistryBranchSelection,
    build_region_owner_index,
    resolve_region_owners,
    resolve_region_owners_from_index,
    select_registry_owners_from_index,
)

__all__ = [
    "MISSING_OBSERVATION_REASON",
    "NOT_APPLICABLE",
    "UNKNOWN",
    "FieldProvenance",
    "JsonSerializableValue",
    "ObservationInput",
    "OriginLiteral",
    "ProjectedField",
    "ProjectionOutcome",
    "ProjectionReport",
    "Refusal",
    "StatusProjectionModel",
    "UnknownFact",
    "build_projected_field",
    "refuse",
    "MunicipalityBranchLiteral",
    "RegionOwnerIndex",
    "RegionOwnerResolution",
    "RegistryBranchSelection",
    "build_region_owner_index",
    "resolve_region_owners",
    "resolve_region_owners_from_index",
    "select_registry_owners_from_index",
]
