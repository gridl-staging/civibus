from __future__ import annotations

import hashlib
import json
import os
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
VERIFIER_PATH = REPO_ROOT / "infra/scripts/verify_refresh_machine.sh"
REGIONAL_PROFILE_PATH = REPO_ROOT / "infra/fly/regional_refresh_machine_profile.json"
MACHINE_ID = "859e0da479e678"
VOLUME_ID = "vol_42kzg23gem178304"
EXPECTED_ENV = {
    "CIVIBUS_ENV": "production",
    "POSTGRES_HOST": "civibus-db.internal",
    "POSTGRES_PORT": "5432",
    "POSTGRES_USER": "civibus",
    "POSTGRES_DB": "civibus",
    "CIVIBUS_REFRESH_DATA_DIR": "/data",
    "CIVIBUS_STARTUP_CANARY": "skip",
}
PRODUCED_IMAGE_TAGGED_DIGEST = "registry.fly.io/civibus-refresh:regional-candidate@sha256:" + "a" * 64


def _valid_payloads() -> dict[str, Any]:
    return {
        "machines": [
            {
                "id": MACHINE_ID,
                "name": "lingering-butterfly-8636",
                "region": "sjc",
                "state": "stopped",
                "config": {
                    "schedule": "weekly",
                    "guest": {
                        "cpu_kind": "shared",
                        "cpus": 1,
                        "memory_mb": 1024,
                    },
                },
            }
        ],
        "machine_config": {
            "init": {
                "cmd": [
                    "python",
                    "-m",
                    "core.refresh.runner",
                    "--scope",
                    "federal",
                ]
            },
            "env": dict(EXPECTED_ENV),
            "mounts": [{"volume": VOLUME_ID, "path": "/data"}],
            "restart": {"policy": "no"},
        },
        "volumes": [
            {
                "id": VOLUME_ID,
                "state": "created",
                "attached_machine_id": MACHINE_ID,
            }
        ],
        "version": {
            "git_sha": "0123456789abcdef0123456789abcdef01234567",
            "built_at": "2026-07-31T12:00:00Z",
        },
        "expected_plan": {
            "refresh_plan_job_keys": [
                "federal-congress-spine",
                "federal-donor-search-rollup",
            ],
        },
        "image_proof": {
            "build_version": {
                "git_sha": "0123456789abcdef0123456789abcdef01234567",
                "built_at": "2026-07-31T12:00:00Z",
            },
            "person_link_is_fillable": True,
            "repair_pair_alarm": True,
            "refresh_plan_job_keys": [
                "federal-congress-spine",
                "federal-donor-search-rollup",
            ],
        },
    }


def _write_external_command_stubs(tmp_path: Path) -> Path:
    stub_bin = tmp_path / "stub_bin"
    stub_bin.mkdir()
    for command in ("flyctl", "curl", "docker"):
        stub = stub_bin / command
        stub.write_text(
            f"#!/usr/bin/env bash\necho 'unexpected {command} invocation' >&2\nexit 97\n",
            encoding="utf-8",
        )
        stub.chmod(0o755)
    return stub_bin


def _write_fixture_paths(
    tmp_path: Path,
    payloads: dict[str, Any],
    *,
    omit_payload: str | None = None,
    invalid_payload: str | None = None,
) -> dict[str, Path]:
    fixture_paths: dict[str, Path] = {}
    for payload_name, payload in payloads.items():
        fixture_path = tmp_path / f"{payload_name}.json"
        if payload_name != omit_payload:
            fixture_path.write_text(
                "not JSON" if payload_name == invalid_payload else json.dumps(payload),
                encoding="utf-8",
            )
        fixture_paths[payload_name] = fixture_path
    return fixture_paths


def _run_verifier(
    tmp_path: Path,
    payloads: dict[str, Any],
    *,
    omit_payload: str | None = None,
    invalid_payload: str | None = None,
    include_plan_proof: bool = False,
    include_machine_fixtures: bool = True,
) -> subprocess.CompletedProcess[str]:
    fixture_paths = _write_fixture_paths(
        tmp_path,
        payloads,
        omit_payload=omit_payload,
        invalid_payload=invalid_payload,
    )

    stub_bin = _write_external_command_stubs(tmp_path)
    environment = os.environ.copy()
    environment["PATH"] = f"{stub_bin}:/usr/bin:/bin"
    command = ["bash", str(VERIFIER_PATH)]
    if include_machine_fixtures:
        command.extend(
            [
                "--machines-json",
                str(fixture_paths["machines"]),
                "--machine-config-json",
                str(fixture_paths["machine_config"]),
                "--volumes-json",
                str(fixture_paths["volumes"]),
                "--version-json",
                str(fixture_paths["version"]),
            ]
        )
    if include_plan_proof:
        command.extend(
            [
                "--expected-plan-json",
                str(fixture_paths["expected_plan"]),
                "--image-proof-json",
                str(fixture_paths["image_proof"]),
            ]
        )
    return subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )


