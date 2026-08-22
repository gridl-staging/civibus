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
    assert "Receipt source composition by dollars" not in source
    assert '"person-receipt-composition"' in source
    assert "Monthly contribution columns" in source
    # Retired with civibus-3a3: HorizontalBarChart no longer renders an svg
    # chart section, so this aria label no longer exists anywhere in the app and
    # a probe using it can only ever no-op. The module is checked through its
    # frame testId and the HTML bar-list oracle instead.
    assert "Itemized contribution-size buckets bar chart" not in source
    assert '"person-size-buckets"' in source
    assert "expectHtmlBarListRenderIfPlotted" in source
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
    # The congress directory money summary is a labeled <dl>, not a landmark region (one region
    # per directory row would flood landmark navigation), so it is located by accessible name.
    assert 'page.locator(`[aria-label="Money summary for ${RELEASE_PERSON_NAME}"]`)' in source
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
    """The outside-spending gate decides by VALUES across three states.

    The pre-2026-08-21 predicate keyed on "Support total" label VISIBILITY with
    an unwaited isVisible(): the first real loaded_zero view (created by the
    2024 Schedule E load) rendered honest $0.00 labels with no marks and the
    gate demanded marks against it (deploy run 32450666834), while the same
    run's desktop retry passed by racing hydration into a silent skip. These
    pins hold the replacement to its three-state shape: totals parsed as
    dollars, nonzero -> real marks required, measured zero -> the words arm
    plus an explicit zero-mark assertion, and a settled wait so the helper can
    never skip by racing.
    """
    source = _production_finance_spec()

    assert "settledOutsideSpendingTotals" in source
    assert "hasNonzeroActivity" in source
    # The settle step waits on the SSR panel heading, then polls the totals —
    # the un-waited isVisible() race must not come back.
    assert 'getByRole("heading", { name: "Outside spending" })' in source
    assert "await supportLabel.waitFor" in source
    # Nonzero arm still demands a real render and painted marks.
    assert "expect(outsidePaints.length).toBeGreaterThan(0)" in source
    # Measured-zero arm asserts the honest words AND that no bar mark rendered.
    assert "reports \\$0\\.00 in support spending and \\$0\\.00 in oppose spending" in source
    assert "expect(await outsideFrame.locator(BAR_SERIES_MARK_SELECTOR).count()).toBe(0)" in source
    # The label-presence predicate is retired; presence is not activity.
    assert "outsideSpendingHasReportedActivity" not in source


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


FIXTURE_FINANCE_SPEC = REPO_ROOT / "web/tests/smoke/finance-visuals.spec.ts"
FIXTURE_FINANCE_SNAPSHOTS = REPO_ROOT / "web/tests/smoke/finance-visuals.spec.ts-snapshots"
CHART_ADAPTER = REPO_ROOT / "web/src/lib/charts/Chart.svelte"
CHART_FRAME = REPO_ROOT / "web/src/lib/charts/ChartFrame.svelte"


def _fixture_finance_spec() -> str:
    return FIXTURE_FINANCE_SPEC.read_text(encoding="utf-8")


def _screenshot_name_patterns(spec_source: str) -> list[re.Pattern[str]]:
    """Compile every ``toHaveScreenshot`` name in the spec into a filename matcher.

    Screenshot names are template literals (``person-finance-${viewport.name}.png``)
    while the committed files carry a resolved viewport plus the Playwright project
    suffix (``person-finance-desktop-chromium.png``). So each ``${...}`` becomes a
    wildcard and the project suffix is matched as a trailing segment. Everything
    outside the interpolations is escaped, which keeps the ``.`` in ``.png``
    literal rather than letting it match any character.
    """
    patterns: list[re.Pattern[str]] = []
    for template in re.findall(r"toHaveScreenshot\(\s*`([^`]+)`", spec_source):
        stem = template.removesuffix(".png")
        # Split on interpolations so the literal halves can be escaped separately.
        literal_parts = [re.escape(part) for part in re.split(r"\$\{[^}]*\}", stem)]
        patterns.append(re.compile(rf"^{'.+'.join(literal_parts)}-[^-]+\.png$"))
    return patterns


def test_every_committed_screenshot_baseline_is_still_asserted() -> None:
    """No baseline may outlive the assertion that produced it.

    A committed screenshot with no ``toHaveScreenshot`` call behind it is never
    compared against anything, so it silently rots: it keeps describing a page
    that has since changed, and the next person regenerating baselines has no way
    to tell a live baseline from a dead one. That is not hypothetical here — the
    contest frames outlived their assertion when the race page moved from
    per-candidate cards to a scoreboard table, and stale baselines are part of why
    the clipped-axis defect survived review for as long as it did.

    This guard can fail: delete a ``toHaveScreenshot`` call while leaving its
    ``.png`` committed, or commit a baseline for a page nothing screenshots, and
    the orphan is named here.
    """
    patterns = _screenshot_name_patterns(_fixture_finance_spec())
    committed = sorted(path.name for path in FIXTURE_FINANCE_SNAPSHOTS.glob("*.png"))

    # A spec that screenshots nothing must not be silently "satisfied" by an
    # empty pattern list while baselines sit committed beside it.
    assert patterns, "finance-visuals.spec.ts declares no toHaveScreenshot names"

    orphans = [name for name in committed if not any(pattern.match(name) for pattern in patterns)]

    assert orphans == [], f"committed baselines with no assertion behind them: {orphans}"


