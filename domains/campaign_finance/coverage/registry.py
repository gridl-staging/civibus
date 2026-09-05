"""Coverage registry data model and I/O for campaign finance jurisdiction tracking."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StringConstraints, ValidationError, model_validator

from domains.campaign_finance.jurisdictions.config_schema import (
    FilingAuthorityKindLiteral,
    GeographicJurisdictionTypeLiteral,
    UpdateFrequencyLiteral,
)

TierLiteral = Literal[
    "launch-support candidate",
    "freshness-limited",
    "deferred/blocked",
    "implemented but unproven",
]
CoverageJurisdictionIdentity: TypeAlias = tuple[GeographicJurisdictionTypeLiteral, str]
NonBlankText: TypeAlias = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

MunicipalAuditDecisionLiteral = Literal[
    "covered_by_parent",
    "independent_target",
]

# Jurisdiction types that are state-equivalent (no parent linkage allowed)
_STATE_EQUIVALENT_TYPES: frozenset[str] = frozenset({"federal", "state"})
_MUNICIPALITY_TYPE = "municipality"

DEFAULT_REGISTRY_PATH = (
    Path(__file__).resolve().parents[3] / "docs" / "reference" / "research" / "coverage-registry.json"
)


class CoverageRegistryBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FilingAuthorityReference(CoverageRegistryBaseModel):
    """One typed filing/reporting authority reference, never geographic containment."""

    kind: FilingAuthorityKindLiteral
    code: NonBlankText
    name: NonBlankText | None = None

    @model_validator(mode="after")
    def _validate_named_other(self) -> "FilingAuthorityReference":
        if self.kind == "named_other" and self.name is None:
            raise ValueError("named_other filing authority requires an explicit name")
        if self.kind != "named_other" and self.name is not None:
            raise ValueError(f"name is only valid for named_other filing authorities, found {self.kind}")
        return self


class IndependentAuthorityRelation(CoverageRegistryBaseModel):
    relation: Literal["independent"]
    authority: FilingAuthorityReference


class InheritedAuthorityRelation(CoverageRegistryBaseModel):
    relation: Literal["inherited"]
    authority: FilingAuthorityReference


class AuthorityPartition(CoverageRegistryBaseModel):
    authority: FilingAuthorityReference
    scope: NonBlankText


class AuthorityPrecedence(CoverageRegistryBaseModel):
    authority: FilingAuthorityReference
    scope: NonBlankText


class AuthorityProvenanceScope(CoverageRegistryBaseModel):
    authority: FilingAuthorityReference
    source_scope: NonBlankText


class AuthorityDeduplicationDisposition(CoverageRegistryBaseModel):
    disposition: Literal["deduplicate", "refuse_combination"]
    identity_keys: list[NonBlankText] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_disposition_keys(self) -> "AuthorityDeduplicationDisposition":
        if self.disposition == "deduplicate" and not self.identity_keys:
            raise ValueError("deduplicate disposition requires identity_keys")
        if self.disposition == "refuse_combination" and self.identity_keys:
            raise ValueError("refuse_combination disposition must not carry identity_keys")
        if len(set(self.identity_keys)) != len(self.identity_keys):
            raise ValueError("deduplication identity_keys must be unique")
        return self


def _authority_key(authority: FilingAuthorityReference) -> tuple[str, str, str | None]:
    return authority.kind, authority.code, authority.name


def _exact_authority_membership_error(
    *,
    label: str,
    expected: list[FilingAuthorityReference],
    actual: list[FilingAuthorityReference],
) -> str | None:
    expected_keys = [_authority_key(authority) for authority in expected]
    actual_keys = [_authority_key(authority) for authority in actual]
    if len(set(actual_keys)) != len(actual_keys) or set(actual_keys) != set(expected_keys):
        return f"{label} must reference every overlap authority exactly once"
    return None


Sha256Text: TypeAlias = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class AuthorityRelationEvidence(CoverageRegistryBaseModel):
    owner: NonBlankText
    receipt: NonBlankText
    receipt_sha256: Sha256Text
    packet_sha256: Sha256Text | None = None
    aggregate_receipt: NonBlankText | None = None
    aggregate_receipt_sha256: Sha256Text | None = None

    @model_validator(mode="after")
    def _validate_aggregate_receipt_pair(self) -> "AuthorityRelationEvidence":
        if (self.aggregate_receipt is None) != (self.aggregate_receipt_sha256 is None):
            raise ValueError("aggregate receipt path and SHA-256 must be supplied together")
        return self


class PartitionedOverlappingAuthorityRelation(CoverageRegistryBaseModel):
    relation: Literal["partitioned_overlapping"]
    authorities: list[FilingAuthorityReference] = Field(min_length=2)
    precedence: list[AuthorityPrecedence] = Field(min_length=2)
    partitions: list[AuthorityPartition] = Field(min_length=2)
    provenance: list[AuthorityProvenanceScope] = Field(min_length=2)
    deduplication: AuthorityDeduplicationDisposition
    refusals: list[NonBlankText] = Field(default_factory=list)
    evidence: AuthorityRelationEvidence

    @model_validator(mode="after")
    def _validate_complete_policy(self) -> "PartitionedOverlappingAuthorityRelation":
        authority_keys = [_authority_key(authority) for authority in self.authorities]
        if len(set(authority_keys)) != len(authority_keys):
            raise ValueError("overlap authorities must be unique")
        for label, references in (
            ("precedence", [precedence.authority for precedence in self.precedence]),
            ("partitions", [partition.authority for partition in self.partitions]),
            ("provenance", [scope.authority for scope in self.provenance]),
        ):
            error = _exact_authority_membership_error(
                label=label,
                expected=self.authorities,
                actual=references,
            )
            if error is not None:
                raise ValueError(error)
        return self


class UnresolvedAuthorityRelation(CoverageRegistryBaseModel):
    relation: Literal["unresolved"]
    candidate_authorities: list[FilingAuthorityReference]
    reason: NonBlankText
    aggregation_disposition: Literal["refuse"]


AuthorityRelation: TypeAlias = Annotated[
    IndependentAuthorityRelation
    | InheritedAuthorityRelation
    | PartitionedOverlappingAuthorityRelation
    | UnresolvedAuthorityRelation,
    Field(discriminator="relation"),
]


IdentityDomainLiteral = Literal[
    "geographic_subject",
    "filing_authority",
    "acquisition_scope",
    "provenance_scope",
    "public_route",
]


class ScopedIdentity(CoverageRegistryBaseModel):
    """One owner-local identity tagged by both domain and authority/geography kind."""

    domain: IdentityDomainLiteral
    kind: FilingAuthorityKindLiteral
    value: NonBlankText
    name: NonBlankText | None = None

    @model_validator(mode="after")
    def _validate_identity_domain(self) -> "ScopedIdentity":
        if self.kind == "named_other" and self.name is None:
            raise ValueError("named_other identity requires an explicit name")
        if self.kind != "named_other" and self.name is not None:
            raise ValueError(f"name is only valid for named_other identities, found {self.kind}")
        if self.kind == "named_other" and self.domain in {"geographic_subject", "public_route"}:
            raise ValueError(f"named_other cannot be used as a {self.domain} identity")
        return self


class IdentityTranslation(CoverageRegistryBaseModel):
    """A bounded bridge whose five identity domains never collapse into one key."""

    geographic_subject: ScopedIdentity
    filing_authority: ScopedIdentity | None = None
    acquisition_scope: ScopedIdentity | None = None
    provenance_scope: ScopedIdentity | None = None
    public_route: ScopedIdentity | None = None

    @model_validator(mode="after")
    def _validate_scoped_slots(self) -> "IdentityTranslation":
        populated = 0
        for slot in (
            "geographic_subject",
            "filing_authority",
            "acquisition_scope",
            "provenance_scope",
            "public_route",
        ):
            identity = getattr(self, slot)
            if identity is None:
                continue
            populated += 1
            if identity.domain != slot:
                raise ValueError(f"{slot} must carry domain={slot}, found {identity.domain}")
        if populated < 2:
            raise ValueError("identity translation requires at least two distinct identity domains")
        return self

    def identity_for(self, domain: IdentityDomainLiteral) -> ScopedIdentity | None:
        return getattr(self, domain)


class IdentityTranslationError(KeyError, ValueError):
    """Base class for fail-closed cross-owner translation errors."""


class IdentityTranslationNotFoundError(IdentityTranslationError):
    pass


class IdentityTranslationMultipleError(IdentityTranslationError):
    pass


class IdentityTranslationKindMismatchError(IdentityTranslationError):
    pass


class IdentityTranslationContradictionError(IdentityTranslationError):
    pass


def _scoped_identity_key(identity: ScopedIdentity) -> tuple[str, str, str, str | None]:
    return identity.domain, identity.kind, identity.value, identity.name


def translate_identity(
    source: ScopedIdentity,
    *,
    target_domain: IdentityDomainLiteral,
    translations: list[IdentityTranslation],
) -> ScopedIdentity:
    """Resolve exactly one typed translation or refuse with a precise failure class."""

    same_value = [
        candidate
        for translation in translations
        if (candidate := translation.identity_for(source.domain)) is not None
        and candidate.value == source.value
        and candidate.name == source.name
    ]
    exact_matches = [translation for translation in translations if translation.identity_for(source.domain) == source]
    if not exact_matches:
        if any(candidate.kind != source.kind for candidate in same_value):
            available_kinds = ", ".join(sorted({candidate.kind for candidate in same_value}))
            raise IdentityTranslationKindMismatchError(
                f"identity kind mismatch for {source.domain}/{source.value}: "
                f"requested {source.kind}, available {available_kinds}"
            )
        raise IdentityTranslationNotFoundError(
            f"zero identity translation matches for {source.domain}/{source.kind}/{source.value}"
        )

    targets = [translation.identity_for(target_domain) for translation in exact_matches]
    present_targets = [target for target in targets if target is not None]
    if len(exact_matches) > 1:
        target_keys = {_scoped_identity_key(target) for target in present_targets}
        if len(target_keys) > 1 or len(present_targets) != len(targets):
            raise IdentityTranslationContradictionError(
                f"contradictory identity translations for {source.domain}/{source.kind}/{source.value} "
                f"to {target_domain}"
            )
        if not present_targets:
            raise IdentityTranslationNotFoundError(
                f"zero {target_domain} targets for {source.domain}/{source.kind}/{source.value}"
            )
        raise IdentityTranslationMultipleError(
            f"multiple identity translation matches for {source.domain}/{source.kind}/{source.value}"
        )

    target = targets[0]
    if target is None:
        raise IdentityTranslationNotFoundError(
            f"zero {target_domain} targets for {source.domain}/{source.kind}/{source.value}"
        )
    return target


class CoverageRegistryRow(CoverageRegistryBaseModel):
    """Single jurisdiction entry in the coverage registry."""

    jurisdiction_code: str
    name: str
    jurisdiction_type: GeographicJurisdictionTypeLiteral

    best_update_frequency: UpdateFrequencyLiteral
    best_last_verified_working: date | None
    covers_sub_jurisdictions: bool
    source_count: StrictInt
    source_names: list[str]

    runner_wired: bool

    tier: TierLiteral | None
    evidence_summary: str | None
    operational_reason: str | None
    next_action: str | None
    evidence_date: date | None
    loaded_count: StrictInt | None = None
    expected_count: StrictInt | None = None
    # Tri-state evidence flag for outside-spending coverage. None = not yet
    # determined (existing tier-based behavior preserved). False is required when
    # the source's evidence shows the current bulk export does not carry IE
    # data, so the API must return null IE totals instead of misleading zeroes.
    ie_coverage_available: bool | None = None

    # Municipality layer fields (Stage 5) — null for state-equivalent rows
    parent_jurisdiction_code: str | None = None
    municipal_audit_decision: MunicipalAuditDecisionLiteral | None = None
    # Browser-verified portal URL for independent municipalities (Stage 1 city research)
    municipal_portal_url: str | None = None
    authority_relation: AuthorityRelation

    @model_validator(mode="before")
    @classmethod
    def _upgrade_legacy_authority_relation(cls, payload: object) -> object:
        """Load legacy rows as unresolved; compatibility fields never choose the relation."""

        if not isinstance(payload, Mapping) or payload.get("authority_relation") is not None:
            return payload
        upgraded = dict(payload)
        jurisdiction_code = upgraded.get("jurisdiction_code")
        jurisdiction_type = upgraded.get("jurisdiction_type")
        parent_code = upgraded.get("parent_jurisdiction_code")
        if not isinstance(jurisdiction_code, str) or not isinstance(jurisdiction_type, str):
            return payload
        candidate_authorities: list[dict[str, str]] = [{"kind": jurisdiction_type, "code": jurisdiction_code}]
        if jurisdiction_type == _MUNICIPALITY_TYPE and isinstance(parent_code, str):
            candidate_authorities.insert(0, {"kind": "state", "code": parent_code})
        upgraded["authority_relation"] = {
            "relation": "unresolved",
            "candidate_authorities": candidate_authorities,
            "reason": ("Legacy compatibility fields do not carry an accepted typed filing-authority receipt."),
            "aggregation_disposition": "refuse",
        }
        return upgraded

    @model_validator(mode="after")
    def _validate_municipality_linkage(self) -> "CoverageRegistryRow":
        """Enforce parent/decision/portal constraints by jurisdiction type."""
        relation = self.authority_relation
        if relation.relation == "independent" and relation.authority.kind != "named_other":
            if (relation.authority.kind, relation.authority.code) != (
                self.jurisdiction_type,
                self.jurisdiction_code,
            ):
                raise ValueError("independent geographic authority must match its coverage-registry row")

        is_municipality = self.jurisdiction_type == _MUNICIPALITY_TYPE
        if not is_municipality:
            if self.parent_jurisdiction_code is not None:
                raise ValueError(
                    f"parent_jurisdiction_code must be null for {self.jurisdiction_type} row '{self.jurisdiction_code}'"
                )
            if self.municipal_audit_decision is not None:
                raise ValueError(
                    f"municipal_audit_decision must be null for {self.jurisdiction_type} row '{self.jurisdiction_code}'"
                )
            if self.municipal_portal_url is not None:
                raise ValueError(
                    f"municipal_portal_url must be null for {self.jurisdiction_type} row '{self.jurisdiction_code}'"
                )
            return self

        if self.parent_jurisdiction_code is None:
            raise ValueError(
                f"parent_jurisdiction_code is required for {self.jurisdiction_type} row '{self.jurisdiction_code}'"
            )
        if self.municipal_audit_decision is None:
            raise ValueError(
                f"municipal_audit_decision is required for {self.jurisdiction_type} row '{self.jurisdiction_code}'"
            )
        if self.municipal_audit_decision == "covered_by_parent" and self.municipal_portal_url is not None:
            raise ValueError(f"municipal_portal_url must be null for covered_by_parent row '{self.jurisdiction_code}'")
        if (
            self.municipal_audit_decision == "independent_target"
            and self.evidence_summary is not None
            and "browser-verified" in self.evidence_summary.lower()
            and not self.municipal_portal_url
        ):
            raise ValueError(
                f"municipal_portal_url is required for browser-verified independent_target row "
                f"'{self.jurisdiction_code}'"
            )
        return self


class CoverageRegistry(CoverageRegistryBaseModel):
    identity_translations: list[IdentityTranslation] = Field(default_factory=list)
    rows: list[CoverageRegistryRow]

    @model_validator(mode="after")
    def _validate_unique_jurisdiction_codes(self) -> "CoverageRegistry":
        duplicate_codes = collect_duplicate_jurisdiction_codes(self.rows)
        if duplicate_codes:
            details = "; ".join(
                f"{code} at row indexes {', '.join(str(index) for index in indexes)}"
                for code, indexes in sorted(duplicate_codes.items())
            )
            raise ValueError(f"Duplicate jurisdiction code(s): {details}")

        rows_by_identity = {(row.jurisdiction_type, row.jurisdiction_code): row for row in self.rows}
        for index, translation in enumerate(self.identity_translations):
            geographic_subject = translation.geographic_subject
            row = rows_by_identity.get((geographic_subject.kind, geographic_subject.value))
            if row is None:
                raise ValueError(
                    f"identity_translations[{index}] geographic_subject "
                    f"{geographic_subject.kind}/{geographic_subject.value} does not resolve "
                    "to one coverage-registry row"
                )

            filing_authority = translation.filing_authority
            if filing_authority is None:
                continue
            relation = row.authority_relation
            if relation.relation == "unresolved":
                raise ValueError(
                    f"identity_translations[{index}] filing_authority cannot be projected "
                    "from an unresolved authority relation"
                )
            if relation.relation in {"independent", "inherited"}:
                accepted_authorities = [relation.authority]
            else:
                accepted_authorities = relation.authorities
            filing_authority_key = (
                filing_authority.kind,
                filing_authority.value,
                filing_authority.name,
            )
            if filing_authority_key not in {_authority_key(authority) for authority in accepted_authorities}:
                raise ValueError(
                    f"identity_translations[{index}] filing_authority does not match "
                    "the geographic subject's accepted authority relation"
                )
        return self


def coverage_parent_linkage_error(
    row: CoverageRegistryRow,
    rows_by_code: Mapping[str, CoverageRegistryRow],
) -> str | None:
    """Return the registry-owned municipality parent invariant violation, if any."""

    if row.jurisdiction_type != _MUNICIPALITY_TYPE:
        return None

    parent_code = row.parent_jurisdiction_code
    parent = rows_by_code.get(parent_code) if parent_code is not None else None
    if parent is None:
        return f"municipality '{row.jurisdiction_code}' has no coverage-registry parent '{parent_code}'"
    if parent.jurisdiction_type != "state":
        return (
            f"municipality '{row.jurisdiction_code}' parent '{parent.jurisdiction_code}' must be a state, "
            f"found {parent.jurisdiction_type}"
        )
    if row.municipal_audit_decision == "covered_by_parent" and not parent.covers_sub_jurisdictions:
        return (
            f"covered_by_parent municipality '{row.jurisdiction_code}' names parent "
            f"'{parent.jurisdiction_code}' with covers_sub_jurisdictions=false"
        )
    return None


def _row_owns_authority(row: CoverageRegistryRow, authority: FilingAuthorityReference) -> bool:
    relation = row.authority_relation
    if relation.relation == "independent" and relation.authority == authority:
        return True
    return (
        authority.kind != "named_other"
        and row.jurisdiction_type == authority.kind
        and row.jurisdiction_code == authority.code
    )


def coverage_authority_linkage_errors(
    row: CoverageRegistryRow,
    rows_by_code: Mapping[str, CoverageRegistryRow],
) -> list[str]:
    """Return unresolved references in an accepted inherited or overlap relation.

    Unresolved relations intentionally do not require their candidates to resolve:
    their only safe behavior is refusal.  Independent authorities are self-owned.
    """

    relation = row.authority_relation
    references: list[FilingAuthorityReference]
    if relation.relation == "inherited":
        references = [relation.authority]
    elif relation.relation == "partitioned_overlapping":
        references = relation.authorities
    else:
        return []

    errors: list[str] = []
    for authority in references:
        if authority.kind == "named_other":
            continue
        owner = rows_by_code.get(authority.code)
        if owner is None or not _row_owns_authority(owner, authority):
            errors.append(
                f"{relation.relation} authority {authority.kind}/{authority.code} does not resolve "
                "to one typed coverage-registry authority row"
            )
    return errors


def format_validation_errors(validation_error: ValidationError) -> str:
    formatted_errors: list[str] = []
    for error in validation_error.errors():
        location = ".".join(str(part) for part in error["loc"])
        if not location:
            location = "<root>"
        formatted_errors.append(f"{location}: {error['msg']}")
    return "; ".join(formatted_errors)


def collect_duplicate_jurisdiction_codes(rows: list[CoverageRegistryRow]) -> dict[str, list[int]]:
    code_to_indexes: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        code_to_indexes[row.jurisdiction_code].append(index)

    return {code: indexes for code, indexes in code_to_indexes.items() if len(indexes) > 1}


def load_registry_json(path: str | Path) -> object:
    registry_path = Path(path)
    try:
        return json.loads(registry_path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ValueError(f"Failed to read registry file at {registry_path}: {error}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"Failed to parse registry JSON at {registry_path}: {error}") from error


def load_registry(path: str | Path) -> CoverageRegistry:
    registry_path = Path(path)
    raw_payload = load_registry_json(registry_path)

    try:
        return CoverageRegistry.model_validate(raw_payload)
    except ValidationError as error:
        raise ValueError(f"Invalid registry JSON at {registry_path}: {format_validation_errors(error)}") from error


def write_registry(path: str | Path, registry: CoverageRegistry) -> Path:
    registry_path = Path(path)
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(f"{registry.model_dump_json(indent=2)}\n", encoding="utf-8")
    return registry_path
