from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import secrets
import shutil
import stat
import sys
import tarfile
import tempfile
from collections.abc import Sequence
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, ValidationError, model_validator

from core.refresh import job_builders
from core.refresh.authority_ledger import (
    AuthorityLedgerProof,
    DatabaseIdentity,
    RawDatabaseObservation,
    RawFlyAppStatus,
    RawFlyMachineStatus,
    RefreshQuiescence,
    RefreshRunEvidence,
    RegionalScheduledObservationReceipt,
    ScheduledTerminalEvent,
    validate_authority_ledger_proof,
)
from core.refresh.authority_execution_plan import AuthorityIdentity, RefreshJobLike
from core.refresh.authority_operations_profile import (
    AuthorityOperationsProfile,
    canonical_sha256,
    expected_image_plan_proof,
    load_authority_operations_profile,
)
from core.refresh.runner import RunnerParameters
from domains.campaign_finance.jurisdictions.config_schema import GeographicJurisdictionTypeLiteral

from .registry import FilingAuthorityReference, TierLiteral, format_validation_errors

AcquisitionPatternLiteral = Literal[
    "bulk_file",
    "bulk_api",
    "search_export_portal",
    "browser_session_portal",
    "protected_or_blocked",
    "unknown",
]
DiscoveryMaturityLiteral = Literal["not_started", "researched", "interactively_proven", "blocked"]
SourceContractMaturityLiteral = Literal["not_started", "partial", "encoded", "verified"]
LegalFilingSemanticsMaturityLiteral = Literal["not_started", "partial", "substantial", "verified"]
ImplementationMaturityLiteral = Literal[
    "not_started",
    "scaffolded",
    "fixture_tested",
    "live_proven",
    "full_history_proven",
]
OperationalMaturityLiteral = Literal["unknown", "manual_only", "runner_wired", "operational"]
CompletenessIntelligenceMaturityLiteral = Literal[
    "not_started",
    "rules_only",
    "observed_only",
    "gap_detection_ready",
]
CivicsCandidacyStatusLiteral = Literal[
    "not_started",
    "loaded",
    "full_csv_proven",
]
AuthorityRelationLiteral = Literal["independent", "inherited", "partitioned_overlapping", "unresolved"]
AuthorityAggregationDispositionLiteral = Literal[
    "not_applicable",
    "deduplicate",
    "refuse_combination",
    "refuse",
]
AuthorityFreshnessStatusLiteral = Literal["fresh", "stale", "degraded", "unknown"]
AuthorityRevisionParityLiteral = Literal["match", "mismatch", "unknown"]
NonBlankText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
RevisionText = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40,64}$")]
Sha256Text = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]

DEFAULT_IMPLEMENTED_REGION_LIFECYCLE_PATH = (
    Path(__file__).resolve().parents[3] / "docs" / "reference" / "research" / "implemented-region-lifecycle.json"
)
DEFAULT_IMPLEMENTED_REGION_LIFECYCLE_SUMMARY_PATH = (
    Path(__file__).resolve().parents[3] / "docs" / "reference" / "research" / "implemented-region-lifecycle-summary.md"
)
AUTHORITY_PROMOTION_RECEIPT_ENV = "CIVIBUS_AUTHORITY_PROMOTION_RECEIPT_JSON"
AUTHORITY_PROMOTION_ARCHIVE_NAME = "authority-promotion-bundle.tar"
AUTHORITY_PROMOTION_BUILD_RECEIPT_NAME = "authority-promotion-bundle-build-receipt.json"
AUTHORITY_PROMOTION_RECEIPT_NAME = "authority-promotion-receipt.json"
AUTHORITY_PROMOTION_INSTALL_DIRECTORY = PurePosixPath("/app/private/civibus/authority-promotion")
_WASHINGTON_REGIONAL_PROFILE_PATH = (
    Path(__file__).resolve().parents[3] / "infra" / "fly" / "regional_refresh_machine_profile.json"
)
_LIFECYCLE_AUTHORITY_NOTE = "Authoritative source: `docs/reference/research/implemented-region-lifecycle.json`."
_CREDENTIAL_BEARING_JSON_KEYS = {
    "authorization",
    "cookie",
    "credentials",
    "database_url",
    "password",
    "pgpass",
    "private_key",
    "secret",
    "token",
}
_CREDENTIAL_BEARING_JSON_KEY_SUFFIXES = (
    "_api_key",
    "_authorization",
    "_cookie",
    "_credentials",
    "_database_url",
    "_password",
    "_private_key",
    "_secret",
    "_token",
)


class LifecycleBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AuthoritySourceEvidence(LifecycleBaseModel):
    """One exact source's freshness evidence for a promotion decision."""

    source_identity: NonBlankText
    freshness_status: AuthorityFreshnessStatusLiteral
    observed_at: datetime | None

    @model_validator(mode="after")
    def _normalize_observed_at(self) -> "AuthoritySourceEvidence":
        if self.observed_at is not None:
            if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
                raise ValueError("source freshness observed_at must be timezone-aware")
            self.observed_at = self.observed_at.astimezone(timezone.utc)
        return self


class AuthorityRecurrenceEvidence(LifecycleBaseModel):
    """One exact source's latest recurrence proof, never inferred from cadence alone."""

    source_identity: NonBlankText
    pull_status: Literal["crashed", "empty", "degraded", "failed", "running", "success"]
    execution_origin: Literal["manual", "scheduled", "unknown"]
    completed_at: datetime | None

    @model_validator(mode="after")
    def _normalize_completed_at(self) -> "AuthorityRecurrenceEvidence":
        if self.completed_at is not None:
            if self.completed_at.tzinfo is None or self.completed_at.utcoffset() is None:
                raise ValueError("recurrence completed_at must be timezone-aware")
            self.completed_at = self.completed_at.astimezone(timezone.utc)
        return self


class AuthorityPromotionEvidence(LifecycleBaseModel):
    """Caller-supplied exact evidence set for one authority promotion decision."""

    authority_identity: NonBlankText
    authority_relation: AuthorityRelationLiteral
    aggregation_disposition: AuthorityAggregationDispositionLiteral
    expected_source_identities: list[NonBlankText] = Field(min_length=1)
    source_evidence: list[AuthoritySourceEvidence]
    recurrence_evidence: list[AuthorityRecurrenceEvidence]
    provenance_source_identities: list[NonBlankText]
    keel_source_identities: list[NonBlankText]
    deployed_source_identities: list[NonBlankText]
    source_revision: RevisionText | None
    api_revision: RevisionText | None
    web_revision: RevisionText | None

    @model_validator(mode="after")
    def _validate_exact_identity_inputs(self) -> "AuthorityPromotionEvidence":
        for label, identities in (
            ("expected_source_identities", self.expected_source_identities),
            ("source_evidence", [row.source_identity for row in self.source_evidence]),
            ("recurrence_evidence", [row.source_identity for row in self.recurrence_evidence]),
            ("provenance_source_identities", self.provenance_source_identities),
            ("keel_source_identities", self.keel_source_identities),
            ("deployed_source_identities", self.deployed_source_identities),
        ):
            if len(identities) != len(set(identities)):
                raise ValueError(f"{label} must contain unique exact source identities")
        return self


class AuthorityPromotionDecision(LifecycleBaseModel):
    """Fail-closed promotion result projected by lifecycle, coverage, and public views."""

    authority_identity: NonBlankText
    eligible: bool
    revision_parity: AuthorityRevisionParityLiteral
    refusal_reasons: list[NonBlankText]

    @model_validator(mode="after")
    def _validate_eligibility(self) -> "AuthorityPromotionDecision":
        if self.eligible == bool(self.refusal_reasons):
            raise ValueError("eligible promotion requires no refusals; refused promotion requires reasons")
        return self


PromotionEvidenceKind = Literal[
    "canary_ledger",
    "scheduled_recurrence",
    "filing_authority",
    "provenance",
    "keel",
    "serving_deploy",
    "surface_parity",
]


class CanonicalPromotionEvidence(LifecycleBaseModel):
    """One immutable canonical input to a composite promotion receipt."""

    kind: PromotionEvidenceKind
    path: NonBlankText
    sha256: Sha256Text

    @model_validator(mode="after")
    def _validate_absolute_path(self) -> "CanonicalPromotionEvidence":
        if not Path(self.path).is_absolute():
            raise ValueError("canonical promotion evidence paths must be absolute")
        return self


class PromotionGeographicSubject(LifecycleBaseModel):
    """Typed geography kept distinct from the filing authority identity."""

    kind: GeographicJurisdictionTypeLiteral
    code: NonBlankText


class FilingAuthorityPromotionArtifact(LifecycleBaseModel):
    """Canonical filing-authority resolution consumed by promotion."""

    schema_version: Literal[1]
    geographic_subject: PromotionGeographicSubject
    filing_authority: FilingAuthorityReference
    authority_relation: Literal["independent"]
    aggregation_disposition: Literal["not_applicable"]


class ScheduledRecurrencePromotionArtifact(LifecycleBaseModel):
    """Hash-bound references to the existing Gate 10 proof and receipt outputs."""

    schema_version: Literal[1]
    authority_ledger_proof_path: NonBlankText
    authority_ledger_proof_sha256: Sha256Text
    observation_receipt_path: NonBlankText
    observation_receipt_sha256: Sha256Text
    canary_promotion_artifact_sha256: Sha256Text

    @model_validator(mode="after")
    def _validate_output_paths(self) -> "ScheduledRecurrencePromotionArtifact":
        paths = (Path(self.authority_ledger_proof_path), Path(self.observation_receipt_path))
        if any(not path.is_absolute() for path in paths):
            raise ValueError("scheduled recurrence proof and receipt paths must be absolute")
        if paths[0] == paths[1]:
            raise ValueError("scheduled recurrence proof and receipt paths must be distinct")
        return self


class HashBoundPromotionFile(LifecycleBaseModel):
    """One absolute regular evidence file bound by exact bytes."""

    path: NonBlankText
    sha256: Sha256Text

    @model_validator(mode="after")
    def _validate_path(self) -> "HashBoundPromotionFile":
        if not Path(self.path).is_absolute():
            raise ValueError("promotion evidence file paths must be absolute")
        return self


CanaryLifecycleMarkerKind = Literal[
    "regional_create_ownership",
    "regional_machine_ownership",
    "regional_stopped_provision",
    "regional_start_attempt",
    "regional_canary_mode",
    "regional_canary_machine_terminal",
    "regional_rollback_attempt",
    "regional_rollback_stopped",
    "regional_rollback_complete",
]


class CanaryLifecycleMarkerReference(HashBoundPromotionFile):
    kind: CanaryLifecycleMarkerKind


class RegionalCanaryPromotionArtifact(LifecycleBaseModel):
    """One changed-image canary, terminal database proof, and exact rollback."""

    schema_version: Literal[1]
    observed_at: datetime
    profile_file_sha256: Sha256Text
    candidate_receipt: HashBoundPromotionFile
    candidate_source_git_sha: RevisionText
    candidate_tree_git_sha: RevisionText
    qualified_image: NonBlankText
    authority_ledger_proof: HashBoundPromotionFile
    app: NonBlankText
    machine_id: NonBlankText
    machine_name: NonBlankText
    machine_config_sha256: Sha256Text
    authority: FilingAuthorityReference
    execution_plan_id: NonBlankText
    job_key: NonBlankText
    refresh_run_id: UUID
    execution_origin: Literal["operator_attended"]
    terminal_event: ScheduledTerminalEvent
    database: DatabaseIdentity
    quiescence: RefreshQuiescence
    terminal_machine_evidence: HashBoundPromotionFile
    database_postcondition: HashBoundPromotionFile
    federal_invariance_before: HashBoundPromotionFile
    federal_invariance_after: HashBoundPromotionFile
    public_invariance_before: HashBoundPromotionFile
    public_invariance_after: HashBoundPromotionFile
    rollback_app_inventory_before: HashBoundPromotionFile
    rollback_machine_inventory_before: HashBoundPromotionFile
    rollback_volume_inventory_before: HashBoundPromotionFile
    rollback_app_inventory: HashBoundPromotionFile
    rollback_machine_inventory: HashBoundPromotionFile
    rollback_volume_inventory: HashBoundPromotionFile
    lifecycle_markers: tuple[CanaryLifecycleMarkerReference, ...]

    @model_validator(mode="after")
    def _validate_distinct_exact_references(self) -> "RegionalCanaryPromotionArtifact":
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("canary promotion observed_at must be timezone-aware")
        self.observed_at = self.observed_at.astimezone(timezone.utc)
        expected_marker_kinds = (
            "regional_create_ownership",
            "regional_machine_ownership",
            "regional_stopped_provision",
            "regional_start_attempt",
            "regional_canary_mode",
            "regional_canary_machine_terminal",
            "regional_rollback_attempt",
            "regional_rollback_stopped",
            "regional_rollback_complete",
        )
        if tuple(marker.kind for marker in self.lifecycle_markers) != expected_marker_kinds:
            raise ValueError("canary promotion requires exact ordered lifecycle markers")
        references = (
            self.candidate_receipt,
            self.authority_ledger_proof,
            self.terminal_machine_evidence,
            self.database_postcondition,
            self.federal_invariance_before,
            self.federal_invariance_after,
            self.public_invariance_before,
            self.public_invariance_after,
            self.rollback_app_inventory_before,
            self.rollback_machine_inventory_before,
            self.rollback_volume_inventory_before,
            self.rollback_app_inventory,
            self.rollback_machine_inventory,
            self.rollback_volume_inventory,
            *self.lifecycle_markers,
        )
        paths = tuple(reference.path for reference in references)
        if len(paths) != len(set(paths)):
            raise ValueError("canary promotion evidence paths must be distinct")
        return self


class PromotionBundleMember(LifecycleBaseModel):
    path: NonBlankText
    sha256: Sha256Text
    mode: Literal["0600"]


class PromotionBundleBuildReceipt(LifecycleBaseModel):
    """Transport identity embedded in the immutable bundle and checked by deploy."""

    schema_version: Literal[1]
    run_id: NonBlankText
    run_name: NonBlankText
    artifact_name: NonBlankText
    source_revision: RevisionText
    api_revision: RevisionText
    web_revision: RevisionText
    members: tuple[PromotionBundleMember, ...]

    @model_validator(mode="after")
    def _validate_identity(self) -> "PromotionBundleBuildReceipt":
        if not self.run_id.isdecimal() or self.run_id.startswith("0"):
            raise ValueError("promotion bundle run ID must be a positive decimal integer")
        safe_name = r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}"
        if re.fullmatch(safe_name, self.run_name) is None or re.fullmatch(safe_name, self.artifact_name) is None:
            raise ValueError("promotion bundle run or artifact name contains unsupported characters")
        if len({self.source_revision, self.api_revision, self.web_revision}) != 1:
            raise ValueError("promotion bundle source/API/web revisions are split")
        paths = tuple(member.path for member in self.members)
        if not paths or len(paths) != len(set(paths)):
            raise ValueError("promotion bundle build receipt member paths must be nonempty and distinct")
        return self


class RawCanaryTerminalMachine(LifecycleBaseModel):
    schema_version: Literal[1]
    app: NonBlankText
    machine_id: NonBlankText
    machine_name: NonBlankText
    image: NonBlankText
    machine_config_sha256: Sha256Text
    state: Literal["stopped"]
    exit_code: Literal[0]
    occurred_at: AwareDatetime
    captured_at: AwareDatetime

    @model_validator(mode="after")
    def _validate_capture_window(self) -> "RawCanaryTerminalMachine":
        if self.captured_at < self.occurred_at:
            raise ValueError("terminal Machine capture predates the terminal event")
        return self


class RawCanaryDatabasePostcondition(LifecycleBaseModel):
    schema_version: Literal[1]
    app: NonBlankText
    machine_id: NonBlankText
    authority: NonBlankText
    execution_plan: NonBlankText
    refresh_run_id: UUID
    job_key: NonBlankText
    execution_origin: Literal["operator_attended"]
    pull_status: Literal["success"]
    completed_at: AwareDatetime
    metadata_updates: Literal[1]
    running_refresh_rows: Literal[0]
    active_refresh_backends: Literal[0]
    long_idle_transactions: Literal[0]
    ungranted_locks: Literal[0]
    database: DatabaseIdentity


class RawInvarianceRecord(LifecycleBaseModel):
    owner: NonBlankText
    identity: NonBlankText
    row_count: int = Field(ge=0)
    content_sha256: Sha256Text


class RawInvarianceSnapshot(LifecycleBaseModel):
    schema_version: Literal[2]
    producer: Literal["regional_lifecycle_invariance_capture"]
    stage: Literal["before", "after"]
    scope: Literal["federal", "public"]
    captured_at: AwareDatetime
    canonical_receipt_git_sha: RevisionText
    canonical_source_git_sha: RevisionText
    canonical_tree_git_sha: RevisionText
    source_revision: RevisionText
    source_tree_git_sha: RevisionText
    authority: AuthorityIdentity
    execution_plan: NonBlankText
    job_key: NonBlankText
    execution_origin: Literal["operator_attended"]
    profile_file_sha256: Sha256Text
    candidate_receipt_file_sha256: Sha256Text
    qualified_image: NonBlankText
    app: NonBlankText
    machine_id: NonBlankText
    machine_name: NonBlankText
    machine_config_sha256: Sha256Text
    database: DatabaseIdentity
    api_revision: RevisionText
    web_revision: RevisionText
    records: tuple[RawInvarianceRecord, ...] = Field(min_length=1)
    identity_sha256: Sha256Text

    @model_validator(mode="after")
    def _derive_identity(self) -> "RawInvarianceSnapshot":
        identities = tuple((record.owner, record.identity) for record in self.records)
        if len(identities) != len(set(identities)) or identities != tuple(sorted(identities)):
            raise ValueError("invariance records must have sorted unique owner identities")
        if self.api_revision != self.web_revision:
            raise ValueError("invariance API/web revisions are split")
        expected_payload = self.model_dump(
            mode="json",
            exclude={"captured_at", "stage", "identity_sha256"},
        )
        expected = canonical_sha256(expected_payload)
        if self.identity_sha256 != expected:
            raise ValueError("invariance identity digest mismatch")
        return self


class RawInvarianceDatabaseObservation(LifecycleBaseModel):
    """Exact read-only database identity and quiescence captured by the deploy owner."""

    schema_version: Literal[1]
    application_name: Literal["civibus:regional-invariance-capture"]
    transaction_read_only: Literal["on"]
    default_transaction_read_only: Literal["on"]
    database_name: NonBlankText
    server_address: NonBlankText
    server_port: int = Field(ge=1, le=65535)
    running_refresh_rows: Literal[0]
    active_refresh_backends: Literal[0]
    long_idle_transactions: Literal[0]
    ungranted_locks: Literal[0]
    advisory_locks: Literal[0]


