from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
VERIFIER_PATH = REPO_ROOT / "infra/scripts/verify_refresh_machine.sh"
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


def _run_verifier(
    tmp_path: Path,
    payloads: dict[str, Any],
    *,
    omit_payload: str | None = None,
    invalid_payload: str | None = None,
) -> subprocess.CompletedProcess[str]:
    fixture_paths: dict[str, Path] = {}
    for payload_name, payload in payloads.items():
        fixture_path = tmp_path / f"{payload_name}.json"
        if payload_name != omit_payload:
            fixture_path.write_text(
                "not JSON" if payload_name == invalid_payload else json.dumps(payload),
                encoding="utf-8",
            )
        fixture_paths[payload_name] = fixture_path

    stub_bin = _write_external_command_stubs(tmp_path)
    environment = os.environ.copy()
    environment["PATH"] = f"{stub_bin}:/usr/bin:/bin"
    return subprocess.run(
        [
            "bash",
            str(VERIFIER_PATH),
            "--machines-json",
            str(fixture_paths["machines"]),
            "--machine-config-json",
            str(fixture_paths["machine_config"]),
            "--volumes-json",
            str(fixture_paths["volumes"]),
            "--version-json",
            str(fixture_paths["version"]),
        ],
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
