"""Contract tests for the deployed public-surface parity probe."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PROBE_PATH = REPO_ROOT / "infra/scripts/probe_deployed_surface_parity.sh"
RUNBOOK_PATH = REPO_ROOT / "docs/howto/operations/fly_deployment_runbook.md"
DEFAULT_PUBLIC_BASE_URL = "https://civibus-caddy.fly.dev"
EXPECTED_SHA = subprocess.run(
    ["git", "rev-parse", "HEAD"],
    cwd=REPO_ROOT,
    text=True,
    capture_output=True,
    check=True,
).stdout.strip()
DRIFTED_SHA = subprocess.run(
    ["git", "rev-parse", "HEAD~1"],
    cwd=REPO_ROOT,
    text=True,
    capture_output=True,
    check=True,
).stdout.strip()


def _write_fixture(
    fixture_dir: Path,
    *,
    repo_paths: set[str],
    deployed_paths: set[str],
    page_statuses: dict[str, int | str] | None = None,
    openapi_status: int = 200,
    api_version_payload: dict[str, str] | None = None,
    web_version_payload: dict[str, str] | None = None,
    api_version_status: int = 200,
    web_version_status: int = 200,
) -> None:
    fixture_dir.mkdir()
    (fixture_dir / "repo_openapi_paths.json").write_text(
        json.dumps(sorted(repo_paths)),
        encoding="utf-8",
    )
    (fixture_dir / "deployed_openapi.json").write_text(
        json.dumps({"paths": {path: {} for path in sorted(deployed_paths)}}),
        encoding="utf-8",
    )
    (fixture_dir / "deployed_openapi_status.txt").write_text(
        f"{openapi_status}\n",
        encoding="utf-8",
    )
    statuses = page_statuses or {"/": 200, "/congress": 200, "/developers": 200}
    (fixture_dir / "page_statuses.tsv").write_text(
        "".join(f"{path}\t{status}\n" for path, status in statuses.items()),
        encoding="utf-8",
    )
    (fixture_dir / "api_health_version.json").write_text(
        json.dumps(api_version_payload or {"git_sha": EXPECTED_SHA, "built_at": "2026-07-14T21:20:44Z"}),
        encoding="utf-8",
    )
    (fixture_dir / "web_version.json").write_text(
        json.dumps(web_version_payload or {"git_sha": EXPECTED_SHA, "built_at": "2026-07-14T21:20:44Z"}),
        encoding="utf-8",
    )
    (fixture_dir / "api_health_version_status.txt").write_text(f"{api_version_status}\n", encoding="utf-8")
    (fixture_dir / "web_version_status.txt").write_text(f"{web_version_status}\n", encoding="utf-8")


def _run_probe(fixture_dir: Path, *, expected_sha: str = EXPECTED_SHA) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("CIVIBUS_PUBLIC_BASE_URL", None)
    env["CIVIBUS_DEPLOYED_SURFACE_FIXTURE_DIR"] = str(fixture_dir)
    env["CIVIBUS_EXPECTED_SHA"] = expected_sha
    return subprocess.run(
        ["bash", str(PROBE_PATH)],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_deployed_surface_parity_probe_accepts_matching_fixture_surface(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "matching"
    _write_fixture(
        fixture_dir,
        repo_paths={"/health", "/public/v1/federal/officials", "/v1/candidates"},
        deployed_paths={"/health", "/public/v1/federal/officials", "/v1/candidates"},
    )

    result = _run_probe(fixture_dir)

    assert result.returncode == 0, result.stderr
    assert f"base_url {DEFAULT_PUBLIC_BASE_URL}" in result.stdout
    assert f"deployed_sha_match expected={EXPECTED_SHA} api={EXPECTED_SHA} web={EXPECTED_SHA}" in result.stdout
    assert "openapi_paths_match repo=3 deployed=3" in result.stdout
    assert "page_status / 200" in result.stdout
    assert "page_status /congress 200" in result.stdout
    assert "page_status /developers 200" in result.stdout
    assert "surface_parity_ok" in result.stdout


def test_deployed_surface_parity_probe_fails_loud_on_sha_drift(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "sha-drift"
    _write_fixture(
        fixture_dir,
        repo_paths={"/health", "/public/v1/federal/officials", "/v1/candidates"},
        deployed_paths={"/health", "/public/v1/federal/officials", "/v1/candidates"},
        api_version_payload={"git_sha": DRIFTED_SHA, "built_at": "2026-07-13T21:20:44Z"},
        web_version_payload={"git_sha": DRIFTED_SHA, "built_at": "2026-07-13T21:20:44Z"},
    )

    result = _run_probe(fixture_dir)

    assert result.returncode != 0
    assert "deployed_sha_drift" in result.stderr
    assert f"expected_sha {EXPECTED_SHA}" in result.stderr
    assert f"api_deployed_sha {DRIFTED_SHA}" in result.stderr
    assert f"web_deployed_sha {DRIFTED_SHA}" in result.stderr
    assert f"commit_delta {DRIFTED_SHA}..{EXPECTED_SHA}" in result.stderr


def test_deployed_surface_parity_probe_fails_loud_on_unknown_sha(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "sha-unknown"
    _write_fixture(
        fixture_dir,
        repo_paths={"/health"},
        deployed_paths={"/health"},
        api_version_status=404,
        web_version_payload={"git_sha": "unknown", "built_at": "2026-07-13T21:20:44Z"},
    )

    result = _run_probe(fixture_dir)

    assert result.returncode != 0
    assert "deployed_sha_unknown" in result.stderr


def test_deployed_surface_parity_probe_normalizes_invalid_sha_to_unknown(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "invalid-sha"
    _write_fixture(
        fixture_dir,
        repo_paths={"/health"},
        deployed_paths={"/health"},
        api_version_payload={
            "git_sha": "not-a-valid-commit",
            "built_at": "2026-07-13T21:20:44Z",
        },
    )

    result = _run_probe(fixture_dir)

    assert result.returncode != 0
    assert "deployed_sha_unknown" in result.stderr
    assert "api=unknown" in result.stderr


def test_deployed_surface_parity_probe_names_paths_missing_from_deployed(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "missing-deployed"
    _write_fixture(
        fixture_dir,
        repo_paths={"/health", "/v1/candidates"},
        deployed_paths={"/health"},
    )

    result = _run_probe(fixture_dir)

    assert result.returncode != 0
    assert "missing_from_deployed /v1/candidates" in result.stderr


def test_deployed_surface_parity_probe_names_paths_missing_from_repo(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "missing-repo"
    _write_fixture(
        fixture_dir,
        repo_paths={"/health"},
        deployed_paths={"/health", "/v1/extra"},
    )

    result = _run_probe(fixture_dir)

    assert result.returncode != 0
    assert "missing_from_repo /v1/extra" in result.stderr


def test_deployed_surface_parity_probe_names_openapi_unexpected_http_status(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "openapi-status"
    _write_fixture(
        fixture_dir,
        repo_paths={"/health"},
        deployed_paths={"/health"},
        openapi_status=503,
    )

    result = _run_probe(fixture_dir)

    assert result.returncode != 0
    assert "openapi_unexpected_http_status" in result.stderr
    assert "503" in result.stderr


def test_deployed_surface_parity_probe_names_missing_public_pages(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "missing-page"
    _write_fixture(
        fixture_dir,
        repo_paths={"/health"},
        deployed_paths={"/health"},
        page_statuses={"/": 200, "/congress": 404, "/developers": 200},
    )

    result = _run_probe(fixture_dir)

    assert result.returncode != 0
    assert "missing_page /congress 404" in result.stderr


def test_fly_runbook_documents_deployed_surface_parity_probe() -> None:
    runbook_text = RUNBOOK_PATH.read_text(encoding="utf-8")

    assert "## Post-deploy Deployed Surface Parity" in runbook_text
    assert "`bash infra/scripts/probe_deployed_surface_parity.sh`" in runbook_text
    assert "`CIVIBUS_PUBLIC_BASE_URL`" in runbook_text
    assert "`CIVIBUS_EXPECTED_SHA`" in runbook_text
    assert DEFAULT_PUBLIC_BASE_URL in runbook_text


def test_probe_contract_includes_expected_sha_default_owner() -> None:
    probe_text = PROBE_PATH.read_text(encoding="utf-8")

    assert "CIVIBUS_EXPECTED_SHA" in probe_text
    assert "git fetch origin main" in probe_text
    assert "/api/health/version" in probe_text
    assert "/version.json" in probe_text
