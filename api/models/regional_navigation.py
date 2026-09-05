"""Typed public-route contracts for authority-scoped regional finance."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal, TypeAlias
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


RegionalNodeKind: TypeAlias = Literal[
    "state",
    "county",
    "municipality",
    "school_district",
    "special_district",
]
RegionalChildKind: TypeAlias = Literal[
    "county",
    "municipality",
    "school_district",
    "special_district",
]
RegionalAuthorityKind: TypeAlias = Literal[
    "federal",
    "state",
    "county",
    "municipality",
    "school_district",
    "special_district",
    "named_other",
]
RegionalFinanceStatus: TypeAlias = Literal["available", "degraded", "stale", "unavailable"]
RegionalAuthorityRelation: TypeAlias = Literal[
    "independent",
    "inherited",
    "partitioned_overlapping",
    "unresolved",
]
RegionalAggregationDisposition: TypeAlias = Literal[
    "not_applicable",
    "deduplicate",
    "refuse_combination",
    "refuse",
]
RegionalTranslationStatus: TypeAlias = Literal["resolved", "refused"]
RegionalRecurrenceStatus: TypeAlias = Literal["qualified", "degraded", "unknown", "refused"]
RegionalRevisionParity: TypeAlias = Literal["match", "mismatch", "unknown"]
RegionalOverlapDisposition: TypeAlias = Literal["not_combined"]
RegionalMoneyClassKey: TypeAlias = Literal[
    "contributions",
    "expenditures",
    "independent_expenditures",
    "loans",
]
RegionalRefreshStatus: TypeAlias = Literal[
    "crashed",
    "empty",
    "degraded",
    "failed",
    "running",
    "success",
]
RegionalExecutionOrigin: TypeAlias = Literal["manual", "scheduled", "unknown"]


class RegionalNavigationBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RegionalGeometryReference(RegionalNavigationBaseModel):
    """One typed owner-local reference used only to match navigation geometry."""

    namespace: Literal["civic"]
    kind: Literal["electoral_division_name"]
    value: str


class RegionalSubjectIdentity(RegionalNavigationBaseModel):
    """Displayed geography, kept separate from every filing/source identity."""

    kind: RegionalNodeKind
    code: str = Field(min_length=1)
    name: str = Field(min_length=1)


class RegionalFilingAuthority(RegionalNavigationBaseModel):
    """One authority from the typed coverage relation."""

    kind: RegionalAuthorityKind
    code: str = Field(min_length=1)
    name: str = Field(min_length=1)
    scope: str = Field(min_length=1)
    provenance_scope: str = Field(min_length=1)
    official_url: HttpUrl | None = None


class RegionalAuthorityContext(RegionalNavigationBaseModel):
    """Canonical typed translation and authority-relation projection."""

    subject: RegionalSubjectIdentity
    public_route: str | None
    acquisition_scope: str | None
    provenance_scope: str | None
    relation: RegionalAuthorityRelation
    filing_authorities: list[RegionalFilingAuthority]
    included_scopes: list[Annotated[str, Field(min_length=1)]]
    excluded_scopes: list[Annotated[str, Field(min_length=1)]]
    provenance_scopes: list[Annotated[str, Field(min_length=1)]]
    aggregation_disposition: RegionalAggregationDisposition
    evidence_date: date | None
    translation_status: RegionalTranslationStatus
    refusal_reasons: list[Annotated[str, Field(min_length=1)]]

    @model_validator(mode="after")
    def _validate_relation_shape(self) -> "RegionalAuthorityContext":
        authority_keys = [(row.kind, row.code, row.name) for row in self.filing_authorities]
        if len(authority_keys) != len(set(authority_keys)):
            raise ValueError("Filing authorities must be unique.")
        if self.relation == "partitioned_overlapping":
            if len(self.filing_authorities) < 2:
                raise ValueError("Partitioned/overlapping context requires at least two authorities.")
            if self.aggregation_disposition not in {"deduplicate", "refuse_combination"}:
                raise ValueError("Partitioned/overlapping context requires an exact aggregation disposition.")
        if self.relation == "unresolved":
            if self.aggregation_disposition != "refuse" or self.translation_status != "refused":
                raise ValueError("Unresolved authority context must refuse translation and aggregation.")
        if self.translation_status == "refused" and not self.refusal_reasons:
            raise ValueError("Refused authority translation requires a reason.")
        return self


class RegionalAuthorityHealth(RegionalNavigationBaseModel):
    """One authority's distinct freshness, recurrence, revision, and refusal state."""

    authority_code: str = Field(min_length=1)
    freshness_status: RegionalFinanceStatus
    degraded_source_names: list[str]
    recurrence_status: RegionalRecurrenceStatus
    recurrence_observed_at: datetime | None
    revision_parity: RegionalRevisionParity
    deployed_revision: str | None
    promotion_eligible: bool
    refusal_reasons: list[Annotated[str, Field(min_length=1)]]

    @model_validator(mode="after")
    def _validate_promotion_state(self) -> "RegionalAuthorityHealth":
        if self.promotion_eligible == bool(self.refusal_reasons):
            raise ValueError("Eligible authority health has no refusals; refused health requires reasons.")
        return self


