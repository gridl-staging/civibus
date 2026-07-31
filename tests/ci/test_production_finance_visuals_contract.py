"""Static contracts for the production finance visual smoke probes."""

import json
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PRODUCTION_DEPLOY_SPEC = REPO_ROOT / "web/tests/smoke/production_deploy.spec.ts"
PRODUCTION_FINANCE_SPEC = REPO_ROOT / "web/tests/smoke/production_finance_visuals.spec.ts"
PRODUCTION_RELEASE_TARGETS = REPO_ROOT / "web/tests/smoke/production_release_targets.json"
SMOKE_HELPERS = REPO_ROOT / "web/tests/smoke/smoke-helpers.ts"


def _production_deploy_spec() -> str:
    return PRODUCTION_DEPLOY_SPEC.read_text(encoding="utf-8")


def _production_finance_spec() -> str:
    return PRODUCTION_FINANCE_SPEC.read_text(encoding="utf-8")


def _smoke_helpers() -> str:
    return SMOKE_HELPERS.read_text(encoding="utf-8")


def _smoke_specs() -> list[Path]:
    return sorted((REPO_ROOT / "web/tests/smoke").glob("*.spec.ts"))


def test_production_deploy_smoke_uses_current_chart_accessibility_labels() -> None:
    source = _production_deploy_spec()

    assert "Finance chart for" not in source
    assert "Donations over time for" not in source
    assert "Donation count by size bucket for" not in source
    assert "Dollars by size bucket for" not in source
    assert "Fundraising geography for" not in source
    assert "Receipt source composition by dollars" in source
    assert "Monthly contribution columns" in source
    assert "Itemized contribution-size buckets bar chart" in source
    assert "Geography dollar share by contributor location" in source


def test_production_committee_discovery_waits_for_owned_result_row() -> None:
    source = _production_deploy_spec()
    helper = source.split("async function firstCommitteeDetailLink", maxsplit=1)[1].split("\n}", maxsplit=1)[0]

    assert 'page.getByTestId("committee-result-row")' in helper
    assert "await expect(committeeRows.first()).toBeVisible" in helper
    assert 'committeeRows.getByRole("link").all()' in helper
    assert 'page.getByRole("heading", { level: 3 }).getByRole("link").all()' not in helper


def test_production_committee_discovery_rejects_a_malformed_first_visible_link() -> None:
    source = _production_deploy_spec()
    helper = source.split("async function firstCommitteeDetailLink", maxsplit=1)[1].split("\n}", maxsplit=1)[0]

    first_link_lookup = 'committeeRows.first().getByRole("link").first()'
    first_link_assertion = (
        'await expect(firstVisibleCommitteeLink).toHaveAttribute("href", COMMITTEE_ROUTE_HREF_PATTERN)'
    )
    fallback_lookup = 'committeeRows.getByRole("link").all()'

    assert first_link_lookup in helper
    assert first_link_assertion in helper
    assert helper.index(first_link_assertion) < helper.index(fallback_lookup)


def test_production_finance_release_person_has_one_shared_owner() -> None:
    source = _production_finance_spec()
    release_targets = json.loads(PRODUCTION_RELEASE_TARGETS.read_text(encoding="utf-8"))
    release_person_id = release_targets["finance_visual_person_id"]
    release_person_path = release_targets["finance_visual_person_path"]
    smoke_spec_sources = "\n".join(path.read_text(encoding="utf-8") for path in _smoke_specs())

    assert re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
        release_person_id,
    )
    assert release_targets["finance_visual_person_name"].strip()
    assert release_person_path == f"/person/{release_person_id}"
    assert release_targets["finance_visual_minimum_total_raised"] == "1.00"
    assert release_targets["finance_visual_donor_query"] == "williams"
    assert 'import releaseTargets from "./production_release_targets.json"' in source
    assert "releaseTargets.finance_visual_person_id" in source
    assert "releaseTargets.finance_visual_person_name" in source
    assert "releaseTargets.finance_visual_person_path" in source
    assert release_person_id not in smoke_spec_sources
    assert release_person_path not in smoke_spec_sources


def test_production_finance_smoke_requires_release_target_money_values() -> None:
    source = _production_finance_spec()
    person_money_function = source.split("async function expectPersonReleaseTargetRendersMoney", maxsplit=1)[1].split(
        "\n}\n", maxsplit=1
    )[0]

    assert "expectCongressReleaseTargetRendersMoney" in source
    assert "expectPersonReleaseTargetRendersMoney" in source
    assert "page.goto(`/congress?search=${encodeURIComponent(RELEASE_PERSON_NAME)}`)" in source
    assert 'page.getByRole("region", { name: `Money summary for ${RELEASE_PERSON_NAME}` })' in source
    assert "page.goto(`${RELEASE_PERSON_PATH}?cycle=${SELECTED_CYCLE}`)" in source
    assert 'page.getByRole("region", { name: MONEY_AT_GLANCE_REGION })' in source
    assert "expectNonzeroMoneyValue" in source
    assert "TRUTHFUL_NO_DATA" not in person_money_function


def test_production_finance_smoke_exercises_each_chart_disclosure() -> None:
    source = _production_finance_spec()

    assert 'getByText("View chart data", { exact: true }).first()' not in source
    assert "expectedDisclosureCount" in source
    assert "openedDisclosureCount" in source
    assert "disclosure.nth(index)" in source
    assert "dataTables.nth(index)" in source


def test_production_finance_smoke_requires_outside_spending_marks_when_activity_exists() -> None:
    source = _production_finance_spec()

    assert "outsideSpendingHasReportedActivity" in source
    assert "expect(outsidePaints.length).toBeGreaterThan(0)" in source
    assert "outsidePaints.length === 0" not in source


def test_production_finance_no_chart_fallback_is_scoped_to_chart_frames() -> None:
    source = _production_finance_spec()

    assert "page.getByText(TRUTHFUL_NO_DATA)" not in source
    assert "expectFinanceChartNoDataState" in source
    assert "collectChartFrameRegions" in source
    assert "financeChartNoDataStates.length" in source


def test_production_finance_source_links_are_exercised_inside_chart_frames() -> None:
    source = _production_finance_spec()

    assert "expectChartSourceLinksKeyboardReachable" in source
    assert 'region.getByRole("link", { name: EXACT_FEC_SOURCE })' in source
    assert "await sourceLink.focus()" in source
    assert "await expect(sourceLink).toBeFocused()" in source
    assert 'await expect(sourceLink).toHaveAttribute("href", /^https:\\/\\/www\\.fec\\.gov\\//)' in source
    assert "page.getByText(EXACT_FEC_SOURCE)" not in source


def test_production_finance_reuses_shared_regex_escape_helper() -> None:
    source = _production_finance_spec()
    helpers = _smoke_helpers()
    duplicate_owners = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in _smoke_specs()
        if "function escapeRegExp" in path.read_text(encoding="utf-8")
    ]

    assert "export function escapeRegExp" in helpers
    assert "escapeRegExp" in source
    assert duplicate_owners == []