def test_chart_legibility_guards_measure_geometry_and_not_label_length() -> None:
    """The guard this replaced could not fail on the defect it was aimed at.

    `expectBoundedNumericTickLabels` read tick TEXT and asserted each label was at
    most 12 characters, so the 9-character "1,000,000" hanging 34px into the
    neighbouring column scored a pass. Character count is not a rendering
    measurement. Pinned here so the geometric version cannot regress back into a
    string check, and so the tolerance stays sub-pixel: the same defect overflowed
    28-34px against production money values but only ~1px against fixture values,
    which is what makes a "safe" 2px tolerance ship the production bug.
    """
    helpers = _smoke_helpers()

    assert "expectBoundedNumericTickLabels" not in helpers
    assert "export async function expectTickLabelsInsidePlotBox" in helpers
    assert "getBoundingClientRect()" in helpers
    assert "const TICK_LABEL_ESCAPE_TOLERANCE_PX = 0.5;" in helpers
    # Vacuity guards: a page whose charts all rendered nothing must fail, not pass.
    assert 'expect(plottedCharts, "no chart region rendered a plot to measure").toBeGreaterThan(0)' in helpers
    assert 'expect(checkedCharts, "no chart region rendered a value axis to check").toBeGreaterThan(0)' in helpers


def test_axis_format_guard_derives_the_expected_unit_from_the_chart_frame() -> None:
    """Reading the unit off the frame is what makes this hold either way.

    GeographyShareChart declared dollars, printed dollars in its rows, and plotted a
    unitless fraction. A guard with a hardcoded per-chart format would have had to
    pick a side before the disagreement was resolved; deriving from `data-unit`
    means the chart and its frame simply have to agree.
    """
    helpers = _smoke_helpers()
    frame = CHART_FRAME.read_text(encoding="utf-8")

    assert "export async function expectAxisFormatMatchesDeclaredUnit" in helpers
    assert 'getAttribute("data-unit")' in helpers
    assert "AXIS_TICK_TEXT_BY_DECLARED_UNIT" in helpers
    assert "data-unit={unit}" in frame


def test_chart_adapter_keeps_the_padding_formatter_and_interaction_fixes() -> None:
    """One adapter owns all three fixes, which is why one change repaired every chart.

    `web/src/lib/charts/import-boundary.test.ts` pins Chart.svelte as the sole
    layerchart consumer; this pins what that adapter has to keep doing.
    """
    adapter = CHART_ADAPTER.read_text(encoding="utf-8")

    # Axis gutters, sized against the abbreviated currency formatter.
    assert "const AXIS_PADDING = " in adapter
    assert "padding={AXIS_PADDING}" in adapter
    # The value axis formats from the declared unit rather than per chart.
    assert "AXIS_VALUE_FORMATTERS[unit]" in adapter
    assert "TOOLTIP_VALUE_FORMATTERS[unit]" in adapter
    # Band axes subsample instead of drawing every category as an unreadable smear.
    assert "tickSpacing: X_TICK_SPACING_PX" in adapter
    # Interaction: the one CSS declaration that silently discarded layerchart's
    # shipped tooltips may not come back. Matched with its semicolon so the comment
    # explaining its absence does not trip the check.
    assert "pointer-events: none;" not in adapter


def test_fixture_finance_spec_exercises_interaction_and_diverging_encoding() -> None:
    """Interaction and stance colour are asserted as behaviour, not as CSS.

    Asserting `pointer-events !== none` would assert the harness rather than what a
    reader gets, which is the same invalid-probe mistake as counting characters in a
    tick label. The tooltip assertion hovers and reads the tooltip's content, and
    the stance assertion compares painted fills against the shared colour tokens the
    HTML rows already consume.
    """
    fixture_spec = _fixture_finance_spec()
    helpers = _smoke_helpers()

    assert "expectChartTooltipOnHover" in fixture_spec
    assert "expectDivergingStanceFills" in fixture_spec
    assert "FINANCE_CHART_COLORS.support" in fixture_spec
    assert "FINANCE_CHART_COLORS.oppose" in fixture_spec
    # No probe anywhere may assert the CSS property instead of the behaviour.
    assert 'toHaveCSS("pointer-events"' not in fixture_spec
    assert 'toHaveCSS("pointer-events"' not in helpers
    assert "await bandHitArea.hover()" in helpers
    assert 'region.page().getByRole("tooltip")' in helpers
    # layerchart draws a bar as a rounded <path class="lc-bar">, never a <rect>; a
    # sampler restricted to rects only ever saw transparent tooltip hit areas.
    # The exported constant is pinned exactly (civibus-d0o): "svg rect" made
    # every expectRealChartRender consumer pass against a chart whose bars could
    # not draw, because the tooltip hit rects satisfied it.
    assert '"svg path.lc-bar"' in helpers
    assert 'export const BAR_SERIES_MARK_SELECTOR = "svg path.lc-bar";' in helpers
    assert 'BAR_SERIES_MARK_SELECTOR = "svg rect"' not in helpers
    # Tooltip containment belongs where a tooltip is open. The spec-local version
    # ran on an unhovered page, found zero [role="tooltip"] elements, and asserted
    # zero had escaped.
    assert "expectContainedTooltips" not in fixture_spec
    assert "an open chart tooltip rendered outside the viewport" in helpers


