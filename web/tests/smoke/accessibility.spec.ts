import AxeBuilder from "@axe-core/playwright";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { expect, test } from "playwright/test";
import type { Page } from "playwright";

import {
  ACCESSIBILITY_SCAN_DESTINATIONS,
  type AccessibilityScanDestination,
  stubExternalImages
} from "./a11y-helpers";
import { capturePageLoadErrors } from "./smoke-helpers";

const ACCESSIBILITY_RECEIPT_PATH = resolve(
  process.cwd(),
  "../docs/live-state/2026_07_29_accessibility_baseline.md"
);
const ACCESSIBILITY_BASELINE_PATH = resolve(process.cwd(), "tests/smoke/a11y-baseline.json");
const STAGE_2_SECTION_START = "<!-- stage2-accessibility-baseline:start -->";
const STAGE_2_SECTION_END = "<!-- stage2-accessibility-baseline:end -->";
const IMPACT_ORDER = ["critical", "serious", "moderate", "minor"] as const;

type AxeScanResults = Awaited<ReturnType<AxeBuilder["analyze"]>>;
type AxeViolation = AxeScanResults["violations"][number];
type AxeNode = AxeViolation["nodes"][number];
type AxeImpact = Exclude<AxeNode["impact"], undefined>;

type AccessibilityRouteResult = {
  name: string;
  path: string;
  violations: AxeViolation[];
};

type BaselineEntry = {
  key: string;
  routeName: string;
  routePath: string;
  ruleId: string;
  impact: AxeImpact;
  elementIdentifier: string;
  target: AxeNode["target"];
  html: string;
  failureSummary: string | null;
  checks: Array<{ id: string; impact: string; message: string }>;
  help: string;
  helpUrl: string;
};

type AccessibilityBaselineFile = {
  violations: BaselineEntry[];
};

function normalizeHtml(html: string): string {
  return html.replace(/\s+/g, " ").trim();
}

function stableElementIdentifier(node: AxeNode): string {
  if (node.target.length > 0) {
    return `target:${JSON.stringify(node.target)}`;
  }

  // Axe normally supplies a target. Normalized HTML is the stable fallback when it does not.
  return `html:${normalizeHtml(node.html)}`;
}

function normalizedChecks(node: AxeNode): BaselineEntry["checks"] {
  return [...node.any, ...node.all, ...node.none]
    .map(({ id, impact, message }) => ({ id, impact, message }))
    .sort((left, right) => compareText(`${left.id}:${left.message}`, `${right.id}:${right.message}`));
}

function compareText(left: string, right: string): number {
  return left < right ? -1 : left > right ? 1 : 0;
}

function normalizeBaselineEntries(routeResults: AccessibilityRouteResult[]): BaselineEntry[] {
  const entries = routeResults.flatMap((routeResult) =>
    routeResult.violations.flatMap((violation) =>
      violation.nodes.map((node) => {
        const elementIdentifier = stableElementIdentifier(node);
        return {
          key: `${routeResult.path}::${violation.id}::${elementIdentifier}`,
          routeName: routeResult.name,
          routePath: routeResult.path,
          ruleId: violation.id,
          impact: node.impact ?? violation.impact ?? null,
          elementIdentifier,
          target: node.target,
          html: normalizeHtml(node.html),
          failureSummary: node.failureSummary ?? null,
          checks: normalizedChecks(node),
          help: violation.help,
          helpUrl: violation.helpUrl
        };
      })
    )
  );
  entries.sort((left, right) => compareText(left.key, right.key));

  const keys = new Set(entries.map((entry) => entry.key));
  if (keys.size !== entries.length) {
    throw new Error("Accessibility baseline contains duplicate route, rule, and element keys");
  }
  return entries;
}

function readAccessibilityBaseline(): BaselineEntry[] {
  const baseline = JSON.parse(readFileSync(ACCESSIBILITY_BASELINE_PATH, "utf8")) as AccessibilityBaselineFile;
  if (!Array.isArray(baseline.violations)) {
    throw new Error("Accessibility baseline must contain a violations array");
  }
  return baseline.violations;
}

