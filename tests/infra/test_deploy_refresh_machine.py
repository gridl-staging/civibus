from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_SCRIPT = REPO_ROOT / "infra/scripts/deploy_refresh_machine.sh"
MACHINE_ID = "859e0da479e678"
APP_NAME = "civibus-refresh"
MIRROR_SHA = "0123456789abcdef0123456789abcdef01234567"
DEV_SHA = "89abcdef0123456789abcdef0123456789abcdef"
IMAGE_TAG = f"registry.fly.io/{APP_NAME}:deployment-stage2"
IMAGE_DIGEST = f"registry.fly.io/{APP_NAME}@sha256:{'a' * 64}"


STUB_PROGRAM = r"""import json
import os
import pathlib
import sys

command = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ["COMMAND_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps([command, *args]) + "\n")

if command == "bash":
    os.execv("/bin/bash", ["/bin/bash", *args])

failure = os.environ.get("STUB_FAILURE", "")
command_history = [
    json.loads(line)
    for line in pathlib.Path(os.environ["COMMAND_LOG"]).read_text().splitlines()
]
machine_was_updated = any(
    argv[:3] == ["flyctl", "machine", "update"] for argv in command_history
)
post_digest = "sha256:" + ("b" if failure == "post_image_mismatch" else "a") * 64
machine = {
    "id": "859e0da479e678",
    "name": "lingering-butterfly-8636",
    "region": "sjc",
    "state": "stopped",
    "config": {
        "schedule": "weekly",
        "guest": {"cpu_kind": "shared", "cpus": 1, "memory_mb": 1024},
        "image": os.environ.get("STUB_MACHINE_IMAGE", "registry.fly.io/civibus-refresh:old"),
    },
}
if machine_was_updated:
    machine["state"] = "started"
    machine["config"]["image"] = (
        "registry.fly.io/civibus-refresh:deployment-stage2@" + post_digest
    )
    machine["image_ref"] = {
        "registry": "registry.fly.io",
        "repository": "civibus-refresh",
        "tag": "deployment-stage2",
        "digest": post_digest,
    }
machine_config = {
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
volumes = [{
    "id": "vol_42kzg23gem178304",
    "state": "created",
    "size_gb": 10,
    "attached_machine_id": "859e0da479e678",
}]

if command == "git":
    if args == ["status", "--porcelain", "--untracked-files=normal"]:
        if failure == "dirty":
            print(" M tracked_file")
    elif args == ["rev-parse", "--verify", "HEAD"]:
        print(os.environ["STUB_GIT_SHA"])
    elif args == ["rev-parse", "--show-toplevel"]:
        print(os.environ["REPO_ROOT"])
    else:
        sys.exit(91)
elif command == "curl":
    print(json.dumps({"git_sha": "previous", "built_at": "previous"}))
elif command == "flyctl":
    if args == ["auth", "whoami"]:
        if failure == "auth_whoami":
            sys.exit(92)
        print("authenticated@example.invalid")
    elif args == ["machines", "list", "-a", "civibus-refresh", "--json"]:
        if failure == "pre_verifier":
            machine["state"] = "started"
        print(json.dumps([machine]))
    elif args == ["machine", "status", "859e0da479e678", "-a", "civibus-refresh", "--display-config"]:
        print(json.dumps(machine_config))
    elif args == ["machine", "status", "859e0da479e678", "-a", "civibus-refresh"]:
        print("Event Logs\nSTATE stopped")
    elif args == ["volumes", "list", "-a", "civibus-refresh", "--json"]:
        print(json.dumps(volumes))
    elif args[:3] == ["deploy", "--build-only", "--push"]:
        if failure == "build":
            sys.exit(93)
        pushed_refs = os.environ.get("STUB_PUSHED_REFS", "default")
        if pushed_refs == "default":
            print("image: registry.fly.io/civibus-refresh:deployment-stage2")
        elif pushed_refs == "stderr":
            print("image: registry.fly.io/civibus-refresh:deployment-stage2", file=sys.stderr)
        elif pushed_refs == "ambiguous":
            print("registry.fly.io/civibus-refresh:first")
            print("registry.fly.io/civibus-refresh:second")
    elif args == ["auth", "docker"]:
        if failure == "registry_auth":
            sys.exit(94)
        print("registry authentication configured")
    elif args[:3] == ["machine", "update", "859e0da479e678"]:
        if failure == "update":
            print("invalid image identifier", file=sys.stderr)
            sys.exit(95)
        print("machine updated")
    else:
        sys.exit(96)
elif command == "sleep":
    pass
elif command == "docker":
    if args[:1] == ["pull"]:
        pull_count = sum(
            json.loads(line)[:2] == ["docker", "pull"]
            for line in pathlib.Path(os.environ["COMMAND_LOG"]).read_text().splitlines()
        )
        if failure == "image_pull" or (failure == "registry_delay" and pull_count == 1):
            print("manifest unknown", file=sys.stderr)
            sys.exit(90)
        print("pulled")
    elif args[:2] == ["image", "inspect"]:
        digest_mode = os.environ.get("STUB_DIGESTS", "default")
        if digest_mode == "default":
            print(json.dumps(["registry.fly.io/civibus-refresh@sha256:" + "a" * 64]))
        elif digest_mode == "ambiguous":
            print(json.dumps([
                "registry.fly.io/civibus-refresh@sha256:" + "a" * 64,
                "registry.fly.io/civibus-refresh@sha256:" + "b" * 64,
            ]))
        elif digest_mode == "malformed":
            print(json.dumps(["registry.fly.io/civibus-refresh@sha256:short"]))
        else:
            print("[]")
    elif args[:2] == ["image", "rm"]:
        # Dropping the local copy before the Machine update stops flyctl from
        # finding the tag locally and re-pushing it under a second deployment
        # tag, which would mint a second digest and make the post-update digest
        # guard unpassable (civibus-n8r).
        if failure == "local_image_rm":
            print("no such image", file=sys.stderr)
            sys.exit(1)
        print("Untagged: " + args[2])
    elif args[:1] == ["run"]:
        if failure in {"image_version", "image_guard"}:
            print(failure, file=sys.stderr)
            sys.exit(97)
        from core.refresh.job_builders import build_refresh_plan
        image_plan_keys = sorted(job.key for job in build_refresh_plan(scope="federal"))
        if failure == "image_plan_mismatch":
            image_plan_keys = [
                key for key in image_plan_keys if key != "federal-donor-search-rollup"
            ]
            image_plan_keys.append("federal-unexpected-image-job")
        print(json.dumps({
            "build_version": {"git_sha": args[-2], "built_at": args[-1]},
            "person_link_is_fillable": True,
            "repair_pair_alarm": True,
            "refresh_plan_job_keys": image_plan_keys,
        }, sort_keys=True))
    else:
        sys.exit(98)
else:
    sys.exit(99)
"""