class RegionalInvarianceAdmissionReference(LifecycleBaseModel):
    """Exact immutable before-snapshot bytes and semantic identity admitted at start."""

    snapshot_sha256: Sha256Text
    identity_sha256: Sha256Text


class RegionalInvarianceAdmission(LifecycleBaseModel):
    """The bounded freshness decision durably owned by the one-start marker."""

    admitted_at: AwareDatetime
    max_age_seconds: Literal[600]
    future_skew_seconds: Literal[60]
    federal_before: RegionalInvarianceAdmissionReference
    public_before: RegionalInvarianceAdmissionReference


def invariance_capture_time_is_fresh(
    captured_at: datetime,
    *,
    admitted_at: datetime,
    max_age_seconds: int = 600,
    future_skew_seconds: int = 60,
) -> bool:
    """Apply the canonical inclusive freshness window at the admission decision."""

    return (
        admitted_at - timedelta(seconds=max_age_seconds)
        <= captured_at
        <= admitted_at + timedelta(seconds=future_skew_seconds)
    )


class RawRegionalLifecycleMarker(LifecycleBaseModel):
    schema_version: Literal[2, 3]
    app: NonBlankText
    authority: NonBlankText
    execution_plan: NonBlankText
    kind: CanaryLifecycleMarkerKind
    machine_id: str | None
    machine_name: NonBlankText
    profile_file_sha256: Sha256Text
    candidate_receipt_file_sha256: Sha256Text
    invariance_admission: RegionalInvarianceAdmission | None = None

    @model_validator(mode="after")
    def _validate_start_admission_shape(self) -> "RawRegionalLifecycleMarker":
        if self.schema_version == 3:
            if self.kind != "regional_start_attempt" or self.invariance_admission is None:
                raise ValueError("schema-3 lifecycle marker must be an admission-bound start attempt")
        elif self.invariance_admission is not None:
            raise ValueError("schema-2 lifecycle marker cannot carry invariance admission")
        return self


class ProvenancePromotionArtifact(LifecycleBaseModel):
    """Canonical source ownership and provenance scope for one authority."""

    schema_version: Literal[1]
    filing_authority: FilingAuthorityReference
    provenance_scope: NonBlankText
    source_identities: list[NonBlankText] = Field(min_length=1)


class KeelPromotionArtifact(LifecycleBaseModel):
    """Canonical Keel/lifecycle validation for the exact source set."""

    schema_version: Literal[1]
    filing_authority: FilingAuthorityReference
    source_identities: list[NonBlankText] = Field(min_length=1)
    validation_status: Literal["pass"]
    implementation_maturity: Literal["live_proven"]
    operational_maturity: Literal["runner_wired"]


class ServingDeployPromotionArtifact(LifecycleBaseModel):
    """Canonical serving deployment identity and exact deployed sources."""

    schema_version: Literal[1]
    filing_authority: FilingAuthorityReference
    source_identities: list[NonBlankText] = Field(min_length=1)
    candidate_receipt_file_sha256: Sha256Text
    candidate_source_git_sha: RevisionText
    candidate_tree_git_sha: RevisionText
    qualified_image: NonBlankText
    source_revision: RevisionText
    api_revision: RevisionText
    web_revision: RevisionText


class RawDeployedSurfaceResult(LifecycleBaseModel):
    """One manifest-owned deployed surface result, as observed over HTTP."""

    surface_id: NonBlankText
    path: NonBlankText
    http_status: Literal[200]
    content_sha256: Sha256Text


class RawDeployedApiParityEvidence(LifecycleBaseModel):
    """Raw deployed API/HTTP evidence from the existing parity probe owner."""

    schema_version: Literal[1]
    captured_at: AwareDatetime
    source_revision: RevisionText
    api_revision: RevisionText
    web_revision: RevisionText
    candidate_receipt_file_sha256: Sha256Text
    candidate_tree_git_sha: RevisionText
    qualified_image: NonBlankText
    promotion_bundle_sha256: Sha256Text
    filing_authority: FilingAuthorityReference
    source_identities: tuple[NonBlankText, ...] = Field(min_length=1)
    health_status: Literal["healthy"]
    content_health_status: Literal["healthy"]
    surface_parity_ok: Literal[True]
    federal_identity_sha256: Sha256Text
    regional_navigation_routes: tuple[NonBlankText, ...]
    washington_specimens: tuple[NonBlankText, ...] = Field(min_length=1)
    surfaces: tuple[RawDeployedSurfaceResult, ...]


class RawBrowserRouteEvidence(LifecycleBaseModel):
    """One visible regional route result emitted by the Playwright owner."""

    path: NonBlankText
    http_status: Literal[200]
    heading: NonBlankText
    campaign_finance_status: Literal["available", "direct", "inherited"]
    authority_identity: NonBlankText


class RawDeployedBrowserParityEvidence(LifecycleBaseModel):
    """Raw production-browser result bound to the same deployed revision."""

    schema_version: Literal[1]
    captured_at: AwareDatetime
    source_revision: RevisionText
    api_revision: RevisionText
    web_revision: RevisionText
    candidate_receipt_file_sha256: Sha256Text
    candidate_tree_git_sha: RevisionText
    qualified_image: NonBlankText
    promotion_bundle_sha256: Sha256Text
    filing_authority: FilingAuthorityReference
    federal_identity_sha256: Sha256Text
    routes: tuple[RawBrowserRouteEvidence, ...]
    washington_specimens: tuple[NonBlankText, ...] = Field(min_length=1)


class SurfaceParityPromotionArtifact(LifecycleBaseModel):
    """Hash-bound deployed API/browser parity proof for one fresh revision."""

    schema_version: Literal[1]
    observed_at: AwareDatetime
    candidate_receipt_file_sha256: Sha256Text
    candidate_tree_git_sha: RevisionText
    qualified_image: NonBlankText
    promotion_bundle_sha256: Sha256Text
    source_revision: RevisionText
    api_revision: RevisionText
    web_revision: RevisionText
    raw_api_evidence: HashBoundPromotionFile
    raw_browser_evidence: HashBoundPromotionFile

    @model_validator(mode="before")
    @classmethod
    def _require_raw_owner_evidence(cls, value: object) -> object:
        if not isinstance(value, dict) or not {
            "raw_api_evidence",
            "raw_browser_evidence",
            "observed_at",
        }.issubset(value):
            raise ValueError("surface parity requires raw API and browser evidence with observation time")
        return value

    @model_validator(mode="after")
    def _validate_identity(self) -> "SurfaceParityPromotionArtifact":
        if len({self.source_revision, self.api_revision, self.web_revision}) != 1:
            raise ValueError("surface parity source revision is split across source/API/web")
        if self.raw_api_evidence.path == self.raw_browser_evidence.path:
            raise ValueError("surface parity raw API and browser evidence paths must be distinct")
        return self


_SURFACE_PARITY_IDS = (
    "home_surface",
    "search_surface",
    "donor_search_surface",
    "congress_surface",
    "methodology_surface",
    "developers_surface",
    "candidates_surface",
    "committees_surface",
    "committee_detail_surface",
    "compare_surface",
    "calendar_surface",
    "coverage_surface",
    "data_sources_surface",
    "about_surface",
    "contact_surface",
    "privacy_surface",
    "sitemap_index_surface",
    "person_detail_surface",
)
REGIONAL_BROWSER_ROUTE_EXPECTATIONS = (
    ("/state/WA", "Washington", "available", "state/WA"),
    ("/state/WA/municipality/seattle", "Seattle", "inherited", "state/WA"),
    (
        "/state/NY/municipality/new-york-city",
        "New York City",
        "direct",
        "named_other/NY_NEW_YORK",
    ),
)
REGIONAL_BROWSER_ROUTES = tuple(row[0] for row in REGIONAL_BROWSER_ROUTE_EXPECTATIONS)
_WASHINGTON_SOURCE_NAMES = (
    "WA PDC Contributions",
    "WA PDC Expenditures",
    "WA PDC Independent Expenditures",
    "WA PDC Loans",
)


def _mode_0600_hash_bound_file(path: Path, *, label: str) -> HashBoundPromotionFile:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a regular non-symlink file")
    resolved = path.resolve(strict=True)
    if stat.S_IMODE(resolved.stat().st_mode) != 0o600:
        raise ValueError(f"{label} must be mode 0600")
    return HashBoundPromotionFile(
        path=str(resolved),
        sha256=hashlib.sha256(resolved.read_bytes()).hexdigest(),
    )


def _write_new_mode_0600_json(path: Path, payload: object, *, label: str) -> None:
    if not path.parent.is_dir() or path.parent.is_symlink():
        raise ValueError(f"{label} parent must be an existing regular directory")
    data = (
        json.dumps(payload, ensure_ascii=True, allow_nan=False, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")
    temporary = path.parent / f".{path.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(temporary, flags, 0o600)
    except FileExistsError as error:
        raise ValueError(f"{label} temporary path collision") from error
    try:
        with os.fdopen(descriptor, "wb") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path, follow_symlinks=False)
        except FileExistsError as error:
            raise ValueError(f"{label} path already exists") from error
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def _read_invariance_owner_json(path: Path, *, label: str) -> object:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a regular non-symlink file")
    payload = _read_strict_promotion_json(path, label=label)
    _reject_credential_bearing_promotion_json(payload, label=label)
    return payload


def _invariance_record(
    *,
    owner: str,
    identity: str,
    row_count: int,
    payload: object,
) -> RawInvarianceRecord:
    return RawInvarianceRecord(
        owner=owner,
        identity=identity,
        row_count=row_count,
        content_sha256=canonical_sha256(payload),
    )


def build_regional_invariance_snapshots(
    *,
    profile_path: Path,
    candidate_receipt_path: Path,
    stage: Literal["before", "after"],
    captured_at: datetime,
    machine_id: str,
    federal_machines_path: Path,
    federal_machine_config_path: Path,
    federal_volumes_path: Path,
    federal_version_path: Path,
    public_api_version_path: Path,
    public_web_version_path: Path,
    public_content_health_path: Path,
    database_observation_path: Path,
) -> tuple[RawInvarianceSnapshot, RawInvarianceSnapshot]:
    """Derive the canonical before/after pair from exact read-only owner captures."""

    now = datetime.now(timezone.utc)
    if captured_at.tzinfo is None or not now - timedelta(minutes=10) <= captured_at <= now + timedelta(minutes=1):
        raise ValueError("regional invariance capture timestamp is stale, replayed, or future-dated")
    if re.fullmatch(r"[0-9a-f]+", machine_id) is None:
        raise ValueError("regional invariance Machine identity is invalid")

    profile = load_authority_operations_profile(profile_path)
    candidate = _read_invariance_owner_json(
        candidate_receipt_path,
        label="regional invariance candidate receipt",
    )
    expected_candidate_keys = {
        "canonical_receipt_git_sha",
        "canonical_source_git_sha",
        "canonical_tree_git_sha",
        "image_proof",
        "machine_config_sha256",
        "produced_image_tagged_digest",
        "profile_sha256",
        "qualification_kind",
        "schema_version",
        "source_git_sha",
        "source_tree_git_sha",
    }
    if not isinstance(candidate, dict) or set(candidate) != expected_candidate_keys:
        raise ValueError("regional invariance candidate receipt shape mismatch")
    candidate_identity = (
        candidate.get("schema_version"),
        candidate.get("qualification_kind"),
        candidate.get("canonical_receipt_git_sha"),
        candidate.get("canonical_source_git_sha"),
        candidate.get("canonical_tree_git_sha"),
        candidate.get("profile_sha256"),
        candidate.get("machine_config_sha256"),
    )
    expected_candidate_identity = (
        2,
        "authority_refresh_image_candidate",
        profile.canonical_source.receipt_git_sha,
        profile.canonical_source.source_git_sha,
        profile.canonical_source.tree_git_sha,
        canonical_sha256(profile.model_dump(mode="json")),
        profile.machine.config_sha256,
    )
    image_proof = candidate.get("image_proof")
    build_version = image_proof.get("build_version") if isinstance(image_proof, dict) else None
    if (
        candidate_identity != expected_candidate_identity
        or not isinstance(build_version, dict)
        or build_version.get("git_sha") != candidate.get("source_git_sha")
        or not build_version.get("built_at")
        or image_proof != expected_image_plan_proof(profile, build_version=build_version)
    ):
        raise ValueError("regional invariance candidate receipt identity mismatch")

    federal_machines = _read_invariance_owner_json(
        federal_machines_path,
        label="federal Machine inventory",
    )
    federal_config = _read_invariance_owner_json(
        federal_machine_config_path,
        label="federal Machine config",
    )
    federal_volumes = _read_invariance_owner_json(
        federal_volumes_path,
        label="federal volume inventory",
    )
    federal_version = _read_invariance_owner_json(
        federal_version_path,
        label="federal public version",
    )
    public_api_version = _read_invariance_owner_json(
        public_api_version_path,
        label="public API version",
    )
    public_web_version = _read_invariance_owner_json(
        public_web_version_path,
        label="public web version",
    )
    public_content_health = _read_invariance_owner_json(
        public_content_health_path,
        label="public content health",
    )
    raw_database = RawInvarianceDatabaseObservation.model_validate(
        _read_invariance_owner_json(
            database_observation_path,
            label="regional invariance database observation",
        )
    )

    federal_machine_id = "859e0da479e678"
    if (
        not isinstance(federal_machines, list)
        or len(federal_machines) != 1
        or not isinstance(federal_machines[0], dict)
        or federal_machines[0].get("id") != federal_machine_id
        or federal_machines[0].get("name") != "lingering-butterfly-8636"
        or federal_machines[0].get("state") != "stopped"
    ):
        raise ValueError("federal Machine inventory is missing, ambiguous, foreign, or nonterminal")
    expected_federal_config = {
        "init": {"cmd": ["python", "-m", "core.refresh.runner", "--scope", "federal"]},
        "env": {
            "CIVIBUS_ENV": "production",
            "POSTGRES_HOST": "civibus-db.internal",
            "POSTGRES_PORT": "5432",
            "POSTGRES_USER": "civibus",
            "POSTGRES_DB": "civibus",
            "CIVIBUS_REFRESH_DATA_DIR": "/data",
            "CIVIBUS_STARTUP_CANARY": "skip",
        },
        "mounts": [{"volume": "vol_42kzg23gem178304", "path": "/data"}],
        "restart": {"policy": "no"},
    }
    if federal_config != expected_federal_config:
        raise ValueError("federal Machine config is foreign, partial, or secret-bearing")
    if (
        not isinstance(federal_volumes, list)
        or len(federal_volumes) != 1
        or not isinstance(federal_volumes[0], dict)
        or federal_volumes[0].get("id") != "vol_42kzg23gem178304"
        or federal_volumes[0].get("attached_machine_id") != federal_machine_id
    ):
        raise ValueError("federal volume inventory is missing, ambiguous, or foreign")

    def version_identity(payload: object, label: str) -> tuple[str, str]:
        if not isinstance(payload, dict) or set(payload) != {"git_sha", "built_at"}:
            raise ValueError(f"{label} shape mismatch")
        revision = payload.get("git_sha")
        built_at = payload.get("built_at")
        if not isinstance(revision, str) or re.fullmatch(r"[0-9a-f]{40}", revision) is None:
            raise ValueError(f"{label} revision is invalid")
        if not isinstance(built_at, str):
            raise ValueError(f"{label} build timestamp is invalid")
        try:
            parsed_built_at = datetime.fromisoformat(built_at.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError(f"{label} build timestamp is invalid") from error
        if parsed_built_at.tzinfo is None or parsed_built_at > captured_at:
            raise ValueError(f"{label} build timestamp is future-dated")
        return revision, built_at

    federal_revision = version_identity(federal_version, "federal public version")[0]
    api_revision = version_identity(public_api_version, "public API version")[0]
    web_revision = version_identity(public_web_version, "public web version")[0]
    if federal_revision != api_revision or api_revision != web_revision:
        raise ValueError("federal/public API/web revisions are split")
    if public_content_health != {"healthy": True}:
        raise ValueError("public content health is missing or unhealthy")

    expected_database = profile.machine.config.env
    if raw_database.database_name != expected_database["POSTGRES_DB"] or raw_database.server_port != int(
        expected_database["POSTGRES_PORT"]
    ):
        raise ValueError("regional invariance database identity mismatch")
    database = DatabaseIdentity(
        host=expected_database["POSTGRES_HOST"],
        port=int(expected_database["POSTGRES_PORT"]),
        name=expected_database["POSTGRES_DB"],
    )
    database_payload = raw_database.model_dump(mode="json")
    database_record = _invariance_record(
        owner="core.refresh.database_quiescence",
        identity=f"{database.host}:{database.port}/{database.name}",
        row_count=1,
        payload=database_payload,
    )
    federal_records = tuple(
        sorted(
            (
                database_record,
                _invariance_record(
                    owner="infra.fly.federal_machine_config",
                    identity=f"civibus-refresh/{federal_machine_id}/config",
                    row_count=1,
                    payload=federal_config,
                ),
                _invariance_record(
                    owner="infra.fly.federal_machine_inventory",
                    identity=f"civibus-refresh/{federal_machine_id}",
                    row_count=len(federal_machines),
                    payload=federal_machines,
                ),
                _invariance_record(
                    owner="infra.fly.federal_volume_inventory",
                    identity="civibus-refresh/vol_42kzg23gem178304",
                    row_count=len(federal_volumes),
                    payload=federal_volumes,
                ),
                _invariance_record(
                    owner="public.api_health_version",
                    identity="https://civibus.shareborough.com/api/health/version",
                    row_count=1,
                    payload=federal_version,
                ),
            ),
            key=lambda record: (record.owner, record.identity),
        )
    )
    public_records = tuple(
        sorted(
            (
                database_record,
                _invariance_record(
                    owner="public.api_health_content",
                    identity="https://civibus-caddy.fly.dev/api/health/content",
                    row_count=1,
                    payload=public_content_health,
                ),
                _invariance_record(
                    owner="public.api_health_version",
                    identity="https://civibus-caddy.fly.dev/api/health/version",
                    row_count=1,
                    payload=public_api_version,
                ),
                _invariance_record(
                    owner="public.web_version",
                    identity="https://civibus-caddy.fly.dev/version.json",
                    row_count=1,
                    payload=public_web_version,
                ),
            ),
            key=lambda record: (record.owner, record.identity),
        )
    )
    common = {
        "schema_version": 2,
        "producer": "regional_lifecycle_invariance_capture",
        "stage": stage,
        "captured_at": captured_at,
        "canonical_receipt_git_sha": profile.canonical_source.receipt_git_sha,
        "canonical_source_git_sha": profile.canonical_source.source_git_sha,
        "canonical_tree_git_sha": profile.canonical_source.tree_git_sha,
        "source_revision": candidate["source_git_sha"],
        "source_tree_git_sha": candidate["source_tree_git_sha"],
        "authority": profile.execution_plan.authority,
        "execution_plan": profile.execution_plan.plan_id,
        "job_key": profile.execution_plan.canary.job_keys[0],
        "execution_origin": "operator_attended",
        "profile_file_sha256": hashlib.sha256(profile_path.read_bytes()).hexdigest(),
        "candidate_receipt_file_sha256": hashlib.sha256(candidate_receipt_path.read_bytes()).hexdigest(),
        "qualified_image": candidate["produced_image_tagged_digest"],
        "app": profile.app,
        "machine_id": machine_id,
        "machine_name": profile.machine.name,
        "machine_config_sha256": profile.machine.config_sha256,
        "database": database,
        "api_revision": api_revision,
        "web_revision": web_revision,
    }

    def snapshot(
        scope: Literal["federal", "public"], records: tuple[RawInvarianceRecord, ...]
    ) -> RawInvarianceSnapshot:
        payload = {**common, "scope": scope, "records": records}
        identity_payload = {
            key: value
            for key, value in RawInvarianceSnapshot.model_construct(
                **payload,
                identity_sha256="0" * 64,
            )
            .model_dump(mode="json")
            .items()
            if key not in {"captured_at", "stage", "identity_sha256"}
        }
        return RawInvarianceSnapshot(
            **payload,
            identity_sha256=canonical_sha256(identity_payload),
        )

    return snapshot("federal", federal_records), snapshot("public", public_records)


def _exact_set_refusal(
    *,
    label: str,
    expected: set[str],
    actual: set[str],
) -> str | None:
    if actual == expected:
        return None
    missing = ", ".join(sorted(expected - actual)) or "none"
    unexpected = ", ".join(sorted(actual - expected)) or "none"
    return f"{label} exact set mismatch (missing: {missing}; unexpected: {unexpected})."


def assess_authority_promotion(evidence: AuthorityPromotionEvidence) -> AuthorityPromotionDecision:
    """Require exact authority/source/recurrence/provenance/Keel/deploy proof.

    This function owns only the decision rule. Callers remain responsible for
    reading each canonical evidence owner and may not synthesize missing inputs.
    """

    expected = set(evidence.expected_source_identities)
    refusals: list[str] = []
    if evidence.authority_relation == "unresolved":
        refusals.append("The filing authority relation is unresolved.")
    if evidence.authority_relation == "partitioned_overlapping" and evidence.aggregation_disposition in {
        "refuse_combination",
        "refuse",
    }:
        refusals.append("The authority overlap disposition refuses combined promotion.")

    source_by_identity = {row.source_identity: row for row in evidence.source_evidence}
    recurrence_by_identity = {row.source_identity: row for row in evidence.recurrence_evidence}
    for label, actual in (
        ("freshness", set(source_by_identity)),
        ("recurrence", set(recurrence_by_identity)),
        ("provenance", set(evidence.provenance_source_identities)),
        ("Keel", set(evidence.keel_source_identities)),
        ("deployed evidence", set(evidence.deployed_source_identities)),
    ):
        refusal = _exact_set_refusal(label=label, expected=expected, actual=actual)
        if refusal is not None:
            refusals.append(refusal)

    for source_identity in sorted(expected & set(source_by_identity)):
        source = source_by_identity[source_identity]
        if source.freshness_status != "fresh":
            refusals.append(f"Source {source_identity} is {source.freshness_status}, not fresh.")
        if source.observed_at is None:
            refusals.append(f"Source {source_identity} has no freshness observation time.")

    for source_identity in sorted(expected & set(recurrence_by_identity)):
        recurrence = recurrence_by_identity[source_identity]
        if recurrence.pull_status != "success":
            refusals.append(f"Source {source_identity} recurrence is {recurrence.pull_status}, not success.")
        if recurrence.execution_origin != "scheduled":
            refusals.append(
                f"Source {source_identity} recurrence origin is {recurrence.execution_origin}, not scheduled."
            )
        if recurrence.completed_at is None:
            refusals.append(f"Source {source_identity} recurrence has no completion time.")

    revision_parity: AuthorityRevisionParityLiteral
    if evidence.source_revision is None or evidence.api_revision is None or evidence.web_revision is None:
        revision_parity = "unknown"
        refusals.append("Serving source/API/web revision parity is unknown.")
    elif len({evidence.source_revision, evidence.api_revision, evidence.web_revision}) != 1:
        revision_parity = "mismatch"
        refusals.append("Serving source/API/web revision parity is mismatched.")
    else:
        revision_parity = "match"

    unique_refusals = list(dict.fromkeys(refusals))
    return AuthorityPromotionDecision(
        authority_identity=evidence.authority_identity,
        eligible=not unique_refusals,
        revision_parity=revision_parity,
        refusal_reasons=unique_refusals,
    )


class AuthorityPromotionReceipt(LifecycleBaseModel):
    """Hash-bound canonical evidence for one independent filing authority."""

    schema_version: Literal[1]
    issued_at: datetime
    jurisdiction_code: NonBlankText
    geographic_subject: PromotionGeographicSubject
    filing_authority: FilingAuthorityReference
    authority_relation: Literal["independent"]
    aggregation_disposition: Literal["not_applicable"]
    provenance_scope: NonBlankText
    promotion_evidence: AuthorityPromotionEvidence
    canonical_evidence: list[CanonicalPromotionEvidence]

    @model_validator(mode="after")
    def _validate_exact_canonical_inputs(self) -> "AuthorityPromotionReceipt":
        if self.issued_at.tzinfo is None or self.issued_at.utcoffset() is None:
            raise ValueError("promotion receipt issued_at must be timezone-aware")
        self.issued_at = self.issued_at.astimezone(timezone.utc)
        if self.geographic_subject.code != self.jurisdiction_code:
            raise ValueError("promotion receipt geographic subject does not match jurisdiction")
        if (self.geographic_subject.kind, self.geographic_subject.code) != (
            self.filing_authority.kind,
            self.filing_authority.code,
        ):
            raise ValueError("independent promotion receipt must bind distinct domains to the same typed identity")
        authority_identity = f"{self.filing_authority.kind}/{self.filing_authority.code}"
        if self.provenance_scope != authority_identity:
            raise ValueError("promotion receipt provenance scope must match exact filing authority identity")
        if self.promotion_evidence.authority_identity != authority_identity:
            raise ValueError("promotion receipt filing authority identity mismatch")
        if self.promotion_evidence.authority_relation != self.authority_relation:
            raise ValueError("promotion receipt authority relation mismatch")
        if self.promotion_evidence.aggregation_disposition != self.aggregation_disposition:
            raise ValueError("promotion receipt aggregation disposition mismatch")

        expected_sources = tuple(self.promotion_evidence.expected_source_identities)
        for label, identities in (
            ("freshness", tuple(row.source_identity for row in self.promotion_evidence.source_evidence)),
            ("recurrence", tuple(row.source_identity for row in self.promotion_evidence.recurrence_evidence)),
            ("provenance", tuple(self.promotion_evidence.provenance_source_identities)),
            ("Keel", tuple(self.promotion_evidence.keel_source_identities)),
            ("deployed", tuple(self.promotion_evidence.deployed_source_identities)),
        ):
            if identities != expected_sources:
                raise ValueError(f"promotion receipt {label} evidence must follow the exact source order")

        expected_kinds = (
            "canary_ledger",
            "scheduled_recurrence",
            "filing_authority",
            "provenance",
            "keel",
            "serving_deploy",
            "surface_parity",
        )
        if tuple(item.kind for item in self.canonical_evidence) != expected_kinds:
            raise ValueError("promotion receipt requires exact ordered canonical evidence")
        evidence_paths = [item.path for item in self.canonical_evidence]
        if len(evidence_paths) != len(set(evidence_paths)):
            raise ValueError("promotion receipt canonical evidence paths must be distinct")

        decision = assess_authority_promotion(self.promotion_evidence)
        if not decision.eligible:
            raise ValueError("promotion receipt evidence must itself be promotion-eligible")
        evidence_times = [
            timestamp
            for timestamp in (
                *[row.observed_at for row in self.promotion_evidence.source_evidence],
                *[row.completed_at for row in self.promotion_evidence.recurrence_evidence],
            )
            if timestamp is not None
        ]
        if any(timestamp > self.issued_at for timestamp in evidence_times):
            raise ValueError("promotion receipt cannot predate its source or recurrence evidence")
        return self


def _read_strict_promotion_json(path: Path, *, label: str) -> object:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"{label} must be a regular non-symlink file")

    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        payload: dict[str, object] = {}
        for key, value in pairs:
            if key in payload:
                raise ValueError(f"{label} contains a duplicate object key")
            payload[key] = value
        return payload

    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"{label} contains non-finite number {value}")
            ),
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is not readable strict JSON") from error


