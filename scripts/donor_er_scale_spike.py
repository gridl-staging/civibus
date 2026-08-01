"""Contract-only donor entity-resolution diagnostic harness."""

from __future__ import annotations

# ruff: noqa: E402

import argparse
import hashlib
import json
import math
import os
import re
import resource
import secrets
import shlex
import subprocess
import sys
import sysconfig
import time
from collections.abc import Mapping, Sequence, Set
from pathlib import Path
from typing import Annotated, Any, Literal, get_args
from urllib.parse import urlparse
from uuid import UUID

_SCRIPT_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_SCRIPT_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_REPO_ROOT))
_INTERPRETER_SITE_PACKAGES = sysconfig.get_paths().get("purelib")
if _INTERPRETER_SITE_PACKAGES and _INTERPRETER_SITE_PACKAGES not in sys.path:
    sys.path.append(_INTERPRETER_SITE_PACKAGES)

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationError, model_validator

import core.entity_resolution.transaction_counterparty_resolver as transaction_counterparty_resolver
from core.db import get_connection
from core.entity_resolution.blocking import count_blocked_pairs
from core.entity_resolution.clustering import cluster_scored_pairs
from core.entity_resolution.confidence import classify_scored_pairs
from core.entity_resolution.extract import extract_donors_for_matching
from core.entity_resolution.persist import persist_auto_merge_clusters, persist_match_decisions
from core.entity_resolution.scoring import score_rows
from core.entity_resolution.splink_runtime import BoundedDuckDBConfig, open_bounded_duckdb_connection
from api.contribution_insights_contract import is_contribution_insights_mapped_row
from domains.campaign_finance.ingest.bulk_parser import read_bulk_file
from domains.campaign_finance.ingest.fec_bulk_files import fec_bulk_data_root
from domains.campaign_finance.ingest.field_mapper import map_contribution_fields
from domains.campaign_finance.normalize.addresses import normalize_address
from domains.campaign_finance.normalize.names import parse_name

_SCHEMA_VERSION = "donor_er_scale_spike.v1"
_MAX_COHORT_SIZE = 100
_REPO_ROOT = _SCRIPT_REPO_ROOT
_REPOSITORY_FEC_BULK_ROOT = fec_bulk_data_root(_REPO_ROOT / "data").resolve(strict=False)
_NETWORK_SCHEMES = frozenset({"http", "https", "s3", "gs"})
_DATABASE_SCHEMES = frozenset({"postgres", "postgresql"})
_BENCHMARK_CHILD_ENV = "CIVIBUS_DONOR_ER_SCALE_SPIKE_CHILD"
_SCRUBBED_ENV_TOKENS = ("DATABASE", "POSTGRES", "PG", "FLY")
_BENCHMARK_INVOCATION_ID_BYTES = 32
_DONOR_PROXY_SCHEMA_VERSION = "donor_er_proxy_measurement.v1"
_DONOR_PROXY_RECEIPT_FENCE_LANGUAGE = "donor_er_proxy_measurement_receipt"
_DONOR_PROXY_MODEL_ENTITY_TYPE = "person"
_DONOR_IDENTITY_ENTITY_TYPE = "donor_identity"
_WILSON_95_Z = 1.959963984540054

ScaleVerdict = Literal["SCALE_NOW", "SCALE_WITH_CHANGES", "PRECISION_INSUFFICIENT", "BLOCKED_ON_NAMED_DEFECT"]


class NormalizedBenchmarkRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    row_id: str
    canonical_name: str | None
    employer: str | None
    occupation: str | None
    city: str | None
    state: str | None
    zip5: str | None


class RunObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: Literal["materialize", "benchmark", "validate-receipt"]
    input_rows: int
    output_rows: int
    cohort_size: int
    timeout_seconds: int
    memory_bytes: int
    temp_bytes: int
    temp_root: str
    input_sha256: str | None = None
    unique_signature_count: int | None = None
    null_counts: dict[str, int] | None = None
    blocking_rules: list[dict[str, Any]] | None = None
    max_block_size: int | None = None
    elapsed_seconds: float | None = None
    peak_rss_bytes: int | None = None
    peak_temp_bytes: int | None = None
    exit_state: Literal["passed", "failed", "timeout", "memory_exceeded", "temp_exceeded"] | None = None
    benchmark_invocation_id: str | None = None

    @model_validator(mode="after")
    def require_benchmark_evidence(self) -> RunObservation:
        if self.command != "benchmark":
            return self
        missing_fields = [
            field_name
            for field_name in (
                "input_sha256",
                "unique_signature_count",
                "null_counts",
                "blocking_rules",
                "max_block_size",
                "elapsed_seconds",
                "peak_rss_bytes",
                "peak_temp_bytes",
                "exit_state",
                "benchmark_invocation_id",
            )
            if getattr(self, field_name) is None
        ]
        if missing_fields:
            raise ValueError(f"benchmark observation missing required evidence: {', '.join(missing_fields)}")
        return self


class DonorErScaleSpikeReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["donor_er_scale_spike.v1"]
    rows_sha256: str
    observations: tuple[RunObservation, ...]


# --- validate-receipt oracle ------------------------------------------------
# D2 embeds exactly one fenced object of the language below in its Markdown
# receipt; the closed runtime literal sets are owned here once and consumed by
# the validators and the CLI rather than being re-listed anywhere else.
_ARCHITECTURE_RECEIPT_SCHEMA_VERSION = "donor_er_architecture_receipt.v1"
_RECEIPT_FENCE_LANGUAGE = "donor_er_scale_spike_receipt"
_MEASUREMENT_NOT_READY = "MEASUREMENT_NOT_READY"
_ENVIRONMENT_ASSIGNMENT_PATTERN = re.compile(
    r"(?:^|(?<=[ \t\r\n;&|('\"]))(?:export[ \t]+)?[A-Z_][A-Z0-9_]*=",
    re.IGNORECASE,
)
_SECRET_FILE_CONTENT_MARKERS = (
    "-----BEGIN PRIVATE KEY-----",
    "-----BEGIN OPENSSH PRIVATE KEY-----",
    "-----BEGIN RSA PRIVATE KEY-----",
    "-----BEGIN EC PRIVATE KEY-----",
    "-----BEGIN DSA PRIVATE KEY-----",
    "-----BEGIN PGP PRIVATE KEY BLOCK-----",
)

B2Disposition = Literal["GO", "NO_GO"]
B2BlockerClass = Literal["NONE", "COVERAGE_IDENTITY", "CAPACITY", "EXTERNAL_EVIDENCE", "UNCLASSIFIED"]
UnclassifiedReason = Literal["CONFLICTING_SOURCE_EVIDENCE", "INSUFFICIENT_SOURCE_EVIDENCE"]
ArchitectureDisposition = Literal[
    "ADOPT_BOUNDED_SINGLE_NODE",
    "ADOPT_PARTITIONED_BLOCKING",
    "ADOPT_EXTERNAL_ER_SERVICE",
]
# A terminal disposition is either an architecture verdict or the not-ready
# re-gate signal; the architecture literals are owned by ArchitectureDisposition.
TerminalDisposition = ArchitectureDisposition | Literal["MEASUREMENT_NOT_READY"]

B2_DISPOSITIONS = frozenset(get_args(B2Disposition))
B2_BLOCKER_CLASSES = frozenset(get_args(B2BlockerClass))
UNCLASSIFIED_REASONS = frozenset(get_args(UnclassifiedReason))
ARCHITECTURE_DISPOSITIONS = frozenset(get_args(ArchitectureDisposition))
TERMINAL_DISPOSITIONS = ARCHITECTURE_DISPOSITIONS | {_MEASUREMENT_NOT_READY}

_FENCED_RECEIPT_PATTERN = re.compile(
    rf"^```{re.escape(_RECEIPT_FENCE_LANGUAGE)}\r?\n(.*?)\r?\n```[ \t]*$",
    re.DOTALL | re.MULTILINE,
)
_DONOR_PROXY_FENCED_RECEIPT_PATTERN = re.compile(
    rf"^```{re.escape(_DONOR_PROXY_RECEIPT_FENCE_LANGUAGE)}\r?\n(.*?)\r?\n```[ \t]*$",
    re.DOTALL | re.MULTILINE,
)
_DONOR_PROXY_VERDICT_HEADING_PATTERN = re.compile(r"^## VERDICT: ([A-Z_]+)[ \t]*$", re.MULTILINE)
_SHA256_HEX_PATTERN = re.compile(r"[0-9a-f]{64}")


def _require_nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("must be nonblank")
    return value


def _require_path_only(value: str) -> str:
    # Cleanup evidence is filesystem paths and absence facts only; it must never
    # carry environment values or file contents that could leak a secret.
    _require_nonblank(value)
    if "\n" in value or "\r" in value:
        raise ValueError("must not embed file contents")
    if "=" in value:
        raise ValueError("must not embed environment assignments")
    _reject_remote_database_or_fly_argument(value, "cleanup evidence")
    return value


def _reject_secret_bearing_receipt_text(value: object) -> None:
    if isinstance(value, str):
        if _receipt_text_contains_file_content(value):
            raise ValueError("validated receipt strings must not embed file contents")
        if _receipt_text_contains_environment_assignment(value):
            raise ValueError("validated receipt strings must not embed environment assignments")
        return
    if isinstance(value, Mapping):
        for key, nested_value in value.items():
            _reject_secret_bearing_receipt_text(key)
            _reject_secret_bearing_receipt_text(nested_value)
        return
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        for nested_value in value:
            _reject_secret_bearing_receipt_text(nested_value)


def _require_sha256_hex(value: str) -> str:
    if not _SHA256_HEX_PATTERN.fullmatch(value):
        raise ValueError("must be a 64-character lowercase hex SHA-256 digest")
    return value


NonblankStr = Annotated[str, AfterValidator(_require_nonblank)]
CleanupPath = Annotated[str, AfterValidator(_require_path_only)]
Sha256Hex = Annotated[str, AfterValidator(_require_sha256_hex)]