class RegionalFinanceState(RegionalNavigationBaseModel):
    """Shallow availability state shared by resolve, search, and detail."""

    status: RegionalFinanceStatus
    authority_context: RegionalAuthorityContext
    authority_health: list[RegionalAuthorityHealth]
    reason: str = Field(min_length=1)


class RegionalFinanceSource(RegionalNavigationBaseModel):
    """One exact source and its independent data and recurrence clocks."""

    class_key: RegionalMoneyClassKey
    authority_code: str = Field(min_length=1)
    source_identity: str = Field(min_length=1)
    name: str = Field(min_length=1)
    url: HttpUrl
    status: RegionalFinanceStatus
    last_successful_pull: datetime | None
    last_verified_working: date | None
    latest_refresh_completed_at: datetime | None
    latest_refresh_status: RegionalRefreshStatus | None
    latest_refresh_execution_origin: RegionalExecutionOrigin
    recurrence_status: RegionalRecurrenceStatus
    reason: str = Field(min_length=1)


class RegionalMoneyClass(RegionalNavigationBaseModel):
    """Exact current-window amount for one non-overlapping source class."""

    key: RegionalMoneyClassKey
    authority_code: str = Field(min_length=1)
    source_identity: str = Field(min_length=1)
    label: str = Field(min_length=1)
    status: RegionalFinanceStatus
    amount: Decimal | None
    transaction_count: int = Field(ge=0)
    data_through: date | None
    source_name: str = Field(min_length=1)
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_amount_availability(self) -> "RegionalMoneyClass":
        if self.status == "unavailable" and self.amount is not None:
            raise ValueError("Unavailable money classes cannot publish an amount.")
        if self.status != "unavailable" and self.amount is None:
            raise ValueError("Available, degraded, and stale money classes require an amount.")
        return self


class RegionalNativeIdentifier(RegionalNavigationBaseModel):
    """Authority-plan identifier without exposing a jurisdiction storage key."""

    authority_code: str = Field(min_length=1)
    value: str = Field(min_length=1)


class RegionalCandidate(RegionalNavigationBaseModel):
    """Civic candidacy with only identifier-proven authority-scoped money linkage."""

    person_id: UUID
    person_name: str = Field(min_length=1)
    candidacy_id: UUID
    contest_id: UUID
    contest_name: str = Field(min_length=1)
    election_date: date | None
    office_id: UUID
    office_name: str = Field(min_length=1)
    office_title: str | None
    division_id: UUID | None
    division_name: str | None
    party: str | None
    candidacy_status: str | None
    current_officeholding_id: UUID | None
    native_filer_identifier: RegionalNativeIdentifier | None
    money_connection: Literal["connected", "unavailable"]
    activity_amount: Decimal | None
    transaction_count: int = Field(ge=0)

    @model_validator(mode="after")
    def _validate_money_connection(self) -> "RegionalCandidate":
        if self.money_connection == "connected":
            if self.native_filer_identifier is None or self.activity_amount is None:
                raise ValueError("Connected candidates require a native filer identifier and amount.")
        elif (
            self.native_filer_identifier is not None or self.activity_amount is not None or self.transaction_count != 0
        ):
            raise ValueError("Unavailable candidate money cannot carry activity or an identifier.")
        return self


class RegionalCommittee(RegionalNavigationBaseModel):
    """Committee participating in the exact bounded authority transaction set."""

    committee_id: UUID
    organization_id: UUID | None
    name: str = Field(min_length=1)
    activity_amount: Decimal
    transaction_count: int = Field(ge=1)
    data_through: date | None


