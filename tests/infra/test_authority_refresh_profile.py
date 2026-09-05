from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from core.refresh.authority_operations_profile import (
    AuthorityOperationsProfile,
    canonical_sha256,
    expected_image_plan_proof,
    load_authority_operations_profile,
    validate_disjoint_operations_profiles,
)


_REPO_ROOT = Path(__file__).resolve().parents[2]
_PROFILE_PATH = _REPO_ROOT / "infra/fly/regional_refresh_machine_profile.json"


def _synthetic_sf_profile() -> AuthorityOperationsProfile:
    payload = deepcopy(load_authority_operations_profile(_PROFILE_PATH).model_dump(mode="json"))
    plan = payload["execution_plan"]
    plan["authority"] = {"kind": "municipality", "code": "SF"}
    plan["plan_id"] = "regional-sf-scheduled"
    plan["contract_path"] = "infra/fly/regional_sf_refresh_machine_profile.json"
    plan["scheduled"]["job_keys"] = ["city-sf-transactions"]
    plan["canary"]["job_keys"] = ["city-sf-transactions"]
    payload["profile_id"] = "regional-sf-scheduled"
    payload["app"] = "civibus-regional-refresh-sf"
    payload["canary"]["job_key"] = "city-sf-transactions"
    payload["canary"]["command"] = [
        "python",
        "-m",
        "core.refresh.runner",
        "--authority-plan-json",
        "infra/fly/regional_sf_refresh_machine_profile.json",
        "--execution-mode",
        "canary",
        "--execution-origin",
        "operator_attended",
    ]
    payload["machine"]["name"] = "regional-sf-scheduled"
    payload["machine"]["config"]["init"]["cmd"] = [
        "python",
        "-m",
        "core.refresh.runner",
        "--authority-plan-json",
        "infra/fly/regional_sf_refresh_machine_profile.json",
        "--execution-mode",
        "scheduled",
        "--execution-origin",
        "scheduled",
    ]
    payload["machine"]["config"]["metadata"] = {
        "civibus_authority": "municipality/SF",
        "civibus_execution_plan": "regional-sf-scheduled",
        "civibus_profile": "regional-sf-scheduled",
    }
    payload["machine"]["config_sha256"] = canonical_sha256(payload["machine"]["config"])
    payload["resource_ownership"] = {
        "app": "civibus-regional-refresh-sf",
        "authority": "municipality/SF",
        "machine": "regional-sf-scheduled",
        "plan": "regional-sf-scheduled",
    }
    return AuthorityOperationsProfile.model_validate(payload)


def test_live_profile_binds_exact_authority_plan_machine_and_nonsecret_delivery() -> None:
    profile = load_authority_operations_profile(_PROFILE_PATH)

    assert profile.authority.operational_scope == "state/WA"
    assert profile.machine.config.metadata == {
        "civibus_authority": "state/WA",
        "civibus_execution_plan": "regional-wa-scheduled",
        "civibus_profile": "regional-wa-scheduled",
    }
    assert profile.machine.config_sha256 == canonical_sha256(profile.machine.config.model_dump(mode="json"))
    assert profile.secret_delivery.names == ("POSTGRES_PASSWORD",)
    assert profile.secret_delivery.machine_config_env_names == ()
    assert profile.cleanup.indeterminate == "handoff_without_mutation_or_retry"


def test_image_proof_is_derived_from_typed_plan_instead_of_washington_constants() -> None:
    profile = load_authority_operations_profile(_PROFILE_PATH)
    proof = expected_image_plan_proof(
        profile,
        build_version={"git_sha": "4" * 40, "built_at": "2026-08-28T00:00:00Z"},
    )

    assert proof["authority"] == {"kind": "state", "code": "WA"}
    assert proof["scheduled"]["job_keys"] == list(profile.execution_plan.scheduled.job_keys)
    assert proof["canary"]["job_keys"] == ["state-wa-contributions"]
    assert proof["concurrency"]["max_parallel_jobs"] == 1
    assert proof["cadence_clock"]["force_allowed"] is False


def test_two_authority_profiles_cannot_share_runtime_resource_ownership() -> None:
    wa_profile = load_authority_operations_profile(_PROFILE_PATH)
    sf_profile = _synthetic_sf_profile()
    validate_disjoint_operations_profiles((wa_profile, sf_profile))

    shared_app = deepcopy(sf_profile.model_dump(mode="json"))
    shared_app["app"] = wa_profile.app
    shared_app["resource_ownership"]["app"] = wa_profile.app
    with pytest.raises(ValueError, match="share app ownership"):
        validate_disjoint_operations_profiles((wa_profile, AuthorityOperationsProfile.model_validate(shared_app)))

    shared_job = deepcopy(sf_profile.model_dump(mode="json"))
    shared_job_key = wa_profile.execution_plan.scheduled.job_keys[0]
    shared_job["execution_plan"]["scheduled"]["job_keys"] = [shared_job_key]
    shared_job["execution_plan"]["canary"]["job_keys"] = [shared_job_key]
    shared_job["canary"]["job_key"] = shared_job_key
    with pytest.raises(ValueError, match="share refresh job ownership"):
        validate_disjoint_operations_profiles((wa_profile, AuthorityOperationsProfile.model_validate(shared_job)))


def test_profile_refuses_secret_or_cross_authority_machine_metadata_drift() -> None:
    profile = load_authority_operations_profile(_PROFILE_PATH)
    payload = deepcopy(profile.model_dump(mode="json"))
    payload["machine"]["config"]["metadata"]["civibus_authority"] = "municipality/SF"
    payload["machine"]["config_sha256"] = canonical_sha256(payload["machine"]["config"])
    with pytest.raises(ValueError, match="metadata does not bind exact plan ownership"):
        AuthorityOperationsProfile.model_validate(payload)

    payload = deepcopy(profile.model_dump(mode="json"))
    payload["secret_delivery"]["value"] = "must never be accepted"
    with pytest.raises(ValueError, match="extra_forbidden"):
        AuthorityOperationsProfile.model_validate(payload)