def _reject_credential_bearing_promotion_json(payload: object, *, label: str) -> None:
    """Keep credentials and secrets out of the immutable serving image."""

    if isinstance(payload, dict):
        for key, value in payload.items():
            normalized_key = "_".join(part for part in key.lower().replace("-", "_").split("_") if part)
            if normalized_key in _CREDENTIAL_BEARING_JSON_KEYS or normalized_key.endswith(
                _CREDENTIAL_BEARING_JSON_KEY_SUFFIXES
            ):
                raise ValueError(f"{label} contains credential-bearing key {key!r}")
            _reject_credential_bearing_promotion_json(value, label=label)
    elif isinstance(payload, list):
        for value in payload:
            _reject_credential_bearing_promotion_json(value, label=label)


def _resolve_promotion_path(path_text: str | Path, *, filesystem_root: Path | None) -> Path:
    path = Path(path_text)
    if filesystem_root is None:
        return path
    if not path.is_absolute():
        raise ValueError("canonical promotion evidence paths must be absolute")
    root = Path(filesystem_root)
    if not root.is_dir() or root.is_symlink():
        raise ValueError("promotion evidence filesystem root must be a regular non-symlink directory")
    return root.joinpath(*path.parts[1:])


def _parse_canonical_promotion_artifact(
    artifact: CanonicalPromotionEvidence,
    model: type[BaseModel],
    *,
    filesystem_root: Path | None,
) -> BaseModel:
    label = f"canonical {artifact.kind} evidence"
    payload = _read_strict_promotion_json(
        _resolve_promotion_path(artifact.path, filesystem_root=filesystem_root),
        label=label,
    )
    try:
        return model.model_validate(payload)
    except ValidationError as error:
        raise ValueError(f"Invalid {label}: {format_validation_errors(error)}") from error


def _promotion_authority_identity(authority: FilingAuthorityReference) -> str:
    return f"{authority.kind}/{authority.code}"


def _load_hash_bound_promotion_model(
    *,
    path_text: str,
    expected_sha256: str,
    label: str,
    model: type[BaseModel],
    filesystem_root: Path | None,
) -> BaseModel:
    path = _resolve_promotion_path(path_text, filesystem_root=filesystem_root)
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"{label} must be a regular non-symlink file")
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha256:
        raise ValueError(f"{label} digest mismatch")
    try:
        return model.model_validate(_read_strict_promotion_json(path, label=label))
    except ValidationError as error:
        raise ValueError(f"Invalid {label}: {format_validation_errors(error)}") from error


def _load_hash_bound_promotion_payload(
    reference: HashBoundPromotionFile,
    *,
    label: str,
    filesystem_root: Path | None,
) -> object:
    path = _resolve_promotion_path(reference.path, filesystem_root=filesystem_root)
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"{label} must be a regular non-symlink file")
    if hashlib.sha256(path.read_bytes()).hexdigest() != reference.sha256:
        raise ValueError(f"{label} digest mismatch")
    return _read_strict_promotion_json(path, label=label)


def _validate_canary_candidate(
    canary: RegionalCanaryPromotionArtifact,
    *,
    profile: AuthorityOperationsProfile,
    serving: ServingDeployPromotionArtifact,
    filesystem_root: Path | None,
) -> None:
    candidate = _load_hash_bound_promotion_payload(
        canary.candidate_receipt,
        label="canary qualified candidate receipt",
        filesystem_root=filesystem_root,
    )
    expected_candidate_keys = {
        "canonical_receipt_git_sha",
        "canonical_source_git_sha",
        "canonical_tree_git_sha",
        "image_proof",
        "machine_config_sha256",
        "produced_image_tagged_digest",
        "profile_sha256",
        "qualification_kind",
        "schema_version",
        "source_git_sha",
        "source_tree_git_sha",
    }
    if not isinstance(candidate, dict) or set(candidate) != expected_candidate_keys:
        raise ValueError("canonical canary qualified candidate receipt shape mismatch")
    expected_identity = (
        2,
        "authority_refresh_image_candidate",
        profile.canonical_source.receipt_git_sha,
        profile.canonical_source.source_git_sha,
        profile.canonical_source.tree_git_sha,
        canonical_sha256(profile.model_dump(mode="json")),
        profile.machine.config_sha256,
    )
    actual_identity = tuple(
        candidate.get(key)
        for key in (
            "schema_version",
            "qualification_kind",
            "canonical_receipt_git_sha",
            "canonical_source_git_sha",
            "canonical_tree_git_sha",
            "profile_sha256",
            "machine_config_sha256",
        )
    )
    image_proof = candidate.get("image_proof")
    build_version = image_proof.get("build_version") if isinstance(image_proof, dict) else None
    if actual_identity != expected_identity or not isinstance(build_version, dict):
        raise ValueError("canonical canary qualified candidate receipt identity mismatch")
    built_at = build_version.get("built_at")
    if build_version.get("git_sha") != candidate.get("source_git_sha"):
        raise ValueError("canonical canary qualified candidate receipt identity mismatch")
    if not isinstance(built_at, str) or not built_at:
        raise ValueError("canonical canary qualified candidate receipt identity mismatch")
    if image_proof != expected_image_plan_proof(profile, build_version=build_version):
        raise ValueError("canonical canary qualified candidate receipt identity mismatch")
    candidate_serving_identity = (
        candidate.get("source_git_sha"),
        candidate.get("source_tree_git_sha"),
        candidate.get("produced_image_tagged_digest"),
        canary.candidate_receipt.sha256,
        canary.candidate_source_git_sha,
        canary.candidate_tree_git_sha,
        canary.qualified_image,
        canary.candidate_source_git_sha,
    )
    expected_serving_identity = (
        canary.candidate_source_git_sha,
        canary.candidate_tree_git_sha,
        canary.qualified_image,
        serving.candidate_receipt_file_sha256,
        serving.candidate_source_git_sha,
        serving.candidate_tree_git_sha,
        serving.qualified_image,
        serving.source_revision,
    )
    if candidate_serving_identity != expected_serving_identity:
        raise ValueError(
            "canonical canary candidate receipt mismatch: candidate, receipt, tree, image, or serving revision mismatch"
        )


def _validate_canary_terminal_and_postcondition(
    canary: RegionalCanaryPromotionArtifact,
    refresh_run: RefreshRunEvidence,
    *,
    authority_identity: str,
    filesystem_root: Path | None,
) -> None:
    terminal_payload = _load_hash_bound_promotion_payload(
        canary.terminal_machine_evidence,
        label="canary terminal Machine evidence",
        filesystem_root=filesystem_root,
    )
    try:
        terminal = RawCanaryTerminalMachine.model_validate(terminal_payload)
    except ValidationError as error:
        raise ValueError(f"Invalid canary terminal Machine evidence: {format_validation_errors(error)}") from error
    expected_terminal = ScheduledTerminalEvent(
        state=terminal.state,
        exit_code=terminal.exit_code,
        machine_id=terminal.machine_id,
        occurred_at=terminal.occurred_at,
    )
    terminal_identity = (
        terminal.app,
        terminal.machine_id,
        terminal.machine_name,
        terminal.image,
        terminal.machine_config_sha256,
        expected_terminal,
    )
    expected_terminal_identity = (
        canary.app,
        canary.machine_id,
        canary.machine_name,
        canary.qualified_image,
        canary.machine_config_sha256,
        canary.terminal_event,
    )
    if terminal_identity != expected_terminal_identity:
        raise ValueError("canonical canary terminal Machine evidence mismatch")
    if not (
        terminal.occurred_at <= terminal.captured_at <= canary.observed_at
        and terminal.captured_at >= refresh_run.completed_at
    ):
        raise ValueError("canonical canary terminal Machine capture window mismatch")

    postcondition_payload = _load_hash_bound_promotion_payload(
        canary.database_postcondition,
        label="canary database postcondition",
        filesystem_root=filesystem_root,
    )
    try:
        postcondition = RawCanaryDatabasePostcondition.model_validate(postcondition_payload)
    except ValidationError as error:
        raise ValueError(f"Invalid canary database postcondition: {format_validation_errors(error)}") from error
    postcondition_identity = (
        postcondition.app,
        postcondition.machine_id,
        postcondition.authority,
        postcondition.execution_plan,
        postcondition.refresh_run_id,
        postcondition.job_key,
        postcondition.database,
        postcondition.completed_at,
    )
    expected_postcondition_identity = (
        canary.app,
        canary.machine_id,
        authority_identity,
        canary.execution_plan_id,
        canary.refresh_run_id,
        canary.job_key,
        canary.database,
        refresh_run.completed_at,
    )
    derived_quiescence = RefreshQuiescence(
        running_refresh_rows=postcondition.running_refresh_rows,
        active_refresh_backends=postcondition.active_refresh_backends,
        long_idle_transactions=postcondition.long_idle_transactions,
        ungranted_locks=postcondition.ungranted_locks,
    )
    if postcondition_identity != expected_postcondition_identity or canary.quiescence != derived_quiescence:
        raise ValueError("canonical canary database postcondition identity or quiescence mismatch")
    completed_at = refresh_run.completed_at
    if not (
        completed_at <= canary.terminal_event.occurred_at <= canary.observed_at
        and completed_at >= canary.observed_at - timedelta(minutes=30)
    ):
        raise ValueError("canonical canary evidence is stale or nonterminal")