function assertNoNewAccessibilityViolations(
  observedEntries: BaselineEntry[],
  baselineEntries: BaselineEntry[]
): void {
  const baselineKeys = new Set(baselineEntries.map((entry) => entry.key));
  const newEntries = observedEntries.filter((entry) => !baselineKeys.has(entry.key));
  if (newEntries.length === 0) {
    return;
  }

  const newEntryLines = newEntries.map((entry) => `- ${entry.key}`).join("\n");
  throw new Error(`New accessibility violations found:\n${newEntryLines}`);
}

function assertNoSeriousAccessibilityViolations(observedEntries: BaselineEntry[]): void {
  // Forbidden unless demonstrably no worse than moderate. `serious` and `critical` (strictly
  // worse than serious) both fail, and a null/indeterminate impact — which normalizeBaselineEntries
  // can produce when axe supplies neither a node nor a rule impact — also fails, because defaulting
  // an unknown severity to healthy would be a guard that cannot fail.
  const forbiddenEntries = observedEntries.filter(
    (entry) => entry.impact !== "moderate" && entry.impact !== "minor"
  );
  if (forbiddenEntries.length === 0) {
    return;
  }

  const forbiddenLines = forbiddenEntries.map((entry) => `- ${entry.impact} ${entry.key}`).join("\n");
  throw new Error(
    `Serious or worse accessibility violations found (${forbiddenEntries.length}):\n${forbiddenLines}`
  );
}

function baselineEntryForKey(key: string): BaselineEntry {
  return {
    key,
    routeName: "Developers",
    routePath: "/developers",
    ruleId: "region",
    impact: "moderate",
    elementIdentifier: key.split("::").at(-1) ?? key,
    target: ["main"],
    html: "<main>Example</main>",
    failureSummary: "Fix the landmark",
    checks: [{ id: "region", impact: "moderate", message: "Some page content is not contained by landmarks" }],
    help: "All page content should be contained by landmarks",
    helpUrl: "https://dequeuniversity.com/rules/axe/4.12/region"
  };
}

function axeNode(target: AxeNode["target"], html: string, impact: AxeNode["impact"] = "serious"): AxeNode {
  return {
    impact,
    target,
    html,
    failureSummary: "Fix the scrollable region",
    any: [],
    all: [],
    none: []
  };
}

function scrollableRegionViolation(nodes: AxeNode[]): AxeViolation {
  return {
    id: "scrollable-region-focusable",
    impact: "serious",
    description: "Ensure elements that have scrollable content are accessible by keyboard",
    help: "Scrollable region must have keyboard access",
    helpUrl: "https://dequeuniversity.com/rules/axe/4.12/scrollable-region-focusable",
    tags: ["cat.keyboard"],
    nodes
  };
}

function writeAccessibilityBaseline(routeResults: AccessibilityRouteResult[]): void {
  mkdirSync(dirname(ACCESSIBILITY_BASELINE_PATH), { recursive: true });
  writeFileSync(
    ACCESSIBILITY_BASELINE_PATH,
    `${JSON.stringify({ violations: normalizeBaselineEntries(routeResults) }, null, 2)}\n`
  );
}

function shouldUpdateAccessibilityArtifacts(): boolean {
  return process.env.UPDATE_ACCESSIBILITY_BASELINE === "1";
}

function assertAccessibilityReceiptMatches(routeResults: AccessibilityRouteResult[]): void {
  const receipt = readFileSync(ACCESSIBILITY_RECEIPT_PATH, "utf8");
  const receiptWithFreshStage2Section = replaceStage2Section(receipt, stage2ReceiptSection(routeResults));
  if (receiptWithFreshStage2Section !== receipt) {
    throw new Error(
      "Accessibility receipt Stage 2 counts do not match the current fixture scan; rerun with UPDATE_ACCESSIBILITY_BASELINE=1"
    );
  }
}