def _reject_repository_path_text(value: str) -> None:
    if str(_REPO_ROOT) in value:
        raise ValueError("validated receipt strings must not embed repository absolute paths")


def _reject_repository_path_tree(value: object) -> None:
    if isinstance(value, str):
        _reject_repository_path_text(value)
        return
    if isinstance(value, Mapping):
        for key, nested_value in value.items():
            _reject_repository_path_tree(key)
            _reject_repository_path_tree(nested_value)
        return
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        for nested_value in value:
            _reject_repository_path_tree(nested_value)


class TransactionWriteDefect(BaseModel):
    model_config = ConfigDict(extra="forbid")

    owner: NonblankStr
    detail: NonblankStr


class FiredBlockingRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    match_key: NonblankStr
    blocking_rule: NonblankStr


class DonorPairAttribution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_id_a: NonblankStr
    entity_id_b: NonblankStr
    match_key: NonblankStr
    fired_blocking_rules: list[FiredBlockingRule] = Field(min_length=1)
    comparison_levels: dict[NonblankStr, int] = Field(min_length=1)
    match_weight: float
    confidence: float = Field(ge=0, le=1)
    decision: NonblankStr

    @model_validator(mode="after")
    def validate_actual_run_attribution(self) -> DonorPairAttribution:
        if self.entity_id_a == self.entity_id_b:
            raise ValueError("pair members must be distinct")
        if not math.isfinite(self.match_weight):
            raise ValueError("match_weight must be finite")
        if not math.isfinite(self.confidence):
            raise ValueError("confidence must be finite")
        if self.match_key not in {rule.match_key for rule in self.fired_blocking_rules}:
            raise ValueError("match_key must identify one of the fired blocking rules")
        return self


class SampledFalsePairCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    audit_pair_keys: list[NonblankStr]
    attributed_pair_keys: list[NonblankStr]
    coverage_ratio: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def require_complete_coverage(self) -> SampledFalsePairCoverage:
        if sorted(self.audit_pair_keys) != sorted(self.attributed_pair_keys) or self.coverage_ratio != 1.0:
            raise ValueError("complete sampled-false-pair coverage is required")
        if len(set(self.audit_pair_keys)) != len(self.audit_pair_keys):
            raise ValueError("sampled pair keys must be unique")
        return self


class DonorErPairAttributionArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["donor_er_pair_attribution.v1"]
    seed: NonblankStr
    chosen_slice_size: int = Field(ge=0)
    pair_attributions: list[DonorPairAttribution]
    sampled_false_pair_coverage: SampledFalsePairCoverage

    @model_validator(mode="after")
    def validate_pair_frame(self) -> DonorErPairAttributionArtifact:
        dumped = self.model_dump(mode="python")
        _reject_secret_bearing_receipt_text(dumped)
        _reject_repository_path_tree(dumped)
        pair_keys = [_donor_pair_key(pair.entity_id_a, pair.entity_id_b) for pair in self.pair_attributions]
        unique_pair_keys = set(pair_keys)
        if len(unique_pair_keys) != len(pair_keys):
            raise ValueError("pair_attributions must identify unique entity pairs")
        missing_attribution = set(self.sampled_false_pair_coverage.attributed_pair_keys) - unique_pair_keys
        if missing_attribution:
            raise ValueError("sampled coverage references a pair absent from pair_attributions")
        return self


class PairAttributionArtifactReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: CleanupPath
    sha256: Sha256Hex
    validator_command: NonblankStr
    pair_count: int = Field(ge=0)
    sampled_pair_count: int = Field(ge=0)


class DonorProxyMeasurementReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["donor_er_proxy_measurement.v1"]
    verdict: ScaleVerdict
    donor_denominator: int = Field(ge=0)
    cluster_count: int = Field(ge=0)
    compression_ratio: float = Field(ge=0)
    cluster_size_distribution: dict[str, int]
    confidence_band_counts: dict[str, int]
    blocking_rule_selectivity: list[dict[str, Any]]
    chosen_slice_size: int = Field(ge=0)
    timing_seconds: float = Field(ge=0)
    peak_child_rss_bytes: int = Field(ge=0)
    db_counts: dict[str, int]
    seed: NonblankStr
    precision_successes: int = Field(ge=0)
    precision_denominator: int = Field(ge=0)
    precision_wilson_low: float = Field(ge=0, le=1)
    precision_wilson_high: float = Field(ge=0, le=1)
    undecidable_count: int = Field(ge=0)
    deterministic_cluster_sample: list[dict[str, Any]]
    named_transaction_write_defect: TransactionWriteDefect | None
    pair_attribution_artifact: PairAttributionArtifactReference | None = None

    @model_validator(mode="after")
    def validate_measurement_consistency(self) -> DonorProxyMeasurementReceipt:
        _reject_secret_bearing_receipt_text(self.model_dump(mode="python"))
        if self.precision_successes > self.precision_denominator:
            raise ValueError("precision_successes must not exceed precision_denominator")
        if self.precision_wilson_low > self.precision_wilson_high:
            raise ValueError("precision_wilson_low must not exceed precision_wilson_high")
        return self


class B2SourceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Verbatim, unstructured B2 output. D2 is the sole normalization owner and
    # never claims that B2 itself emitted the closed blocker taxonomy.
    verbatim_verdict: NonblankStr
    source_path: NonblankStr


class BlockerEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    normalized_owner_path: NonblankStr
    source_evidence: NonblankStr
    normalization_reason: UnclassifiedReason | None
    rerun_command: NonblankStr
    detail: NonblankStr


class ResourceLocalityEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    execution_locality: NonblankStr
    # Whether the measured work stayed off the network. A not-ready receipt that
    # never launched a child still has to state the scope it would have run in.
    offline: bool
    peak_rss_bytes: int = Field(ge=0)
    peak_temp_bytes: int = Field(ge=0)
    memory_budget_bytes: int = Field(ge=0)
    temp_budget_bytes: int = Field(ge=0)


class ArchiveIdentity(BaseModel):
    """Byte-level identity of one shared FEC bulk archive, as recomputed."""

    model_config = ConfigDict(extra="forbid")

    cycle: int = Field(ge=1990, le=2100)
    path: CleanupPath
    size_bytes: int = Field(ge=0)
    sha256: Sha256Hex
    member_name: CleanupPath
    crc_ok: bool
    part_files_present: int = Field(ge=0)

    @model_validator(mode="after")
    def _forbid_traversal_segments(self) -> ArchiveIdentity:
        for field_name, value in (("path", self.path), ("member_name", self.member_name)):
            if ".." in Path(value).parts:
                raise ValueError(f"{field_name} must not contain traversal segments")
        return self


class BlockerGap(BaseModel):
    """One unclosed gate, its owner, and the condition that would close it."""

    model_config = ConfigDict(extra="forbid")

    gap_id: NonblankStr
    owner: NonblankStr
    closing_condition: NonblankStr


class NotReadyDecisionMenu(BaseModel):
    """The terminal menu a MEASUREMENT_NOT_READY receipt must carry.

    Schema-owned so a not-ready verdict cannot degrade into narrative: an empty
    gap spec, a missing bias callout, or an absent rerun path all fail closed.
    """

    model_config = ConfigDict(extra="forbid")

    gap_spec: tuple[BlockerGap, ...] = Field(min_length=1)
    # A substituted proxy biases the verdict, so both the decision and the
    # direction of the bias are recorded rather than left to prose.
    proxy_substituted: bool
    proxy_offer_bias: NonblankStr
    conditional_disposition: tuple[NonblankStr, ...] = Field(min_length=1)
    rerun_menu: tuple[NonblankStr, ...] = Field(min_length=1)


class CleanupEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Roots are nullable because a lane that stops before materialization never
    # creates one; a required path string would force an invented value.
    data_root_path: CleanupPath | None = None
    data_root_created: bool
    data_root_removed: bool
    temp_root_path: CleanupPath | None = None
    temp_root_created: bool
    temp_root_removed: bool
    credential_root_path: CleanupPath | None = None
    credential_root_absent: bool
    credential_paths: tuple[CleanupPath, ...]
    credential_files_present: int = Field(ge=0)
    lane_pid_count: int = Field(ge=0)
    lane_proxy_count: int = Field(ge=0)

    @model_validator(mode="after")
    def _validate_root_lifecycle(self) -> CleanupEvidence:
        for label, path, created, removed in (
            ("data root", self.data_root_path, self.data_root_created, self.data_root_removed),
            ("temp root", self.temp_root_path, self.temp_root_created, self.temp_root_removed),
        ):
            if not created:
                if path is not None:
                    raise ValueError(f"{label} was not created, so it must not record a path")
                if removed:
                    raise ValueError(f"{label} was not created, so it cannot have been removed")
            elif path is None:
                raise ValueError(f"{label} was created, so it must record a path")
        if self.credential_root_absent:
            if self.credential_files_present:
                raise ValueError("credential root recorded absent while credential files remain present")
            if self.credential_paths:
                raise ValueError("credential root recorded absent while credential paths remain recorded")
        elif self.credential_root_path is None:
            raise ValueError("a credential root that is not absent must record its path")
        for label, value in (
            ("data root path", self.data_root_path),
            ("temp root path", self.temp_root_path),
            ("credential root path", self.credential_root_path),
        ):
            if value is not None and ".." in Path(value).parts:
                raise ValueError(f"{label} must not contain traversal segments")
        for credential_path in self.credential_paths:
            if ".." in Path(credential_path).parts:
                raise ValueError("credential paths must not contain traversal segments")
        return self

    @property
    def lane_resources_released(self) -> bool:
        """True only when every lane-owned resource is provably gone."""
        return not _unreleased_lane_resources(self)