def _validate_canary_invariance(
    canary: RegionalCanaryPromotionArtifact,
    *,
    refresh_run: RefreshRunEvidence,
    filesystem_root: Path | None,
) -> str:
    start_references = tuple(
        reference for reference in canary.lifecycle_markers if reference.kind == "regional_start_attempt"
    )
    if len(start_references) != 1:
        raise ValueError("canonical canary invariance requires one exact start-admission marker")
    start_payload = _load_hash_bound_promotion_payload(
        start_references[0],
        label="canary start-admission lifecycle marker",
        filesystem_root=filesystem_root,
    )
    try:
        start_marker = RawRegionalLifecycleMarker.model_validate(start_payload)
    except ValidationError as error:
        raise ValueError(f"Invalid canary start-admission marker: {format_validation_errors(error)}") from error
    expected_start_identity = (
        "regional_start_attempt",
        canary.app,
        f"{canary.authority.kind}/{canary.authority.code}",
        canary.execution_plan_id,
        canary.machine_name,
        canary.machine_id,
        canary.profile_file_sha256,
        canary.candidate_receipt.sha256,
    )
    actual_start_identity = (
        start_marker.kind,
        start_marker.app,
        start_marker.authority,
        start_marker.execution_plan,
        start_marker.machine_name,
        start_marker.machine_id,
        start_marker.profile_file_sha256,
        start_marker.candidate_receipt_file_sha256,
    )
    admission = start_marker.invariance_admission
    if (
        start_marker.schema_version != 3
        or admission is None
        or actual_start_identity != expected_start_identity
        or not (
            admission.admitted_at <= refresh_run.started_at <= canary.terminal_event.occurred_at
            and canary.terminal_event.occurred_at <= admission.admitted_at + timedelta(minutes=30)
            and admission.admitted_at <= canary.observed_at
        )
    ):
        raise ValueError("canonical canary start-admission identity or time window mismatch")
    federal_identity = ""
    for before_ref, after_ref, scope in (
        (canary.federal_invariance_before, canary.federal_invariance_after, "federal"),
        (canary.public_invariance_before, canary.public_invariance_after, "public"),
    ):
        before_payload = _load_hash_bound_promotion_payload(
            before_ref,
            label=f"canary {scope} invariance before evidence",
            filesystem_root=filesystem_root,
        )
        after_payload = _load_hash_bound_promotion_payload(
            after_ref,
            label=f"canary {scope} invariance after evidence",
            filesystem_root=filesystem_root,
        )
        try:
            before = RawInvarianceSnapshot.model_validate(before_payload)
            after = RawInvarianceSnapshot.model_validate(after_payload)
        except ValidationError as error:
            raise ValueError(
                f"canonical canary {scope} invariance mismatch: {format_validation_errors(error)}"
            ) from error
        expected_identity = (
            "regional_lifecycle_invariance_capture",
            scope,
            canary.candidate_source_git_sha,
            canary.candidate_tree_git_sha,
            (canary.authority.kind, canary.authority.code),
            canary.execution_plan_id,
            canary.job_key,
            "operator_attended",
            canary.profile_file_sha256,
            canary.candidate_receipt.sha256,
            canary.qualified_image,
            canary.app,
            canary.machine_id,
            canary.machine_name,
            canary.machine_config_sha256,
            canary.database,
        )
        before_identity = (
            before.producer,
            before.scope,
            before.source_revision,
            before.source_tree_git_sha,
            (before.authority.kind, before.authority.code),
            before.execution_plan,
            before.job_key,
            before.execution_origin,
            before.profile_file_sha256,
            before.candidate_receipt_file_sha256,
            before.qualified_image,
            before.app,
            before.machine_id,
            before.machine_name,
            before.machine_config_sha256,
            before.database,
        )
        after_identity = (
            after.producer,
            after.scope,
            after.source_revision,
            after.source_tree_git_sha,
            (after.authority.kind, after.authority.code),
            after.execution_plan,
            after.job_key,
            after.execution_origin,
            after.profile_file_sha256,
            after.candidate_receipt_file_sha256,
            after.qualified_image,
            after.app,
            after.machine_id,
            after.machine_name,
            after.machine_config_sha256,
            after.database,
        )
        admission_reference = getattr(admission, f"{scope}_before")
        if (
            before.stage != "before"
            or after.stage != "after"
            or before_identity != expected_identity
            or after_identity != expected_identity
            or before.canonical_receipt_git_sha != after.canonical_receipt_git_sha
            or before.canonical_source_git_sha != after.canonical_source_git_sha
            or before.canonical_tree_git_sha != after.canonical_tree_git_sha
            or before.api_revision != after.api_revision
            or before.web_revision != after.web_revision
            or before.records != after.records
            or before.identity_sha256 != after.identity_sha256
            or before_ref.sha256 != admission_reference.snapshot_sha256
            or before.identity_sha256 != admission_reference.identity_sha256
            or not (
                invariance_capture_time_is_fresh(
                    before.captured_at,
                    admitted_at=admission.admitted_at,
                    max_age_seconds=admission.max_age_seconds,
                    future_skew_seconds=admission.future_skew_seconds,
                )
                and before.captured_at <= refresh_run.started_at
                and canary.terminal_event.occurred_at <= after.captured_at <= canary.observed_at
            )
        ):
            raise ValueError(f"canonical canary {scope} invariance mismatch")
        if scope == "federal":
            federal_identity = before.identity_sha256
    return federal_identity


def _validate_canary_markers_and_rollback(
    canary: RegionalCanaryPromotionArtifact,
    *,
    authority_identity: str,
    filesystem_root: Path | None,
) -> None:
    marker_machine_id = {
        "regional_create_ownership": None,
        "regional_rollback_attempt": None,
    }
    for reference in canary.lifecycle_markers:
        payload = _load_hash_bound_promotion_payload(
            reference,
            label=f"canary lifecycle marker {reference.kind}",
            filesystem_root=filesystem_root,
        )
        try:
            marker = RawRegionalLifecycleMarker.model_validate(payload)
        except ValidationError as error:
            raise ValueError(f"Invalid canary lifecycle marker: {format_validation_errors(error)}") from error
        expected_machine_id = marker_machine_id.get(reference.kind, canary.machine_id)
        marker_identity = (
            marker.kind,
            marker.app,
            marker.authority,
            marker.execution_plan,
            marker.machine_name,
            marker.machine_id,
            marker.profile_file_sha256,
            marker.candidate_receipt_file_sha256,
        )
        expected_identity = (
            reference.kind,
            canary.app,
            authority_identity,
            canary.execution_plan_id,
            canary.machine_name,
            expected_machine_id,
            canary.profile_file_sha256,
            canary.candidate_receipt.sha256,
        )
        if marker_identity != expected_identity:
            raise ValueError("canonical canary lifecycle marker identity mismatch")

    app_inventory_before = _load_hash_bound_promotion_payload(
        canary.rollback_app_inventory_before,
        label="canary rollback app inventory before",
        filesystem_root=filesystem_root,
    )
    if not isinstance(app_inventory_before, list):
        raise ValueError("canonical canary rollback app inventory before must be a list")
    matching_apps = []
    for row in app_inventory_before:
        if not isinstance(row, dict):
            raise ValueError("canonical canary rollback app inventory before contains a malformed row")
        name = row.get("Name", row.get("name"))
        app_id = row.get("ID")
        if not isinstance(name, str) or not isinstance(app_id, str):
            raise ValueError("canonical canary rollback app inventory before row identity is malformed")
        if name == canary.app or app_id == canary.app:
            matching_apps.append(row)
    if len(matching_apps) != 1:
        raise ValueError("canonical canary rollback app inventory before is absent or ambiguous")

    machine_inventory_before = _load_hash_bound_promotion_payload(
        canary.rollback_machine_inventory_before,
        label="canary rollback Machine inventory before",
        filesystem_root=filesystem_root,
    )
    if not isinstance(machine_inventory_before, list) or len(machine_inventory_before) != 1:
        raise ValueError("canonical canary rollback Machine inventory before is absent or ambiguous")
    machine_before = machine_inventory_before[0]
    if not isinstance(machine_before, dict) or (
        machine_before.get("id"),
        machine_before.get("name"),
        machine_before.get("state"),
    ) != (canary.machine_id, canary.machine_name, "stopped"):
        raise ValueError("canonical canary rollback Machine inventory before identity mismatch")
    volume_inventory_before = _load_hash_bound_promotion_payload(
        canary.rollback_volume_inventory_before,
        label="canary rollback volume inventory before",
        filesystem_root=filesystem_root,
    )
    if volume_inventory_before != []:
        raise ValueError("canonical canary rollback volume inventory before is nonzero or malformed")

    app_inventory = _load_hash_bound_promotion_payload(
        canary.rollback_app_inventory,
        label="canary rollback app inventory after",
        filesystem_root=filesystem_root,
    )
    if not isinstance(app_inventory, list):
        raise ValueError("canonical canary rollback app inventory must be a list")
    for row in app_inventory:
        if not isinstance(row, dict):
            raise ValueError("canonical canary rollback app inventory contains a malformed row")
        name = row.get("Name", row.get("name"))
        app_id = row.get("ID")
        if not isinstance(name, str) or not isinstance(app_id, str):
            raise ValueError("canonical canary rollback app inventory row identity is malformed")
        if name == canary.app or app_id == canary.app:
            raise ValueError("canonical canary rollback app inventory is nonzero or ambiguous")
    for reference, label in (
        (canary.rollback_machine_inventory, "Machine"),
        (canary.rollback_volume_inventory, "volume"),
    ):
        inventory = _load_hash_bound_promotion_payload(
            reference,
            label=f"canary rollback {label} inventory",
            filesystem_root=filesystem_root,
        )
        if inventory != []:
            raise ValueError(f"canonical canary rollback {label} inventory is nonzero or malformed")


def _validate_canary_promotion_artifact(
    canary: RegionalCanaryPromotionArtifact,
    *,
    profile: AuthorityOperationsProfile,
    registry_jobs: Sequence[RefreshJobLike],
    authority_identity: str,
    serving: ServingDeployPromotionArtifact,
    filesystem_root: Path | None,
) -> tuple[tuple[str, ...], datetime, str]:
    proof = _load_hash_bound_promotion_model(
        path_text=canary.authority_ledger_proof.path,
        expected_sha256=canary.authority_ledger_proof.sha256,
        label="canary authority ledger proof",
        model=AuthorityLedgerProof,
        filesystem_root=filesystem_root,
    )
    assert isinstance(proof, AuthorityLedgerProof)
    if _promotion_authority_identity(canary.authority) != authority_identity:
        raise ValueError("canonical canary ledger filing authority mismatch")
    if proof.authority.operational_scope != authority_identity or proof.execution_mode != "canary":
        raise ValueError("canonical canary ledger must contain canary execution evidence")
    validate_authority_ledger_proof(profile, proof, registry_jobs=registry_jobs)
    if len(proof.runner_results) != 1 or len(proof.refresh_runs) != 1 or proof.observed_plan_row_count != 1:
        raise ValueError("canonical canary ledger must contain exactly one executed canary result")
    result = proof.runner_results[0]
    refresh_run = proof.refresh_runs[0]
    if (
        result.job_key != refresh_run.job_key
        or result.status != "success"
        or refresh_run.pull_status != "success"
        or refresh_run.execution_origin != "operator_attended"
    ):
        raise ValueError("canonical canary ledger must prove one attended successful refresh")
    source_names = tuple(source.name for source in proof.data_sources)
    if not source_names or refresh_run.data_source_names != source_names:
        raise ValueError("canonical canary ledger data-source ownership mismatch")
    if result.metadata_updates != len(source_names) or refresh_run.metadata_updates != len(source_names):
        raise ValueError("canonical canary ledger metadata advancement mismatch")
    if refresh_run.started_at < proof.observed_after or refresh_run.completed_at < refresh_run.started_at:
        raise ValueError("canonical canary ledger execution window mismatch")
    for source in proof.data_sources:
        if (
            source.jurisdiction != authority_identity
            or source.post_last_pull_status != "success"
            or source.post_last_pull_at < refresh_run.completed_at
        ):
            raise ValueError("canonical canary ledger source freshness mismatch")
        if source.baseline_last_pull_at is not None and source.post_last_pull_at <= source.baseline_last_pull_at:
            raise ValueError("canonical canary ledger source freshness did not advance")

    profile_file_sha256 = hashlib.sha256(_WASHINGTON_REGIONAL_PROFILE_PATH.read_bytes()).hexdigest()
    if (
        canary.profile_file_sha256 != profile_file_sha256
        or canary.app != profile.app
        or canary.machine_name != profile.machine.name
        or canary.machine_config_sha256 != profile.machine.config_sha256
        or canary.execution_plan_id != profile.execution_plan.plan_id
        or canary.job_key != profile.execution_plan.canary.job_keys[0]
        or canary.execution_origin != profile.execution_plan.canary.execution_origin
        or canary.refresh_run_id != refresh_run.refresh_run_id
    ):
        raise ValueError("canonical canary profile, app, Machine, plan, job, or attempt mismatch")
    if canary.database != DatabaseIdentity(
        host=profile.machine.config.env["POSTGRES_HOST"],
        port=int(profile.machine.config.env["POSTGRES_PORT"]),
        name=profile.machine.config.env["POSTGRES_DB"],
    ):
        raise ValueError("canonical canary database identity mismatch")

    _validate_canary_candidate(
        canary,
        profile=profile,
        serving=serving,
        filesystem_root=filesystem_root,
    )

    _validate_canary_terminal_and_postcondition(
        canary,
        refresh_run,
        authority_identity=authority_identity,
        filesystem_root=filesystem_root,
    )

    federal_identity_sha256 = _validate_canary_invariance(
        canary,
        refresh_run=refresh_run,
        filesystem_root=filesystem_root,
    )

    _validate_canary_markers_and_rollback(
        canary,
        authority_identity=authority_identity,
        filesystem_root=filesystem_root,
    )

    return (
        tuple(f"{authority_identity}:{name}" for name in source_names),
        refresh_run.completed_at,
        federal_identity_sha256,
    )


def validate_regional_canary_promotion_artifact(
    artifact: RegionalCanaryPromotionArtifact,
    *,
    profile_path: Path,
    candidate_receipt_path: Path,
    filesystem_root: Path | None = None,
) -> None:
    """Validate one standalone canary artifact for recurring admission."""

    if profile_path.is_symlink() or not profile_path.is_file():
        raise ValueError("regional canary admission profile must be a regular non-symlink file")
    profile = load_authority_operations_profile(profile_path)
    if candidate_receipt_path.is_symlink() or not candidate_receipt_path.is_file():
        raise ValueError("regional canary admission candidate receipt must be a regular non-symlink file")
    candidate_path = candidate_receipt_path.resolve(strict=True)
    if hashlib.sha256(candidate_path.read_bytes()).hexdigest() != artifact.candidate_receipt.sha256:
        raise ValueError("regional canary admission candidate receipt digest mismatch")
    proof = _load_hash_bound_promotion_model(
        path_text=artifact.authority_ledger_proof.path,
        expected_sha256=artifact.authority_ledger_proof.sha256,
        label="canary authority ledger proof",
        model=AuthorityLedgerProof,
        filesystem_root=filesystem_root,
    )
    assert isinstance(proof, AuthorityLedgerProof)
    source_identities = [f"{profile.authority.operational_scope}:{source.name}" for source in proof.data_sources]
    serving = ServingDeployPromotionArtifact(
        schema_version=1,
        filing_authority=FilingAuthorityReference(
            kind=profile.authority.kind,
            code=profile.authority.code,
        ),
        source_identities=source_identities,
        candidate_receipt_file_sha256=artifact.candidate_receipt.sha256,
        candidate_source_git_sha=artifact.candidate_source_git_sha,
        candidate_tree_git_sha=artifact.candidate_tree_git_sha,
        qualified_image=artifact.qualified_image,
        source_revision=artifact.candidate_source_git_sha,
        api_revision=artifact.candidate_source_git_sha,
        web_revision=artifact.candidate_source_git_sha,
    )
    registry_jobs = job_builders.build_refresh_plan(
        scope="all",
        parameters=RunnerParameters(),
        job_key_prefixes=(),
    )
    _validate_canary_promotion_artifact(
        artifact,
        profile=profile,
        registry_jobs=registry_jobs,
        authority_identity=profile.authority.operational_scope,
        serving=serving,
        filesystem_root=filesystem_root,
    )


