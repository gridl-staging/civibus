"""Behavioral contract for the delegated production rollback owner.

`infra/scripts/rollback_serving_apps.sh` is the single owner of "put the serving
apps back on the image they were running before this deploy touched them". The
deploy workflow delegates to it exactly the way it delegates the refresh-machine
deploy to `deploy_refresh_machine.sh`, so the workflow YAML stays thin.

These tests EXECUTE the script against a stub `flyctl` on `PATH` rather than
asserting on its source text. That matters: the failure this script exists to
prevent is a rollback that silently no-ops, and only a behavioral test can tell
"restored three apps" apart from "printed nothing and exited 0".

Anchored incident: 2026-08-03. A red deploy left `civibus-api` crash-looping for
~40 minutes because no rollback path existed at all. See
`docs/live-state/2026_08_03_production_outage_restore.md`.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
ROLLBACK_SCRIPT_PATH = REPO_ROOT / "infra/scripts/rollback_serving_apps.sh"
API_DOCKERFILE_PATH = REPO_ROOT / "infra/api/Dockerfile"
API_FLY_CONFIG_PATH = REPO_ROOT / "infra/fly/api.fly.toml"
API_ENTRYPOINT_PATH = REPO_ROOT / "infra/api/docker-entrypoint.sh"

# The serving set, and only the serving set. `civibus-db` holds the data and
# `civibus-refresh` is a scheduled worker; rolling either back from a failed
# serving deploy would turn a recoverable outage into a data incident.
ERROR_PREFIX = "rollback_serving_apps:"
SERVING_APPS = ("civibus-api", "civibus-web", "civibus-caddy")
FORBIDDEN_ROLLBACK_APPS = ("civibus-db", "civibus-refresh")


def _write_stub_flyctl(directory: Path, *, images: dict[str, str], argv_log: Path) -> None:
    """Install a fake `flyctl` that logs argv and answers `machine list --json`.

    `images` maps app name to the image the stub reports as currently running;
    an app mapped to the empty string reports a machine with no image, which is
    how we exercise the "refuse to deploy without a rollback target" path.
    """
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        f'printf "%s\\n" "$*" >> {argv_log}',
        'if [[ "${1:-}" == "machine" && "${2:-}" == "list" ]]; then',
        "  app=''",
        "  for ((i = 1; i <= $#; i++)); do",
        '    if [[ "${!i}" == "-a" ]]; then next=$((i + 1)); app="${!next}"; fi',
        "  done",
        '  case "$app" in',
    ]
    for app, image in images.items():
        # A machine with no image is reported as JSON null, exactly as flyctl
        # would for a machine that has never been deployed.
        image_json = f'\\"{image}\\"' if image else "null"
        lines.append(f'    {app}) printf \'[{{"config":{{"image":{image_json}}}}}]\\n\' ;;')
    lines.extend(
        [
            "    *) printf '[]\\n' ;;",
            "  esac",
            "  exit 0",
            "fi",
            "exit 0",
        ]
    )
    stub = directory / "flyctl"
    stub.write_text("\n".join(lines) + "\n", encoding="utf-8")
    stub.chmod(0o755)


def _run_script(*args: str, stub_dir: Path) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PATH"] = f"{stub_dir}{os.pathsep}{env['PATH']}"
    return subprocess.run(
        ["bash", str(ROLLBACK_SCRIPT_PATH), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


@pytest.fixture
def stub_env(tmp_path: Path) -> tuple[Path, Path]:
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    argv_log = tmp_path / "flyctl_argv.log"
    argv_log.write_text("", encoding="utf-8")
    return stub_dir, argv_log


def test_rollback_script_exists() -> None:
    assert ROLLBACK_SCRIPT_PATH.is_file(), f"missing delegated rollback owner at {ROLLBACK_SCRIPT_PATH}"


def test_capture_records_one_app_config_image_triple_per_serving_app(
    tmp_path: Path, stub_env: tuple[Path, Path]
) -> None:
    stub_dir, argv_log = stub_env
    _write_stub_flyctl(
        stub_dir,
        images={
            "civibus-api": "registry.fly.io/civibus-api:deployment-AAA",
            "civibus-web": "registry.fly.io/civibus-web:deployment-BBB",
            "civibus-caddy": "registry.fly.io/civibus-caddy:deployment-CCC",
        },
        argv_log=argv_log,
    )
    manifest = tmp_path / "pre_deploy_images.txt"

    result = _run_script("capture", str(manifest), stub_dir=stub_dir)

    assert result.returncode == 0, result.stderr
    # Hand-calculated expected content: the exact three lines, in serving order,
    # each pairing the app with its own fly config and its running image.
    assert manifest.read_text(encoding="utf-8").splitlines() == [
        "civibus-api|infra/fly/api.fly.toml|registry.fly.io/civibus-api:deployment-AAA",
        "civibus-web|infra/fly/web.fly.toml|registry.fly.io/civibus-web:deployment-BBB",
        "civibus-caddy|infra/fly/caddy.fly.toml|registry.fly.io/civibus-caddy:deployment-CCC",
    ]


def test_capture_never_touches_the_database_or_refresh_apps(tmp_path: Path, stub_env: tuple[Path, Path]) -> None:
    stub_dir, argv_log = stub_env
    _write_stub_flyctl(
        stub_dir,
        images={app: f"registry.fly.io/{app}:deployment-X" for app in SERVING_APPS},
        argv_log=argv_log,
    )

    result = _run_script("capture", str(tmp_path / "manifest.txt"), stub_dir=stub_dir)

    assert result.returncode == 0, result.stderr
    invocations = argv_log.read_text(encoding="utf-8")
    for app in FORBIDDEN_ROLLBACK_APPS:
        assert app not in invocations, f"rollback capture must never query {app}"


def test_capture_refuses_when_an_app_reports_no_running_image(tmp_path: Path, stub_env: tuple[Path, Path]) -> None:
    """No rollback target means the deploy has no safety net — fail loud, do not proceed."""
    stub_dir, argv_log = stub_env
    _write_stub_flyctl(
        stub_dir,
        images={
            "civibus-api": "registry.fly.io/civibus-api:deployment-AAA",
            "civibus-web": "",
            "civibus-caddy": "registry.fly.io/civibus-caddy:deployment-CCC",
        },
        argv_log=argv_log,
    )
    manifest = tmp_path / "manifest.txt"

    result = _run_script("capture", str(manifest), stub_dir=stub_dir)

    assert result.returncode != 0
    assert ERROR_PREFIX in result.stderr
    assert "civibus-web" in result.stderr


def test_restore_redeploys_every_captured_image_with_its_own_config(
    tmp_path: Path, stub_env: tuple[Path, Path]
) -> None:
    stub_dir, argv_log = stub_env
    _write_stub_flyctl(stub_dir, images={app: "unused" for app in SERVING_APPS}, argv_log=argv_log)
    manifest = tmp_path / "manifest.txt"
    manifest.write_text(
        "civibus-api|infra/fly/api.fly.toml|registry.fly.io/civibus-api:deployment-AAA\n"
        "civibus-web|infra/fly/web.fly.toml|registry.fly.io/civibus-web:deployment-BBB\n"
        "civibus-caddy|infra/fly/caddy.fly.toml|registry.fly.io/civibus-caddy:deployment-CCC\n",
        encoding="utf-8",
    )

    result = _run_script("restore", str(manifest), stub_dir=stub_dir)

    assert result.returncode == 0, result.stderr
    invocations = [line for line in argv_log.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert invocations == [
        "deploy --image registry.fly.io/civibus-api:deployment-AAA -a civibus-api -c infra/fly/api.fly.toml",
        "deploy --image registry.fly.io/civibus-web:deployment-BBB -a civibus-web -c infra/fly/web.fly.toml",
        "deploy --image registry.fly.io/civibus-caddy:deployment-CCC -a civibus-caddy -c infra/fly/caddy.fly.toml",
    ]


def test_api_rollback_restores_image_owned_promotion_evidence_without_shared_state() -> None:
    rollback_text = ROLLBACK_SCRIPT_PATH.read_text(encoding="utf-8")
    dockerfile_text = API_DOCKERFILE_PATH.read_text(encoding="utf-8")
    fly_config_text = API_FLY_CONFIG_PATH.read_text(encoding="utf-8")
    entrypoint_text = API_ENTRYPOINT_PATH.read_text(encoding="utf-8")

    assert '"civibus-api|infra/fly/api.fly.toml"' in rollback_text
    assert 'flyctl deploy --image "$image" -a "$app" -c "$config"' in rollback_text
    assert "COPY infra/api/authority_promotion_bundle /app/private/civibus/authority-promotion" in dockerfile_text
    assert "/app/private/civibus/authority-promotion/authority-promotion-receipt.json" in entrypoint_text
    assert "CIVIBUS_AUTHORITY_PROMOTION_RECEIPT_JSON" not in fly_config_text
    assert "file-local" not in fly_config_text


def test_restore_refuses_an_empty_manifest(tmp_path: Path, stub_env: tuple[Path, Path]) -> None:
    """A rollback that quietly restores nothing is the exact failure mode this owner exists to prevent."""
    stub_dir, argv_log = stub_env
    _write_stub_flyctl(stub_dir, images={}, argv_log=argv_log)
    manifest = tmp_path / "manifest.txt"
    manifest.write_text("", encoding="utf-8")

    result = _run_script("restore", str(manifest), stub_dir=stub_dir)

    assert result.returncode != 0
    assert ERROR_PREFIX in result.stderr, "must be the script refusing, not bash failing to find it"
    assert argv_log.read_text(encoding="utf-8").strip() == "", "an empty manifest must not deploy anything"


def test_restore_refuses_an_app_outside_the_serving_set(tmp_path: Path, stub_env: tuple[Path, Path]) -> None:
    stub_dir, argv_log = stub_env
    _write_stub_flyctl(stub_dir, images={}, argv_log=argv_log)
    manifest = tmp_path / "manifest.txt"
    manifest.write_text(
        "civibus-db|infra/fly/db.fly.toml|registry.fly.io/civibus-db:deployment-ZZZ\n", encoding="utf-8"
    )

    result = _run_script("restore", str(manifest), stub_dir=stub_dir)

    assert result.returncode != 0
    assert "civibus-db" in result.stderr
    assert argv_log.read_text(encoding="utf-8").strip() == "", "a forbidden app must not reach flyctl"


def test_restore_refuses_a_missing_manifest(tmp_path: Path, stub_env: tuple[Path, Path]) -> None:
    stub_dir, argv_log = stub_env
    _write_stub_flyctl(stub_dir, images={}, argv_log=argv_log)

    result = _run_script("restore", str(tmp_path / "does_not_exist.txt"), stub_dir=stub_dir)

    assert result.returncode != 0
    assert ERROR_PREFIX in result.stderr, "must be the script refusing, not bash failing to find it"
    assert argv_log.read_text(encoding="utf-8").strip() == ""


def test_script_rejects_an_unknown_mode(tmp_path: Path, stub_env: tuple[Path, Path]) -> None:
    stub_dir, argv_log = stub_env
    _write_stub_flyctl(stub_dir, images={}, argv_log=argv_log)

    result = _run_script("obliterate", str(tmp_path / "manifest.txt"), stub_dir=stub_dir)

    assert result.returncode != 0
    assert ERROR_PREFIX in result.stderr, "must be the script refusing, not bash failing to find it"
