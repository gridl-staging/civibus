"""Contract tests for the deployed public-surface parity probe."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
PROBE_PATH = REPO_ROOT / "infra/scripts/probe_deployed_surface_parity.sh"
RUNBOOK_PATH = REPO_ROOT / "docs/howto/operations/fly_deployment_runbook.md"
RELEASE_TARGETS_PATH = REPO_ROOT / "web/tests/smoke/production_release_targets.json"
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

PUBLIC_PAGE_BODIES = {
    "/": "Follow money around Congress and the White House.",
    "/search?q=ossoff": 'data-testid="search-results-region"',
    "/donors?q=smith&by=name": 'data-testid="donor-result-row"',
    "/congress": 'data-testid="congress-member-row-0"',
    "/methodology": "Methodology",
    "/developers": "GET /api/public/v1/federal/officials",
    "/candidates": "Candidates",
    "/committees": "Committees",
    "/committee/jon-ossoff-for-senate": "Key metrics",
    "/compare": "Compare officeholders",
    "/calendar": "Election calendar",
    "/coverage": "campaign_finance",
    "/data-sources": "campaign_finance",
    "/sitemap.xml": "<sitemapindex",
}
KNOWN_RED_PAGE_BODIES: dict[str, str] = {}
DEFAULT_PAGE_BODIES = PUBLIC_PAGE_BODIES | KNOWN_RED_PAGE_BODIES


def _release_targets() -> dict[str, object]:
    return json.loads(RELEASE_TARGETS_PATH.read_text(encoding="utf-8"))


def _fixture_body_slug(path: str) -> str:
    return path.encode("utf-8").hex()


def _helper_money_row(index: int, *, has_fec_money: bool = True) -> dict[str, object]:
    targets = _release_targets()
    return {
        "person_id": (
            str(targets["finance_visual_person_id"]) if index == 0 else f"00000000-0000-4000-8000-{index:012d}"
        ),
        "person_name": str(targets["finance_visual_person_name"]) if index == 0 else f"Member {index}",
        "has_fec_money": has_fec_money,
        "candidate_id": f"10000000-0000-4000-8000-{index:012d}" if has_fec_money else None,
        "total_raised": str(targets["finance_visual_minimum_total_raised"]) if index == 0 else "100.00",
        "total_spent": "50.00",
        "net": "50.00",
        "cash_on_hand": "25.00",
        "summary_source": "fec_candidate_summary" if has_fec_money else None,
        "ie_support_total": "2424806.88" if index == 0 else "0.00",
        "ie_oppose_total": "8.00" if index == 0 else "0.00",
        "ie_support_count": 1 if index == 0 else 0,
        "ie_oppose_count": 1 if index == 0 else 0,
        "sources": [{"record_url": "https://www.fec.gov/data/candidate/example/"}],
    }


def _helper_export_rows(*, denominator: int = 540, fec_rows: int = 540) -> list[dict[str, object]]:
    # denominator defaults to an in-range [535, 543] value so the default helper
    # surface is a post-repair PASS specimen; range-shaped specimens pass a
    # denominator inside or outside the range explicitly.
    return [_helper_money_row(index, has_fec_money=index < fec_rows) for index in range(denominator)]


def _write_helper_http_fixture(
    fixture_dir: Path,
    *,
    helper_export_payload: object | None,
    helper_statuses: dict[str, int] | None,
    helper_donor_body: str | None = None,
) -> None:
    targets = _release_targets()
    donor_query = targets["finance_visual_donor_query"]
    route_bodies = {
        "/api/public/v1/federal/export.json": json.dumps(
            _helper_export_rows() if helper_export_payload is None else helper_export_payload
        ),
        "/candidates": '<li data-testid="candidate-result-row">Candidate</li>',
        "/committees": '<li data-testid="committee-result-row">Committee</li>',
        f"/donors?q={donor_query}&by=name": (
            helper_donor_body
            if helper_donor_body is not None
            else '<tr data-testid="donor-result-row"><td>Williams</td></tr>'
        ),
    }
    body_dir = fixture_dir / "helper_http_bodies"
    body_dir.mkdir()
    for route, body in route_bodies.items():
        (body_dir / f"{_fixture_body_slug(route)}.txt").write_text(body, encoding="utf-8")
    (fixture_dir / "helper_http_statuses.tsv").write_text(
        "".join(f"{route}\t{status}\n" for route, status in (helper_statuses or {}).items()),
        encoding="utf-8",
    )


def _write_fixture(
    fixture_dir: Path,
    *,
    repo_paths: set[str],
    deployed_paths: set[str],
    sitemap_latency_seconds: str = "30.000",
    page_statuses: dict[str, int | str] | None = None,
    page_bodies: dict[str, str] | None = None,
    openapi_status: int = 200,
    api_version_payload: dict[str, str] | None = None,
    web_version_payload: dict[str, str] | None = None,
    api_version_status: int = 200,
    web_version_status: int = 200,
    helper_export_payload: object | None = None,
    helper_statuses: dict[str, int] | None = None,
    helper_donor_body: str | None = None,
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
    statuses = page_statuses or {path: 200 for path in DEFAULT_PAGE_BODIES}
    (fixture_dir / "page_statuses.tsv").write_text(
        "".join(f"{path}\t{status}\n" for path, status in statuses.items()),
        encoding="utf-8",
    )
    (fixture_dir / "page_latencies.tsv").write_text(
        f"/sitemap.xml\t{sitemap_latency_seconds}\n",
        encoding="utf-8",
    )
    bodies = DEFAULT_PAGE_BODIES | (page_bodies or {})
    body_dir = fixture_dir / "page_bodies"
    body_dir.mkdir()
    for path in statuses:
        body = bodies.get(path, f"<html><body>{path}</body></html>")
        (body_dir / f"{_fixture_body_slug(path)}.html").write_text(body, encoding="utf-8")
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
    _write_helper_http_fixture(
        fixture_dir,
        helper_export_payload=helper_export_payload,
        helper_statuses=helper_statuses,
        helper_donor_body=helper_donor_body,
    )


def _run_probe(
    fixture_dir: Path,
    *,
    expected_sha: str = EXPECTED_SHA,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("CIVIBUS_PUBLIC_BASE_URL", None)
    env["CIVIBUS_DEPLOYED_SURFACE_FIXTURE_DIR"] = str(fixture_dir)
    env["CIVIBUS_EXPECTED_SHA"] = expected_sha
    env.update(extra_env or {})
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
        # 537/539 is a range-shaped in-[535, 543] PASS specimen; Stage 1 pins the
        # post-repair PASS line so Stage 2 makes it green.
        helper_export_payload=_helper_export_rows(denominator=539, fec_rows=537),
    )

    result = _run_probe(fixture_dir)

    assert result.returncode == 0, result.stderr
    assert f"base_url {DEFAULT_PUBLIC_BASE_URL}" in result.stdout
    assert f"deployed_sha_match expected={EXPECTED_SHA} api={EXPECTED_SHA} web={EXPECTED_SHA}" in result.stdout
    assert "openapi_paths_match repo=3 deployed=3" in result.stdout
    for page_path in PUBLIC_PAGE_BODIES:
        assert f"page_status {page_path} 200 marker_ok" in result.stdout
    assert "page_latency /sitemap.xml seconds=30.000 budget_seconds=30.000" in result.stdout
    assert "WARN known_red_page /sitemap.xml" not in result.stdout
    assert "surfaces_probed=14 failed=0" in result.stdout
    assert "money_value_assertion fec_money_coverage PASS numerator=537 denominator=539" in result.stdout
    assert "money_value_probe_ok" in result.stdout
    assert (
        "money_value_assertion candidates_http PASS numerator=200 denominator=200 diagnostic=/candidates returned HTTP 200"
        in result.stdout
    )
    assert (
        "money_value_assertion committees_rows PASS numerator=1 denominator=1 diagnostic=/committees rendered 1 result rows"
        in result.stdout
    )
    assert (
        "money_value_assertion donor_search_rows PASS numerator=1 denominator=1 "
        f"diagnostic=/donors?q={_release_targets()['finance_visual_donor_query']}&by=name rendered 1 result rows"
        in result.stdout
    )
    assert "/api/v1/" not in result.stdout
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
        page_statuses={
            **{path: 200 for path in DEFAULT_PAGE_BODIES},
            "/congress": 404,
        },
    )

    result = _run_probe(fixture_dir)

    assert result.returncode != 0
    assert "missing_page /congress 404" in result.stderr
    assert "page_status /developers 200 marker_ok" in result.stdout


def test_deployed_surface_parity_probe_fails_on_status_200_without_donor_result_content(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "donor-content-missing"
    _write_fixture(
        fixture_dir,
        repo_paths={"/health"},
        deployed_paths={"/health"},
        page_bodies={"/donors?q=smith&by=name": "<html><body>No donors loaded.</body></html>"},
    )

    result = _run_probe(fixture_dir)

    assert result.returncode != 0
    assert 'page_content_marker_missing /donors?q=smith&by=name marker=data-testid="donor-result-row"' in result.stderr
    assert "surfaces_probed=14 failed=1" in result.stdout


def test_deployed_surface_parity_probe_aggregates_failures_and_probes_sitemap(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "aggregates-failures"
    _write_fixture(
        fixture_dir,
        repo_paths={"/health"},
        deployed_paths={"/health"},
        page_statuses={
            **{path: 200 for path in DEFAULT_PAGE_BODIES},
            "/search?q=ossoff": 500,
        },
    )

    result = _run_probe(fixture_dir)

    assert result.returncode != 0
    assert "page_unexpected_http_status /search?q=ossoff 500" in result.stderr
    assert "page_status /donors?q=smith&by=name 200 marker_ok" in result.stdout
    assert "page_status /calendar 200 marker_ok" in result.stdout
    assert "page_status /sitemap.xml 200 marker_ok" in result.stdout
    assert "surfaces_probed=14 failed=1" in result.stdout


def test_deployed_surface_parity_probe_runs_money_assertions_after_structural_failure(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "structural-and-money-failures"
    _write_fixture(
        fixture_dir,
        repo_paths={"/health"},
        deployed_paths={"/health"},
        page_statuses={
            **{path: 200 for path in DEFAULT_PAGE_BODIES},
            "/search?q=ossoff": 500,
        },
        # 534/539: sub-floor numerator inside a range denominator. After Stage 2
        # promotes fec_money_coverage, the probe exits 2, but the flip stays off,
        # so the wrapper still renders it nonfatal — now at exit_status=2.
        helper_export_payload=_helper_export_rows(denominator=539, fec_rows=534),
    )

    result = _run_probe(fixture_dir)

    assert result.returncode != 0
    assert "page_unexpected_http_status /search?q=ossoff 500" in result.stderr
    assert "surface_parity_failed failed=1" in result.stderr
    assert "money_value_assertion fec_money_coverage FAIL numerator=534 denominator=539" in result.stdout
    assert "money_value_failure_nonfatal exit_status=2 fatal=0" in result.stdout
    assert "surface_parity_ok" not in result.stdout


def test_deployed_surface_parity_probe_accepts_sitemap_at_latency_budget(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "sitemap-at-budget"
    _write_fixture(
        fixture_dir,
        repo_paths={"/health"},
        deployed_paths={"/health"},
        sitemap_latency_seconds="30.000",
    )

    result = _run_probe(fixture_dir)

    assert result.returncode == 0, result.stderr
    assert "page_latency /sitemap.xml seconds=30.000 budget_seconds=30.000" in result.stdout
    assert "page_latency_budget_exceeded" not in result.stderr


def test_deployed_surface_parity_probe_fails_sitemap_over_latency_budget(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "sitemap-over-budget"
    _write_fixture(
        fixture_dir,
        repo_paths={"/health"},
        deployed_paths={"/health"},
        sitemap_latency_seconds="30.001",
    )

    result = _run_probe(fixture_dir)

    assert result.returncode != 0
    assert "page_latency /sitemap.xml seconds=30.001 budget_seconds=30.000" in result.stdout
    assert "page_latency_budget_exceeded /sitemap.xml seconds=30.001 budget_seconds=30.000" in result.stderr


def test_deployed_surface_parity_probe_fails_closed_without_sitemap_latency(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "sitemap-latency-missing"
    _write_fixture(
        fixture_dir,
        repo_paths={"/health"},
        deployed_paths={"/health"},
    )
    (fixture_dir / "page_latencies.tsv").unlink()

    result = _run_probe(fixture_dir)

    assert result.returncode != 0
    assert "page_fetch_error /sitemap.xml fixture_latency_table_missing" in result.stderr
    assert "surfaces_probed=14 failed=1" in result.stdout


def test_deployed_surface_parity_probe_renders_money_helper_failures_nonfatally(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "money-helper-nonfatal"
    _write_fixture(
        fixture_dir,
        repo_paths={"/health"},
        deployed_paths={"/health"},
        # 534/539 sub-floor specimen: promoted-fatal probe exit 2 stays nonfatal in
        # the wrapper because the flip is off.
        helper_export_payload=_helper_export_rows(denominator=539, fec_rows=534),
    )

    result = _run_probe(fixture_dir)

    assert result.returncode == 0, result.stderr
    assert "money_value_assertion fec_money_coverage FAIL numerator=534 denominator=539" in result.stdout
    assert "money_value_failure_nonfatal exit_status=2 fatal=0" in result.stdout
    assert "surface_parity_ok" in result.stdout


def test_deployed_surface_parity_probe_keeps_unpromoted_money_failures_nonfatal_when_flip_is_on(
    tmp_path: Path,
) -> None:
    fixture_dir = tmp_path / "money-helper-unpromoted"
    # donor_search_rows is NOT in PROMOTED_FATAL_ASSERTIONS and Stage 2 does not add
    # it, so it stays unpromoted after the flip. The export payload defaults to an
    # in-range full-coverage PASS specimen so fec_money_coverage does not interfere;
    # the failure comes solely from an empty donor search body.
    _write_fixture(
        fixture_dir,
        repo_paths={"/health"},
        deployed_paths={"/health"},
        helper_donor_body="<html><body>No donors loaded.</body></html>",
    )

    result = _run_probe(fixture_dir, extra_env={"CIVIBUS_PUBLIC_MONEY_VALUE_FATAL": "1"})

    donor_query = _release_targets()["finance_visual_donor_query"]
    assert result.returncode == 0, result.stderr
    assert (
        "money_value_assertion donor_search_rows FAIL numerator=0 denominator=1 "
        f"diagnostic=/donors?q={donor_query}&by=name rendered 0 result rows"
    ) in result.stdout
    assert "money_value_assertion fec_money_coverage PASS numerator=540 denominator=540" in result.stdout
    assert "money_value_failure_nonfatal exit_status=1 fatal=0" in result.stdout


def test_deployed_surface_parity_probe_promotes_selected_money_failures_when_flip_is_on(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "money-helper-fatal"
    _write_fixture(
        fixture_dir,
        repo_paths={"/health"},
        deployed_paths={"/health"},
        helper_statuses={"/candidates": 503},
    )

    result = _run_probe(fixture_dir, extra_env={"CIVIBUS_PUBLIC_MONEY_VALUE_FATAL": "1"})

    assert result.returncode != 0
    assert "money_value_assertion candidates_http FAIL numerator=503 denominator=200" in result.stdout
    assert "money_value_failure_fatal exit_status=2 fatal=1" in result.stderr

    helper_candidates_path = fixture_dir / "helper_http_bodies" / f"{_fixture_body_slug('/candidates')}.txt"
    helper_candidates_path.write_bytes(b"\xff")

    crashed_result = _run_probe(fixture_dir, extra_env={"CIVIBUS_PUBLIC_MONEY_VALUE_FATAL": "1"})

    assert crashed_result.returncode != 0
    assert "money_value_probe_error UnicodeDecodeError" in crashed_result.stderr
    assert "money_value_probe_error exit_status=3" in crashed_result.stderr
    assert "surface_parity_ok" not in crashed_result.stdout


@pytest.mark.dev_repo_only(
    private_asset="docs/howto/operations/fly_deployment_runbook.md",
    owner="Fly deployment operations docs",
)
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


def test_shell_money_fixture_does_not_duplicate_shared_release_targets() -> None:
    targets = _release_targets()
    test_source = Path(__file__).read_text(encoding="utf-8")

    assert str(targets["finance_visual_person_id"]) not in test_source
    assert str(targets["finance_visual_person_name"]) not in test_source
    assert f"/donors?q={targets['finance_visual_donor_query']}&by=name" not in test_source