def test_production_finance_smoke_runs_the_chart_legibility_guards() -> None:
    """The deploy gate carries the guards, not just the fixture suite.

    The clipped-axis defect was 28-34px in production and ~1px in the fixture, so a
    guard that only ran locally would have kept passing through the failure it
    exists to catch.
    """
    source = _production_finance_spec()

    assert "expectTickLabelsInsidePlotBox" in source
    assert "expectAxisFormatMatchesDeclaredUnit" in source
    assert "expectBoundedNumericTickLabels" not in source


HORIZONTAL_BAR_CHART = REPO_ROOT / "web/src/lib/charts/HorizontalBarChart.svelte"
RECEIPT_COMPOSITION_CHART = REPO_ROOT / "web/src/lib/charts/ReceiptCompositionChart.svelte"


def test_horizontal_bar_chart_has_one_visual_encoding_and_every_lane_asserts_it() -> None:
    """HorizontalBarChart draws its series exactly once, as an HTML bar list.

    civibus-3a3: the component used to render the same rows THREE ways — a
    layerchart VERTICAL svg bar chart, the ranked HTML bar list, and the
    disclosure table. The svg duplicate is gone; this pins that it stays gone
    and that each smoke lane's probe moved with it rather than silently
    no-opping against a label that no longer exists.

    Fails for a real defect: re-importing Chart.svelte into the component,
    resurrecting the retired svg aria label, or dropping the bar-list oracle
    from any of the four lanes that carry it.
    """
    component = HORIZONTAL_BAR_CHART.read_text(encoding="utf-8")
    helpers = _smoke_helpers()

    # The component renders no layerchart adapter and no svg of its own.
    assert 'from "./Chart.svelte"' not in component
    assert "<svg" not in component
    assert "horizontal-bars__bar" in component

    # The oracle exists, pins the no-svg contract, and reads real painted style.
    assert "export async function expectHtmlBarListRender" in helpers
    assert 'region.locator("svg")).toHaveCount(0)' in helpers
    assert "linear-gradient" in helpers

    # Every lane that used to assert the svg render now asserts the bar list:
    # fixture visuals, fixture+live data access, fixture+live accessibility,
    # the production deploy gate, and the production visuals gate.
    assert "expectHtmlBarListRender" in _fixture_finance_spec()
    assert "expectHtmlBarListRender" in (REPO_ROOT / "web/tests/smoke/chart_data_access.spec.ts").read_text(
        encoding="utf-8"
    )
    assert "expectHtmlBarListRender" in (REPO_ROOT / "web/tests/smoke/a11y-helpers.ts").read_text(encoding="utf-8")
    assert "expectHtmlBarListRenderIfPlotted" in _production_deploy_spec()
    assert "expectHtmlBarListRenderIfPlotted" in _production_finance_spec()


def test_receipt_composition_has_one_visual_encoding_and_every_lane_asserts_it() -> None:
    component = RECEIPT_COMPOSITION_CHART.read_text(encoding="utf-8")
    fixture_visuals = _fixture_finance_spec()
    chart_data_access = (REPO_ROOT / "web/tests/smoke/chart_data_access.spec.ts").read_text(encoding="utf-8")
    entity_and_civic = (REPO_ROOT / "web/tests/smoke/entity-and-civic.spec.ts").read_text(encoding="utf-8")

    assert 'from "./Chart.svelte"' not in component
    assert "buildChartSeries" not in component
    assert "receipt-composition__bar" in component
    assert "Receipt source composition by dollars" not in fixture_visuals
    assert 'page.getByTestId("person-receipt-composition")' in fixture_visuals
    assert (
        "paintLabel: null"
        in chart_data_access.split('owner: "ReceiptCompositionChart"', maxsplit=1)[1].split("},", maxsplit=1)[0]
    )
    assert 'page.getByTestId("person-receipt-composition")' in entity_and_civic
    assert '"person-receipt-composition"' in _production_deploy_spec()
    assert '"person-receipt-composition"' in _production_finance_spec()


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