class RegionalFinanceDetail(RegionalNavigationBaseModel):
    """Authority-parameterized finance detail for one typed regional subject."""

    subject: RegionalSubjectIdentity
    authority_context: RegionalAuthorityContext
    authority_health: list[RegionalAuthorityHealth]
    as_of: datetime
    period_start: date
    period_end: date
    money: list[RegionalMoneyClass] = Field(min_length=1)
    candidates: list[RegionalCandidate]
    committees: list[RegionalCommittee]
    sources: list[RegionalFinanceSource] = Field(min_length=1)
    registry_evidence_date: date | None
    lifecycle_registry_updated_at: date | None
    included: list[Annotated[str, Field(min_length=1)]] = Field(min_length=1)
    excluded: list[Annotated[str, Field(min_length=1)]] = Field(min_length=1)
    named_gaps: list[Annotated[str, Field(min_length=1)]]

    @model_validator(mode="after")
    def _validate_class_coverage(self) -> "RegionalFinanceDetail":
        money_keys = [(row.authority_code, row.source_identity, row.key) for row in self.money]
        source_keys = [(row.authority_code, row.source_identity, row.class_key) for row in self.sources]
        if len(money_keys) != len(set(money_keys)) or set(money_keys) != set(source_keys):
            raise ValueError("Finance detail requires one matching source and money row per authority class.")
        if self.period_start > self.period_end or self.period_end != self.as_of.date():
            raise ValueError("Regional finance window must end on the response as-of date.")
        if self.authority_context.subject != self.subject:
            raise ValueError("Finance detail subject and authority context must match.")
        return self


class RegionalProxyAnalysis(RegionalNavigationBaseModel):
    """Presentation boundary for an analysis narrower than geographic coverage."""

    label: str
    scope_label: str
    excludes: list[str]
    overlap_disposition: RegionalOverlapDisposition


_ROUTE_SEGMENT = {
    "county": "county",
    "municipality": "municipality",
    "school_district": "school-district",
    "special_district": "special-district",
}


class RegionalNavigationNode(RegionalNavigationBaseModel):
    """A route-owned presentation identity, not a fact registry."""

    kind: RegionalNodeKind
    name: str
    state_code: str
    state_name: str
    slug: str | None
    canonical_path: str
    geometry_reference: RegionalGeometryReference | None
    finance: RegionalFinanceState
    finance_detail: RegionalFinanceDetail | None = None
    proxy_analysis: RegionalProxyAnalysis | None

    @model_validator(mode="after")
    def _validate_detail_scope(self) -> "RegionalNavigationNode":
        expected_path = (
            f"/state/{self.state_code}"
            if self.kind == "state" and self.slug is None
            else f"/state/{self.state_code}/{_ROUTE_SEGMENT[self.kind]}/{self.slug}"
            if self.kind != "state" and self.slug is not None
            else None
        )
        if expected_path is None or self.canonical_path != expected_path:
            raise ValueError("Canonical path must match the typed regional subject.")
        context = self.finance.authority_context
        if context.subject.kind != self.kind or context.subject.name != self.name:
            raise ValueError("Navigation identity and authority-context subject must match.")
        if context.public_route is not None and context.public_route != self.canonical_path:
            raise ValueError("Typed public route and canonical path must match.")
        if self.finance_detail is not None:
            if self.finance_detail.subject != context.subject:
                raise ValueError("Finance detail and navigation subject must match.")
            if self.finance_detail.authority_context != context:
                raise ValueError("Shallow and detailed authority context must match.")
            if self.finance_detail.authority_health != self.finance.authority_health:
                raise ValueError("Shallow and detailed authority health must match.")
            detail_statuses = {row.status for row in self.finance_detail.money}
            expected_status = (
                "unavailable"
                if detail_statuses == {"unavailable"}
                else "degraded"
                if "unavailable" in detail_statuses or "degraded" in detail_statuses
                else "stale"
                if "stale" in detail_statuses
                else "available"
            )
            if self.finance.status != expected_status:
                raise ValueError("Shallow and detail finance statuses must match.")
        return self


class RegionalNavigationListResponse(RegionalNavigationBaseModel):
    items: list[RegionalNavigationNode]
    incomplete_node_kinds: list[RegionalNodeKind]
    has_unsafe_omissions: bool


# Transitional import names for internal callers while serialization is generic.
RegionalStateCandidate = RegionalCandidate
RegionalStateCommittee = RegionalCommittee
RegionalStateFinanceDetail = RegionalFinanceDetail


__all__ = [
    "RegionalAuthorityContext",
    "RegionalAuthorityHealth",
    "RegionalCandidate",
    "RegionalChildKind",
    "RegionalCommittee",
    "RegionalFilingAuthority",
    "RegionalFinanceDetail",
    "RegionalFinanceSource",
    "RegionalFinanceState",
    "RegionalGeometryReference",
    "RegionalMoneyClass",
    "RegionalNativeIdentifier",
    "RegionalNavigationListResponse",
    "RegionalNavigationNode",
    "RegionalNodeKind",
    "RegionalOverlapDisposition",
    "RegionalProxyAnalysis",
    "RegionalStateCandidate",
    "RegionalStateCommittee",
    "RegionalStateFinanceDetail",
    "RegionalSubjectIdentity",
]
