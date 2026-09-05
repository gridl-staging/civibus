from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from functools import cache
from pathlib import Path
from typing import Any, Callable
from uuid import UUID

import pytest

from core.refresh import runner
from core.types.python.models import RefreshRun


REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_SCRIPT = REPO_ROOT / "infra/scripts/deploy_refresh_machine.sh"
VERIFIER_SCRIPT = REPO_ROOT / "infra/scripts/verify_refresh_machine.sh"
REGIONAL_PROFILE_PATH = REPO_ROOT / "infra/fly/regional_refresh_machine_profile.json"
MACHINE_ID = "859e0da479e678"
APP_NAME = "civibus-refresh"
MIRROR_SHA = "0123456789abcdef0123456789abcdef01234567"
DEV_SHA = "89abcdef0123456789abcdef0123456789abcdef"
IMAGE_TAG = f"registry.fly.io/{APP_NAME}:deployment-stage2"
IMAGE_DIGEST = f"registry.fly.io/{APP_NAME}@sha256:{'a' * 64}"
IMAGE_TAGGED_DIGEST = f"{IMAGE_TAG}@sha256:{'a' * 64}"
R36_MACHINE_ID = "080d391a2ed098"
R36_REFRESH_RUN_ID = "e00cb630-7024-4c5d-8c10-ef2a87e83db7"
R36_CANDIDATE_RECEIPT_SHA256 = "8d9833e9031bb9e3b8fde0510fe9da46c9481abe864cc4cb7524c76b8c6d2f8e"
R36_CANDIDATE_RECEIPT = {
    "canonical_receipt_git_sha": "f198d2d2aab360b62d55d6b61f2853f4a4bc10ac",
    "canonical_source_git_sha": "3df2e919388edb84b9f4f6cc33c496a8a8462937",
    "canonical_tree_git_sha": "61c293365ede61e0a43d42087c0ffdd70251631f",
    "image_proof": {
        "authority": {"code": "WA", "kind": "state"},
        "build_version": {
            "built_at": "2026-08-29T01:21:34Z",
            "git_sha": "a066a7fc4833e703b31b0b68ef7d8c846052bac7",
        },
        "cadence_clock": {
            "force_allowed": False,
            "job_due": "refresh_history_or_data_source_per_job",
            "scheduler": "machine_schedule",
        },
        "canary": {
            "execution_origin": "operator_attended",
            "job_keys": ["state-wa-contributions"],
            "schedule": None,
            "stop_on_failure": True,
        },
        "concurrency": {
            "cross_host_lock": "exact_authority_and_job_key_postgres_advisory_lock",
            "max_parallel_jobs": 1,
            "same_host_lock": "exact_authority_and_job_key_flock",
        },
        "execution_plan_id": "regional-wa-scheduled",
        "execution_plan_sha256": "21af08066e8ffa4964e8d2836572fcaa2b860770645d44875d60ba3b85d1c332",
        "scheduled": {
            "execution_origin": "scheduled",
            "job_keys": [
                "state-wa-contributions",
                "state-wa-expenditures",
                "state-wa-independent_expenditures",
                "state-wa-loans",
            ],
            "schedule": "daily",
            "stop_on_failure": False,
        },
    },
    "machine_config_sha256": "620ad2707365938ba628433d254f8ef9d229a075c2c880435edc1f947379abad",
    "produced_image_tagged_digest": (
        "registry.fly.io/civibus-refresh:deployment-01M15HQ6D2FQD7S0Z2D35JTZKB"
        "@sha256:65f4acf2ff3fd89588120a3137f88bf63e476b82540ed389e807f57d9c691c86"
    ),
    "profile_sha256": "2f7fdbe1e97473479617212fa2cc6a22f6f4482011856f0583d9f757c2c4760f",
    "qualification_kind": "authority_refresh_image_candidate",
    "schema_version": 2,
    "source_git_sha": "a066a7fc4833e703b31b0b68ef7d8c846052bac7",
    "source_tree_git_sha": "a8b5f18fcfbc0e3f9d2de86f6c6a9da6528e0715",
}
R36_MARKER_SHA256 = {
    "canary_mode.json": "6035722c87a9f1fc4f826779c3699c4b936476bc1c2fab6a8386b4920a117500",
    "create_ownership.json": "e978036a4e7292c6b0d6d278533501cadf8de3d6ae284f65ad2c4037c1ad59f9",
    "machine_ownership.json": "d6a8f0c7508b459a635dd9ac19e9631371719ec5bf253f4292991fbb0c978ce8",
    "provision.json": "7e022053d46dc9fcd3d2986b982dba1a5086eed8caa4053b59754b5787f839f4",
    "rollback_attempt.json": "63c3cab2e8896193eaaca989faa75adbdf1cb2c5ff5d566c1e81fd92d7cbdaf0",
    "start_attempt.json": "268b01ef404b97dc4616d323fe4b40a359023f2d3da213d09157ce53793672e2",
}