def build_regional_canary_promotion_artifact(
    *,
    evidence_directory: Path,
    output_path: Path,
) -> RegionalCanaryPromotionArtifact:
    """Build the existing canary artifact from the lifecycle's durable files."""

    root = evidence_directory.resolve(strict=True)
    if not root.is_dir() or root.is_symlink():
        raise ValueError("regional canary evidence directory must be a regular non-symlink directory")

    def reference(name: str, label: str) -> HashBoundPromotionFile:
        return _mode_0600_hash_bound_file(root / name, label=label)

    profile_path = root / "profile.json"
    candidate_path = root / "candidate_receipt.json"
    profile_reference = reference("profile.json", "regional canary profile snapshot")
    candidate_reference = reference("candidate_receipt.json", "regional canary candidate snapshot")
    profile = load_authority_operations_profile(profile_path)
    candidate = _read_strict_promotion_json(candidate_path, label="regional canary candidate receipt")
    if not isinstance(candidate, dict):
        raise ValueError("regional canary candidate receipt must be an object")

    proof_reference = reference("authority_ledger_proof.json", "regional canary authority ledger proof")
    proof = AuthorityLedgerProof.model_validate(
        _read_strict_promotion_json(
            Path(proof_reference.path),
            label="regional canary authority ledger proof",
        )
    )
    terminal_reference = reference("terminal_machine.json", "regional canary terminal Machine evidence")
    terminal = RawCanaryTerminalMachine.model_validate(
        _read_strict_promotion_json(Path(terminal_reference.path), label="regional canary terminal Machine evidence")
    )
    postcondition_reference = reference(
        "database_postcondition.json",
        "regional canary database postcondition",
    )
    postcondition = RawCanaryDatabasePostcondition.model_validate(
        _read_strict_promotion_json(
            Path(postcondition_reference.path),
            label="regional canary database postcondition",
        )
    )
    federal_before = reference("federal_invariance_before.json", "regional canary federal baseline")
    federal_after = reference("federal_invariance_after.json", "regional canary federal postcondition")
    public_before = reference("public_invariance_before.json", "regional canary public baseline")
    public_after = reference("public_invariance_after.json", "regional canary public postcondition")
    federal_after_payload = RawInvarianceSnapshot.model_validate(
        _read_strict_promotion_json(Path(federal_after.path), label="regional canary federal postcondition")
    )
    public_after_payload = RawInvarianceSnapshot.model_validate(
        _read_strict_promotion_json(Path(public_after.path), label="regional canary public postcondition")
    )

    marker_files = (
        ("regional_create_ownership", "create_ownership.json"),
        ("regional_machine_ownership", "machine_ownership.json"),
        ("regional_stopped_provision", "provision.json"),
        ("regional_start_attempt", "start_attempt.json"),
        ("regional_canary_mode", "canary_mode.json"),
        ("regional_canary_machine_terminal", "canary_machine_terminal.json"),
        ("regional_rollback_attempt", "rollback_attempt.json"),
        ("regional_rollback_stopped", "rollback_stopped.json"),
        ("regional_rollback_complete", "rollback_complete.json"),
    )
    marker_references = tuple(
        CanaryLifecycleMarkerReference(
            kind=kind,
            **reference(name, f"regional canary lifecycle marker {kind}").model_dump(),
        )
        for kind, name in marker_files
    )
    if len(proof.refresh_runs) != 1:
        raise ValueError("regional canary authority ledger must contain exactly one refresh run")
    refresh_run = proof.refresh_runs[0]
    artifact = RegionalCanaryPromotionArtifact(
        schema_version=1,
        observed_at=max(
            terminal.captured_at,
            federal_after_payload.captured_at,
            public_after_payload.captured_at,
            postcondition.completed_at,
        ),
        profile_file_sha256=profile_reference.sha256,
        candidate_receipt=candidate_reference,
        candidate_source_git_sha=candidate.get("source_git_sha"),
        candidate_tree_git_sha=candidate.get("source_tree_git_sha"),
        qualified_image=candidate.get("produced_image_tagged_digest"),
        authority_ledger_proof=proof_reference,
        app=profile.app,
        machine_id=terminal.machine_id,
        machine_name=profile.machine.name,
        machine_config_sha256=profile.machine.config_sha256,
        authority=FilingAuthorityReference(kind=profile.authority.kind, code=profile.authority.code),
        execution_plan_id=profile.execution_plan.plan_id,
        job_key=refresh_run.job_key,
        refresh_run_id=refresh_run.refresh_run_id,
        execution_origin=refresh_run.execution_origin,
        terminal_event=ScheduledTerminalEvent(
            state=terminal.state,
            exit_code=terminal.exit_code,
            machine_id=terminal.machine_id,
            occurred_at=terminal.occurred_at,
        ),
        database=postcondition.database,
        quiescence=RefreshQuiescence(
            running_refresh_rows=postcondition.running_refresh_rows,
            active_refresh_backends=postcondition.active_refresh_backends,
            long_idle_transactions=postcondition.long_idle_transactions,
            ungranted_locks=postcondition.ungranted_locks,
        ),
        terminal_machine_evidence=terminal_reference,
        database_postcondition=postcondition_reference,
        federal_invariance_before=federal_before,
        federal_invariance_after=federal_after,
        public_invariance_before=public_before,
        public_invariance_after=public_after,
        rollback_app_inventory_before=reference(
            "rollback_apps_before.json",
            "regional canary rollback app inventory before",
        ),
        rollback_machine_inventory_before=reference(
            "rollback_machines_before.json",
            "regional canary rollback Machine inventory before",
        ),
        rollback_volume_inventory_before=reference(
            "rollback_volumes_before.json",
            "regional canary rollback volume inventory before",
        ),
        rollback_app_inventory=reference(
            "rollback_apps_after.json",
            "regional canary rollback app inventory after",
        ),
        rollback_machine_inventory=reference(
            "rollback_machines_after.json",
            "regional canary rollback Machine inventory after",
        ),
        rollback_volume_inventory=reference(
            "rollback_volumes_after.json",
            "regional canary rollback volume inventory after",
        ),
        lifecycle_markers=marker_references,
    )
    validate_regional_canary_promotion_artifact(
        artifact,
        profile_path=profile_path,
        candidate_receipt_path=candidate_path,
    )
    _write_new_mode_0600_json(
        output_path,
        artifact.model_dump(mode="json"),
        label="regional canary promotion artifact",
    )
    return artifact


def _validate_scheduled_promotion_artifact(
    scheduled: ScheduledRecurrencePromotionArtifact,
    *,
    profile: AuthorityOperationsProfile,
    registry_jobs: Sequence[RefreshJobLike],
    candidate_receipt_file_sha256: str,
    candidate_source_git_sha: str,
    candidate_tree_git_sha: str,
    qualified_image: str,
    authority_identity: str,
    filesystem_root: Path | None,
) -> tuple[list[AuthoritySourceEvidence], list[AuthorityRecurrenceEvidence], tuple[UUID, ...]]:
    proof = _load_hash_bound_promotion_model(
        path_text=scheduled.authority_ledger_proof_path,
        expected_sha256=scheduled.authority_ledger_proof_sha256,
        label="scheduled authority ledger proof",
        model=AuthorityLedgerProof,
        filesystem_root=filesystem_root,
    )
    receipt = _load_hash_bound_promotion_model(
        path_text=scheduled.observation_receipt_path,
        expected_sha256=scheduled.observation_receipt_sha256,
        label="scheduled observation receipt",
        model=RegionalScheduledObservationReceipt,
        filesystem_root=filesystem_root,
    )
    assert isinstance(proof, AuthorityLedgerProof)
    assert isinstance(receipt, RegionalScheduledObservationReceipt)

    if proof.execution_mode != "scheduled":
        raise ValueError("canonical scheduled recurrence requires a scheduled ledger proof")
    validate_authority_ledger_proof(profile, proof, registry_jobs=registry_jobs)
    if receipt.authority.operational_scope != authority_identity or proof.authority != receipt.authority:
        raise ValueError("canonical scheduled recurrence filing authority mismatch")
    profile_sha256 = hashlib.sha256(_WASHINGTON_REGIONAL_PROFILE_PATH.read_bytes()).hexdigest()
    plan_sha256 = canonical_sha256(profile.execution_plan.model_dump(mode="json"))
    if (
        receipt.profile_id != profile.profile_id
        or receipt.profile_file_sha256 != profile_sha256
        or receipt.app != profile.app
        or receipt.machine_name != profile.machine.name
        or receipt.execution_plan_id != profile.execution_plan.plan_id
        or receipt.execution_plan_sha256 != plan_sha256
        or receipt.machine_config_sha256 != profile.machine.config_sha256
    ):
        raise ValueError("canonical scheduled recurrence profile, app, Machine, or plan mismatch")
    if (
        receipt.candidate_receipt_file_sha256,
        receipt.candidate_source_git_sha,
        receipt.candidate_tree_git_sha,
        receipt.qualified_image,
    ) != (
        candidate_receipt_file_sha256,
        candidate_source_git_sha,
        candidate_tree_git_sha,
        qualified_image,
    ):
        raise ValueError("canonical scheduled recurrence candidate receipt, source, tree, or image mismatch")
    if receipt.authority_ledger_proof_sha256 != canonical_sha256(proof.model_dump(mode="json")):
        raise ValueError("canonical scheduled recurrence ledger proof digest mismatch")
    if receipt.machine_created_at != receipt.observed_after:
        raise ValueError("canonical scheduled recurrence window is not creation-anchored")
    if {
        receipt.start_event.machine_id,
        receipt.terminal_event.machine_id,
    } != {receipt.machine_id} or not receipt.machine_id:
        raise ValueError("canonical scheduled recurrence Machine identity mismatch")
    if not (
        receipt.observed_after
        < receipt.start_event.occurred_at
        < receipt.terminal_event.occurred_at
        <= receipt.observed_at
    ):
        raise ValueError("canonical scheduled recurrence event window mismatch")
    expected_database = (
        profile.machine.config.env["POSTGRES_HOST"],
        int(profile.machine.config.env["POSTGRES_PORT"]),
        profile.machine.config.env["POSTGRES_DB"],
    )
    if (receipt.database.host, receipt.database.port, receipt.database.name) != expected_database:
        raise ValueError("canonical scheduled recurrence database identity mismatch")

    raw_kinds = tuple(row.kind for row in receipt.raw_evidence)
    if raw_kinds != ("fly_app_status", "fly_machine_status", "database_observation"):
        raise ValueError("canonical scheduled recurrence raw evidence order mismatch")
    raw_paths = [row.path for row in receipt.raw_evidence]
    if len(raw_paths) != len(set(raw_paths)):
        raise ValueError("canonical scheduled recurrence raw evidence paths must be distinct")
    raw_payloads: dict[str, BaseModel] = {}
    raw_models: dict[str, type[BaseModel]] = {
        "fly_app_status": RawFlyAppStatus,
        "fly_machine_status": RawFlyMachineStatus,
        "database_observation": RawDatabaseObservation,
    }
    for row in receipt.raw_evidence:
        raw_path = _resolve_promotion_path(row.path, filesystem_root=filesystem_root)
        if not raw_path.is_file() or raw_path.is_symlink():
            raise ValueError(f"canonical scheduled recurrence {row.kind} must be a regular non-symlink file")
        if hashlib.sha256(raw_path.read_bytes()).hexdigest() != row.sha256:
            raise ValueError(f"canonical scheduled recurrence {row.kind} digest mismatch")
        if not receipt.terminal_event.occurred_at <= row.captured_at <= receipt.observed_at:
            raise ValueError("canonical scheduled recurrence raw evidence timestamp mismatch")
        try:
            raw_payloads[row.kind] = raw_models[row.kind].model_validate(
                _read_strict_promotion_json(raw_path, label=f"scheduled {row.kind} raw evidence")
            )
        except ValidationError as error:
            raise ValueError(
                f"Invalid canonical scheduled {row.kind} raw evidence: {format_validation_errors(error)}"
            ) from error
        if raw_payloads[row.kind].captured_at != row.captured_at:  # type: ignore[attr-defined]
            raise ValueError("canonical scheduled recurrence raw capture timestamp mismatch")
    if receipt.observed_at != max(row.captured_at for row in receipt.raw_evidence):
        raise ValueError("canonical scheduled recurrence observation time is not derived from raw evidence")

    raw_app = raw_payloads["fly_app_status"]
    raw_machine = raw_payloads["fly_machine_status"]
    raw_database = raw_payloads["database_observation"]
    assert isinstance(raw_app, RawFlyAppStatus)
    assert isinstance(raw_machine, RawFlyMachineStatus)
    assert isinstance(raw_database, RawDatabaseObservation)
    if raw_app.app != receipt.app or raw_app.machine_ids != (receipt.machine_id,):
        raise ValueError("canonical scheduled recurrence raw app Machine identity mismatch")
    if (
        raw_machine.app != receipt.app
        or raw_machine.machine_id != receipt.machine_id
        or raw_machine.machine_name != receipt.machine_name
        or raw_machine.image != qualified_image
        or raw_machine.machine_config_sha256 != receipt.machine_config_sha256
        or raw_machine.created_at != receipt.machine_created_at
        or tuple(event.type for event in raw_machine.events) != ("start", "stop")
    ):
        raise ValueError("canonical scheduled recurrence raw Fly Machine identity mismatch")
    raw_start, raw_terminal = raw_machine.events
    if (
        raw_start.source != receipt.start_event.source
        or raw_start.occurred_at != receipt.start_event.occurred_at
        or raw_terminal.state != receipt.terminal_event.state
        or raw_terminal.exit_code != receipt.terminal_event.exit_code
        or raw_terminal.occurred_at != receipt.terminal_event.occurred_at
    ):
        raise ValueError("canonical scheduled recurrence raw Machine event mismatch")
    if (
        raw_database.machine_id != receipt.machine_id
        or raw_database.authority != receipt.authority
        or raw_database.execution_plan_id != receipt.execution_plan_id
        or raw_database.database != receipt.database
        or raw_database.runner_results != proof.runner_results
        or raw_database.refresh_runs != proof.refresh_runs
        or raw_database.data_sources != receipt.data_sources
        or raw_database.quiescence != receipt.quiescence
    ):
        raise ValueError("canonical scheduled recurrence raw database evidence mismatch")

    result_keys = tuple(row.job_key for row in proof.runner_results)
    refresh_keys = tuple(row.job_key for row in proof.refresh_runs)
    if not result_keys or result_keys != refresh_keys:
        raise ValueError("canonical scheduled recurrence result and refresh-row order mismatch")
    if any(row.status != "success" for row in proof.runner_results):
        raise ValueError("canonical scheduled recurrence requires every result to succeed")
    if any(row.pull_status != "success" or row.execution_origin != "scheduled" for row in proof.refresh_runs):
        raise ValueError("canonical scheduled recurrence requires scheduled successful refresh rows")

    source_names = tuple(name for row in proof.refresh_runs for name in row.data_source_names)
    if tuple(source.name for source in receipt.data_sources) != source_names:
        raise ValueError("canonical scheduled recurrence source order mismatch")
    if len(source_names) != len(set(source_names)):
        raise ValueError("canonical scheduled recurrence sources must be unique")
    if authority_identity == "state/WA" and len(source_names) != 4:
        raise ValueError("canonical Washington recurrence requires exact four source identities")

    completed_by_source: dict[str, datetime] = {}
    for result, refresh_run in zip(proof.runner_results, proof.refresh_runs, strict=True):
        if (
            result.metadata_updates != len(refresh_run.data_source_names)
            or refresh_run.metadata_updates != len(refresh_run.data_source_names)
            or not (
                receipt.start_event.occurred_at
                <= refresh_run.started_at
                <= refresh_run.completed_at
                <= receipt.terminal_event.occurred_at
            )
        ):
            raise ValueError("canonical scheduled recurrence refresh-row evidence mismatch")
        for source_name in refresh_run.data_source_names:
            completed_by_source[source_name] = refresh_run.completed_at

    source_evidence: list[AuthoritySourceEvidence] = []
    recurrence_evidence: list[AuthorityRecurrenceEvidence] = []
    for source in receipt.data_sources:
        completed_at = completed_by_source[source.name]
        if (
            source.jurisdiction != authority_identity
            or source.post_last_pull_status != "success"
            or not completed_at <= source.post_last_pull_at <= raw_database.captured_at
        ):
            raise ValueError("canonical scheduled recurrence source freshness mismatch")
        if source.baseline_last_pull_at is not None and source.post_last_pull_at <= source.baseline_last_pull_at:
            raise ValueError("canonical scheduled recurrence source freshness did not advance")
        source_identity = f"{authority_identity}:{source.name}"
        source_evidence.append(
            AuthoritySourceEvidence(
                source_identity=source_identity,
                freshness_status="fresh",
                observed_at=source.post_last_pull_at,
            )
        )
        recurrence_evidence.append(
            AuthorityRecurrenceEvidence(
                source_identity=source_identity,
                pull_status="success",
                execution_origin="scheduled",
                completed_at=completed_at,
            )
        )
    return source_evidence, recurrence_evidence, tuple(row.refresh_run_id for row in proof.refresh_runs)


def _validate_surface_parity_artifact(
    parity: SurfaceParityPromotionArtifact,
    *,
    serving: ServingDeployPromotionArtifact,
    filing_authority: FilingAuthorityReference,
    source_identities: Sequence[str],
    federal_identity_sha256: str,
    receipt_issued_at: datetime,
    filesystem_root: Path | None,
) -> None:
    raw_api = _load_hash_bound_promotion_model(
        path_text=parity.raw_api_evidence.path,
        expected_sha256=parity.raw_api_evidence.sha256,
        label="deployed surface parity raw API evidence",
        model=RawDeployedApiParityEvidence,
        filesystem_root=filesystem_root,
    )
    raw_browser = _load_hash_bound_promotion_model(
        path_text=parity.raw_browser_evidence.path,
        expected_sha256=parity.raw_browser_evidence.sha256,
        label="deployed surface parity raw browser evidence",
        model=RawDeployedBrowserParityEvidence,
        filesystem_root=filesystem_root,
    )
    assert isinstance(raw_api, RawDeployedApiParityEvidence)
    assert isinstance(raw_browser, RawDeployedBrowserParityEvidence)

    revision_identity = (serving.source_revision, serving.api_revision, serving.web_revision)
    artifact_identity = (parity.source_revision, parity.api_revision, parity.web_revision)
    api_identity = (raw_api.source_revision, raw_api.api_revision, raw_api.web_revision)
    browser_identity = (
        raw_browser.source_revision,
        raw_browser.api_revision,
        raw_browser.web_revision,
    )
    if len({*revision_identity, *artifact_identity, *api_identity, *browser_identity}) != 1:
        raise ValueError("canonical surface parity source revision mismatch")
    candidate_identity = (
        serving.candidate_receipt_file_sha256,
        serving.candidate_tree_git_sha,
        serving.qualified_image,
        filing_authority,
    )
    if (
        (
            parity.candidate_receipt_file_sha256,
            parity.candidate_tree_git_sha,
            parity.qualified_image,
            filing_authority,
        )
        != candidate_identity
        or (
            raw_api.candidate_receipt_file_sha256,
            raw_api.candidate_tree_git_sha,
            raw_api.qualified_image,
            raw_api.filing_authority,
        )
        != candidate_identity
        or (
            raw_browser.candidate_receipt_file_sha256,
            raw_browser.candidate_tree_git_sha,
            raw_browser.qualified_image,
            raw_browser.filing_authority,
        )
        != candidate_identity
    ):
        raise ValueError("canonical surface parity candidate, image, or authority mismatch")
    if {
        parity.promotion_bundle_sha256,
        raw_api.promotion_bundle_sha256,
        raw_browser.promotion_bundle_sha256,
    } != {parity.promotion_bundle_sha256}:
        raise ValueError("canonical surface parity promotion bundle mismatch")

    expected_sources = tuple(source_identities)
    if raw_api.source_identities != expected_sources:
        raise ValueError("canonical surface parity source identities mismatch")
    if raw_api.regional_navigation_routes != REGIONAL_BROWSER_ROUTES:
        raise ValueError("canonical surface parity regional navigation routes mismatch")
    if raw_api.washington_specimens != _WASHINGTON_SOURCE_NAMES:
        raise ValueError("canonical surface parity Washington specimens mismatch")
    surface_ids = tuple(surface.surface_id for surface in raw_api.surfaces)
    surface_paths = tuple(surface.path for surface in raw_api.surfaces)
    if surface_ids != _SURFACE_PARITY_IDS or len(surface_paths) != len(set(surface_paths)):
        raise ValueError("canonical surface parity requires exact 18/18 manifest surfaces")

    browser_routes = tuple(
        (route.path, route.heading, route.campaign_finance_status, route.authority_identity)
        for route in raw_browser.routes
    )
    if browser_routes != REGIONAL_BROWSER_ROUTE_EXPECTATIONS:
        raise ValueError("canonical surface parity browser regional routes mismatch")
    if raw_browser.washington_specimens != _WASHINGTON_SOURCE_NAMES:
        raise ValueError("canonical surface parity browser Washington specimens mismatch")
    if {
        raw_api.federal_identity_sha256,
        raw_browser.federal_identity_sha256,
        federal_identity_sha256,
    } != {federal_identity_sha256}:
        raise ValueError("canonical surface parity federal invariance mismatch")
    if parity.observed_at != max(raw_api.captured_at, raw_browser.captured_at):
        raise ValueError("canonical surface parity observation time is not derived from raw evidence")
    if not (
        raw_api.captured_at <= parity.observed_at <= receipt_issued_at
        and raw_browser.captured_at <= parity.observed_at
        and raw_api.captured_at >= receipt_issued_at - timedelta(minutes=30)
        and raw_browser.captured_at >= receipt_issued_at - timedelta(minutes=30)
    ):
        raise ValueError("canonical surface parity evidence is stale, replayed, or future-dated")


