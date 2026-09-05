from __future__ import annotations

import hashlib
import json
import stat
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from core.refresh.authority_operations_profile import (
    canonical_sha256,
    expected_image_plan_proof,
    load_authority_operations_profile,
)
from domains.campaign_finance.coverage.lifecycle import (
    AuthorityPromotionReceipt,
    AuthorityPromotionEvidence,
    AuthorityRecurrenceEvidence,
    AuthoritySourceEvidence,
    DEFAULT_IMPLEMENTED_REGION_LIFECYCLE_PATH,
    DEFAULT_IMPLEMENTED_REGION_LIFECYCLE_SUMMARY_PATH,
    RawInvarianceSnapshot,
    RawRegionalLifecycleMarker,
    SurfaceParityPromotionArtifact,
    assess_authority_promotion_receipt,
    assess_authority_promotion,
    load_authority_promotion_receipt,
    load_lifecycle,
    invariance_capture_time_is_fresh,
    main,
    render_lifecycle_summary_markdown,
)
from domains.campaign_finance.coverage.registry import DEFAULT_REGISTRY_PATH, load_registry
from domains.campaign_finance.coverage.render_summary import derive_implemented_jurisdiction_codes
from domains.campaign_finance.coverage.seed_registry import derive_state_registry_rows

_REGIONAL_PROFILE_PATH = Path(__file__).resolve().parents[3] / "infra/fly/regional_refresh_machine_profile.json"
_REGIONAL_PROFILE = load_authority_operations_profile(_REGIONAL_PROFILE_PATH)


def _valid_payload(*, jurisdiction_code: str = "EX") -> dict[str, object]:
    return {
        "updated_at": "2026-03-27",
        "rows": [
            {
                "jurisdiction_code": jurisdiction_code,
                "name": "Example",
                "acquisition_pattern": "bulk_file",
                "discovery_maturity": "researched",
                "source_contract_maturity": "encoded",
                "legal_filing_semantics_maturity": "partial",
                "implementation_maturity": "fixture_tested",
                "operational_maturity": "manual_only",
                "public_claim_status": "implemented but unproven",
                "completeness_intelligence_maturity": "not_started",
                "civics_candidacy_status": "not_started",
                "main_blocker": "Example blocker",
            }
        ],
    }


def test_load_lifecycle_rejects_invalid_status_literal(tmp_path: Path) -> None:
    payload = _valid_payload()
    payload["rows"][0]["acquisition_pattern"] = "portal_magic"
    path = tmp_path / "lifecycle.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="acquisition_pattern"):
        load_lifecycle(path)


def test_render_lifecycle_summary_markdown_contains_expected_columns(tmp_path: Path) -> None:
    path = tmp_path / "lifecycle.json"
    path.write_text(json.dumps(_valid_payload()), encoding="utf-8")

    lifecycle = load_lifecycle(path)
    markdown = render_lifecycle_summary_markdown(lifecycle)

    assert "# Implemented Region Lifecycle Summary (Derived)" in markdown
    assert "| Jurisdiction | Acquisition Pattern | Discovery | Source Contract |" in markdown
    assert "| EX | bulk_file | researched | encoded |" in markdown


def test_render_lifecycle_summary_markdown_describes_state_and_independent_city_scope(tmp_path: Path) -> None:
    path = tmp_path / "lifecycle.json"
    path.write_text(json.dumps(_valid_payload()), encoding="utf-8")

    lifecycle = load_lifecycle(path)
    markdown = render_lifecycle_summary_markdown(lifecycle)

    assert (
        "This summary is a derived view of lifecycle statuses for the FEC plus "
        "implemented campaign-finance state and independent-city packages." in markdown
    )


def test_render_lifecycle_summary_markdown_escapes_table_breaking_text(tmp_path: Path) -> None:
    payload = _valid_payload()
    payload["rows"][0]["main_blocker"] = "Needs committee | enrichment\nand proof"
    path = tmp_path / "lifecycle.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    lifecycle = load_lifecycle(path)
    markdown = render_lifecycle_summary_markdown(lifecycle)

    assert "Needs committee \\| enrichment and proof" in markdown


def test_lifecycle_main_writes_summary_markdown(tmp_path: Path) -> None:
    lifecycle_path = tmp_path / "lifecycle.json"
    output_path = tmp_path / "summary.md"
    lifecycle_path.write_text(json.dumps(_valid_payload()), encoding="utf-8")

    exit_code = main(["--path", str(lifecycle_path), "--output", str(output_path)])

    assert exit_code == 0
    assert output_path.exists()
    assert "# Implemented Region Lifecycle Summary (Derived)" in output_path.read_text(encoding="utf-8")


def test_current_lifecycle_rows_match_implemented_jurisdiction_codes() -> None:
    lifecycle = load_lifecycle(DEFAULT_IMPLEMENTED_REGION_LIFECYCLE_PATH)

    assert {row.jurisdiction_code for row in lifecycle.rows} == derive_implemented_jurisdiction_codes()


def test_current_lifecycle_summary_snapshot_matches_rendered_output() -> None:
    lifecycle = load_lifecycle(DEFAULT_IMPLEMENTED_REGION_LIFECYCLE_PATH)

    assert DEFAULT_IMPLEMENTED_REGION_LIFECYCLE_SUMMARY_PATH.read_text(encoding="utf-8") == (
        render_lifecycle_summary_markdown(lifecycle)
    )


def test_lifecycle_public_claim_status_and_names_match_registry_authority() -> None:
    lifecycle = load_lifecycle(DEFAULT_IMPLEMENTED_REGION_LIFECYCLE_PATH)
    registry_rows_by_code = {row.jurisdiction_code: row for row in load_registry(DEFAULT_REGISTRY_PATH).rows}

    for row in lifecycle.rows:
        registry_row = registry_rows_by_code[row.jurisdiction_code]
        assert row.public_claim_status == registry_row.tier, row.jurisdiction_code
        assert row.name == registry_row.name, row.jurisdiction_code


def test_lifecycle_operational_maturity_respects_registry_runner_wiring_floor() -> None:
    lifecycle = load_lifecycle(DEFAULT_IMPLEMENTED_REGION_LIFECYCLE_PATH)
    registry_rows_by_code = {row.jurisdiction_code: row for row in load_registry(DEFAULT_REGISTRY_PATH).rows}

    for row in lifecycle.rows:
        registry_row = registry_rows_by_code[row.jurisdiction_code]
        if registry_row.runner_wired:
            assert row.operational_maturity in {"runner_wired", "operational"}, row.jurisdiction_code
            continue
        assert row.operational_maturity in {"unknown", "manual_only"}, row.jurisdiction_code


def test_washington_lifecycle_preserves_unattended_refresh_blocker_after_ie_disposition() -> None:
    lifecycle = load_lifecycle(DEFAULT_IMPLEMENTED_REGION_LIFECYCLE_PATH)
    wa_row = next(row for row in lifecycle.rows if row.jurisdiction_code == "WA")

    assert lifecycle.updated_at.isoformat() == "2026-08-27"
    assert wa_row.main_blocker == (
        "Need qualifying production core.refresh_run rows for state-wa-* on civibus-db/civibus to regain "
        "operational; WA still lacks qualifying recurring/unattended production refresh evidence."
    )
    assert "decide independent-expenditures ingest scope" not in wa_row.main_blocker


def test_lifecycle_owner_contract_does_not_infer_source_maturity_from_status(tmp_path: Path) -> None:
    payload = _valid_payload(jurisdiction_code="OWNER_CONTRACT")
    row = payload["rows"][0]
    assert isinstance(row, dict)
    row["source_contract_maturity"] = "encoded"
    row["operational_maturity"] = "runner_wired"
    row["public_claim_status"] = "launch-support candidate"
    path = tmp_path / "lifecycle.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    lifecycle = load_lifecycle(path)

    loaded_row = lifecycle.rows[0]
    assert loaded_row.source_contract_maturity == "encoded"
    assert loaded_row.operational_maturity == "runner_wired"
    assert loaded_row.public_claim_status == "launch-support candidate"


def test_implemented_state_packages_have_required_lifecycle_artifacts() -> None:
    project_root = Path(__file__).resolve().parents[3]
    states_root = project_root / "domains" / "campaign_finance" / "jurisdictions" / "states"

    for row in derive_state_registry_rows():
        state_dir = states_root / row.jurisdiction_code
        assert (state_dir / "README.md").exists(), row.jurisdiction_code
        assert (state_dir / "config.yaml").exists(), row.jurisdiction_code
        assert (state_dir / "data_semantics.md").exists(), row.jurisdiction_code
        assert (state_dir / "laws.md").exists(), row.jurisdiction_code
        assert (state_dir / "scraper").is_dir(), row.jurisdiction_code

        test_files = [*state_dir.glob("scraper/test_*.py"), *state_dir.glob("tests/test_*.py")]
        assert test_files, row.jurisdiction_code


