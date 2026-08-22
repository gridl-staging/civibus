"""Contract tests for the deployed public-surface parity probe."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.ci.deployed_surface_parity_contract_helpers import (
    DEFAULT_PAGE_BODIES,
    DEFAULT_PUBLIC_BASE_URL,
    DRIFTED_SHA,
    EXPECTED_PRODUCTION_MANIFEST_READERS,
    EXPECTED_SHA,
    MANIFEST_HEADER,
    MANIFEST_PATH,
    PERSON_SURFACE_PATH,
    PERSON_SURFACE_SITEMAP_PATH,
    PROBE_PATH,
    PUBLIC_PAGE_BODIES,
    RUNBOOK_PATH,
    assert_direct_call_metadata_detection,
    assert_manifest_row_schema,
    assert_manifest_row_metadata_detection,
    assert_manifest_surface_topology,
    assert_qualified_assignment_metadata_detection,
    assert_interpolated_metadata_detection,
    assert_root_doc_source_filter,
    assert_session_notes_source_filter,
    assert_split_path_metadata_detection,
    expected_money_value_pass_lines,
    fixture_body_slug,
    helper_export_rows,
    manifest_row,
    person_surface_row,
    person_surface_statuses,
    production_manifest_readers,
    read_public_surface_manifest,
    release_targets,
    run_probe,
    scan_runtime_reader_source,
    unregistered_public_surface_metadata,
    write_fixture,
    write_static_manifest_probe,
    write_temp_manifest_probe,
)


def test_committed_public_surface_manifest_contract() -> None:
    assert MANIFEST_PATH.is_file(), f"missing committed public-surface manifest: {MANIFEST_PATH}"
    parsed_rows = read_public_surface_manifest()
    assert_manifest_row_schema(parsed_rows)
    assert_manifest_surface_topology(parsed_rows)


@pytest.mark.parametrize(
    ("header", "rows", "expected_error"),
    (
        pytest.param(
            MANIFEST_HEADER[:-1],
            (manifest_row()[:-1],),
            "header missing_column=owners",
            id="missing-header-column",
        ),
        pytest.param(
            MANIFEST_HEADER,
            (manifest_row() + ("unexpected",),),
            "row=2 field_count=8 expected=7",
            id="extra-field-count",
        ),
        pytest.param(
            MANIFEST_HEADER,
            (
                manifest_row(surface_id="duplicate_surface"),
                manifest_row(surface_id="duplicate_surface", path="/duplicate"),
            ),
            "row=3 duplicate_surface_id=duplicate_surface",
            id="duplicate-surface-id",
        ),
        pytest.param(
            MANIFEST_HEADER,
            (manifest_row(kind="dynamic"),),
            "row=2 unknown_kind=dynamic",
            id="unknown-kind",
        ),
        pytest.param(
            MANIFEST_HEADER,
            (manifest_row(parity_mode="advisory"),),
            "row=2 unknown_parity_mode=advisory",
            id="unknown-parity-mode",
        ),
        pytest.param(
            MANIFEST_HEADER,
            (manifest_row(uptime_mode="known_red"),),
            "row=2 unknown_uptime_mode=known_red",
            id="unknown-uptime-mode",
        ),
        pytest.param(
            MANIFEST_HEADER,
            (manifest_row(marker=" "),),
            "row=2 blank_field=marker",
            id="whitespace-only-marker",
        ),
        pytest.param(
            MANIFEST_HEADER,
            (manifest_row(path="@attacker.example/person/specimen"),),
            "row=2 unsafe_path=@attacker.example/person/specimen",
            id="authority-switching-path",
        ),
        pytest.param(
            MANIFEST_HEADER,
            (manifest_row(path="/public/%252e%252e/api/private"),),
            "row=2 unsafe_path=/public/%252e%252e/api/private",
            id="encoded-traversal-path",
        ),
    ),
)
def test_probe_fails_closed_on_malformed_script_relative_manifest(
    tmp_path: Path,
    header: tuple[str, ...],
    rows: tuple[tuple[str, ...], ...],
    expected_error: str,
) -> None:
    copied_probe_path = write_temp_manifest_probe(tmp_path / "probe-repo", rows, header=header)
    fixture_dir = tmp_path / "fixture"
    write_fixture(fixture_dir, repo_paths={"/health"}, deployed_paths={"/health"})

    result = run_probe(fixture_dir, probe_path=copied_probe_path)

    assert result.returncode != 0, result.stdout
    assert f"public_surface_manifest_error {expected_error}" in result.stderr, result.stderr
    assert "marker_ok" not in result.stdout
    assert "surface_parity_ok" not in result.stdout


def test_script_relative_manifest_replaces_legacy_surface_registry(tmp_path: Path) -> None:
    sentinel_path = "/manifest-only-sentinel"
    sentinel_marker = "manifest-only marker"
    copied_probe_path = write_static_manifest_probe(
        tmp_path / "probe-repo",
        path=sentinel_path,
        marker=sentinel_marker,
    )
    fixture_dir = tmp_path / "fixture"
    write_fixture(
        fixture_dir,
        repo_paths={"/health"},
        deployed_paths={"/health"},
        page_statuses={sentinel_path: 200},
        page_bodies={sentinel_path: f"<html><body>{sentinel_marker}</body></html>"},
    )

    result = run_probe(fixture_dir, probe_path=copied_probe_path)

    assert result.returncode == 0, result.stderr
    assert f"page_status {sentinel_path} 200 marker_ok" in result.stdout
    assert "surfaces_probed=1 failed=0" in result.stdout
    assert "page_status /congress " not in result.stdout
    assert "page_status /donors?q=smith&by=name " not in result.stdout
    assert "surface_parity_ok" in result.stdout


def test_manifest_static_marker_is_matched_as_literal_not_grep_option(tmp_path: Path) -> None:
    sentinel_path = "/option-shaped-marker"
    sentinel_marker = "--version"
    copied_probe_path = write_static_manifest_probe(
        tmp_path / "probe-repo",
        path=sentinel_path,
        marker=sentinel_marker,
    )
    fixture_dir = tmp_path / "fixture"
    write_fixture(
        fixture_dir,
        repo_paths={"/health"},
        deployed_paths={"/health"},
        page_statuses={sentinel_path: 200},
        page_bodies={sentinel_path: "<html><body>literal marker absent</body></html>"},
    )

    result = run_probe(fixture_dir, probe_path=copied_probe_path)

    assert result.returncode != 0
    assert f"page_content_marker_missing {sentinel_path} marker={sentinel_marker}" in result.stderr
    assert "marker_ok" not in result.stdout
    assert "surface_parity_ok" not in result.stdout


def test_manifest_fatal_static_failure_counts_toward_summary(tmp_path: Path) -> None:
    failed_path = "/manifest-fatal-failure"
    copied_probe_path = write_static_manifest_probe(
        tmp_path / "probe-repo",
        path=failed_path,
    )
    fixture_dir = tmp_path / "fixture"
    write_fixture(
        fixture_dir,
        repo_paths={"/health"},
        deployed_paths={"/health"},
        page_statuses={failed_path: 503},
    )

    result = run_probe(fixture_dir, probe_path=copied_probe_path)

    assert result.returncode != 0
    assert f"page_unexpected_http_status {failed_path} 503" in result.stderr
    assert "surfaces_probed=1 failed=1" in result.stdout
    assert "surface_parity_failed failed=1" in result.stderr


def test_manifest_known_red_static_failure_stays_visible_and_nonfatal(tmp_path: Path) -> None:
    known_red_path = "/manifest-known-red"
    copied_probe_path = write_static_manifest_probe(
        tmp_path / "probe-repo",
        path=known_red_path,
        parity_mode="known_red",
    )
    fixture_dir = tmp_path / "fixture"
    write_fixture(
        fixture_dir,
        repo_paths={"/health"},
        deployed_paths={"/health"},
        page_statuses={known_red_path: 503},
    )

    result = run_probe(fixture_dir, probe_path=copied_probe_path)

    assert result.returncode == 0, result.stderr
    assert f"WARN known_red_page {known_red_path} 503" in result.stdout
    assert "surfaces_probed=0 failed=0" in result.stdout
    assert "surface_parity_failed" not in result.stderr
    assert "surface_parity_ok" in result.stdout


def test_manifest_skip_row_is_not_probed(tmp_path: Path) -> None:
    skipped_path = "/manifest-skipped"
    copied_probe_path = write_static_manifest_probe(
        tmp_path / "probe-repo",
        path=skipped_path,
        parity_mode="skip",
    )
    fixture_dir = tmp_path / "fixture"
    write_fixture(
        fixture_dir,
        repo_paths={"/health"},
        deployed_paths={"/health"},
        page_statuses={"/fixture-only": 200},
    )

    result = run_probe(fixture_dir, probe_path=copied_probe_path)

    assert result.returncode == 0, result.stderr
    assert skipped_path not in result.stdout
    assert skipped_path not in result.stderr
    assert "surfaces_probed=0 failed=0" in result.stdout
    assert "surface_parity_ok" in result.stdout


@pytest.mark.parametrize(
    ("parity_mode", "expected_returncode", "expected_summary"),
    (
        pytest.param("fatal", 1, "surfaces_probed=1 failed=1", id="fatal"),
        pytest.param("known_red", 0, "surfaces_probed=0 failed=0", id="known-red"),
    ),
)
def test_person_sitemap_without_specimen_obeys_manifest_parity_mode(
    tmp_path: Path,
    parity_mode: str,
    expected_returncode: int,
    expected_summary: str,
) -> None:
    copied_probe_path = write_temp_manifest_probe(
        tmp_path / "probe-repo",
        (
            manifest_row(
                surface_id="person_detail_surface",
                kind="person_sitemap",
                path=PERSON_SURFACE_SITEMAP_PATH,
                marker='aria-label="Breadcrumb"',
                parity_mode=parity_mode,
                uptime_mode="fatal",
            ),
        ),
    )
    fixture_dir = tmp_path / "fixture"
    write_fixture(
        fixture_dir,
        repo_paths={"/health"},
        deployed_paths={"/health"},
        page_statuses={path: 200 for path in DEFAULT_PAGE_BODIES},
        page_bodies={
            PERSON_SURFACE_SITEMAP_PATH: '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"></urlset>'
        },
    )

    result = run_probe(fixture_dir, probe_path=copied_probe_path)

    assert result.returncode == expected_returncode, result.stderr
    assert f"person_surface {PERSON_SURFACE_SITEMAP_PATH} failed reason=no_person_specimen" in result.stdout
    assert expected_summary in result.stdout
    if parity_mode == "known_red":
        assert "surface_parity_ok" in result.stdout
    else:
        assert "surface_parity_failed failed=1" in result.stderr


def test_person_sitemap_manifest_fetches_healthy_discovered_person_specimen(tmp_path: Path) -> None:
    copied_probe_path = write_temp_manifest_probe(
        tmp_path / "probe-repo",
        (person_surface_row("fatal"),),
    )
    fixture_dir = tmp_path / "fixture"
    write_fixture(
        fixture_dir,
        repo_paths={"/health"},
        deployed_paths={"/health"},
        page_statuses=person_surface_statuses(),
    )

    result = run_probe(fixture_dir, probe_path=copied_probe_path)

    assert result.returncode == 0, result.stderr
    assert f"person_surface {PERSON_SURFACE_PATH} ok" in result.stdout
    assert "surfaces_probed=1 failed=0" in result.stdout
    assert "surface_parity_ok" in result.stdout


@pytest.mark.parametrize(
    ("page_status", "page_body", "expected_reason"),
    (
        pytest.param(503, None, "unexpected_http_status_503", id="bad-status"),
        pytest.param(
            200,
            "<html><main>Person detail without breadcrumb.</main></html>",
            "breadcrumb_missing",
            id="missing-breadcrumb",
        ),
        pytest.param(
            200,
            "<html><main>temporarily unavailable</main></html>",
            "backend_failure_copy",
            id="backend-failure-copy",
        ),
    ),
)
@pytest.mark.parametrize(
    ("parity_mode", "expected_returncode", "expected_summary"),
    (
        pytest.param("fatal", 1, "surfaces_probed=1 failed=1", id="fatal"),
        pytest.param("known_red", 0, "surfaces_probed=0 failed=0", id="known-red"),
    ),
)
def test_person_sitemap_manifest_failures_obey_parity_mode(
    tmp_path: Path,
    page_status: int,
    page_body: str | None,
    expected_reason: str,
    parity_mode: str,
    expected_returncode: int,
    expected_summary: str,
) -> None:
    copied_probe_path = write_temp_manifest_probe(
        tmp_path / "probe-repo",
        (person_surface_row(parity_mode),),
    )
    page_bodies = {} if page_body is None else {PERSON_SURFACE_PATH: page_body}
    fixture_dir = tmp_path / "fixture"
    write_fixture(
        fixture_dir,
        repo_paths={"/health"},
        deployed_paths={"/health"},
        page_statuses=person_surface_statuses(page_status),
        page_bodies=page_bodies,
    )

    result = run_probe(fixture_dir, probe_path=copied_probe_path)

    assert result.returncode == expected_returncode, result.stderr
    assert f"person_surface {PERSON_SURFACE_PATH} failed reason={expected_reason}" in result.stdout
    assert expected_summary in result.stdout
    if parity_mode == "fatal":
        assert "surface_parity_failed failed=1" in result.stderr
    else:
        assert "surface_parity_ok" in result.stdout


def test_probe_sources_public_surface_membership_from_manifest() -> None:
    probe_text = PROBE_PATH.read_text(encoding="utf-8")

    assert re.search(r"(?m)^PUBLIC_PAGES=\(", probe_text) is None
    assert re.search(r"(?m)^KNOWN_RED_PUBLIC_PAGES=\(", probe_text) is None
    assert "public_surface_probes.tsv" in probe_text
    assert "BASH_SOURCE[0]" in probe_text
    for column_name in MANIFEST_HEADER:
        assert column_name in probe_text
    assert '"/congress|data-testid=\\"congress-member-row-0\\""' not in probe_text
    assert '"/sitemap-person-0.xml|aria-label=' not in probe_text


def test_deployed_surface_parity_probe_accepts_matching_fixture_surface(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "matching"
    write_fixture(
        fixture_dir,
        repo_paths={"/health", "/public/v1/federal/officials", "/v1/candidates"},
        deployed_paths={"/health", "/public/v1/federal/officials", "/v1/candidates"},
        helper_export_payload=helper_export_rows(denominator=539, fec_rows=537),
    )

    result = run_probe(fixture_dir)

    assert result.returncode == 0, result.stderr
    assert f"base_url {DEFAULT_PUBLIC_BASE_URL}" in result.stdout
    assert f"deployed_sha_match expected={EXPECTED_SHA} api={EXPECTED_SHA} web={EXPECTED_SHA}" in result.stdout
    assert "openapi_paths_match repo=3 deployed=3" in result.stdout
    for page_path in PUBLIC_PAGE_BODIES:
        assert f"page_status {page_path} 200 marker_ok" in result.stdout
    assert "page_latency /sitemap.xml seconds=30.000 budget_seconds=30.000" in result.stdout
    assert "WARN known_red_page /sitemap.xml" not in result.stdout
    assert "surfaces_probed=18 failed=0" in result.stdout
    assert "money_value_assertion fec_money_coverage PASS numerator=537 denominator=539" in result.stdout
    assert "money_value_probe_ok" in result.stdout
    for expected_line in expected_money_value_pass_lines():
        assert expected_line in result.stdout
    assert "/api/v1/" not in result.stdout
    assert "surface_parity_ok" in result.stdout


def test_deployed_surface_parity_probe_fails_loud_on_sha_drift(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "sha-drift"
    write_fixture(
        fixture_dir,
        repo_paths={"/health", "/public/v1/federal/officials", "/v1/candidates"},
        deployed_paths={"/health", "/public/v1/federal/officials", "/v1/candidates"},
        api_version_payload={"git_sha": DRIFTED_SHA, "built_at": "2026-07-13T21:20:44Z"},
        web_version_payload={"git_sha": DRIFTED_SHA, "built_at": "2026-07-13T21:20:44Z"},
    )

    result = run_probe(fixture_dir)

    assert result.returncode != 0
    assert "deployed_sha_drift" in result.stderr
    assert f"expected_sha {EXPECTED_SHA}" in result.stderr
    assert f"api_deployed_sha {DRIFTED_SHA}" in result.stderr
    assert f"web_deployed_sha {DRIFTED_SHA}" in result.stderr
    assert f"commit_delta {DRIFTED_SHA}..{EXPECTED_SHA}" in result.stderr


def test_deployed_surface_parity_probe_fails_loud_on_unknown_sha(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "sha-unknown"
    write_fixture(
        fixture_dir,
        repo_paths={"/health"},
        deployed_paths={"/health"},
        api_version_status=404,
        web_version_payload={"git_sha": "unknown", "built_at": "2026-07-13T21:20:44Z"},
    )

    result = run_probe(fixture_dir)

    assert result.returncode != 0
    assert "deployed_sha_unknown" in result.stderr


def test_deployed_surface_parity_probe_normalizes_invalid_sha_to_unknown(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "invalid-sha"
    write_fixture(
        fixture_dir,
        repo_paths={"/health"},
        deployed_paths={"/health"},
        api_version_payload={
            "git_sha": "not-a-valid-commit",
            "built_at": "2026-07-13T21:20:44Z",
        },
    )

    result = run_probe(fixture_dir)

    assert result.returncode != 0
    assert "deployed_sha_unknown" in result.stderr
    assert "api=unknown" in result.stderr


def test_deployed_surface_parity_probe_names_paths_missing_from_deployed(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "missing-deployed"
    write_fixture(
        fixture_dir,
        repo_paths={"/health", "/v1/candidates"},
        deployed_paths={"/health"},
    )

    result = run_probe(fixture_dir)

    assert result.returncode != 0
    assert "missing_from_deployed /v1/candidates" in result.stderr


def test_deployed_surface_parity_probe_names_paths_missing_from_repo(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "missing-repo"
    write_fixture(
        fixture_dir,
        repo_paths={"/health"},
        deployed_paths={"/health", "/v1/extra"},
    )

    result = run_probe(fixture_dir)

    assert result.returncode != 0
    assert "missing_from_repo /v1/extra" in result.stderr


def test_deployed_surface_parity_probe_names_openapi_unexpected_http_status(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "openapi-status"
    write_fixture(
        fixture_dir,
        repo_paths={"/health"},
        deployed_paths={"/health"},
        openapi_status=503,
    )

    result = run_probe(fixture_dir)

    assert result.returncode != 0
    assert "openapi_unexpected_http_status" in result.stderr
    assert "503" in result.stderr


def test_deployed_surface_parity_probe_names_missing_public_pages(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "missing-page"
    write_fixture(
        fixture_dir,
        repo_paths={"/health"},
        deployed_paths={"/health"},
        page_statuses={
            **{path: 200 for path in DEFAULT_PAGE_BODIES},
            "/congress": 404,
        },
    )

    result = run_probe(fixture_dir)

    assert result.returncode != 0
    assert "missing_page /congress 404" in result.stderr
    assert "page_status /developers 200 marker_ok" in result.stdout


def test_deployed_surface_parity_probe_fails_on_status_200_without_donor_result_content(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "donor-content-missing"
    write_fixture(
        fixture_dir,
        repo_paths={"/health"},
        deployed_paths={"/health"},
        page_bodies={"/donors?q=smith&by=name": "<html><body>No donors loaded.</body></html>"},
    )

    result = run_probe(fixture_dir)

    assert result.returncode != 0
    assert 'page_content_marker_missing /donors?q=smith&by=name marker=data-testid="donor-result-row"' in result.stderr
    assert "surfaces_probed=18 failed=1" in result.stdout


def test_deployed_surface_parity_probe_fails_on_methodology_shell_without_disclosures(tmp_path: Path) -> None:
    """Red on the live-demonstrated drift specimen (civibus-dsf).

    Production served 14-day-old methodology copy from 2026-08-03 to
    2026-08-17: the page body still said "Methodology" (shell heading) while
    rendering zero data-testid="methodology-*" disclosure regions, and the
    parity gate stayed green on every run. The manifest marker must fail that
    exact body. The marker is data-testid="methodology-freshness" because the
    screen spec renders it last of the four pinned disclosure regions, so
    matching it implies the preceding three rendered.
    """
    fixture_dir = tmp_path / "methodology-shell-drift"
    write_fixture(
        fixture_dir,
        repo_paths={"/health"},
        deployed_paths={"/health"},
        page_bodies={"/methodology": "<html><body><h1>Methodology</h1></body></html>"},
    )

    result = run_probe(fixture_dir)

    assert result.returncode != 0
    assert 'page_content_marker_missing /methodology marker=data-testid="methodology-freshness"' in result.stderr
    assert "surfaces_probed=18 failed=1" in result.stdout


@pytest.mark.parametrize(
    ("page_path", "shell_heading", "result_marker"),
    (
        pytest.param(
            "/candidates",
            "Candidates",
            'data-testid="candidate-total-raised"',
            id="candidates",
        ),
        pytest.param(
            "/committees",
            "Committees",
            'data-testid="committee-result-row"',
            id="committees",
        ),
    ),
)
def test_deployed_surface_parity_probe_fails_on_list_shell_without_results(
    tmp_path: Path,
    page_path: str,
    shell_heading: str,
    result_marker: str,
) -> None:
    """Reject a shared-shell heading when the page's result body is absent."""
    fixture_dir = tmp_path / f"{shell_heading.lower()}-shell-drift"
    write_fixture(
        fixture_dir,
        repo_paths={"/health"},
        deployed_paths={"/health"},
        page_bodies={page_path: f"<html><body><nav>{shell_heading}</nav></body></html>"},
    )

    result = run_probe(fixture_dir)

    assert result.returncode != 0
    assert f"page_content_marker_missing {page_path} marker={result_marker}" in result.stderr
    assert "surfaces_probed=18 failed=1" in result.stdout