def build_surface_parity_promotion_artifact(
    *,
    raw_api_path: Path,
    raw_browser_path: Path,
    output_path: Path,
) -> SurfaceParityPromotionArtifact:
    """Produce the one existing parity artifact from its two raw owners."""

    raw_api_reference = _mode_0600_hash_bound_file(
        raw_api_path,
        label="deployed surface parity raw API evidence",
    )
    raw_browser_reference = _mode_0600_hash_bound_file(
        raw_browser_path,
        label="deployed surface parity raw browser evidence",
    )
    raw_api = RawDeployedApiParityEvidence.model_validate(
        _read_strict_promotion_json(
            Path(raw_api_reference.path),
            label="deployed surface parity raw API evidence",
        )
    )
    raw_browser = RawDeployedBrowserParityEvidence.model_validate(
        _read_strict_promotion_json(
            Path(raw_browser_reference.path),
            label="deployed surface parity raw browser evidence",
        )
    )
    artifact = SurfaceParityPromotionArtifact(
        schema_version=1,
        observed_at=max(raw_api.captured_at, raw_browser.captured_at),
        candidate_receipt_file_sha256=raw_api.candidate_receipt_file_sha256,
        candidate_tree_git_sha=raw_api.candidate_tree_git_sha,
        qualified_image=raw_api.qualified_image,
        promotion_bundle_sha256=raw_api.promotion_bundle_sha256,
        source_revision=raw_api.source_revision,
        api_revision=raw_api.api_revision,
        web_revision=raw_api.web_revision,
        raw_api_evidence=raw_api_reference,
        raw_browser_evidence=raw_browser_reference,
    )
    serving = ServingDeployPromotionArtifact(
        schema_version=1,
        filing_authority=raw_api.filing_authority,
        source_identities=list(raw_api.source_identities),
        candidate_receipt_file_sha256=raw_api.candidate_receipt_file_sha256,
        candidate_source_git_sha=raw_api.source_revision,
        candidate_tree_git_sha=raw_api.candidate_tree_git_sha,
        qualified_image=raw_api.qualified_image,
        source_revision=raw_api.source_revision,
        api_revision=raw_api.api_revision,
        web_revision=raw_api.web_revision,
    )
    _validate_surface_parity_artifact(
        artifact,
        serving=serving,
        filing_authority=raw_api.filing_authority,
        source_identities=raw_api.source_identities,
        federal_identity_sha256=raw_api.federal_identity_sha256,
        receipt_issued_at=artifact.observed_at,
        filesystem_root=None,
    )
    _write_new_mode_0600_json(
        output_path,
        artifact.model_dump(mode="json"),
        label="surface parity promotion artifact",
    )
    return artifact


def _derive_canonical_promotion_evidence(
    receipt: AuthorityPromotionReceipt,
    *,
    filesystem_root: Path | None,
) -> AuthorityPromotionEvidence:
    artifacts = {artifact.kind: artifact for artifact in receipt.canonical_evidence}
    canary = _parse_canonical_promotion_artifact(
        artifacts["canary_ledger"], RegionalCanaryPromotionArtifact, filesystem_root=filesystem_root
    )
    scheduled = _parse_canonical_promotion_artifact(
        artifacts["scheduled_recurrence"],
        ScheduledRecurrencePromotionArtifact,
        filesystem_root=filesystem_root,
    )
    filing = _parse_canonical_promotion_artifact(
        artifacts["filing_authority"], FilingAuthorityPromotionArtifact, filesystem_root=filesystem_root
    )
    provenance = _parse_canonical_promotion_artifact(
        artifacts["provenance"], ProvenancePromotionArtifact, filesystem_root=filesystem_root
    )
    keel = _parse_canonical_promotion_artifact(
        artifacts["keel"], KeelPromotionArtifact, filesystem_root=filesystem_root
    )
    serving = _parse_canonical_promotion_artifact(
        artifacts["serving_deploy"], ServingDeployPromotionArtifact, filesystem_root=filesystem_root
    )
    parity = _parse_canonical_promotion_artifact(
        artifacts["surface_parity"], SurfaceParityPromotionArtifact, filesystem_root=filesystem_root
    )
    assert isinstance(canary, RegionalCanaryPromotionArtifact)
    assert isinstance(scheduled, ScheduledRecurrencePromotionArtifact)
    assert isinstance(filing, FilingAuthorityPromotionArtifact)
    assert isinstance(provenance, ProvenancePromotionArtifact)
    assert isinstance(keel, KeelPromotionArtifact)
    assert isinstance(serving, ServingDeployPromotionArtifact)
    assert isinstance(parity, SurfaceParityPromotionArtifact)

    if (
        filing.geographic_subject != receipt.geographic_subject
        or filing.filing_authority != receipt.filing_authority
        or filing.authority_relation != receipt.authority_relation
        or filing.aggregation_disposition != receipt.aggregation_disposition
    ):
        raise ValueError("canonical filing authority evidence does not match promotion receipt identity")
    authority_identity = _promotion_authority_identity(filing.filing_authority)
    profile = load_authority_operations_profile(_WASHINGTON_REGIONAL_PROFILE_PATH)
    registry_jobs = job_builders.build_refresh_plan(
        scope="all",
        parameters=RunnerParameters(),
        job_key_prefixes=(),
    )
    (
        canary_source_identities,
        canary_completed_at,
        canary_federal_identity_sha256,
    ) = _validate_canary_promotion_artifact(
        canary,
        profile=profile,
        registry_jobs=registry_jobs,
        authority_identity=authority_identity,
        serving=serving,
        filesystem_root=filesystem_root,
    )
    if scheduled.canary_promotion_artifact_sha256 != artifacts["canary_ledger"].sha256:
        raise ValueError("canonical scheduled recurrence is not bound to the accepted canary artifact")
    source_evidence, recurrence_evidence, scheduled_refresh_run_ids = _validate_scheduled_promotion_artifact(
        scheduled,
        profile=profile,
        registry_jobs=registry_jobs,
        candidate_receipt_file_sha256=serving.candidate_receipt_file_sha256,
        candidate_source_git_sha=serving.candidate_source_git_sha,
        candidate_tree_git_sha=serving.candidate_tree_git_sha,
        qualified_image=serving.qualified_image,
        authority_identity=authority_identity,
        filesystem_root=filesystem_root,
    )
    source_identities = [row.source_identity for row in source_evidence]
    if canary_source_identities != tuple(source_identities[: len(canary_source_identities)]):
        raise ValueError("canonical canary ledger does not match the scheduled source order")
    if canary.refresh_run_id in scheduled_refresh_run_ids:
        raise ValueError("canonical canary attempt is replayed in scheduled recurrence evidence")
    if provenance.filing_authority != filing.filing_authority:
        raise ValueError("canonical provenance filing authority mismatch")
    if provenance.provenance_scope != authority_identity:
        raise ValueError("canonical provenance scope must match exact filing authority identity")
    if provenance.source_identities != source_identities:
        raise ValueError("canonical provenance source order mismatch")
    if keel.filing_authority != filing.filing_authority or keel.source_identities != source_identities:
        raise ValueError("canonical Keel evidence does not match exact authority sources")
    if serving.filing_authority != filing.filing_authority:
        raise ValueError("canonical serving deploy filing authority mismatch")
    if serving.source_identities != source_identities:
        raise ValueError("canonical serving deploy source order mismatch")
    if len({serving.source_revision, serving.api_revision, serving.web_revision}) != 1:
        raise ValueError("canonical serving deploy source/API/web revision mismatch")
    _validate_surface_parity_artifact(
        parity,
        serving=serving,
        filing_authority=filing.filing_authority,
        source_identities=source_identities,
        federal_identity_sha256=canary_federal_identity_sha256,
        receipt_issued_at=receipt.issued_at,
        filesystem_root=filesystem_root,
    )
    scheduled_receipt = _load_hash_bound_promotion_model(
        path_text=scheduled.observation_receipt_path,
        expected_sha256=scheduled.observation_receipt_sha256,
        label="scheduled observation receipt",
        model=RegionalScheduledObservationReceipt,
        filesystem_root=filesystem_root,
    )
    assert isinstance(scheduled_receipt, RegionalScheduledObservationReceipt)
    if scheduled_receipt.observed_at > receipt.issued_at or canary_completed_at > receipt.issued_at:
        raise ValueError("canonical promotion artifacts cannot postdate the composite receipt")

    return AuthorityPromotionEvidence(
        authority_identity=authority_identity,
        authority_relation=filing.authority_relation,
        aggregation_disposition=filing.aggregation_disposition,
        expected_source_identities=source_identities,
        source_evidence=source_evidence,
        recurrence_evidence=recurrence_evidence,
        provenance_source_identities=provenance.source_identities,
        keel_source_identities=keel.source_identities,
        deployed_source_identities=serving.source_identities,
        source_revision=serving.source_revision,
        api_revision=serving.api_revision,
        web_revision=serving.web_revision,
    )


def load_authority_promotion_receipt(
    path: str | Path,
    *,
    filesystem_root: Path | None = None,
) -> AuthorityPromotionReceipt:
    """Load one composite receipt and derive it from seven canonical owners."""

    receipt_path = Path(path)
    try:
        receipt = AuthorityPromotionReceipt.model_validate(
            _read_strict_promotion_json(receipt_path, label="authority promotion receipt JSON")
        )
    except ValidationError as error:
        raise ValueError(f"Invalid authority promotion receipt: {format_validation_errors(error)}") from error
    for artifact in receipt.canonical_evidence:
        artifact_path = _resolve_promotion_path(artifact.path, filesystem_root=filesystem_root)
        if not artifact_path.is_file() or artifact_path.is_symlink():
            raise ValueError(f"canonical {artifact.kind} evidence must be a regular non-symlink file")
        if hashlib.sha256(artifact_path.read_bytes()).hexdigest() != artifact.sha256:
            raise ValueError(f"canonical {artifact.kind} evidence digest mismatch")
    derived_evidence = _derive_canonical_promotion_evidence(receipt, filesystem_root=filesystem_root)
    if receipt.promotion_evidence != derived_evidence:
        raise ValueError("promotion receipt self-asserted evidence is not derivable from canonical artifacts")
    return receipt


def _promotion_bundle_virtual_paths(
    receipt: AuthorityPromotionReceipt,
    *,
    filesystem_root: Path,
) -> tuple[Path, ...]:
    canonical_paths = tuple(Path(artifact.path) for artifact in receipt.canonical_evidence)
    canary_artifact = next(artifact for artifact in receipt.canonical_evidence if artifact.kind == "canary_ledger")
    canary = _parse_canonical_promotion_artifact(
        canary_artifact,
        RegionalCanaryPromotionArtifact,
        filesystem_root=filesystem_root,
    )
    assert isinstance(canary, RegionalCanaryPromotionArtifact)
    scheduled_artifact = next(
        artifact for artifact in receipt.canonical_evidence if artifact.kind == "scheduled_recurrence"
    )
    scheduled = _parse_canonical_promotion_artifact(
        scheduled_artifact,
        ScheduledRecurrencePromotionArtifact,
        filesystem_root=filesystem_root,
    )
    assert isinstance(scheduled, ScheduledRecurrencePromotionArtifact)
    parity_artifact = next(artifact for artifact in receipt.canonical_evidence if artifact.kind == "surface_parity")
    parity = _parse_canonical_promotion_artifact(
        parity_artifact,
        SurfaceParityPromotionArtifact,
        filesystem_root=filesystem_root,
    )
    assert isinstance(parity, SurfaceParityPromotionArtifact)
    observation = _load_hash_bound_promotion_model(
        path_text=scheduled.observation_receipt_path,
        expected_sha256=scheduled.observation_receipt_sha256,
        label="scheduled observation receipt",
        model=RegionalScheduledObservationReceipt,
        filesystem_root=filesystem_root,
    )
    assert isinstance(observation, RegionalScheduledObservationReceipt)
    canary_paths = (
        Path(canary.candidate_receipt.path),
        Path(canary.authority_ledger_proof.path),
        Path(canary.terminal_machine_evidence.path),
        Path(canary.database_postcondition.path),
        Path(canary.federal_invariance_before.path),
        Path(canary.federal_invariance_after.path),
        Path(canary.public_invariance_before.path),
        Path(canary.public_invariance_after.path),
        Path(canary.rollback_app_inventory_before.path),
        Path(canary.rollback_machine_inventory_before.path),
        Path(canary.rollback_volume_inventory_before.path),
        Path(canary.rollback_app_inventory.path),
        Path(canary.rollback_machine_inventory.path),
        Path(canary.rollback_volume_inventory.path),
        *(Path(marker.path) for marker in canary.lifecycle_markers),
    )
    return (
        Path(AUTHORITY_PROMOTION_INSTALL_DIRECTORY) / AUTHORITY_PROMOTION_RECEIPT_NAME,
        *canonical_paths,
        *canary_paths,
        Path(scheduled.authority_ledger_proof_path),
        Path(scheduled.observation_receipt_path),
        *(Path(row.path) for row in observation.raw_evidence),
        Path(parity.raw_api_evidence.path),
        Path(parity.raw_browser_evidence.path),
    )


def _validate_promotion_archive_member(member: tarfile.TarInfo, *, seen: set[str]) -> PurePosixPath:
    member_path = PurePosixPath(member.name)
    if member_path.is_absolute():
        raise ValueError("authority promotion archive member paths must be relative")
    if not member_path.parts or ".." in member_path.parts or "\\" in member.name:
        raise ValueError("authority promotion archive members must be confined to the installed bundle")
    install_parts = AUTHORITY_PROMOTION_INSTALL_DIRECTORY.parts[1:]
    if member_path.parts[: len(install_parts)] != install_parts or len(member_path.parts) == len(install_parts):
        raise ValueError("authority promotion archive members must be confined to the installed bundle")
    if member.name in seen:
        raise ValueError(f"authority promotion archive contains duplicate member {member.name}")
    seen.add(member.name)
    if not member.isfile():
        raise ValueError("authority promotion archive may contain regular files only")
    if member.mode != 0o600:
        raise ValueError(f"authority promotion archive file {member.name} must have mode 0600")
    return member_path


def _write_exclusive_json(path: Path, payload: object, *, label: str) -> None:
    if not path.parent.is_dir() or path.parent.is_symlink():
        raise ValueError(f"{label} parent must be a regular directory")
    data = (json.dumps(payload, ensure_ascii=True, allow_nan=False, sort_keys=True) + "\n").encode()
    try:
        with path.open("xb") as handle:
            handle.write(data)
    except FileExistsError as error:
        raise ValueError(f"{label} already exists") from error
    path.chmod(0o600)


