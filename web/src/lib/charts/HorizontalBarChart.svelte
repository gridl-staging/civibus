<script lang="ts">
  // A ranked HTML bar list inside the shared ChartFrame. This is NOT a
  // layerchart adapter and deliberately does not import Chart.svelte: the bars
  // are server-rendered HTML spans whose widths come from the shared-scale
  // transform, which is exactly the encoding ui_chart_encoding.md §1 prescribes
  // for "a ranked list of a handful of rows".
  import ChartFrame from "./ChartFrame.svelte";
  import { sharedScaleWidthPct } from "./comparison-transforms";
  import { formatCount, formatCurrency, toExactRows } from "./finance";
  import type { ChartFrameProps, HorizontalBarRow } from "./types";

  export let testId: string;
  export let title: string;
  export let cycle: number;
  export let coverageThrough: string | null;
  export let sources: ChartFrameProps["sources"] = [];
  export let rows: HorizontalBarRow[] = [];
  // Supplied by comparison surfaces so sibling columns plot against one domain;
  // omitted elsewhere, where the chart self-normalizes to its own largest row.
  export let scaleMax: number | undefined = undefined;

  $: plottedRows = rows.filter((row) => row.canPlot);
  // One expression, consumed by the frame's declared unit, so the rows' unit and
  // the frame's "Unit: …" label cannot drift apart.
  $: declaredUnit = plottedRows[0]?.unit ?? "dollars";
  $: ownMaxRowValue = Math.max(0, ...plottedRows.map((row) => getRowValue(row)));
  $: effectiveScaleMax = scaleMax ?? ownMaxRowValue;
  $: state =
    plottedRows.length === 0
      ? { kind: "no-data" as const, message: "No itemized rows are loaded for this chart." }
      : { kind: "ready" as const };
  $: exactRows = toExactRows(rows);
  $: summary = {
    sentence: `${title} discloses ${formatCurrency(
      plottedRows.reduce((sum, row) => sum + row.amount, 0)
    )} across ${formatCount(
      plottedRows.reduce((sum, row) => sum + row.transactionCount, 0)
    )} reported transactions in the ${cycle} cycle.`
  };

  function getRowWidth(row: HorizontalBarRow): string {
    return `${sharedScaleWidthPct(getRowValue(row), effectiveScaleMax) * 100}%`;
  }

  function getRowValue(row: HorizontalBarRow): number {
    return row.unit === "reported_transactions" ? row.transactionCount : row.amount;
  }

  function formatRowUnit(row: HorizontalBarRow): string {
    if (row.unit === "reported_transactions") {
      return `${formatCount(row.transactionCount)} reported transactions`;
    }
    return `${formatCurrency(row.amount)}; ${formatCount(row.transactionCount)} reported transactions`;
  }
</script>

<ChartFrame
  {testId}
  {title}
  unit={declaredUnit}
  {cycle}
  {coverageThrough}
  {sources}
  {summary}
  {exactRows}
  {state}
>
  <!--
    ONE visual encoding, deliberately (civibus-3a3). Until 2026-08-20 this
    component ALSO drew the same rows through the layerchart adapter as a
    VERTICAL svg bar chart above this list — two competing visual encodings of
    one series in one component. The HTML list won on evidence from rendering
    both: it prints every bucket label in full with its exact value while the
    svg duplicate thinned two of five band labels away at 390px, it repeated the
    frame's title as an extra heading, and it carried none of the ~450px of
    plot height the svg added to an already ~10,000px-tall person page. Exact
    values live in text beside each bar, so the svg's hover tooltip loses no
    information either. Guard: the "ONLY visual encoding" unit test in
    finance-components.test.ts and expectHtmlBarListRender in
    web/tests/smoke/smoke-helpers.ts both fail if an svg comes back here.
  -->
  <div class="horizontal-bars" data-testid="{testId}-plot" data-domain-max={effectiveScaleMax}>
    {#each plottedRows as row (row.id)}
      <div class="horizontal-bars__row">
        <span>{row.label}</span>
        <span>{formatRowUnit(row)}</span>
        <span class="horizontal-bars__bar" style:--finance-width={getRowWidth(row)}></span>
      </div>
    {/each}
  </div>
</ChartFrame>

<style>
  .horizontal-bars {
    display: grid;
    gap: 0.5rem;
  }

  .horizontal-bars__row {
    display: grid;
    gap: 0.25rem;
    min-height: 3rem;
  }

  /*
    The filled share of the bar must stay equal to FINANCE_CHART_COLORS.support
    (#0f766e) in finance.ts, the same single-series hue the neighbouring HTML
    rows use. A Svelte <style> block cannot read a module constant, so the
    pairing is held by expectHtmlBarListRender in
    web/tests/smoke/smoke-helpers.ts, which asserts the computed gradient paints
    in exactly that token. Change both or neither.
  */
  .horizontal-bars__bar {
    background: linear-gradient(90deg, #0f766e var(--finance-width), #e2e8f0 0);
    border: 1px solid #cbd5e1;
    display: block;
    height: 0.875rem;
  }
</style>
