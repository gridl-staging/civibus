from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from domains.campaign_finance.coverage.authority_onboarding_rehearsal import (
    DiscoveryGateMode,
    run_authority_onboarding_rehearsal,
    verify_discovery_receipt,
    verify_evidence_file,
    write_rehearsal_receipt,
)


_SOURCE_COMMIT = "8e49bc0959b091699b6ca6d973789bc9f9f88c9e"
_SOURCE_TREE = "fd57f231d89fabac67277ae1647dad22d695bd51"
_CALCULATED_AT = datetime(2026, 8, 28, 22, 30, tzinfo=timezone.utc)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_discovery_receipt(root: Path, *, accepted_parent_count: int = 42) -> tuple[str, str]:
    packet_path = root / "packets" / "wave-05" / "synthetic-control.json"
    packet_path.parent.mkdir(parents=True)
    packet_path.write_text('{"status":"research_complete"}\n', encoding="utf-8")

    individual_receipt_path = root / "receipts" / "synthetic-control-receipt.json"
    individual_receipt_path.parent.mkdir(parents=True)
    individual_receipt_path.write_text('{"verdict":"pass"}\n', encoding="utf-8")

    program_receipt = {
        "receipt_version": 1,
        "issued_at_utc": "2026-08-28T22:14:00Z",
        "gate": "synthetic accepted discovery boundary",
        "verdict": "pass",
        "goal_thread_id": "01a04964-3c95-7260-8323-a634da4173b7",
        "bead_id": "civibus-aji.46",
        "scope": {
            "national_parents_completed_total": accepted_parent_count,
            "national_parent_total": 57,
            "independent_adversarial_review_rate": f"{accepted_parent_count}/{accepted_parent_count}",
        },
        "packets": [
            {
                "parent": "SYNTH",
                "path": "packets/wave-05/synthetic-control.json",
                "sha256": _sha256(packet_path),
                "individual_receipt": "receipts/synthetic-control-receipt.json",
                "individual_receipt_sha256": _sha256(individual_receipt_path),
            }
        ],
        "program_hashes": {
            "packet_set_sha256": "1" * 64,
            "parent_queue_sha256": "2" * 64,
            "tracker_sha256": "3" * 64,
            "packet_schema_sha256": "4" * 64,
            "validator_sha256": "5" * 64,
            "execution_contract_sha256": "6" * 64,
        },
        "explicit_refusal_classes": ["Unsupported authority combinations refuse."],
        "nonclaims": [
            "No canonical coverage-registry decision was changed.",
            "No product code or Git generation was created by discovery.",
            "No production or lifecycle state was mutated.",
            "No public coverage or completeness claim was made.",
            "Discovery does not authorize another jurisdiction implementation; Washington remains the sole implementation generation.",
        ],
        "successor_ownership": {
            "active_bead": "civibus-aji.46",
            "revalidation": "civibus-aji.46 recurring read-only queue",
        },
    }
    receipt_path = root / "receipts" / "program-controls-receipt.json"
    receipt_path.write_text(json.dumps(program_receipt, indent=2) + "\n", encoding="utf-8")
    return "receipts/program-controls-receipt.json", _sha256(receipt_path)


