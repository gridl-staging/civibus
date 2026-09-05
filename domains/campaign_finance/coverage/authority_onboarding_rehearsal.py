"""Machine-verifiable rehearsal over the existing filing-authority owners.

This module composes canonical owners; it is not a registry, scheduler, source
adapter, route system, or status layer. Discovery evidence stays outside product
Git and is accepted only by an exact caller-supplied SHA-256.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field

from api.queries.regional_navigation import resolve_regional_navigation_node
from core.refresh.authority_execution_plan import (
    AuthorityExecutionPlan,
    load_authority_execution_plan,
    select_execution_plan_jobs,
)
from core.refresh.runner import RefreshJob, RunnerParameters
from core.types.python.models import DataSource, EntitySourceLink, SourceRecord
from domains.campaign_finance.coverage.lifecycle import (
    AuthorityPromotionDecision,
    AuthorityPromotionEvidence,
    AuthorityRecurrenceEvidence,
    AuthoritySourceEvidence,
    DEFAULT_IMPLEMENTED_REGION_LIFECYCLE_PATH,
    assess_authority_promotion,
    load_lifecycle,
)
from domains.campaign_finance.coverage.registry import (
    DEFAULT_REGISTRY_PATH,
    CoverageRegistry,
    CoverageRegistryRow,
    FilingAuthorityReference,
    IdentityTranslationError,
    ScopedIdentity,
    UnresolvedAuthorityRelation,
    load_registry,
    translate_identity,
)
from domains.campaign_finance.coverage.status.models import Refusal
from domains.campaign_finance.coverage.status.municipality import (
    RegionOwnerResolution,
    resolve_region_owners,
)
from domains.campaign_finance.ingest.authority_identity import (
    AuthorityOverlapRefusal,
    AuthorityScopedSourceRecord,
    deduplicate_authority_overlap,
)
from domains.campaign_finance.jurisdictions.config_schema import (
    JurisdictionConfig,
    load_jurisdiction_config,
    operational_scope_for_config_identity,
)
from domains.campaign_finance.jurisdictions.refresh_registry import (
    JURISDICTION_REFRESH_REGISTRATIONS,
    build_registered_refresh_jobs,
)


_REPO_ROOT = Path(__file__).resolve().parents[3]
_WA_CONFIG_PATH = _REPO_ROOT / "domains/campaign_finance/jurisdictions/states/WA/config.yaml"
_NYC_CONFIG_PATH = _REPO_ROOT / "domains/campaign_finance/jurisdictions/cities/NYC/config.yaml"
_WA_PROFILE_PATH = _REPO_ROOT / "infra/fly/regional_refresh_machine_profile.json"
_HEX_40 = re.compile(r"^[0-9a-f]{40}$")
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_DISCOVERY_BEAD = "civibus-aji.46"
_DISCOVERY_TASK = "01a04964-3c95-7260-8323-a634da4173b7"
_REQUIRED_CANONICAL_RECEIPT = "8e49bc0959b091699b6ca6d973789bc9f9f88c9e"
_NATIONAL_PARENT_COUNT = 57
_LAUNCH_PARENT_FLOOR = 42
_STAGE_ORDER = [
    "authority_selection",
    "typed_translation",
    "source_contract",
    "ingest_entity_provenance_dedup",
    "refresh_recurrence_plan",
    "lifecycle_coverage_gate",
    "api_navigation_status",
    "release_receipt",
]
_NONCLAIMS = [
    "no_production_mutation",
    "no_registry_or_coverage_promotion",
    "no_public_claim",
    "no_real_new_jurisdiction_implementation",
    "washington_remains_sole_implemented_jurisdiction",
]


class DiscoveryGateMode(str, Enum):
    LAUNCH = "launch"
    FINAL = "final"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TerminalDiscoveryArtifacts(_StrictModel):
    complete_manifest_path: str
    complete_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    aggregate_receipt_path: str
    aggregate_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    acceptance_envelope_path: str
    acceptance_envelope_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class DiscoveryEvidence(_StrictModel):
    bead_id: Literal["civibus-aji.46"]
    receipt_path: str
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    accepted_parent_count: int = Field(ge=0, le=57)
    parent_count: Literal[57]
    independent_adversarial_review_rate: str
    packet_set_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    parent_queue_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    tracker_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    packet_schema_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    validator_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    execution_contract_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    explicit_refusal_classes: tuple[str, ...]
    successor_revalidation_owner: str
    final_gate_satisfied: bool
    terminal_artifacts: TerminalDiscoveryArtifacts | None = None


class SourceEvidence(_StrictModel):
    git_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    git_tree: str = Field(pattern=r"^[0-9a-f]{40}$")


class DatabaseBoundary(_StrictModel):
    connection_attempted: Literal[False] = False
    mutated: Literal[False] = False
    locality: Literal["not_applicable_pure_contract_rehearsal"] = "not_applicable_pure_contract_rehearsal"
    pre_row_count: Literal[0] = 0
    post_row_count: Literal[0] = 0


class RehearsalStage(_StrictModel):
    name: str
    owner: str
    outcome: Literal["passed", "refused_as_designed"]
    detail: str


class RehearsalControlResult(_StrictModel):
    control_id: str
    subject_code: str
    compatibility_branch: str | None
    status_origin: str
    authority_relation: str
    aggregation_disposition: str
    translation_status: str
    source_contract_scope: str | None
    ingest_provenance_outcome: str
    deduplication_outcome: str
    refresh_plan_id: str | None
    lifecycle_eligible: bool
    navigation_status: str
    relation_evidence_sha256: tuple[str, ...]
    stage_order: list[str]
    stages: tuple[RehearsalStage, ...]
    totals_emitted: Literal[False] = False
    public_claim_emitted: Literal[False] = False


class AuthorityOnboardingRehearsalReceipt(_StrictModel):
    schema_version: Literal[1] = 1
    verdict: Literal["pass"] = "pass"
    calculated_at: datetime
    source: SourceEvidence
    discovery: DiscoveryEvidence
    database: DatabaseBoundary
    controls: tuple[RehearsalControlResult, ...]
    nonclaims: list[str]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_evidence_file(root: Path, relative_path: str, expected_sha256: str) -> Path:
    """Resolve one immutable evidence file inside ``root`` and verify its digest."""

    if _HEX_64.fullmatch(expected_sha256) is None:
        raise ValueError("evidence expected SHA-256 must be 64 lowercase hexadecimal characters")
    relative = Path(relative_path)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ValueError("evidence path must be a safe relative path")
    resolved_root = root.resolve(strict=True)
    candidate = root / relative
    try:
        resolved_candidate = candidate.resolve(strict=True)
    except OSError as error:
        raise ValueError(f"evidence file is unavailable: {relative_path}") from error
    if not resolved_candidate.is_relative_to(resolved_root):
        raise ValueError("evidence path must be a safe relative path inside the discovery root")
    if candidate.is_symlink() or not candidate.is_file():
        raise ValueError("evidence file must be a regular non-symlink file")
    actual_sha256 = _sha256(candidate)
    if actual_sha256 != expected_sha256:
        raise ValueError(
            f"evidence SHA-256 mismatch for {relative_path}: expected {expected_sha256}, found {actual_sha256}"
        )
    return candidate


def _read_strict_json(path: Path, *, label: str) -> dict[str, Any]:
    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        payload: dict[str, object] = {}
        for key, value in pairs:
            if key in payload:
                raise ValueError(f"{label} contains duplicate object key: {key}")
            payload[key] = value
        return payload

    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"{label} contains non-finite number: {value}")
            ),
        )
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is not readable strict JSON") from error
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object")
    return payload


def _required_sha256(mapping: object, key: str) -> str:
    if not isinstance(mapping, dict):
        raise ValueError("discovery receipt program_hashes must be an object")
    value = mapping.get(key)
    if not isinstance(value, str) or _HEX_64.fullmatch(value) is None:
        raise ValueError(f"discovery receipt requires exact program hash {key}")
    return value


def _validate_discovery_nonclaims(payload: dict[str, Any]) -> None:
    nonclaims = payload.get("nonclaims")
    if not isinstance(nonclaims, list) or not all(isinstance(item, str) for item in nonclaims):
        raise ValueError("discovery receipt requires explicit nonclaims")
    text = " ".join(nonclaims).lower()
    required_boundaries = {
        "registry": "coverage-registry",
        "production": "production",
        "public claim": "public coverage",
        "jurisdiction implementation": "jurisdiction implementation",
        "Washington implementation": "washington",
    }
    missing = [label for label, fragment in required_boundaries.items() if fragment not in text]
    if missing:
        raise ValueError(f"discovery receipt is missing nonclaim boundary/boundaries: {missing!r}")


def _terminal_counts_and_review(payload: dict[str, Any], *, label: str) -> tuple[int, int]:
    accepted = payload.get("national_parents_completed_total")
    parent_count = payload.get("national_parent_total")
    if accepted != _NATIONAL_PARENT_COUNT or parent_count != _NATIONAL_PARENT_COUNT:
        raise ValueError(f"{label} requires the independently accepted complete 57/57 parent universe")
    review = payload.get("independent_adversarial_review_outcome")
    if isinstance(review, str):
        if review != "pass":
            raise ValueError(f"{label} independent adversarial review must pass")
    elif isinstance(review, dict):
        if review.get("status") != "pass":
            raise ValueError(f"{label} independent adversarial review must pass")
        if review.get("parents_reviewed") != _NATIONAL_PARENT_COUNT:
            raise ValueError(f"{label} must record 57 independently reviewed parents")
        if review.get("parents_passed") != _NATIONAL_PARENT_COUNT:
            raise ValueError(f"{label} must record 57 independently passed parents")
        if review.get("parents_failed_terminal") != 0:
            raise ValueError(f"{label} must record zero terminal parent failures")
        if review.get("no_unreviewed_parent_promoted") is not True:
            raise ValueError(f"{label} must refuse promotion of unreviewed parents")
    else:
        raise ValueError(f"{label} requires an independent adversarial review outcome")
    return accepted, parent_count


def _terminal_successor_owner(payload: dict[str, Any], *, label: str) -> str:
    successor = payload.get("successor_revalidation_owner")
    if not isinstance(successor, dict):
        raise ValueError(f"{label} requires successor/revalidation ownership")
    bead_id = successor.get("bead_id")
    mode = successor.get("mode")
    if bead_id != _DISCOVERY_BEAD or not isinstance(mode, str) or "read-only" not in mode:
        raise ValueError(f"{label} successor must remain the civibus-aji.46 read-only queue")
    if successor.get("promotion_authority") is not False:
        raise ValueError(f"{label} successor must have no promotion authority")
    return f"{bead_id}: {mode}"


def _terminal_program_hashes(payload: dict[str, Any], *, label: str) -> dict[str, str]:
    raw_hashes = payload.get("program_hashes")
    if not isinstance(raw_hashes, dict):
        raise ValueError(f"{label} requires exact program hashes")
    return {
        key: _required_sha256(raw_hashes, key)
        for key in (
            "packet_set_sha256",
            "parent_queue_sha256",
            "tracker_sha256",
            "packet_schema_sha256",
            "validator_sha256",
            "execution_contract_sha256",
        )
    }


def _verify_terminal_program_files(
    discovery_root: Path,
    *,
    program_hashes: dict[str, str],
    inventory_paths: set[str],
) -> None:
    direct_files = {
        "parent_queue_sha256": "parent-queue.json",
        "tracker_sha256": "tracker.json",
        "packet_schema_sha256": "packet-schema.json",
        "validator_sha256": "validate.py",
        "execution_contract_sha256": "execution-contract.json",
    }
    for hash_key, relative_path in direct_files.items():
        verify_evidence_file(discovery_root, relative_path, program_hashes[hash_key])

    packet_root = discovery_root / "packets"
    packet_paths = sorted(path for path in packet_root.glob("**/*.json") if path.is_file())
    relative_packet_paths = {path.relative_to(discovery_root).as_posix() for path in packet_paths}
    if relative_packet_paths != inventory_paths or len(packet_paths) != _NATIONAL_PARENT_COUNT:
        raise ValueError("terminal manifest inventory must exactly cover all 57 discovery packets")
    for packet_path in packet_paths:
        relative_path = packet_path.relative_to(discovery_root).as_posix()
        verify_evidence_file(discovery_root, relative_path, _sha256(packet_path))
    packet_set_sha256 = hashlib.sha256(b"".join(path.read_bytes() for path in packet_paths)).hexdigest()
    if packet_set_sha256 != program_hashes["packet_set_sha256"]:
        raise ValueError("terminal packet-set SHA-256 does not match the complete packet corpus")

    queue = _read_strict_json(discovery_root / "parent-queue.json", label="terminal parent queue")
    parents = queue.get("parents")
    if not isinstance(parents, list) or len(parents) != _NATIONAL_PARENT_COUNT:
        raise ValueError("terminal parent queue must contain exactly 57 parents")
    parent_codes = [row.get("code") for row in parents if isinstance(row, dict)]
    statuses = [row.get("status") for row in parents if isinstance(row, dict)]
    if (
        queue.get("parent_count") != _NATIONAL_PARENT_COUNT
        or len(parent_codes) != _NATIONAL_PARENT_COUNT
        or len(set(parent_codes)) != _NATIONAL_PARENT_COUNT
        or set(statuses) != {"research_complete_review_passed"}
    ):
        raise ValueError("terminal parent queue must be 57/57 unique review-passed parents")

    tracker = _read_strict_json(discovery_root / "tracker.json", label="terminal tracker")
    discovery_queue = tracker.get("discovery_queue")
    if (
        tracker.get("bead_id") != _DISCOVERY_BEAD
        or tracker.get("coverage_registry_is_decision_owner") is not True
        or tracker.get("this_directory_is_non_authoritative") is not True
        or tracker.get("packet_set_sha256") != program_hashes["packet_set_sha256"]
        or not isinstance(discovery_queue, dict)
        or discovery_queue.get("parent_complete") != _NATIONAL_PARENT_COUNT
        or discovery_queue.get("parent_queued") != 0
        or discovery_queue.get("parent_in_progress") != 0
    ):
        raise ValueError("terminal tracker must preserve registry ownership and a complete read-only queue")


def _verify_terminal_discovery_receipt(
    *,
    discovery_root: Path,
    receipt_path: str,
    expected_sha256: str,
    payload: dict[str, Any],
    acceptance_envelope_path: str | None,
    acceptance_envelope_sha256: str | None,
) -> DiscoveryEvidence:
    if acceptance_envelope_path is None or acceptance_envelope_sha256 is None:
        raise ValueError("final rehearsal requires the detached terminal acceptance envelope path and SHA-256")
    if (
        payload.get("verdict") != "pass"
        or payload.get("bead_id") != _DISCOVERY_BEAD
        or payload.get("goal_thread_id") != _DISCOVERY_TASK
    ):
        raise ValueError("terminal aggregate receipt must be a PASS owned by civibus-aji.46")
    accepted, parent_count = _terminal_counts_and_review(payload, label="terminal aggregate receipt")
    _validate_discovery_nonclaims(payload)
    successor_owner = _terminal_successor_owner(payload, label="terminal aggregate receipt")
    program_hashes = _terminal_program_hashes(payload, label="terminal aggregate receipt")

    refusal_classes = payload.get("explicit_unresolved_refuse_classes")
    if (
        not isinstance(refusal_classes, list)
        or not refusal_classes
        or not all(isinstance(item, str) and item for item in refusal_classes)
    ):
        raise ValueError("terminal aggregate receipt requires explicit unresolved/refuse classes")

    envelope_file = verify_evidence_file(
        discovery_root,
        acceptance_envelope_path,
        acceptance_envelope_sha256,
    )
    envelope = _read_strict_json(envelope_file, label="terminal acceptance envelope")
    if (
        envelope.get("verdict") != "pass"
        or envelope.get("bead_id") != _DISCOVERY_BEAD
        or envelope.get("goal_thread_id") != _DISCOVERY_TASK
        or envelope.get("hash_algorithm") != "sha256"
    ):
        raise ValueError("terminal acceptance envelope owner/verdict/hash contract mismatch")
    _terminal_counts_and_review(envelope, label="terminal acceptance envelope")
    _terminal_successor_owner(envelope, label="terminal acceptance envelope")
    envelope_artifacts = envelope.get("terminal_artifacts")
    if not isinstance(envelope_artifacts, dict):
        raise ValueError("terminal acceptance envelope requires both immutable artifact hashes")
    manifest_reference = envelope_artifacts.get("complete_manifest")
    receipt_reference = envelope_artifacts.get("aggregate_receipt")
    if not isinstance(manifest_reference, dict) or not isinstance(receipt_reference, dict):
        raise ValueError("terminal acceptance envelope requires manifest and aggregate receipt references")
    manifest_path = manifest_reference.get("path")
    manifest_sha256 = manifest_reference.get("sha256")
    if not isinstance(manifest_path, str) or not isinstance(manifest_sha256, str):
        raise ValueError("terminal acceptance envelope requires the exact complete-manifest path and SHA-256")
    if receipt_reference.get("path") != receipt_path or receipt_reference.get("sha256") != expected_sha256:
        raise ValueError("terminal acceptance envelope aggregate-receipt cross-hash mismatch")

    manifest_file = verify_evidence_file(discovery_root, manifest_path, manifest_sha256)
    manifest = _read_strict_json(manifest_file, label="complete discovery manifest")
    if (
        manifest.get("verdict") != "pass"
        or manifest.get("bead_id") != _DISCOVERY_BEAD
        or manifest.get("goal_thread_id") != _DISCOVERY_TASK
    ):
        raise ValueError("complete discovery manifest owner/verdict mismatch")
    _terminal_counts_and_review(manifest, label="complete discovery manifest")
    _validate_discovery_nonclaims(manifest)
    _terminal_successor_owner(manifest, label="complete discovery manifest")
    manifest_program_hashes = _terminal_program_hashes(manifest, label="complete discovery manifest")
    if manifest_program_hashes != program_hashes:
        raise ValueError("terminal manifest and aggregate receipt program hashes must match exactly")

    manifest_refusals = manifest.get("explicit_unresolved_refuse_classes")
    if (
        not isinstance(manifest_refusals, list)
        or not manifest_refusals
        or not all(
            isinstance(item, dict) and isinstance(item.get("class"), str) and isinstance(item.get("rule"), str)
            for item in manifest_refusals
        )
    ):
        raise ValueError("complete discovery manifest requires typed unresolved/refuse classes")

    packet_inventory = manifest.get("packet_inventory")
    if not isinstance(packet_inventory, list) or len(packet_inventory) != _NATIONAL_PARENT_COUNT:
        raise ValueError("complete discovery manifest requires exactly 57 packet inventory entries")
    inventory_parents: set[str] = set()
    inventory_paths: set[str] = set()
    for index, packet in enumerate(packet_inventory):
        if not isinstance(packet, dict):
            raise ValueError(f"complete discovery manifest packet {index} must be an object")
        parent = packet.get("parent")
        packet_path = packet.get("path")
        packet_sha256 = packet.get("sha256")
        if (
            not isinstance(parent, str)
            or not isinstance(packet_path, str)
            or not isinstance(packet_sha256, str)
            or packet.get("review") != "passed"
        ):
            raise ValueError(f"complete discovery manifest packet {index} is not review-passed and hash-bound")
        verify_evidence_file(discovery_root, packet_path, packet_sha256)
        inventory_parents.add(parent)
        inventory_paths.add(packet_path)
    if len(inventory_parents) != _NATIONAL_PARENT_COUNT or len(inventory_paths) != _NATIONAL_PARENT_COUNT:
        raise ValueError("complete discovery manifest packet parents and paths must be unique")

    accepted_wave_receipts = manifest.get("accepted_wave_receipts")
    if not isinstance(accepted_wave_receipts, list) or not accepted_wave_receipts:
        raise ValueError("complete discovery manifest requires accepted wave receipts")
    for index, wave_receipt in enumerate(accepted_wave_receipts):
        if not isinstance(wave_receipt, dict):
            raise ValueError(f"accepted wave receipt {index} must be an object")
        wave_path = wave_receipt.get("path")
        wave_sha256 = wave_receipt.get("sha256")
        if not isinstance(wave_path, str) or not isinstance(wave_sha256, str):
            raise ValueError(f"accepted wave receipt {index} requires an exact path and SHA-256")
        verify_evidence_file(discovery_root, wave_path, wave_sha256)

    artifact_contract = manifest.get("terminal_artifact_contract")
    if (
        not isinstance(artifact_contract, dict)
        or artifact_contract.get("complete_manifest_path") != manifest_path
        or artifact_contract.get("aggregate_receipt_path") != receipt_path
        or artifact_contract.get("detached_hash_envelope_path") != acceptance_envelope_path
    ):
        raise ValueError("complete discovery manifest terminal artifact paths do not match the envelope")

    receipt_artifacts = payload.get("terminal_artifacts")
    if not isinstance(receipt_artifacts, dict):
        raise ValueError("terminal aggregate receipt requires terminal artifact references")
    receipt_manifest_reference = receipt_artifacts.get("complete_manifest")
    receipt_envelope_reference = receipt_artifacts.get("detached_acceptance_envelope")
    if (
        not isinstance(receipt_manifest_reference, dict)
        or receipt_manifest_reference.get("path") != manifest_path
        or receipt_manifest_reference.get("sha256") != manifest_sha256
        or not isinstance(receipt_envelope_reference, dict)
        or receipt_envelope_reference.get("path") != acceptance_envelope_path
    ):
        raise ValueError("terminal aggregate receipt artifact references do not match the envelope")

    final_wave_packets = payload.get("final_wave_packets")
    if not isinstance(final_wave_packets, list) or not final_wave_packets:
        raise ValueError("terminal aggregate receipt requires exact final-wave packet evidence")
    for index, packet in enumerate(final_wave_packets):
        if not isinstance(packet, dict):
            raise ValueError(f"terminal final-wave packet {index} must be an object")
        packet_path = packet.get("path")
        packet_sha256 = packet.get("sha256")
        if not isinstance(packet_path, str) or not isinstance(packet_sha256, str) or packet.get("review") != "passed":
            raise ValueError(f"terminal final-wave packet {index} must be review-passed and hash-bound")
        verify_evidence_file(discovery_root, packet_path, packet_sha256)

    corpus_metrics = payload.get("corpus_metrics")
    canonical_state = payload.get("canonical_state")
    cleanup = payload.get("cleanup")
    if not isinstance(corpus_metrics, dict) or corpus_metrics.get("packets") != _NATIONAL_PARENT_COUNT:
        raise ValueError("terminal aggregate receipt corpus metrics must record 57 packets")
    if (
        not isinstance(canonical_state, dict)
        or canonical_state.get("remote_main_observed") != _REQUIRED_CANONICAL_RECEIPT
        or canonical_state.get("coverage_registry_remains_decision_owner") is not True
        or canonical_state.get("shared_checkout_advanced_or_mutated") is not False
    ):
        raise ValueError("terminal discovery must preserve the required canonical registry boundary")
    if (
        not isinstance(cleanup, dict)
        or cleanup.get("unfinished_research_batches") != 0
        or cleanup.get("unreviewed_parent_packets") != 0
        or cleanup.get("product_checkout_left_clean") is not True
    ):
        raise ValueError("terminal discovery cleanup must leave no unfinished or unreviewed parent work")

    _verify_terminal_program_files(
        discovery_root,
        program_hashes=program_hashes,
        inventory_paths=inventory_paths,
    )
    return DiscoveryEvidence(
        bead_id=_DISCOVERY_BEAD,
        receipt_path=receipt_path,
        receipt_sha256=expected_sha256,
        accepted_parent_count=accepted,
        parent_count=parent_count,
        independent_adversarial_review_rate="57/57",
        packet_set_sha256=program_hashes["packet_set_sha256"],
        parent_queue_sha256=program_hashes["parent_queue_sha256"],
        tracker_sha256=program_hashes["tracker_sha256"],
        packet_schema_sha256=program_hashes["packet_schema_sha256"],
        validator_sha256=program_hashes["validator_sha256"],
        execution_contract_sha256=program_hashes["execution_contract_sha256"],
        explicit_refusal_classes=tuple(refusal_classes),
        successor_revalidation_owner=successor_owner,
        final_gate_satisfied=True,
        terminal_artifacts=TerminalDiscoveryArtifacts(
            complete_manifest_path=manifest_path,
            complete_manifest_sha256=manifest_sha256,
            aggregate_receipt_path=receipt_path,
            aggregate_receipt_sha256=expected_sha256,
            acceptance_envelope_path=acceptance_envelope_path,
            acceptance_envelope_sha256=acceptance_envelope_sha256,
        ),
    )


def verify_discovery_receipt(
    *,
    discovery_root: Path,
    receipt_path: str,
    expected_sha256: str,
    gate_mode: DiscoveryGateMode,
    acceptance_envelope_path: str | None = None,
    acceptance_envelope_sha256: str | None = None,
) -> DiscoveryEvidence:
    """Verify one accepted external discovery receipt and its directly listed artifacts."""

    path = verify_evidence_file(discovery_root, receipt_path, expected_sha256)
    payload = _read_strict_json(path, label="discovery receipt")
    if gate_mode is DiscoveryGateMode.FINAL:
        return _verify_terminal_discovery_receipt(
            discovery_root=discovery_root,
            receipt_path=receipt_path,
            expected_sha256=expected_sha256,
            payload=payload,
            acceptance_envelope_path=acceptance_envelope_path,
            acceptance_envelope_sha256=acceptance_envelope_sha256,
        )
    if acceptance_envelope_path is not None or acceptance_envelope_sha256 is not None:
        raise ValueError("launch rehearsal does not consume terminal acceptance-envelope arguments")
    if payload.get("verdict") != "pass" or payload.get("bead_id") != _DISCOVERY_BEAD:
        raise ValueError("discovery receipt must be a PASS owned by civibus-aji.46")

    scope = payload.get("scope")
    if not isinstance(scope, dict):
        raise ValueError("discovery receipt requires scope")
    accepted = scope.get("national_parents_completed_total")
    parent_count = scope.get("national_parent_total")
    review_rate = scope.get("independent_adversarial_review_rate")
    if not isinstance(accepted, int) or not isinstance(parent_count, int) or not isinstance(review_rate, str):
        raise ValueError("discovery receipt requires parent counts and independent adversarial review rate")
    if parent_count != _NATIONAL_PARENT_COUNT or accepted > parent_count:
        raise ValueError("discovery receipt parent universe must be exactly 57")
    if gate_mode is DiscoveryGateMode.LAUNCH and accepted < _LAUNCH_PARENT_FLOOR:
        raise ValueError("launch rehearsal requires the accepted Wave 5 floor of at least 42/57 parents")
    packets = payload.get("packets")
    if not isinstance(packets, list) or not packets:
        raise ValueError("discovery receipt requires directly listed packet evidence")
    for index, packet in enumerate(packets):
        if not isinstance(packet, dict):
            raise ValueError(f"discovery receipt packet {index} must be an object")
        packet_path = packet.get("path")
        packet_sha256 = packet.get("sha256")
        individual_path = packet.get("individual_receipt")
        individual_sha256 = packet.get("individual_receipt_sha256")
        if not all(
            isinstance(value, str) for value in (packet_path, packet_sha256, individual_path, individual_sha256)
        ):
            raise ValueError(f"discovery receipt packet {index} lacks exact evidence paths and hashes")
        try:
            verify_evidence_file(discovery_root, packet_path, packet_sha256)
        except ValueError as error:
            raise ValueError(f"packet SHA-256 mismatch or unsafe packet evidence at index {index}") from error
        verify_evidence_file(discovery_root, individual_path, individual_sha256)

    hashes = payload.get("program_hashes")
    packet_set_sha256 = _required_sha256(hashes, "packet_set_sha256")
    parent_queue_sha256 = _required_sha256(hashes, "parent_queue_sha256")
    tracker_sha256 = _required_sha256(hashes, "tracker_sha256")
    packet_schema_sha256 = _required_sha256(hashes, "packet_schema_sha256")
    validator_sha256 = _required_sha256(hashes, "validator_sha256")
    execution_contract_sha256 = _required_sha256(hashes, "execution_contract_sha256")
    _validate_discovery_nonclaims(payload)

    refusals = payload.get("explicit_refusal_classes")
    if not isinstance(refusals, list) or not refusals or not all(isinstance(item, str) and item for item in refusals):
        raise ValueError("discovery receipt requires explicit unresolved/refuse classes")
    successor = payload.get("successor_ownership")
    if not isinstance(successor, dict):
        raise ValueError("discovery receipt requires successor/revalidation ownership")
    successor_owner = successor.get("revalidation") or successor.get("successor_revalidation_owner")
    if not isinstance(successor_owner, str) or not successor_owner:
        raise ValueError("discovery receipt requires a nonblank successor revalidation owner")

    return DiscoveryEvidence(
        bead_id=_DISCOVERY_BEAD,
        receipt_path=receipt_path,
        receipt_sha256=expected_sha256,
        accepted_parent_count=accepted,
        parent_count=parent_count,
        independent_adversarial_review_rate=review_rate,
        packet_set_sha256=packet_set_sha256,
        parent_queue_sha256=parent_queue_sha256,
        tracker_sha256=tracker_sha256,
        packet_schema_sha256=packet_schema_sha256,
        validator_sha256=validator_sha256,
        execution_contract_sha256=execution_contract_sha256,
        explicit_refusal_classes=tuple(refusals),
        successor_revalidation_owner=successor_owner,
        final_gate_satisfied=accepted == parent_count,
    )


def _relation_aggregation(row: CoverageRegistryRow) -> str:
    relation = row.authority_relation
    if relation.relation == "partitioned_overlapping":
        return relation.deduplication.disposition
    if relation.relation == "unresolved":
        return relation.aggregation_disposition
    return "not_applicable"


def _verify_relation_receipt_files(discovery_root: Path, row: CoverageRegistryRow) -> tuple[str, ...]:
    relation = row.authority_relation
    if relation.relation != "partitioned_overlapping":
        return ()
    evidence = relation.evidence
    receipt_path = verify_evidence_file(discovery_root, evidence.receipt, evidence.receipt_sha256)
    receipt = _read_strict_json(receipt_path, label=f"{row.jurisdiction_code} authority receipt")
    if receipt.get("verdict") != "pass" or receipt.get("bead_id") != evidence.owner:
        raise ValueError(f"{row.jurisdiction_code} authority receipt owner/verdict mismatch")
    packet = receipt.get("packet")
    if not isinstance(packet, dict) or packet.get("sha256") != evidence.packet_sha256:
        raise ValueError(f"{row.jurisdiction_code} authority packet hash mismatch in receipt")
    packet_path = packet.get("path")
    if not isinstance(packet_path, str) or evidence.packet_sha256 is None:
        raise ValueError(f"{row.jurisdiction_code} authority receipt lacks packet path/hash")
    verify_evidence_file(discovery_root, packet_path, evidence.packet_sha256)
    hashes = [evidence.receipt_sha256, evidence.packet_sha256]
    if evidence.aggregate_receipt is not None and evidence.aggregate_receipt_sha256 is not None:
        verify_evidence_file(discovery_root, evidence.aggregate_receipt, evidence.aggregate_receipt_sha256)
        hashes.append(evidence.aggregate_receipt_sha256)
    return tuple(hashes)


def _registration_jobs(
    config: JurisdictionConfig,
    *,
    now: datetime,
) -> list[RefreshJob]:
    registration = next(
        item for item in JURISDICTION_REFRESH_REGISTRATIONS if item.identity == config.jurisdiction.identity
    )
    return build_registered_refresh_jobs(
        registrations=(registration,),
        configs=(config,),
        parameters=RunnerParameters(),
        now=now,
    )


def _prospective_nyc_plan(job: RefreshJob) -> AuthorityExecutionPlan:
    return AuthorityExecutionPlan.model_validate(
        {
            "schema_version": 1,
            "plan_id": "rehearsal-nyc-direct",
            "contract_path": "evidence/rehearsal-nyc-direct.json",
            "authority": {"kind": "municipality", "code": "NYC"},
            "scheduled": {
                "execution_origin": "scheduled",
                "job_keys": [job.key],
                "schedule": "weekly",
                "stop_on_failure": False,
            },
            "canary": {
                "execution_origin": "operator_attended",
                "job_keys": [job.key],
                "schedule": None,
                "stop_on_failure": True,
            },
            "concurrency": {
                "max_parallel_jobs": 1,
                "same_host_lock": "exact_authority_and_job_key_flock",
                "cross_host_lock": "exact_authority_and_job_key_postgres_advisory_lock",
            },
            "cadence_clock": {
                "scheduler": "machine_schedule",
                "job_due": "refresh_history_or_data_source_per_job",
                "force_allowed": False,
            },
        }
    )


def _single_authority_ingest(
    *,
    control_id: str,
    authority: FilingAuthorityReference,
    relation: object,
    operational_scope: str,
) -> tuple[str, str]:
    source_id = uuid5(NAMESPACE_URL, f"civibus-rje.6:{control_id}:source")
    record_id = uuid5(NAMESPACE_URL, f"civibus-rje.6:{control_id}:record")
    entity_id = uuid5(NAMESPACE_URL, f"civibus-rje.6:{control_id}:entity")
    source = DataSource(
        id=source_id,
        domain="campaign_finance",
        jurisdiction=operational_scope,
        filing_authority_type=authority.kind,
        filing_authority_code=authority.code,
        name=f"{control_id} source contract",
        source_url="https://example.invalid/rehearsal",
    )
    record = SourceRecord(
        id=record_id,
        data_source_id=source.id,
        source_record_key=f"{control_id}:record-1",
        raw_fields={"native_id": "record-1", "amount": "125.00"},
        pull_date=datetime(2026, 8, 28, tzinfo=timezone.utc),
    )
    link = EntitySourceLink(
        entity_type="organization",
        entity_id=entity_id,
        source_record_id=record.id,
        extraction_role="filer",
        confidence=1.0,
        extracted_fields={"native_id": "record-1"},
    )
    scoped = AuthorityScopedSourceRecord(
        source_record_id=record.id,
        authority=authority,
        source_name=source.name,
        raw_fields=record.raw_fields,
    )
    selected = deduplicate_authority_overlap(relation, [scoped])  # type: ignore[arg-type]
    if selected != [scoped] or link.source_record_id != record.id:
        raise ValueError("single-authority ingest/provenance rehearsal lost source identity")
    return "typed_source_record_and_entity_link_preserved", "single_authority_record_preserved"


def _promotion_decision(
    *,
    authority_identity: str,
    relation: str,
    aggregation_disposition: str,
    source_identity: str,
    observed_at: datetime,
) -> AuthorityPromotionDecision:
    evidence = AuthorityPromotionEvidence(
        authority_identity=authority_identity,
        authority_relation=relation,  # type: ignore[arg-type]
        aggregation_disposition=aggregation_disposition,  # type: ignore[arg-type]
        expected_source_identities=[source_identity],
        source_evidence=[
            AuthoritySourceEvidence(
                source_identity=source_identity,
                freshness_status="fresh",
                observed_at=observed_at,
            )
        ],
        recurrence_evidence=[
            AuthorityRecurrenceEvidence(
                source_identity=source_identity,
                pull_status="success",
                execution_origin="scheduled",
                completed_at=observed_at,
            )
        ],
        provenance_source_identities=[source_identity],
        keel_source_identities=[source_identity],
        deployed_source_identities=[source_identity],
        source_revision="a" * 40,
        api_revision="a" * 40,
        web_revision="a" * 40,
    )
    return assess_authority_promotion(evidence)


def _stages(
    *,
    authority: str,
    translation: str,
    source: str,
    ingest: str,
    refresh: str,
    lifecycle: str,
    navigation: str,
    refused_names: set[str] | None = None,
) -> tuple[RehearsalStage, ...]:
    details = {
        "authority_selection": ("coverage-registry/status owner", authority),
        "typed_translation": ("coverage-registry identity translation", translation),
        "source_contract": ("jurisdiction config/refresh registry", source),
        "ingest_entity_provenance_dedup": ("shared ingest/provenance owner", ingest),
        "refresh_recurrence_plan": ("authority execution-plan owner", refresh),
        "lifecycle_coverage_gate": ("coverage lifecycle owner", lifecycle),
        "api_navigation_status": ("regional navigation/status owner", navigation),
        "release_receipt": ("rje.6 receipt compositor", "No totals, promotion, or public claim emitted."),
    }
    refused = refused_names or set()
    return tuple(
        RehearsalStage(
            name=name,
            owner=details[name][0],
            outcome="refused_as_designed" if name in refused else "passed",
            detail=details[name][1],
        )
        for name in _STAGE_ORDER
    )


def _control_results(
    *,
    registry: CoverageRegistry,
    discovery_root: Path,
    calculated_at: datetime,
    verify_relation_receipts: bool,
) -> tuple[RehearsalControlResult, ...]:
    lifecycle = load_lifecycle(DEFAULT_IMPLEMENTED_REGION_LIFECYCLE_PATH)
    rows = {row.jurisdiction_code: row for row in registry.rows}
    seattle_row = rows["WA_SEATTLE"]
    nyc_row = rows["NY_NEW_YORK"]
    seattle_evidence = _verify_relation_receipt_files(discovery_root, seattle_row) if verify_relation_receipts else ()
    nyc_evidence = _verify_relation_receipt_files(discovery_root, nyc_row) if verify_relation_receipts else ()

    seattle_resolution = resolve_region_owners(
        "WA_SEATTLE",
        coverage_registry=registry,
        lifecycle_registry=lifecycle,
    )
    nyc_resolution = resolve_region_owners(
        "NY_NEW_YORK",
        coverage_registry=registry,
        lifecycle_registry=lifecycle,
    )
    if not isinstance(seattle_resolution, RegionOwnerResolution) or not isinstance(
        nyc_resolution, RegionOwnerResolution
    ):
        raise ValueError("canonical Seattle and NYC compatibility controls must resolve through existing owners")

    wa_config = load_jurisdiction_config(_WA_CONFIG_PATH)
    nyc_config = load_jurisdiction_config(_NYC_CONFIG_PATH)
    wa_scope = operational_scope_for_config_identity(wa_config.jurisdiction.identity)
    nyc_scope = operational_scope_for_config_identity(nyc_config.jurisdiction.identity)
    wa_jobs = _registration_jobs(wa_config, now=calculated_at)
    nyc_jobs = _registration_jobs(nyc_config, now=calculated_at)
    wa_plan = load_authority_execution_plan(_WA_PROFILE_PATH)
    selected_wa_jobs = select_execution_plan_jobs(wa_jobs, wa_plan, mode="scheduled")
    if len(nyc_jobs) != 1:
        raise ValueError("NYC direct compatibility rehearsal requires its exact existing singleton refresh job")
    nyc_plan = _prospective_nyc_plan(nyc_jobs[0])
    selected_nyc_jobs = select_execution_plan_jobs(nyc_jobs, nyc_plan, mode="scheduled")

    seattle_route = ScopedIdentity(
        domain="public_route",
        kind="municipality",
        value="/state/WA/municipality/seattle",
    )
    nyc_route = ScopedIdentity(
        domain="public_route",
        kind="municipality",
        value="/state/NY/municipality/new-york-city",
    )
    seattle_subject = translate_identity(
        seattle_route,
        target_domain="geographic_subject",
        translations=registry.identity_translations,
    )
    nyc_subject = translate_identity(
        nyc_route,
        target_domain="geographic_subject",
        translations=registry.identity_translations,
    )
    nyc_acquisition = translate_identity(
        nyc_route,
        target_domain="acquisition_scope",
        translations=registry.identity_translations,
    )
    if (
        seattle_subject.value != "WA_SEATTLE"
        or nyc_subject.value != "NY_NEW_YORK"
        or nyc_acquisition.value != nyc_config.jurisdiction.code
    ):
        raise ValueError("canonical route/config translations drifted")
    try:
        translate_identity(
            seattle_route,
            target_domain="filing_authority",
            translations=registry.identity_translations,
        )
    except IdentityTranslationError:
        seattle_translation_status = "bounded_geography_only"
    else:
        raise ValueError("Seattle route must not flatten its overlap into one filing authority")

    seattle_authority = next(
        authority
        for authority in seattle_row.authority_relation.authorities  # type: ignore[union-attr]
        if authority.kind == "state" and authority.code == "WA"
    )
    nyc_authority = next(
        authority
        for authority in nyc_row.authority_relation.authorities  # type: ignore[union-attr]
        if authority.kind == "municipality" and authority.code == "NY_NEW_YORK"
    )
    parent_ingest, parent_dedup = _single_authority_ingest(
        control_id="parent_routed_compatibility",
        authority=seattle_authority,
        relation=seattle_row.authority_relation,
        operational_scope=wa_scope,
    )
    direct_ingest, direct_dedup = _single_authority_ingest(
        control_id="direct_authority_compatibility",
        authority=nyc_authority,
        relation=nyc_row.authority_relation,
        operational_scope=nyc_scope,
    )

    seattle_node = resolve_regional_navigation_node(
        kind="municipality",
        state_code="WA",
        slug="seattle",
    )
    nyc_node = resolve_regional_navigation_node(
        kind="municipality",
        state_code="NY",
        slug="new-york-city",
    )
    wake_node = resolve_regional_navigation_node(kind="county", state_code="NC", slug="wake")
    if seattle_node is None or nyc_node is None or wake_node is None:
        raise ValueError("existing navigation controls must resolve")

    parent_promotion = _promotion_decision(
        authority_identity="state/WA",
        relation=seattle_row.authority_relation.relation,
        aggregation_disposition=_relation_aggregation(seattle_row),
        source_identity=f"state/WA:{wa_config.data_sources[0].name}",
        observed_at=calculated_at,
    )
    direct_promotion = _promotion_decision(
        authority_identity="municipality/NY_NEW_YORK",
        relation=nyc_row.authority_relation.relation,
        aggregation_disposition=_relation_aggregation(nyc_row),
        source_identity=f"municipality/NYC:{nyc_config.data_sources[0].name}",
        observed_at=calculated_at,
    )

    overlap_records = [
        AuthorityScopedSourceRecord(
            source_record_id=uuid5(NAMESPACE_URL, f"civibus-rje.6:overlap:{authority.code}"),
            authority=authority,
            source_name=f"source/{authority.code}",
            raw_fields={"native_id": "shared-record", "amount": "100.00"},
        )
        for authority in seattle_row.authority_relation.authorities[:2]  # type: ignore[union-attr]
    ]
    try:
        deduplicate_authority_overlap(seattle_row.authority_relation, overlap_records)
    except AuthorityOverlapRefusal:
        overlap_dedup = "refused_before_cross_system_deduplication"
    else:
        raise ValueError("Seattle overlap must refuse before cross-system deduplication")

    unresolved_relation = UnresolvedAuthorityRelation(
        relation="unresolved",
        candidate_authorities=[
            FilingAuthorityReference(kind="state", code="NC"),
            FilingAuthorityReference(kind="county", code="NC_WAKE"),
        ],
        reason="No exact typed authority translation is accepted for the Wake control.",
        aggregation_disposition="refuse",
    )
    unresolved_records = [
        AuthorityScopedSourceRecord(
            source_record_id=uuid5(NAMESPACE_URL, f"civibus-rje.6:wake:{authority.code}"),
            authority=authority,
            source_name=f"source/{authority.code}",
            raw_fields={"native_id": "shared-record"},
        )
        for authority in unresolved_relation.candidate_authorities
    ]
    try:
        deduplicate_authority_overlap(unresolved_relation, unresolved_records)
    except AuthorityOverlapRefusal:
        unresolved_dedup = "refused_before_source_or_entity_combination"
    else:
        raise ValueError("unresolved authority control must refuse ingest combination")
    try:
        translate_identity(
            ScopedIdentity(domain="geographic_subject", kind="county", value="NC_WAKE"),
            target_domain="filing_authority",
            translations=registry.identity_translations,
        )
    except IdentityTranslationError:
        unresolved_translation = "refused"
    else:
        raise ValueError("Wake control must not invent a filing-authority translation")
    wake_resolution = resolve_region_owners(
        "NC_WAKE",
        coverage_registry=registry,
        lifecycle_registry=lifecycle,
    )
    if not isinstance(wake_resolution, Refusal):
        raise ValueError("Wake control must refuse without a registry authority owner")
    unresolved_promotion = _promotion_decision(
        authority_identity="county/NC_WAKE",
        relation="unresolved",
        aggregation_disposition="refuse",
        source_identity="county/NC_WAKE:unsupported",
        observed_at=calculated_at,
    )

    return (
        RehearsalControlResult(
            control_id="parent_routed_compatibility",
            subject_code="WA_SEATTLE",
            compatibility_branch=seattle_resolution.branch,
            status_origin=seattle_resolution.status_origin,
            authority_relation=seattle_row.authority_relation.relation,
            aggregation_disposition=_relation_aggregation(seattle_row),
            translation_status=seattle_translation_status,
            source_contract_scope=wa_scope,
            ingest_provenance_outcome=parent_ingest,
            deduplication_outcome=parent_dedup,
            refresh_plan_id=wa_plan.plan_id,
            lifecycle_eligible=parent_promotion.eligible,
            navigation_status=seattle_node.finance.status,
            relation_evidence_sha256=seattle_evidence,
            stage_order=list(_STAGE_ORDER),
            stages=_stages(
                authority="Compatibility remains parent-routed while typed authority stays overlap-aware.",
                translation="Public route resolves only to geography; no flat filing authority is inferred.",
                source=f"Existing WA source contract remains scoped to {wa_scope}.",
                ingest=parent_ingest,
                refresh=f"Existing plan {wa_plan.plan_id} selects {len(selected_wa_jobs)} exact ordered jobs.",
                lifecycle="Overlap refusal prevents promotion despite synthetic green clocks.",
                navigation="Seattle exposes inherited status separately from filing-authority context.",
                refused_names={"lifecycle_coverage_gate"},
            ),
        ),
        RehearsalControlResult(
            control_id="direct_authority_compatibility",
            subject_code="NY_NEW_YORK",
            compatibility_branch=nyc_resolution.branch,
            status_origin=nyc_resolution.status_origin,
            authority_relation=nyc_row.authority_relation.relation,
            aggregation_disposition=_relation_aggregation(nyc_row),
            translation_status="bounded_direct_acquisition",
            source_contract_scope=nyc_scope,
            ingest_provenance_outcome=direct_ingest,
            deduplication_outcome=direct_dedup,
            refresh_plan_id=nyc_plan.plan_id,
            lifecycle_eligible=direct_promotion.eligible,
            navigation_status=nyc_node.finance.status,
            relation_evidence_sha256=nyc_evidence,
            stage_order=list(_STAGE_ORDER),
            stages=_stages(
                authority="Compatibility remains direct/independent-target while typed relation stays overlap-aware.",
                translation="Route resolves to NYC geography and exact NYC acquisition scope.",
                source=f"Existing NYC contract remains scoped to {nyc_scope}.",
                ingest=direct_ingest,
                refresh=f"Prospective plan selects exact existing job {selected_nyc_jobs[0].key} without execution.",
                lifecycle="Overlap refusal prevents promotion despite synthetic green clocks.",
                navigation="NYC direct status stays separate from its multi-authority context.",
                refused_names={"lifecycle_coverage_gate"},
            ),
        ),
        RehearsalControlResult(
            control_id="partitioned_overlap_refusal",
            subject_code="WA_SEATTLE",
            compatibility_branch=seattle_resolution.branch,
            status_origin=seattle_resolution.status_origin,
            authority_relation=seattle_row.authority_relation.relation,
            aggregation_disposition=_relation_aggregation(seattle_row),
            translation_status="multiple_authorities_preserved",
            source_contract_scope=None,
            ingest_provenance_outcome="authority_specific_provenance_preserved",
            deduplication_outcome=overlap_dedup,
            refresh_plan_id=None,
            lifecycle_eligible=parent_promotion.eligible,
            navigation_status=seattle_node.finance.status,
            relation_evidence_sha256=seattle_evidence,
            stage_order=list(_STAGE_ORDER),
            stages=_stages(
                authority="All receipt-backed Seattle authorities remain distinct.",
                translation="No single filing-authority or acquisition translation is invented.",
                source="Each authority requires a separate exact source contract.",
                ingest="Cross-system records refuse before entity merge, totals, or deduplication.",
                refresh="No cross-authority refresh plan is synthesized.",
                lifecycle="refuse_combination blocks coverage promotion.",
                navigation="Navigation exposes all authorities and refusal status.",
                refused_names={
                    "typed_translation",
                    "source_contract",
                    "ingest_entity_provenance_dedup",
                    "refresh_recurrence_plan",
                    "lifecycle_coverage_gate",
                },
            ),
        ),
        RehearsalControlResult(
            control_id="unresolved_authority_refusal",
            subject_code="NC_WAKE",
            compatibility_branch=None,
            status_origin="refused",
            authority_relation="unresolved",
            aggregation_disposition="refuse",
            translation_status=unresolved_translation,
            source_contract_scope=None,
            ingest_provenance_outcome="no_entity_or_provenance_merge",
            deduplication_outcome=unresolved_dedup,
            refresh_plan_id=None,
            lifecycle_eligible=unresolved_promotion.eligible,
            navigation_status=wake_node.finance.status,
            relation_evidence_sha256=(),
            stage_order=list(_STAGE_ORDER),
            stages=_stages(
                authority="No coverage-registry authority owner exists for the Wake subject.",
                translation="No filing-authority translation exists.",
                source="No source contract is admitted without authority selection.",
                ingest="Ingest combination refuses before entity/provenance merge.",
                refresh="No recurrence plan is admitted without an authority owner.",
                lifecycle="Unresolved relation refuses coverage promotion.",
                navigation="API navigation renders finance unavailable, never zero.",
                refused_names=set(_STAGE_ORDER[:-1]),
            ),
        ),
    )


def run_authority_onboarding_rehearsal(
    *,
    discovery_root: Path,
    discovery_receipt_path: str,
    discovery_receipt_sha256: str,
    gate_mode: DiscoveryGateMode,
    source_git_commit: str,
    source_git_tree: str,
    calculated_at: datetime,
    verify_relation_receipts: bool = True,
    discovery_acceptance_envelope_path: str | None = None,
    discovery_acceptance_envelope_sha256: str | None = None,
) -> AuthorityOnboardingRehearsalReceipt:
    """Execute the pure-contract rehearsal without database or external mutations."""

    if _HEX_40.fullmatch(source_git_commit) is None or _HEX_40.fullmatch(source_git_tree) is None:
        raise ValueError("rehearsal source commit and tree must be exact 40-character Git hashes")
    if calculated_at.tzinfo is None or calculated_at.utcoffset() is None:
        raise ValueError("rehearsal calculated_at must be timezone-aware")
    calculated_at = calculated_at.astimezone(timezone.utc)
    discovery = verify_discovery_receipt(
        discovery_root=discovery_root,
        receipt_path=discovery_receipt_path,
        expected_sha256=discovery_receipt_sha256,
        gate_mode=gate_mode,
        acceptance_envelope_path=discovery_acceptance_envelope_path,
        acceptance_envelope_sha256=discovery_acceptance_envelope_sha256,
    )
    registry = load_registry(DEFAULT_REGISTRY_PATH)
    controls = _control_results(
        registry=registry,
        discovery_root=discovery_root,
        calculated_at=calculated_at,
        verify_relation_receipts=verify_relation_receipts,
    )
    if len(controls) != 4 or any(control.totals_emitted or control.public_claim_emitted for control in controls):
        raise ValueError("rehearsal must produce exactly four fail-closed nonclaim controls")
    return AuthorityOnboardingRehearsalReceipt(
        calculated_at=calculated_at,
        source=SourceEvidence(git_commit=source_git_commit, git_tree=source_git_tree),
        discovery=discovery,
        database=DatabaseBoundary(),
        controls=controls,
        nonclaims=list(_NONCLAIMS),
    )


def write_rehearsal_receipt(path: Path, receipt: AuthorityOnboardingRehearsalReceipt) -> Path:
    """Write one canonical JSON receipt, refusing a symlink destination."""

    if path.exists() and (path.is_symlink() or not path.is_file()):
        raise ValueError("rehearsal output must be a regular non-symlink file")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = receipt.model_dump(mode="json")
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _parse_calculated_at(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise argparse.ArgumentTypeError("calculated-at must be an ISO-8601 timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("calculated-at must include a timezone")
    return parsed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the filing-authority onboarding rehearsal")
    parser.add_argument("--discovery-root", type=Path, required=True)
    parser.add_argument("--discovery-receipt", required=True)
    parser.add_argument("--discovery-receipt-sha256", required=True)
    parser.add_argument("--discovery-acceptance-envelope")
    parser.add_argument("--discovery-acceptance-envelope-sha256")
    parser.add_argument("--gate-mode", choices=[mode.value for mode in DiscoveryGateMode], required=True)
    parser.add_argument("--source-git-commit", required=True)
    parser.add_argument("--source-git-tree", required=True)
    parser.add_argument("--calculated-at", type=_parse_calculated_at, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    receipt = run_authority_onboarding_rehearsal(
        discovery_root=args.discovery_root,
        discovery_receipt_path=args.discovery_receipt,
        discovery_receipt_sha256=args.discovery_receipt_sha256,
        gate_mode=DiscoveryGateMode(args.gate_mode),
        source_git_commit=args.source_git_commit,
        source_git_tree=args.source_git_tree,
        calculated_at=args.calculated_at,
        discovery_acceptance_envelope_path=args.discovery_acceptance_envelope,
        discovery_acceptance_envelope_sha256=args.discovery_acceptance_envelope_sha256,
    )
    write_rehearsal_receipt(args.output, receipt)
    print(
        "PASS: authority onboarding rehearsal "
        f"mode={args.gate_mode} parents={receipt.discovery.accepted_parent_count}/57 "
        f"controls={len(receipt.controls)} output={args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "AuthorityOnboardingRehearsalReceipt",
    "DiscoveryGateMode",
    "run_authority_onboarding_rehearsal",
    "verify_discovery_receipt",
    "verify_evidence_file",
    "write_rehearsal_receipt",
]