def build_authority_promotion_bundle(
    *,
    receipt_path: str | Path,
    artifact_directory: str | Path,
    build_receipt_path: str | Path,
    run_id: str,
    run_name: str,
    artifact_name: str,
    expected_source_revision: str,
    expected_api_revision: str,
    expected_web_revision: str,
    filesystem_root: Path | None = None,
) -> Path:
    """Build the one deterministic immutable transport consumed by deploy.yml."""

    if not run_id.isdecimal() or run_id.startswith("0"):
        raise ValueError("promotion bundle run ID must be a positive decimal integer")
    safe_name = r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}"
    if re.fullmatch(safe_name, run_name) is None or re.fullmatch(safe_name, artifact_name) is None:
        raise ValueError("promotion bundle run or artifact name contains unsupported characters")
    revisions = (expected_source_revision, expected_api_revision, expected_web_revision)
    if any(re.fullmatch(r"[0-9a-f]{40,64}", revision) is None for revision in revisions):
        raise ValueError("promotion bundle revisions must be lowercase Git identities")
    if len(set(revisions)) != 1:
        raise ValueError("promotion bundle source/API/web revisions are split")

    artifact_root = Path(artifact_directory)
    if not artifact_root.is_dir() or artifact_root.is_symlink() or list(artifact_root.iterdir()):
        raise ValueError("promotion bundle artifact directory must be an empty regular directory")
    archive_path = artifact_root / AUTHORITY_PROMOTION_ARCHIVE_NAME
    build_receipt = Path(build_receipt_path)
    if archive_path.exists() or archive_path.is_symlink() or build_receipt.exists() or build_receipt.is_symlink():
        raise ValueError("promotion bundle outputs must not already exist")

    source_receipt_path = Path(receipt_path)
    receipt = load_authority_promotion_receipt(source_receipt_path, filesystem_root=filesystem_root)
    serving = next(
        _parse_canonical_promotion_artifact(artifact, ServingDeployPromotionArtifact, filesystem_root=filesystem_root)
        for artifact in receipt.canonical_evidence
        if artifact.kind == "serving_deploy"
    )
    assert isinstance(serving, ServingDeployPromotionArtifact)
    if (serving.source_revision, serving.api_revision, serving.web_revision) != revisions:
        raise ValueError("promotion bundle expected revisions do not match validated serving evidence")

    canary_artifact = next(item for item in receipt.canonical_evidence if item.kind == "canary_ledger")
    scheduled_artifact = next(item for item in receipt.canonical_evidence if item.kind == "scheduled_recurrence")
    parity_artifact = next(item for item in receipt.canonical_evidence if item.kind == "surface_parity")
    canary = _parse_canonical_promotion_artifact(
        canary_artifact,
        RegionalCanaryPromotionArtifact,
        filesystem_root=filesystem_root,
    )
    scheduled = _parse_canonical_promotion_artifact(
        scheduled_artifact,
        ScheduledRecurrencePromotionArtifact,
        filesystem_root=filesystem_root,
    )
    parity = _parse_canonical_promotion_artifact(
        parity_artifact,
        SurfaceParityPromotionArtifact,
        filesystem_root=filesystem_root,
    )
    assert isinstance(canary, RegionalCanaryPromotionArtifact)
    assert isinstance(scheduled, ScheduledRecurrencePromotionArtifact)
    assert isinstance(parity, SurfaceParityPromotionArtifact)
    scheduled_receipt = _load_hash_bound_promotion_model(
        path_text=scheduled.observation_receipt_path,
        expected_sha256=scheduled.observation_receipt_sha256,
        label="scheduled observation receipt",
        model=RegionalScheduledObservationReceipt,
        filesystem_root=filesystem_root,
    )
    assert isinstance(scheduled_receipt, RegionalScheduledObservationReceipt)

    canonical_references = [Path(item.path) for item in receipt.canonical_evidence]
    canary_references = [
        Path(canary.candidate_receipt.path),
        Path(canary.authority_ledger_proof.path),
        Path(canary.terminal_machine_evidence.path),
        Path(canary.database_postcondition.path),
        Path(canary.federal_invariance_before.path),
        Path(canary.federal_invariance_after.path),
        Path(canary.public_invariance_before.path),
        Path(canary.public_invariance_after.path),
        Path(canary.rollback_app_inventory_before.path),
        Path(canary.rollback_machine_inventory_before.path),
        Path(canary.rollback_volume_inventory_before.path),
        Path(canary.rollback_app_inventory.path),
        Path(canary.rollback_machine_inventory.path),
        Path(canary.rollback_volume_inventory.path),
        *(Path(marker.path) for marker in canary.lifecycle_markers),
    ]
    scheduled_references = [
        Path(scheduled.authority_ledger_proof_path),
        Path(scheduled.observation_receipt_path),
        *(Path(row.path) for row in scheduled_receipt.raw_evidence),
    ]
    parity_references = [
        Path(parity.raw_api_evidence.path),
        Path(parity.raw_browser_evidence.path),
    ]
    references = [*canonical_references, *canary_references, *scheduled_references, *parity_references]
    resolved_sources = [_resolve_promotion_path(reference, filesystem_root=filesystem_root) for reference in references]
    source_paths = [source_receipt_path, *resolved_sources]
    if len(source_paths) != len(set(source_paths)):
        raise ValueError("promotion bundle source graph contains duplicate evidence paths")
    if any(not path.is_absolute() or not path.is_file() or path.is_symlink() for path in source_paths):
        raise ValueError("promotion bundle source graph requires absolute regular non-symlink files")
    source_stats = [path.stat() for path in source_paths]
    if any(metadata.st_nlink != 1 for metadata in source_stats) or len(
        {(metadata.st_dev, metadata.st_ino) for metadata in source_stats}
    ) != len(source_stats):
        raise ValueError("promotion bundle source graph refuses hardlinked evidence files")
    install = Path(AUTHORITY_PROMOTION_INSTALL_DIRECTORY)
    if filesystem_root is not None:
        source_install = Path(filesystem_root).joinpath(*install.parts[1:])
        expected_receipt_path = source_install / AUTHORITY_PROMOTION_RECEIPT_NAME
        if source_receipt_path != expected_receipt_path:
            raise ValueError("promotion bundle rooted receipt must use the exact install namespace")
        if not source_install.is_dir() or source_install.is_symlink():
            raise ValueError("promotion bundle rooted source install directory is invalid")
        source_entries = list(source_install.rglob("*"))
        if any(path.is_symlink() or (not path.is_file() and not path.is_dir()) for path in source_entries):
            raise ValueError("promotion bundle rooted source contains unsafe entries")
        source_files = {path for path in source_entries if path.is_file()}
        expected_directories: set[Path] = set()
        for source in source_paths:
            parent = source.parent
            while parent != source_install:
                expected_directories.add(parent)
                parent = parent.parent
        source_directories = {path for path in source_entries if path.is_dir()}
        if source_files != set(source_paths) or source_directories != expected_directories:
            missing = sorted(str(path) for path in set(source_paths) - source_files)
            extra = sorted(str(path) for path in source_files - set(source_paths))
            extra.extend(sorted(str(path) for path in source_directories - expected_directories))
            raise ValueError(
                "promotion bundle rooted source file set mismatch "
                f"(missing: {missing or ['none']}; extra: {extra or ['none']})"
            )
    if filesystem_root is None:
        basenames = [AUTHORITY_PROMOTION_RECEIPT_NAME, *(path.name for path in source_paths[1:])]
        if len(basenames) != len(set(basenames)) or any(
            not name or name in {".", ".."} or "/" in name or "\\" in name for name in basenames
        ):
            raise ValueError("promotion bundle source graph has unsafe or colliding member names")
        virtual_paths = [install / name for name in basenames]
    else:
        if any(not reference.is_relative_to(install) for reference in references):
            raise ValueError("promotion bundle rooted source references must stay inside the install namespace")
        virtual_paths = [install / AUTHORITY_PROMOTION_RECEIPT_NAME, *references]
    if len(virtual_paths) != len(set(virtual_paths)):
        raise ValueError("promotion bundle source graph has colliding member paths")
    virtual_by_source = dict(zip(source_paths, virtual_paths, strict=True))
    source_filesystem_root = filesystem_root

    def source_for_reference(path_text: str | Path) -> Path:
        return _resolve_promotion_path(path_text, filesystem_root=source_filesystem_root)

    def virtual_for_reference(path_text: str | Path) -> Path:
        return virtual_by_source[source_for_reference(path_text)]

    with tempfile.TemporaryDirectory(prefix="civibus-authority-promotion-build-") as temporary:
        transport_root = Path(temporary)
        staged_by_source = {
            source: transport_root.joinpath(*virtual.parts[1:]) for source, virtual in virtual_by_source.items()
        }
        staged_install = transport_root.joinpath(*install.parts[1:])
        staged_install.mkdir(parents=True, mode=0o700)

        rewritten_sources = {
            source_receipt_path,
            source_for_reference(canary_artifact.path),
            source_for_reference(scheduled_artifact.path),
            source_for_reference(parity_artifact.path),
            source_for_reference(scheduled.observation_receipt_path),
        }
        for source, destination in staged_by_source.items():
            if source in rewritten_sources:
                continue
            payload = _read_strict_promotion_json(source, label=f"promotion bundle source {source.name}")
            _reject_credential_bearing_promotion_json(payload, label=f"promotion bundle source {source.name}")
            shutil.copyfile(source, destination)
            destination.chmod(0o600)

        scheduled_receipt_payload = _read_strict_promotion_json(
            source_for_reference(scheduled.observation_receipt_path),
            label="scheduled observation receipt",
        )
        assert isinstance(scheduled_receipt_payload, dict)
        for row in scheduled_receipt_payload["raw_evidence"]:
            row["path"] = str(virtual_for_reference(row["path"]))
        scheduled_receipt_destination = staged_by_source[source_for_reference(scheduled.observation_receipt_path)]
        _write_exclusive_json(
            scheduled_receipt_destination,
            scheduled_receipt_payload,
            label="rewritten scheduled observation receipt",
        )

        canary_source = source_for_reference(canary_artifact.path)
        canary_payload = _read_strict_promotion_json(canary_source, label="canary promotion")
        assert isinstance(canary_payload, dict)
        for key in (
            "candidate_receipt",
            "authority_ledger_proof",
            "terminal_machine_evidence",
            "database_postcondition",
            "federal_invariance_before",
            "federal_invariance_after",
            "public_invariance_before",
            "public_invariance_after",
            "rollback_app_inventory_before",
            "rollback_machine_inventory_before",
            "rollback_volume_inventory_before",
            "rollback_app_inventory",
            "rollback_machine_inventory",
            "rollback_volume_inventory",
        ):
            canary_payload[key]["path"] = str(virtual_for_reference(canary_payload[key]["path"]))
        for marker in canary_payload["lifecycle_markers"]:
            marker["path"] = str(virtual_for_reference(marker["path"]))
        canary_destination = staged_by_source[canary_source]
        _write_exclusive_json(canary_destination, canary_payload, label="rewritten canary promotion")

        scheduled_source = source_for_reference(scheduled_artifact.path)
        scheduled_payload = _read_strict_promotion_json(scheduled_source, label="scheduled recurrence")
        assert isinstance(scheduled_payload, dict)
        scheduled_payload["authority_ledger_proof_path"] = str(
            virtual_for_reference(scheduled.authority_ledger_proof_path)
        )
        scheduled_payload["observation_receipt_path"] = str(virtual_for_reference(scheduled.observation_receipt_path))
        scheduled_payload["observation_receipt_sha256"] = hashlib.sha256(
            scheduled_receipt_destination.read_bytes()
        ).hexdigest()
        scheduled_payload["canary_promotion_artifact_sha256"] = hashlib.sha256(
            canary_destination.read_bytes()
        ).hexdigest()
        scheduled_destination = staged_by_source[scheduled_source]
        _write_exclusive_json(scheduled_destination, scheduled_payload, label="rewritten scheduled recurrence")

        parity_source = source_for_reference(parity_artifact.path)
        parity_payload = _read_strict_promotion_json(parity_source, label="surface parity")
        assert isinstance(parity_payload, dict)
        parity_payload["raw_api_evidence"]["path"] = str(virtual_for_reference(parity.raw_api_evidence.path))
        parity_payload["raw_browser_evidence"]["path"] = str(virtual_for_reference(parity.raw_browser_evidence.path))
        parity_destination = staged_by_source[parity_source]
        _write_exclusive_json(parity_destination, parity_payload, label="rewritten surface parity")

        receipt_payload = _read_strict_promotion_json(source_receipt_path, label="authority promotion receipt")
        assert isinstance(receipt_payload, dict)
        for artifact in receipt_payload["canonical_evidence"]:
            source = source_for_reference(artifact["path"])
            destination = staged_by_source[source]
            artifact["path"] = str(virtual_by_source[source])
            artifact["sha256"] = hashlib.sha256(destination.read_bytes()).hexdigest()
        receipt_destination = staged_by_source[source_receipt_path]
        _write_exclusive_json(receipt_destination, receipt_payload, label="rewritten authority promotion receipt")

        staged_receipt = load_authority_promotion_receipt(receipt_destination, filesystem_root=transport_root)
        virtual_paths = _promotion_bundle_virtual_paths(staged_receipt, filesystem_root=transport_root)
        if len(virtual_paths) != len(set(virtual_paths)):
            raise ValueError("promotion bundle rewritten graph contains duplicate members")
        member_rows = [
            {
                "path": str(PurePosixPath(*virtual_path.parts[1:])),
                "sha256": hashlib.sha256(transport_root.joinpath(*virtual_path.parts[1:]).read_bytes()).hexdigest(),
                "mode": "0600",
            }
            for virtual_path in virtual_paths
        ]
        embedded_build_payload = {
            "schema_version": 1,
            "run_id": run_id,
            "run_name": run_name,
            "artifact_name": artifact_name,
            "source_revision": expected_source_revision,
            "api_revision": expected_api_revision,
            "web_revision": expected_web_revision,
            "members": member_rows,
        }
        PromotionBundleBuildReceipt.model_validate(embedded_build_payload)
        embedded_build_path = staged_install / AUTHORITY_PROMOTION_BUILD_RECEIPT_NAME
        _write_exclusive_json(
            embedded_build_path,
            embedded_build_payload,
            label="embedded promotion bundle build receipt",
        )
        embedded_build_sha256 = hashlib.sha256(embedded_build_path.read_bytes()).hexdigest()
        embedded_build_virtual_path = install / AUTHORITY_PROMOTION_BUILD_RECEIPT_NAME
        temporary_archive = transport_root / AUTHORITY_PROMOTION_ARCHIVE_NAME
        with tarfile.open(temporary_archive, mode="x:", format=tarfile.USTAR_FORMAT) as archive:
            for virtual_path in (embedded_build_virtual_path, *virtual_paths):
                source = transport_root.joinpath(*virtual_path.parts[1:])
                data = source.read_bytes()
                member_name = str(PurePosixPath(*virtual_path.parts[1:]))
                info = tarfile.TarInfo(member_name)
                info.size = len(data)
                info.mode = 0o600
                info.mtime = 0
                info.uid = 0
                info.gid = 0
                info.uname = ""
                info.gname = ""
                archive.addfile(info, io.BytesIO(data))
        shutil.copyfile(temporary_archive, archive_path)
        archive_path.chmod(0o600)

    build_payload = {
        "schema_version": 1,
        "run_id": run_id,
        "run_name": run_name,
        "artifact_name": artifact_name,
        "archive_name": AUTHORITY_PROMOTION_ARCHIVE_NAME,
        "archive_sha256": hashlib.sha256(archive_path.read_bytes()).hexdigest(),
        "source_revision": expected_source_revision,
        "api_revision": expected_api_revision,
        "web_revision": expected_web_revision,
        "embedded_build_receipt_path": str(PurePosixPath(*embedded_build_virtual_path.parts[1:])),
        "embedded_build_receipt_sha256": embedded_build_sha256,
        "members": member_rows,
    }
    _write_exclusive_json(build_receipt, build_payload, label="promotion bundle build receipt")
    return archive_path


def stage_authority_promotion_bundle(
    *,
    artifact_directory: str | Path,
    destination_directory: str | Path,
    expected_source_revision: str,
    expected_run_id: str,
    expected_run_name: str,
    expected_artifact_name: str,
) -> Path:
    """Validate one immutable transport archive and stage its exact runtime files."""

    artifact_root = Path(artifact_directory)
    if not artifact_root.is_dir() or artifact_root.is_symlink():
        raise ValueError("authority promotion artifact directory must be a regular non-symlink directory")
    entries = list(artifact_root.iterdir())
    archive_path = artifact_root / AUTHORITY_PROMOTION_ARCHIVE_NAME
    if entries != [archive_path] or not archive_path.is_file() or archive_path.is_symlink():
        raise ValueError(
            f"authority promotion artifact must contain exactly one regular {AUTHORITY_PROMOTION_ARCHIVE_NAME}"
        )

    destination = Path(destination_directory)
    if not destination.is_dir() or destination.is_symlink():
        raise ValueError("authority promotion build-context directory must be a regular non-symlink directory")
    destination_entries = list(destination.iterdir())
    if any(path.name != ".gitkeep" or not path.is_file() or path.is_symlink() for path in destination_entries):
        raise ValueError("authority promotion build-context directory must be empty except for .gitkeep")

    with tempfile.TemporaryDirectory(prefix="civibus-authority-promotion-") as temporary:
        filesystem_root = Path(temporary)
        extracted_members: set[str] = set()
        extracted_member_order: list[str] = []
        try:
            archive = tarfile.open(archive_path, mode="r:")
        except (OSError, tarfile.TarError) as error:
            raise ValueError("authority promotion artifact is not a readable uncompressed tar archive") from error
        with archive:
            members = archive.getmembers()
            if not members:
                raise ValueError("authority promotion archive contains no evidence files")
            for member in members:
                member_path = _validate_promotion_archive_member(member, seen=extracted_members)
                extracted_member_order.append(member.name)
                file_object = archive.extractfile(member)
                if file_object is None:
                    raise ValueError("authority promotion archive may contain regular files only")
                output_path = filesystem_root.joinpath(*member_path.parts)
                output_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                with output_path.open("xb") as output:
                    shutil.copyfileobj(file_object, output)
                output_path.chmod(0o600)
                payload = _read_strict_promotion_json(
                    output_path,
                    label=f"authority promotion archive file {member.name}",
                )
                _reject_credential_bearing_promotion_json(
                    payload,
                    label=f"authority promotion archive file {member.name}",
                )

        receipt_path = filesystem_root.joinpath(
            *AUTHORITY_PROMOTION_INSTALL_DIRECTORY.parts[1:],
            AUTHORITY_PROMOTION_RECEIPT_NAME,
        )
        receipt = load_authority_promotion_receipt(receipt_path, filesystem_root=filesystem_root)
        if (
            receipt.jurisdiction_code != "WA"
            or receipt.geographic_subject.kind != "state"
            or receipt.geographic_subject.code != "WA"
            or receipt.filing_authority.kind != "state"
            or receipt.filing_authority.code != "WA"
        ):
            raise ValueError("authority promotion bundle must bind exact state/WA geography and filing authority")
        if receipt.promotion_evidence.source_revision != expected_source_revision:
            raise ValueError("authority promotion bundle serving source revision does not match deploy provenance")

        virtual_paths = _promotion_bundle_virtual_paths(receipt, filesystem_root=filesystem_root)
        if len(virtual_paths) != len(set(virtual_paths)):
            raise ValueError("authority promotion bundle contains duplicate transitive evidence paths")
        install_directory = Path(AUTHORITY_PROMOTION_INSTALL_DIRECTORY)
        if any(not path.is_absolute() or not path.is_relative_to(install_directory) for path in virtual_paths):
            raise ValueError("authority promotion evidence paths must stay inside the deterministic installed bundle")
        embedded_build_member = str(
            PurePosixPath(*AUTHORITY_PROMOTION_INSTALL_DIRECTORY.parts[1:]) / AUTHORITY_PROMOTION_BUILD_RECEIPT_NAME
        )
        embedded_build_path = filesystem_root / embedded_build_member
        try:
            embedded_build = PromotionBundleBuildReceipt.model_validate(
                _read_strict_promotion_json(
                    embedded_build_path,
                    label="embedded promotion bundle build receipt",
                )
            )
        except ValidationError as error:
            raise ValueError(
                f"Invalid embedded promotion bundle build receipt: {format_validation_errors(error)}"
            ) from error
        if (
            embedded_build.run_id != expected_run_id
            or embedded_build.run_name != expected_run_name
            or embedded_build.artifact_name != expected_artifact_name
        ):
            raise ValueError("authority promotion bundle run or artifact identity mismatch")
        if (
            embedded_build.source_revision != expected_source_revision
            or embedded_build.api_revision != expected_source_revision
            or embedded_build.web_revision != expected_source_revision
        ):
            raise ValueError("authority promotion bundle build receipt revision mismatch")
        expected_evidence_order = tuple(str(PurePosixPath(*path.parts[1:])) for path in virtual_paths)
        expected_member_rows = tuple(
            PromotionBundleMember(
                path=member_name,
                sha256=hashlib.sha256((filesystem_root / member_name).read_bytes()).hexdigest(),
                mode="0600",
            )
            for member_name in expected_evidence_order
        )
        if embedded_build.members != expected_member_rows:
            raise ValueError("authority promotion bundle build receipt member identity mismatch")
        expected_member_order = (embedded_build_member, *expected_evidence_order)
        expected_members = set(expected_member_order)
        if tuple(extracted_member_order) != expected_member_order:
            missing = sorted(expected_members - extracted_members)
            unreferenced = sorted(extracted_members - expected_members)
            raise ValueError(
                "authority promotion archive transitive file order or set mismatch "
                f"(missing: {missing or ['none']}; unreferenced: {unreferenced or ['none']})"
            )

        staged_source = filesystem_root.joinpath(*AUTHORITY_PROMOTION_INSTALL_DIRECTORY.parts[1:])
        embedded_build_path.unlink()
        for existing in destination_entries:
            existing.unlink()
        shutil.copytree(staged_source, destination, dirs_exist_ok=True, copy_function=shutil.copy2)
        return destination / AUTHORITY_PROMOTION_RECEIPT_NAME