def _unreleased_lane_resources(cleanup: CleanupEvidence) -> list[str]:
    """Name every lane-owned resource the cleanup evidence does not prove released.

    This is the single owner of the release rule: the ``lane_resources_released``
    property negates it and ``_require_released_lane_resources`` raises from it,
    so the boolean and the gate can never drift apart.
    """
    unreleased: list[str] = []
    if cleanup.data_root_created and not cleanup.data_root_removed:
        unreleased.append("data root still present")
    if cleanup.temp_root_created and not cleanup.temp_root_removed:
        unreleased.append("temp root still present")
    if not cleanup.credential_root_absent:
        unreleased.append("credential root still present")
    if cleanup.credential_files_present:
        unreleased.append("credential files still present")
    if cleanup.lane_pid_count:
        unreleased.append("lane processes still running")
    if cleanup.lane_proxy_count:
        unreleased.append("lane proxies still running")
    return unreleased


class DonorErArchitectureReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["donor_er_architecture_receipt.v1"]
    b2_disposition: B2Disposition
    b2_blocker_class: B2BlockerClass
    terminal_disposition: TerminalDisposition
    # Whether any materialization actually started. This gates every measured
    # claim: without it, a stopped lane could still present benchmark numbers.
    materialization_started: bool
    b2_source: B2SourceReference
    archive_identities: tuple[ArchiveIdentity, ...] = Field(min_length=1)
    resource_locality: ResourceLocalityEvidence
    cleanup_evidence: CleanupEvidence
    decision_menu: NotReadyDecisionMenu | None = None
    benchmark: DonorErScaleSpikeReceipt | None = None
    blocker_evidence: BlockerEvidence | None = None

    @property
    def requires_normalization_regate(self) -> bool:
        # UNCLASSIFIED is the only class that forces D2 back through normalization.
        return self.b2_blocker_class == "UNCLASSIFIED"

    @model_validator(mode="after")
    def _validate_disposition_invariants(self) -> DonorErArchitectureReceipt:
        _reject_secret_bearing_receipt_text(self.model_dump(mode="python"))
        # Disposition invariants run first so the existing GO/NO-GO diagnostics
        # stay the reported cause; the materialization rules refine them.
        if self.b2_disposition == "GO":
            self._require_go_invariants()
        else:
            self._require_no_go_invariants()
        self._require_materialization_invariants()
        return self

    def _require_materialization_invariants(self) -> None:
        # Benchmark observations can only exist downstream of a real
        # materialization, and a terminal not-ready verdict means none started.
        if not self.materialization_started and self.benchmark is not None:
            raise ValueError("benchmark observations require materialization_started true")
        if self.terminal_disposition == _MEASUREMENT_NOT_READY:
            if self.materialization_started:
                raise ValueError("MEASUREMENT_NOT_READY forbids started materialization")
            if self.decision_menu is None:
                raise ValueError("MEASUREMENT_NOT_READY requires a terminal decision menu")
        elif self.decision_menu is not None:
            raise ValueError("a decision menu is valid only for MEASUREMENT_NOT_READY")

    def _require_go_invariants(self) -> None:
        if self.b2_blocker_class != "NONE":
            raise ValueError("B2 GO requires b2_blocker_class NONE")
        if self.blocker_evidence is not None:
            raise ValueError("B2 GO forbids blocker evidence")
        if self.terminal_disposition not in ARCHITECTURE_DISPOSITIONS:
            raise ValueError("B2 GO requires an architecture terminal_disposition")
        if not _benchmark_receipt_passed(self.benchmark):
            raise ValueError("B2 GO requires a passed benchmark receipt")

    def _require_no_go_invariants(self) -> None:
        if self.b2_blocker_class == "NONE":
            raise ValueError("B2 NO-GO forbids b2_blocker_class NONE")
        if self.blocker_evidence is None:
            raise ValueError("B2 NO-GO requires blocker evidence")
        normalization_reason = self.blocker_evidence.normalization_reason
        if self.b2_blocker_class == "UNCLASSIFIED":
            if normalization_reason not in UNCLASSIFIED_REASONS:
                raise ValueError("UNCLASSIFIED requires a closed normalization_reason")
        elif normalization_reason is not None:
            raise ValueError("normalization_reason is valid only for UNCLASSIFIED")
        if self.terminal_disposition != _MEASUREMENT_NOT_READY:
            raise ValueError("B2 NO-GO requires terminal_disposition MEASUREMENT_NOT_READY")
        if self.benchmark is not None:
            raise ValueError("B2 NO-GO must not carry benchmark observations")


def _benchmark_receipt_passed(benchmark: DonorErScaleSpikeReceipt | None) -> bool:
    if benchmark is None or not benchmark.observations:
        return False
    return all(
        observation.command == "benchmark" and observation.exit_state == "passed"
        for observation in benchmark.observations
    )


def _receipt_text_is_secret_bearing(value: str) -> bool:
    return _receipt_text_contains_file_content(value) or _receipt_text_contains_environment_assignment(value)


def _receipt_text_contains_file_content(value: str) -> bool:
    return any(marker in value for marker in _SECRET_FILE_CONTENT_MARKERS)


def _receipt_text_contains_environment_assignment(value: str) -> bool:
    return bool(_ENVIRONMENT_ASSIGNMENT_PATTERN.search(value))


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run donor ER diagnostic harness contracts")
    subparsers = parser.add_subparsers(dest="command", required=True)

    materialize = subparsers.add_parser("materialize", description="Validate materialization evidence")
    materialize.add_argument("--data-root", required=True)
    materialize.add_argument("--committee-id-file", required=True)
    materialize.add_argument("--expected-committee-count", required=True, type=int)
    materialize.add_argument("--committee-id-file-sha256", required=True)
    materialize.add_argument("--archive-url", required=True)
    materialize.add_argument("--archive-member-name", required=True)
    materialize.add_argument("--archive-sha256", required=True)
    materialize.add_argument("--archive-size-bytes", required=True, type=int)
    _add_execution_evidence_arguments(materialize)
    materialize.set_defaults(func=_materialize)

    benchmark = subparsers.add_parser("benchmark", description="Validate benchmark execution evidence")
    benchmark.add_argument("--input-path", required=True)
    benchmark.add_argument("--benchmark-invocation-id", default=None, help=argparse.SUPPRESS)
    _add_execution_evidence_arguments(benchmark)
    benchmark.set_defaults(func=_benchmark)

    donor_proxy = subparsers.add_parser("donor-proxy", description="Run bounded DB-backed donor proxy ER")
    donor_proxy.add_argument("--committee-id", dest="committee_ids", action="append", required=True)
    donor_proxy.add_argument("--slice-size", required=True, type=int)
    donor_proxy.add_argument("--cluster-sample-size", required=True, type=int)
    donor_proxy.add_argument("--seed", required=True)
    _add_donor_proxy_execution_arguments(donor_proxy)
    donor_proxy.set_defaults(func=_donor_proxy)

    validate_pair_attribution = subparsers.add_parser(
        "validate-pair-attribution",
        description="Validate a donor-proxy receipt and its actual-run pair attribution artifact",
    )
    validate_pair_attribution.add_argument("--receipt", required=True)
    validate_pair_attribution.add_argument("--artifact", required=True)
    validate_pair_attribution.set_defaults(func=_validate_pair_attribution)

    validate_receipt = subparsers.add_parser("validate-receipt", description="Validate a harness receipt")
    # `--receipt` is the documented spelling; `--receipt-path` is kept for the
    # existing callers. Presence is enforced in the handler so that naming the
    # same file through both spellings stays legal while a conflict fails.
    validate_receipt.add_argument("--receipt", dest="receipt", default=None)
    validate_receipt.add_argument("--receipt-path", dest="receipt_path", default=None)
    validate_receipt.add_argument(
        "--require-cleanup",
        action="store_true",
        dest="require_cleanup",
        help="Fail unless the receipt proves every lane-owned resource was released",
    )
    validate_receipt.add_argument(
        "--emit-validated-json",
        action="store_true",
        dest="emit_validated_json",
        help="Write only the validated receipt JSON object to stdout",
    )
    validate_receipt.set_defaults(func=_validate_receipt)
    return parser


def _add_execution_evidence_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output-path", required=True)
    parser.add_argument("--cohort-size", required=True, type=int)
    parser.add_argument("--timeout-seconds", required=True, type=int)
    parser.add_argument("--memory-bytes", required=True, type=int)
    parser.add_argument("--temp-bytes", required=True, type=int)
    parser.add_argument("--temp-root", required=True)


def _add_donor_proxy_execution_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output-path", required=True)
    parser.add_argument("--pair-attribution-output-path", default=None)
    parser.add_argument("--timeout-seconds", required=True, type=int)
    parser.add_argument("--memory-bytes", required=True, type=int)
    parser.add_argument("--temp-bytes", required=True, type=int)
    parser.add_argument("--temp-root", required=True)


def diagnostic_signature_tuple(
    row: Mapping[str, str | None],
) -> tuple[str | None, str | None, str | None, str | None, str | None, str | None]:
    mapped = map_contribution_fields(row)
    return mapped_contribution_signature_tuple(mapped)


def mapped_contribution_signature_tuple(
    mapped: Mapping[str, object],
) -> tuple[str | None, str | None, str | None, str | None, str | None, str | None]:
    parsed_name = parse_name(_mapped_text(mapped, "contributor_name"))
    normalized_address = normalize_address(
        city=_mapped_text(mapped, "contributor_city"),
        state=_mapped_text(mapped, "contributor_state"),
        zip=_mapped_text(mapped, "contributor_zip"),
    )
    return (
        parsed_name.canonical or None,
        _mapped_text(mapped, "contributor_employer"),
        _mapped_text(mapped, "contributor_occupation"),
        normalized_address.city,
        normalized_address.state,
        normalized_address.zip5,
    )