def _write_command_stubs(tmp_path: Path) -> tuple[Path, Path]:
    stub_bin = tmp_path / "stub_bin"
    stub_bin.mkdir()
    command_log = tmp_path / "commands.jsonl"
    stub_program = STUB_PROGRAM.replace(
        '"CIVIBUS_STARTUP_CANARY": "skip",\n    },',
        '"CIVIBUS_STARTUP_CANARY": "skip",\n        "UNEXPECTED_SECRET": "top-secret",\n    },',
    )
    for command in ("bash", "git", "flyctl", "curl", "sleep", "docker"):
        stub = stub_bin / command
        stub.write_text(f"#!{sys.executable}\n{stub_program}", encoding="utf-8")
        stub.chmod(0o755)
    return stub_bin, command_log


def _run_deploy(
    tmp_path: Path,
    *,
    failure: str = "",
    pushed_refs: str = "default",
    digests: str = "default",
    evidence_dir: Path | None = None,
) -> tuple[subprocess.CompletedProcess[str], list[list[str]], Path]:
    stub_bin, command_log = _write_command_stubs(tmp_path)
    if evidence_dir is None:
        evidence_dir = tmp_path / "evidence"
        evidence_dir.mkdir()
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{stub_bin}:/usr/bin:/bin",
            "COMMAND_LOG": str(command_log),
            "REPO_ROOT": str(REPO_ROOT),
            "STUB_GIT_SHA": MIRROR_SHA,
            "STUB_FAILURE": failure,
            "STUB_PUSHED_REFS": pushed_refs,
            "STUB_DIGESTS": digests,
            "PYTHON_BIN": sys.executable,
            "PYTHONPATH": str(REPO_ROOT),
        }
    )
    result = subprocess.run(
        [
            "/bin/bash",
            str(DEPLOY_SCRIPT),
            "--evidence-dir",
            str(evidence_dir),
            "--dev-sha",
            DEV_SHA,
        ],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    invocations = []
    if command_log.exists():
        invocations = [json.loads(line) for line in command_log.read_text().splitlines()]
    return result, invocations, evidence_dir


def _machine_updates(invocations: list[list[str]]) -> list[list[str]]:
    return [argv for argv in invocations if argv[:3] == ["flyctl", "machine", "update"]]


def test_deploy_uses_exact_build_probe_update_and_verifier_contract(tmp_path: Path) -> None:
    """Prevent recurrence of the live unarmed scheduled-Machine deployment.

    Machine 859e0da479e678 was updated on July 31/August 1 with
    ``--skip-start`` and had no subsequent start event, producing
    ``AUTOMATIC_START_NOT_OBSERVED`` for the August 4 and August 11, 2026
    windows.
    """
    result, invocations, evidence_dir = _run_deploy(tmp_path)

    assert result.returncode == 0, result.stderr
    build_timestamp = (evidence_dir / "built_at.txt").read_text().strip()
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", build_timestamp)
    assert (evidence_dir / "checkout_head_sha.txt").read_text() == f"{MIRROR_SHA}\n"
    assert (evidence_dir / "dev_sha.txt").read_text() == f"{DEV_SHA}\n"
    assert [
        "flyctl",
        "deploy",
        "--build-only",
        "--push",
        "-c",
        "infra/fly/refresh.fly.toml",
        "--build-arg",
        f"CIVIBUS_GIT_SHA={DEV_SHA}",
        "--build-arg",
        f"CIVIBUS_BUILT_AT={build_timestamp}",
    ] in invocations
    machine_updates = _machine_updates(invocations)
    assert len(machine_updates) == 1
    assert "--skip-start" not in machine_updates[0]
    assert machine_updates == [
        [
            "flyctl",
            "machine",
            "update",
            MACHINE_ID,
            "-a",
            APP_NAME,
            "--image",
            IMAGE_TAG,
            "--yes",
        ]
    ]

    # The local copy of the pushed image must be dropped exactly once, AFTER the
    # content proof needs it and BEFORE the Machine update. Ordering is the whole
    # point: with the tag still in the local daemon, `flyctl machine update`
    # re-pushes it under a second deployment tag, minting a second manifest
    # digest and making verify_post_image_digest unpassable (civibus-n8r, which
    # failed both 2026-08-17 deploy attempts). Assert positions, not just
    # presence, so reordering these steps fails here instead of in production.
    local_image_removals = [argv for argv in invocations if argv[:3] == ["docker", "image", "rm"]]
    assert local_image_removals == [["docker", "image", "rm", IMAGE_TAG]]
    image_probe_index = max(index for index, argv in enumerate(invocations) if argv[:2] == ["docker", "run"])
    removal_index = invocations.index(["docker", "image", "rm", IMAGE_TAG])
    machine_update_index = invocations.index(machine_updates[0])
    assert image_probe_index < removal_index < machine_update_index

    verifier_path = str(REPO_ROOT / "infra/scripts/verify_refresh_machine.sh")
    verifier_calls = [argv for argv in invocations if argv[0:2] == ["bash", verifier_path]]
    assert verifier_calls == [
        [
            "bash",
            verifier_path,
            "--machines-json",
            str(evidence_dir / "pre_machines.json"),
            "--machine-config-json",
            str(evidence_dir / "pre_machine_config.json"),
            "--volumes-json",
            str(evidence_dir / "pre_volumes.json"),
            "--version-json",
            str(evidence_dir / "pre_version.json"),
        ],
        [
            "bash",
            verifier_path,
            "--expected-plan-json",
            str(evidence_dir / "expected_refresh_plan.txt"),
            "--image-proof-json",
            str(evidence_dir / "image_proof.txt"),
        ],
    ]
    post_machine = json.loads((evidence_dir / "post_machines.json").read_text())[0]
    assert post_machine["state"] == "started"
    assert not (evidence_dir / "post_verify_refresh_machine.txt").exists()
    expected_sanitized_env = {
        "CIVIBUS_ENV": "production",
        "POSTGRES_HOST": "civibus-db.internal",
        "POSTGRES_PORT": "5432",
        "POSTGRES_USER": "civibus",
        "POSTGRES_DB": "civibus",
        "CIVIBUS_REFRESH_DATA_DIR": "/data",
        "CIVIBUS_STARTUP_CANARY": "skip",
    }
    for phase in ("pre", "post"):
        machine_config = json.loads((evidence_dir / f"{phase}_machine_config.json").read_text())
        assert machine_config["env"] == expected_sanitized_env
        assert "UNEXPECTED_SECRET" not in machine_config["env"]

    image_probes = [argv for argv in invocations if argv[:2] == ["docker", "run"]]
    assert len(image_probes) == 1
    expected_probe_prefix = [
        "docker",
        "run",
        "--rm",
        "--platform",
        "linux/amd64",
        "--network",
        "none",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=16m",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "-e",
        "PYTHONDONTWRITEBYTECODE=1",
        "--entrypoint",
        "python",
    ]
    assert image_probes[0][: len(expected_probe_prefix)] == expected_probe_prefix
    assert IMAGE_DIGEST in image_probes[0]
    probe_text = " ".join(image_probes[0])
    assert "build_version_payload" in probe_text
    assert "person_link_is_fillable" in probe_text
    # The 2026-08-01 image shipped the durability guard but not the repair-pair
    # alarm, because this script predates the alarm's merge. The proof must
    # assert the alarm too, or a redeploy performed to ship it cannot show it did.
    for alarm_symbol in (
        "_record_repair_pair_alarm",
        "_append_repair_pair_alarms",
        "side_effects_repaired_by_job_key",
    ):
        assert alarm_symbol in probe_text, f"image proof must assert {alarm_symbol}"
    assert "core.refresh.job_builders" in probe_text
    assert "build_refresh_plan" in probe_text
    assert 'scope="federal"' in probe_text
    assert "refresh_plan_job_keys" in probe_text
    assert (evidence_dir / "pushed_image.txt").read_text() == f"{IMAGE_TAG}\n"
    assert (evidence_dir / "image_digest.txt").read_text() == f"{IMAGE_DIGEST}\n"
    image_proof = (evidence_dir / "image_proof.txt").read_text()
    assert f'"git_sha": "{DEV_SHA}"' in image_proof
    assert '"person_link_is_fillable": true' in image_proof
    assert '"repair_pair_alarm": true' in image_proof
    assert '"refresh_plan_job_keys": [' in image_proof
    expected_plan_proof = (evidence_dir / "expected_refresh_plan.txt").read_text()
    assert '"refresh_plan_job_keys": [' in expected_plan_proof
    assert '"federal-donor-search-rollup"' in expected_plan_proof

    assert [argv for argv in invocations if argv[:3] == ["docker", "image", "inspect"]] == [
        ["docker", "image", "inspect", IMAGE_TAG, "--format", "{{json .RepoDigests}}"]
    ]

    forbidden_fly_subcommands = {"exec", "start", "stop", "destroy"}
    assert not any(
        argv[:2] == ["flyctl", "machine"] and len(argv) > 2 and argv[2] in forbidden_fly_subcommands
        for argv in invocations
    )
    forbidden_update_flags = {
        "--schedule",
        "--restart",
        "--command",
        "-C",
        "--mount-point",
        "--region",
        "--regions",
        "--vm-size",
        "--vm-cpus",
        "--vm-memory",
    }
    assert forbidden_update_flags.isdisjoint(_machine_updates(invocations)[0])


@pytest.mark.parametrize(
    ("failure", "pushed_refs", "digests"),
    [
        ("dirty", "default", "default"),
        ("auth_whoami", "default", "default"),
        ("pre_verifier", "default", "default"),
        ("build", "default", "default"),
        ("", "missing", "default"),
        ("", "ambiguous", "default"),
        ("registry_auth", "default", "default"),
        ("image_pull", "default", "default"),
        ("", "default", "missing"),
        ("", "default", "ambiguous"),
        ("", "default", "malformed"),
        ("image_version", "default", "default"),
        ("image_guard", "default", "default"),
        ("image_plan_mismatch", "default", "default"),
    ],
)
def test_deploy_never_writes_machine_when_a_prewrite_gate_fails(
    tmp_path: Path,
    failure: str,
    pushed_refs: str,
    digests: str,
) -> None:
    result, invocations, _ = _run_deploy(
        tmp_path,
        failure=failure,
        pushed_refs=pushed_refs,
        digests=digests,
    )

    assert result.returncode != 0
    assert _machine_updates(invocations) == []


def test_deploy_checks_image_plan_before_machine_update(tmp_path: Path) -> None:
    result, invocations, _ = _run_deploy(tmp_path, failure="image_plan_mismatch")

    assert result.returncode != 0
    assert _machine_updates(invocations) == []
    assert "refresh plan job key mismatch" in result.stderr


def test_deploy_does_not_retry_or_fallback_after_machine_update_failure(tmp_path: Path) -> None:
    result, invocations, evidence_dir = _run_deploy(tmp_path, failure="update")

    assert result.returncode != 0
    assert len(_machine_updates(invocations)) == 1
    assert "invalid image identifier" in (evidence_dir / "machine_update.txt").read_text()
    assert not any(argv[:3] == ["flyctl", "machine", "start"] for argv in invocations)


def test_deploy_fails_closed_when_post_update_digest_differs_from_proven_image(
    tmp_path: Path,
) -> None:
    result, invocations, _ = _run_deploy(tmp_path, failure="post_image_mismatch")

    assert result.returncode != 0
    assert "does not match proven digest" in result.stderr
    assert len(_machine_updates(invocations)) == 1


def test_deploy_waits_for_delayed_registry_visibility_before_image_proof(tmp_path: Path) -> None:
    result, invocations, _ = _run_deploy(tmp_path, failure="registry_delay")

    assert result.returncode == 0, result.stderr
    assert [argv for argv in invocations if argv[:2] == ["docker", "pull"]] == [
        ["docker", "pull", IMAGE_TAG],
        ["docker", "pull", IMAGE_TAG],
    ]
    assert ["sleep", "2"] in invocations
    assert len(_machine_updates(invocations)) == 1


def test_deploy_accepts_a_single_pushed_image_reference_written_to_stderr(tmp_path: Path) -> None:
    result, invocations, evidence_dir = _run_deploy(tmp_path, pushed_refs="stderr")

    assert result.returncode == 0, result.stderr
    assert len(_machine_updates(invocations)) == 1
    assert (evidence_dir / "pushed_image.txt").read_text() == f"{IMAGE_TAG}\n"


def test_deploy_rejects_an_evidence_directory_inside_the_repository(tmp_path: Path) -> None:
    evidence_dir = REPO_ROOT / ".pytest_cache" / "deploy_evidence_inside_repository"
    shutil.rmtree(evidence_dir, ignore_errors=True)
    evidence_dir.mkdir(parents=True)
    try:
        result, invocations, _ = _run_deploy(tmp_path, evidence_dir=evidence_dir)
    finally:
        shutil.rmtree(evidence_dir, ignore_errors=True)

    assert result.returncode != 0
    assert "outside the repository" in result.stderr
    assert _machine_updates(invocations) == []


def test_deploy_preserves_an_existing_nonempty_evidence_directory(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "existing_evidence"
    evidence_dir.mkdir()
    existing_file = evidence_dir / "existing.txt"
    existing_file.write_text("preserve me", encoding="utf-8")

    stub_bin, _ = _write_command_stubs(tmp_path)
    environment = os.environ.copy()
    environment["PATH"] = f"{stub_bin}:/usr/bin:/bin"
    result = subprocess.run(
        [
            "/bin/bash",
            str(DEPLOY_SCRIPT),
            "--evidence-dir",
            str(evidence_dir),
            "--dev-sha",
            DEV_SHA,
        ],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode != 0
    assert "empty" in result.stderr
    assert existing_file.read_text(encoding="utf-8") == "preserve me"


@pytest.mark.parametrize("dev_sha", ["", "abc123", "A" * 40, "g" * 40])
def test_deploy_rejects_missing_or_invalid_dev_sha_before_external_calls(
    tmp_path: Path,
    dev_sha: str,
) -> None:
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    command = [
        "/bin/bash",
        str(DEPLOY_SCRIPT),
        "--evidence-dir",
        str(evidence_dir),
    ]
    if dev_sha:
        command.extend(["--dev-sha", dev_sha])

    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode != 0
    assert "--dev-sha" in result.stderr
    assert list(evidence_dir.iterdir()) == []