def test_deployed_surface_parity_probe_aggregates_failures_and_probes_sitemap(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "aggregates-failures"
    write_fixture(
        fixture_dir,
        repo_paths={"/health"},
        deployed_paths={"/health"},
        page_statuses={
            **{path: 200 for path in DEFAULT_PAGE_BODIES},
            "/search?q=ossoff": 500,
        },
    )

    result = run_probe(fixture_dir)

    assert result.returncode != 0
    assert "page_unexpected_http_status /search?q=ossoff 500" in result.stderr
    assert "page_status /donors?q=smith&by=name 200 marker_ok" in result.stdout
    assert "page_status /calendar 200 marker_ok" in result.stdout
    assert "page_status /sitemap.xml 200 marker_ok" in result.stdout
    assert "surfaces_probed=18 failed=1" in result.stdout


def test_deployed_surface_parity_probe_runs_money_assertions_after_structural_failure(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "structural-and-money-failures"
    write_fixture(
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
        helper_export_payload=helper_export_rows(denominator=539, fec_rows=534),
    )

    result = run_probe(fixture_dir)

    assert result.returncode != 0
    assert "page_unexpected_http_status /search?q=ossoff 500" in result.stderr
    assert "surface_parity_failed failed=1" in result.stderr
    assert "money_value_assertion fec_money_coverage FAIL numerator=534 denominator=539" in result.stdout
    assert "money_value_failure_nonfatal exit_status=2 fatal=0" in result.stdout
    assert "surface_parity_ok" not in result.stdout


def test_deployed_surface_parity_probe_accepts_sitemap_at_latency_budget(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "sitemap-at-budget"
    write_fixture(
        fixture_dir,
        repo_paths={"/health"},
        deployed_paths={"/health"},
        sitemap_latency_seconds="30.000",
    )

    result = run_probe(fixture_dir)

    assert result.returncode == 0, result.stderr
    assert "page_latency /sitemap.xml seconds=30.000 budget_seconds=30.000" in result.stdout
    assert "page_latency_budget_exceeded" not in result.stderr


def test_deployed_surface_parity_probe_fails_sitemap_over_latency_budget(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "sitemap-over-budget"
    write_fixture(
        fixture_dir,
        repo_paths={"/health"},
        deployed_paths={"/health"},
        sitemap_latency_seconds="30.001",
    )

    result = run_probe(fixture_dir)

    assert result.returncode != 0
    assert "page_latency /sitemap.xml seconds=30.001 budget_seconds=30.000" in result.stdout
    assert "page_latency_budget_exceeded /sitemap.xml seconds=30.001 budget_seconds=30.000" in result.stderr


def test_deployed_surface_parity_probe_fails_closed_without_sitemap_latency(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "sitemap-latency-missing"
    write_fixture(
        fixture_dir,
        repo_paths={"/health"},
        deployed_paths={"/health"},
    )
    (fixture_dir / "page_latencies.tsv").unlink()

    result = run_probe(fixture_dir)

    assert result.returncode != 0
    assert "page_fetch_error /sitemap.xml fixture_latency_table_missing" in result.stderr
    assert "surfaces_probed=18 failed=1" in result.stdout


def test_deployed_surface_parity_probe_renders_money_helper_failures_nonfatally(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "money-helper-nonfatal"
    write_fixture(
        fixture_dir,
        repo_paths={"/health"},
        deployed_paths={"/health"},
        helper_export_payload=helper_export_rows(denominator=539, fec_rows=534),
    )

    result = run_probe(fixture_dir)

    assert result.returncode == 0, result.stderr
    assert "money_value_assertion fec_money_coverage FAIL numerator=534 denominator=539" in result.stdout
    assert "money_value_failure_nonfatal exit_status=2 fatal=0" in result.stdout
    assert "surface_parity_ok" in result.stdout


def test_deployed_surface_parity_probe_keeps_unpromoted_money_failures_nonfatal_when_flip_is_on(
    tmp_path: Path,
) -> None:
    fixture_dir = tmp_path / "money-helper-unpromoted"
    write_fixture(
        fixture_dir,
        repo_paths={"/health"},
        deployed_paths={"/health"},
        helper_donor_body="<html><body>No donors loaded.</body></html>",
    )

    result = run_probe(fixture_dir, extra_env={"CIVIBUS_PUBLIC_MONEY_VALUE_FATAL": "1"})

    donor_query = release_targets()["finance_visual_donor_query"]
    assert result.returncode == 0, result.stderr
    assert (
        "money_value_assertion donor_search_rows FAIL numerator=0 denominator=1 "
        f"diagnostic=/donors?q={donor_query}&by=name rendered 0 result rows"
    ) in result.stdout
    assert "money_value_assertion fec_money_coverage PASS numerator=540 denominator=540" in result.stdout
    assert "money_value_failure_nonfatal exit_status=1 fatal=0" in result.stdout


def test_deployed_surface_parity_probe_promotes_selected_money_failures_when_flip_is_on(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "money-helper-fatal"
    write_fixture(
        fixture_dir,
        repo_paths={"/health"},
        deployed_paths={"/health"},
        helper_statuses={"/candidates": 503},
    )

    result = run_probe(fixture_dir, extra_env={"CIVIBUS_PUBLIC_MONEY_VALUE_FATAL": "1"})

    assert result.returncode != 0
    assert "money_value_assertion candidates_http FAIL numerator=503 denominator=200" in result.stdout
    assert "money_value_failure_fatal exit_status=2 fatal=1" in result.stderr

    helper_candidates_path = fixture_dir / "helper_http_bodies" / f"{fixture_body_slug('/candidates')}.txt"
    helper_candidates_path.write_bytes(b"\xff")

    crashed_result = run_probe(fixture_dir, extra_env={"CIVIBUS_PUBLIC_MONEY_VALUE_FATAL": "1"})

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

    for expected_text in (
        "## Post-deploy Deployed Surface Parity",
        "`bash infra/scripts/probe_deployed_surface_parity.sh`",
        "`CIVIBUS_PUBLIC_BASE_URL`",
        "`CIVIBUS_EXPECTED_SHA`",
        DEFAULT_PUBLIC_BASE_URL,
    ):
        assert expected_text in runbook_text


def test_probe_contract_includes_expected_sha_default_owner() -> None:
    probe_text = PROBE_PATH.read_text(encoding="utf-8")

    for expected_text in (
        "CIVIBUS_EXPECTED_SHA",
        "git fetch origin main",
        "/api/health/version",
        "/version.json",
    ):
        assert expected_text in probe_text


def test_shell_money_fixture_does_not_duplicate_sharedrelease_targets() -> None:
    targets = release_targets()
    test_source = Path(__file__).read_text(encoding="utf-8")

    assert str(targets["finance_visual_person_id"]) not in test_source
    assert str(targets["finance_visual_person_name"]) not in test_source
    assert f"/donors?q={targets['finance_visual_donor_query']}&by=name" not in test_source


def test_public_surface_manifest_has_exactly_two_production_readers() -> None:
    assert production_manifest_readers() == EXPECTED_PRODUCTION_MANIFEST_READERS


def test_public_surface_runtime_consumers_reject_unregistered_metadata() -> None:
    assert unregistered_public_surface_metadata() == []


def test_production_source_discovery_covers_extensionless_owners() -> None:
    """A third reader in an extensionless production file must be reported."""
    readers = production_manifest_readers(((Path("Makefile"), "cat infra/public_surface_probes.tsv"),))
    assert readers == frozenset({"Makefile"})


def test_unregistered_metadata_detects_manifest_absent_surface_urls() -> None:
    """Manifest-absent surface URLs are caught under natural names and inline; registered/health routes are not."""
    bypass = "surface_url=/donors?q=evil&by=name"
    natural = scan_runtime_reader_source(
        ".github/workflows/uptime_probe.yml",
        'DONOR_URL = "https://civibus.shareborough.com/donors?q=evil&by=name"',
    )
    inline = scan_runtime_reader_source(
        "infra/scripts/probe_deployed_surface_parity.sh",
        'probe_url "donor" "https://civibus-caddy.fly.dev/donors?q=evil&by=name"',
    )
    allowed_routes = scan_runtime_reader_source(
        ".github/workflows/uptime_probe.yml",
        'X = "https://civibus.shareborough.com/congress"\nH = "https://civibus.shareborough.com/api/health/content"',
    )
    assert any(bypass in violation for violation in natural)
    assert any(bypass in violation for violation in inline)
    assert allowed_routes == []


def test_unregistered_metadata_detects_interpolated_surface_registrations() -> None:
    assert_interpolated_metadata_detection()


def test_public_surface_metadata_guard_rejects_split_paths_and_row_overrides() -> None:
    assert_split_path_metadata_detection()
    assert_manifest_row_metadata_detection()
    assert_direct_call_metadata_detection()
    assert_qualified_assignment_metadata_detection()


def test_production_source_path_filter_excludes_root_docs_but_keeps_runtime_owners() -> None:
    assert_root_doc_source_filter()


def test_production_source_path_filter_excludes_private_session_notes() -> None:
    assert_session_notes_source_filter()