def assess_authority_promotion_receipt(
    receipt: AuthorityPromotionReceipt,
    *,
    jurisdiction_code: str,
    authority_identity: str,
    expected_source_identities: list[str],
    source_evidence: list[AuthoritySourceEvidence],
    recurrence_evidence: list[AuthorityRecurrenceEvidence],
) -> AuthorityPromotionDecision:
    """Bind current database clocks to one exact canonical promotion receipt."""

    refusals: list[str] = []
    if receipt.jurisdiction_code != jurisdiction_code:
        refusals.append("The canonical receipt belongs to a different geographic subject.")
    if receipt.promotion_evidence.authority_identity != authority_identity:
        refusals.append("The canonical receipt belongs to a different filing authority.")
    if receipt.promotion_evidence.expected_source_identities != expected_source_identities:
        refusals.append("Runtime source identities do not exactly match the canonical receipt.")
    if receipt.promotion_evidence.source_evidence != source_evidence:
        refusals.append("Runtime freshness evidence does not exactly match the canonical receipt.")
    if receipt.promotion_evidence.recurrence_evidence != recurrence_evidence:
        refusals.append("Runtime recurrence evidence does not exactly match the canonical receipt.")
    receipt_decision = assess_authority_promotion(receipt.promotion_evidence)
    if refusals:
        return AuthorityPromotionDecision(
            authority_identity=authority_identity,
            eligible=False,
            revision_parity=receipt_decision.revision_parity,
            refusal_reasons=refusals,
        )
    return receipt_decision


class ImplementedRegionLifecycleRow(LifecycleBaseModel):
    jurisdiction_code: str
    name: str
    acquisition_pattern: AcquisitionPatternLiteral
    discovery_maturity: DiscoveryMaturityLiteral
    source_contract_maturity: SourceContractMaturityLiteral
    legal_filing_semantics_maturity: LegalFilingSemanticsMaturityLiteral
    implementation_maturity: ImplementationMaturityLiteral
    operational_maturity: OperationalMaturityLiteral
    public_claim_status: TierLiteral
    completeness_intelligence_maturity: CompletenessIntelligenceMaturityLiteral
    civics_candidacy_status: CivicsCandidacyStatusLiteral
    main_blocker: str

    @model_validator(mode="after")
    def _validate_main_blocker(self) -> "ImplementedRegionLifecycleRow":
        if not self.main_blocker.strip():
            raise ValueError(f"main_blocker must be non-empty for row '{self.jurisdiction_code}'")
        return self


class ImplementedRegionLifecycleRegistry(LifecycleBaseModel):
    updated_at: date
    rows: list[ImplementedRegionLifecycleRow]

    @model_validator(mode="after")
    def _validate_unique_jurisdiction_codes(self) -> "ImplementedRegionLifecycleRegistry":
        duplicate_codes = _collect_duplicate_jurisdiction_codes(self.rows)
        if duplicate_codes:
            details = "; ".join(
                f"{code} at row indexes {', '.join(str(index) for index in indexes)}"
                for code, indexes in sorted(duplicate_codes.items())
            )
            raise ValueError(f"Duplicate lifecycle jurisdiction code(s): {details}")
        return self


def _collect_duplicate_jurisdiction_codes(rows: list[ImplementedRegionLifecycleRow]) -> dict[str, list[int]]:
    code_to_indexes: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        code_to_indexes[row.jurisdiction_code].append(index)
    return {code: indexes for code, indexes in code_to_indexes.items() if len(indexes) > 1}


def load_lifecycle_json(path: str | Path) -> object:
    lifecycle_path = Path(path)
    try:
        return json.loads(lifecycle_path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ValueError(f"Failed to read lifecycle file at {lifecycle_path}: {error}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"Failed to parse lifecycle JSON at {lifecycle_path}: {error}") from error


def load_lifecycle(path: str | Path) -> ImplementedRegionLifecycleRegistry:
    lifecycle_path = Path(path)
    raw_payload = load_lifecycle_json(lifecycle_path)
    try:
        return ImplementedRegionLifecycleRegistry.model_validate(raw_payload)
    except ValidationError as error:
        raise ValueError(f"Invalid lifecycle JSON at {lifecycle_path}: {format_validation_errors(error)}") from error


def write_lifecycle(path: str | Path, lifecycle: ImplementedRegionLifecycleRegistry) -> Path:
    lifecycle_path = Path(path)
    lifecycle_path.parent.mkdir(parents=True, exist_ok=True)
    lifecycle_path.write_text(f"{lifecycle.model_dump_json(indent=2)}\n", encoding="utf-8")
    return lifecycle_path


def _escape_markdown_cell(value: object) -> str:
    """Keep derived markdown tables stable even when human-edited text contains table syntax."""
    return str(value).replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")


def render_lifecycle_summary_markdown(lifecycle: ImplementedRegionLifecycleRegistry) -> str:
    lines = [
        "# Implemented Region Lifecycle Summary (Derived)",
        "",
        f"Date: {lifecycle.updated_at.isoformat()}",
        "",
        _LIFECYCLE_AUTHORITY_NOTE,
        (
            "This summary is a derived view of lifecycle statuses for the FEC plus "
            "implemented campaign-finance state and independent-city packages."
        ),
        "",
        "## Implemented Region Layer Status",
        "",
        (
            "| Jurisdiction | Acquisition Pattern | Discovery | Source Contract | "
            "Legal / Filing Semantics | Implementation | Operations | Public Claim | "
            "Completeness Intelligence | Civics Candidacy | Main Blocker |"
        ),
        ("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"),
    ]
    for row in lifecycle.rows:
        lines.append(
            f"| {_escape_markdown_cell(row.jurisdiction_code)} | "
            f"{_escape_markdown_cell(row.acquisition_pattern)} | "
            f"{_escape_markdown_cell(row.discovery_maturity)} | "
            f"{_escape_markdown_cell(row.source_contract_maturity)} | "
            f"{_escape_markdown_cell(row.legal_filing_semantics_maturity)} | "
            f"{_escape_markdown_cell(row.implementation_maturity)} | "
            f"{_escape_markdown_cell(row.operational_maturity)} | "
            f"{_escape_markdown_cell(row.public_claim_status)} | "
            f"{_escape_markdown_cell(row.completeness_intelligence_maturity)} | "
            f"{_escape_markdown_cell(row.civics_candidacy_status)} | "
            f"{_escape_markdown_cell(row.main_blocker)} |"
        )
    return "\n".join(lines) + "\n"


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Render implemented-region lifecycle summary markdown from lifecycle JSON",
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=DEFAULT_IMPLEMENTED_REGION_LIFECYCLE_PATH,
        help="Input path for implemented-region lifecycle JSON",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_IMPLEMENTED_REGION_LIFECYCLE_SUMMARY_PATH,
        help="Output path for implemented-region lifecycle summary markdown",
    )
    parser.add_argument(
        "--promotion-artifact-directory",
        type=Path,
        help="Downloaded directory containing the immutable promotion bundle tar",
    )
    parser.add_argument(
        "--promotion-destination-directory",
        type=Path,
        help="Existing API build-context directory that receives the validated bundle",
    )
    parser.add_argument(
        "--expected-source-revision",
        help="Canonical Debbie dev SHA that every serving revision must match",
    )
    parser.add_argument("--expected-promotion-run-id")
    parser.add_argument("--expected-promotion-run-name")
    parser.add_argument("--expected-promotion-artifact-name")
    parser.add_argument("--promotion-receipt-json", type=Path)
    parser.add_argument("--promotion-artifact-output-directory", type=Path)
    parser.add_argument("--promotion-build-receipt-json", type=Path)
    parser.add_argument("--promotion-run-id")
    parser.add_argument("--promotion-run-name")
    parser.add_argument("--promotion-artifact-name")
    parser.add_argument("--promotion-source-revision")
    parser.add_argument("--promotion-api-revision")
    parser.add_argument("--promotion-web-revision")
    parser.add_argument("--promotion-filesystem-root", type=Path)
    parser.add_argument("--regional-canary-evidence-directory", type=Path)
    parser.add_argument("--regional-canary-artifact-output-json", type=Path)
    parser.add_argument("--regional-canary-artifact-json", type=Path)
    parser.add_argument("--regional-canary-profile-json", type=Path)
    parser.add_argument("--regional-canary-candidate-receipt-json", type=Path)
    parser.add_argument("--surface-parity-raw-api-json", type=Path)
    parser.add_argument("--surface-parity-raw-browser-json", type=Path)
    parser.add_argument("--surface-parity-output-json", type=Path)
    parser.add_argument("--regional-invariance-profile-json", type=Path)
    parser.add_argument("--regional-invariance-candidate-receipt-json", type=Path)
    parser.add_argument("--regional-invariance-stage", choices=("before", "after"))
    parser.add_argument("--regional-invariance-captured-at")
    parser.add_argument("--regional-invariance-machine-id")
    parser.add_argument("--regional-invariance-federal-machines-json", type=Path)
    parser.add_argument("--regional-invariance-federal-machine-config-json", type=Path)
    parser.add_argument("--regional-invariance-federal-volumes-json", type=Path)
    parser.add_argument("--regional-invariance-federal-version-json", type=Path)
    parser.add_argument("--regional-invariance-public-api-version-json", type=Path)
    parser.add_argument("--regional-invariance-public-web-version-json", type=Path)
    parser.add_argument("--regional-invariance-public-content-health-json", type=Path)
    parser.add_argument("--regional-invariance-database-observation-json", type=Path)
    parser.add_argument("--regional-invariance-federal-output-json", type=Path)
    parser.add_argument("--regional-invariance-public-output-json", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_argument_parser().parse_args(argv)
    try:
        invariance_arguments = (
            args.regional_invariance_profile_json,
            args.regional_invariance_candidate_receipt_json,
            args.regional_invariance_stage,
            args.regional_invariance_captured_at,
            args.regional_invariance_machine_id,
            args.regional_invariance_federal_machines_json,
            args.regional_invariance_federal_machine_config_json,
            args.regional_invariance_federal_volumes_json,
            args.regional_invariance_federal_version_json,
            args.regional_invariance_public_api_version_json,
            args.regional_invariance_public_web_version_json,
            args.regional_invariance_public_content_health_json,
            args.regional_invariance_database_observation_json,
            args.regional_invariance_federal_output_json,
            args.regional_invariance_public_output_json,
        )
        if any(value is not None for value in invariance_arguments):
            if not all(value is not None for value in invariance_arguments):
                raise ValueError("regional invariance production requires every raw owner, identity, and output")
            federal_output = args.regional_invariance_federal_output_json
            public_output = args.regional_invariance_public_output_json
            assert isinstance(federal_output, Path)
            assert isinstance(public_output, Path)
            if federal_output == public_output:
                raise ValueError("regional invariance outputs must be distinct")
            try:
                captured_at = datetime.fromisoformat(str(args.regional_invariance_captured_at).replace("Z", "+00:00"))
            except ValueError as error:
                raise ValueError("regional invariance captured-at timestamp is invalid") from error
            federal, public = build_regional_invariance_snapshots(
                profile_path=args.regional_invariance_profile_json,
                candidate_receipt_path=args.regional_invariance_candidate_receipt_json,
                stage=args.regional_invariance_stage,
                captured_at=captured_at,
                machine_id=args.regional_invariance_machine_id,
                federal_machines_path=args.regional_invariance_federal_machines_json,
                federal_machine_config_path=args.regional_invariance_federal_machine_config_json,
                federal_volumes_path=args.regional_invariance_federal_volumes_json,
                federal_version_path=args.regional_invariance_federal_version_json,
                public_api_version_path=args.regional_invariance_public_api_version_json,
                public_web_version_path=args.regional_invariance_public_web_version_json,
                public_content_health_path=args.regional_invariance_public_content_health_json,
                database_observation_path=args.regional_invariance_database_observation_json,
            )
            wrote_federal = False
            try:
                _write_new_mode_0600_json(
                    federal_output,
                    federal.model_dump(mode="json"),
                    label="regional federal invariance snapshot",
                )
                wrote_federal = True
                _write_new_mode_0600_json(
                    public_output,
                    public.model_dump(mode="json"),
                    label="regional public invariance snapshot",
                )
            except Exception:
                if wrote_federal and not public_output.exists():
                    federal_output.unlink(missing_ok=True)
                raise
            print(
                "Built canonical regional invariance snapshots: "
                f"stage={args.regional_invariance_stage} machine={args.regional_invariance_machine_id}"
            )
            return 0
        surface_parity_arguments = (
            args.surface_parity_raw_api_json,
            args.surface_parity_raw_browser_json,
            args.surface_parity_output_json,
        )
        if any(value is not None for value in surface_parity_arguments):
            if not all(value is not None for value in surface_parity_arguments):
                raise ValueError("surface parity production requires raw API, raw browser, and output paths")
            artifact = build_surface_parity_promotion_artifact(
                raw_api_path=args.surface_parity_raw_api_json,
                raw_browser_path=args.surface_parity_raw_browser_json,
                output_path=args.surface_parity_output_json,
            )
            print(
                "Built validated surface parity promotion artifact: "
                f"{args.surface_parity_output_json.resolve()} revision={artifact.source_revision}"
            )
            return 0
        regional_canary_build_arguments = (
            args.regional_canary_evidence_directory,
            args.regional_canary_artifact_output_json,
        )
        regional_canary_validate_arguments = (
            args.regional_canary_artifact_json,
            args.regional_canary_profile_json,
            args.regional_canary_candidate_receipt_json,
        )
        if any(value is not None for value in regional_canary_build_arguments):
            if not all(value is not None for value in regional_canary_build_arguments):
                raise ValueError("regional canary artifact production requires evidence directory and output")
            if any(value is not None for value in regional_canary_validate_arguments):
                raise ValueError("regional canary artifact production and validation modes are exclusive")
            artifact = build_regional_canary_promotion_artifact(
                evidence_directory=args.regional_canary_evidence_directory,
                output_path=args.regional_canary_artifact_output_json,
            )
            print(
                "Built validated regional canary promotion artifact: "
                f"{args.regional_canary_artifact_output_json.resolve()} machine={artifact.machine_id}"
            )
            return 0
        if any(value is not None for value in regional_canary_validate_arguments):
            if not all(value is not None for value in regional_canary_validate_arguments):
                raise ValueError("regional canary artifact validation requires artifact, profile, and candidate")
            try:
                artifact = RegionalCanaryPromotionArtifact.model_validate(
                    _read_strict_promotion_json(
                        args.regional_canary_artifact_json,
                        label="regional canary promotion artifact",
                    )
                )
            except ValidationError as error:
                raise ValueError(
                    f"Invalid regional canary promotion artifact: {format_validation_errors(error)}"
                ) from error
            validate_regional_canary_promotion_artifact(
                artifact,
                profile_path=args.regional_canary_profile_json,
                candidate_receipt_path=args.regional_canary_candidate_receipt_json,
            )
            print(
                "PASS: regional canary promotion artifact "
                f"machine={artifact.machine_id} attempt={artifact.refresh_run_id}"
            )
            return 0
        producer_arguments = (
            args.promotion_receipt_json,
            args.promotion_artifact_output_directory,
            args.promotion_build_receipt_json,
            args.promotion_run_id,
            args.promotion_run_name,
            args.promotion_artifact_name,
            args.promotion_source_revision,
            args.promotion_api_revision,
            args.promotion_web_revision,
        )
        if any(value is not None for value in producer_arguments):
            if not all(value is not None for value in producer_arguments):
                raise ValueError("promotion bundle production requires every run, revision, receipt, and output input")
            archive_path = build_authority_promotion_bundle(
                receipt_path=args.promotion_receipt_json,
                artifact_directory=args.promotion_artifact_output_directory,
                build_receipt_path=args.promotion_build_receipt_json,
                run_id=args.promotion_run_id,
                run_name=args.promotion_run_name,
                artifact_name=args.promotion_artifact_name,
                expected_source_revision=args.promotion_source_revision,
                expected_api_revision=args.promotion_api_revision,
                expected_web_revision=args.promotion_web_revision,
                filesystem_root=args.promotion_filesystem_root,
            )
            print(f"Built validated authority promotion bundle: {archive_path.resolve()}")
            return 0
        promotion_arguments = (
            args.promotion_artifact_directory,
            args.promotion_destination_directory,
            args.expected_source_revision,
            args.expected_promotion_run_id,
            args.expected_promotion_run_name,
            args.expected_promotion_artifact_name,
        )
        if any(value is not None for value in promotion_arguments):
            if not all(value is not None for value in promotion_arguments):
                raise ValueError("promotion staging requires artifact directory, destination, and source revision")
            receipt_path = stage_authority_promotion_bundle(
                artifact_directory=args.promotion_artifact_directory,
                destination_directory=args.promotion_destination_directory,
                expected_source_revision=args.expected_source_revision,
                expected_run_id=args.expected_promotion_run_id,
                expected_run_name=args.expected_promotion_run_name,
                expected_artifact_name=args.expected_promotion_artifact_name,
            )
            print(f"Staged validated authority promotion receipt: {receipt_path.resolve()}")
            return 0
        lifecycle = load_lifecycle(args.path)
        output_path = args.output.resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(render_lifecycle_summary_markdown(lifecycle), encoding="utf-8")
    except (OSError, ValueError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    print(f"Wrote implemented-region lifecycle summary markdown: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