def _write_terminal_discovery_receipt(root: Path) -> tuple[str, str, str, str]:
    packet_inventory = []
    parents = []
    for index in range(57):
        parent = f"P{index:02d}"
        relative_path = f"packets/wave-06/{parent}.json"
        packet_path = root / relative_path
        packet_path.parent.mkdir(parents=True, exist_ok=True)
        packet_path.write_text(json.dumps({"parent": parent}) + "\n", encoding="utf-8")
        packet_inventory.append(
            {
                "parent": parent,
                "path": relative_path,
                "sha256": _sha256(packet_path),
                "relation": "partitioned_overlapping",
                "review": "passed",
                "revalidate_by": "2027-06-30",
            }
        )
        parents.append({"code": parent, "status": "research_complete_review_passed"})

    packet_paths = sorted((root / "packets").glob("**/*.json"))
    packet_set_sha256 = hashlib.sha256(b"".join(path.read_bytes() for path in packet_paths)).hexdigest()
    queue_path = root / "parent-queue.json"
    queue_path.write_text(json.dumps({"parent_count": 57, "parents": parents}) + "\n", encoding="utf-8")
    tracker_path = root / "tracker.json"
    tracker_path.write_text(
        json.dumps(
            {
                "bead_id": "civibus-aji.46",
                "coverage_registry_is_decision_owner": True,
                "this_directory_is_non_authoritative": True,
                "packet_set_sha256": packet_set_sha256,
                "discovery_queue": {"parent_complete": 57, "parent_queued": 0, "parent_in_progress": 0},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    schema_path = root / "packet-schema.json"
    schema_path.write_text('{"type":"object"}\n', encoding="utf-8")
    validator_path = root / "validate.py"
    validator_path.write_text("raise SystemExit(0)\n", encoding="utf-8")
    execution_path = root / "execution-contract.json"
    execution_path.write_text('{"mode":"read-only"}\n', encoding="utf-8")
    program_hashes = {
        "packet_set_sha256": packet_set_sha256,
        "parent_queue_sha256": _sha256(queue_path),
        "tracker_sha256": _sha256(tracker_path),
        "packet_schema_sha256": _sha256(schema_path),
        "validator_sha256": _sha256(validator_path),
        "execution_contract_sha256": _sha256(execution_path),
    }

    wave_receipt_path = root / "receipts" / "wave-06-controls-receipt.json"
    wave_receipt_path.parent.mkdir(parents=True, exist_ok=True)
    wave_receipt_path.write_text('{"verdict":"pass"}\n', encoding="utf-8")
    nonclaims = [
        "No canonical product Git was changed or advanced.",
        "No coverage-registry value or public coverage decision was changed.",
        "No lifecycle state, production system, scheduled production job, or public claim was mutated.",
        "No new jurisdiction implementation was created; Washington remains the sole implementation generation.",
    ]
    review = {
        "status": "pass",
        "parents_reviewed": 57,
        "parents_passed": 57,
        "parents_failed_terminal": 0,
        "no_unreviewed_parent_promoted": True,
    }
    successor = {
        "bead_id": "civibus-aji.46",
        "mode": "recurring read-only revalidation queue",
        "promotion_authority": False,
    }
    manifest = {
        "manifest_version": 1,
        "verdict": "pass",
        "bead_id": "civibus-aji.46",
        "goal_thread_id": "01a04964-3c95-7260-8323-a634da4173b7",
        "national_parents_completed_total": 57,
        "national_parent_total": 57,
        "independent_adversarial_review_outcome": review,
        "program_hashes": program_hashes,
        "explicit_unresolved_refuse_classes": [
            {"class": "cross-authority deduplication", "rule": "Refuse without an official conflict rule."}
        ],
        "nonclaims": nonclaims,
        "successor_revalidation_owner": successor,
        "packet_inventory": packet_inventory,
        "accepted_wave_receipts": [
            {
                "wave": "wave-06",
                "path": "receipts/wave-06-controls-receipt.json",
                "sha256": _sha256(wave_receipt_path),
            }
        ],
        "terminal_artifact_contract": {
            "complete_manifest_path": "complete-manifest.json",
            "aggregate_receipt_path": "receipts/national-terminal-controls-receipt.json",
            "detached_hash_envelope_path": "terminal-acceptance-envelope.json",
        },
    }
    manifest_path = root / "complete-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    manifest_sha256 = _sha256(manifest_path)

    aggregate = {
        "receipt_version": 1,
        "verdict": "pass",
        "bead_id": "civibus-aji.46",
        "goal_thread_id": "01a04964-3c95-7260-8323-a634da4173b7",
        "national_parents_completed_total": 57,
        "national_parent_total": 57,
        "independent_adversarial_review_outcome": review,
        "program_hashes": program_hashes,
        "explicit_unresolved_refuse_classes": ["Cross-authority deduplication must refuse."],
        "nonclaims": nonclaims,
        "successor_revalidation_owner": successor,
        "terminal_artifacts": {
            "complete_manifest": {"path": "complete-manifest.json", "sha256": manifest_sha256},
            "aggregate_receipt": {
                "path": "receipts/national-terminal-controls-receipt.json",
                "sha256_recorded_at": "terminal-acceptance-envelope.json#/terminal_artifacts/aggregate_receipt/sha256",
            },
            "detached_acceptance_envelope": {"path": "terminal-acceptance-envelope.json"},
        },
        "final_wave_packets": [packet_inventory[-1]],
        "corpus_metrics": {"packets": 57},
        "canonical_state": {
            "remote_main_observed": "8e49bc0959b091699b6ca6d973789bc9f9f88c9e",
            "coverage_registry_remains_decision_owner": True,
            "shared_checkout_advanced_or_mutated": False,
        },
        "cleanup": {
            "unfinished_research_batches": 0,
            "unreviewed_parent_packets": 0,
            "product_checkout_left_clean": True,
        },
    }
    receipt_path = root / "receipts" / "national-terminal-controls-receipt.json"
    receipt_path.write_text(json.dumps(aggregate, indent=2) + "\n", encoding="utf-8")
    receipt_sha256 = _sha256(receipt_path)

    envelope = {
        "verdict": "pass",
        "bead_id": "civibus-aji.46",
        "goal_thread_id": "01a04964-3c95-7260-8323-a634da4173b7",
        "national_parents_completed_total": 57,
        "national_parent_total": 57,
        "independent_adversarial_review_outcome": "pass",
        "hash_algorithm": "sha256",
        "terminal_artifacts": {
            "complete_manifest": {"path": "complete-manifest.json", "sha256": manifest_sha256},
            "aggregate_receipt": {
                "path": "receipts/national-terminal-controls-receipt.json",
                "sha256": receipt_sha256,
            },
        },
        "successor_revalidation_owner": successor,
    }
    envelope_path = root / "terminal-acceptance-envelope.json"
    envelope_path.write_text(json.dumps(envelope, indent=2) + "\n", encoding="utf-8")
    return (
        "receipts/national-terminal-controls-receipt.json",
        receipt_sha256,
        "terminal-acceptance-envelope.json",
        _sha256(envelope_path),
    )


def test_discovery_receipt_is_hash_bound_and_final_gate_requires_57_parents(tmp_path: Path) -> None:
    relative_path, receipt_sha256 = _write_discovery_receipt(tmp_path)

    launch = verify_discovery_receipt(
        discovery_root=tmp_path,
        receipt_path=relative_path,
        expected_sha256=receipt_sha256,
        gate_mode=DiscoveryGateMode.LAUNCH,
    )
    assert launch.accepted_parent_count == 42
    assert launch.parent_count == 57
    assert launch.packet_set_sha256 == "1" * 64

    with pytest.raises(ValueError, match="detached terminal acceptance envelope"):
        verify_discovery_receipt(
            discovery_root=tmp_path,
            receipt_path=relative_path,
            expected_sha256=receipt_sha256,
            gate_mode=DiscoveryGateMode.FINAL,
        )

    packet_path = tmp_path / "packets" / "wave-05" / "synthetic-control.json"
    packet_path.write_text('{"status":"tampered"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="packet SHA-256 mismatch"):
        verify_discovery_receipt(
            discovery_root=tmp_path,
            receipt_path=relative_path,
            expected_sha256=receipt_sha256,
            gate_mode=DiscoveryGateMode.LAUNCH,
        )


def test_terminal_discovery_contract_cross_hashes_all_57_packets_and_runs_final_rehearsal(tmp_path: Path) -> None:
    receipt_path, receipt_sha256, envelope_path, envelope_sha256 = _write_terminal_discovery_receipt(tmp_path)

    discovery = verify_discovery_receipt(
        discovery_root=tmp_path,
        receipt_path=receipt_path,
        expected_sha256=receipt_sha256,
        gate_mode=DiscoveryGateMode.FINAL,
        acceptance_envelope_path=envelope_path,
        acceptance_envelope_sha256=envelope_sha256,
    )
    assert discovery.accepted_parent_count == 57
    assert discovery.independent_adversarial_review_rate == "57/57"
    assert discovery.final_gate_satisfied is True
    assert discovery.terminal_artifacts is not None
    assert discovery.terminal_artifacts.complete_manifest_path == "complete-manifest.json"
    assert discovery.terminal_artifacts.aggregate_receipt_sha256 == receipt_sha256

    rehearsal = run_authority_onboarding_rehearsal(
        discovery_root=tmp_path,
        discovery_receipt_path=receipt_path,
        discovery_receipt_sha256=receipt_sha256,
        gate_mode=DiscoveryGateMode.FINAL,
        source_git_commit=_SOURCE_COMMIT,
        source_git_tree=_SOURCE_TREE,
        calculated_at=_CALCULATED_AT,
        verify_relation_receipts=False,
        discovery_acceptance_envelope_path=envelope_path,
        discovery_acceptance_envelope_sha256=envelope_sha256,
    )
    assert rehearsal.discovery.final_gate_satisfied is True
    assert len(rehearsal.controls) == 4

    packet_path = tmp_path / "packets" / "wave-06" / "P56.json"
    packet_path.write_text('{"parent":"tampered"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        verify_discovery_receipt(
            discovery_root=tmp_path,
            receipt_path=receipt_path,
            expected_sha256=receipt_sha256,
            gate_mode=DiscoveryGateMode.FINAL,
            acceptance_envelope_path=envelope_path,
            acceptance_envelope_sha256=envelope_sha256,
        )


def test_evidence_paths_refuse_symlinks_escape_and_hash_drift(tmp_path: Path) -> None:
    evidence_path = tmp_path / "receipts" / "accepted.json"
    evidence_path.parent.mkdir(parents=True)
    evidence_path.write_text('{"verdict":"pass"}\n', encoding="utf-8")
    evidence_sha256 = _sha256(evidence_path)

    assert verify_evidence_file(tmp_path, "receipts/accepted.json", evidence_sha256) == evidence_path

    with pytest.raises(ValueError, match="safe relative path"):
        verify_evidence_file(tmp_path, "../foreign.json", evidence_sha256)
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        verify_evidence_file(tmp_path, "receipts/accepted.json", "0" * 64)

    symlink_path = tmp_path / "receipts" / "linked.json"
    symlink_path.symlink_to(evidence_path)
    with pytest.raises(ValueError, match="regular non-symlink"):
        verify_evidence_file(tmp_path, "receipts/linked.json", evidence_sha256)


def test_rehearsal_traverses_four_existing_owner_controls_without_claims(tmp_path: Path) -> None:
    relative_path, receipt_sha256 = _write_discovery_receipt(tmp_path)

    receipt = run_authority_onboarding_rehearsal(
        discovery_root=tmp_path,
        discovery_receipt_path=relative_path,
        discovery_receipt_sha256=receipt_sha256,
        gate_mode=DiscoveryGateMode.LAUNCH,
        source_git_commit=_SOURCE_COMMIT,
        source_git_tree=_SOURCE_TREE,
        calculated_at=_CALCULATED_AT,
        verify_relation_receipts=False,
    )

    assert receipt.verdict == "pass"
    assert receipt.discovery.accepted_parent_count == 42
    assert receipt.discovery.final_gate_satisfied is False
    assert receipt.database.mutated is False
    assert receipt.database.connection_attempted is False
    assert receipt.nonclaims == [
        "no_production_mutation",
        "no_registry_or_coverage_promotion",
        "no_public_claim",
        "no_real_new_jurisdiction_implementation",
        "washington_remains_sole_implemented_jurisdiction",
    ]

    controls = {control.control_id: control for control in receipt.controls}
    assert set(controls) == {
        "parent_routed_compatibility",
        "direct_authority_compatibility",
        "partitioned_overlap_refusal",
        "unresolved_authority_refusal",
    }

    parent = controls["parent_routed_compatibility"]
    assert parent.subject_code == "WA_SEATTLE"
    assert parent.compatibility_branch == "covered_by_parent"
    assert parent.status_origin == "inherited"
    assert parent.authority_relation == "partitioned_overlapping"
    assert parent.source_contract_scope == "state/WA"
    assert parent.refresh_plan_id == "regional-wa-scheduled"

    direct = controls["direct_authority_compatibility"]
    assert direct.subject_code == "NY_NEW_YORK"
    assert direct.compatibility_branch == "independent_target"
    assert direct.status_origin == "direct"
    assert direct.source_contract_scope == "municipality/NYC"
    assert direct.refresh_plan_id == "rehearsal-nyc-direct"

    overlap = controls["partitioned_overlap_refusal"]
    assert overlap.authority_relation == "partitioned_overlapping"
    assert overlap.aggregation_disposition == "refuse_combination"
    assert overlap.deduplication_outcome == "refused_before_cross_system_deduplication"
    assert overlap.lifecycle_eligible is False

    unresolved = controls["unresolved_authority_refusal"]
    assert unresolved.subject_code == "NC_WAKE"
    assert unresolved.authority_relation == "unresolved"
    assert unresolved.translation_status == "refused"
    assert unresolved.source_contract_scope is None
    assert unresolved.refresh_plan_id is None
    assert unresolved.navigation_status == "unavailable"

    for control in receipt.controls:
        assert control.stage_order == [
            "authority_selection",
            "typed_translation",
            "source_contract",
            "ingest_entity_provenance_dedup",
            "refresh_recurrence_plan",
            "lifecycle_coverage_gate",
            "api_navigation_status",
            "release_receipt",
        ]
        assert control.totals_emitted is False
        assert control.public_claim_emitted is False

    output_path = tmp_path / "rehearsal-receipt.json"
    write_rehearsal_receipt(output_path, receipt)
    assert json.loads(output_path.read_text(encoding="utf-8"))["source"]["git_tree"] == _SOURCE_TREE
