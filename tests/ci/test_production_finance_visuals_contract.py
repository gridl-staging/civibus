"""Static contracts for the production finance visual smoke probes."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PRODUCTION_DEPLOY_SPEC = REPO_ROOT / "web/tests/smoke/production_deploy.spec.ts"
PRODUCTION_FINANCE_SPEC = REPO_ROOT / "web/tests/smoke/production_finance_visuals.spec.ts"
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