function updateAccessibilityArtifactsOrAssertBaseline(routeResults: AccessibilityRouteResult[]): void {
  if (shouldUpdateAccessibilityArtifacts()) {
    writeAccessibilityBaseline(routeResults);
    appendAccessibilityReceipt(routeResults);
    return;
  }
  assertNoNewAccessibilityViolations(normalizeBaselineEntries(routeResults), readAccessibilityBaseline());
  assertAccessibilityReceiptMatches(routeResults);
}

async function expectNextTabStop(page: Page, testId: string): Promise<void> {
  await page.keyboard.press("Tab");
  await expect(page.getByTestId(testId)).toBeFocused();
}

async function scanDestination(
  page: Page,
  destination: AccessibilityScanDestination
): Promise<AccessibilityRouteResult> {
  const pageLoadErrors = capturePageLoadErrors(page);

  await page.goto(destination.path);
  await destination.assertContent(page);

  const results = await new AxeBuilder({ page }).analyze();

  await pageLoadErrors.assertNoErrors();

  return {
    name: destination.name,
    path: destination.path,
    violations: results.violations
  };
}

function incrementCount(counts: Map<string, number>, key: string): void {
  counts.set(key, (counts.get(key) ?? 0) + 1);
}

function userImpactSentence(routeResult: AccessibilityRouteResult, violation: AxeViolation): string {
  const affectedSurface = `${routeResult.name} (${routeResult.path})`;
  if (violation.id === "aria-progressbar-name") {
    return `USER_IMPACT: ${affectedSurface} — screen-reader users cannot identify the progress indicator's purpose.`;
  }
  if (violation.id === "scrollable-region-focusable") {
    return `USER_IMPACT: ${affectedSurface} — keyboard-only users cannot reach and scroll all of the region's content.`;
  }
  return `USER_IMPACT: ${affectedSurface} — assistive-technology users may be unable to perceive or operate content affected by ${violation.id}.`;
}

function replaceStage2Section(receipt: string, stage2Section: string): string {
  const startIndex = receipt.indexOf(STAGE_2_SECTION_START);
  const endIndex = receipt.indexOf(STAGE_2_SECTION_END);
  if (startIndex === -1 && endIndex === -1) {
    return `${receipt.trimEnd()}\n\n${stage2Section}\n`;
  }
  if (startIndex === -1 || endIndex === -1 || endIndex < startIndex) {
    throw new Error("Accessibility receipt has an incomplete Stage 2 section");
  }
  const afterSection = endIndex + STAGE_2_SECTION_END.length;
  return `${receipt.slice(0, startIndex)}${stage2Section}${receipt.slice(afterSection)}`;
}