def diagnostic_signature_bytes(row: Mapping[str, str | None]) -> bytes:
    # Canonical-row hashing is over owner-normalized diagnostic fields only.
    return json.dumps(
        diagnostic_signature_tuple(row),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def normalized_benchmark_row_id(row: Mapping[str, str | None]) -> str:
    return hashlib.sha256(diagnostic_signature_bytes(row)).hexdigest()


def normalized_benchmark_rows_sha256(rows: Sequence[Mapping[str, str | None]]) -> str:
    row_bytes = sorted(diagnostic_signature_bytes(row) for row in rows)
    return hashlib.sha256(b"".join(row_bytes)).hexdigest()


def normalized_benchmark_row(row: Mapping[str, str | None]) -> NormalizedBenchmarkRow:
    return normalized_benchmark_row_from_signature(diagnostic_signature_tuple(row))


def normalized_benchmark_row_from_signature(
    signature: tuple[str | None, str | None, str | None, str | None, str | None, str | None],
) -> NormalizedBenchmarkRow:
    canonical_name, employer, occupation, city, state, zip5 = signature
    row_id = hashlib.sha256(_signature_bytes(signature)).hexdigest()
    return NormalizedBenchmarkRow(
        row_id=row_id,
        canonical_name=canonical_name,
        employer=employer,
        occupation=occupation,
        city=city,
        state=state,
        zip5=zip5,
    )


def select_deterministic_db_prefix(rows: Sequence[dict[str, Any]], *, seed: str, size: int) -> list[dict[str, Any]]:
    if size < 0:
        raise ValueError("size must be non-negative")
    return sorted(rows, key=lambda row: (_seeded_sha256_key(seed, _stable_row_id(row)), str(row["id"])))[:size]


def select_deterministic_cluster_sample(
    clusters: Sequence[dict[str, Any]], *, seed: str, size: int
) -> list[dict[str, Any]]:
    if size < 0:
        raise ValueError("size must be non-negative")
    selected_clusters = sorted(
        clusters,
        key=lambda cluster: (_seeded_sha256_key(seed, _stable_cluster_id(cluster)), _stable_cluster_id(cluster)),
    )[:size]
    return [_json_safe_cluster_sample(cluster) for cluster in selected_clusters]


def wilson_95_interval(*, successes: int, denominator: int) -> tuple[float, float]:
    if denominator < 0 or successes < 0 or successes > denominator:
        raise ValueError("successes and denominator must describe a non-negative fraction")
    if denominator == 0:
        return (0.0, 0.0)
    proportion = successes / denominator
    denominator_adjustment = 1 + (_WILSON_95_Z * _WILSON_95_Z / denominator)
    center = (proportion + (_WILSON_95_Z * _WILSON_95_Z / (2 * denominator))) / denominator_adjustment
    margin = (
        _WILSON_95_Z
        * math.sqrt((proportion * (1 - proportion) + (_WILSON_95_Z * _WILSON_95_Z / (4 * denominator))) / denominator)
        / denominator_adjustment
    )
    return (round(max(0.0, center - margin), 6), round(min(1.0, center + margin), 6))


def project_required_slice_size(*, target_clusters: int, measured_clusters: int, measured_slice_size: int) -> int:
    if target_clusters <= 0:
        raise ValueError("target_clusters must be positive")
    if measured_clusters <= 0 or measured_slice_size <= 0:
        raise ValueError("measured cluster yield must be positive")
    return math.ceil(target_clusters * measured_slice_size / measured_clusters)


def classify_frame_growth(
    *, prior_clusters: int, prior_slice_size: int, grown_clusters: int, grown_slice_size: int
) -> str:
    if min(prior_clusters, prior_slice_size, grown_clusters, grown_slice_size) < 0:
        raise ValueError("cluster and slice counts must be non-negative")
    if grown_slice_size <= prior_slice_size:
        raise ValueError("grown_slice_size must exceed prior_slice_size")
    if grown_clusters <= prior_clusters:
        return "VACUOUS"
    return "GROWN"


def choose_scale_verdict(
    *,
    named_transaction_write_defect: Mapping[str, Any] | TransactionWriteDefect | None,
    denominator: int,
    undecidable_count: int,
    precision_lower_bound: float,
    minimum_precision: float,
) -> ScaleVerdict:
    if named_transaction_write_defect is not None:
        return "BLOCKED_ON_NAMED_DEFECT"
    if denominator <= 0 or precision_lower_bound < minimum_precision:
        return "PRECISION_INSUFFICIENT"
    if undecidable_count > 0:
        return "SCALE_WITH_CHANGES"
    return "SCALE_NOW"


def format_donor_proxy_measurement_receipt(receipt: DonorProxyMeasurementReceipt) -> str:
    return (
        f"## VERDICT: {receipt.verdict}\n\n```{_DONOR_PROXY_RECEIPT_FENCE_LANGUAGE}\n{receipt.model_dump_json()}\n```\n"
    )


def validate_donor_proxy_measurement_receipt_markdown(markdown_text: str) -> DonorProxyMeasurementReceipt:
    headings = _DONOR_PROXY_VERDICT_HEADING_PATTERN.findall(markdown_text)
    if len(headings) != 1:
        raise ValueError("expected exactly one verdict heading")
    blocks = _DONOR_PROXY_FENCED_RECEIPT_PATTERN.findall(markdown_text)
    if len(blocks) != 1:
        raise ValueError(f"expected exactly one fenced {_DONOR_PROXY_RECEIPT_FENCE_LANGUAGE} object")
    try:
        receipt = DonorProxyMeasurementReceipt.model_validate_json(blocks[0])
    except ValidationError as error:
        raise ValueError(_scrubbed_validation_message(error)) from None
    if receipt.verdict != headings[0]:
        raise ValueError("verdict heading must match receipt verdict")
    return receipt


def _mapped_text(mapped: Mapping[str, object], key: str) -> str | None:
    value = mapped.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _signature_bytes(
    signature: tuple[str | None, str | None, str | None, str | None, str | None, str | None],
) -> bytes:
    return json.dumps(
        signature,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _seeded_sha256_key(seed: str, stable_id: str) -> str:
    return hashlib.sha256(f"{seed}\x00{stable_id}".encode("utf-8")).hexdigest()


def _stable_row_id(row: Mapping[str, Any]) -> str:
    if "id" not in row:
        raise ValueError("deterministic DB prefix rows must carry id")
    return str(row["id"])


def _stable_cluster_id(cluster: Mapping[str, Any]) -> str:
    cluster_id = cluster.get("cluster_id")
    if cluster_id is not None:
        return str(cluster_id)
    member_ids = cluster.get("member_ids")
    if not isinstance(member_ids, (Sequence, Set)) or isinstance(member_ids, (bytes, str)):
        raise ValueError("cluster samples must carry cluster_id or member_ids")
    return "|".join(sorted(str(member_id) for member_id in member_ids))


def _json_safe_cluster_sample(cluster: Mapping[str, Any]) -> dict[str, Any]:
    sample = dict(cluster)
    member_ids = sample.get("member_ids")
    if isinstance(member_ids, (Sequence, Set)) and not isinstance(member_ids, (bytes, str)):
        sample["member_ids"] = sorted(str(member_id) for member_id in member_ids)
    return sample


def _donor_proxy(args: argparse.Namespace) -> int:
    started_at = time.monotonic()
    paths = _resolve_donor_proxy_paths(args)
    committee_ids = _parse_committee_ids(args.committee_ids)
    config = BoundedDuckDBConfig(
        database_path=paths.temp_root / "donor_er_donor_proxy.duckdb",
        temp_root=paths.temp_root,
        memory_limit_bytes=args.memory_bytes,
        max_temp_directory_size_bytes=args.temp_bytes,
    )

    with get_connection() as conn:
        rows = extract_donors_for_matching(conn, scope={"committee_ids": committee_ids})
        selected_rows = select_deterministic_db_prefix(rows, seed=args.seed, size=args.slice_size)
        selected_person_model_rows = [_donor_proxy_person_er_row(row) for row in selected_rows]

        def bounded_connection_factory() -> Any:
            return open_bounded_duckdb_connection(config)

        blocking_counts = count_blocked_pairs(
            selected_person_model_rows,
            _DONOR_PROXY_MODEL_ENTITY_TYPE,
            bounded_connection_factory=bounded_connection_factory,
        )
        scored_pairs = score_rows(
            selected_person_model_rows,
            _DONOR_PROXY_MODEL_ENTITY_TYPE,
            bounded_connection_factory=bounded_connection_factory,
            include_attribution=True,
        )
        classified_pairs = classify_scored_pairs(scored_pairs)
        clustered = cluster_scored_pairs(classified_pairs, selected_person_model_rows)
        attribution_classified_pairs = [dict(pair) for pair in classified_pairs]
        _strip_pair_attribution_fields(classified_pairs)
        decision_ids = persist_match_decisions(conn, classified_pairs, _DONOR_IDENTITY_ENTITY_TYPE)
        cluster_ids = persist_auto_merge_clusters(
            conn,
            clustered["auto_merge_clusters"],
            _DONOR_IDENTITY_ENTITY_TYPE,
        )

    receipt = _donor_proxy_receipt(
        args,
        _DonorProxyRunEvidence(
            rows=rows,
            selected_rows=selected_rows,
            blocking_counts=blocking_counts,
            classified_pairs=classified_pairs,
            clustered=clustered,
            persisted_decision_count=len(decision_ids or []),
            persisted_cluster_count=len(cluster_ids or []),
            elapsed_seconds=round(time.monotonic() - started_at, 6),
        ),
    )
    if paths.pair_attribution_output_path is not None:
        artifact = _build_pair_attribution_artifact(receipt, attribution_classified_pairs)
        paths.pair_attribution_output_path.write_text(artifact.model_dump_json() + "\n", encoding="utf-8")
        artifact_reference = PairAttributionArtifactReference(
            path=str(paths.pair_attribution_output_path),
            sha256=hashlib.sha256(paths.pair_attribution_output_path.read_bytes()).hexdigest(),
            validator_command=_pair_attribution_validator_command(
                paths.output_path,
                paths.pair_attribution_output_path,
            ),
            pair_count=len(artifact.pair_attributions),
            sampled_pair_count=len(artifact.sampled_false_pair_coverage.audit_pair_keys),
        )
        receipt = DonorProxyMeasurementReceipt.model_validate(
            {
                **receipt.model_dump(mode="python"),
                "pair_attribution_artifact": artifact_reference.model_dump(mode="python"),
            }
        )
    paths.output_path.write_text(format_donor_proxy_measurement_receipt(receipt), encoding="utf-8")
    print(
        "donor-proxy "
        f"verdict={receipt.verdict} "
        f"donor_denominator={receipt.donor_denominator} "
        f"cluster_count={receipt.cluster_count}"
    )
    return 0


def _strip_pair_attribution_fields(classified_pairs: Sequence[dict[str, Any]]) -> None:
    attribution_fields = {"match_key", "fired_blocking_rules", "comparison_levels", "match_weight"}
    for pair in classified_pairs:
        for field_name in attribution_fields:
            pair.pop(field_name, None)


def _build_pair_attribution_artifact(
    receipt: DonorProxyMeasurementReceipt,
    classified_pairs: Sequence[Mapping[str, Any]],
) -> DonorErPairAttributionArtifact:
    pair_attributions = [
        DonorPairAttribution(
            entity_id_a=str(pair["entity_id_a"]),
            entity_id_b=str(pair["entity_id_b"]),
            match_key=str(pair["match_key"]),
            fired_blocking_rules=pair["fired_blocking_rules"],
            comparison_levels=pair["comparison_levels"],
            match_weight=float(pair["match_weight"]),
            confidence=float(pair["confidence"]),
            decision=str(pair["decision"]),
        )
        for pair in classified_pairs
    ]
    audit_pair_keys = _sampled_audit_pair_keys(
        receipt.deterministic_cluster_sample,
        pair_attributions,
    )
    return DonorErPairAttributionArtifact(
        schema_version="donor_er_pair_attribution.v1",
        seed=receipt.seed,
        chosen_slice_size=receipt.chosen_slice_size,
        pair_attributions=pair_attributions,
        sampled_false_pair_coverage=SampledFalsePairCoverage(
            audit_pair_keys=audit_pair_keys,
            attributed_pair_keys=list(audit_pair_keys),
            coverage_ratio=1.0,
        ),
    )


def _sampled_audit_pair_keys(
    cluster_sample: Sequence[Mapping[str, Any]],
    pair_attributions: Sequence[DonorPairAttribution],
) -> list[str]:
    sampled_pair_keys: set[str] = set()
    for cluster in cluster_sample:
        member_ids = {str(member_id) for member_id in cluster.get("member_ids", [])}
        for pair in pair_attributions:
            if pair.entity_id_a in member_ids and pair.entity_id_b in member_ids:
                sampled_pair_keys.add(_donor_pair_key(pair.entity_id_a, pair.entity_id_b))
    return sorted(sampled_pair_keys)


def _donor_pair_key(entity_id_a: str, entity_id_b: str) -> str:
    return "|".join(sorted((str(entity_id_a), str(entity_id_b))))


def _pair_attribution_validator_command(receipt_path: Path, artifact_path: Path) -> str:
    return shlex.join(
        [
            "uv",
            "run",
            "--extra",
            "entity-resolution",
            "python",
            "scripts/donor_er_scale_spike.py",
            "validate-pair-attribution",
            "--receipt",
            str(receipt_path),
            "--artifact",
            str(artifact_path),
        ]
    )


def _parse_committee_ids(raw_committee_ids: Sequence[str]) -> list[UUID]:
    if not raw_committee_ids:
        raise ValueError("at least one committee-id is required")
    return [UUID(raw_committee_id) for raw_committee_id in raw_committee_ids]


def _donor_proxy_person_er_row(row: Mapping[str, Any]) -> dict[str, object]:
    parsed_name = parse_name(str(row.get("contributor_name_raw") or row.get("canonical_name") or ""))
    last_name = parsed_name.last
    return {
        "id": row["id"],
        "canonical_name": parsed_name.canonical or None,
        "first_name": parsed_name.first,
        "last_name": last_name,
        "last_name_prefix5": last_name[:5] if last_name else None,
        "last_name_prefix3": last_name[:3] if last_name else None,
        "date_of_birth": None,
        "normalized_address": None,
        "street_number": None,
        "zip5": row.get("zip5"),
        "state": row.get("contributor_state"),
        "employer": row.get("contributor_employer"),
        "occupation": row.get("contributor_occupation"),
        "identifier_key": None,
    }


def _donor_proxy_receipt(args: argparse.Namespace, evidence: _DonorProxyRunEvidence) -> DonorProxyMeasurementReceipt:
    precision_successes = sum(pair.get("decision") == "match" for pair in evidence.classified_pairs)
    precision_denominator = len(evidence.classified_pairs)
    wilson_low, wilson_high = wilson_95_interval(successes=precision_successes, denominator=precision_denominator)
    undecidable_count = sum(
        pair.get("decision") in {"probable_match", "possible_match"} for pair in evidence.classified_pairs
    )
    defect = _transaction_write_defect()
    verdict = choose_scale_verdict(
        named_transaction_write_defect=defect,
        denominator=precision_denominator,
        undecidable_count=undecidable_count,
        precision_lower_bound=wilson_low,
        minimum_precision=0.95,
    )
    all_clusters = _donor_proxy_clusters_for_sampling(evidence.clustered)
    return DonorProxyMeasurementReceipt(
        schema_version=_DONOR_PROXY_SCHEMA_VERSION,
        verdict=verdict,
        donor_denominator=len(evidence.rows),
        cluster_count=len(all_clusters),
        compression_ratio=_compression_ratio(len(evidence.selected_rows), len(all_clusters)),
        cluster_size_distribution=_cluster_size_distribution(all_clusters),
        confidence_band_counts=_confidence_band_counts(evidence.classified_pairs),
        blocking_rule_selectivity=evidence.blocking_counts,
        chosen_slice_size=len(evidence.selected_rows),
        timing_seconds=evidence.elapsed_seconds,
        peak_child_rss_bytes=_current_process_peak_rss_bytes(),
        db_counts={
            "extracted_donors": len(evidence.rows),
            "selected_donors": len(evidence.selected_rows),
            "classified_pairs": len(evidence.classified_pairs),
            "persisted_decisions": evidence.persisted_decision_count,
            "persisted_clusters": evidence.persisted_cluster_count,
        },
        seed=args.seed,
        precision_successes=precision_successes,
        precision_denominator=precision_denominator,
        precision_wilson_low=wilson_low,
        precision_wilson_high=wilson_high,
        undecidable_count=undecidable_count,
        deterministic_cluster_sample=select_donor_proxy_cluster_sample(
            evidence.clustered,
            seed=args.seed,
            size=args.cluster_sample_size,
        ),
        named_transaction_write_defect=defect,
    )


def _donor_proxy_clusters_for_sampling(clustered: Mapping[str, Any]) -> list[dict[str, Any]]:
    return list(clustered["auto_merge_clusters"]) + list(clustered["review_components"])


def select_donor_proxy_cluster_sample(clustered: Mapping[str, Any], *, seed: str, size: int) -> list[dict[str, Any]]:
    return select_deterministic_cluster_sample(_donor_proxy_clusters_for_sampling(clustered), seed=seed, size=size)


def _transaction_write_defect() -> TransactionWriteDefect | None:
    transaction_write_seam = "resolve_donor_identity_transactions"
    transaction_target = "cf.transaction.contributor_" + "person" + "_id"
    if callable(getattr(transaction_counterparty_resolver, transaction_write_seam, None)):
        return None
    return TransactionWriteDefect(
        owner="core/entity_resolution/transaction_counterparty_resolver.py",
        detail=f"no existing owner seam resolves donor identities onto local-only {transaction_target} writes",
    )


def _compression_ratio(selected_count: int, cluster_count: int) -> float:
    if selected_count == 0 or cluster_count == 0:
        return 0.0
    return round(selected_count / cluster_count, 6)


def _cluster_size_distribution(clusters: Sequence[dict[str, Any]]) -> dict[str, int]:
    distribution: dict[str, int] = {}
    for cluster in clusters:
        size_key = str(len(cluster.get("member_ids", [])))
        distribution[size_key] = distribution.get(size_key, 0) + 1
    return distribution


def _confidence_band_counts(classified_pairs: Sequence[dict[str, Any]]) -> dict[str, int]:
    counts = {"match": 0, "probable_match": 0, "possible_match": 0, "no_match": 0}
    for pair in classified_pairs:
        decision = str(pair.get("decision"))
        counts[decision] = counts.get(decision, 0) + 1
    return counts


def _materialize(args: argparse.Namespace) -> int:
    paths = _resolve_materialize_paths(args)
    committee_ids = _load_committee_ids(
        paths.committee_id_file,
        expected_count=args.expected_committee_count,
        expected_sha256=args.committee_id_file_sha256,
    )
    _validate_archive_evidence(
        paths.archive_path,
        data_root=paths.data_root,
        expected_size_bytes=args.archive_size_bytes,
        expected_sha256=args.archive_sha256,
    )

    config = BoundedDuckDBConfig(
        database_path=paths.temp_root / "donor_er_scale_spike.duckdb",
        temp_root=paths.temp_root,
        memory_limit_bytes=args.memory_bytes,
        max_temp_directory_size_bytes=args.temp_bytes,
    )
    connection = open_bounded_duckdb_connection(config)
    try:
        rows = _materialized_rows(
            connection,
            archive_path=paths.archive_path,
            archive_member_name=args.archive_member_name,
            committee_ids=committee_ids,
            cohort_size=args.cohort_size,
        )
        _write_jsonl(paths.output_path, rows)
    finally:
        connection.close()
    return 0


class _MaterializePaths(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    data_root: Path
    temp_root: Path
    committee_id_file: Path
    archive_path: Path
    output_path: Path


class _BoundedExecutionPaths(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    temp_root: Path
    output_path: Path


class _DonorProxyPaths(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    temp_root: Path
    output_path: Path
    pair_attribution_output_path: Path | None = None


class _DonorProxyRunEvidence(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    rows: list[dict[str, Any]]
    selected_rows: list[dict[str, Any]]
    blocking_counts: list[dict[str, Any]]
    classified_pairs: list[dict[str, Any]]
    clustered: dict[str, Any]
    persisted_decision_count: int
    persisted_cluster_count: int
    elapsed_seconds: float


def _resolve_materialize_paths(args: argparse.Namespace) -> _MaterializePaths:
    execution_paths = _resolve_bounded_execution_paths(args)
    _reject_repository_cache_candidate(args.data_root, "data-root")
    data_root = _resolve_existing_directory(args.data_root, "data-root")
    _reject_repository_cache_path(data_root, "data-root")
    committee_id_file = _resolve_existing_file(
        args.committee_id_file,
        "committee-id-file",
        base=execution_paths.temp_root,
    )
    archive_path = _resolve_existing_file(args.archive_url, "archive-url", base=data_root)
    _require_within(archive_path, data_root, "archive-url must resolve inside data-root")
    return _MaterializePaths(
        data_root=data_root,
        temp_root=execution_paths.temp_root,
        committee_id_file=committee_id_file,
        archive_path=archive_path,
        output_path=execution_paths.output_path,
    )


def _resolve_bounded_execution_paths(args: argparse.Namespace) -> _BoundedExecutionPaths:
    _validate_cohort_size(args.cohort_size)
    temp_root = _resolve_temp_root(args.temp_root)
    output_path = _resolve_contained_output_path(args.output_path, temp_root)
    return _BoundedExecutionPaths(temp_root=temp_root, output_path=output_path)


def _resolve_donor_proxy_paths(args: argparse.Namespace) -> _DonorProxyPaths:
    _validate_positive_int(args.slice_size, "slice-size")
    _validate_positive_int(args.cluster_sample_size, "cluster-sample-size")
    temp_root = _resolve_temp_root(args.temp_root)
    output_path = _resolve_contained_output_path(args.output_path, temp_root)
    raw_pair_attribution_path = getattr(args, "pair_attribution_output_path", None)
    pair_attribution_output_path = (
        _resolve_contained_output_path(raw_pair_attribution_path, temp_root)
        if raw_pair_attribution_path is not None
        else None
    )
    if pair_attribution_output_path == output_path:
        raise ValueError("pair-attribution-output-path must not alias output-path")
    return _DonorProxyPaths(
        temp_root=temp_root,
        output_path=output_path,
        pair_attribution_output_path=pair_attribution_output_path,
    )


def _validate_cohort_size(cohort_size: int) -> None:
    if cohort_size <= 0 or cohort_size > _MAX_COHORT_SIZE:
        raise ValueError("cohort-size must be between 1 and 100")


def _validate_positive_int(value: int, field_name: str) -> None:
    if value <= 0:
        raise ValueError(f"{field_name} must be positive")


def _resolve_temp_root(value: object) -> Path:
    _reject_repository_cache_candidate(value, "temp-root")
    temp_root = _resolve_existing_directory(value, "temp-root")
    _reject_repository_cache_path(temp_root, "temp-root")
    return temp_root


def _resolve_contained_output_path(value: object, temp_root: Path) -> Path:
    output_path = _resolve_output_path(value, temp_root)
    _require_within(output_path, temp_root, "output-path must resolve inside temp-root")
    _ensure_output_parent(output_path)
    return output_path


def _resolve_existing_directory(value: object, field_name: str) -> Path:
    path = _resolve_local_path(value, field_name)
    if not path.is_dir():
        raise ValueError(f"{field_name} must resolve to an existing local directory")
    return path


def _resolve_existing_file(value: object, field_name: str, *, base: Path) -> Path:
    path = _resolve_local_path(value, field_name, base=base)
    if not path.is_file():
        raise ValueError(f"{field_name} must resolve to an existing local file")
    _reject_repository_cache_path(path, field_name)
    return path


def _resolve_output_path(value: object, temp_root: Path) -> Path:
    return _resolve_local_path(value, "output-path", base=temp_root, must_exist=False)


def _ensure_output_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _resolve_local_path(
    value: object,
    field_name: str,
    *,
    base: Path | None = None,
    must_exist: bool = True,
) -> Path:
    raw_value = str(value)
    _reject_remote_database_or_fly_argument(raw_value, field_name)
    candidate = Path(raw_value)
    if not candidate.is_absolute():
        candidate = (base or Path.cwd()) / candidate
    try:
        return candidate.resolve(strict=must_exist)
    except OSError as error:
        raise ValueError(f"{field_name} must resolve to a local filesystem path") from error


def _reject_remote_database_or_fly_argument(raw_value: str, field_name: str) -> None:
    parsed = urlparse(raw_value)
    scheme = parsed.scheme.lower()
    lowered = raw_value.lower()
    if scheme in _NETWORK_SCHEMES:
        raise ValueError(f"{field_name} must not use a network URL scheme")
    if scheme in _DATABASE_SCHEMES or "dbname=" in lowered or "host=" in lowered:
        raise ValueError(f"{field_name} must not be a database URL or DSN")
    if scheme == "fly" or lowered.startswith("fly "):
        raise ValueError(f"{field_name} must not be a Fly-style argument")


def _reject_repository_cache_candidate(value: object, field_name: str) -> None:
    raw_value = str(value)
    _reject_remote_database_or_fly_argument(raw_value, field_name)
    candidate = Path(raw_value)
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    _reject_repository_cache_path(candidate.resolve(strict=False), field_name)


def _reject_repository_cache_path(path: Path, field_name: str) -> None:
    if _is_within(path, _REPOSITORY_FEC_BULK_ROOT):
        raise ValueError(f"{field_name} must not be the repository FEC bulk cache or one of its descendants")


def _is_within(path: Path, root: Path) -> bool:
    return path == root or path.is_relative_to(root)


def _require_within(path: Path, root: Path, message: str) -> None:
    if not _is_within(path, root):
        raise ValueError(message)


def _load_committee_ids(path: Path, *, expected_count: int, expected_sha256: str) -> frozenset[str]:
    actual_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual_sha256 != expected_sha256:
        raise ValueError("committee-id-file SHA-256 mismatch")
    committee_ids = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(committee_ids) != expected_count:
        raise ValueError("committee-id-file count mismatch")
    if len(set(committee_ids)) != len(committee_ids):
        raise ValueError("committee-id-file contains duplicate IDs")
    if committee_ids != sorted(committee_ids):
        raise ValueError("committee-id-file IDs must be sorted")
    return frozenset(committee_ids)


def _validate_archive_evidence(
    path: Path,
    *,
    data_root: Path,
    expected_size_bytes: int,
    expected_sha256: str,
) -> None:
    _require_within(path, data_root, "archive-url must resolve inside data-root")
    actual_size = path.stat().st_size
    if actual_size != expected_size_bytes:
        raise ValueError("archive size mismatch")
    actual_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual_sha256 != expected_sha256:
        raise ValueError("archive SHA-256 mismatch")


def _materialized_rows(
    connection: Any,
    *,
    archive_path: Path,
    archive_member_name: str,
    committee_ids: frozenset[str],
    cohort_size: int,
) -> list[NormalizedBenchmarkRow]:
    connection.execute("CREATE TABLE normalized_rows (row_id VARCHAR, row_json VARCHAR)")
    for raw_row in read_bulk_file(archive_path, "itcont", expected_member_name=archive_member_name):
        mapped = map_contribution_fields(raw_row)
        if not _is_materializer_survivor(mapped, committee_ids):
            continue
        row = normalized_benchmark_row_from_signature(mapped_contribution_signature_tuple(mapped))
        connection.execute("INSERT INTO normalized_rows VALUES (?, ?)", [row.row_id, row.model_dump_json()])
    return [
        NormalizedBenchmarkRow.model_validate_json(row_json)
        for (row_json,) in connection.execute(
            """
            SELECT row_json
            FROM normalized_rows
            GROUP BY row_id, row_json
            ORDER BY row_id
            LIMIT ?
            """,
            [cohort_size],
        ).fetchall()
    ]


def _is_materializer_survivor(mapped: Mapping[str, object], committee_ids: frozenset[str]) -> bool:
    committee_id = _mapped_text(mapped, "committee_id")
    contributor_name = _mapped_text(mapped, "contributor_name")
    return (
        is_contribution_insights_mapped_row(mapped) and committee_id in committee_ids and contributor_name is not None
    )


def _write_jsonl(path: Path, rows: Sequence[NormalizedBenchmarkRow]) -> None:
    payload = "".join(f"{row.model_dump_json()}\n" for row in rows)
    path.write_text(payload, encoding="utf-8")


class _BenchmarkPaths(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    temp_root: Path
    input_path: Path
    output_path: Path


class _BenchmarkInvocationEvidence(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    input_sha256: str
    cohort_size: int
    timeout_seconds: int
    memory_bytes: int
    temp_bytes: int
    temp_root: Path
    benchmark_invocation_id: str


def _benchmark(args: argparse.Namespace) -> int:
    if os.environ.get(_BENCHMARK_CHILD_ENV) == "1" or getattr(args, "_run_in_process", False):
        return _benchmark_in_process(args)
    return _benchmark_subprocess(args)


def _benchmark_subprocess(args: argparse.Namespace) -> int:
    # The parent process owns isolation and budgets; the child owns ER analysis only.
    started_at = time.monotonic()
    paths = _resolve_benchmark_paths(args)
    input_sha256 = hashlib.sha256(paths.input_path.read_bytes()).hexdigest()
    benchmark_invocation_id = _new_benchmark_invocation_id()
    expected_evidence = _benchmark_invocation_evidence(args, paths, input_sha256, benchmark_invocation_id)
    paths.output_path.unlink(missing_ok=True)
    process = subprocess.Popen(
        _benchmark_child_argv(args, paths, benchmark_invocation_id),
        cwd=str(_REPO_ROOT),
        env=_benchmark_child_environment(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    peak_rss_bytes = 0
    peak_temp_bytes = 0
    elapsed_seconds = 0.0
    exit_state: Literal["passed", "failed", "timeout", "memory_exceeded", "temp_exceeded"] | None = None
    while process.poll() is None:
        elapsed_seconds = time.monotonic() - started_at
        peak_rss_bytes = max(peak_rss_bytes, _child_rss_bytes(process.pid))
        peak_temp_bytes = max(peak_temp_bytes, _temp_tree_size_bytes(paths.temp_root))
        if elapsed_seconds > args.timeout_seconds:
            exit_state = "timeout"
            break
        if peak_rss_bytes > args.memory_bytes:
            exit_state = "memory_exceeded"
            break
        if peak_temp_bytes > args.temp_bytes:
            exit_state = "temp_exceeded"
            break
        time.sleep(0.05)

    if exit_state is not None:
        _terminate_exact_child(process)
    stdout, stderr = process.communicate(timeout=1)
    if stdout:
        print(stdout, end="")
    if stderr:
        print(stderr, end="", file=sys.stderr)
    if exit_state is None:
        # Fail closed: a clean exit code is not trusted until the child receipt is
        # present, valid, and reports peak RSS/temp within the requested budgets.
        elapsed_seconds = time.monotonic() - started_at
        child_observation = _load_child_benchmark_observation(paths.output_path, expected_evidence)
        if child_observation is not None:
            peak_rss_bytes = max(peak_rss_bytes, child_observation.peak_rss_bytes or 0)
            peak_temp_bytes = max(peak_temp_bytes, child_observation.peak_temp_bytes or 0)
        exit_state = _completed_child_failure_state(
            process.returncode, child_observation, args.memory_bytes, args.temp_bytes
        )
        if exit_state is None:
            return 0

    observation = _red_benchmark_observation(
        args,
        paths,
        input_sha256=input_sha256,
        elapsed_seconds=round(elapsed_seconds, 6),
        peak_rss_bytes=peak_rss_bytes,
        peak_temp_bytes=peak_temp_bytes,
        exit_state=exit_state,
        benchmark_invocation_id=benchmark_invocation_id,
    )
    receipt = DonorErScaleSpikeReceipt(
        schema_version=_SCHEMA_VERSION,
        rows_sha256=input_sha256,
        observations=(observation,),
    )
    paths.output_path.write_text(receipt.model_dump_json() + "\n", encoding="utf-8")
    print(
        "benchmark "
        f"input_rows={observation.input_rows} "
        f"unique_signatures={observation.unique_signature_count} "
        f"max_block_size={observation.max_block_size} "
        f"exit_state={observation.exit_state}"
    )
    return 1


def _benchmark_in_process(args: argparse.Namespace) -> int:
    started_at = time.monotonic()
    paths = _resolve_benchmark_paths(args)
    input_bytes = paths.input_path.read_bytes()
    input_sha256 = hashlib.sha256(input_bytes).hexdigest()
    benchmark_invocation_id = _benchmark_in_process_invocation_id(args)
    config = BoundedDuckDBConfig(
        database_path=paths.temp_root / "donor_er_scale_spike.duckdb",
        temp_root=paths.temp_root,
        memory_limit_bytes=args.memory_bytes,
        max_temp_directory_size_bytes=args.temp_bytes,
    )
    benchmark_rows = _read_normalized_benchmark_jsonl(paths.input_path)
    # Benchmark rows are diagnostic signatures, not durable people or donor identities.
    er_rows = [_benchmark_person_er_row(row) for row in sorted(benchmark_rows, key=lambda row: row.row_id)]
    # Pair volumes come from the canonical Splink blocking-analysis owner.
    blocking_counts = count_blocked_pairs(
        er_rows,
        "person",
        bounded_connection_factory=lambda: open_bounded_duckdb_connection(config),
    )
    observation = RunObservation(
        command="benchmark",
        input_rows=len(benchmark_rows),
        output_rows=1,
        cohort_size=args.cohort_size,
        timeout_seconds=args.timeout_seconds,
        memory_bytes=args.memory_bytes,
        temp_bytes=args.temp_bytes,
        temp_root=str(paths.temp_root),
        input_sha256=input_sha256,
        unique_signature_count=len({_benchmark_signature(row) for row in benchmark_rows}),
        null_counts=_benchmark_null_counts(benchmark_rows),
        blocking_rules=blocking_counts,
        max_block_size=max((int(rule["max_block_size"]) for rule in blocking_counts), default=0),
        elapsed_seconds=round(time.monotonic() - started_at, 6),
        peak_rss_bytes=_current_process_peak_rss_bytes(),
        peak_temp_bytes=_temp_tree_size_bytes(paths.temp_root),
        exit_state="passed",
        benchmark_invocation_id=benchmark_invocation_id,
    )
    receipt = DonorErScaleSpikeReceipt(
        schema_version=_SCHEMA_VERSION,
        rows_sha256=input_sha256,
        observations=(observation,),
    )
    paths.output_path.write_text(receipt.model_dump_json() + "\n", encoding="utf-8")
    print(
        "benchmark "
        f"input_rows={observation.input_rows} "
        f"unique_signatures={observation.unique_signature_count} "
        f"max_block_size={observation.max_block_size} "
        f"exit_state={observation.exit_state}"
    )
    return 0


def _benchmark_child_argv(
    args: argparse.Namespace,
    paths: _BenchmarkPaths,
    benchmark_invocation_id: str,
) -> list[str]:
    return [
        sys.executable,
        str(Path(__file__).resolve()),
        "benchmark",
        "--benchmark-invocation-id",
        benchmark_invocation_id,
        "--input-path",
        str(paths.input_path),
        "--output-path",
        str(paths.output_path),
        "--cohort-size",
        str(args.cohort_size),
        "--timeout-seconds",
        str(args.timeout_seconds),
        "--memory-bytes",
        str(args.memory_bytes),
        "--temp-bytes",
        str(args.temp_bytes),
        "--temp-root",
        str(paths.temp_root),
    ]


def _benchmark_child_environment() -> dict[str, str]:
    env: dict[str, str] = {}
    for key, value in os.environ.items():
        normalized_key = key.upper()
        if any(token in normalized_key for token in _SCRUBBED_ENV_TOKENS):
            continue
        env[key] = value
    env[_BENCHMARK_CHILD_ENV] = "1"
    return env


def _new_benchmark_invocation_id() -> str:
    return secrets.token_hex(_BENCHMARK_INVOCATION_ID_BYTES)


def _benchmark_in_process_invocation_id(args: argparse.Namespace) -> str:
    benchmark_invocation_id = getattr(args, "benchmark_invocation_id", None)
    if benchmark_invocation_id:
        return str(benchmark_invocation_id)
    if os.environ.get(_BENCHMARK_CHILD_ENV) == "1":
        raise ValueError("benchmark child missing invocation evidence")
    return _new_benchmark_invocation_id()


def _terminate_exact_child(process: subprocess.Popen[str]) -> None:
    # Safety boundary: only the benchmark subprocess PID created by this parent is terminated.
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.communicate(timeout=1)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate(timeout=1)


def _benchmark_invocation_evidence(
    args: argparse.Namespace,
    paths: _BenchmarkPaths,
    input_sha256: str,
    benchmark_invocation_id: str,
) -> _BenchmarkInvocationEvidence:
    return _BenchmarkInvocationEvidence(
        input_sha256=input_sha256,
        cohort_size=args.cohort_size,
        timeout_seconds=args.timeout_seconds,
        memory_bytes=args.memory_bytes,
        temp_bytes=args.temp_bytes,
        temp_root=paths.temp_root,
        benchmark_invocation_id=benchmark_invocation_id,
    )


def _load_child_benchmark_observation(
    output_path: Path,
    expected_evidence: _BenchmarkInvocationEvidence,
) -> RunObservation | None:
    # Fail closed: a missing, unreadable, or malformed receipt yields no observation.
    try:
        receipt_text = output_path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        receipt = DonorErScaleSpikeReceipt.model_validate_json(receipt_text)
    except ValueError:
        return None
    if receipt.rows_sha256 != expected_evidence.input_sha256:
        return None
    benchmark_observations = [observation for observation in receipt.observations if observation.command == "benchmark"]
    if len(benchmark_observations) != 1:
        return None
    observation = benchmark_observations[0]
    if not _observation_matches_invocation(observation, expected_evidence):
        return None
    return observation


def _observation_matches_invocation(
    observation: RunObservation,
    expected: _BenchmarkInvocationEvidence,
) -> bool:
    return (
        observation.input_sha256 == expected.input_sha256
        and observation.cohort_size == expected.cohort_size
        and observation.timeout_seconds == expected.timeout_seconds
        and observation.memory_bytes == expected.memory_bytes
        and observation.temp_bytes == expected.temp_bytes
        and observation.temp_root == str(expected.temp_root)
        and observation.benchmark_invocation_id == expected.benchmark_invocation_id
    )


def _completed_child_failure_state(
    returncode: int | None,
    child_observation: RunObservation | None,
    memory_bytes: int,
    temp_bytes: int,
) -> Literal["failed", "memory_exceeded", "temp_exceeded"] | None:
    if returncode != 0 or child_observation is None or child_observation.exit_state != "passed":
        return "failed"
    if child_observation.peak_rss_bytes is None or child_observation.peak_temp_bytes is None:
        return "failed"
    if child_observation.peak_rss_bytes > memory_bytes:
        return "memory_exceeded"
    if child_observation.peak_temp_bytes > temp_bytes:
        return "temp_exceeded"
    return None


def _red_benchmark_observation(
    args: argparse.Namespace,
    paths: _BenchmarkPaths,
    *,
    input_sha256: str,
    elapsed_seconds: float,
    peak_rss_bytes: int,
    peak_temp_bytes: int,
    exit_state: Literal["failed", "timeout", "memory_exceeded", "temp_exceeded"],
    benchmark_invocation_id: str,
) -> RunObservation:
    rows = _read_normalized_benchmark_jsonl(paths.input_path)
    return RunObservation(
        command="benchmark",
        input_rows=len(rows),
        output_rows=0,
        cohort_size=args.cohort_size,
        timeout_seconds=args.timeout_seconds,
        memory_bytes=args.memory_bytes,
        temp_bytes=args.temp_bytes,
        temp_root=str(paths.temp_root),
        input_sha256=input_sha256,
        unique_signature_count=len({_benchmark_signature(row) for row in rows}),
        null_counts=_benchmark_null_counts(rows),
        blocking_rules=[],
        max_block_size=0,
        elapsed_seconds=elapsed_seconds,
        peak_rss_bytes=peak_rss_bytes,
        peak_temp_bytes=peak_temp_bytes,
        exit_state=exit_state,
        benchmark_invocation_id=benchmark_invocation_id,
    )


def _current_process_peak_rss_bytes() -> int:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    if sys.platform == "darwin":
        return int(usage.ru_maxrss)
    return int(usage.ru_maxrss) * 1024


def _child_rss_bytes(pid: int) -> int:
    completed = subprocess.run(
        ["ps", "-o", "rss=", "-p", str(pid)],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        return 0
    return int(completed.stdout.strip().splitlines()[0].strip()) * 1024


def _temp_tree_size_bytes(path: Path) -> int:
    total = 0
    for candidate in path.rglob("*"):
        if candidate.is_file():
            total += candidate.stat().st_size
    return total


def _resolve_benchmark_paths(args: argparse.Namespace) -> _BenchmarkPaths:
    execution_paths = _resolve_bounded_execution_paths(args)
    input_path = _resolve_existing_file(
        args.input_path,
        "input-path",
        base=execution_paths.temp_root,
    )
    _require_within(
        input_path,
        execution_paths.temp_root,
        "input-path must resolve inside temp-root",
    )
    if execution_paths.output_path == input_path or (
        execution_paths.output_path.exists() and execution_paths.output_path.samefile(input_path)
    ):
        raise ValueError("output-path must not resolve to input-path")
    return _BenchmarkPaths(
        temp_root=execution_paths.temp_root,
        input_path=input_path,
        output_path=execution_paths.output_path,
    )


def _read_normalized_benchmark_jsonl(path: Path) -> list[NormalizedBenchmarkRow]:
    rows: list[NormalizedBenchmarkRow] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(NormalizedBenchmarkRow.model_validate_json(line))
    return rows


def _benchmark_person_er_row(row: NormalizedBenchmarkRow) -> dict[str, object]:
    parsed_name = parse_name(row.canonical_name)
    last_name = parsed_name.last
    normalized_address = None
    return {
        "id": row.row_id,
        "canonical_name": parsed_name.canonical or None,
        "first_name": parsed_name.first,
        "last_name": last_name,
        "last_name_prefix5": last_name[:5] if last_name else None,
        "last_name_prefix3": last_name[:3] if last_name else None,
        "date_of_birth": None,
        "normalized_address": normalized_address,
        "street_number": None,
        "zip5": row.zip5,
        "state": row.state,
        "employer": row.employer,
        "occupation": row.occupation,
        "identifier_key": None,
    }


def _benchmark_signature(
    row: NormalizedBenchmarkRow,
) -> tuple[str | None, str | None, str | None, str | None, str | None, str | None]:
    return (row.canonical_name, row.employer, row.occupation, row.city, row.state, row.zip5)


def _benchmark_null_counts(rows: Sequence[NormalizedBenchmarkRow]) -> dict[str, int]:
    nullable_fields = ("canonical_name", "employer", "occupation", "city", "state", "zip5")
    return {field: sum(getattr(row, field) is None for row in rows) for field in nullable_fields}


def _validate_receipt(args: argparse.Namespace) -> int:
    try:
        receipt_path = _resolve_receipt_argument(args)
        receipt = _parse_validatable_receipt_markdown(receipt_path)
        if getattr(args, "require_cleanup", False):
            if isinstance(receipt, DonorProxyMeasurementReceipt):
                raise ValueError("cleanup evidence is not part of donor proxy measurement receipts")
            _require_released_lane_resources(receipt.cleanup_evidence)
    except (OSError, ValueError) as error:
        # Never echo receipt field values: a validation error may reference a
        # credential-looking string, so only the sanitized message reaches stderr.
        print(f"validate-receipt failed: {error}", file=sys.stderr)
        return 1
    if getattr(args, "emit_validated_json", False):
        print(receipt.model_dump_json())
        return 0
    if isinstance(receipt, DonorProxyMeasurementReceipt):
        summary = f"validate-receipt schema_version={receipt.schema_version} verdict={receipt.verdict}"
    else:
        summary = (
            "validate-receipt "
            f"b2_disposition={receipt.b2_disposition} "
            f"b2_blocker_class={receipt.b2_blocker_class} "
            f"terminal_disposition={receipt.terminal_disposition}"
        )
    if getattr(args, "require_cleanup", False):
        summary += " cleanup=verified"
    print(summary)
    return 0


def _validate_pair_attribution(args: argparse.Namespace) -> int:
    try:
        receipt_path = Path(args.receipt).resolve(strict=True)
        artifact_path = Path(args.artifact).resolve(strict=True)
        receipt = validate_donor_proxy_measurement_receipt_markdown(receipt_path.read_text(encoding="utf-8"))
        reference = receipt.pair_attribution_artifact
        if reference is None:
            raise ValueError("receipt does not declare a pair attribution artifact")
        if Path(reference.path).resolve(strict=True) != artifact_path:
            raise ValueError("receipt pair attribution path does not match --artifact")
        if hashlib.sha256(artifact_path.read_bytes()).hexdigest() != reference.sha256:
            raise ValueError("pair attribution artifact SHA-256 does not match receipt")
        artifact = DonorErPairAttributionArtifact.model_validate_json(artifact_path.read_text(encoding="utf-8"))
        if artifact.seed != receipt.seed or artifact.chosen_slice_size != receipt.chosen_slice_size:
            raise ValueError("pair attribution run identity does not match receipt")
        expected_audit_pair_keys = _sampled_audit_pair_keys(
            receipt.deterministic_cluster_sample,
            artifact.pair_attributions,
        )
        if artifact.sampled_false_pair_coverage.audit_pair_keys != expected_audit_pair_keys:
            raise ValueError("sampled-false-pair coverage does not match the receipt cluster sample")
        if reference.pair_count != len(artifact.pair_attributions):
            raise ValueError("receipt pair attribution count does not match artifact")
        if reference.sampled_pair_count != len(expected_audit_pair_keys):
            raise ValueError("receipt sampled pair count does not match artifact")
        if reference.validator_command != _pair_attribution_validator_command(receipt_path, artifact_path):
            raise ValueError("receipt validator command does not match the validated paths")
    except (OSError, ValidationError, ValueError) as error:
        if isinstance(error, ValidationError):
            message = _scrubbed_validation_message(error)
        else:
            message = str(error)
        print(f"validate-pair-attribution failed: {message}", file=sys.stderr)
        return 1
    print(
        "validate-pair-attribution "
        f"schema_version={artifact.schema_version} "
        f"pairs={len(artifact.pair_attributions)} "
        f"sampled_pairs={len(expected_audit_pair_keys)}"
    )
    return 0


def _resolve_receipt_argument(args: argparse.Namespace) -> Path:
    receipt = getattr(args, "receipt", None)
    receipt_path = getattr(args, "receipt_path", None)
    if receipt is not None and receipt_path is not None and receipt != receipt_path:
        raise ValueError("--receipt and --receipt-path name different files")
    selected = receipt if receipt is not None else receipt_path
    if selected is None:
        raise ValueError("one of --receipt or --receipt-path is required")
    return Path(selected)


def _require_released_lane_resources(cleanup: CleanupEvidence) -> None:
    # A cleanup gate that cannot fail is not a gate: name each unreleased
    # resource explicitly rather than reporting a single opaque boolean. The
    # release rule itself lives in _unreleased_lane_resources.
    unreleased = _unreleased_lane_resources(cleanup)
    if unreleased:
        raise ValueError(f"cleanup not verified: {', '.join(unreleased)}")


def _parse_receipt_markdown(path: Path) -> DonorErArchitectureReceipt:
    fenced_json = _single_fenced_receipt_json(path.read_text(encoding="utf-8"))
    try:
        return DonorErArchitectureReceipt.model_validate_json(fenced_json)
    except ValidationError as error:
        raise ValueError(_scrubbed_validation_message(error)) from None


def _parse_validatable_receipt_markdown(
    path: Path,
) -> DonorErArchitectureReceipt | DonorProxyMeasurementReceipt:
    markdown_text = path.read_text(encoding="utf-8")
    if _DONOR_PROXY_FENCED_RECEIPT_PATTERN.search(markdown_text):
        return validate_donor_proxy_measurement_receipt_markdown(markdown_text)
    return _parse_receipt_markdown(path)


def _single_fenced_receipt_json(markdown_text: str) -> str:
    # The report carries narrative for human readers, but only the single
    # fenced object is authoritative: prose is never parsed, and zero, multiple,
    # or wrong-language fences fail closed rather than picking a winner.
    blocks = _FENCED_RECEIPT_PATTERN.findall(markdown_text)
    if not blocks:
        raise ValueError(f"no fenced {_RECEIPT_FENCE_LANGUAGE} object found")
    if len(blocks) > 1:
        raise ValueError(f"expected exactly one fenced {_RECEIPT_FENCE_LANGUAGE} object")
    return blocks[0]


def _scrubbed_validation_message(error: ValidationError) -> str:
    # Report field locations and messages only; omit each error's `input` so
    # secret-bearing receipt values never reach stdout or stderr.
    return "; ".join(
        f"{'.'.join(_scrubbed_validation_location_part(part) for part in item['loc'])}: {item['msg']}"
        for item in error.errors(include_url=False)
    )


def _scrubbed_validation_location_part(part: object) -> str:
    text = str(part)
    if _receipt_text_is_secret_bearing(text):
        return "<redacted>"
    return text


def main(argv: list[str] | None = None) -> int:
    parser = build_argument_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as error:
        return int(error.code) if isinstance(error.code, int) else 1
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