STUB_PROGRAM = r"""import json
import os
import pathlib
import stat
import subprocess
import sys
import time

command = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ["COMMAND_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps([command, *args]) + "\n")

if command == "bash":
    for option in ("--profile-json", "--candidate-receipt-json"):
        if option in args:
            path = pathlib.Path(args[args.index(option) + 1])
            if "/.capture." in str(path) and stat.S_IMODE(path.stat().st_mode) != 0o600:
                sys.exit(89)
    os.execv("/bin/bash", ["/bin/bash", *args])

failure = os.environ.get("STUB_FAILURE", "")
command_history = [
    json.loads(line)
    for line in pathlib.Path(os.environ["COMMAND_LOG"]).read_text().splitlines()
]
machine_was_updated = any(
    argv[:3] == ["flyctl", "machine", "update"] for argv in command_history
)
regional_app_created = any(argv[:3] == ["flyctl", "apps", "create"] for argv in command_history)
regional_app_destroyed = any(argv[:3] == ["flyctl", "apps", "destroy"] for argv in command_history)
regional_machine_created = any(argv[:3] == ["flyctl", "machine", "create"] for argv in command_history)
regional_machine_started = any(argv[:3] == ["flyctl", "machine", "start"] for argv in command_history)
regional_start_wait_history = [
    argv[2] for argv in command_history
    if argv[:2] == ["flyctl", "machine"] and argv[2] in {"start", "wait"}
]
regional_machine_waited = bool(regional_start_wait_history and regional_start_wait_history[-1] == "wait")
regional_machine_stopped = any(argv[:3] == ["flyctl", "machine", "stop"] for argv in command_history)
regional_machine_destroyed = any(argv[:3] == ["flyctl", "machine", "destroy"] for argv in command_history)
canary_marker = pathlib.Path(os.environ.get("STUB_LIFECYCLE_DIR", "")) / "canary_mode.json"
regional_canary_mode = os.environ.get("STUB_ACTION", "").startswith("create-canary") or canary_marker.is_file()
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
    elif args == ["rev-parse", os.environ.get("STUB_BASE_SOURCE_SHA", "") + "^{tree}"]:
        print("e" * 40 if failure == "canonical_source_tree" else os.environ["STUB_BASE_TREE_SHA"])
    elif args == ["rev-parse", os.environ.get("STUB_BASE_RECEIPT_SHA", "") + "^{tree}"]:
        print("e" * 40 if failure == "canonical_receipt_tree" else os.environ["STUB_BASE_TREE_SHA"])
    elif args == ["rev-parse", os.environ.get("STUB_BASE_RECEIPT_SHA", "") + "^"]:
        print(
            "f" * 40
            if failure == "canonical_receipt_parent"
            else os.environ["STUB_BASE_SOURCE_SHA"]
        )
    elif args == ["rev-parse", "--verify", os.environ.get("STUB_CANDIDATE_SHA", "") + "^{commit}"]:
        if failure == "candidate_unresolved":
            sys.exit(1)
        print(os.environ["STUB_CANDIDATE_SHA"])
    elif args == ["rev-parse", os.environ.get("STUB_CANDIDATE_SHA", "") + "^{tree}"]:
        print("e" * 40 if failure == "candidate_tree" else os.environ["STUB_CANDIDATE_TREE_SHA"])
    elif args == [
        "merge-base",
        "--is-ancestor",
        os.environ["STUB_BASE_RECEIPT_SHA"],
        os.environ["STUB_CANDIDATE_SHA"],
    ]:
        if failure == "candidate_ancestry":
            sys.exit(1)
    elif args == [
        "diff", "--name-only", "--no-renames", "-z",
        os.environ["STUB_BASE_RECEIPT_SHA"], os.environ["STUB_CANDIDATE_SHA"],
    ]:
        if failure == "candidate_diff":
            sys.exit(1)
        for changed_path in os.environ.get("STUB_CHANGED_PATHS", "core/refresh/runner.py").split(","):
            if changed_path:
                sys.stdout.write(changed_path + "\0")
    else:
        sys.exit(91)
elif command == "curl":
    if os.environ.get("STUB_ACTION") == "capture-invariance":
        url = args[-1]
        if url.endswith("/api/health/content"):
            print(json.dumps({"healthy": failure != "regional_invariance_unhealthy_public"}))
        else:
            revision = "6" * 40 if failure == "regional_invariance_split_revision" and url.endswith(
                "/version.json"
            ) else "4" * 40
            print(json.dumps({"git_sha": revision, "built_at": "2026-08-29T00:00:00Z"}))
    else:
        print(json.dumps({"git_sha": "previous", "built_at": "previous"}))
elif command == "psql":
    if failure == "regional_invariance_database_probe":
        sys.exit(96)
    print(json.dumps({
        "schema_version": 1,
        "application_name": "civibus:regional-invariance-capture",
        "transaction_read_only": "off" if failure == "regional_invariance_write_enabled" else "on",
        "default_transaction_read_only": "on",
        "database_name": "foreign" if failure == "regional_invariance_foreign_database" else "civibus",
        "server_address": "fdaa::1",
        "server_port": 5432,
        "running_refresh_rows": 1 if failure == "regional_invariance_running_rows" else 0,
        "active_refresh_backends": 1 if failure == "regional_invariance_active_backend" else 0,
        "long_idle_transactions": 1 if failure == "regional_invariance_long_idle" else 0,
        "ungranted_locks": 1 if failure == "regional_invariance_ungranted_lock" else 0,
        "advisory_locks": 1 if failure == "regional_invariance_advisory_lock" else 0,
    }))
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
        if (
            os.environ.get("STUB_REQUIRE_DOCKER_HOST") == "1"
            and os.environ.get("DOCKER_HOST") != os.environ["STUB_DOCKER_CONTEXT_HOST"]
        ):
            print("docker is unavailable to build the deployment image", file=sys.stderr)
            sys.exit(98)
        if failure == "build":
            sys.exit(93)
        pushed_refs = os.environ.get("STUB_PUSHED_REFS", "default")
        if pushed_refs == "default":
            print(
                "pushing manifest for "
                "registry.fly.io/civibus-refresh:deployment-stage2@sha256:"
                + "a" * 64
            )
            print("image: registry.fly.io/civibus-refresh:deployment-stage2")
        elif pushed_refs == "stderr":
            print(
                "pushing manifest for "
                "registry.fly.io/civibus-refresh:deployment-stage2@sha256:"
                + "a" * 64,
                file=sys.stderr,
            )
            print("image: registry.fly.io/civibus-refresh:deployment-stage2", file=sys.stderr)
        elif pushed_refs == "fly_tag_digest":
            print("deployment-stage2: digest: sha256:" + "a" * 64 + " size: 3061")
            print("image: registry.fly.io/civibus-refresh:deployment-stage2")
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
    elif args == ["apps", "list", "--json"]:
        if failure == "regional_historical_app_absent":
            print("[]")
            raise SystemExit(0)
        if failure == "regional_historical_app_ambiguous":
            print(json.dumps([
                {"Name": "civibus-regional-refresh", "ID": "civibus-regional-refresh"},
                {"Name": "civibus-regional-refresh", "ID": "civibus-regional-refresh"},
            ]))
            raise SystemExit(0)
        if failure == "regional_apps_not_list" and not regional_app_created:
            print(json.dumps({"apps": []}))
            raise SystemExit(0)
        if failure == "regional_malformed_apps" and not regional_app_created:
            print(json.dumps(["malformed-row"]))
            raise SystemExit(0)
        if failure == "regional_apps_missing_identity" and not regional_app_created:
            print(json.dumps([{"Name": "another-app"}]))
            raise SystemExit(0)
        if failure == "regional_preexisting_app_id_only" and not regional_app_created:
            print(json.dumps([{"Name": "another-app", "ID": "civibus-regional-refresh"}]))
            raise SystemExit(0)
        present = (
            (regional_app_created and not regional_app_destroyed)
            or (failure == "regional_lingering_app" and regional_app_created)
            or (failure == "regional_preexisting_app" and not regional_app_created)
        )
        print(json.dumps([{
            "Name": "civibus-regional-refresh",
            "ID": "civibus-regional-refresh",
        }] if present else []))
    elif args == ["apps", "create", "civibus-regional-refresh", "--org", "personal", "--json", "--yes"]:
        if failure == "regional_app_create":
            sys.exit(96)
        print(json.dumps({"Name": "civibus-regional-refresh"}))
    elif args == ["secrets", "import", "-a", "civibus-regional-refresh"]:
        if "POSTGRES_PASSWORD=" not in sys.stdin.read():
            sys.exit(96)
        if failure == "regional_secret_import":
            print("secret import failed", file=sys.stderr)
            sys.exit(96)
        print("secret staged; POSTGRES_PASSWORD=do-not-log-this")
    elif args[:3] == ["machine", "create", os.environ.get("STUB_REGIONAL_IMAGE_SELECTOR", "")]:
        if failure == "regional_machine_create":
            sys.exit(96)
        config_path = pathlib.Path(args[args.index("--machine-config") + 1])
        if (
            not config_path.is_file()
            or config_path.is_symlink()
            or stat.S_IMODE(config_path.stat().st_mode) != 0o600
            or config_path.suffix != ".json"
        ):
            print(
                "regional Machine config must be a regular non-symlink mode-0600 .json file",
                file=sys.stderr,
            )
            sys.exit(96)
        actual_config = json.loads(config_path.read_text(encoding="utf-8"))
        profile = json.loads(pathlib.Path(os.environ["REGIONAL_PROFILE_PATH"]).read_text())
        expected_config = profile["machine"]["config"]
        if regional_canary_mode:
            expected_config["init"]["cmd"] = profile["canary"]["command"]
            expected_config.pop("schedule", None)
            plan = profile["execution_plan"]
            authority = plan["authority"]
            expected_config["metadata"] = {
                "civibus_authority": f"{authority['kind']}/{authority['code']}",
                "civibus_execution_plan": plan["plan_id"],
                "civibus_job_key": plan["canary"]["job_keys"][0],
                "civibus_profile": profile["profile_id"],
            }
        if actual_config != expected_config:
            print("unexpected regional Machine create config", file=sys.stderr)
            sys.exit(96)
        print("created abc123")
    elif args == ["status", "-a", "civibus-regional-refresh", "--json"]:
        predestroy_identity_drift = failure == "regional_predestroy_wrong_org" and regional_machine_destroyed
        poststop_identity_drift = (
            failure == "regional_post_stop_wrong_org"
            and regional_machine_stopped
            and not regional_machine_destroyed
        )
        postwait_identity_drift = (
            failure == "regional_create_post_wait_identity_drift"
            and regional_machine_waited
        )
        print(json.dumps({
            "Name": "civibus-regional-refresh",
            "ID": (
                "wrong-app"
                if failure == "regional_wrong_app" or postwait_identity_drift
                else "civibus-regional-refresh"
            ),
            "Organization": {
                "Slug": (
                    "wrong"
                    if failure == "regional_wrong_org" or predestroy_identity_drift or poststop_identity_drift
                    else "personal"
                ),
                "ID": (
                    "wrong-org"
                    if failure == "regional_wrong_org" or predestroy_identity_drift or poststop_identity_drift
                    else "NP9vVpRwXy9omT9Lbem2Q7gOw2IyyZXDg"
                ),
            },
        }))
    elif args == ["machines", "list", "-a", "civibus-regional-refresh", "--json"]:
        if regional_machine_created and (
            not regional_machine_destroyed or failure == "regional_lingering_machine"
        ):
            state = (
                "indeterminate"
                if failure in {"regional_indeterminate_state", "regional_wrong_machine_state"}
                else "created"
                if failure == "regional_create_post_wait_wrong_state" and regional_machine_waited
                else "created"
                if failure == "regional_create_transient_created" and not regional_machine_waited
                else "started" if failure == "regional_rollback_started" and not regional_machine_stopped
                else "started" if failure == "regional_post_stop_started" and regional_machine_stopped
                else "stopped" if regional_machine_waited
                else "started" if regional_machine_started and not regional_machine_stopped else "stopped"
            )
            machine_row = {
                "id": (
                    "def456"
                    if failure == "regional_wrong_machine_id"
                    or (failure == "regional_create_post_wait_marker_mismatch" and regional_machine_waited)
                    else "abc123"
                ),
                "name": "wrong-name" if failure == "regional_wrong_machine_name" else "regional-wa-scheduled",
                "region": "iad" if failure == "regional_wrong_machine_region" else "sjc",
                "state": state,
            }
            regional_image = os.environ["STUB_REGIONAL_IMAGE"]
            image_with_tag, image_digest = regional_image.rsplit("@", 1)
            image_repository, image_tag = image_with_tag.rsplit(":", 1)
            image_registry, image_repository = image_repository.split("/", 1)
            machine_row["image_ref"] = {
                "registry": image_registry,
                "repository": image_repository,
                "tag": image_tag,
                "digest": image_digest,
            }
            if regional_machine_started and regional_machine_waited:
                now_ms = int(time.time() * 1000)
                start_event = {
                    "type": "start",
                    "status": "started",
                    "source": "user",
                    "timestamp": now_ms - 2_000,
                }
                exit_event = {
                    "type": "exit",
                    "status": "stopped",
                    "source": "flyd",
                    "timestamp": now_ms - 1_000,
                    "request": {
                        "exit_event": {
                            "exit_code": 1 if failure == "regional_canary_exit_nonzero" else 0,
                        }
                    },
                }
                if failure == "regional_canary_exit_missing":
                    machine_row["events"] = [start_event]
                elif failure == "regional_canary_exit_ambiguous":
                    machine_row["events"] = [exit_event, dict(exit_event), start_event]
                else:
                    machine_row["events"] = [exit_event, start_event]
            rows = [machine_row]
            if failure in {"regional_extra_machine", "regional_create_ambiguity"} or (
                failure == "regional_create_post_wait_ambiguous" and regional_machine_waited
            ):
                rows.append({
                    "id": "def456", "name": "unexpected", "region": "sjc", "state": "stopped"
                })
            print(json.dumps(rows))
        else:
            print("[]")
    elif args == ["machine", "status", "abc123", "-a", "civibus-regional-refresh", "--display-config"]:
        profile = json.loads(pathlib.Path(os.environ["REGIONAL_PROFILE_PATH"]).read_text())
        config = profile["machine"]["config"]
        if regional_canary_mode:
            config["init"]["cmd"] = profile["canary"]["command"]
            config.pop("schedule", None)
            plan = profile["execution_plan"]
            authority = plan["authority"]
            config["metadata"] = {
                "civibus_authority": f"{authority['kind']}/{authority['code']}",
                "civibus_execution_plan": plan["plan_id"],
                "civibus_job_key": plan["canary"]["job_keys"][0],
                "civibus_profile": profile["profile_id"],
            }
        config["image"] = (
            "registry.fly.io/civibus-refresh:wrong@sha256:" + "f" * 64
            if failure in {"regional_image_drift", "regional_create_post_wait_image_drift"}
            or (failure == "regional_post_start_drift" and regional_machine_started)
            else os.environ["STUB_REGIONAL_IMAGE"]
        )
        if failure in {"regional_flyctl_equivalent_defaults", "regional_create_transient_created"}:
            for key in ("auto_destroy", "files", "mounts", "services"):
                config.pop(key, None)
            config["dns"] = {}
        if failure == "regional_auto_destroy_true":
            config["auto_destroy"] = True
        nonlist_default = {
            "regional_files_nonlist": "files",
            "regional_mounts_nonlist": "mounts",
            "regional_services_nonlist": "services",
        }.get(failure)
        if nonlist_default:
            config[nonlist_default] = {}
        nonempty_default = {
            "regional_files_nonempty": "files",
            "regional_mounts_nonempty": "mounts",
            "regional_services_nonempty": "services",
        }.get(failure)
        if nonempty_default:
            config[nonempty_default] = [{"unexpected": "material"}]
        if failure == "regional_dns_nonmapping":
            config["dns"] = []
        if failure == "regional_dns_nonempty":
            config["dns"] = {"nameservers": ["fdaa::3"]}
        if failure == "regional_missing_material_key":
            config.pop("restart")
        if failure == "regional_changed_material_value":
            config["restart"] = {"policy": "always"}
        if failure == "regional_create_post_wait_config_drift":
            config["restart"] = {"policy": "always"}
        if failure == "regional_unexpected_top_level_key":
            config["checks"] = {}
        if failure == "regional_config_secret":
            config["env"]["UNEXPECTED_SECRET"] = "do-not-log-this"
        print(json.dumps(config))
    elif args == ["machine", "start", "abc123", "-a", "civibus-regional-refresh"]:
        if failure == "regional_start_failure":
            sys.exit(96)
        print("started")
    elif args == [
        "machine", "wait", "abc123", "-a", "civibus-regional-refresh",
        "--state", "stopped", "--wait-timeout", "30m",
    ]:
        lifecycle_dir = pathlib.Path(os.environ["STUB_LIFECYCLE_DIR"])
        expected_markers = {
            "create_ownership.json": ("regional_create_ownership", None),
            "machine_ownership.json": ("regional_machine_ownership", "abc123"),
        }
        if regional_canary_mode:
            expected_markers["canary_mode.json"] = ("regional_canary_mode", "abc123")
        for marker_name, (kind, machine_id) in expected_markers.items():
            marker_path = lifecycle_dir / marker_name
            if not marker_path.is_file() or marker_path.is_symlink():
                sys.exit(97)
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
            if marker.get("kind") != kind or marker.get("machine_id") != machine_id:
                sys.exit(97)
        if failure in {
            "regional_canary_wait_failure",
            "regional_create_wait_nonzero",
            "regional_create_wait_timeout",
        }:
            print("bounded stopped-state wait failed", file=sys.stderr)
            sys.exit(96)
        print("stopped")
    elif args == ["machine", "stop", "abc123", "-a", "civibus-regional-refresh"]:
        if failure == "regional_stop_failure":
            sys.exit(96)
        print("stopped")
    elif args == ["machine", "destroy", "abc123", "-a", "civibus-regional-refresh"]:
        if failure == "regional_destroy_failure":
            sys.exit(96)
        print("destroyed")
    elif args == ["apps", "destroy", "civibus-regional-refresh", "--yes"]:
        if failure == "regional_app_destroy_failure":
            sys.exit(96)
        print("destroyed app")
    elif args == ["volumes", "list", "-a", "civibus-regional-refresh", "--json"]:
        print(json.dumps([{"id": "vol_owned_elsewhere"}] if failure == "regional_extra_volume" else []))
    else:
        sys.exit(96)
elif command == "sleep":
    pass
elif command == "docker":
    if args == ["context", "show"]:
        print("colima")
    elif args == ["context", "inspect", "colima", "--format", "{{.Endpoints.docker.Host}}"]:
        print(os.environ.get("STUB_DOCKER_CONTEXT_HOST", "unix:///tmp/colima/docker.sock"))
    elif args[:3] == ["buildx", "imagetools", "inspect"]:
        if failure == "regional_registry_manifest_absent":
            print(f"ERROR: {args[3]}: not found", file=sys.stderr)
            sys.exit(90)
        digest_character = "b" if failure == "regional_registry_manifest_mismatch" else "a"
        print(f"Name: {args[3]}")
        print("MediaType: application/vnd.oci.image.manifest.v1+json")
        print("Digest: sha256:" + digest_character * 64)
    elif args[:1] == ["pull"]:
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
        if len(args) >= 2 and args[-2] == os.environ.get("STUB_CANDIDATE_SHA"):
            if failure == "regional_image_plan_mismatch":
                profile = json.loads(pathlib.Path(os.environ["REGIONAL_PROFILE_PATH"]).read_text())
                plan = profile["execution_plan"]
                scheduled = dict(plan["scheduled"])
                scheduled["job_keys"] = [*scheduled["job_keys"][:-1], "state-wa-unexpected"]
                print(json.dumps({
                    "authority": plan["authority"],
                    "build_version": {"git_sha": args[-2], "built_at": "2026-08-28T00:00:00Z"},
                    "cadence_clock": plan["cadence_clock"],
                    "canary": plan["canary"],
                    "concurrency": plan["concurrency"],
                    "execution_plan_id": plan["plan_id"],
                    "execution_plan_sha256": "0" * 64,
                    "scheduled": scheduled,
                }, sort_keys=True))
                raise SystemExit(0)
            probe = subprocess.run(
                [sys.executable, "-c", args[args.index("-c") + 1], args[-2], args[-1]],
                cwd=os.environ["REPO_ROOT"],
                env={
                    **os.environ,
                    "CIVIBUS_GIT_SHA": args[-2],
                    "CIVIBUS_BUILT_AT": "2026-08-28T00:00:00Z",
                },
                capture_output=True,
                text=True,
                check=False,
            )
            sys.stdout.write(probe.stdout)
            sys.stderr.write(probe.stderr)
            raise SystemExit(probe.returncode)
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
    for command in ("bash", "git", "flyctl", "curl", "psql", "sleep", "docker"):
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
            "REGIONAL_PROFILE_PATH": str(REGIONAL_PROFILE_PATH),
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


def _run_machine_image_selector(
    proven_identity: str = IMAGE_TAGGED_DIGEST,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "/bin/bash",
            str(DEPLOY_SCRIPT),
            "--select-machine-image",
            proven_identity,
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )


def _run_invalid_regional_cli(
    tmp_path: Path,
    args: list[str],
) -> tuple[subprocess.CompletedProcess[str], list[list[str]]]:
    stub_bin, command_log = _write_command_stubs(tmp_path)
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{stub_bin}:/usr/bin:/bin",
            "COMMAND_LOG": str(command_log),
            "PYTHON_BIN": sys.executable,
            "POSTGRES_HOST": "127.0.0.1",
            "POSTGRES_PORT": "16599",
            "POSTGRES_USER": "civibus",
            "POSTGRES_PASSWORD": "do-not-log-this",
            "POSTGRES_DB": "civibus",
        }
    )
    result = subprocess.run(
        ["/bin/bash", str(DEPLOY_SCRIPT), *args],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    invocations = [json.loads(line) for line in command_log.read_text().splitlines()] if command_log.exists() else []
    return result, invocations


def _canonical_sha256(value: object) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def _authority_image_proof(profile: dict[str, Any], source: str) -> dict[str, Any]:
    plan = profile["execution_plan"]
    return {
        "authority": plan["authority"],
        "build_version": {"git_sha": source, "built_at": "2026-08-28T00:00:00Z"},
        "cadence_clock": plan["cadence_clock"],
        "canary": plan["canary"],
        "concurrency": plan["concurrency"],
        "execution_plan_id": plan["plan_id"],
        "execution_plan_sha256": _canonical_sha256(plan),
        "scheduled": plan["scheduled"],
    }


def _regional_candidate_receipt(profile: dict[str, Any]) -> dict[str, Any]:
    canonical = profile["canonical_source"]
    source = "4" * 40
    return {
        "canonical_receipt_git_sha": canonical["receipt_git_sha"],
        "canonical_source_git_sha": canonical["source_git_sha"],
        "canonical_tree_git_sha": canonical["tree_git_sha"],
        "image_proof": _authority_image_proof(profile, source),
        "machine_config_sha256": profile["machine"]["config_sha256"],
        "produced_image_tagged_digest": IMAGE_TAGGED_DIGEST,
        "profile_sha256": _canonical_sha256(profile),
        "qualification_kind": "authority_refresh_image_candidate",
        "schema_version": 2,
        "source_git_sha": source,
        "source_tree_git_sha": "5" * 40,
    }


@pytest.mark.parametrize(
    "args",
    [
        ["--regional-action"],
        [
            "--regional-action",
            "invalid",
            "--profile-json",
            "p",
            "--candidate-receipt-json",
            "r",
            "--lifecycle-dir",
            "l",
        ],
        ["--regional-action", "start-once"],
        [
            "--regional-action",
            "create-stopped",
            "--profile-json",
            "p",
            "--candidate-receipt-json",
            "r",
            "--lifecycle-dir",
            "l",
        ],
        [
            "--regional-action",
            "start-once",
            "--profile-json",
            "p",
            "--candidate-receipt-json",
            "r",
            "--lifecycle-dir",
            "l",
            "--secret-file",
            "s",
        ],
        [
            "--regional-action",
            "create-canary-stopped",
            "--profile-json",
            "p",
            "--candidate-receipt-json",
            "r",
            "--lifecycle-dir",
            "l",
        ],
        [
            "--regional-action",
            "start-canary-once",
            "--profile-json",
            "p",
            "--candidate-receipt-json",
            "r",
            "--lifecycle-dir",
            "l",
            "--secret-file",
            "s",
        ],
        [
            "--regional-action",
            "rollback",
            "--profile-json",
            "p",
            "--profile-json",
            "p2",
            "--candidate-receipt-json",
            "r",
            "--lifecycle-dir",
            "l",
        ],
        ["--regional-action", "rollback", "--unknown", "x"],
        ["--regional-action", "rollback", "--profile-json"],
        ["--regional-action", "rollback", "--profile-json", ""],
    ],
    ids=(
        "missing-action",
        "invalid-action",
        "missing-required-options",
        "create-missing-secret",
        "secret-on-start",
        "canary-create-missing-secret",
        "secret-on-canary-start",
        "duplicate-option",
        "unknown-option",
        "missing-value",
        "empty-value",
    ),
)
def test_regional_cli_rejects_invalid_or_ambiguous_contract_before_owner_calls(
    tmp_path: Path,
    args: list[str],
) -> None:
    result, invocations = _run_invalid_regional_cli(tmp_path, args)

    assert result.returncode != 0
    assert not any(row[0] in {"flyctl", "docker", "git", "curl"} for row in invocations)


def _run_qualification_only(
    tmp_path: Path,
    *,
    failure: str = "",
    profile_path: Path = REGIONAL_PROFILE_PATH,
    source_sha: str = MIRROR_SHA,
    produced_image: str = IMAGE_TAGGED_DIGEST,
    receipt_path: Path | None = None,
    manifest_paths: list[str] | None = None,
    manifest_updates: dict[str, Any] | None = None,
    manifest_remove: str = "",
    duplicate_manifest_key: bool = False,
    actual_paths: list[str] | None = None,
    extra_args: tuple[str, ...] = (),
    build_qualify: bool = False,
    head_sha: str | None = None,
    require_docker_context: bool = False,
    pushed_refs: str = "default",
) -> tuple[subprocess.CompletedProcess[str], list[list[str]], Path]:
    stub_bin, command_log = _write_command_stubs(tmp_path)
    if receipt_path is None:
        receipt_path = tmp_path / "regional_image_candidate_receipt.json"
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    canonical_source = profile["canonical_source"]
    candidate_tree_sha = "d" * 40
    manifest = {
        "authority": profile["execution_plan"]["authority"],
        "baseline_receipt_git_sha": canonical_source["receipt_git_sha"],
        "baseline_source_git_sha": canonical_source["source_git_sha"],
        "baseline_tree_git_sha": canonical_source["tree_git_sha"],
        "candidate_git_sha": source_sha,
        "candidate_tree_git_sha": candidate_tree_sha,
        "changed_paths": ["core/refresh/runner.py"] if manifest_paths is None else manifest_paths,
        "execution_plan_id": profile["execution_plan"]["plan_id"],
        "manifest_kind": "authority_refresh_candidate",
        "profile_sha256": _canonical_sha256(profile),
        "schema_version": 2,
    }
    if manifest_updates:
        manifest.update(manifest_updates)
    if manifest_remove:
        del manifest[manifest_remove]
    manifest_path = tmp_path / "candidate_manifest.json"
    manifest_text = json.dumps(manifest)
    if duplicate_manifest_key:
        manifest_text = manifest_text[:-1] + ', "schema_version": 2}'
    manifest_path.write_text(manifest_text, encoding="utf-8")
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{stub_bin}:/usr/bin:/bin",
            "COMMAND_LOG": str(command_log),
            "REPO_ROOT": str(REPO_ROOT),
            "REGIONAL_PROFILE_PATH": str(profile_path),
            "STUB_BASE_RECEIPT_SHA": canonical_source["receipt_git_sha"],
            "STUB_BASE_SOURCE_SHA": canonical_source["source_git_sha"],
            "STUB_BASE_TREE_SHA": canonical_source["tree_git_sha"],
            "STUB_CANDIDATE_SHA": source_sha,
            "STUB_CANDIDATE_TREE_SHA": candidate_tree_sha,
            "STUB_CHANGED_PATHS": ",".join(["core/refresh/runner.py"] if actual_paths is None else actual_paths),
            "STUB_FAILURE": failure,
            "STUB_GIT_SHA": source_sha if head_sha is None else head_sha,
            "STUB_DIGESTS": "default",
            "STUB_PUSHED_REFS": pushed_refs,
            "PYTHON_BIN": sys.executable,
        }
    )
    if require_docker_context:
        environment.pop("DOCKER_HOST", None)
        environment["STUB_REQUIRE_DOCKER_HOST"] = "1"
        environment["STUB_DOCKER_CONTEXT_HOST"] = "unix:///tmp/colima/docker.sock"
    evidence_dir = tmp_path / "regional_build_evidence"
    if build_qualify:
        evidence_dir.mkdir()
        if receipt_path == tmp_path / "regional_image_candidate_receipt.json":
            receipt_path = evidence_dir / receipt_path.name
        command = [
            "/bin/bash",
            str(DEPLOY_SCRIPT),
            "--regional-build-qualify",
            "--profile-json",
            str(profile_path),
            "--candidate-manifest-json",
            str(manifest_path),
            "--evidence-dir",
            str(evidence_dir),
            "--candidate-receipt-json",
            str(receipt_path),
            *extra_args,
        ]
    else:
        command = [
            "/bin/bash",
            str(DEPLOY_SCRIPT),
            "--qualify-only",
            "--profile-json",
            str(profile_path),
            "--candidate-manifest-json",
            str(manifest_path),
            "--produced-image-tagged-digest",
            produced_image,
            "--candidate-receipt-json",
            str(receipt_path),
            *extra_args,
        ]
    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    invocations = []
    if command_log.exists():
        invocations = [json.loads(line) for line in command_log.read_text().splitlines()]
    return result, invocations, receipt_path


def test_qualification_only_writes_verifier_consumable_local_candidate_without_external_or_machine_actions(
    tmp_path: Path,
) -> None:
    result, invocations, receipt_path = _run_qualification_only(tmp_path)

    assert result.returncode == 0, result.stderr
    profile = json.loads(REGIONAL_PROFILE_PATH.read_text(encoding="utf-8"))
    canonical_source = profile["canonical_source"]
    image_proof = _authority_image_proof(profile, MIRROR_SHA)
    assert json.loads(receipt_path.read_text(encoding="utf-8")) == {
        "canonical_receipt_git_sha": canonical_source["receipt_git_sha"],
        "canonical_source_git_sha": canonical_source["source_git_sha"],
        "canonical_tree_git_sha": canonical_source["tree_git_sha"],
        "image_proof": image_proof,
        "machine_config_sha256": profile["machine"]["config_sha256"],
        "produced_image_tagged_digest": IMAGE_TAGGED_DIGEST,
        "profile_sha256": _canonical_sha256(profile),
        "qualification_kind": "authority_refresh_image_candidate",
        "schema_version": 2,
        "source_git_sha": MIRROR_SHA,
        "source_tree_git_sha": "d" * 40,
    }
    assert not any(argv[0] in {"curl", "flyctl"} for argv in invocations)
    assert not any(
        argv[:3] in (["flyctl", "machine", "create"], ["flyctl", "machine", "update"]) for argv in invocations
    )
    image_probes = [argv for argv in invocations if argv[:2] == ["docker", "run"]]
    assert len(image_probes) == 1
    assert image_probes[0][:12] == [
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
    ]
    probe_text = " ".join(image_probes[0])
    for contract_text in (
        "from core.refresh.authority_execution_plan import select_execution_plan_jobs",
        "from core.refresh.authority_operations_profile import (",
        "from core.refresh.job_builders import build_refresh_plan",
        'scope="all"',
        'mode="scheduled"',
        'mode="canary"',
        "expected_image_plan_proof",
    ):
        assert contract_text in probe_text
    verifier_invocations = [argv for argv in invocations if argv[:2] == ["bash", str(VERIFIER_SCRIPT)]]
    assert len(verifier_invocations) == 2
    assert "--profile-only" in verifier_invocations[0]
    assert "--candidate-receipt-json" in verifier_invocations[1]
    assert "--profile-json" in verifier_invocations[1]


def test_regional_build_qualify_reuses_immutable_build_owner_without_any_machine_or_app_action(
    tmp_path: Path,
) -> None:
    result, invocations, receipt_path = _run_qualification_only(tmp_path, build_qualify=True)

    assert result.returncode == 0, result.stderr
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["source_git_sha"] == MIRROR_SHA
    assert receipt["produced_image_tagged_digest"] == IMAGE_TAGGED_DIGEST
    assert receipt["image_proof"]["canary"]["job_keys"] == ["state-wa-contributions"]
    assert receipt["image_proof"]["scheduled"]["job_keys"] == [
        "state-wa-contributions",
        "state-wa-expenditures",
        "state-wa-independent_expenditures",
        "state-wa-loans",
    ]
    fly_calls = [row for row in invocations if row[0] == "flyctl"]
    assert [row[:3] for row in fly_calls] == [
        ["flyctl", "auth", "whoami"],
        ["flyctl", "deploy", "--build-only"],
        ["flyctl", "auth", "docker"],
    ]
    deploy_call = next(row for row in fly_calls if row[:3] == ["flyctl", "deploy", "--build-only"])
    assert "--push" in deploy_call
    assert "--local-only" in deploy_call
    assert [row for row in invocations if row[:3] == ["docker", "buildx", "imagetools"]] == [
        ["docker", "buildx", "imagetools", "inspect", IMAGE_TAG]
    ]
    assert [row for row in invocations if row[:2] == ["docker", "pull"]] == [["docker", "pull", IMAGE_TAGGED_DIGEST]]
    assert not any(
        row[:2]
        in (
            ["flyctl", "machine"],
            ["flyctl", "machines"],
            ["flyctl", "apps"],
            ["flyctl", "secrets"],
        )
        for row in invocations
    )
    assert not any(row[0] in {"curl", "sleep"} for row in invocations)


def test_regional_build_qualify_parses_current_fly_tag_digest_output_before_registry_auth(
    tmp_path: Path,
) -> None:
    result, invocations, receipt_path = _run_qualification_only(
        tmp_path,
        build_qualify=True,
        failure="registry_auth",
        pushed_refs="fly_tag_digest",
    )

    assert result.returncode != 0
    assert "regional registry authentication failed" in result.stderr
    assert not receipt_path.exists()
    assert (tmp_path / "regional_build_evidence" / "emitted_image_manifest_digest.txt").read_text(
        encoding="utf-8"
    ) == f"sha256:{'a' * 64}\n"
    assert [row for row in invocations if row[:3] == ["flyctl", "auth", "docker"]] == [["flyctl", "auth", "docker"]]
    assert not any(row[:3] == ["docker", "buildx", "imagetools"] for row in invocations)


def test_regional_build_qualify_exports_active_docker_context_for_flyctl(
    tmp_path: Path,
) -> None:
    result, invocations, _receipt_path = _run_qualification_only(
        tmp_path,
        failure="build",
        build_qualify=True,
        require_docker_context=True,
    )

    assert result.returncode == 1
    assert "regional image build/push failed" in result.stderr
    assert (tmp_path / "regional_build_evidence" / "fly_deploy_build_push.txt").read_text(encoding="utf-8") == ""
    assert ["docker", "context", "show"] in invocations
    assert [
        "docker",
        "context",
        "inspect",
        "colima",
        "--format",
        "{{.Endpoints.docker.Host}}",
    ] in invocations
    built_at = (tmp_path / "regional_build_evidence" / "built_at.txt").read_text(encoding="utf-8").strip()
    assert [row for row in invocations if row[0] == "flyctl"] == [
        ["flyctl", "auth", "whoami"],
        [
            "flyctl",
            "deploy",
            "--build-only",
            "--push",
            "--local-only",
            "-c",
            "infra/fly/refresh.fly.toml",
            "--build-arg",
            f"CIVIBUS_GIT_SHA={MIRROR_SHA}",
            "--build-arg",
            f"CIVIBUS_BUILT_AT={built_at}",
        ],
    ]
    assert not any(row[:3] == ["docker", "buildx", "imagetools"] or row[:2] == ["docker", "run"] for row in invocations)


def test_regional_build_qualify_fails_when_build_claims_success_but_registry_has_no_tag_or_digest(
    tmp_path: Path,
) -> None:
    result, invocations, receipt_path = _run_qualification_only(
        tmp_path,
        build_qualify=True,
        failure="regional_registry_manifest_absent",
    )

    assert result.returncode != 0
    assert "registry metadata could not resolve the regional pushed image" in result.stderr
    assert not receipt_path.exists()
    assert [row for row in invocations if row[:3] == ["docker", "buildx", "imagetools"]] == [
        ["docker", "buildx", "imagetools", "inspect", IMAGE_TAG]
    ]
    assert not any(row[:2] == ["docker", "pull"] for row in invocations)
    assert [row for row in invocations if row[:3] == ["docker", "image", "rm"]] == [
        ["docker", "image", "rm", IMAGE_TAG]
    ]
    assert not any(
        row[:2] in (["flyctl", "machine"], ["flyctl", "machines"], ["flyctl", "apps"]) for row in invocations
    )


def test_regional_build_qualify_rejects_registry_manifest_digest_mismatch_before_pull(
    tmp_path: Path,
) -> None:
    result, invocations, receipt_path = _run_qualification_only(
        tmp_path,
        build_qualify=True,
        failure="regional_registry_manifest_mismatch",
    )

    assert result.returncode != 0
    assert "registry manifest digest does not match the emitted digest" in result.stderr
    assert not receipt_path.exists()
    assert not any(row[:2] == ["docker", "pull"] for row in invocations)
    assert [row for row in invocations if row[:3] == ["docker", "image", "rm"]] == [
        ["docker", "image", "rm", IMAGE_TAG]
    ]
    assert not any(
        row[:2] in (["flyctl", "machine"], ["flyctl", "machines"], ["flyctl", "apps"]) for row in invocations
    )


@pytest.mark.parametrize(
    ("failure", "head_sha"),
    [("dirty", None), ("", "f" * 40)],
)
def test_regional_build_qualify_refuses_dirty_or_wrong_head_before_registry_or_fly_calls(
    tmp_path: Path,
    failure: str,
    head_sha: str | None,
) -> None:
    result, invocations, receipt_path = _run_qualification_only(
        tmp_path,
        build_qualify=True,
        failure=failure,
        head_sha=head_sha,
    )

    assert result.returncode != 0
    assert not receipt_path.exists()
    assert not any(row[0] in {"flyctl", "docker", "curl", "sleep"} for row in invocations)


@pytest.mark.parametrize(
    "failure",
    ["registry_auth", "image_pull", "regional_image_plan_mismatch"],
)
def test_regional_build_qualify_failure_removes_only_its_local_tag_without_retry_or_machine_action(
    tmp_path: Path,
    failure: str,
) -> None:
    result, invocations, receipt_path = _run_qualification_only(
        tmp_path,
        build_qualify=True,
        failure=failure,
    )

    assert result.returncode != 0
    assert not receipt_path.exists()
    assert [row for row in invocations if row[:2] == ["docker", "image"] and row[2:3] == ["rm"]] == [
        ["docker", "image", "rm", IMAGE_TAG]
    ]
    assert not any(row[0] in {"sleep", "curl"} for row in invocations)
    assert not any(
        row[:2] in (["flyctl", "machine"], ["flyctl", "machines"], ["flyctl", "apps"]) for row in invocations
    )


@pytest.mark.parametrize(
    "produced_image",
    [
        "",
        IMAGE_TAG,
        IMAGE_DIGEST,
        "registry.fly.io/another-app:deployment-stage2@sha256:" + "a" * 64,
        IMAGE_TAGGED_DIGEST + "@sha256:" + "b" * 64,
    ],
    ids=(
        "missing_output",
        "mutable_output",
        "digest_only_output",
        "wrong_output_repository",
        "double_digest_output",
    ),
)
def test_qualification_only_rejects_mutable_or_unbound_image_identity_without_owner_calls(
    tmp_path: Path,
    produced_image: str,
) -> None:
    result, invocations, receipt_path = _run_qualification_only(
        tmp_path,
        produced_image=produced_image,
    )

    assert result.returncode != 0
    assert not receipt_path.exists()
    assert not any(argv[0] in {"curl", "docker", "flyctl", "git"} for argv in invocations)


def test_qualification_only_rejects_approved_source_drift_without_owner_calls(
    tmp_path: Path,
) -> None:
    result, invocations, receipt_path = _run_qualification_only(
        tmp_path,
        source_sha="not-a-sha",
    )

    assert result.returncode != 0
    assert "candidate manifest source" in result.stderr
    assert not receipt_path.exists()
    assert not any(argv[0] in {"curl", "docker", "flyctl"} for argv in invocations)


@pytest.mark.parametrize(
    ("failure", "error"),
    [
        ("canonical_source_tree", "canonical source tree"),
        ("canonical_receipt_tree", "canonical receipt tree"),
        ("canonical_receipt_parent", "accepted source as its parent"),
        ("candidate_tree", "candidate source tree"),
        ("candidate_ancestry", "not descended"),
        ("image_pull", "candidate image pull"),
        ("image_version", "image content proof"),
        ("regional_image_plan_mismatch", "authority image proof mismatch"),
    ],
)
def test_qualification_only_fails_closed_on_git_or_image_proof_drift(
    tmp_path: Path,
    failure: str,
    error: str,
) -> None:
    result, invocations, receipt_path = _run_qualification_only(tmp_path, failure=failure)

    assert result.returncode != 0
    assert error in result.stderr
    assert not receipt_path.exists()
    assert not any(row[0] in {"curl", "flyctl"} for row in invocations)


@pytest.mark.parametrize(
    "manifest_paths",
    [[], ["core/refresh/runner.py", "fake.py"]],
    ids=("omitted", "extra"),
)
def test_qualification_only_rejects_manifest_paths_that_do_not_equal_git_diff(
    tmp_path: Path,
    manifest_paths: list[str],
) -> None:
    result, invocations, receipt_path = _run_qualification_only(
        tmp_path,
        manifest_paths=manifest_paths,
    )

    assert result.returncode != 0
    assert "changed_paths do not match" in result.stderr
    assert not receipt_path.exists()
    assert not any(row[0] in {"curl", "docker", "flyctl"} for row in invocations)


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        ({"manifest_updates": {"unexpected": True}}, "key set mismatch"),
        ({"manifest_remove": "baseline_tree_git_sha"}, "key set mismatch"),
        ({"manifest_updates": {"schema_version": True}}, "identity mismatch"),
        ({"manifest_updates": {"manifest_kind": "wrong"}}, "identity mismatch"),
        ({"manifest_updates": {"authority": {"kind": "municipality", "code": "SF"}}}, "profile binding"),
        ({"manifest_updates": {"execution_plan_id": "regional-sf-scheduled"}}, "profile binding"),
        ({"manifest_updates": {"profile_sha256": "0" * 64}}, "profile binding"),
        ({"manifest_updates": {"baseline_source_git_sha": "0" * 40}}, "does not match"),
        ({"manifest_paths": ["../escape"]}, "safe sorted unique"),
        ({"duplicate_manifest_key": True}, "duplicate object key"),
        ({"failure": "candidate_unresolved"}, "git identity proof failed"),
        ({"failure": "candidate_diff"}, "changed-path proof failed"),
    ],
    ids=(
        "extra-key",
        "missing-key",
        "boolean-schema",
        "wrong-kind",
        "authority-drift",
        "plan-drift",
        "profile-drift",
        "baseline-drift",
        "unsafe-path",
        "duplicate-key",
        "unresolved-candidate",
        "git-diff-failure",
    ),
)
def test_qualification_only_rejects_strict_manifest_or_git_resolution_drift(
    tmp_path: Path,
    kwargs: dict[str, Any],
    error: str,
) -> None:
    result, invocations, receipt_path = _run_qualification_only(tmp_path, **kwargs)

    assert result.returncode != 0
    assert error in result.stderr
    assert not receipt_path.exists()
    assert not any(row[0] in {"curl", "flyctl"} for row in invocations)


@pytest.mark.parametrize("recompute_config_digest", [False, True])
def test_qualification_only_rejects_machine_config_and_profile_drift(
    tmp_path: Path,
    recompute_config_digest: bool,
) -> None:
    profile = json.loads(REGIONAL_PROFILE_PATH.read_text(encoding="utf-8"))
    profile["machine"]["config"]["schedule"] = "weekly"
    if recompute_config_digest:
        profile["machine"]["config_sha256"] = _canonical_sha256(profile["machine"]["config"])
    profile_path = tmp_path / "drifted_profile.json"
    profile_path.write_text(json.dumps(profile), encoding="utf-8")

    result, invocations, receipt_path = _run_qualification_only(
        tmp_path,
        profile_path=profile_path,
    )

    assert result.returncode != 0
    assert not receipt_path.exists()
    assert not any(argv[0] in {"curl", "docker", "flyctl", "git"} for argv in invocations)


@pytest.mark.parametrize(
    ("option", "value"),
    [
        ("--profile-json", str(REGIONAL_PROFILE_PATH)),
        (
            "--candidate-manifest-json",
            "candidate_manifest.json",
        ),
        ("--produced-image-tagged-digest", IMAGE_TAGGED_DIGEST),
        ("--candidate-receipt-json", "duplicate.json"),
    ],
    ids=(
        "profile-json",
        "candidate-manifest-json",
        "produced-image-tagged-digest",
        "candidate-receipt-json",
    ),
)
def test_qualification_only_rejects_duplicate_options_before_owner_calls(
    tmp_path: Path,
    option: str,
    value: str,
) -> None:
    result, invocations, receipt_path = _run_qualification_only(
        tmp_path,
        extra_args=(option, value),
    )

    assert result.returncode != 0
    assert "may be supplied only once" in result.stderr
    assert not receipt_path.exists()
    assert invocations == []


def test_regional_canary_start_refuses_legacy_caller_supplied_invariance_files(
    tmp_path: Path,
) -> None:
    run, command_log, _ = _regional_lifecycle_harness(tmp_path)
    assert run("create-canary-stopped", with_secret=True).returncode == 0

    result = run(
        "start-canary-once",
        federal_invariance_before=_regional_invariance_snapshot("federal"),
        public_invariance_before=_regional_invariance_snapshot("public"),
    )

    assert result.returncode != 0
    assert "legacy caller-supplied invariance evidence is forbidden" in result.stderr
    invocations = [json.loads(line) for line in command_log.read_text().splitlines()]
    assert not any(argv[:3] == ["flyctl", "machine", "start"] for argv in invocations)


def test_regional_invariance_capture_derives_bound_mode_0600_evidence_without_mutation_or_secrets(
    tmp_path: Path,
) -> None:
    run, command_log, lifecycle_dir = _regional_lifecycle_harness(tmp_path)
    assert run("create-canary-stopped", with_secret=True).returncode == 0
    offset = len(command_log.read_text().splitlines())

    captured = run("capture-invariance", invariance_stage="before")

    assert captured.returncode == 0, captured.stderr
    assert "canonical regional invariance captured stage=before machine=abc123" in captured.stdout
    federal_path = lifecycle_dir / "federal_invariance_before.json"
    public_path = lifecycle_dir / "public_invariance_before.json"
    assert stat.S_IMODE(federal_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(public_path.stat().st_mode) == 0o600
    federal = json.loads(federal_path.read_text(encoding="utf-8"))
    public = json.loads(public_path.read_text(encoding="utf-8"))
    expected_common = {
        "schema_version": 2,
        "producer": "regional_lifecycle_invariance_capture",
        "stage": "before",
        "source_revision": "4" * 40,
        "source_tree_git_sha": "5" * 40,
        "authority": {"kind": "state", "code": "WA"},
        "execution_plan": "regional-wa-scheduled",
        "job_key": "state-wa-contributions",
        "execution_origin": "operator_attended",
        "qualified_image": IMAGE_TAGGED_DIGEST,
        "app": "civibus-regional-refresh",
        "machine_id": "abc123",
        "machine_name": "regional-wa-scheduled",
        "database": {"host": "civibus-db.internal", "port": 5432, "name": "civibus"},
        "api_revision": "4" * 40,
        "web_revision": "4" * 40,
    }
    for scope, payload in (("federal", federal), ("public", public)):
        assert payload["scope"] == scope
        for key, value in expected_common.items():
            assert payload[key] == value
        assert [(record["owner"], record["identity"]) for record in payload["records"]] == sorted(
            (record["owner"], record["identity"]) for record in payload["records"]
        )
    assert federal["captured_at"] == public["captured_at"]
    capture_log = [json.loads(line) for line in command_log.read_text().splitlines()[offset:]]
    forbidden_mutations = {
        ("flyctl", "apps", "create"),
        ("flyctl", "apps", "destroy"),
        ("flyctl", "machine", "create"),
        ("flyctl", "machine", "start"),
        ("flyctl", "machine", "stop"),
        ("flyctl", "machine", "destroy"),
        ("flyctl", "secrets", "import"),
    }
    assert not any(tuple(argv[:3]) in forbidden_mutations for argv in capture_log)
    persisted = federal_path.read_text(encoding="utf-8") + public_path.read_text(encoding="utf-8")
    assert "do-not-log-this" not in captured.stdout + captured.stderr + command_log.read_text() + persisted


@pytest.mark.parametrize(
    "failure",
    [
        "pre_verifier",
        "regional_invariance_database_probe",
        "regional_invariance_write_enabled",
        "regional_invariance_foreign_database",
        "regional_invariance_running_rows",
        "regional_invariance_active_backend",
        "regional_invariance_long_idle",
        "regional_invariance_ungranted_lock",
        "regional_invariance_advisory_lock",
        "regional_invariance_unhealthy_public",
        "regional_invariance_split_revision",
    ],
)
def test_regional_invariance_capture_refuses_unhealthy_foreign_or_nonquiescent_raw_owners_before_start(
    tmp_path: Path,
    failure: str,
) -> None:
    run, command_log, lifecycle_dir = _regional_lifecycle_harness(tmp_path)
    assert run("create-canary-stopped", with_secret=True).returncode == 0
    offset = len(command_log.read_text().splitlines())

    captured = run("capture-invariance", invariance_stage="before", failure=failure)

    assert captured.returncode != 0
    assert not (lifecycle_dir / "federal_invariance_before.json").exists()
    assert not (lifecycle_dir / "public_invariance_before.json").exists()
    invocations = [json.loads(line) for line in command_log.read_text().splitlines()[offset:]]
    assert not any(argv[:3] == ["flyctl", "machine", "start"] for argv in invocations)
    assert not any(argv[:3] == ["flyctl", "machine", "destroy"] for argv in invocations)


def test_regional_invariance_capture_is_idempotent_only_for_byte_identical_evidence(
    tmp_path: Path,
) -> None:
    run, _, lifecycle_dir = _regional_lifecycle_harness(tmp_path)
    assert run("create-canary-stopped", with_secret=True).returncode == 0
    assert run("capture-invariance", invariance_stage="before").returncode == 0
    paths = (
        lifecycle_dir / "federal_invariance_before.json",
        lifecycle_dir / "public_invariance_before.json",
    )
    before = tuple(path.read_bytes() for path in paths)

    repeated = run("capture-invariance", invariance_stage="before")
    drifted = run(
        "capture-invariance",
        invariance_stage="before",
        failure="regional_invariance_split_revision",
    )

    assert repeated.returncode == 0, repeated.stderr
    assert drifted.returncode != 0
    assert tuple(path.read_bytes() for path in paths) == before


def test_regional_invariance_capture_refuses_partial_publication_and_after_before_terminal(
    tmp_path: Path,
) -> None:
    run, command_log, lifecycle_dir = _regional_lifecycle_harness(tmp_path)
    assert run("create-canary-stopped", with_secret=True).returncode == 0
    offset = len(command_log.read_text().splitlines())

    after = run("capture-invariance", invariance_stage="after")
    assert after.returncode != 0
    assert "requires the exact one-start marker" in after.stderr
    partial = lifecycle_dir / "federal_invariance_before.json"
    partial.write_text("operator-owned\n", encoding="utf-8")
    partial.chmod(0o600)
    before = run("capture-invariance", invariance_stage="before")

    assert before.returncode != 0
    assert "partially published" in before.stderr
    assert partial.read_text(encoding="utf-8") == "operator-owned\n"
    assert not (lifecycle_dir / "public_invariance_before.json").exists()
    invocations = [json.loads(line) for line in command_log.read_text().splitlines()[offset:]]
    assert not any(argv[:3] == ["flyctl", "machine", "start"] for argv in invocations)


@pytest.mark.parametrize("target_kind", ["file", "directory", "symlink_to_directory"])
def test_qualification_only_preserves_an_existing_candidate_receipt_target(
    tmp_path: Path,
    target_kind: str,
) -> None:
    receipt_path = tmp_path / "existing_candidate_receipt.json"
    if target_kind == "file":
        receipt_path.write_text("operator-owned\n", encoding="utf-8")
    elif target_kind == "directory":
        receipt_path.mkdir()
    elif target_kind == "symlink_to_directory":
        target_dir = tmp_path / "operator_owned_directory"
        target_dir.mkdir()
        receipt_path.symlink_to(target_dir, target_is_directory=True)
    else:
        raise AssertionError(f"unknown target kind: {target_kind}")

    result, invocations, _ = _run_qualification_only(
        tmp_path,
        receipt_path=receipt_path,
    )

    assert result.returncode != 0
    if target_kind == "file":
        assert receipt_path.read_text(encoding="utf-8") == "operator-owned\n"
    else:
        assert receipt_path.is_dir()
        assert list(receipt_path.iterdir()) == []
    assert invocations == []


def test_federal_deploy_execution_block_remains_byte_for_byte_baseline() -> None:
    deploy_text = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    start = deploy_text.index('  local evidence_dir="$EVIDENCE_DIR"\n')
    final_line = "  printf 'PASS: refresh Machine image updated to %s\\n' \"$digest_ref\"\n"
    end = deploy_text.index(final_line, start) + len(final_line)
    federal_execution_block = deploy_text[start:end].encode()

    assert len(federal_execution_block) == 3869
    assert hashlib.sha256(federal_execution_block).hexdigest() == (
        "6e95769906f06faae07e8e14c447b9e074f400e94b47c3b8eb6e6cb60bb486f4"
    )


def _regional_lifecycle_harness(
    tmp_path: Path,
    *,
    secret_kind: str = "valid",
    lifecycle_input_kind: str = "",
):
    stub_bin, command_log = _write_command_stubs(tmp_path)
    profile = json.loads(REGIONAL_PROFILE_PATH.read_text(encoding="utf-8"))
    receipt_path = tmp_path / "candidate_receipt.json"
    receipt_path.write_text(json.dumps(_regional_candidate_receipt(profile)), encoding="utf-8")
    profile_arg = REGIONAL_PROFILE_PATH
    receipt_arg = receipt_path
    if lifecycle_input_kind == "profile":
        profile_arg = tmp_path / "profile-link.json"
        profile_arg.symlink_to(REGIONAL_PROFILE_PATH)
    elif lifecycle_input_kind == "mutable-profile":
        profile_arg = tmp_path / "profile-copy.json"
        profile_arg.write_bytes(REGIONAL_PROFILE_PATH.read_bytes())
    elif lifecycle_input_kind == "receipt":
        receipt_arg = tmp_path / "receipt-link.json"
        receipt_arg.symlink_to(receipt_path)
    elif lifecycle_input_kind == "profile-directory":
        profile_arg = tmp_path / "profile-directory"
        profile_arg.mkdir()
    elif lifecycle_input_kind == "receipt-directory":
        receipt_arg = tmp_path / "receipt-directory"
        receipt_arg.mkdir()
    lifecycle_dir = tmp_path / "lifecycle"
    lifecycle_dir.mkdir()
    secret_file = tmp_path / "regional.secret"
    if secret_kind == "symlink":
        target = tmp_path / "secret-target"
        target.write_text("POSTGRES_PASSWORD=do-not-log-this\n", encoding="utf-8")
        target.chmod(0o600)
        secret_file.symlink_to(target)
    else:
        secret_file.write_text(
            "WRONG_NAME=do-not-log-this\n" if secret_kind == "malformed" else "POSTGRES_PASSWORD=do-not-log-this\n",
            encoding="utf-8",
        )
        secret_file.chmod(0o644 if secret_kind == "wrong-mode" else 0o600)
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{stub_bin}:/usr/bin:/bin",
            "COMMAND_LOG": str(command_log),
            "REGIONAL_PROFILE_PATH": str(REGIONAL_PROFILE_PATH),
            "STUB_REGIONAL_IMAGE": IMAGE_TAGGED_DIGEST,
            "STUB_REGIONAL_IMAGE_SELECTOR": IMAGE_TAG,
            "STUB_LIFECYCLE_DIR": str(lifecycle_dir),
            "PYTHON_BIN": sys.executable,
            "POSTGRES_HOST": "127.0.0.1",
            "POSTGRES_PORT": "16599",
            "POSTGRES_USER": "civibus",
            "POSTGRES_PASSWORD": "do-not-log-this",
            "POSTGRES_DB": "civibus",
        }
    )
    status_injector = tmp_path / "python-status-injector"
    status_injector.write_text(
        """#!/bin/bash