function stage2ReceiptSection(routeResults: AccessibilityRouteResult[]): string {
  const ruleCounts = new Map<string, number>();
  const impactCounts = new Map<string, number>();
  const baselineEntryImpactCounts = new Map<string, number>();
  const userImpacts: string[] = [];
  for (const routeResult of routeResults) {
    for (const violation of routeResult.violations) {
      incrementCount(ruleCounts, violation.id);
      incrementCount(impactCounts, violation.impact ?? "unknown");
      if (violation.impact === "critical" || violation.impact === "serious") {
        userImpacts.push(userImpactSentence(routeResult, violation));
      }
    }
  }
  const baselineEntries = normalizeBaselineEntries(routeResults);
  for (const entry of baselineEntries) {
    incrementCount(baselineEntryImpactCounts, entry.impact ?? "unknown");
  }

  const totalViolations = routeResults.reduce((total, result) => total + result.violations.length, 0);
  const sortedRuleCounts = [...ruleCounts].sort(([left], [right]) => compareText(left, right));
  const unknownImpactLine = impactCounts.has("unknown")
    ? [`- unknown: ${impactCounts.get("unknown")}`]
    : [];
  const unknownBaselineEntryImpactLine = baselineEntryImpactCounts.has("unknown")
    ? [`- unknown: ${baselineEntryImpactCounts.get("unknown")}`]
    : [];
  const triageLines =
    sortedRuleCounts.length === 0
      ? ["TRIAGE: none = accepted_limitation", "TRIAGE_REASON: The fresh fixture corpus has no axe violations to classify."]
      : sortedRuleCounts.map(([ruleId]) => `TRIAGE: ${ruleId} = real_defect`);

  return [
    STAGE_2_SECTION_START,
    "## Stage 2 committed baseline and triage",
    "",
    `TOTAL_VIOLATIONS: ${totalViolations}`,
    `TOTAL_BASELINE_ENTRIES: ${baselineEntries.length}`,
    "COUNTING_NOTE: TOTAL_VIOLATIONS counts axe rule results by route; TOTAL_BASELINE_ENTRIES counts the affected elements serialized as ratchet keys.",
    "VIOLATIONS_BY_RULE:",
    ...sortedRuleCounts.map(([ruleId, count]) => `- ${ruleId}: ${count}`),
    "VIOLATIONS_BY_IMPACT:",
    ...IMPACT_ORDER.map((impact) => `- ${impact}: ${impactCounts.get(impact) ?? 0}`),
    ...unknownImpactLine,
    "BASELINE_ENTRIES_BY_IMPACT:",
    ...IMPACT_ORDER.map((impact) => `- ${impact}: ${baselineEntryImpactCounts.get(impact) ?? 0}`),
    ...unknownBaselineEntryImpactLine,
    ...triageLines,
    ...userImpacts,
    "",
    "CHARTS_SUCCESSOR_WORK: The read-only SVG surfaces in Chart, ChartFrame, CashOnHandTrendChart, ComparisonBar, GeographyShareChart, HorizontalBarChart, MonthlyContributionsChart, OutsideSpendingChart, and ReceiptCompositionChart expose visible summaries and exact rows, but axe cannot prove screen-reader data access for SVG charts. Successor work must add automated screen-reader data-access contracts for these chart surfaces; Stage 2 adds no chart assertions or remediation markup.",
    STAGE_2_SECTION_END
  ].join("\n");
}

function appendAccessibilityReceipt(routeResults: AccessibilityRouteResult[]): void {
  mkdirSync(dirname(ACCESSIBILITY_RECEIPT_PATH), { recursive: true });
  const receipt = readFileSync(ACCESSIBILITY_RECEIPT_PATH, "utf8");
  writeFileSync(
    ACCESSIBILITY_RECEIPT_PATH,
    replaceStage2Section(receipt, stage2ReceiptSection(routeResults))
  );
}