def _promotion_evidence(**overrides: object) -> AuthorityPromotionEvidence:
    payload: dict[str, object] = {
        "authority_identity": "state/WA",
        "authority_relation": "independent",
        "aggregation_disposition": "not_applicable",
        "expected_source_identities": ["wa/contributions", "wa/expenditures"],
        "source_evidence": [
            AuthoritySourceEvidence(
                source_identity="wa/contributions",
                freshness_status="fresh",
                observed_at="2026-08-28T12:00:00Z",
            ),
            AuthoritySourceEvidence(
                source_identity="wa/expenditures",
                freshness_status="fresh",
                observed_at="2026-08-28T12:00:00Z",
            ),
        ],
        "recurrence_evidence": [
            AuthorityRecurrenceEvidence(
                source_identity="wa/contributions",
                pull_status="success",
                execution_origin="scheduled",
                completed_at="2026-08-28T12:00:00Z",
            ),
            AuthorityRecurrenceEvidence(
                source_identity="wa/expenditures",
                pull_status="success",
                execution_origin="scheduled",
                completed_at="2026-08-28T12:00:00Z",
            ),
        ],
        "provenance_source_identities": ["wa/contributions", "wa/expenditures"],
        "keel_source_identities": ["wa/contributions", "wa/expenditures"],
        "deployed_source_identities": ["wa/contributions", "wa/expenditures"],
        "source_revision": "a" * 40,
        "api_revision": "a" * 40,
        "web_revision": "a" * 40,
    }
    payload.update(overrides)
    return AuthorityPromotionEvidence.model_validate(payload)


def test_authority_promotion_requires_one_exact_green_evidence_set() -> None:
    decision = assess_authority_promotion(_promotion_evidence())

    assert decision.eligible is True
    assert decision.refusal_reasons == []
    assert decision.revision_parity == "match"


def test_one_fresh_source_never_promotes_incomplete_authority_evidence() -> None:
    evidence = _promotion_evidence(
        source_evidence=[
            AuthoritySourceEvidence(
                source_identity="wa/contributions",
                freshness_status="fresh",
                observed_at="2026-08-28T12:00:00Z",
            )
        ],
        recurrence_evidence=[],
        provenance_source_identities=["wa/contributions"],
        keel_source_identities=[],
        deployed_source_identities=[],
    )

    decision = assess_authority_promotion(evidence)

    assert decision.eligible is False
    assert any("freshness exact set" in reason for reason in decision.refusal_reasons)
    assert any("recurrence exact set" in reason for reason in decision.refusal_reasons)
    assert any("provenance exact set" in reason for reason in decision.refusal_reasons)
    assert any("Keel exact set" in reason for reason in decision.refusal_reasons)
    assert any("deployed evidence exact set" in reason for reason in decision.refusal_reasons)


def test_unresolved_overlap_degradation_and_revision_mismatch_each_refuse_promotion() -> None:
    degraded_sources = [
        AuthoritySourceEvidence(
            source_identity="wa/contributions",
            freshness_status="degraded",
            observed_at="2026-08-28T12:00:00Z",
        ),
        AuthoritySourceEvidence(
            source_identity="wa/expenditures",
            freshness_status="fresh",
            observed_at="2026-08-28T12:00:00Z",
        ),
    ]
    decision = assess_authority_promotion(
        _promotion_evidence(
            authority_relation="unresolved",
            aggregation_disposition="refuse",
            source_evidence=degraded_sources,
            api_revision="a" * 40,
            web_revision="b" * 40,
        )
    )

    assert decision.eligible is False
    assert decision.revision_parity == "mismatch"
    assert any("authority relation" in reason for reason in decision.refusal_reasons)
    assert any("degraded" in reason for reason in decision.refusal_reasons)
    assert any("revision parity" in reason for reason in decision.refusal_reasons)

    overlap = assess_authority_promotion(
        _promotion_evidence(
            authority_relation="partitioned_overlapping",
            aggregation_disposition="refuse_combination",
        )
    )
    assert overlap.eligible is False
    assert any("overlap disposition" in reason for reason in overlap.refusal_reasons)