def _run_regional_profile_check(
    tmp_path: Path,
    profile: dict[str, Any] | str,
    *,
    profile_only: bool = True,
) -> subprocess.CompletedProcess[str]:
    profile_path = tmp_path / "regional_profile.json"
    profile_path.write_text(
        profile if isinstance(profile, str) else json.dumps(profile),
        encoding="utf-8",
    )
    return _run_regional_profile_path(tmp_path, profile_path, profile_only=profile_only)


def _run_regional_profile_path(
    tmp_path: Path,
    profile_path: Path,
    *,
    profile_only: bool = True,
) -> subprocess.CompletedProcess[str]:
    stub_bin = _write_external_command_stubs(tmp_path)
    environment = os.environ.copy()
    environment["PATH"] = f"{stub_bin}:/usr/bin:/bin"
    command = ["bash", str(VERIFIER_PATH), "--profile-json", str(profile_path)]
    if profile_only:
        command.append("--profile-only")
    return subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )


def _regional_profile() -> dict[str, Any]:
    return json.loads(REGIONAL_PROFILE_PATH.read_text(encoding="utf-8"))


def _canonical_sha256(value: object) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def _regional_candidate_receipt(
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if profile is None:
        profile = _regional_profile()
    canonical_source = profile["canonical_source"]
    plan = profile["execution_plan"]
    return {
        "canonical_receipt_git_sha": canonical_source["receipt_git_sha"],
        "canonical_source_git_sha": canonical_source["source_git_sha"],
        "canonical_tree_git_sha": canonical_source["tree_git_sha"],
        "image_proof": {
            "authority": plan["authority"],
            "build_version": {"git_sha": "4" * 40, "built_at": "2026-08-28T00:00:00Z"},
            "cadence_clock": plan["cadence_clock"],
            "canary": plan["canary"],
            "concurrency": plan["concurrency"],
            "execution_plan_id": plan["plan_id"],
            "execution_plan_sha256": _canonical_sha256(plan),
            "scheduled": plan["scheduled"],
        },
        "machine_config_sha256": profile["machine"]["config_sha256"],
        "produced_image_tagged_digest": PRODUCED_IMAGE_TAGGED_DIGEST,
        "profile_sha256": _canonical_sha256(profile),
        "qualification_kind": "authority_refresh_image_candidate",
        "schema_version": 2,
        "source_git_sha": "4" * 40,
        "source_tree_git_sha": "5" * 40,
    }


def _run_candidate_receipt_check(
    tmp_path: Path,
    receipt: dict[str, Any] | str,
    *,
    profile: dict[str, Any] | str | None = None,
    receipt_path: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    profile_payload = _regional_profile() if profile is None else profile
    profile_path = tmp_path / "regional_profile.json"
    profile_path.write_text(
        profile_payload if isinstance(profile_payload, str) else json.dumps(profile_payload),
        encoding="utf-8",
    )
    if receipt_path is None:
        receipt_path = tmp_path / "candidate_receipt.json"
        receipt_path.write_text(
            receipt if isinstance(receipt, str) else json.dumps(receipt),
            encoding="utf-8",
        )
    stub_bin = _write_external_command_stubs(tmp_path)
    environment = os.environ.copy()
    environment["PATH"] = f"{stub_bin}:/usr/bin:/bin"
    return subprocess.run(
        [
            "bash",
            str(VERIFIER_PATH),
            "--profile-json",
            str(profile_path),
            "--candidate-receipt-json",
            str(receipt_path),
            "--profile-only",
        ],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )


def _run_regional_live_check(
    tmp_path: Path,
    *,
    case: str = "",
    duplicate_option: str = "",
    config_kind: str = "recurring",
) -> subprocess.CompletedProcess[str]:
    profile = _regional_profile()
    receipt = _regional_candidate_receipt(profile)
    app: Any = {
        "Name": profile["app"],
        "ID": profile["app"],
        "Organization": {"Slug": profile["organization"], "ID": profile["organization_id"]},
    }
    machines: Any = [
        {
            "id": "abc123",
            "name": profile["machine"]["name"],
            "region": profile["machine"]["region"],
            "state": "stopped",
        }
    ]
    config: Any = deepcopy(profile["machine"]["config"])
    if config_kind == "canary":
        config["init"]["cmd"] = profile["canary"]["command"]
        config.pop("schedule")
        plan = profile["execution_plan"]
        authority = plan["authority"]
        config["metadata"] = {
            "civibus_authority": f"{authority['kind']}/{authority['code']}",
            "civibus_execution_plan": plan["plan_id"],
            "civibus_job_key": plan["canary"]["job_keys"][0],
            "civibus_profile": profile["profile_id"],
        }
    config["image"] = receipt["produced_image_tagged_digest"]
    expected_state = "stopped"
    machine_id = "abc123"
    if case == "invalid_expected_state":
        expected_state = "destroyed"
    elif case == "invalid_machine_id":
        machine_id = "NOT-HEX"
    elif case == "app_not_object":
        app = []
    elif case == "wrong_app_name":
        app["Name"] = "wrong"
    elif case == "wrong_app_id":
        app["ID"] = "wrong"
    elif case == "organization_not_object":
        app["Organization"] = []
    elif case == "wrong_organization_slug":
        app["Organization"]["Slug"] = "wrong"
    elif case == "wrong_organization_id":
        app["Organization"]["ID"] = "wrong"
    elif case == "machines_not_list":
        machines = {}
    elif case == "extra_machine":
        machines.append(dict(machines[0], id="def456"))
    elif case == "machine_not_object":
        machines[0] = "wrong"
    elif case == "wrong_machine_id":
        machines[0]["id"] = "def456"
    elif case == "wrong_machine_name":
        machines[0]["name"] = "wrong"
    elif case == "wrong_machine_region":
        machines[0]["region"] = "iad"
    elif case == "wrong_machine_state":
        machines[0]["state"] = "started"
    elif case == "config_not_object":
        config = []
    elif case == "wrong_image":
        config["image"] = "registry.fly.io/civibus-refresh:wrong@sha256:" + "f" * 64
    elif case == "config_drift":
        config["schedule"] = "weekly"
    elif case == "recurring_config":
        config = deepcopy(profile["machine"]["config"])
        config["image"] = receipt["produced_image_tagged_digest"]
    elif case == "canary_config":
        config = deepcopy(profile["machine"]["config"])
        config["init"]["cmd"] = profile["canary"]["command"]
        config.pop("schedule")
        plan = profile["execution_plan"]
        authority = plan["authority"]
        config["metadata"] = {
            "civibus_authority": f"{authority['kind']}/{authority['code']}",
            "civibus_execution_plan": plan["plan_id"],
            "civibus_job_key": plan["canary"]["job_keys"][0],
            "civibus_profile": profile["profile_id"],
        }
        config["image"] = receipt["produced_image_tagged_digest"]
    elif case:
        raise AssertionError(f"unknown case: {case}")
    payloads = {"profile": profile, "receipt": receipt, "app": app, "machines": machines, "config": config}
    paths = _write_fixture_paths(tmp_path, payloads)
    stub_bin = _write_external_command_stubs(tmp_path)
    environment = os.environ.copy()
    environment["PATH"] = f"{stub_bin}:/usr/bin:/bin"
    command = [
        "bash",
        str(VERIFIER_PATH),
        "--profile-json",
        str(paths["profile"]),
        "--candidate-receipt-json",
        str(paths["receipt"]),
        "--regional-app-json",
        str(paths["app"]),
        "--regional-machines-json",
        str(paths["machines"]),
        "--regional-machine-config-json",
        str(paths["config"]),
        "--regional-expected-state",
        expected_state,
        "--regional-machine-id",
        machine_id,
        "--regional-config-kind",
        config_kind,
    ]
    if duplicate_option:
        command[command.index(duplicate_option) : command.index(duplicate_option)] = [duplicate_option, "wrong"]
    return subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )


def _apply_failure_case(payloads: dict[str, Any], case: str) -> None:
    machine = payloads["machines"][0]
    machine_config = payloads["machine_config"]
    if case == "missing_machine":
        payloads["machines"] = []
    elif case == "extra_machine":
        payloads["machines"].append({"id": "extra-machine"})
    elif case == "wrong_machine_id":
        machine["id"] = "wrong-machine"
    elif case == "wrong_machine_name":
        machine["name"] = "wrong-name"
    elif case == "wrong_command":
        machine_config["init"]["cmd"][-1] = "state"
    elif case == "wrong_schedule":
        machine["config"]["schedule"] = "daily"
    elif case == "restart_enabled":
        machine_config["restart"]["policy"] = "always"
    elif case == "started_state":
        machine["state"] = "started"
    elif case == "running_state":
        machine["state"] = "running"
    elif case == "wrong_region":
        machine["region"] = "iad"
    elif case == "wrong_cpu_kind":
        machine["config"]["guest"]["cpu_kind"] = "performance"
    elif case == "wrong_cpu_count":
        machine["config"]["guest"]["cpus"] = 2
    elif case == "wrong_memory":
        machine["config"]["guest"]["memory_mb"] = 2048
    elif case == "missing_data_mount":
        machine_config["mounts"] = []
    elif case == "missing_volume_evidence":
        payloads["volumes"] = []
    elif case == "wrong_volume_attachment":
        payloads["volumes"][0]["attached_machine_id"] = "wrong-machine"
    else:
        raise AssertionError(f"unknown test case: {case}")


def test_verifier_accepts_complete_fixture_contract_without_external_reads(
    tmp_path: Path,
) -> None:
    result = _run_verifier(tmp_path, _valid_payloads())

    assert result.returncode == 0, result.stderr
    assert result.stdout == "PASS: refresh Machine contract verified\n"
    assert result.stderr == ""


def test_verifier_rejects_duplicate_regional_profile_keys(tmp_path: Path) -> None:
    profile_text = json.dumps(_regional_profile())
    duplicate_key_text = '{"app":"civibus-refresh",' + profile_text[1:]

    result = _run_regional_profile_check(tmp_path, duplicate_key_text)

    assert result.returncode == 1
    assert result.stdout == ""
    assert "duplicate object key" in result.stderr


def test_verifier_rejects_regional_profile_symlink(tmp_path: Path) -> None:
    target = tmp_path / "profile_target.json"
    target.write_text(json.dumps(_regional_profile()), encoding="utf-8")
    profile_link = tmp_path / "profile_link.json"
    profile_link.symlink_to(target)

    result = _run_regional_profile_path(tmp_path, profile_link)

    assert result.returncode == 1
    assert result.stdout == ""
    assert "regular non-symlink file" in result.stderr


def test_verifier_freezes_unprovisioned_regional_profile_without_external_reads(
    tmp_path: Path,
) -> None:
    result = _run_regional_profile_check(tmp_path, _regional_profile())

    assert result.returncode == 0, result.stderr
    assert result.stdout == ("PASS: regional refresh Machine profile frozen (unprovisioned; not execution-ready)\n")
    assert result.stderr == ""


def test_verifier_accepts_a_disjoint_authority_profile_without_weakening_washington_control(
    tmp_path: Path,
) -> None:
    profile = deepcopy(_regional_profile())
    plan = profile["execution_plan"]
    plan["authority"] = {"kind": "municipality", "code": "SF"}
    plan["plan_id"] = "regional-sf-scheduled"
    plan["contract_path"] = "infra/fly/regional_sf_refresh_machine_profile.json"
    plan["scheduled"]["job_keys"] = ["city-sf-transactions"]
    plan["canary"]["job_keys"] = ["city-sf-transactions"]
    profile["app"] = "civibus-regional-refresh-sf"
    profile["profile_id"] = plan["plan_id"]
    profile["canary"]["command"] = [
        "python",
        "-m",
        "core.refresh.runner",
        "--authority-plan-json",
        plan["contract_path"],
        "--execution-mode",
        "canary",
        "--execution-origin",
        "operator_attended",
    ]
    profile["canary"]["job_key"] = "city-sf-transactions"
    profile["machine"]["name"] = plan["plan_id"]
    profile["machine"]["config"]["init"]["cmd"] = [
        "python",
        "-m",
        "core.refresh.runner",
        "--authority-plan-json",
        plan["contract_path"],
        "--execution-mode",
        "scheduled",
        "--execution-origin",
        "scheduled",
    ]
    profile["machine"]["config"]["metadata"] = {
        "civibus_authority": "municipality/SF",
        "civibus_execution_plan": plan["plan_id"],
        "civibus_profile": plan["plan_id"],
    }
    profile["machine"]["config_sha256"] = _canonical_sha256(profile["machine"]["config"])
    profile["resource_ownership"] = {
        "app": profile["app"],
        "authority": "municipality/SF",
        "machine": plan["plan_id"],
        "plan": plan["plan_id"],
    }

    result = _run_regional_profile_check(tmp_path, profile)

    assert result.returncode == 0, result.stderr
    assert result.stdout == "PASS: regional refresh Machine profile frozen (unprovisioned; not execution-ready)\n"
    assert result.stderr == ""


def test_regional_profile_is_rooted_in_the_accepted_canonical_receipt_source_and_tree() -> None:
    profile = _regional_profile()

    assert profile["canonical_source"] == {
        "receipt_git_sha": "f198d2d2aab360b62d55d6b61f2853f4a4bc10ac",
        "source_git_sha": "3df2e919388edb84b9f4f6cc33c496a8a8462937",
        "tree_git_sha": "61c293365ede61e0a43d42087c0ffdd70251631f",
    }
    assert profile["machine"]["config"]["init"]["cmd"] == [
        "python",
        "-m",
        "core.refresh.runner",
        "--authority-plan-json",
        "infra/fly/regional_refresh_machine_profile.json",
        "--execution-mode",
        "scheduled",
        "--execution-origin",
        "scheduled",
    ]
    assert profile["canary"] == {
        "command": [
            "python",
            "-m",
            "core.refresh.runner",
            "--authority-plan-json",
            "infra/fly/regional_refresh_machine_profile.json",
            "--execution-mode",
            "canary",
            "--execution-origin",
            "operator_attended",
        ],
        "job_key": "state-wa-contributions",
        "execution_origin": "operator_attended",
        "schedule": None,
        "stop_on_failure": True,
    }


def test_verifier_blocks_live_use_of_unprovisioned_regional_profile(
    tmp_path: Path,
) -> None:
    result = _run_regional_profile_check(
        tmp_path,
        _regional_profile(),
        profile_only=False,
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert "regional profile is unprovisioned; live verification is blocked" in result.stderr
    assert "unexpected flyctl invocation" not in result.stderr


def test_verifier_accepts_bound_regional_image_candidate_receipt_without_external_reads(
    tmp_path: Path,
) -> None:
    result = _run_candidate_receipt_check(
        tmp_path,
        _regional_candidate_receipt(),
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "PASS: regional refresh image candidate receipt verified\n"
    assert result.stderr == ""


def test_verifier_accepts_exact_regional_live_contract_without_external_reads(
    tmp_path: Path,
) -> None:
    result = _run_regional_live_check(tmp_path)

    assert result.returncode == 0, result.stderr
    assert result.stdout == "PASS: regional refresh Machine live contract verified\n"


def test_verifier_accepts_exact_singleton_canary_config_without_a_schedule(
    tmp_path: Path,
) -> None:
    result = _run_regional_live_check(tmp_path, config_kind="canary")

    assert result.returncode == 0, result.stderr
    assert result.stdout == "PASS: regional refresh Machine live contract verified\n"


def test_verifier_rejects_recurring_four_job_config_when_canary_is_claimed(
    tmp_path: Path,
) -> None:
    result = _run_regional_live_check(tmp_path, config_kind="canary", case="recurring_config")

    assert result.returncode != 0
    assert "regional Machine config" in result.stderr


def test_verifier_rejects_canary_config_when_recurring_four_job_mode_is_claimed(
    tmp_path: Path,
) -> None:
    result = _run_regional_live_check(tmp_path, config_kind="recurring", case="canary_config")

    assert result.returncode != 0
    assert "regional Machine config" in result.stderr


@pytest.mark.parametrize(
    "option",
    [
        "--regional-app-json",
        "--regional-machines-json",
        "--regional-machine-config-json",
        "--regional-expected-state",
        "--regional-machine-id",
        "--regional-config-kind",
    ],
)
def test_verifier_rejects_duplicate_regional_live_options(tmp_path: Path, option: str) -> None:
    result = _run_regional_live_check(tmp_path, duplicate_option=option)

    assert result.returncode == 1
    assert f"{option} may be supplied only once" in result.stderr


@pytest.mark.parametrize(
    "case",
    [
        "invalid_expected_state",
        "invalid_machine_id",
        "app_not_object",
        "wrong_app_name",
        "wrong_app_id",
        "organization_not_object",
        "wrong_organization_slug",
        "wrong_organization_id",
        "machines_not_list",
        "extra_machine",
        "machine_not_object",
        "wrong_machine_id",
        "wrong_machine_name",
        "wrong_machine_region",
        "wrong_machine_state",
        "config_not_object",
        "wrong_image",
        "config_drift",
    ],
)
def test_verifier_rejects_every_regional_live_identity_or_config_branch(
    tmp_path: Path,
    case: str,
) -> None:
    result = _run_regional_live_check(tmp_path, case=case)

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.startswith("FAIL: refresh Machine contract:")
    assert "unexpected" not in result.stderr


@pytest.mark.parametrize("profile_only", [False, True])
def test_verifier_rejects_incomplete_or_profile_only_regional_live_mode(
    tmp_path: Path,
    profile_only: bool,
) -> None:
    profile_path = tmp_path / "profile.json"
    receipt_path = tmp_path / "receipt.json"
    app_path = tmp_path / "app.json"
    profile_path.write_text(json.dumps(_regional_profile()), encoding="utf-8")
    receipt_path.write_text(json.dumps(_regional_candidate_receipt()), encoding="utf-8")
    app_path.write_text("{}", encoding="utf-8")
    stub_bin = _write_external_command_stubs(tmp_path)
    environment = os.environ.copy()
    environment["PATH"] = f"{stub_bin}:/usr/bin:/bin"
    command = [
        "bash",
        str(VERIFIER_PATH),
        "--profile-json",
        str(profile_path),
        "--candidate-receipt-json",
        str(receipt_path),
        "--regional-app-json",
        str(app_path),
    ]
    if profile_only:
        command.extend(
            [
                "--regional-machines-json",
                str(app_path),
                "--regional-machine-config-json",
                str(app_path),
                "--regional-expected-state",
                "stopped",
                "--regional-machine-id",
                "abc123",
                "--profile-only",
            ]
        )

    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 1
    assert "regional live mode requires" in result.stderr


@pytest.mark.parametrize(
    "case",
    [
        "missing_field",
        "extra_field",
        "boolean_schema_version",
        "wrong_kind",
        "source_drift",
        "proof_source_drift",
        "proof_plan_drift",
        "mutable_produced_image",
        "digest_only_produced_image",
        "wrong_produced_repository",
        "config_digest_drift",
        "profile_digest_drift",
    ],
)
def test_verifier_rejects_candidate_receipt_drift_fail_closed(
    tmp_path: Path,
    case: str,
) -> None:
    receipt = _regional_candidate_receipt()
    if case == "missing_field":
        del receipt["profile_sha256"]
    elif case == "extra_field":
        receipt["unexpected"] = True
    elif case == "boolean_schema_version":
        receipt["schema_version"] = True
    elif case == "wrong_kind":
        receipt["qualification_kind"] = "deploy"
    elif case == "source_drift":
        receipt["source_git_sha"] = "not-a-commit"
    elif case == "proof_source_drift":
        receipt["image_proof"]["build_version"]["git_sha"] = "6" * 40
    elif case == "proof_plan_drift":
        receipt["image_proof"]["scheduled"]["job_keys"].pop()
    elif case == "mutable_produced_image":
        receipt["produced_image_tagged_digest"] = "registry.fly.io/civibus-refresh:regional-candidate"
    elif case == "digest_only_produced_image":
        receipt["produced_image_tagged_digest"] = "registry.fly.io/civibus-refresh@sha256:" + "a" * 64
    elif case == "wrong_produced_repository":
        receipt["produced_image_tagged_digest"] = "registry.fly.io/another-app:regional-candidate@sha256:" + "a" * 64
    elif case == "config_digest_drift":
        receipt["machine_config_sha256"] = "0" * 64
    elif case == "profile_digest_drift":
        receipt["profile_sha256"] = "0" * 64
    else:
        raise AssertionError(f"unknown case: {case}")

    result = _run_candidate_receipt_check(tmp_path, receipt)

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.startswith("FAIL: refresh Machine contract:")
    assert "unexpected flyctl invocation" not in result.stderr
    assert "unexpected curl invocation" not in result.stderr
    assert "unexpected docker invocation" not in result.stderr


def test_verifier_rejects_duplicate_candidate_receipt_keys(tmp_path: Path) -> None:
    receipt_text = json.dumps(_regional_candidate_receipt())
    duplicate_key_text = '{"schema_version":2,' + receipt_text[1:]

    result = _run_candidate_receipt_check(tmp_path, duplicate_key_text)

    assert result.returncode == 1
    assert "candidate receipt JSON contains a duplicate object key" in result.stderr


def test_verifier_rejects_candidate_receipt_symlink(tmp_path: Path) -> None:
    receipt_target = tmp_path / "candidate_receipt_target.json"
    receipt_target.write_text(
        json.dumps(_regional_candidate_receipt()),
        encoding="utf-8",
    )
    receipt_link = tmp_path / "candidate_receipt_link.json"
    receipt_link.symlink_to(receipt_target)

    result = _run_candidate_receipt_check(
        tmp_path,
        _regional_candidate_receipt(),
        receipt_path=receipt_link,
    )

    assert result.returncode == 1
    assert "candidate receipt JSON must be a regular non-symlink file" in result.stderr


def test_verifier_requires_candidate_receipt_and_profile_mode_together(
    tmp_path: Path,
) -> None:
    receipt_path = tmp_path / "candidate_receipt.json"
    receipt_path.write_text(
        json.dumps(_regional_candidate_receipt()),
        encoding="utf-8",
    )
    stub_bin = _write_external_command_stubs(tmp_path)
    environment = os.environ.copy()
    environment["PATH"] = f"{stub_bin}:/usr/bin:/bin"

    result = subprocess.run(
        [
            "bash",
            str(VERIFIER_PATH),
            "--candidate-receipt-json",
            str(receipt_path),
        ],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 1
    assert "candidate receipt mode requires --profile-json" in result.stderr


@pytest.mark.parametrize(
    ("candidate_args", "expected_error"),
    [
        (
            ("--candidate-receipt-json", ""),
            "--candidate-receipt-json requires a non-empty path",
        ),
        (
            (
                "--candidate-receipt-json",
                "candidate_receipt.json",
                "--candidate-receipt-json",
                "",
            ),
            "--candidate-receipt-json may be supplied only once",
        ),
    ],
)
def test_verifier_rejects_empty_or_duplicate_candidate_receipt_options(
    tmp_path: Path,
    candidate_args: tuple[str, ...],
    expected_error: str,
) -> None:
    stub_bin = _write_external_command_stubs(tmp_path)
    environment = os.environ.copy()
    environment["PATH"] = f"{stub_bin}:/usr/bin:/bin"

    result = subprocess.run(
        [
            "bash",
            str(VERIFIER_PATH),
            "--profile-json",
            str(REGIONAL_PROFILE_PATH),
            *candidate_args,
            "--profile-only",
        ],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert expected_error in result.stderr


@pytest.mark.parametrize(
    "case",
    [
        "extra_top_level_field",
        "federal_app_reuse",
        "wrong_source_revision",
        "premature_machine_identity",
        "premature_image_identity",
        "non_stopped_default",
        "wrong_schedule",
        "extra_command_option",
        "volume_mount",
        "secret_in_machine_env",
        "machine_config_file",
        "wrong_secret_delivery",
        "unsafe_cleanup",
    ],
)
def test_verifier_rejects_regional_profile_drift_fail_closed(
    tmp_path: Path,
    case: str,
) -> None:
    profile = deepcopy(_regional_profile())
    if case == "extra_top_level_field":
        profile["unexpected"] = True
    elif case == "federal_app_reuse":
        profile["app"] = "civibus-refresh"
    elif case == "wrong_source_revision":
        profile["canonical_source"]["source_git_sha"] = "0" * 40
    elif case == "premature_machine_identity":
        profile["machine"]["id"] = "1234567890abcd"
    elif case == "premature_image_identity":
        profile["image"]["tagged_digest"] = f"registry.fly.io/civibus-refresh:deployment-test@sha256:{'a' * 64}"
    elif case == "non_stopped_default":
        profile["machine"]["default_state"] = "started"
    elif case == "wrong_schedule":
        profile["machine"]["config"]["schedule"] = "weekly"
    elif case == "extra_command_option":
        profile["machine"]["config"]["init"]["cmd"].append("--force")
    elif case == "volume_mount":
        profile["machine"]["config"]["mounts"] = [{"path": "/data", "volume": "federal"}]
    elif case == "secret_in_machine_env":
        profile["machine"]["config"]["env"]["POSTGRES_PASSWORD"] = "must-not-appear"
    elif case == "machine_config_file":
        profile["machine"]["config"]["files"] = [{"guest_path": "/tmp/password"}]
    elif case == "wrong_secret_delivery":
        profile["secret_delivery"]["provider"] = "machine_config_file"
    elif case == "unsafe_cleanup":
        profile["cleanup"]["prestart_failure"] = "destroy_all_machines"
    else:
        raise AssertionError(f"unknown case: {case}")

    result = _run_regional_profile_check(tmp_path, profile)

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.startswith("FAIL: refresh Machine contract:")
    assert "unexpected flyctl invocation" not in result.stderr


def test_verifier_accepts_matching_refresh_plan_proof_inputs(tmp_path: Path) -> None:
    result = _run_verifier(tmp_path, _valid_payloads(), include_plan_proof=True)

    assert result.returncode == 0, result.stderr
    assert result.stdout == "PASS: refresh Machine contract verified\n"
    assert result.stderr == ""


def test_verifier_accepts_plan_proof_without_live_machine_probes(tmp_path: Path) -> None:
    result = _run_verifier(
        tmp_path,
        _valid_payloads(),
        include_plan_proof=True,
        include_machine_fixtures=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "PASS: refresh Machine contract verified\n"
    assert result.stderr == ""


@pytest.mark.parametrize(
    ("image_plan_keys", "expected_errors"),
    [
        (
            ["federal-congress-spine", "federal-unexpected-image-job"],
            (
                "refresh plan job key mismatch",
                "missing from image: ['federal-donor-search-rollup']",
                "extra in image: ['federal-unexpected-image-job']",
            ),
        ),
        (
            ["federal-congress-spine", "federal-congress-spine", "federal-donor-search-rollup"],
            ("image-proof refresh_plan_job_keys contains duplicate keys: ['federal-congress-spine']",),
        ),
    ],
    ids=("missing_and_extra", "duplicate"),
)
def test_verifier_rejects_refresh_plan_mismatch_with_missing_and_extra_keys(
    tmp_path: Path,
    image_plan_keys: list[str],
    expected_errors: tuple[str, ...],
) -> None:
    payloads = _valid_payloads()
    payloads["image_proof"]["refresh_plan_job_keys"] = image_plan_keys

    result = _run_verifier(tmp_path, payloads, include_plan_proof=True)

    assert result.returncode == 1
    assert result.stdout == ""
    for expected_error in expected_errors:
        assert expected_error in result.stderr


def test_verifier_requires_plan_proof_paths_as_an_all_or_none_pair(tmp_path: Path) -> None:
    payloads = _valid_payloads()
    fixture_paths = _write_fixture_paths(tmp_path, payloads)
    stub_bin = _write_external_command_stubs(tmp_path)
    environment = os.environ.copy()
    environment["PATH"] = f"{stub_bin}:/usr/bin:/bin"

    result = subprocess.run(
        [
            "bash",
            str(VERIFIER_PATH),
            "--expected-plan-json",
            str(fixture_paths["expected_plan"]),
        ],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 1
    assert "plan-proof mode requires both JSON paths" in result.stderr


@pytest.mark.parametrize(
    ("case", "expected_error"),
    [
        ("missing_machine", "expected exactly one Machine, found 0"),
        ("extra_machine", "expected exactly one Machine, found 2"),
        ("wrong_machine_id", "Machine id"),
        ("wrong_machine_name", "Machine name"),
        ("wrong_command", "command"),
        ("wrong_schedule", "schedule"),
        ("restart_enabled", "restart policy"),
        ("started_state", "state"),
        ("running_state", "state"),
        ("wrong_region", "region"),
        ("wrong_cpu_kind", "VM CPU kind"),
        ("wrong_cpu_count", "VM CPU count"),
        ("wrong_memory", "VM memory"),
        ("missing_data_mount", "/data mount"),
        ("missing_volume_evidence", "volume evidence"),
        ("wrong_volume_attachment", "volume evidence"),
    ],
)
def test_verifier_rejects_incomplete_or_drifted_machine_contracts(
    tmp_path: Path,
    case: str,
    expected_error: str,
) -> None:
    payloads = _valid_payloads()
    _apply_failure_case(payloads, case)

    result = _run_verifier(tmp_path, payloads)

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.startswith("FAIL: refresh Machine contract:")
    assert expected_error in result.stderr


@pytest.mark.parametrize("missing_env_name", sorted(EXPECTED_ENV))
def test_verifier_requires_every_non_secret_production_env_value(
    tmp_path: Path,
    missing_env_name: str,
) -> None:
    payloads = _valid_payloads()
    del payloads["machine_config"]["env"][missing_env_name]

    result = _run_verifier(tmp_path, payloads)

    assert result.returncode == 1
    assert f"environment {missing_env_name}" in result.stderr


@pytest.mark.parametrize(
    ("omit_payload", "invalid_payload", "expected_error"),
    [
        ("version", None, "cannot read version JSON"),
        (None, "version", "version JSON is not valid JSON"),
    ],
)
def test_verifier_rejects_missing_or_non_json_version_payload(
    tmp_path: Path,
    omit_payload: str | None,
    invalid_payload: str | None,
    expected_error: str,
) -> None:
    result = _run_verifier(
        tmp_path,
        _valid_payloads(),
        omit_payload=omit_payload,
        invalid_payload=invalid_payload,
    )

    assert result.returncode == 1
    assert expected_error in result.stderr


@pytest.mark.parametrize(
    ("version_payload", "expected_error"),
    [
        ({"error": "degraded"}, "version git_sha"),
        ({"built_at": "2026-07-31T12:00:00Z"}, "version git_sha"),
        ({"git_sha": "abc123"}, "version built_at"),
        (
            {"git_sha": 123, "built_at": "2026-07-31T12:00:00Z"},
            "version git_sha",
        ),
        ({"git_sha": "abc123", "built_at": None}, "version built_at"),
    ],
)
def test_verifier_requires_string_version_contract_fields(
    tmp_path: Path,
    version_payload: dict[str, Any],
    expected_error: str,
) -> None:
    payloads = _valid_payloads()
    payloads["version"] = version_payload

    result = _run_verifier(tmp_path, payloads)

    assert result.returncode == 1
    assert result.stdout == ""
    assert expected_error in result.stderr


def test_verifier_source_is_read_only_and_uses_the_declared_live_probes() -> None:
    verifier_text = VERIFIER_PATH.read_text(encoding="utf-8")
    required_commands = (
        "flyctl auth whoami",
        "flyctl machines list -a civibus-refresh --json",
        "flyctl machine status 859e0da479e678 -a civibus-refresh --display-config",
        "flyctl volumes list -a civibus-refresh --json",
        ("curl --fail --silent --show-error --max-time 10 https://civibus.shareborough.com/api/health/version"),
    )
    forbidden_commands = (
        "flyctl machine update",
        "flyctl machine start",
        "flyctl deploy",
        "flyctl machine exec",
        "docker",
        "psql",
    )

    for required_command in required_commands:
        assert required_command in verifier_text
    for forbidden_command in forbidden_commands:
        assert forbidden_command not in verifier_text