test.describe("accessibility smoke axe scan", () => {
  test("baseline entries use stable route, rule, and element identity", () => {
    const violation = scrollableRegionViolation([
      axeNode(["main > pre"], "<pre>Example</pre>"),
      axeNode(["main > code"], "<code>Example</code>"),
      axeNode([], "<section>\n  Example\n</section>", null)
    ]);
    const routeResult = { name: "Developers", path: "/developers", violations: [violation] };
    const entries = normalizeBaselineEntries([routeResult]);
    const reversedEntries = normalizeBaselineEntries([
      { ...routeResult, violations: [{ ...violation, nodes: [...violation.nodes].reverse() }] }
    ]);
    const singleSelector = { ...violation.nodes[0], target: ["main || iframe"] };
    const frameSelectors = { ...violation.nodes[0], target: ["main", "iframe"] };

    expect(reversedEntries).toEqual(entries);
    expect(stableElementIdentifier(singleSelector)).not.toBe(stableElementIdentifier(frameSelectors));
    expect(entries.map(({ key }) => key)).toEqual([
      "/developers::scrollable-region-focusable::html:<section> Example </section>",
      '/developers::scrollable-region-focusable::target:["main > code"]',
      '/developers::scrollable-region-focusable::target:["main > pre"]'
    ]);
    expect(entries[2]).toEqual(
      expect.objectContaining({
        routeName: "Developers",
        routePath: "/developers",
        ruleId: "scrollable-region-focusable",
        impact: "serious",
        elementIdentifier: 'target:["main > pre"]',
        target: ["main > pre"],
        html: "<pre>Example</pre>",
        failureSummary: "Fix the scrollable region"
      })
    );
    expect(entries[0]).toEqual(
      expect.objectContaining({
        impact: "serious",
        elementIdentifier: "html:<section> Example </section>",
        target: [],
        html: "<section> Example </section>"
      })
    );
  });

  test("Stage 2 receipt replacement is idempotent", () => {
    const stage2Section = stage2ReceiptSection([]);
    const receiptWithOldSection = [
      "# Accessibility evidence",
      STAGE_2_SECTION_START,
      "stale totals",
      STAGE_2_SECTION_END,
      ""
    ].join("\n");

    const updatedReceipt = replaceStage2Section(receiptWithOldSection, stage2Section);

    expect(updatedReceipt).not.toContain("stale totals");
    expect(updatedReceipt.match(new RegExp(STAGE_2_SECTION_START, "g"))).toHaveLength(1);
    expect(replaceStage2Section(updatedReceipt, stage2Section)).toBe(updatedReceipt);
  });

  test("Stage 2 receipt distinguishes rule results from affected element entries", () => {
    const violation = scrollableRegionViolation([
      axeNode(["main > pre"], "<pre>First</pre>"),
      axeNode(["main > code"], "<code>Second</code>")
    ]);

    const section = stage2ReceiptSection([
      { name: "Developers", path: "/developers", violations: [violation] }
    ]);

    expect(section).toContain("TOTAL_VIOLATIONS: 1");
    expect(section).toContain("TOTAL_BASELINE_ENTRIES: 2");
    expect(section).toContain("BASELINE_ENTRIES_BY_IMPACT:\n- critical: 0\n- serious: 2\n- moderate: 0\n- minor: 0");
  });

  test("baseline comparison fails when observed violations add a new stable key", () => {
    const baselineEntry = baselineEntryForKey("/developers::region::target:[\"main\"]");
    const newObservedEntry = baselineEntryForKey("/developers::region::target:[\"aside\"]");

    expect(() => assertNoNewAccessibilityViolations([baselineEntry, newObservedEntry], [baselineEntry])).toThrow(
      /New accessibility violations/
    );
  });

  test("serious assertion throws for a mixed serious and moderate list, naming each serious key and the count", () => {
    const progressbarEntry = {
      ...baselineEntryForKey('/::aria-progressbar-name::target:[".navigation-progress"]'),
      ruleId: "aria-progressbar-name",
      impact: "serious" as AxeImpact
    };
    const scrollableEntry = {
      ...baselineEntryForKey('/developers::scrollable-region-focusable::target:["main > pre"]'),
      ruleId: "scrollable-region-focusable",
      impact: "serious" as AxeImpact
    };
    const moderateEntry = baselineEntryForKey('/developers::region::target:["main"]');

    let thrown: Error | null = null;
    try {
      assertNoSeriousAccessibilityViolations([progressbarEntry, moderateEntry, scrollableEntry]);
    } catch (error) {
      thrown = error as Error;
    }

    expect(thrown).not.toBeNull();
    const message = thrown?.message ?? "";
    expect(message).toContain("Serious or worse accessibility violations found (2):");
    expect(message).toContain(progressbarEntry.key);
    expect(message).toContain(scrollableEntry.key);
    expect(message).not.toContain(moderateEntry.key);
  });

  test("serious assertion does not throw for a moderate-only list", () => {
    const regionEntry = baselineEntryForKey('/developers::region::target:["main"]');
    const minorEntry = {
      ...baselineEntryForKey('/developers::region::target:["aside"]'),
      impact: "minor" as AxeImpact
    };

    expect(() => assertNoSeriousAccessibilityViolations([regionEntry, minorEntry])).not.toThrow();
  });

  test("serious assertion counts a critical entry and a null-impact entry", () => {
    const criticalEntry = {
      ...baselineEntryForKey('/developers::region::target:["main"]'),
      impact: "critical" as AxeImpact
    };
    const nullImpactEntry = {
      ...baselineEntryForKey('/developers::region::target:["aside"]'),
      impact: null
    };

    expect(() => assertNoSeriousAccessibilityViolations([criticalEntry])).toThrow(/found \(1\)/);
    expect(() => assertNoSeriousAccessibilityViolations([nullImpactEntry])).toThrow(/found \(1\)/);
    expect(() => assertNoSeriousAccessibilityViolations([criticalEntry, nullImpactEntry])).toThrow(/found \(2\)/);
  });

  test("baseline comparison passes for the same or fewer stable keys", () => {
    const firstEntry = baselineEntryForKey("/developers::region::target:[\"main\"]");
    const secondEntry = baselineEntryForKey("/developers::scrollable-region-focusable::target:[\"pre\"]");

    expect(() => assertNoNewAccessibilityViolations([firstEntry, secondEntry], [firstEntry, secondEntry])).not.toThrow();
    expect(() => assertNoNewAccessibilityViolations([firstEntry], [firstEntry, secondEntry])).not.toThrow();
  });

  test("fixture destinations expose non-empty content before axe measurement", async ({ page }: { page: Page }) => {
    await stubExternalImages(page);
    expect(ACCESSIBILITY_SCAN_DESTINATIONS.length).toBeGreaterThan(0);

    const routeResults: AccessibilityRouteResult[] = [];
    for (const destination of ACCESSIBILITY_SCAN_DESTINATIONS) {
      routeResults.push(await scanDestination(page, destination));
    }

    expect(routeResults).toHaveLength(ACCESSIBILITY_SCAN_DESTINATIONS.length);
    updateAccessibilityArtifactsOrAssertBaseline(routeResults);
    // Runs after the update call and unconditional with respect to UPDATE_ACCESSIBILITY_BASELINE:
    // Stage 3 must still regenerate the artifacts (which the update branch writes before this throws),
    // and a regenerated run must not be exempt from the serious floor or a green run would prove nothing.
    assertNoSeriousAccessibilityViolations(normalizeBaselineEntries(routeResults));
  });

  test("application shell skip link bypasses primary navigation without changing its traversal", async ({ page }: { page: Page }) => {
    const pageLoadErrors = capturePageLoadErrors(page);

    await page.goto("/");
    await expect(page.getByTestId("shell-header")).toBeVisible();
    await expect(page.getByTestId("shell-primary-nav")).toBeVisible();
    await expect(page.getByTestId("shell-main")).toBeVisible();
    await expect(page.getByTestId("shell-footer")).toBeVisible();

    const skipLink = page.getByTestId("shell-skip-link");
    await expect(skipLink).not.toBeInViewport();
    await expectNextTabStop(page, "shell-skip-link");
    await expect(skipLink).toBeVisible();
    await expect(skipLink).toBeInViewport();
    await expect(skipLink).toHaveCSS("outline-style", /^(auto|solid)$/);
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("shell-main")).toBeFocused();
    await expect(page).toHaveURL(/#main-content$/);

    await page.goto("/");
    await expectNextTabStop(page, "shell-skip-link");
    await expectNextTabStop(page, "shell-nav-link-home");
    await expect(page.getByTestId("shell-nav-link-home")).toHaveCSS("outline-style", /^(auto|solid)$/);
    await expectNextTabStop(page, "shell-nav-link-search");
    await expectNextTabStop(page, "shell-nav-link-candidates");
    await expectNextTabStop(page, "shell-nav-link-committees");
    await expectNextTabStop(page, "shell-nav-link-congress");
    await expectNextTabStop(page, "shell-nav-link-developers");
    await expectNextTabStop(page, "shell-nav-link-methodology");

    await pageLoadErrors.assertNoErrors();
  });
});