target=false
if [[ "$#" -eq 9 && "$2" == "${INJECT_VALIDATOR_MARKER_PATH:-}" ]]; then
  target=true
fi
"${REAL_PYTHON_BIN:?}" "$@"
status=$?
if [[ "$status" -eq 0 && "$target" == true ]]; then
  count=0
  if [[ -f "${INJECT_VALIDATOR_COUNTER:?}" ]]; then
    read -r count <"$INJECT_VALIDATOR_COUNTER"
  fi
  count=$((count + 1))
  printf '%s\n' "$count" >"$INJECT_VALIDATOR_COUNTER"
  if [[ "$count" -eq "${INJECT_VALIDATOR_OCCURRENCE:?}" ]]; then
    printf '%s|%s\n' "$2" "$3" >>"${INJECT_VALIDATOR_LOG:?}"
    exit 42
  fi
fi
exit "$status"
""",
        encoding="utf-8",
    )
    status_injector.chmod(0o755)

    def run(
        action: str,
        *,
        with_secret: bool = False,
        failure: str = "",
        refresh_postcondition: dict[str, object] | None = None,
        omit_refresh_postcondition: bool = False,
        expected_refresh_run_id: str = "",
        validator_failure_marker: str = "",
        validator_failure_occurrence: int = 1,
        federal_invariance_before: dict[str, object] | None = None,
        public_invariance_before: dict[str, object] | None = None,
        federal_invariance_after: dict[str, object] | None = None,
        public_invariance_after: dict[str, object] | None = None,
        authority_ledger_proof: dict[str, object] | None = None,
        canary_promotion_path: Path | None = None,
        omit_canary_promotion: bool = False,
        invariance_stage: str = "",
    ) -> subprocess.CompletedProcess[str]:
        legacy_invariance = any(
            evidence is not None
            for evidence in (
                federal_invariance_before,
                public_invariance_before,
                federal_invariance_after,
                public_invariance_after,
            )
        )
        if action == "start-canary-once" and not legacy_invariance:
            if (
                not (lifecycle_dir / "start_attempt.json").exists()
                and not (lifecycle_dir / "federal_invariance_before.json").exists()
            ):
                captured = run("capture-invariance", invariance_stage="before")
                if captured.returncode != 0:
                    return captured
            elif (lifecycle_dir / "canary_machine_terminal.json").exists() and not (
                lifecycle_dir / "federal_invariance_after.json"
            ).exists():
                captured = run("capture-invariance", invariance_stage="after")
                if captured.returncode != 0:
                    return captured
        command = [
            "/bin/bash",
            str(DEPLOY_SCRIPT),
            "--regional-action",
            action,
            "--profile-json",
            str(profile_arg),
            "--candidate-receipt-json",
            str(receipt_arg),
            "--lifecycle-dir",
            str(lifecycle_dir),
        ]
        if invariance_stage:
            command.extend(["--invariance-stage", invariance_stage])
        if with_secret:
            command.extend(["--secret-file", str(secret_file)])
        if action == "create-stopped" and canary_promotion_path is None and not omit_canary_promotion:
            canary_promotion_path = _shared_valid_canary_promotion_artifact()
        if canary_promotion_path is not None:
            command.extend(["--canary-promotion-json", str(canary_promotion_path)])
        if refresh_postcondition is None and not omit_refresh_postcondition:
            if (
                action == "rollback"
                and (lifecycle_dir / "canary_mode.json").is_file()
                and (lifecycle_dir / "start_attempt.json").is_file()
            ):
                refresh_postcondition = _terminal_regional_refresh_postcondition(
                    pull_status="success",
                    metadata_updates=1,
                )
        if refresh_postcondition is not None:
            postcondition_path = tmp_path / f"refresh_postcondition_{action}.json"
            postcondition_path.write_text(
                json.dumps(refresh_postcondition, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            command.extend(["--refresh-postcondition-json", str(postcondition_path)])
        if expected_refresh_run_id:
            command.extend(["--expected-refresh-run-id", expected_refresh_run_id])
        evidence_arguments = (
            ("--federal-invariance-before-json", "federal_before", federal_invariance_before),
            ("--public-invariance-before-json", "public_before", public_invariance_before),
            ("--federal-invariance-after-json", "federal_after", federal_invariance_after),
            ("--public-invariance-after-json", "public_after", public_invariance_after),
            ("--authority-ledger-proof-json", "authority_ledger", authority_ledger_proof),
        )
        for option, name, evidence in evidence_arguments:
            if evidence is None:
                continue
            evidence_path = tmp_path / f"{name}_{action}.json"
            evidence_path.write_text(json.dumps(evidence, sort_keys=True) + "\n", encoding="utf-8")
            command.extend([option, str(evidence_path)])
        action_environment = dict(environment)
        action_environment["STUB_FAILURE"] = failure
        action_environment["STUB_ACTION"] = action
        if validator_failure_marker:
            counter_path = tmp_path / "validator_status_counter"
            injection_log_path = tmp_path / "validator_status_injections.log"
            counter_path.unlink(missing_ok=True)
            injection_log_path.unlink(missing_ok=True)
            action_environment.update(
                {
                    "PYTHON_BIN": str(status_injector),
                    "REAL_PYTHON_BIN": sys.executable,
                    "INJECT_VALIDATOR_MARKER_PATH": str(lifecycle_dir / validator_failure_marker),
                    "INJECT_VALIDATOR_COUNTER": str(counter_path),
                    "INJECT_VALIDATOR_OCCURRENCE": str(validator_failure_occurrence),
                    "INJECT_VALIDATOR_LOG": str(injection_log_path),
                }
            )
        return subprocess.run(
            command,
            cwd=REPO_ROOT,
            env=action_environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )

    return run, command_log, lifecycle_dir


def _terminal_regional_refresh_postcondition(
    *,
    pull_status: str = "failed",
    completed_at: str | None = "2026-08-30T00:20:00Z",
    metadata_updates: int = 0,
    running_refresh_rows: int = 0,
    active_refresh_backends: int = 0,
    long_idle_transactions: int = 0,
    ungranted_locks: int = 0,
    machine_id: str = "abc123",
    refresh_run_id: str = R36_REFRESH_RUN_ID,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "app": "civibus-regional-refresh",
        "machine_id": machine_id,
        "authority": "state/WA",
        "execution_plan": "regional-wa-scheduled",
        "refresh_run_id": refresh_run_id,
        "job_key": "state-wa-contributions",
        "execution_origin": "operator_attended",
        "pull_status": pull_status,
        "completed_at": completed_at,
        "metadata_updates": metadata_updates,
        "running_refresh_rows": running_refresh_rows,
        "active_refresh_backends": active_refresh_backends,
        "long_idle_transactions": long_idle_transactions,
        "ungranted_locks": ungranted_locks,
        "database": {
            "host": "civibus-db.internal",
            "port": 5432,
            "name": "civibus",
        },
    }


def _regional_invariance_snapshot(
    scope: str,
    *,
    captured_at: str = "2026-08-29T23:39:00Z",
) -> dict[str, object]:
    candidate_source = _regional_candidate_receipt(json.loads(REGIONAL_PROFILE_PATH.read_text(encoding="utf-8")))[
        "source_git_sha"
    ]
    database = {"host": "civibus-db.internal", "port": 5432, "name": "civibus"}
    records = [
        {
            "owner": f"campaign_finance.{scope}",
            "identity": f"{scope}/baseline",
            "row_count": 4,
            "content_sha256": ("d" if scope == "federal" else "e") * 64,
        }
    ]
    return {
        "schema_version": 1,
        "scope": scope,
        "captured_at": captured_at,
        "source_revision": candidate_source,
        "database": database,
        "records": records,
        "identity_sha256": _canonical_sha256(
            {
                "schema_version": 1,
                "scope": scope,
                "source_revision": candidate_source,
                "database": database,
                "records": records,
            }
        ),
    }


def _regional_canary_authority_ledger_proof(
    *,
    started_at: str = "2026-08-29T23:39:28Z",
    completed_at: str = "2026-08-30T00:20:00Z",
) -> dict[str, object]:
    profile = json.loads(REGIONAL_PROFILE_PATH.read_text(encoding="utf-8"))
    source_name = "WA PDC Contributions"
    return {
        "schema_version": 1,
        "authority": {"kind": "state", "code": "WA"},
        "execution_plan_id": profile["execution_plan"]["plan_id"],
        "execution_plan_sha256": _canonical_sha256(profile["execution_plan"]),
        "execution_mode": "canary",
        "observed_after": "2026-08-29T23:39:00Z",
        "observed_plan_row_count": 1,
        "runner_results": [{"job_key": "state-wa-contributions", "status": "success", "metadata_updates": 1}],
        "refresh_runs": [
            {
                "refresh_run_id": R36_REFRESH_RUN_ID,
                "job_key": "state-wa-contributions",
                "data_source_names": [source_name],
                "execution_origin": "operator_attended",
                "pull_status": "success",
                "metadata_updates": 1,
                "started_at": started_at,
                "completed_at": completed_at,
            }
        ],
        "data_sources": [
            {
                "domain": "campaign_finance",
                "jurisdiction": "state/WA",
                "name": source_name,
                "baseline_last_pull_at": "2026-08-28T00:20:00Z",
                "post_last_pull_at": completed_at,
                "post_last_pull_status": "success",
            }
        ],
    }


def _canonical_canary_attempt_window(lifecycle_dir: Path) -> tuple[str, str]:
    before = json.loads((lifecycle_dir / "federal_invariance_before.json").read_text(encoding="utf-8"))
    start_marker = json.loads((lifecycle_dir / "start_attempt.json").read_text(encoding="utf-8"))
    terminal = json.loads((lifecycle_dir / "terminal_machine.json").read_text(encoding="utf-8"))
    admitted_at = datetime.fromisoformat(
        start_marker.get("invariance_admission", {}).get("admitted_at", before["captured_at"])
    )
    started_at = admitted_at + timedelta(milliseconds=1)
    completed_at = datetime.fromisoformat(terminal["occurred_at"]) - timedelta(milliseconds=1)
    assert started_at < completed_at
    return (
        started_at.isoformat().replace("+00:00", "Z"),
        completed_at.isoformat().replace("+00:00", "Z"),
    )


def _rewrite_admitted_before_window(
    lifecycle_dir: Path,
    *,
    canary_age: timedelta,
    baseline_age_at_admission: timedelta = timedelta(minutes=1),
) -> datetime:
    terminal = json.loads((lifecycle_dir / "terminal_machine.json").read_text(encoding="utf-8"))
    admitted_at = datetime.fromisoformat(terminal["occurred_at"]) - canary_age
    captured_at = admitted_at - baseline_age_at_admission
    references: dict[str, dict[str, str]] = {}
    for scope in ("federal", "public"):
        snapshot_path = lifecycle_dir / f"{scope}_invariance_before.json"
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        snapshot["captured_at"] = captured_at.isoformat().replace("+00:00", "Z")
        snapshot_path.write_text(json.dumps(snapshot, sort_keys=True) + "\n", encoding="utf-8")
        snapshot_path.chmod(0o600)
        references[f"{scope}_before"] = {
            "snapshot_sha256": hashlib.sha256(snapshot_path.read_bytes()).hexdigest(),
            "identity_sha256": snapshot["identity_sha256"],
        }
    marker_path = lifecycle_dir / "start_attempt.json"
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    marker["schema_version"] = 3
    marker["invariance_admission"] = {
        "admitted_at": admitted_at.isoformat().replace("+00:00", "Z"),
        "max_age_seconds": 600,
        "future_skew_seconds": 60,
        **references,
    }
    marker_path.write_text(json.dumps(marker, sort_keys=True) + "\n", encoding="utf-8")
    marker_path.chmod(0o600)
    return admitted_at


def _rewrite_before_capture_time(lifecycle_dir: Path, captured_at: datetime) -> None:
    for scope in ("federal", "public"):
        snapshot_path = lifecycle_dir / f"{scope}_invariance_before.json"
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        snapshot["captured_at"] = captured_at.isoformat().replace("+00:00", "Z")
        snapshot_path.write_text(json.dumps(snapshot, sort_keys=True) + "\n", encoding="utf-8")
        snapshot_path.chmod(0o600)


@cache
def _shared_valid_canary_promotion_artifact() -> Path:
    root = Path(tempfile.mkdtemp(prefix="civibus-regional-canary-admission-"))
    run, _, lifecycle_dir = _regional_lifecycle_harness(root)
    created = run("create-canary-stopped", with_secret=True)
    if created.returncode != 0:
        raise RuntimeError(created.stderr)
    terminal = run("start-canary-once", omit_refresh_postcondition=True)
    if terminal.returncode == 0 or not (lifecycle_dir / "terminal_machine.json").is_file():
        raise RuntimeError("shared canary fixture did not reach its durable terminal evidence boundary")
    started_at, completed_at = _canonical_canary_attempt_window(lifecycle_dir)
    finalized = run(
        "start-canary-once",
        refresh_postcondition=_terminal_regional_refresh_postcondition(
            pull_status="success",
            metadata_updates=1,
            completed_at=completed_at,
        ),
        authority_ledger_proof=_regional_canary_authority_ledger_proof(
            started_at=started_at,
            completed_at=completed_at,
        ),
    )
    if finalized.returncode != 0:
        raise RuntimeError(finalized.stderr)
    rollback = run("rollback")
    if rollback.returncode != 0:
        raise RuntimeError(rollback.stderr)
    artifact = lifecycle_dir / "regional_canary_promotion.json"
    if not artifact.is_file() or artifact.is_symlink():
        raise RuntimeError("shared canary fixture did not publish its promotion artifact")
    return artifact


def test_regional_canary_publishes_full_durable_artifact_graph_without_second_start(
    tmp_path: Path,
) -> None:
    run, command_log, lifecycle_dir = _regional_lifecycle_harness(tmp_path)
    assert run("create-canary-stopped", with_secret=True).returncode == 0

    terminal = run("start-canary-once", omit_refresh_postcondition=True)
    assert terminal.returncode != 0
    assert "exact database postcondition is required" in terminal.stderr
    assert (lifecycle_dir / "terminal_machine.json").is_file()
    assert (lifecycle_dir / "canary_machine_terminal.json").is_file()
    terminal_payload = json.loads((lifecycle_dir / "terminal_machine.json").read_text(encoding="utf-8"))
    assert terminal_payload["image"] == IMAGE_TAGGED_DIGEST
    assert datetime.fromisoformat(terminal_payload["occurred_at"]) < datetime.fromisoformat(
        terminal_payload["captured_at"]
    )

    started_at, completed_at = _canonical_canary_attempt_window(lifecycle_dir)
    finalized = run(
        "start-canary-once",
        refresh_postcondition=_terminal_regional_refresh_postcondition(
            pull_status="success",
            metadata_updates=1,
            completed_at=completed_at,
        ),
        authority_ledger_proof=_regional_canary_authority_ledger_proof(
            started_at=started_at,
            completed_at=completed_at,
        ),
    )
    assert finalized.returncode == 0, finalized.stderr
    assert "without another start" in finalized.stdout

    rollback = run("rollback")
    assert rollback.returncode == 0, rollback.stderr
    artifact_path = lifecycle_dir / "regional_canary_promotion.json"
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert artifact["machine_id"] == "abc123"
    assert artifact["refresh_run_id"] == R36_REFRESH_RUN_ID
    assert artifact["terminal_machine_evidence"]["path"] == str(lifecycle_dir / "terminal_machine.json")
    for name in (
        "profile.json",
        "candidate_receipt.json",
        "authority_ledger_proof.json",
        "database_postcondition.json",
        "federal_invariance_before.json",
        "federal_invariance_after.json",
        "public_invariance_before.json",
        "public_invariance_after.json",
        "rollback_apps_before.json",
        "rollback_apps_after.json",
        "rollback_machines_before.json",
        "rollback_machines_after.json",
        "rollback_volumes_before.json",
        "rollback_volumes_after.json",
        "regional_canary_promotion.json",
    ):
        path = lifecycle_dir / name
        assert path.is_file() and not path.is_symlink()
        assert path.stat().st_mode & 0o777 == 0o600
    invocations = [json.loads(line) for line in command_log.read_text().splitlines()]
    assert len([row for row in invocations if row[:3] == ["flyctl", "machine", "start"]]) == 1
    assert len([row for row in invocations if row[:3] == ["flyctl", "machine", "destroy"]]) == 1
    assert len([row for row in invocations if row[:3] == ["flyctl", "apps", "destroy"]]) == 1


def test_regional_canary_start_durably_binds_exact_fresh_before_invariance(
    tmp_path: Path,
) -> None:
    run, command_log, lifecycle_dir = _regional_lifecycle_harness(tmp_path)
    assert run("create-canary-stopped", with_secret=True).returncode == 0

    terminal = run("start-canary-once", omit_refresh_postcondition=True)

    assert terminal.returncode != 0
    marker_path = lifecycle_dir / "start_attempt.json"
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    assert marker["schema_version"] == 3
    admission = marker["invariance_admission"]
    assert set(admission) == {
        "admitted_at",
        "federal_before",
        "future_skew_seconds",
        "max_age_seconds",
        "public_before",
    }
    assert (admission["max_age_seconds"], admission["future_skew_seconds"]) == (600, 60)
    admitted_at = datetime.fromisoformat(admission["admitted_at"])
    for scope in ("federal", "public"):
        snapshot_path = lifecycle_dir / f"{scope}_invariance_before.json"
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        captured_at = datetime.fromisoformat(snapshot["captured_at"])
        assert admitted_at - timedelta(minutes=10) <= captured_at <= admitted_at + timedelta(minutes=1)
        assert admission[f"{scope}_before"] == {
            "snapshot_sha256": hashlib.sha256(snapshot_path.read_bytes()).hexdigest(),
            "identity_sha256": snapshot["identity_sha256"],
        }
    assert marker_path.stat().st_mode & 0o777 == 0o600
    assert "do-not-log-this" not in marker_path.read_text(encoding="utf-8")
    invocations = [json.loads(line) for line in command_log.read_text().splitlines()]
    assert len([row for row in invocations if row[:3] == ["flyctl", "machine", "start"]]) == 1


def test_regional_canary_finalizes_after_ten_minutes_with_exact_admitted_before_snapshot(
    tmp_path: Path,
) -> None:
    run, command_log, lifecycle_dir = _regional_lifecycle_harness(tmp_path)
    assert run("create-canary-stopped", with_secret=True).returncode == 0
    terminal = run("start-canary-once", omit_refresh_postcondition=True)
    assert terminal.returncode != 0
    assert (lifecycle_dir / "terminal_machine.json").is_file()
    admitted_at = _rewrite_admitted_before_window(
        lifecycle_dir,
        canary_age=timedelta(minutes=11),
    )
    terminal_payload = json.loads((lifecycle_dir / "terminal_machine.json").read_text(encoding="utf-8"))
    completed_at_value = datetime.fromisoformat(terminal_payload["occurred_at"]) - timedelta(milliseconds=1)
    started_at_value = admitted_at + timedelta(milliseconds=1)
    assert timedelta(minutes=10) < completed_at_value - started_at_value <= timedelta(minutes=30)
    started_at = started_at_value.isoformat().replace("+00:00", "Z")
    completed_at = completed_at_value.isoformat().replace("+00:00", "Z")

    finalized = run(
        "start-canary-once",
        refresh_postcondition=_terminal_regional_refresh_postcondition(
            pull_status="success",
            metadata_updates=1,
            completed_at=completed_at,
        ),
        authority_ledger_proof=_regional_canary_authority_ledger_proof(
            started_at=started_at,
            completed_at=completed_at,
        ),
    )

    assert finalized.returncode == 0, finalized.stderr
    assert "without another start" in finalized.stdout
    invocations = [json.loads(line) for line in command_log.read_text().splitlines()]
    assert len([row for row in invocations if row[:3] == ["flyctl", "machine", "start"]]) == 1


@pytest.mark.parametrize(
    "captured_at",
    [
        pytest.param(lambda: datetime.now(timezone.utc) - timedelta(minutes=11), id="stale"),
        pytest.param(lambda: datetime.now(timezone.utc) + timedelta(minutes=2), id="future"),
    ],
)
def test_regional_canary_refuses_stale_or_future_before_snapshot_before_start_mutation(
    tmp_path: Path,
    captured_at: Callable[[], datetime],
) -> None:
    run, command_log, lifecycle_dir = _regional_lifecycle_harness(tmp_path)
    assert run("create-canary-stopped", with_secret=True).returncode == 0
    assert run("capture-invariance", invariance_stage="before").returncode == 0
    _rewrite_before_capture_time(lifecycle_dir, captured_at())
    offset = len(command_log.read_text().splitlines())

    refused = run("start-canary-once")

    assert refused.returncode != 0
    assert "invariance baseline is invalid before canary start" in refused.stderr
    assert not (lifecycle_dir / "start_attempt.json").exists()
    invocations = [json.loads(line) for line in command_log.read_text().splitlines()[offset:]]
    assert not any(row[:3] == ["flyctl", "machine", "start"] for row in invocations)


@pytest.mark.parametrize("mutation", ["altered-before", "missing-binding"])
def test_regional_canary_finalization_refuses_unbound_before_evidence_without_second_start(
    tmp_path: Path,
    mutation: str,
) -> None:
    run, command_log, lifecycle_dir = _regional_lifecycle_harness(tmp_path)
    assert run("create-canary-stopped", with_secret=True).returncode == 0
    terminal = run("start-canary-once", omit_refresh_postcondition=True)
    assert terminal.returncode != 0
    started_at, completed_at = _canonical_canary_attempt_window(lifecycle_dir)
    if mutation == "altered-before":
        before_path = lifecycle_dir / "federal_invariance_before.json"
        before = json.loads(before_path.read_text(encoding="utf-8"))
        before["captured_at"] = (
            (datetime.fromisoformat(before["captured_at"]) + timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
        )
        before_path.write_text(json.dumps(before, sort_keys=True) + "\n", encoding="utf-8")
        before_path.chmod(0o600)
    else:
        marker_path = lifecycle_dir / "start_attempt.json"
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        marker["schema_version"] = 2
        marker.pop("invariance_admission")
        marker_path.write_text(json.dumps(marker, sort_keys=True) + "\n", encoding="utf-8")
        marker_path.chmod(0o600)

    refused = run(
        "start-canary-once",
        refresh_postcondition=_terminal_regional_refresh_postcondition(
            pull_status="success",
            metadata_updates=1,
            completed_at=completed_at,
        ),
        authority_ledger_proof=_regional_canary_authority_ledger_proof(
            started_at=started_at,
            completed_at=completed_at,
        ),
    )

    assert refused.returncode != 0
    assert "durable federal invariance baseline is invalid" in refused.stderr
    assert not (lifecycle_dir / "authority_ledger_proof.json").exists()
    assert not (lifecycle_dir / "database_postcondition.json").exists()
    invocations = [json.loads(line) for line in command_log.read_text().splitlines()]
    assert len([row for row in invocations if row[:3] == ["flyctl", "machine", "start"]]) == 1


def test_regional_recurring_create_accepts_only_complete_canary_promotion_artifact(
    tmp_path: Path,
) -> None:
    run, _, lifecycle_dir = _regional_lifecycle_harness(tmp_path)

    result = run("create-stopped", with_secret=True)

    assert result.returncode == 0, result.stderr
    assert (lifecycle_dir / "admitted_canary_promotion.json").is_file()


def _seed_exact_r36_absent_canary_rollback(tmp_path: Path, lifecycle_dir: Path) -> None:
    receipt_path = tmp_path / "candidate_receipt.json"
    receipt_path.write_text(json.dumps(R36_CANDIDATE_RECEIPT, sort_keys=True) + "\n", encoding="utf-8")
    assert hashlib.sha256(receipt_path.read_bytes()).hexdigest() == R36_CANDIDATE_RECEIPT_SHA256
    assert hashlib.sha256(REGIONAL_PROFILE_PATH.read_bytes()).hexdigest() == (
        "a00f9e7285fc0c4f10247fc4f99fe82c405eda8c6f11ea9c602899ddbc392267"
    )
    common = {
        "app": "civibus-regional-refresh",
        "authority": "state/WA",
        "candidate_receipt_file_sha256": R36_CANDIDATE_RECEIPT_SHA256,
        "execution_plan": "regional-wa-scheduled",
        "machine_name": "regional-wa-scheduled",
        "profile_file_sha256": "a00f9e7285fc0c4f10247fc4f99fe82c405eda8c6f11ea9c602899ddbc392267",
        "schema_version": 2,
    }
    marker_specs = {
        "canary_mode.json": ("regional_canary_mode", R36_MACHINE_ID),
        "create_ownership.json": ("regional_create_ownership", None),
        "machine_ownership.json": ("regional_machine_ownership", R36_MACHINE_ID),
        "provision.json": ("regional_stopped_provision", R36_MACHINE_ID),
        "rollback_attempt.json": ("regional_rollback_attempt", None),
        "start_attempt.json": ("regional_start_attempt", R36_MACHINE_ID),
    }
    for marker_name, (kind, machine_id) in marker_specs.items():
        marker_path = lifecycle_dir / marker_name
        marker_path.write_text(
            json.dumps({**common, "kind": kind, "machine_id": machine_id}, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        marker_path.chmod(0o600)
        assert hashlib.sha256(marker_path.read_bytes()).hexdigest() == R36_MARKER_SHA256[marker_name]
    assert {path.name for path in lifecycle_dir.iterdir()} == set(R36_MARKER_SHA256)


def _new_invocations(command_log: Path, offset: int) -> list[list[str]]:
    return [json.loads(line) for line in command_log.read_text().splitlines()[offset:]]


def _assert_no_regional_mutation(invocations: list[list[str]]) -> None:
    assert not any(
        row[:3]
        in (
            ["flyctl", "machine", "start"],
            ["flyctl", "machine", "stop"],
            ["flyctl", "machine", "destroy"],
            ["flyctl", "apps", "create"],
            ["flyctl", "apps", "destroy"],
        )
        for row in invocations
    )


@pytest.mark.parametrize(
    ("site", "marker_name", "expected_kind", "occurrence"),
    [
        ("absent-provision", "provision.json", "regional_stopped_provision", 1),
        ("absent-start", "start_attempt.json", "regional_start_attempt", 1),
        ("absent-canary", "canary_mode.json", "regional_canary_mode", 1),
        ("absent-stopped", "rollback_stopped.json", "regional_rollback_stopped", 1),
        ("absent-complete", "rollback_complete.json", "regional_rollback_complete", 1),
        ("create-machine", "machine_ownership.json", "regional_machine_ownership", 1),
        ("create-canary", "canary_mode.json", "regional_canary_mode", 1),
        ("start-canary", "canary_mode.json", "regional_canary_mode", 1),
        ("live-provision", "provision.json", "regional_stopped_provision", 1),
        ("live-stopped", "rollback_stopped.json", "regional_rollback_stopped", 2),
        ("live-canary", "canary_mode.json", "regional_canary_mode", 1),
        ("live-terminal", "canary_machine_terminal.json", "regional_canary_machine_terminal", 1),
        ("live-start", "start_attempt.json", "regional_start_attempt", 1),
    ],
    ids=lambda value: value if isinstance(value, str) and "-" in value else None,
)
def test_regional_marker_validator_matching_stdout_with_nonzero_status_always_refuses(
    tmp_path: Path,
    site: str,
    marker_name: str,
    expected_kind: str,
    occurrence: int,
) -> None:
    run, command_log, lifecycle_dir = _regional_lifecycle_harness(tmp_path)
    complete_before: bytes | None = None
    stopped_before: bytes | None = None

    def seed_rollback_marker(name: str, kind: str) -> None:
        payload = json.loads((lifecycle_dir / "provision.json").read_text(encoding="utf-8"))
        payload["kind"] = kind
        path = lifecycle_dir / name
        path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        path.chmod(0o600)

    if site.startswith("absent-"):
        _seed_exact_r36_absent_canary_rollback(tmp_path, lifecycle_dir)
        if site in {"absent-stopped", "absent-complete"}:
            seed_rollback_marker("rollback_stopped.json", "regional_rollback_stopped")
            stopped_before = (lifecycle_dir / "rollback_stopped.json").read_bytes()
        if site == "absent-complete":
            seed_rollback_marker("rollback_complete.json", "regional_rollback_complete")
            complete_before = (lifecycle_dir / "rollback_complete.json").read_bytes()
        offset = len(command_log.read_text().splitlines()) if command_log.exists() else 0
        result = run(
            "rollback",
            failure="regional_historical_app_absent",
            refresh_postcondition=_terminal_regional_refresh_postcondition(machine_id=R36_MACHINE_ID),
            expected_refresh_run_id=R36_REFRESH_RUN_ID,
            validator_failure_marker=marker_name,
            validator_failure_occurrence=occurrence,
        )
    elif site == "create-machine":
        offset = len(command_log.read_text().splitlines()) if command_log.exists() else 0
        result = run(
            "create-stopped",
            with_secret=True,
            validator_failure_marker=marker_name,
            validator_failure_occurrence=occurrence,
        )
    elif site == "create-canary":
        offset = len(command_log.read_text().splitlines()) if command_log.exists() else 0
        result = run(
            "create-canary-stopped",
            with_secret=True,
            validator_failure_marker=marker_name,
            validator_failure_occurrence=occurrence,
        )
    elif site == "start-canary":
        assert run("create-canary-stopped", with_secret=True).returncode == 0
        offset = len(command_log.read_text().splitlines())
        result = run(
            "start-canary-once",
            validator_failure_marker=marker_name,
            validator_failure_occurrence=occurrence,
        )
    else:
        if site in {"live-canary", "live-terminal", "live-stopped"}:
            assert run("create-canary-stopped", with_secret=True).returncode == 0
        else:
            assert run("create-stopped", with_secret=True).returncode == 0
        if site == "live-terminal":
            started = run("start-canary-once")
            assert started.returncode != 0
            assert (lifecycle_dir / "canary_machine_terminal.json").is_file()
        elif site == "live-start":
            assert run("start-once").returncode == 0
        elif site == "live-stopped":
            assert run("start-canary-once", failure="regional_canary_wait_failure").returncode != 0
            pending = run(
                "rollback",
                failure="regional_rollback_started",
                omit_refresh_postcondition=True,
            )
            assert pending.returncode != 0
            assert (lifecycle_dir / "rollback_stopped.json").is_file()
            stopped_before = (lifecycle_dir / "rollback_stopped.json").read_bytes()
        offset = len(command_log.read_text().splitlines())
        result = run(
            "rollback",
            omit_refresh_postcondition=True,
            validator_failure_marker=marker_name,
            validator_failure_occurrence=occurrence,
        )

    expected_error = {
        "absent-provision": "historical provision marker does not match exact Machine ownership",
        "absent-start": "historical start marker does not match exact Machine ownership",
        "absent-canary": "historical canary marker does not match exact Machine ownership",
        "absent-stopped": "historical rollback-stopped marker does not match exact Machine ownership",
        "absent-complete": "historical rollback-complete marker does not match exact Machine ownership",
        "create-machine": "regional Machine ownership marker does not match after stopped-state wait",
        "create-canary": "regional canary-mode marker does not match after stopped-state wait",
        "start-canary": "regional canary-mode marker does not match exact Machine ownership",
        "live-provision": "regional provision receipt does not match exact Machine ownership",
        "live-stopped": "regional rollback-stopped marker does not match exact Machine ownership",
        "live-canary": "regional canary-mode marker does not match exact Machine ownership",
        "live-terminal": "regional canary Machine terminal receipt does not match exact Machine ownership",
        "live-start": "running regional Machine has no exact start-attempt ownership",
    }[site]
    assert result.returncode != 0
    assert expected_error in result.stderr
    injection_log = (tmp_path / "validator_status_injections.log").read_text(encoding="utf-8").splitlines()
    assert injection_log == [f"{lifecycle_dir / marker_name}|{expected_kind}"]
    invocations = _new_invocations(command_log, offset)
    if site.startswith(("absent-", "live-")) or site == "start-canary":
        _assert_no_regional_mutation(invocations)
    else:
        assert not any(
            row[:3]
            in (
                ["flyctl", "machine", "start"],
                ["flyctl", "machine", "stop"],
                ["flyctl", "machine", "destroy"],
                ["flyctl", "apps", "destroy"],
            )
            for row in invocations
        )
        assert not (lifecycle_dir / "provision.json").exists()
    if site != "absent-complete":
        assert not (lifecycle_dir / "rollback_complete.json").exists()
    else:
        assert (lifecycle_dir / "rollback_complete.json").read_bytes() == complete_before
    if stopped_before is not None:
        assert (lifecycle_dir / "rollback_stopped.json").read_bytes() == stopped_before
    else:
        assert not (lifecycle_dir / "rollback_stopped.json").exists()


def test_historical_absent_canary_rollback_finalizes_exact_r36_markers_without_fly_mutation(
    tmp_path: Path,
) -> None:
    run, command_log, lifecycle_dir = _regional_lifecycle_harness(tmp_path)
    _seed_exact_r36_absent_canary_rollback(tmp_path, lifecycle_dir)
    offset = len(command_log.read_text().splitlines()) if command_log.exists() else 0
    postcondition = _terminal_regional_refresh_postcondition(machine_id=R36_MACHINE_ID)

    result = run(
        "rollback",
        failure="regional_historical_app_absent",
        refresh_postcondition=postcondition,
        expected_refresh_run_id=R36_REFRESH_RUN_ID,
    )

    assert result.returncode == 0, result.stderr
    invocations = _new_invocations(command_log, offset)
    _assert_no_regional_mutation(invocations)
    assert [row for row in invocations if row[0] == "flyctl"] == [["flyctl", "apps", "list", "--json"]]
    stopped_path = lifecycle_dir / "rollback_stopped.json"
    complete_path = lifecycle_dir / "rollback_complete.json"
    stopped = stopped_path.read_bytes()
    complete = complete_path.read_bytes()
    assert stopped_path.stat().st_mode & 0o777 == 0o600
    assert complete_path.stat().st_mode & 0o777 == 0o600
    assert json.loads(stopped)["kind"] == "regional_rollback_stopped"
    assert json.loads(complete)["kind"] == "regional_rollback_complete"
    assert json.loads(stopped)["machine_id"] == R36_MACHINE_ID
    assert json.loads(complete)["machine_id"] == R36_MACHINE_ID

    repeat_offset = len(command_log.read_text().splitlines())
    repeated = run(
        "rollback",
        failure="regional_historical_app_absent",
        refresh_postcondition=postcondition,
        expected_refresh_run_id=R36_REFRESH_RUN_ID,
    )

    assert repeated.returncode == 0, repeated.stderr
    assert stopped_path.read_bytes() == stopped
    assert complete_path.read_bytes() == complete
    repeated_invocations = _new_invocations(command_log, repeat_offset)
    _assert_no_regional_mutation(repeated_invocations)
    assert [row for row in repeated_invocations if row[0] == "flyctl"] == [["flyctl", "apps", "list", "--json"]]


@pytest.mark.parametrize(
    ("postcondition", "expected_error"),
    [
        (
            _terminal_regional_refresh_postcondition(
                pull_status="success", metadata_updates=1, machine_id=R36_MACHINE_ID
            ),
            "historical rollback requires the recovered failed refresh attempt",
        ),
        (
            _terminal_regional_refresh_postcondition(
                pull_status="running", completed_at=None, machine_id=R36_MACHINE_ID
            ),
            "exact refresh attempt is not terminal",
        ),
        (
            _terminal_regional_refresh_postcondition(metadata_updates=1, machine_id=R36_MACHINE_ID),
            "historical rollback requires zero metadata updates",
        ),
        (
            _terminal_regional_refresh_postcondition(running_refresh_rows=1, machine_id=R36_MACHINE_ID),
            "running refresh rows remain",
        ),
        (
            _terminal_regional_refresh_postcondition(active_refresh_backends=1, machine_id=R36_MACHINE_ID),
            "active refresh backends remain",
        ),
        (
            _terminal_regional_refresh_postcondition(long_idle_transactions=1, machine_id=R36_MACHINE_ID),
            "long-idle database transactions remain",
        ),
        (
            _terminal_regional_refresh_postcondition(ungranted_locks=1, machine_id=R36_MACHINE_ID),
            "ungranted database locks remain",
        ),
        (
            {**_terminal_regional_refresh_postcondition(machine_id=R36_MACHINE_ID), "job_key": "state-wa-loans"},
            "refresh postcondition identity mismatch",
        ),
        (
            {
                **_terminal_regional_refresh_postcondition(machine_id=R36_MACHINE_ID),
                "database": {"host": "foreign.internal", "port": 5432, "name": "civibus"},
            },
            "refresh postcondition identity mismatch",
        ),
        (
            _terminal_regional_refresh_postcondition(machine_id="def456"),
            "refresh postcondition identity mismatch",
        ),
        (
            _terminal_regional_refresh_postcondition(
                machine_id=R36_MACHINE_ID,
                refresh_run_id="11111111-1111-4111-8111-111111111111",
            ),
            "refresh postcondition attempt identity mismatch",
        ),
    ],
    ids=(
        "success",
        "nonterminal",
        "metadata-updates",
        "running-row",
        "active-backend",
        "long-idle-transaction",
        "ungranted-lock",
        "foreign-job",
        "foreign-database",
        "foreign-machine",
        "foreign-attempt",
    ),
)
def test_historical_absent_canary_rollback_refuses_nonexact_recovery_postcondition(
    tmp_path: Path,
    postcondition: dict[str, object],
    expected_error: str,
) -> None:
    run, command_log, lifecycle_dir = _regional_lifecycle_harness(tmp_path)
    _seed_exact_r36_absent_canary_rollback(tmp_path, lifecycle_dir)
    offset = len(command_log.read_text().splitlines()) if command_log.exists() else 0

    result = run(
        "rollback",
        failure="regional_historical_app_absent",
        refresh_postcondition=postcondition,
        expected_refresh_run_id=R36_REFRESH_RUN_ID,
    )

    assert result.returncode != 0
    assert expected_error in result.stderr
    assert not (lifecycle_dir / "rollback_stopped.json").exists()
    assert not (lifecycle_dir / "rollback_complete.json").exists()
    _assert_no_regional_mutation(_new_invocations(command_log, offset))


@pytest.mark.parametrize(
    ("marker_name", "mutation"),
    [
        *((marker_name, "missing") for marker_name in R36_MARKER_SHA256),
        ("canary_mode.json", "foreign-profile"),
        ("create_ownership.json", "foreign-receipt"),
        ("machine_ownership.json", "foreign-machine"),
        ("rollback_attempt.json", "foreign-machine"),
    ],
)
def test_historical_absent_canary_rollback_refuses_missing_or_drifted_markers(
    tmp_path: Path,
    marker_name: str,
    mutation: str,
) -> None:
    run, command_log, lifecycle_dir = _regional_lifecycle_harness(tmp_path)
    _seed_exact_r36_absent_canary_rollback(tmp_path, lifecycle_dir)
    marker_path = lifecycle_dir / marker_name
    if mutation == "missing":
        marker_path.unlink()
    else:
        marker = json.loads(marker_path.read_text())
        if mutation == "foreign-profile":
            marker["profile_file_sha256"] = "0" * 64
        elif mutation == "foreign-receipt":
            marker["candidate_receipt_file_sha256"] = "0" * 64
        else:
            marker["machine_id"] = "def456"
        marker_path.write_text(json.dumps(marker, sort_keys=True) + "\n", encoding="utf-8")
    offset = len(command_log.read_text().splitlines()) if command_log.exists() else 0

    result = run(
        "rollback",
        failure="regional_historical_app_absent",
        refresh_postcondition=_terminal_regional_refresh_postcondition(machine_id=R36_MACHINE_ID),
        expected_refresh_run_id=R36_REFRESH_RUN_ID,
    )

    assert result.returncode != 0
    assert not (lifecycle_dir / "rollback_stopped.json").exists()
    assert not (lifecycle_dir / "rollback_complete.json").exists()
    _assert_no_regional_mutation(_new_invocations(command_log, offset))


@pytest.mark.parametrize("failure", ["regional_preexisting_app", "regional_historical_app_ambiguous"])
def test_historical_absent_canary_rollback_refuses_present_or_ambiguous_app_inventory(
    tmp_path: Path,
    failure: str,
) -> None:
    run, command_log, lifecycle_dir = _regional_lifecycle_harness(tmp_path)
    _seed_exact_r36_absent_canary_rollback(tmp_path, lifecycle_dir)
    offset = len(command_log.read_text().splitlines()) if command_log.exists() else 0

    result = run(
        "rollback",
        failure=failure,
        refresh_postcondition=_terminal_regional_refresh_postcondition(machine_id=R36_MACHINE_ID),
        expected_refresh_run_id=R36_REFRESH_RUN_ID,
    )

    assert result.returncode != 0
    assert not (lifecycle_dir / "rollback_stopped.json").exists()
    assert not (lifecycle_dir / "rollback_complete.json").exists()
    _assert_no_regional_mutation(_new_invocations(command_log, offset))


def test_regional_lifecycle_consumes_runner_historical_recovery_postcondition(
    tmp_path: Path,
) -> None:
    run, _, lifecycle_dir = _regional_lifecycle_harness(tmp_path)
    assert run("create-canary-stopped", with_secret=True).returncode == 0
    assert run("start-canary-once", failure="regional_canary_wait_failure").returncode != 0
    started_at = datetime(2026, 8, 29, 23, 39, 28, tzinfo=timezone.utc)
    completed_at = datetime(2026, 8, 30, 0, 20, tzinfo=timezone.utc)
    identity = runner.HistoricalRefreshRecoveryIdentity(
        refresh_run_id=UUID("e00cb630-7024-4c5d-8c10-ef2a87e83db7"),
        job_key="state-wa-contributions",
        domain="campaign_finance",
        jurisdiction="state/WA",
        filing_authority_type="state",
        filing_authority_code="WA",
        data_source_names=("WA PDC Contributions",),
        execution_origin="operator_attended",
        started_at=started_at,
        app="civibus-regional-refresh",
        machine_id="abc123",
        authority="state/WA",
        execution_plan="regional-wa-scheduled",
        database_host="civibus-db.internal",
        database_port=5432,
        database_name="civibus",
    )
    attempt = RefreshRun(
        id=identity.refresh_run_id,
        job_key=identity.job_key,
        domain=identity.domain,
        jurisdiction=identity.jurisdiction,
        data_source_names=list(identity.data_source_names),
        execution_origin=identity.execution_origin,
        pull_status="failed",
        started_at=started_at,
        completed_at=completed_at,
        metadata_updates=0,
        message=runner._HISTORICAL_RECOVERY_MESSAGE,
        error=runner._HISTORICAL_RECOVERY_ERROR,
    )
    postcondition = runner.build_historical_recovery_postcondition(
        identity,
        attempt,
        running_refresh_rows=0,
        active_refresh_backends=0,
        long_idle_transactions=0,
        ungranted_locks=0,
    )

    result = run("rollback", refresh_postcondition=postcondition)

    assert result.returncode == 0, result.stderr
    assert (lifecycle_dir / "rollback_complete.json").is_file()


def test_regional_lifecycle_is_stopped_start_once_and_nonforce_reversible(
    tmp_path: Path,
) -> None:
    run, command_log, lifecycle_dir = _regional_lifecycle_harness(tmp_path)

    created = run("create-stopped", with_secret=True)
    assert created.returncode == 0, created.stderr
    invocations = [json.loads(line) for line in command_log.read_text().splitlines()] if command_log.exists() else []
    machine_creates = [row for row in invocations if row[:3] == ["flyctl", "machine", "create"]]
    assert len(machine_creates) == 1
    assert machine_creates[0][3] == IMAGE_TAG
    assert not any(row[:3] == ["flyctl", "machine", "start"] for row in invocations)
    assert "do-not-log-this" not in command_log.read_text()
    assert "do-not-log-this" not in created.stdout + created.stderr
    assert not any(path.name.startswith(".capture.") for path in lifecycle_dir.iterdir())
    assert all("do-not-log-this" not in path.read_text() for path in lifecycle_dir.iterdir())
    verifier_calls = [
        row for row in invocations if row[:2] == ["bash", str(VERIFIER_SCRIPT)] and "--profile-json" in row
    ]
    assert verifier_calls
    assert all(
        "/.capture." in row[row.index("--profile-json") + 1]
        or row[row.index("--profile-json") + 1] == str(lifecycle_dir / "profile.json")
        for row in verifier_calls
    )
    assert json.loads((lifecycle_dir / "provision.json").read_text())["machine_id"] == "abc123"

    started = run("start-once")
    assert started.returncode == 0, started.stderr
    second_start = run("start-once")
    assert second_start.returncode != 0
    invocations = [json.loads(line) for line in command_log.read_text().splitlines()]
    assert len([row for row in invocations if row[:3] == ["flyctl", "machine", "start"]]) == 1

    rolled_back = run("rollback")
    assert rolled_back.returncode == 0, rolled_back.stderr
    invocations = [json.loads(line) for line in command_log.read_text().splitlines()]
    assert len([row for row in invocations if row[:3] == ["flyctl", "machine", "stop"]]) == 1
    destroys = [row for row in invocations if row[:3] == ["flyctl", "machine", "destroy"]]
    assert destroys == [["flyctl", "machine", "destroy", "abc123", "-a", "civibus-regional-refresh"]]
    assert all("--force" not in row for row in invocations)
    assert len([row for row in invocations if row[:3] == ["flyctl", "apps", "destroy"]]) == 1


@pytest.mark.parametrize("action", ["create-stopped", "create-canary-stopped"])
def test_regional_machine_create_uses_private_json_file_and_cleans_it(
    tmp_path: Path,
    action: str,
) -> None:
    run, command_log, lifecycle_dir = _regional_lifecycle_harness(tmp_path)

    result = run(action, with_secret=True)

    assert result.returncode == 0, result.stderr
    invocations = [json.loads(line) for line in command_log.read_text().splitlines()]
    machine_creates = [row for row in invocations if row[:3] == ["flyctl", "machine", "create"]]
    assert len(machine_creates) == 1
    config_path = Path(machine_creates[0][machine_creates[0].index("--machine-config") + 1])
    assert config_path.suffix == ".json"
    assert not config_path.exists()
    assert not any(argument.lstrip().startswith("{") for argument in machine_creates[0])
    assert "do-not-log-this" not in result.stdout + result.stderr + command_log.read_text()
    assert not any(path.name.startswith(".capture.") for path in lifecycle_dir.iterdir())


@pytest.mark.parametrize("action", ["create-stopped", "create-canary-stopped"])
def test_regional_stopped_create_waits_for_exact_machine_then_recaptures_and_provisions(
    tmp_path: Path,
    action: str,
) -> None:
    run, command_log, lifecycle_dir = _regional_lifecycle_harness(tmp_path)

    result = run(
        action,
        with_secret=True,
        failure="regional_create_transient_created",
    )

    assert result.returncode == 0, result.stderr
    invocations = [json.loads(line) for line in command_log.read_text().splitlines()]
    exact_wait = [
        "flyctl",
        "machine",
        "wait",
        "abc123",
        "-a",
        "civibus-regional-refresh",
        "--state",
        "stopped",
        "--wait-timeout",
        "30m",
    ]
    assert [row for row in invocations if row[:3] == ["flyctl", "machine", "wait"]] == [exact_wait]
    inventory_indices = [
        index
        for index, row in enumerate(invocations)
        if row == ["flyctl", "machines", "list", "-a", "civibus-regional-refresh", "--json"]
    ]
    wait_index = invocations.index(exact_wait)
    config_index = invocations.index(
        [
            "flyctl",
            "machine",
            "status",
            "abc123",
            "-a",
            "civibus-regional-refresh",
            "--display-config",
        ]
    )
    assert len(inventory_indices) == 2
    assert inventory_indices[0] < wait_index < inventory_indices[1] < config_index
    expected_markers = {
        "create_ownership.json": ("regional_create_ownership", None),
        "machine_ownership.json": ("regional_machine_ownership", "abc123"),
        "provision.json": ("regional_stopped_provision", "abc123"),
    }
    if action == "create-canary-stopped":
        expected_markers["canary_mode.json"] = ("regional_canary_mode", "abc123")
    for marker_name, (kind, machine_id) in expected_markers.items():
        marker = json.loads((lifecycle_dir / marker_name).read_text(encoding="utf-8"))
        assert (marker["kind"], marker["machine_id"]) == (kind, machine_id)
    assert (lifecycle_dir / "canary_mode.json").is_file() is (action == "create-canary-stopped")
    assert not (lifecycle_dir / "start_attempt.json").exists()
    assert not any(
        row[:3]
        in (
            ["flyctl", "machine", "start"],
            ["flyctl", "machine", "stop"],
            ["flyctl", "machine", "destroy"],
            ["flyctl", "apps", "destroy"],
        )
        for row in invocations
    )


@pytest.mark.parametrize("action", ["create-stopped", "create-canary-stopped"])
@pytest.mark.parametrize(
    "failure",
    [
        "regional_create_wait_nonzero",
        "regional_create_wait_timeout",
        "regional_create_post_wait_wrong_state",
        "regional_create_post_wait_identity_drift",
        "regional_create_post_wait_marker_mismatch",
        "regional_create_post_wait_ambiguous",
        "regional_create_post_wait_config_drift",
        "regional_create_post_wait_image_drift",
    ],
)
def test_regional_stopped_create_wait_or_postwait_failure_preserves_rollback_ownership(
    tmp_path: Path,
    action: str,
    failure: str,
) -> None:
    run, command_log, lifecycle_dir = _regional_lifecycle_harness(tmp_path)

    result = run(action, with_secret=True, failure=failure)

    assert result.returncode != 0
    initial_invocations = [json.loads(line) for line in command_log.read_text().splitlines()]
    assert len([row for row in initial_invocations if row[:3] == ["flyctl", "machine", "wait"]]) == 1
    expected_markers = {
        "create_ownership.json": ("regional_create_ownership", None),
        "machine_ownership.json": ("regional_machine_ownership", "abc123"),
    }
    if action == "create-canary-stopped":
        expected_markers["canary_mode.json"] = ("regional_canary_mode", "abc123")
    for marker_name, (kind, machine_id) in expected_markers.items():
        marker = json.loads((lifecycle_dir / marker_name).read_text(encoding="utf-8"))
        assert (marker["kind"], marker["machine_id"]) == (kind, machine_id)
    assert (lifecycle_dir / "canary_mode.json").is_file() is (action == "create-canary-stopped")
    assert not (lifecycle_dir / "provision.json").exists()
    assert not (lifecycle_dir / "start_attempt.json").exists()
    assert "do-not-log-this" not in result.stdout + result.stderr + command_log.read_text()
    machine_creates = [row for row in initial_invocations if row[:3] == ["flyctl", "machine", "create"]]
    assert len(machine_creates) == 1
    assert not any(argument.lstrip().startswith("{") for argument in machine_creates[0])
    config_path = Path(machine_creates[0][machine_creates[0].index("--machine-config") + 1])
    assert config_path.suffix == ".json"
    assert not config_path.exists()
    assert not any(
        row[:3]
        in (
            ["flyctl", "machine", "start"],
            ["flyctl", "machine", "stop"],
            ["flyctl", "machine", "destroy"],
            ["flyctl", "apps", "destroy"],
        )
        for row in initial_invocations
    )

    cleanup = run("rollback")

    assert cleanup.returncode == 0, cleanup.stderr
    all_invocations = [json.loads(line) for line in command_log.read_text().splitlines()]
    assert not any(
        row[:3] in (["flyctl", "machine", "start"], ["flyctl", "machine", "stop"]) for row in all_invocations
    )
    assert [row for row in all_invocations if row[:3] == ["flyctl", "machine", "destroy"]] == [
        ["flyctl", "machine", "destroy", "abc123", "-a", "civibus-regional-refresh"]
    ]
    assert len([row for row in all_invocations if row[:3] == ["flyctl", "apps", "destroy"]]) == 1


def test_regional_canary_create_accepts_flyctl_equivalent_omitted_defaults(
    tmp_path: Path,
) -> None:
    run, command_log, lifecycle_dir = _regional_lifecycle_harness(tmp_path)

    result = run(
        "create-canary-stopped",
        with_secret=True,
        failure="regional_flyctl_equivalent_defaults",
    )

    assert result.returncode == 0, result.stderr
    assert (lifecycle_dir / "provision.json").is_file()
    invocations = [json.loads(line) for line in command_log.read_text().splitlines()]
    assert not any(
        row[:3]
        in (
            ["flyctl", "machine", "start"],
            ["flyctl", "machine", "destroy"],
            ["flyctl", "apps", "destroy"],
        )
        for row in invocations
    )


def test_regional_canary_rollback_accepts_flyctl_equivalent_omitted_defaults(
    tmp_path: Path,
) -> None:
    run, command_log, _ = _regional_lifecycle_harness(tmp_path)
    assert run("create-canary-stopped", with_secret=True).returncode == 0

    result = run("rollback", failure="regional_flyctl_equivalent_defaults")

    assert result.returncode == 0, result.stderr
    invocations = [json.loads(line) for line in command_log.read_text().splitlines()]
    assert not any(row[:3] in (["flyctl", "machine", "start"], ["flyctl", "machine", "stop"]) for row in invocations)
    assert [row for row in invocations if row[:3] == ["flyctl", "machine", "destroy"]] == [
        ["flyctl", "machine", "destroy", "abc123", "-a", "civibus-regional-refresh"]
    ]
    assert len([row for row in invocations if row[:3] == ["flyctl", "apps", "destroy"]]) == 1


def test_regional_contributions_canary_is_singleton_terminal_and_exactly_rolled_back(
    tmp_path: Path,
) -> None:
    run, command_log, lifecycle_dir = _regional_lifecycle_harness(tmp_path)

    created = run("create-canary-stopped", with_secret=True)
    assert created.returncode == 0, created.stderr
    assert (lifecycle_dir / "canary_mode.json").is_file()

    started = run("start-canary-once")
    assert started.returncode != 0
    assert "exact database postcondition is required" in started.stderr
    assert (lifecycle_dir / "canary_machine_terminal.json").is_file()
    retry = run("start-canary-once")
    assert retry.returncode != 0

    rolled_back = run("rollback")
    assert rolled_back.returncode == 0, rolled_back.stderr
    invocations = [json.loads(line) for line in command_log.read_text().splitlines()]
    starts = [row for row in invocations if row[:3] == ["flyctl", "machine", "start"]]
    waits = [row for row in invocations if row[:3] == ["flyctl", "machine", "wait"]]
    assert starts == [["flyctl", "machine", "start", "abc123", "-a", "civibus-regional-refresh"]]
    expected_wait = [
        "flyctl",
        "machine",
        "wait",
        "abc123",
        "-a",
        "civibus-regional-refresh",
        "--state",
        "stopped",
        "--wait-timeout",
        "30m",
    ]
    assert waits == [expected_wait, expected_wait]
    wait_indices = [index for index, row in enumerate(invocations) if row == expected_wait]
    assert wait_indices[0] < invocations.index(starts[0]) < wait_indices[1]
    assert not any("--force" in row for row in invocations)
    assert not any(row[:3] == ["flyctl", "machine", "stop"] for row in invocations)
    assert [row for row in invocations if row[:3] == ["flyctl", "machine", "destroy"]] == [
        ["flyctl", "machine", "destroy", "abc123", "-a", "civibus-regional-refresh"]
    ]
    assert len([row for row in invocations if row[:3] == ["flyctl", "apps", "destroy"]]) == 1

    profile = json.loads(REGIONAL_PROFILE_PATH.read_text(encoding="utf-8"))
    assert profile["canary"]["command"] == [
        "python",
        "-m",
        "core.refresh.runner",
        "--authority-plan-json",
        "infra/fly/regional_refresh_machine_profile.json",
        "--execution-mode",
        "canary",
        "--execution-origin",
        "operator_attended",
    ]
    assert "--force" not in profile["canary"]["command"]
    assert "--no-lock" not in profile["canary"]["command"]
    assert profile["canary"]["schedule"] is None
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


@pytest.mark.parametrize("failure", ["regional_wrong_app", "regional_wrong_org"])
def test_regional_create_validates_app_before_secret_or_machine_mutation(
    tmp_path: Path,
    failure: str,
) -> None:
    run, command_log, lifecycle_dir = _regional_lifecycle_harness(tmp_path)

    result = run("create-stopped", with_secret=True, failure=failure)

    assert result.returncode != 0
    assert (lifecycle_dir / "create_ownership.json").is_file()
    invocations = [json.loads(line) for line in command_log.read_text().splitlines()]
    assert not any(row[:3] == ["flyctl", "secrets", "import"] for row in invocations)
    assert not any(row[:3] == ["flyctl", "machine", "create"] for row in invocations)


@pytest.mark.parametrize("secret_kind", ["malformed", "wrong-mode", "symlink"])
def test_regional_create_refuses_unsafe_secret_file_before_fly_mutation(
    tmp_path: Path,
    secret_kind: str,
) -> None:
    run, command_log, _ = _regional_lifecycle_harness(tmp_path, secret_kind=secret_kind)

    result = run("create-stopped", with_secret=True)

    assert result.returncode != 0
    invocations = [json.loads(line) for line in command_log.read_text().splitlines()] if command_log.exists() else []
    assert not any(row[0] == "flyctl" for row in invocations)


@pytest.mark.parametrize(
    ("failure", "expected_error"),
    [
        (
            "regional_registry_manifest_absent",
            "registry metadata could not resolve the qualified regional image",
        ),
        (
            "regional_registry_manifest_mismatch",
            "qualified regional image digest changed before lifecycle handoff",
        ),
    ],
)
def test_regional_create_revalidates_registry_identity_before_any_mutation(
    tmp_path: Path,
    failure: str,
    expected_error: str,
) -> None:
    run, command_log, lifecycle_dir = _regional_lifecycle_harness(tmp_path)

    result = run(
        "create-stopped",
        with_secret=True,
        failure=failure,
    )

    assert result.returncode != 0
    assert expected_error in result.stderr
    invocations = [json.loads(line) for line in command_log.read_text().splitlines()]
    assert [row for row in invocations if row[:3] == ["docker", "buildx", "imagetools"]] == [
        ["docker", "buildx", "imagetools", "inspect", IMAGE_TAG]
    ]
    assert not any(
        row[:3]
        in (
            ["flyctl", "apps", "create"],
            ["flyctl", "secrets", "import"],
            ["flyctl", "machine", "create"],
        )
        for row in invocations
    )
    assert not any(path.name.startswith(".capture.") for path in lifecycle_dir.iterdir())


@pytest.mark.parametrize(
    "input_name",
    ["profile", "receipt", "profile-directory", "receipt-directory"],
)
def test_regional_lifecycle_refuses_symlinked_identity_inputs_before_fly_mutation(
    tmp_path: Path,
    input_name: str,
) -> None:
    run, command_log, _ = _regional_lifecycle_harness(
        tmp_path,
        lifecycle_input_kind=input_name,
    )

    result = run("create-stopped", with_secret=True)

    assert result.returncode != 0
    invocations = [json.loads(line) for line in command_log.read_text().splitlines()] if command_log.exists() else []
    assert not any(row[0] == "flyctl" for row in invocations)


@pytest.mark.parametrize(
    "failure",
    [
        "regional_preexisting_app",
        "regional_preexisting_app_id_only",
        "regional_apps_not_list",
        "regional_malformed_apps",
        "regional_apps_missing_identity",
        "regional_app_create",
        "regional_secret_import",
        "regional_machine_create",
    ],
)
def test_regional_create_failure_is_single_attempt_and_retains_bounded_ownership_evidence(
    tmp_path: Path,
    failure: str,
) -> None:
    run, command_log, lifecycle_dir = _regional_lifecycle_harness(tmp_path)

    result = run("create-stopped", with_secret=True, failure=failure)

    assert result.returncode != 0
    assert "do-not-log-this" not in result.stdout + result.stderr + command_log.read_text()
    invocations = [json.loads(line) for line in command_log.read_text().splitlines()]
    expected_calls = {
        "regional_preexisting_app": (0, 0),
        "regional_preexisting_app_id_only": (0, 0),
        "regional_apps_not_list": (0, 0),
        "regional_malformed_apps": (0, 0),
        "regional_apps_missing_identity": (0, 0),
        "regional_app_create": (1, 0),
        "regional_secret_import": (1, 0),
        "regional_machine_create": (1, 1),
    }
    app_creates, machine_creates = expected_calls[failure]
    assert len([row for row in invocations if row[:3] == ["flyctl", "apps", "create"]]) == app_creates
    assert len([row for row in invocations if row[:3] == ["flyctl", "machine", "create"]]) == machine_creates
    assert not (lifecycle_dir / "machine_ownership.json").exists()
    assert not any(row[:3] in (["flyctl", "machine", "destroy"], ["flyctl", "apps", "destroy"]) for row in invocations)


def test_regional_create_ambiguity_cannot_be_rolled_back_without_exact_machine_ownership(
    tmp_path: Path,
) -> None:
    run, command_log, lifecycle_dir = _regional_lifecycle_harness(tmp_path)

    created = run("create-stopped", with_secret=True, failure="regional_create_ambiguity")
    rolled_back = run("rollback", failure="regional_create_ambiguity")

    assert created.returncode != 0
    assert rolled_back.returncode != 0
    assert not (lifecycle_dir / "machine_ownership.json").exists()
    invocations = [json.loads(line) for line in command_log.read_text().splitlines()]
    assert not any(row[:3] in (["flyctl", "machine", "destroy"], ["flyctl", "apps", "destroy"]) for row in invocations)


def test_regional_app_only_rollback_cleans_up_after_secret_staging_failure(
    tmp_path: Path,
) -> None:
    run, command_log, _ = _regional_lifecycle_harness(tmp_path)
    assert run("create-stopped", with_secret=True, failure="regional_secret_import").returncode != 0

    result = run("rollback")

    assert result.returncode == 0, result.stderr
    invocations = [json.loads(line) for line in command_log.read_text().splitlines()]
    assert not any(row[:3] == ["flyctl", "machine", "destroy"] for row in invocations)
    assert len([row for row in invocations if row[:3] == ["flyctl", "apps", "destroy"]]) == 1


@pytest.mark.parametrize(
    "failure",
    [
        "regional_wrong_app",
        "regional_wrong_org",
        "regional_wrong_machine_name",
        "regional_wrong_machine_region",
        "regional_wrong_machine_state",
        "regional_auto_destroy_true",
        "regional_files_nonlist",
        "regional_files_nonempty",
        "regional_mounts_nonlist",
        "regional_mounts_nonempty",
        "regional_services_nonlist",
        "regional_services_nonempty",
        "regional_dns_nonmapping",
        "regional_dns_nonempty",
        "regional_missing_material_key",
        "regional_changed_material_value",
        "regional_unexpected_top_level_key",
        "regional_image_drift",
        "regional_config_secret",
    ],
)
def test_regional_live_identity_or_config_drift_fails_without_retaining_secrets(
    tmp_path: Path,
    failure: str,
) -> None:
    run, command_log, lifecycle_dir = _regional_lifecycle_harness(tmp_path)

    result = run("create-stopped", with_secret=True, failure=failure)

    assert result.returncode != 0
    assert (lifecycle_dir / "machine_ownership.json").is_file() is (
        failure not in {"regional_wrong_app", "regional_wrong_org", "regional_wrong_machine_name"}
    )
    assert not (lifecycle_dir / "provision.json").exists()
    assert "do-not-log-this" not in result.stdout + result.stderr + command_log.read_text()
    assert not any(path.name.startswith(".capture.") for path in lifecycle_dir.iterdir())
    assert all("do-not-log-this" not in path.read_text() for path in lifecycle_dir.iterdir())
    invocations = [json.loads(line) for line in command_log.read_text().splitlines()]
    assert not any(
        row[:3]
        in (
            ["flyctl", "machine", "start"],
            ["flyctl", "machine", "destroy"],
            ["flyctl", "apps", "destroy"],
        )
        for row in invocations
    )


def test_regional_canary_rollback_refuses_nondefault_config_before_destroy(
    tmp_path: Path,
) -> None:
    run, command_log, lifecycle_dir = _regional_lifecycle_harness(tmp_path)
    assert run("create-canary-stopped", with_secret=True).returncode == 0

    result = run("rollback", failure="regional_dns_nonempty")

    assert result.returncode != 0
    assert (lifecycle_dir / "rollback_attempt.json").is_file()
    invocations = [json.loads(line) for line in command_log.read_text().splitlines()]
    assert not any(
        row[:3] in (["flyctl", "machine", "start"], ["flyctl", "machine", "destroy"], ["flyctl", "apps", "destroy"])
        for row in invocations
    )


def test_regional_start_failure_cannot_retry_start_once(
    tmp_path: Path,
) -> None:
    run, command_log, _ = _regional_lifecycle_harness(tmp_path)
    assert run("create-stopped", with_secret=True).returncode == 0

    first = run("start-once", failure="regional_start_failure")
    second = run("start-once", failure="regional_start_failure")

    assert first.returncode != 0
    assert second.returncode != 0
    invocations = [json.loads(line) for line in command_log.read_text().splitlines()]
    assert len([row for row in invocations if row[:3] == ["flyctl", "machine", "start"]]) == 1


def test_regional_canary_start_failure_cannot_retry_and_exact_rollback_still_cleans_up(
    tmp_path: Path,
) -> None:
    run, command_log, _ = _regional_lifecycle_harness(tmp_path)
    assert run("create-canary-stopped", with_secret=True).returncode == 0

    first = run("start-canary-once", failure="regional_start_failure")
    second = run("start-canary-once", failure="regional_start_failure")
    cleanup = run("rollback")

    assert first.returncode != 0
    assert second.returncode != 0
    assert cleanup.returncode == 0, cleanup.stderr
    invocations = [json.loads(line) for line in command_log.read_text().splitlines()]
    assert len([row for row in invocations if row[:3] == ["flyctl", "machine", "start"]]) == 1
    assert len([row for row in invocations if row[:3] == ["flyctl", "machine", "destroy"]]) == 1
    assert len([row for row in invocations if row[:3] == ["flyctl", "apps", "destroy"]]) == 1


@pytest.mark.parametrize(
    "failure",
    [
        "regional_canary_wait_failure",
        "regional_canary_exit_missing",
        "regional_canary_exit_nonzero",
        "regional_canary_exit_ambiguous",
    ],
)
def test_regional_canary_terminal_proof_fails_closed_without_retry_and_can_clean_up(
    tmp_path: Path,
    failure: str,
) -> None:
    run, command_log, lifecycle_dir = _regional_lifecycle_harness(tmp_path)
    assert run("create-canary-stopped", with_secret=True).returncode == 0

    first = run("start-canary-once", failure=failure)
    retry = run("start-canary-once", failure=failure)
    cleanup = run("rollback")

    assert first.returncode != 0
    assert retry.returncode != 0
    assert not (lifecycle_dir / "canary_machine_terminal.json").exists()
    assert cleanup.returncode == 0, cleanup.stderr
    invocations = [json.loads(line) for line in command_log.read_text().splitlines()]
    assert len([row for row in invocations if row[:3] == ["flyctl", "machine", "start"]]) == 1
    assert len([row for row in invocations if row[:3] == ["flyctl", "machine", "destroy"]]) == 1
    assert len([row for row in invocations if row[:3] == ["flyctl", "apps", "destroy"]]) == 1
    assert all("--force" not in row for row in invocations)


def test_regional_post_start_verification_failure_cannot_retry_start_once(
    tmp_path: Path,
) -> None:
    run, command_log, lifecycle_dir = _regional_lifecycle_harness(tmp_path)
    assert run("create-stopped", with_secret=True).returncode == 0

    first = run("start-once", failure="regional_post_start_drift")
    retry = run("start-once", failure="regional_post_start_drift")

    assert first.returncode != 0
    assert retry.returncode != 0
    assert (lifecycle_dir / "start_attempt.json").is_file()
    invocations = [json.loads(line) for line in command_log.read_text().splitlines()]
    assert len([row for row in invocations if row[:3] == ["flyctl", "machine", "start"]]) == 1


@pytest.mark.parametrize(
    ("identity_drift", "action", "lifecycle_input_kind"),
    [
        ("profile-file", "start-once", "mutable-profile"),
        ("receipt-file", "start-once", ""),
        ("provision-symlink", "start-once", ""),
        ("provision-malformed", "start-once", ""),
        ("provision-reformatted", "start-once", ""),
        ("provision-duplicate", "start-once", ""),
        ("create_ownership-symlink", "rollback", ""),
        ("create_ownership-malformed", "rollback", ""),
    ],
)
def test_regional_later_action_refuses_persisted_identity_drift_before_fly_mutation(
    tmp_path: Path,
    identity_drift: str,
    action: str,
    lifecycle_input_kind: str,
) -> None:
    run, command_log, lifecycle_dir = _regional_lifecycle_harness(
        tmp_path,
        lifecycle_input_kind=lifecycle_input_kind,
    )
    assert run("create-stopped", with_secret=True).returncode == 0
    before = command_log.read_text().splitlines()

    if identity_drift == "profile-file":
        profile_path = tmp_path / "profile-copy.json"
        profile_path.write_text(json.dumps(json.loads(profile_path.read_text()), indent=2), encoding="utf-8")
    elif identity_drift == "receipt-file":
        receipt_path = tmp_path / "candidate_receipt.json"
        receipt_path.write_text(json.dumps(json.loads(receipt_path.read_text()), indent=2), encoding="utf-8")
    else:
        marker_name, marker_kind = identity_drift.split("-", 1)
        marker_path = lifecycle_dir / f"{marker_name}.json"
        if marker_kind == "symlink":
            marker_target = lifecycle_dir / f"{marker_name}-target.json"
            marker_path.rename(marker_target)
            marker_path.symlink_to(marker_target)
        elif marker_kind == "reformatted":
            marker_path.write_text(json.dumps(json.loads(marker_path.read_text()), indent=2), encoding="utf-8")
        elif marker_kind == "duplicate":
            payload = json.loads(marker_path.read_text())
            marker_path.write_text(
                marker_path.read_text().rstrip()[:-1] + f', "machine_id": "{payload["machine_id"]}"}}\n',
                encoding="utf-8",
            )
        else:
            marker_path.write_text("{}\n", encoding="utf-8")

    result = run(action)

    assert result.returncode != 0
    after = [json.loads(line) for line in command_log.read_text().splitlines()[len(before) :]]
    assert not any(
        row[:3]
        in (
            ["flyctl", "machine", "start"],
            ["flyctl", "machine", "stop"],
            ["flyctl", "machine", "destroy"],
            ["flyctl", "apps", "destroy"],
        )
        for row in after
    )


def test_regional_started_rollback_requires_exact_start_attempt_marker(
    tmp_path: Path,
) -> None:
    run, command_log, lifecycle_dir = _regional_lifecycle_harness(tmp_path)
    assert run("create-stopped", with_secret=True).returncode == 0
    assert run("start-once").returncode == 0
    (lifecycle_dir / "start_attempt.json").unlink()

    result = run("rollback")

    assert result.returncode != 0
    invocations = [json.loads(line) for line in command_log.read_text().splitlines()]
    assert not any(row[:3] in (["flyctl", "machine", "stop"], ["flyctl", "machine", "destroy"]) for row in invocations)


@pytest.mark.parametrize(
    ("postcondition", "expected_error"),
    [
        (
            _terminal_regional_refresh_postcondition(
                pull_status="running",
                completed_at=None,
                running_refresh_rows=1,
            ),
            "exact refresh attempt is not terminal",
        ),
        (
            _terminal_regional_refresh_postcondition(active_refresh_backends=1),
            "active refresh backends remain",
        ),
        (
            _terminal_regional_refresh_postcondition(long_idle_transactions=1),
            "long-idle database transactions remain",
        ),
        (
            _terminal_regional_refresh_postcondition(ungranted_locks=1),
            "ungranted database locks remain",
        ),
        (
            {**_terminal_regional_refresh_postcondition(), "job_key": "state-wa-loans"},
            "refresh postcondition identity mismatch",
        ),
    ],
)
def test_regional_started_rollback_refuses_stale_running_backend_or_foreign_attempt_postcondition(
    tmp_path: Path,
    postcondition: dict[str, object],
    expected_error: str,
) -> None:
    run, command_log, lifecycle_dir = _regional_lifecycle_harness(tmp_path)
    assert run("create-canary-stopped", with_secret=True).returncode == 0
    started = run("start-canary-once", omit_refresh_postcondition=True)
    assert started.returncode != 0
    assert "exact database postcondition is required" in started.stderr

    result = run("rollback", refresh_postcondition=postcondition)

    assert result.returncode != 0
    assert expected_error in result.stderr
    assert not (lifecycle_dir / "rollback_complete.json").exists()
    invocations = [json.loads(line) for line in command_log.read_text().splitlines()]
    assert len([row for row in invocations if row[:3] == ["flyctl", "machine", "destroy"]]) <= 1
    assert all("--force" not in row for row in invocations)


def test_regional_canary_stop_is_durable_but_rollback_refuses_without_exact_terminal_zero_state_receipt(
    tmp_path: Path,
) -> None:
    run, command_log, lifecycle_dir = _regional_lifecycle_harness(tmp_path)
    assert run("create-canary-stopped", with_secret=True).returncode == 0

    started = run("start-canary-once", omit_refresh_postcondition=True)
    assert started.returncode != 0
    assert "exact database postcondition is required" in started.stderr
    assert (lifecycle_dir / "canary_machine_terminal.json").is_file()

    missing = run("rollback", omit_refresh_postcondition=True)
    assert missing.returncode != 0
    assert "exact terminal refresh postcondition is required after stopping" in missing.stderr
    assert (lifecycle_dir / "rollback_stopped.json").is_file()
    assert not (lifecycle_dir / "rollback_complete.json").exists()
    invocations = [json.loads(line) for line in command_log.read_text().splitlines()]
    assert not any(row[:3] == ["flyctl", "machine", "destroy"] for row in invocations)


def test_regional_started_canary_rollback_stops_once_then_resumes_only_with_terminal_receipt(
    tmp_path: Path,
) -> None:
    run, command_log, lifecycle_dir = _regional_lifecycle_harness(tmp_path)
    assert run("create-canary-stopped", with_secret=True).returncode == 0
    assert run("start-canary-once", failure="regional_canary_wait_failure").returncode != 0

    pending = run("rollback", omit_refresh_postcondition=True, failure="regional_rollback_started")
    assert pending.returncode != 0
    assert "exact terminal refresh postcondition is required after stopping" in pending.stderr
    assert (lifecycle_dir / "rollback_stopped.json").is_file()
    assert not (lifecycle_dir / "rollback_complete.json").exists()

    completed = run(
        "rollback",
        refresh_postcondition=_terminal_regional_refresh_postcondition(pull_status="failed", metadata_updates=0),
    )
    assert completed.returncode == 0, completed.stderr
    assert (lifecycle_dir / "rollback_complete.json").is_file()
    invocations = [json.loads(line) for line in command_log.read_text().splitlines()]
    assert len([row for row in invocations if row[:3] == ["flyctl", "machine", "stop"]]) == 1
    assert len([row for row in invocations if row[:3] == ["flyctl", "machine", "destroy"]]) == 1


def test_exact_four_create_refuses_without_prior_complete_canary_postcondition(
    tmp_path: Path,
) -> None:
    run, command_log, _ = _regional_lifecycle_harness(tmp_path)

    result = run("create-stopped", with_secret=True, omit_canary_promotion=True)

    assert result.returncode != 0
    assert "complete canary promotion artifact is required before recurring provisioning" in result.stderr
    invocations = [json.loads(line) for line in command_log.read_text().splitlines()] if command_log.exists() else []
    assert not any(row[:3] == ["flyctl", "apps", "create"] for row in invocations)


def test_regional_rollback_requires_provision_and_machine_ownership_to_match(
    tmp_path: Path,
) -> None:
    run, command_log, lifecycle_dir = _regional_lifecycle_harness(tmp_path)
    assert run("create-stopped", with_secret=True).returncode == 0
    provision = json.loads((lifecycle_dir / "provision.json").read_text())
    provision["machine_id"] = "def456"
    (lifecycle_dir / "provision.json").write_text(json.dumps(provision), encoding="utf-8")

    result = run("rollback")

    assert result.returncode != 0
    invocations = [json.loads(line) for line in command_log.read_text().splitlines()]
    assert not any(
        row[:3] in (["flyctl", "machine", "stop"], ["flyctl", "machine", "destroy"], ["flyctl", "apps", "destroy"])
        for row in invocations
    )


@pytest.mark.parametrize(
    "failure",
    [
        "regional_wrong_app",
        "regional_wrong_org",
        "regional_wrong_machine_id",
        "regional_extra_machine",
        "regional_indeterminate_state",
    ],
)
def test_regional_rollback_refuses_identity_inventory_or_state_drift_before_mutation(
    tmp_path: Path,
    failure: str,
) -> None:
    run, command_log, _ = _regional_lifecycle_harness(tmp_path)
    assert run("create-stopped", with_secret=True).returncode == 0

    result = run("rollback", failure=failure)
    retry = run("rollback", failure=failure)

    assert result.returncode != 0
    assert retry.returncode != 0
    invocations = [json.loads(line) for line in command_log.read_text().splitlines()]
    assert not any(
        row[:3] in (["flyctl", "machine", "stop"], ["flyctl", "machine", "destroy"], ["flyctl", "apps", "destroy"])
        for row in invocations
    )


def test_regional_prestart_rollback_removes_exact_stopped_machine_without_stop(
    tmp_path: Path,
) -> None:
    run, command_log, _ = _regional_lifecycle_harness(tmp_path)
    assert run("create-stopped", with_secret=True).returncode == 0

    result = run("rollback")

    assert result.returncode == 0, result.stderr
    invocations = [json.loads(line) for line in command_log.read_text().splitlines()]
    assert not any(row[:3] in (["flyctl", "machine", "start"], ["flyctl", "machine", "stop"]) for row in invocations)
    assert [row for row in invocations if row[:3] == ["flyctl", "machine", "destroy"]] == [
        ["flyctl", "machine", "destroy", "abc123", "-a", "civibus-regional-refresh"]
    ]
    assert not any("--force" in row for row in invocations)
    assert len([row for row in invocations if row[:3] == ["flyctl", "apps", "destroy"]]) == 1


def test_regional_rollback_refuses_app_destroy_when_volume_inventory_is_not_empty(
    tmp_path: Path,
) -> None:
    run, command_log, _ = _regional_lifecycle_harness(tmp_path)
    assert run("create-stopped", with_secret=True).returncode == 0

    result = run("rollback", failure="regional_extra_volume")

    assert result.returncode != 0
    invocations = [json.loads(line) for line in command_log.read_text().splitlines()]
    assert not any(row[:3] == ["flyctl", "machine", "destroy"] for row in invocations)
    assert not any(row[:3] == ["flyctl", "apps", "destroy"] for row in invocations)


@pytest.mark.parametrize(
    ("failure", "expected_app_destroys"),
    [
        ("regional_lingering_machine", 0),
        ("regional_predestroy_wrong_org", 0),
        ("regional_lingering_app", 1),
    ],
)
def test_regional_rollback_postmutation_verification_failure_blocks_every_retry(
    tmp_path: Path,
    failure: str,
    expected_app_destroys: int,
) -> None:
    run, command_log, _ = _regional_lifecycle_harness(tmp_path)
    assert run("create-stopped", with_secret=True).returncode == 0

    first = run("rollback", failure=failure)
    retry = run("rollback", failure=failure)

    assert first.returncode != 0
    assert retry.returncode != 0
    invocations = [json.loads(line) for line in command_log.read_text().splitlines()]
    assert len([row for row in invocations if row[:3] == ["flyctl", "machine", "destroy"]]) == 1
    assert len([row for row in invocations if row[:3] == ["flyctl", "apps", "destroy"]]) == expected_app_destroys


@pytest.mark.parametrize(
    "failure",
    ["regional_post_stop_wrong_org", "regional_post_stop_started", "regional_post_start_drift"],
)
def test_regional_rollback_revalidates_identity_config_and_stopped_state_after_stop(
    tmp_path: Path,
    failure: str,
) -> None:
    run, command_log, _ = _regional_lifecycle_harness(tmp_path)
    assert run("create-stopped", with_secret=True).returncode == 0
    assert run("start-once").returncode == 0

    first = run("rollback", failure=failure)
    retry = run("rollback", failure=failure)

    assert first.returncode != 0
    assert retry.returncode != 0
    invocations = [json.loads(line) for line in command_log.read_text().splitlines()]
    assert len([row for row in invocations if row[:3] == ["flyctl", "machine", "stop"]]) == 1
    assert not any(row[:3] in (["flyctl", "machine", "destroy"], ["flyctl", "apps", "destroy"]) for row in invocations)


@pytest.mark.parametrize(
    ("failure", "started"),
    [
        ("regional_stop_failure", True),
        ("regional_destroy_failure", False),
        ("regional_app_destroy_failure", False),
    ],
)
def test_regional_rollback_owner_never_retries_a_failed_mutation(
    tmp_path: Path,
    failure: str,
    started: bool,
) -> None:
    run, command_log, _ = _regional_lifecycle_harness(tmp_path)
    assert run("create-stopped", with_secret=True).returncode == 0
    if started:
        assert run("start-once").returncode == 0

    result = run("rollback", failure=failure)
    retry = run("rollback", failure=failure)

    assert result.returncode != 0
    assert retry.returncode != 0
    invocations = [json.loads(line) for line in command_log.read_text().splitlines()]
    command = {
        "regional_stop_failure": "stop",
        "regional_destroy_failure": "destroy",
        "regional_app_destroy_failure": "destroy",
    }[failure]
    prefix = ["flyctl", "apps" if failure == "regional_app_destroy_failure" else "machine", command]
    assert len([row for row in invocations if row[:3] == prefix]) == 1


def test_machine_image_selector_avoids_flyctl_v0493_double_digest_composition() -> None:
    digest = IMAGE_DIGEST.rsplit("@", 1)[1]

    # flyctl v0.4.93 resolves a remote image and appends its digest. Supplying
    # the already-digested proof token therefore reproduces the rejected PA
    # launch identifier without asking flyctl to create a Machine.
    assert f"{IMAGE_DIGEST}@{digest}" == (f"registry.fly.io/{APP_NAME}@sha256:{'a' * 64}@sha256:{'a' * 64}")

    result = _run_machine_image_selector()

    assert result.returncode == 0, result.stderr
    assert result.stdout == f"{IMAGE_TAG}\n"
    assert result.stderr == ""
    assert f"{result.stdout.strip()}@{digest}" == IMAGE_TAGGED_DIGEST


@pytest.mark.parametrize(
    "proven_identity",
    [
        IMAGE_DIGEST,
        IMAGE_TAG,
        f"registry.fly.io/another-app:deployment-stage2@sha256:{'a' * 64}",
        f"{IMAGE_TAG}@sha256:short",
        f"registry.fly.io/{APP_NAME}:bad/tag@sha256:{'a' * 64}",
        f"{IMAGE_DIGEST}@sha256:{'a' * 64}",
    ],
)
def test_machine_image_selector_fails_closed_for_unpaired_or_invalid_identity(
    proven_identity: str,
) -> None:
    result = _run_machine_image_selector(proven_identity)

    assert result.returncode != 0
    assert result.stdout == ""
    assert "FAIL: refresh Machine deploy: invalid immutable image identity" in result.stderr


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