def _promotion_receipt_payload(
    tmp_path: Path,
    *,
    reference_root: Path | None = None,
) -> dict[str, object]:
    def referenced_path(path: Path) -> str:
        return str(reference_root / path.name) if reference_root is not None else str(path)

    source_names = [
        "WA PDC Contributions",
        "WA PDC Expenditures",
        "WA PDC Independent Expenditures",
        "WA PDC Loans",
    ]
    source_identities = [f"state/WA:{name}" for name in source_names]
    job_keys = [
        "state-wa-contributions",
        "state-wa-expenditures",
        "state-wa-independent_expenditures",
        "state-wa-loans",
    ]
    completed_at = [f"2026-08-30T10:0{index}:00Z" for index in range(2, 6)]
    candidate_source_git_sha = "a" * 40
    candidate_tree_git_sha = "b" * 40
    qualified_image = "registry.fly.io/civibus-refresh:wa-r1@sha256:" + "c" * 64
    build_version = {"git_sha": candidate_source_git_sha, "built_at": "2026-08-29T09:00:00Z"}
    candidate_receipt = {
        "canonical_receipt_git_sha": _REGIONAL_PROFILE.canonical_source.receipt_git_sha,
        "canonical_source_git_sha": _REGIONAL_PROFILE.canonical_source.source_git_sha,
        "canonical_tree_git_sha": _REGIONAL_PROFILE.canonical_source.tree_git_sha,
        "image_proof": expected_image_plan_proof(_REGIONAL_PROFILE, build_version=build_version),
        "machine_config_sha256": _REGIONAL_PROFILE.machine.config_sha256,
        "produced_image_tagged_digest": qualified_image,
        "profile_sha256": canonical_sha256(_REGIONAL_PROFILE.model_dump(mode="json")),
        "qualification_kind": "authority_refresh_image_candidate",
        "schema_version": 2,
        "source_git_sha": candidate_source_git_sha,
        "source_tree_git_sha": candidate_tree_git_sha,
    }
    candidate_receipt_path = tmp_path / "candidate-receipt.json"
    candidate_receipt_path.write_text(json.dumps(candidate_receipt, sort_keys=True) + "\n", encoding="utf-8")
    candidate_receipt_sha256 = hashlib.sha256(candidate_receipt_path.read_bytes()).hexdigest()
    raw_evidence: list[dict[str, object]] = []
    scheduled_proof = {
        "schema_version": 1,
        "authority": {"kind": "state", "code": "WA"},
        "execution_plan_id": _REGIONAL_PROFILE.execution_plan.plan_id,
        "execution_plan_sha256": canonical_sha256(_REGIONAL_PROFILE.execution_plan.model_dump(mode="json")),
        "execution_mode": "scheduled",
        "observed_after": "2026-08-30T10:00:00Z",
        "observed_plan_row_count": 4,
        "runner_results": [{"job_key": job_key, "status": "success", "metadata_updates": 1} for job_key in job_keys],
        "refresh_runs": [
            {
                "refresh_run_id": f"00000000-0000-4000-8000-{index:012d}",
                "job_key": job_key,
                "data_source_names": [source_name],
                "execution_origin": "scheduled",
                "pull_status": "success",
                "metadata_updates": 1,
                "started_at": f"2026-08-30T10:0{index}:30Z",
                "completed_at": completed,
            }
            for index, (job_key, source_name, completed) in enumerate(
                zip(job_keys, source_names, completed_at, strict=True),
                start=1,
            )
        ],
        "data_sources": [],
    }
    scheduled_proof_path = tmp_path / "scheduled-authority-ledger-proof.json"
    scheduled_proof_path.write_text(
        json.dumps(scheduled_proof, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    scheduled_receipt = {
        "schema_version": 1,
        "observed_after": "2026-08-30T10:00:00Z",
        "observed_at": "2026-08-30T10:11:03Z",
        "authority": {"kind": "state", "code": "WA"},
        "app": _REGIONAL_PROFILE.app,
        "machine_id": "080d391a2ed098",
        "machine_name": _REGIONAL_PROFILE.machine.name,
        "machine_created_at": "2026-08-30T10:00:00Z",
        "profile_id": _REGIONAL_PROFILE.profile_id,
        "profile_file_sha256": hashlib.sha256(_REGIONAL_PROFILE_PATH.read_bytes()).hexdigest(),
        "candidate_receipt_file_sha256": candidate_receipt_sha256,
        "candidate_source_git_sha": candidate_source_git_sha,
        "candidate_tree_git_sha": candidate_tree_git_sha,
        "qualified_image": qualified_image,
        "execution_plan_id": _REGIONAL_PROFILE.execution_plan.plan_id,
        "execution_plan_sha256": canonical_sha256(_REGIONAL_PROFILE.execution_plan.model_dump(mode="json")),
        "machine_config_sha256": _REGIONAL_PROFILE.machine.config_sha256,
        "authority_ledger_proof_sha256": canonical_sha256(scheduled_proof),
        "start_event": {
            "source": "scheduler",
            "machine_id": "080d391a2ed098",
            "occurred_at": "2026-08-30T10:01:00Z",
        },
        "terminal_event": {
            "state": "stopped",
            "exit_code": 0,
            "machine_id": "080d391a2ed098",
            "occurred_at": "2026-08-30T10:10:00Z",
        },
        "database": {"host": "civibus-db.internal", "port": 5432, "name": "civibus"},
        "quiescence": {
            "running_refresh_rows": 0,
            "active_refresh_backends": 0,
            "long_idle_transactions": 0,
            "ungranted_locks": 0,
        },
        "data_sources": [
            {
                "domain": "campaign_finance",
                "jurisdiction": "state/WA",
                "name": source_name,
                "baseline_last_pull_at": "2026-08-29T10:00:00Z",
                "post_last_pull_at": completed,
                "post_last_pull_status": "success",
            }
            for source_name, completed in zip(source_names, completed_at, strict=True)
        ],
        "raw_evidence": raw_evidence,
    }
    raw_payloads = {
        "fly_app_status": {
            "schema_version": 1,
            "captured_at": "2026-08-30T10:11:01Z",
            "app": scheduled_receipt["app"],
            "machine_ids": [scheduled_receipt["machine_id"]],
        },
        "fly_machine_status": {
            "schema_version": 1,
            "captured_at": "2026-08-30T10:11:02Z",
            "app": scheduled_receipt["app"],
            "machine_id": scheduled_receipt["machine_id"],
            "machine_name": scheduled_receipt["machine_name"],
            "image": qualified_image,
            "machine_config_sha256": scheduled_receipt["machine_config_sha256"],
            "created_at": scheduled_receipt["machine_created_at"],
            "events": [
                {
                    "type": "start",
                    "source": scheduled_receipt["start_event"]["source"],
                    "occurred_at": scheduled_receipt["start_event"]["occurred_at"],
                },
                {
                    "type": "stop",
                    "state": scheduled_receipt["terminal_event"]["state"],
                    "exit_code": scheduled_receipt["terminal_event"]["exit_code"],
                    "occurred_at": scheduled_receipt["terminal_event"]["occurred_at"],
                },
            ],
        },
        "database_observation": {
            "schema_version": 1,
            "captured_at": "2026-08-30T10:11:03Z",
            "machine_id": scheduled_receipt["machine_id"],
            "authority": scheduled_receipt["authority"],
            "execution_plan_id": scheduled_receipt["execution_plan_id"],
            "database": scheduled_receipt["database"],
            "runner_results": scheduled_proof["runner_results"],
            "refresh_runs": scheduled_proof["refresh_runs"],
            "data_sources": scheduled_receipt["data_sources"],
            "quiescence": scheduled_receipt["quiescence"],
        },
    }
    for kind, raw_payload in raw_payloads.items():
        raw_path = tmp_path / f"scheduled-{kind}.json"
        raw_path.write_text(json.dumps(raw_payload, sort_keys=True) + "\n", encoding="utf-8")
        raw_evidence.append(
            {
                "kind": kind,
                "path": referenced_path(raw_path),
                "sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
                "captured_at": raw_payload["captured_at"],
            }
        )
    scheduled_receipt_path = tmp_path / "scheduled-observation-receipt.json"
    scheduled_receipt_path.write_text(
        json.dumps(scheduled_receipt, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    canary_refresh_run_id = "10000000-0000-4000-8000-000000000001"
    canary_ledger = {
        "schema_version": 1,
        "authority": {"kind": "state", "code": "WA"},
        "execution_plan_id": _REGIONAL_PROFILE.execution_plan.plan_id,
        "execution_plan_sha256": canonical_sha256(_REGIONAL_PROFILE.execution_plan.model_dump(mode="json")),
        "execution_mode": "canary",
        "observed_after": "2026-08-29T10:00:00Z",
        "observed_plan_row_count": 1,
        "runner_results": [{"job_key": job_keys[0], "status": "success", "metadata_updates": 1}],
        "refresh_runs": [
            {
                "refresh_run_id": canary_refresh_run_id,
                "job_key": job_keys[0],
                "data_source_names": [source_names[0]],
                "execution_origin": "operator_attended",
                "pull_status": "success",
                "metadata_updates": 1,
                "started_at": "2026-08-29T10:01:00Z",
                "completed_at": "2026-08-29T10:02:00Z",
            }
        ],
        "data_sources": [
            {
                "domain": "campaign_finance",
                "jurisdiction": "state/WA",
                "name": source_names[0],
                "baseline_last_pull_at": "2026-08-28T10:02:00Z",
                "post_last_pull_at": "2026-08-29T10:02:00Z",
                "post_last_pull_status": "success",
            }
        ],
    }

    def write_evidence(name: str, payload: object) -> Path:
        path = tmp_path / name
        path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        return path

    canary_ledger_path = write_evidence("canary-authority-ledger-proof.json", canary_ledger)
    terminal_machine_path = write_evidence(
        "canary-terminal-machine.json",
        {
            "schema_version": 1,
            "app": _REGIONAL_PROFILE.app,
            "machine_id": "canary080d391a2ed098",
            "machine_name": _REGIONAL_PROFILE.machine.name,
            "image": qualified_image,
            "machine_config_sha256": _REGIONAL_PROFILE.machine.config_sha256,
            "state": "stopped",
            "exit_code": 0,
            "occurred_at": "2026-08-29T10:03:00Z",
            "captured_at": "2026-08-29T10:03:10Z",
        },
    )
    database_postcondition_path = write_evidence(
        "canary-database-postcondition.json",
        {
            "schema_version": 1,
            "app": _REGIONAL_PROFILE.app,
            "machine_id": "canary080d391a2ed098",
            "authority": "state/WA",
            "execution_plan": _REGIONAL_PROFILE.execution_plan.plan_id,
            "refresh_run_id": canary_refresh_run_id,
            "job_key": job_keys[0],
            "execution_origin": "operator_attended",
            "pull_status": "success",
            "completed_at": "2026-08-29T10:02:00Z",
            "metadata_updates": 1,
            "running_refresh_rows": 0,
            "active_refresh_backends": 0,
            "long_idle_transactions": 0,
            "ungranted_locks": 0,
            "database": {"host": "civibus-db.internal", "port": 5432, "name": "civibus"},
        },
    )
    invariance_paths: dict[str, Path] = {}
    invariance_identity_sha256: dict[str, str] = {}
    database_identity = {"host": "civibus-db.internal", "port": 5432, "name": "civibus"}
    profile_file_sha256 = hashlib.sha256(_REGIONAL_PROFILE_PATH.read_bytes()).hexdigest()
    for scope, owner, content_sha256 in (
        ("federal", "campaign_finance.federal", "d" * 64),
        ("public", "campaign_finance.public", "e" * 64),
    ):
        records = [
            {
                "owner": owner,
                "identity": f"{scope}/baseline",
                "row_count": 4,
                "content_sha256": content_sha256,
            }
        ]
        common_payload = {
            "schema_version": 2,
            "producer": "regional_lifecycle_invariance_capture",
            "scope": scope,
            "canonical_receipt_git_sha": _REGIONAL_PROFILE.canonical_source.receipt_git_sha,
            "canonical_source_git_sha": _REGIONAL_PROFILE.canonical_source.source_git_sha,
            "canonical_tree_git_sha": _REGIONAL_PROFILE.canonical_source.tree_git_sha,
            "source_revision": candidate_source_git_sha,
            "source_tree_git_sha": candidate_tree_git_sha,
            "authority": {"kind": "state", "code": "WA"},
            "execution_plan": _REGIONAL_PROFILE.execution_plan.plan_id,
            "job_key": job_keys[0],
            "execution_origin": "operator_attended",
            "profile_file_sha256": profile_file_sha256,
            "candidate_receipt_file_sha256": candidate_receipt_sha256,
            "qualified_image": qualified_image,
            "app": _REGIONAL_PROFILE.app,
            "machine_id": "canary080d391a2ed098",
            "machine_name": _REGIONAL_PROFILE.machine.name,
            "machine_config_sha256": _REGIONAL_PROFILE.machine.config_sha256,
            "database": database_identity,
            "api_revision": candidate_source_git_sha,
            "web_revision": candidate_source_git_sha,
            "records": records,
        }
        identity_sha256 = canonical_sha256(common_payload)
        invariance_identity_sha256[scope] = identity_sha256
        invariance_paths[f"{scope}_before"] = write_evidence(
            f"canary-{scope}-before.json",
            {
                **common_payload,
                "stage": "before",
                "captured_at": "2026-08-29T10:00:30Z",
                "identity_sha256": identity_sha256,
            },
        )
        invariance_paths[f"{scope}_after"] = write_evidence(
            f"canary-{scope}-after.json",
            {
                **common_payload,
                "stage": "after",
                "captured_at": "2026-08-29T10:04:00Z",
                "identity_sha256": identity_sha256,
            },
        )
    rollback_app_inventory_before_path = write_evidence(
        "canary-rollback-apps-before.json",
        [{"Name": _REGIONAL_PROFILE.app, "ID": _REGIONAL_PROFILE.app}],
    )
    rollback_machine_inventory_before_path = write_evidence(
        "canary-rollback-machines-before.json",
        [
            {
                "id": "canary080d391a2ed098",
                "name": _REGIONAL_PROFILE.machine.name,
                "region": _REGIONAL_PROFILE.machine.region,
                "state": "stopped",
            }
        ],
    )
    rollback_volume_inventory_before_path = write_evidence("canary-rollback-volumes-before.json", [])
    rollback_app_inventory_path = write_evidence(
        "canary-rollback-apps.json",
        [{"Name": "civibus-api", "ID": "unrelated-api"}],
    )
    rollback_machine_inventory_path = write_evidence("canary-rollback-machines.json", [])
    rollback_volume_inventory_path = write_evidence("canary-rollback-volumes.json", [])
    marker_kinds = (
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
    marker_references = []
    for marker_kind in marker_kinds:
        marker_payload = {
            "schema_version": 2,
            "app": _REGIONAL_PROFILE.app,
            "authority": "state/WA",
            "execution_plan": _REGIONAL_PROFILE.execution_plan.plan_id,
            "kind": marker_kind,
            "machine_id": (
                None
                if marker_kind in {"regional_create_ownership", "regional_rollback_attempt"}
                else "canary080d391a2ed098"
            ),
            "machine_name": _REGIONAL_PROFILE.machine.name,
            "profile_file_sha256": profile_file_sha256,
            "candidate_receipt_file_sha256": candidate_receipt_sha256,
        }
        if marker_kind == "regional_start_attempt":
            marker_payload.update(
                schema_version=3,
                invariance_admission={
                    "admitted_at": "2026-08-29T10:00:45Z",
                    "max_age_seconds": 600,
                    "future_skew_seconds": 60,
                    "federal_before": {
                        "snapshot_sha256": hashlib.sha256(invariance_paths["federal_before"].read_bytes()).hexdigest(),
                        "identity_sha256": invariance_identity_sha256["federal"],
                    },
                    "public_before": {
                        "snapshot_sha256": hashlib.sha256(invariance_paths["public_before"].read_bytes()).hexdigest(),
                        "identity_sha256": invariance_identity_sha256["public"],
                    },
                },
            )
        marker_path = write_evidence(
            f"canary-marker-{marker_kind}.json",
            marker_payload,
        )
        marker_references.append(
            {
                "kind": marker_kind,
                "path": referenced_path(marker_path),
                "sha256": hashlib.sha256(marker_path.read_bytes()).hexdigest(),
            }
        )

    def reference(path: Path) -> dict[str, str]:
        return {
            "path": referenced_path(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }

    canary_artifact = {
        "schema_version": 1,
        "observed_at": "2026-08-29T10:10:00Z",
        "profile_file_sha256": profile_file_sha256,
        "candidate_receipt": reference(candidate_receipt_path),
        "candidate_source_git_sha": candidate_source_git_sha,
        "candidate_tree_git_sha": candidate_tree_git_sha,
        "qualified_image": qualified_image,
        "authority_ledger_proof": reference(canary_ledger_path),
        "app": _REGIONAL_PROFILE.app,
        "machine_id": "canary080d391a2ed098",
        "machine_name": _REGIONAL_PROFILE.machine.name,
        "machine_config_sha256": _REGIONAL_PROFILE.machine.config_sha256,
        "authority": {"kind": "state", "code": "WA"},
        "execution_plan_id": _REGIONAL_PROFILE.execution_plan.plan_id,
        "job_key": job_keys[0],
        "refresh_run_id": canary_refresh_run_id,
        "execution_origin": "operator_attended",
        "terminal_event": {
            "state": "stopped",
            "exit_code": 0,
            "machine_id": "canary080d391a2ed098",
            "occurred_at": "2026-08-29T10:03:00Z",
        },
        "database": {"host": "civibus-db.internal", "port": 5432, "name": "civibus"},
        "quiescence": {
            "running_refresh_rows": 0,
            "active_refresh_backends": 0,
            "long_idle_transactions": 0,
            "ungranted_locks": 0,
        },
        "terminal_machine_evidence": reference(terminal_machine_path),
        "database_postcondition": reference(database_postcondition_path),
        "federal_invariance_before": reference(invariance_paths["federal_before"]),
        "federal_invariance_after": reference(invariance_paths["federal_after"]),
        "public_invariance_before": reference(invariance_paths["public_before"]),
        "public_invariance_after": reference(invariance_paths["public_after"]),
        "rollback_app_inventory_before": reference(rollback_app_inventory_before_path),
        "rollback_machine_inventory_before": reference(rollback_machine_inventory_before_path),
        "rollback_volume_inventory_before": reference(rollback_volume_inventory_before_path),
        "rollback_app_inventory": reference(rollback_app_inventory_path),
        "rollback_machine_inventory": reference(rollback_machine_inventory_path),
        "rollback_volume_inventory": reference(rollback_volume_inventory_path),
        "lifecycle_markers": marker_references,
    }

    surface_ids_and_paths = (
        ("home_surface", "/"),
        ("search_surface", "/search?q=ossoff"),
        ("donor_search_surface", "/donors?q=smith&by=name"),
        ("congress_surface", "/congress"),
        ("methodology_surface", "/methodology"),
        ("developers_surface", "/developers"),
        ("candidates_surface", "/candidates"),
        ("committees_surface", "/committees"),
        ("committee_detail_surface", "/committee/jon-ossoff-for-senate"),
        ("compare_surface", "/compare"),
        ("calendar_surface", "/calendar"),
        ("coverage_surface", "/coverage"),
        ("data_sources_surface", "/data-sources"),
        ("about_surface", "/about"),
        ("contact_surface", "/contact"),
        ("privacy_surface", "/privacy"),
        ("sitemap_index_surface", "/sitemap.xml"),
        ("person_detail_surface", "/person/00000000-0000-4000-8000-000000000001"),
    )
    raw_api_parity_path = write_evidence(
        "surface-parity-raw-api.json",
        {
            "schema_version": 1,
            "captured_at": "2026-08-30T11:57:00Z",
            "source_revision": candidate_source_git_sha,
            "api_revision": candidate_source_git_sha,
            "web_revision": candidate_source_git_sha,
            "candidate_receipt_file_sha256": candidate_receipt_sha256,
            "candidate_tree_git_sha": candidate_tree_git_sha,
            "qualified_image": qualified_image,
            "promotion_bundle_sha256": "f" * 64,
            "filing_authority": {"kind": "state", "code": "WA"},
            "source_identities": source_identities,
            "health_status": "healthy",
            "content_health_status": "healthy",
            "surface_parity_ok": True,
            "federal_identity_sha256": invariance_identity_sha256["federal"],
            "regional_navigation_routes": [
                "/state/WA",
                "/state/WA/municipality/seattle",
                "/state/NY/municipality/new-york-city",
            ],
            "washington_specimens": source_names,
            "surfaces": [
                {
                    "surface_id": surface_id,
                    "path": path,
                    "http_status": 200,
                    "content_sha256": hashlib.sha256(path.encode()).hexdigest(),
                }
                for surface_id, path in surface_ids_and_paths
            ],
        },
    )
    raw_browser_parity_path = write_evidence(
        "surface-parity-raw-browser.json",
        {
            "schema_version": 1,
            "captured_at": "2026-08-30T11:58:00Z",
            "source_revision": candidate_source_git_sha,
            "api_revision": candidate_source_git_sha,
            "web_revision": candidate_source_git_sha,
            "candidate_receipt_file_sha256": candidate_receipt_sha256,
            "candidate_tree_git_sha": candidate_tree_git_sha,
            "qualified_image": qualified_image,
            "promotion_bundle_sha256": "f" * 64,
            "filing_authority": {"kind": "state", "code": "WA"},
            "federal_identity_sha256": invariance_identity_sha256["federal"],
            "routes": [
                {
                    "path": "/state/WA",
                    "http_status": 200,
                    "heading": "Washington",
                    "campaign_finance_status": "available",
                    "authority_identity": "state/WA",
                },
                {
                    "path": "/state/WA/municipality/seattle",
                    "http_status": 200,
                    "heading": "Seattle",
                    "campaign_finance_status": "inherited",
                    "authority_identity": "state/WA",
                },
                {
                    "path": "/state/NY/municipality/new-york-city",
                    "http_status": 200,
                    "heading": "New York City",
                    "campaign_finance_status": "direct",
                    "authority_identity": "named_other/NY_NEW_YORK",
                },
            ],
            "washington_specimens": source_names,
        },
    )

    artifacts: dict[str, object] = {
        "canary_ledger": canary_artifact,
        "scheduled_recurrence": {
            "schema_version": 1,
            "authority_ledger_proof_path": referenced_path(scheduled_proof_path),
            "authority_ledger_proof_sha256": hashlib.sha256(scheduled_proof_path.read_bytes()).hexdigest(),
            "observation_receipt_path": referenced_path(scheduled_receipt_path),
            "observation_receipt_sha256": hashlib.sha256(scheduled_receipt_path.read_bytes()).hexdigest(),
            "canary_promotion_artifact_sha256": hashlib.sha256(
                (json.dumps(canary_artifact, sort_keys=True) + "\n").encode()
            ).hexdigest(),
        },
        "filing_authority": {
            "schema_version": 1,
            "geographic_subject": {"kind": "state", "code": "WA"},
            "filing_authority": {"kind": "state", "code": "WA"},
            "authority_relation": "independent",
            "aggregation_disposition": "not_applicable",
        },
        "provenance": {
            "schema_version": 1,
            "filing_authority": {"kind": "state", "code": "WA"},
            "provenance_scope": "state/WA",
            "source_identities": source_identities,
        },
        "keel": {
            "schema_version": 1,
            "filing_authority": {"kind": "state", "code": "WA"},
            "source_identities": source_identities,
            "validation_status": "pass",
            "implementation_maturity": "live_proven",
            "operational_maturity": "runner_wired",
        },
        "serving_deploy": {
            "schema_version": 1,
            "filing_authority": {"kind": "state", "code": "WA"},
            "source_identities": source_identities,
            "candidate_receipt_file_sha256": candidate_receipt_sha256,
            "candidate_source_git_sha": candidate_source_git_sha,
            "candidate_tree_git_sha": candidate_tree_git_sha,
            "qualified_image": qualified_image,
            "source_revision": candidate_source_git_sha,
            "api_revision": candidate_source_git_sha,
            "web_revision": candidate_source_git_sha,
        },
        "surface_parity": {
            "schema_version": 1,
            "observed_at": "2026-08-30T11:58:00Z",
            "candidate_receipt_file_sha256": candidate_receipt_sha256,
            "candidate_tree_git_sha": candidate_tree_git_sha,
            "qualified_image": qualified_image,
            "promotion_bundle_sha256": "f" * 64,
            "source_revision": candidate_source_git_sha,
            "api_revision": candidate_source_git_sha,
            "web_revision": candidate_source_git_sha,
            "raw_api_evidence": reference(raw_api_parity_path),
            "raw_browser_evidence": reference(raw_browser_parity_path),
        },
    }
    canonical_evidence = []
    for kind, artifact in artifacts.items():
        artifact_path = tmp_path / f"{kind}.json"
        artifact_path.write_text(json.dumps(artifact, sort_keys=True) + "\n", encoding="utf-8")
        canonical_evidence.append(
            {
                "kind": kind,
                "path": referenced_path(artifact_path),
                "sha256": hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
            }
        )
    return {
        "schema_version": 1,
        "issued_at": "2026-08-30T12:00:00Z",
        "jurisdiction_code": "WA",
        "geographic_subject": {"kind": "state", "code": "WA"},
        "filing_authority": {"kind": "state", "code": "WA"},
        "authority_relation": "independent",
        "aggregation_disposition": "not_applicable",
        "provenance_scope": "state/WA",
        "promotion_evidence": {
            "authority_identity": "state/WA",
            "authority_relation": "independent",
            "aggregation_disposition": "not_applicable",
            "expected_source_identities": source_identities,
            "source_evidence": [
                {
                    "source_identity": source_identity,
                    "freshness_status": "fresh",
                    "observed_at": observed_at,
                }
                for source_identity, observed_at in zip(source_identities, completed_at, strict=True)
            ],
            "recurrence_evidence": [
                {
                    "source_identity": source_identity,
                    "pull_status": "success",
                    "execution_origin": "scheduled",
                    "completed_at": observed_at,
                }
                for source_identity, observed_at in zip(source_identities, completed_at, strict=True)
            ],
            "provenance_source_identities": source_identities,
            "keel_source_identities": source_identities,
            "deployed_source_identities": source_identities,
            "source_revision": "a" * 40,
            "api_revision": "a" * 40,
            "web_revision": "a" * 40,
        },
        "canonical_evidence": canonical_evidence,
    }


def _rewrite_promotion_artifact(
    payload: dict[str, object],
    kind: str,
    mutation: object,
) -> None:
    artifact = next(item for item in payload["canonical_evidence"] if item["kind"] == kind)  # type: ignore[index]
    path = Path(artifact["path"])
    if callable(mutation):
        artifact_payload = json.loads(path.read_text(encoding="utf-8"))
        mutation(artifact_payload)
        path.write_text(json.dumps(artifact_payload, sort_keys=True) + "\n", encoding="utf-8")
    else:
        path.write_text(str(mutation), encoding="utf-8")
    artifact["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()


def _canary_artifact_payload(
    payload: dict[str, object],
) -> tuple[dict[str, object], Path, dict[str, object]]:
    artifact = next(
        item
        for item in payload["canonical_evidence"]
        if item["kind"] == "canary_ledger"  # type: ignore[index]
    )
    path = Path(artifact["path"])
    return artifact, path, json.loads(path.read_text(encoding="utf-8"))


def _write_canary_artifact(
    payload: dict[str, object],
    artifact: dict[str, object],
    path: Path,
    canary: dict[str, object],
) -> None:
    path.write_text(json.dumps(canary, sort_keys=True) + "\n", encoding="utf-8")
    artifact["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    scheduled_artifact = next(
        item
        for item in payload["canonical_evidence"]
        if item["kind"] == "scheduled_recurrence"  # type: ignore[index]
    )
    scheduled_path = Path(scheduled_artifact["path"])
    scheduled = json.loads(scheduled_path.read_text(encoding="utf-8"))
    scheduled["canary_promotion_artifact_sha256"] = artifact["sha256"]
    scheduled_path.write_text(json.dumps(scheduled, sort_keys=True) + "\n", encoding="utf-8")
    scheduled_artifact["sha256"] = hashlib.sha256(scheduled_path.read_bytes()).hexdigest()


def _rewrite_canary_reference(
    payload: dict[str, object],
    reference_name: str,
    mutation: Callable[[object], None],
) -> None:
    artifact, artifact_path, canary = _canary_artifact_payload(payload)
    reference = canary[reference_name]
    referenced_path = Path(reference["path"])
    referenced_payload = json.loads(referenced_path.read_text(encoding="utf-8"))
    mutation(referenced_payload)
    referenced_path.write_text(json.dumps(referenced_payload, sort_keys=True) + "\n", encoding="utf-8")
    reference["sha256"] = hashlib.sha256(referenced_path.read_bytes()).hexdigest()
    _write_canary_artifact(payload, artifact, artifact_path, canary)


def _rewrite_canary_marker(
    payload: dict[str, object],
    marker_kind: str,
    mutation: Callable[[dict[str, object]], None],
) -> None:
    artifact, artifact_path, canary = _canary_artifact_payload(payload)
    reference = next(marker for marker in canary["lifecycle_markers"] if marker["kind"] == marker_kind)
    marker_path = Path(reference["path"])
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    mutation(marker)
    marker_path.write_text(json.dumps(marker, sort_keys=True) + "\n", encoding="utf-8")
    reference["sha256"] = hashlib.sha256(marker_path.read_bytes()).hexdigest()
    _write_canary_artifact(payload, artifact, artifact_path, canary)


def _rewrite_surface_parity_reference(
    payload: dict[str, object],
    reference_name: str,
    mutation: Callable[[dict[str, object]], None],
) -> None:
    artifact = next(
        item
        for item in payload["canonical_evidence"]
        if item["kind"] == "surface_parity"  # type: ignore[index]
    )
    parity_path = Path(artifact["path"])
    parity = json.loads(parity_path.read_text(encoding="utf-8"))
    reference = parity[reference_name]
    raw_path = Path(reference["path"])
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    mutation(raw)
    raw_path.write_text(json.dumps(raw, sort_keys=True) + "\n", encoding="utf-8")
    reference["sha256"] = hashlib.sha256(raw_path.read_bytes()).hexdigest()
    parity_path.write_text(json.dumps(parity, sort_keys=True) + "\n", encoding="utf-8")
    artifact["sha256"] = hashlib.sha256(parity_path.read_bytes()).hexdigest()


def test_canary_invariance_refuses_matching_self_asserted_identity_digests(tmp_path: Path) -> None:
    payload = _promotion_receipt_payload(tmp_path)
    for reference_name in ("federal_invariance_before", "federal_invariance_after"):
        _rewrite_canary_reference(
            payload,
            reference_name,
            lambda evidence: evidence.update(identity_sha256="0" * 64),
        )
    receipt_path = tmp_path / "authority-promotion-receipt.json"
    receipt_path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="invariance identity digest mismatch"):
        load_authority_promotion_receipt(receipt_path)


def test_invariance_admission_freshness_boundaries_are_inclusive_and_exact() -> None:
    admitted_at = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)

    assert invariance_capture_time_is_fresh(
        admitted_at - timedelta(seconds=600),
        admitted_at=admitted_at,
    )
    assert invariance_capture_time_is_fresh(
        admitted_at + timedelta(seconds=60),
        admitted_at=admitted_at,
    )
    assert not invariance_capture_time_is_fresh(
        admitted_at - timedelta(seconds=600, microseconds=1),
        admitted_at=admitted_at,
    )
    assert not invariance_capture_time_is_fresh(
        admitted_at + timedelta(seconds=60, microseconds=1),
        admitted_at=admitted_at,
    )


def test_lifecycle_marker_schema_three_is_reserved_for_bound_start_admission() -> None:
    common = {
        "app": _REGIONAL_PROFILE.app,
        "authority": "state/WA",
        "execution_plan": _REGIONAL_PROFILE.execution_plan.plan_id,
        "machine_id": "080d391a2ed098",
        "machine_name": _REGIONAL_PROFILE.machine.name,
        "profile_file_sha256": "a" * 64,
        "candidate_receipt_file_sha256": "b" * 64,
    }
    with pytest.raises(ValidationError, match="admission-bound start attempt"):
        RawRegionalLifecycleMarker.model_validate({**common, "schema_version": 3, "kind": "regional_start_attempt"})
    with pytest.raises(ValidationError, match="admission-bound start attempt"):
        RawRegionalLifecycleMarker.model_validate({**common, "schema_version": 3, "kind": "regional_stopped_provision"})


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda marker: (marker.__setitem__("schema_version", 2), marker.pop("invariance_admission")),
            "start-admission identity or time window mismatch",
        ),
        (
            lambda marker: marker["invariance_admission"].__setitem__("admitted_at", "2026-08-29T11:00:00Z"),
            "start-admission identity or time window mismatch",
        ),
        (
            lambda marker: marker["invariance_admission"].__setitem__("admitted_at", "2026-08-29T09:00:00Z"),
            "start-admission identity or time window mismatch",
        ),
    ],
    ids=("missing-binding", "future", "replayed"),
)
def test_canary_promotion_refuses_missing_future_or_replayed_start_admission(
    tmp_path: Path,
    mutation: Callable[[dict[str, object]], object],
    message: str,
) -> None:
    payload = _promotion_receipt_payload(tmp_path)
    _rewrite_canary_marker(payload, "regional_start_attempt", mutation)
    receipt_path = tmp_path / "authority-promotion-receipt.json"
    receipt_path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_authority_promotion_receipt(receipt_path)


def test_canary_promotion_refuses_correctly_rehashed_altered_admitted_before_bytes(
    tmp_path: Path,
) -> None:
    payload = _promotion_receipt_payload(tmp_path)
    _rewrite_canary_reference(
        payload,
        "federal_invariance_before",
        lambda evidence: evidence.update(captured_at="2026-08-29T10:00:31Z"),
    )
    receipt_path = tmp_path / "authority-promotion-receipt.json"
    receipt_path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="canonical canary federal invariance mismatch"):
        load_authority_promotion_receipt(receipt_path)


def test_raw_invariance_snapshot_requires_canonical_capture_provenance() -> None:
    payload = {
        "schema_version": 2,
        "producer": "regional_lifecycle_invariance_capture",
        "stage": "before",
        "scope": "federal",
        "captured_at": "2026-08-30T10:00:30Z",
        "canonical_receipt_git_sha": _REGIONAL_PROFILE.canonical_source.receipt_git_sha,
        "canonical_source_git_sha": _REGIONAL_PROFILE.canonical_source.source_git_sha,
        "canonical_tree_git_sha": _REGIONAL_PROFILE.canonical_source.tree_git_sha,
        "source_revision": "a" * 40,
        "source_tree_git_sha": "b" * 40,
        "authority": {"kind": "state", "code": "WA"},
        "execution_plan": _REGIONAL_PROFILE.execution_plan.plan_id,
        "job_key": _REGIONAL_PROFILE.execution_plan.canary.job_keys[0],
        "execution_origin": "operator_attended",
        "profile_file_sha256": hashlib.sha256(_REGIONAL_PROFILE_PATH.read_bytes()).hexdigest(),
        "candidate_receipt_file_sha256": "c" * 64,
        "qualified_image": "registry.fly.io/civibus-refresh:wa-r1@sha256:" + "d" * 64,
        "app": _REGIONAL_PROFILE.app,
        "machine_id": "080d391a2ed098",
        "machine_name": _REGIONAL_PROFILE.machine.name,
        "machine_config_sha256": _REGIONAL_PROFILE.machine.config_sha256,
        "database": {"host": "civibus-db.internal", "port": 5432, "name": "civibus"},
        "api_revision": "e" * 40,
        "web_revision": "e" * 40,
        "records": [
            {
                "owner": "infra.fly.federal_machine_inventory",
                "identity": "civibus-refresh/859e0da479e678",
                "row_count": 1,
                "content_sha256": "f" * 64,
            }
        ],
    }
    payload["identity_sha256"] = canonical_sha256(
        {key: value for key, value in payload.items() if key not in {"captured_at", "stage"}}
    )

    snapshot = RawInvarianceSnapshot.model_validate(payload)

    assert snapshot.stage == "before"
    assert snapshot.producer == "regional_lifecycle_invariance_capture"
    legacy = {
        "schema_version": 1,
        "scope": "federal",
        "captured_at": "2026-08-30T10:00:30Z",
        "source_revision": "a" * 40,
        "database": {"host": "civibus-db.internal", "port": 5432, "name": "civibus"},
        "records": payload["records"],
    }
    legacy["identity_sha256"] = canonical_sha256({key: value for key, value in legacy.items() if key != "captured_at"})
    with pytest.raises(ValidationError):
        RawInvarianceSnapshot.model_validate(legacy)


def test_surface_parity_artifact_refuses_timeless_self_asserted_pass() -> None:
    with pytest.raises(ValueError, match="raw API and browser evidence"):
        SurfaceParityPromotionArtifact.model_validate(
            {
                "schema_version": 1,
                "source_revision": "a" * 40,
                "api_revision": "a" * 40,
                "web_revision": "a" * 40,
                "status": "pass",
            }
        )


def test_lifecycle_cli_derives_surface_parity_artifact_from_raw_api_and_browser_owners(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = _promotion_receipt_payload(tmp_path)
    parity_reference = next(
        reference for reference in payload["canonical_evidence"] if reference["kind"] == "surface_parity"
    )
    parity = json.loads(Path(parity_reference["path"]).read_text(encoding="utf-8"))
    raw_api_path = Path(parity["raw_api_evidence"]["path"])
    raw_browser_path = Path(parity["raw_browser_evidence"]["path"])
    raw_api_path.chmod(0o600)
    raw_browser_path.chmod(0o600)
    output_path = tmp_path / "derived-surface-parity.json"

    assert (
        main(
            [
                "--surface-parity-raw-api-json",
                str(raw_api_path),
                "--surface-parity-raw-browser-json",
                str(raw_browser_path),
                "--surface-parity-output-json",
                str(output_path),
            ]
        )
        == 0
    )
    derived = json.loads(output_path.read_text(encoding="utf-8"))
    assert derived["source_revision"] == "a" * 40
    assert derived["candidate_tree_git_sha"] == "b" * 40
    assert derived["promotion_bundle_sha256"] == "f" * 64
    assert stat.S_IMODE(output_path.stat().st_mode) == 0o600
    assert "Built validated surface parity promotion artifact" in capsys.readouterr().out
    original = output_path.read_bytes()
    assert (
        main(
            [
                "--surface-parity-raw-api-json",
                str(raw_api_path),
                "--surface-parity-raw-browser-json",
                str(raw_browser_path),
                "--surface-parity-output-json",
                str(output_path),
            ]
        )
        == 1
    )
    assert "path already exists" in capsys.readouterr().err
    assert output_path.read_bytes() == original


def test_lifecycle_cli_builds_one_mode_0600_canary_artifact_from_durable_owner_graph(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    payload = _promotion_receipt_payload(source_root)
    canary_reference = next(
        reference for reference in payload["canonical_evidence"] if reference["kind"] == "canary_ledger"
    )
    canary = json.loads(Path(canary_reference["path"]).read_text(encoding="utf-8"))
    evidence_root = tmp_path / "durable"
    evidence_root.mkdir()

    def copy_owner(name: str, source: Path) -> None:
        destination = evidence_root / name
        destination.write_bytes(source.read_bytes())
        destination.chmod(0o600)

    copy_owner("profile.json", _REGIONAL_PROFILE_PATH)
    copy_owner("candidate_receipt.json", Path(canary["candidate_receipt"]["path"]))
    for name, reference_name in (
        ("authority_ledger_proof.json", "authority_ledger_proof"),
        ("terminal_machine.json", "terminal_machine_evidence"),
        ("database_postcondition.json", "database_postcondition"),
        ("federal_invariance_before.json", "federal_invariance_before"),
        ("federal_invariance_after.json", "federal_invariance_after"),
        ("public_invariance_before.json", "public_invariance_before"),
        ("public_invariance_after.json", "public_invariance_after"),
        ("rollback_apps_before.json", "rollback_app_inventory_before"),
        ("rollback_machines_before.json", "rollback_machine_inventory_before"),
        ("rollback_volumes_before.json", "rollback_volume_inventory_before"),
        ("rollback_apps_after.json", "rollback_app_inventory"),
        ("rollback_machines_after.json", "rollback_machine_inventory"),
        ("rollback_volumes_after.json", "rollback_volume_inventory"),
    ):
        copy_owner(name, Path(canary[reference_name]["path"]))
    marker_names = (
        "create_ownership.json",
        "machine_ownership.json",
        "provision.json",
        "start_attempt.json",
        "canary_mode.json",
        "canary_machine_terminal.json",
        "rollback_attempt.json",
        "rollback_stopped.json",
        "rollback_complete.json",
    )
    for name, marker_reference in zip(marker_names, canary["lifecycle_markers"], strict=True):
        copy_owner(name, Path(marker_reference["path"]))

    output_path = evidence_root / "regional_canary_promotion.json"
    assert (
        main(
            [
                "--regional-canary-evidence-directory",
                str(evidence_root),
                "--regional-canary-artifact-output-json",
                str(output_path),
            ]
        )
        == 0
    )

    artifact = json.loads(output_path.read_text(encoding="utf-8"))
    assert artifact["machine_id"] == "canary080d391a2ed098"
    assert artifact["refresh_run_id"] == "10000000-0000-4000-8000-000000000001"
    assert stat.S_IMODE(output_path.stat().st_mode) == 0o600
    assert "Built validated regional canary promotion artifact" in capsys.readouterr().out

    assert (
        main(
            [
                "--regional-canary-artifact-json",
                str(output_path),
                "--regional-canary-profile-json",
                str(evidence_root / "profile.json"),
                "--regional-canary-candidate-receipt-json",
                str(evidence_root / "candidate_receipt.json"),
            ]
        )
        == 0
    )
    candidate_symlink = evidence_root / "candidate-symlink.json"
    candidate_symlink.symlink_to(evidence_root / "candidate_receipt.json")
    assert (
        main(
            [
                "--regional-canary-artifact-json",
                str(output_path),
                "--regional-canary-profile-json",
                str(evidence_root / "profile.json"),
                "--regional-canary-candidate-receipt-json",
                str(candidate_symlink),
            ]
        )
        == 1
    )
    assert "regular non-symlink file" in capsys.readouterr().err
    profile_symlink = evidence_root / "profile-symlink.json"
    profile_symlink.symlink_to(evidence_root / "profile.json")
    assert (
        main(
            [
                "--regional-canary-artifact-json",
                str(output_path),
                "--regional-canary-profile-json",
                str(profile_symlink),
                "--regional-canary-candidate-receipt-json",
                str(evidence_root / "candidate_receipt.json"),
            ]
        )
        == 1
    )
    assert "profile must be a regular non-symlink file" in capsys.readouterr().err


def _rewrite_scheduled_recurrence_output(
    payload: dict[str, object],
    output: str,
    mutation: object,
) -> None:
    artifact = next(
        item
        for item in payload["canonical_evidence"]
        if item["kind"] == "scheduled_recurrence"  # type: ignore[index]
    )
    manifest_path = Path(artifact["path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    output_path = Path(manifest[f"{output}_path"])
    output_payload = json.loads(output_path.read_text(encoding="utf-8"))
    mutation(output_payload)  # type: ignore[operator]
    output_path.write_text(json.dumps(output_payload, sort_keys=True) + "\n", encoding="utf-8")
    manifest[f"{output}_sha256"] = hashlib.sha256(output_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
    artifact["sha256"] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()


def _rewrite_scheduled_raw_evidence(
    payload: dict[str, object],
    kind: str,
    mutation: Callable[[dict[str, object]], None],
) -> None:
    artifact = next(
        item
        for item in payload["canonical_evidence"]
        if item["kind"] == "scheduled_recurrence"  # type: ignore[index]
    )
    manifest_path = Path(artifact["path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    observation_path = Path(manifest["observation_receipt_path"])
    observation = json.loads(observation_path.read_text(encoding="utf-8"))
    reference = next(row for row in observation["raw_evidence"] if row["kind"] == kind)
    raw_path = Path(reference["path"])
    raw_payload = json.loads(raw_path.read_text(encoding="utf-8"))
    mutation(raw_payload)
    raw_path.write_text(json.dumps(raw_payload, sort_keys=True) + "\n", encoding="utf-8")
    reference["sha256"] = hashlib.sha256(raw_path.read_bytes()).hexdigest()
    observation_path.write_text(json.dumps(observation, sort_keys=True) + "\n", encoding="utf-8")
    manifest["observation_receipt_sha256"] = hashlib.sha256(observation_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
    artifact["sha256"] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()


def test_authority_promotion_receipt_loads_exact_hash_bound_green_evidence(tmp_path: Path) -> None:
    payload = _promotion_receipt_payload(tmp_path)
    receipt_path = tmp_path / "authority-promotion-receipt.json"
    receipt_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    receipt = load_authority_promotion_receipt(receipt_path)
    decision = assess_authority_promotion_receipt(
        receipt,
        jurisdiction_code="WA",
        authority_identity="state/WA",
        expected_source_identities=receipt.promotion_evidence.expected_source_identities,
        source_evidence=receipt.promotion_evidence.source_evidence,
        recurrence_evidence=receipt.promotion_evidence.recurrence_evidence,
    )

    assert isinstance(receipt, AuthorityPromotionReceipt)
    assert decision.eligible is True
    assert decision.revision_parity == "match"
    assert decision.refusal_reasons == []


@pytest.mark.parametrize(
    "kind",
    (
        "canary_ledger",
        "scheduled_recurrence",
        "filing_authority",
        "provenance",
        "keel",
        "serving_deploy",
        "surface_parity",
    ),
)
def test_authority_promotion_receipt_refuses_correctly_hashed_wrong_schema_for_every_artifact(
    tmp_path: Path,
    kind: str,
) -> None:
    payload = _promotion_receipt_payload(tmp_path)
    _rewrite_promotion_artifact(payload, kind, "not-json\n")
    receipt_path = tmp_path / "authority-promotion-receipt.json"
    receipt_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match=f"canonical {kind} evidence"):
        load_authority_promotion_receipt(receipt_path)


@pytest.mark.parametrize(
    ("kind", "mutation", "error"),
    [
        (
            "canary_ledger",
            lambda artifact: artifact["authority"].update(code="OR"),
            "canary ledger filing authority",
        ),
        (
            "filing_authority",
            lambda artifact: artifact["filing_authority"].update(code="OR"),
            "filing authority evidence",
        ),
        (
            "provenance",
            lambda artifact: artifact["filing_authority"].update(code="OR"),
            "provenance filing authority",
        ),
        (
            "provenance",
            lambda artifact: artifact.update(provenance_scope="state/OR"),
            "provenance scope",
        ),
        (
            "keel",
            lambda artifact: artifact["filing_authority"].update(code="OR"),
            "Keel evidence",
        ),
        (
            "keel",
            lambda artifact: artifact["source_identities"].reverse(),
            "Keel evidence",
        ),
        (
            "serving_deploy",
            lambda artifact: artifact["filing_authority"].update(code="OR"),
            "serving deploy filing authority",
        ),
        (
            "serving_deploy",
            lambda artifact: artifact.pop("source_revision"),
            "source_revision",
        ),
        (
            "serving_deploy",
            lambda artifact: artifact.update(candidate_receipt_file_sha256="4" * 64),
            "candidate receipt mismatch",
        ),
        (
            "surface_parity",
            lambda artifact: artifact.update(source_revision="b" * 40),
            "source revision",
        ),
        (
            "surface_parity",
            lambda artifact: artifact.update(observed_at="2026-08-30T11:59:30Z"),
            "observation time is not derived",
        ),
    ],
)
def test_authority_promotion_receipt_refuses_correctly_hashed_semantic_artifact_drift(
    tmp_path: Path,
    kind: str,
    mutation: object,
    error: str,
) -> None:
    payload = _promotion_receipt_payload(tmp_path)
    _rewrite_promotion_artifact(payload, kind, mutation)
    receipt_path = tmp_path / "authority-promotion-receipt.json"
    receipt_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match=error):
        load_authority_promotion_receipt(receipt_path)


@pytest.mark.parametrize(
    ("reference_name", "mutation", "error"),
    [
        (
            "raw_api_evidence",
            lambda raw: raw["surfaces"].pop(),
            "exact 18/18 manifest surfaces",
        ),
        (
            "raw_api_evidence",
            lambda raw: raw["surfaces"].reverse(),
            "exact 18/18 manifest surfaces",
        ),
        (
            "raw_api_evidence",
            lambda raw: raw["regional_navigation_routes"].reverse(),
            "regional navigation routes mismatch",
        ),
        (
            "raw_api_evidence",
            lambda raw: raw["washington_specimens"].pop(),
            "Washington specimens mismatch",
        ),
        (
            "raw_api_evidence",
            lambda raw: raw.update(health_status="degraded"),
            "Invalid deployed surface parity raw API evidence",
        ),
        (
            "raw_api_evidence",
            lambda raw: raw.update(surface_parity_ok=False),
            "Invalid deployed surface parity raw API evidence",
        ),
        (
            "raw_api_evidence",
            lambda raw: raw["filing_authority"].update(code="OR"),
            "candidate, image, or authority mismatch",
        ),
        (
            "raw_api_evidence",
            lambda raw: raw.update(source_revision="b" * 40),
            "source revision mismatch",
        ),
        (
            "raw_api_evidence",
            lambda raw: raw.update(candidate_tree_git_sha="c" * 40),
            "candidate, image, or authority mismatch",
        ),
        (
            "raw_api_evidence",
            lambda raw: raw.update(qualified_image="registry.fly.io/foreign@sha256:" + "1" * 64),
            "candidate, image, or authority mismatch",
        ),
        (
            "raw_api_evidence",
            lambda raw: raw.update(promotion_bundle_sha256="1" * 64),
            "promotion bundle mismatch",
        ),
        (
            "raw_api_evidence",
            lambda raw: raw.update(federal_identity_sha256="1" * 64),
            "federal invariance mismatch",
        ),
        (
            "raw_api_evidence",
            lambda raw: raw.update(captured_at="2026-08-30T10:00:00Z"),
            "stale, replayed, or future-dated",
        ),
        (
            "raw_browser_evidence",
            lambda raw: raw["routes"].pop(),
            "browser regional routes mismatch",
        ),
        (
            "raw_browser_evidence",
            lambda raw: raw["routes"][0].update(campaign_finance_status="degraded"),
            "Invalid deployed surface parity raw browser evidence",
        ),
        (
            "raw_browser_evidence",
            lambda raw: raw["routes"][1].update(authority_identity="state/OR"),
            "browser regional routes mismatch",
        ),
        (
            "raw_browser_evidence",
            lambda raw: raw.update(api_revision="b" * 40),
            "source revision mismatch",
        ),
        (
            "raw_browser_evidence",
            lambda raw: raw["washington_specimens"].reverse(),
            "browser Washington specimens mismatch",
        ),
    ],
)
def test_authority_promotion_receipt_refuses_correctly_rehashed_foreign_public_parity_raw_evidence(
    tmp_path: Path,
    reference_name: str,
    mutation: Callable[[dict[str, object]], None],
    error: str,
) -> None:
    payload = _promotion_receipt_payload(tmp_path)
    _rewrite_surface_parity_reference(payload, reference_name, mutation)
    receipt_path = tmp_path / "authority-promotion-receipt.json"
    receipt_path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match=error):
        load_authority_promotion_receipt(receipt_path)


@pytest.mark.parametrize(
    ("reference_name", "mutation", "error"),
    [
        (
            "terminal_machine_evidence",
            lambda evidence: evidence.update(machine_id="foreign-machine"),
            "terminal Machine evidence mismatch",
        ),
        (
            "terminal_machine_evidence",
            lambda evidence: evidence.update(image="registry.fly.io/foreign@sha256:" + "f" * 64),
            "terminal Machine evidence mismatch",
        ),
        (
            "terminal_machine_evidence",
            lambda evidence: evidence.update(state="started"),
            "Invalid canary terminal Machine evidence",
        ),
        (
            "database_postcondition",
            lambda evidence: evidence["database"].update(name="foreign"),
            "database postcondition identity or quiescence mismatch",
        ),
        (
            "database_postcondition",
            lambda evidence: evidence.update(refresh_run_id="20000000-0000-4000-8000-000000000002"),
            "database postcondition identity or quiescence mismatch",
        ),
        (
            "database_postcondition",
            lambda evidence: evidence.update(running_refresh_rows=1),
            "Invalid canary database postcondition",
        ),
        (
            "database_postcondition",
            lambda evidence: evidence.update(active_refresh_backends=1),
            "Invalid canary database postcondition",
        ),
        (
            "database_postcondition",
            lambda evidence: evidence.update(ungranted_locks=1),
            "Invalid canary database postcondition",
        ),
        (
            "database_postcondition",
            lambda evidence: evidence.update(long_idle_transactions=1),
            "Invalid canary database postcondition",
        ),
        (
            "federal_invariance_after",
            lambda evidence: evidence.update(identity_sha256="f" * 64),
            "federal invariance mismatch",
        ),
        (
            "rollback_app_inventory",
            lambda evidence: evidence.append({"Name": _REGIONAL_PROFILE.app, "ID": "foreign-app-id"}),
            "rollback app inventory is nonzero",
        ),
        (
            "rollback_machine_inventory",
            lambda evidence: evidence.append({"id": "canary080d391a2ed098"}),
            "rollback Machine inventory is nonzero",
        ),
        (
            "rollback_volume_inventory",
            lambda evidence: evidence.append({"id": "volume-one"}),
            "rollback volume inventory is nonzero",
        ),
    ],
)
def test_authority_promotion_receipt_refuses_correctly_hashed_foreign_canary_raw_evidence(
    tmp_path: Path,
    reference_name: str,
    mutation: Callable[[object], None],
    error: str,
) -> None:
    payload = _promotion_receipt_payload(tmp_path)
    _rewrite_canary_reference(payload, reference_name, mutation)
    receipt_path = tmp_path / "authority-promotion-receipt.json"
    receipt_path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match=error):
        load_authority_promotion_receipt(receipt_path)


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        (lambda canary: canary.update(observed_at="2026-08-29T10:40:00Z"), "stale or nonterminal"),
        (lambda canary: canary.update(candidate_tree_git_sha="d" * 40), "candidate, receipt, tree, image"),
        (lambda canary: canary.update(machine_id="foreign-machine"), "terminal Machine evidence mismatch"),
        (lambda canary: canary["authority"].update(kind="municipality"), "filing authority mismatch"),
        (lambda canary: canary["lifecycle_markers"].reverse(), "exact ordered lifecycle markers"),
    ],
)
def test_authority_promotion_receipt_refuses_stale_split_typed_or_reordered_canary_evidence(
    tmp_path: Path,
    mutation: Callable[[dict[str, object]], None],
    error: str,
) -> None:
    payload = _promotion_receipt_payload(tmp_path)
    _rewrite_promotion_artifact(payload, "canary_ledger", mutation)
    receipt_path = tmp_path / "authority-promotion-receipt.json"
    receipt_path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match=error):
        load_authority_promotion_receipt(receipt_path)


def test_authority_promotion_receipt_refuses_foreign_lifecycle_marker_and_replayed_attempt(
    tmp_path: Path,
) -> None:
    marker_root = tmp_path / "marker"
    marker_root.mkdir()
    marker_payload = _promotion_receipt_payload(marker_root)
    _rewrite_canary_marker(
        marker_payload,
        "regional_rollback_complete",
        lambda marker: marker.update(machine_id="foreign-machine"),
    )
    marker_receipt = marker_root / "authority-promotion-receipt.json"
    marker_receipt.write_text(json.dumps(marker_payload, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="lifecycle marker identity mismatch"):
        load_authority_promotion_receipt(marker_receipt)

    replay_root = tmp_path / "replay"
    replay_root.mkdir()
    replay_payload = _promotion_receipt_payload(replay_root)
    artifact, artifact_path, canary = _canary_artifact_payload(replay_payload)
    replayed_id = "00000000-0000-4000-8000-000000000001"
    for reference_name in ("authority_ledger_proof", "database_postcondition"):
        reference = canary[reference_name]
        reference_path = Path(reference["path"])
        evidence = json.loads(reference_path.read_text(encoding="utf-8"))
        if reference_name == "authority_ledger_proof":
            evidence["refresh_runs"][0]["refresh_run_id"] = replayed_id
        else:
            evidence["refresh_run_id"] = replayed_id
        reference_path.write_text(json.dumps(evidence, sort_keys=True) + "\n", encoding="utf-8")
        reference["sha256"] = hashlib.sha256(reference_path.read_bytes()).hexdigest()
    canary["refresh_run_id"] = replayed_id
    _write_canary_artifact(replay_payload, artifact, artifact_path, canary)
    replay_receipt = replay_root / "authority-promotion-receipt.json"
    replay_receipt.write_text(json.dumps(replay_payload, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="attempt is replayed"):
        load_authority_promotion_receipt(replay_receipt)


@pytest.mark.parametrize(
    ("output", "mutation", "error"),
    [
        (
            "observation_receipt",
            lambda artifact: artifact["authority"].update(code="OR"),
            "filing authority",
        ),
        (
            "observation_receipt",
            lambda artifact: artifact["data_sources"][0].update(jurisdiction="state/OR"),
            "raw database evidence mismatch",
        ),
        (
            "observation_receipt",
            lambda artifact: artifact["raw_evidence"][0].update(sha256="0" * 64),
            "digest mismatch",
        ),
        (
            "observation_receipt",
            lambda artifact: artifact.update(profile_file_sha256="0" * 64),
            "profile, app, Machine, or plan",
        ),
        (
            "observation_receipt",
            lambda artifact: artifact.update(observed_at="2026-08-30T10:11:30Z"),
            "observation time is not derived",
        ),
        (
            "authority_ledger_proof",
            lambda artifact: artifact["refresh_runs"][-1].update(completed_at="2026-08-30T10:05:01Z"),
            "ledger proof digest mismatch",
        ),
    ],
)
def test_authority_promotion_receipt_refuses_drifted_gate10_proof_or_receipt(
    tmp_path: Path,
    output: str,
    mutation: object,
    error: str,
) -> None:
    payload = _promotion_receipt_payload(tmp_path)
    _rewrite_scheduled_recurrence_output(payload, output, mutation)
    receipt_path = tmp_path / "authority-promotion-receipt.json"
    receipt_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match=error):
        load_authority_promotion_receipt(receipt_path)


@pytest.mark.parametrize(
    ("kind", "mutation", "error"),
    [
        ("fly_app_status", lambda raw: raw.update(app="foreign-app"), "raw app Machine identity mismatch"),
        (
            "fly_machine_status",
            lambda raw: raw.update(image="registry.fly.io/foreign@sha256:" + "f" * 64),
            "raw Fly Machine identity mismatch",
        ),
        (
            "database_observation",
            lambda raw: raw["refresh_runs"][0].update(execution_origin="operator_attended"),
            "raw database evidence mismatch",
        ),
        (
            "database_observation",
            lambda raw: raw["quiescence"].update(active_refresh_backends=1),
            "Invalid canonical scheduled database_observation raw evidence",
        ),
    ],
)
def test_authority_promotion_receipt_refuses_correctly_hashed_foreign_scheduled_raw_evidence(
    tmp_path: Path,
    kind: str,
    mutation: Callable[[dict[str, object]], None],
    error: str,
) -> None:
    payload = _promotion_receipt_payload(tmp_path)
    _rewrite_scheduled_raw_evidence(payload, kind, mutation)
    receipt_path = tmp_path / "authority-promotion-receipt.json"
    receipt_path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match=error):
        load_authority_promotion_receipt(receipt_path)


def test_authority_promotion_receipt_refuses_self_assertions_not_derived_from_artifacts(
    tmp_path: Path,
) -> None:
    payload = _promotion_receipt_payload(tmp_path)
    payload["promotion_evidence"]["source_revision"] = "b" * 40  # type: ignore[index]
    payload["promotion_evidence"]["api_revision"] = "b" * 40  # type: ignore[index]
    payload["promotion_evidence"]["web_revision"] = "b" * 40  # type: ignore[index]
    receipt_path = tmp_path / "authority-promotion-receipt.json"
    receipt_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="not derivable"):
        load_authority_promotion_receipt(receipt_path)


def test_authority_promotion_evidence_carries_the_exact_serving_source_revision() -> None:
    assert "source_revision" in AuthorityPromotionEvidence.model_fields


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        (lambda payload: payload["canonical_evidence"][0].update(sha256="0" * 64), "digest mismatch"),
        (lambda payload: payload["canonical_evidence"].pop(), "exact ordered canonical evidence"),
        (lambda payload: payload["geographic_subject"].update(code="OR"), "geographic subject"),
        (lambda payload: payload.update(provenance_scope="state/OR"), "provenance scope"),
        (
            lambda payload: payload["filing_authority"].update(kind="municipality"),
            "distinct domains to the same typed identity",
        ),
        (
            lambda payload: payload["promotion_evidence"]["source_evidence"][0].update(freshness_status="degraded"),
            "must itself be promotion-eligible",
        ),
        (
            lambda payload: payload["promotion_evidence"].update(web_revision="b" * 40),
            "must itself be promotion-eligible",
        ),
    ],
)
def test_authority_promotion_receipt_refuses_partial_foreign_or_hash_drifted_evidence(
    tmp_path: Path,
    mutation: object,
    error: str,
) -> None:
    payload = _promotion_receipt_payload(tmp_path)
    mutation(payload)  # type: ignore[operator]
    receipt_path = tmp_path / "authority-promotion-receipt.json"
    receipt_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match=error):
        load_authority_promotion_receipt(receipt_path)


def test_authority_promotion_receipt_refuses_runtime_clock_or_recurrence_drift(tmp_path: Path) -> None:
    payload = _promotion_receipt_payload(tmp_path)
    receipt = AuthorityPromotionReceipt.model_validate(payload)
    drifted_identity = receipt.promotion_evidence.expected_source_identities[0]
    drifted_sources = [
        evidence.model_copy(update={"observed_at": "2026-08-30T12:01:00Z"})
        if evidence.source_identity == drifted_identity
        else evidence
        for evidence in receipt.promotion_evidence.source_evidence
    ]

    decision = assess_authority_promotion_receipt(
        receipt,
        jurisdiction_code="WA",
        authority_identity="state/WA",
        expected_source_identities=receipt.promotion_evidence.expected_source_identities,
        source_evidence=drifted_sources,
        recurrence_evidence=receipt.promotion_evidence.recurrence_evidence,
    )

    assert decision.eligible is False
    assert decision.revision_parity == "match"
    assert decision.refusal_reasons == ["Runtime freshness evidence does not exactly match the canonical receipt."]
