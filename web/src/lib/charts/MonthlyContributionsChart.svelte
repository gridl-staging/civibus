<script lang="ts">
  import ChartFrame from "./ChartFrame.svelte";
  import Chart from "./Chart.svelte";
  import {
    formatCount,
    formatChartMoneyValue,
    formatMonthKey,
    getReadableTickCeiling,
    zeroFillCoveredMonths
  } from "./finance";
  import type { ChartHeadingLevel, ChartFrameProps, ChartSeries, ExactDisclosureRow, MonthlyContributionRow } from "./types";

  export let testId: string;
  export let disclosureContext: string;
  export let cycle: number;
  export let coverageThrough: string | null;
  export let sources: ChartFrameProps["sources"] = [];
  // Outline depth for the inner chart heading; forwarded to the Chart
  // adapter (civibus-4yw). Default 3 preserves pre-prop rendering.
  export let headingLevel: ChartHeadingLevel = 3;
  export let rows: MonthlyContributionRow[] = [];
  export let coveredMonths: string[] = [];
  // Supplied by comparison surfaces so sibling columns plot against one domain;
  // omitted elsewhere, where the chart self-normalizes to its own largest month.
  export let scaleMax: number | undefined = undefined;

  $: filledRows = zeroFillCoveredMonths(rows, coveredMonths);
  $: geometryIsSafe = filledRows.every((row) => row.amount !== null);
  $: plottedRows = filledRows.filter(
    (row): row is MonthlyContributionRow & { amount: number } => row.amount !== null
  );
  $: totalAmount = plottedRows.reduce((sum, row) => sum + row.amount, 0);
  $: maxAmount = Math.max(0, ...plottedRows.map((row) => row.amount));
  $: tickCeiling = getReadableTickCeiling(scaleMax ?? maxAmount);
  $: chartSeries = buildChartSeries(filledRows);
  $: state =
    filledRows.length === 0
      ? {
          kind: "no-data" as const,
          message: "No itemized individual contribution rows are loaded yet."
        }
      : !geometryIsSafe
        ? {
            kind: "table-only" as const,
            message:
              "Amounts exceed the safely plottable range; exact values are shown in the chart data table."
          }
        : { kind: "ready" as const };
  $: exactRows = filledRows.map(
    (row): ExactDisclosureRow => ({
      label: formatMonthKey(row.month),
      values: [
        { label: "Dollars", value: formatChartMoneyValue(row.amount, row.amountLabel) },
        { label: "Transactions", value: formatCount(row.transactionCount) },
        { label: "Coverage", value: row.covered ? "Covered" : "Missing source coverage" }
      ]
    })
  );
  $: summary = {
    sentence: geometryIsSafe
      ? `Itemized individual contributions total ${formatChartMoneyValue(totalAmount)} in the ${cycle} cycle.`
      : `Exact itemized individual contribution amounts are shown for the ${cycle} cycle.`
  };

  function buildChartSeries(inputRows: MonthlyContributionRow[]): ChartSeries[] {
    return [
      {
        id: "monthly_contributions",
        // Reader-facing: this string is the tooltip's series label. The readable
        // ceiling is a domain calculation, not something to say to a person, and it
        // stays in `tickCeiling` where it is used.
        label: "Contributions",
        points: inputRows.flatMap((row) =>
          row.amount === null ? [] : [{ x: row.month, y: row.amount }]
        )
      }
    ];
  }
</script>

<ChartFrame
  {testId}
  {disclosureContext}
  title="Itemized individual contributions by month"
  unit="dollars"
  {cycle}
  {coverageThrough}
  {sources}
  {summary}
  {exactRows}
  {state}
>
  <div class="monthly-contributions" data-testid="{testId}-plot" data-domain-max={tickCeiling}>
    <Chart
      kind="bar"
      title="Monthly contribution columns"
      ariaLabel="Monthly contribution columns"
      unit="dollars"
      series={chartSeries}
      {headingLevel}
      yDomain={tickCeiling > 0 ? [0, tickCeiling] : undefined}
    />
    {#each filledRows as row (row.month)}
      <div class="monthly-contributions__row">
        <span>{formatMonthKey(row.month)}</span>
        <span>{formatChartMoneyValue(row.amount, row.amountLabel)}</span>
        <span>{formatCount(row.transactionCount)} {row.transactionCount === 1 ? "transaction" : "transactions"}</span>
      </div>
    {/each}
  </div>
</ChartFrame>

<style>
  .monthly-contributions {
    display: grid;
    gap: 0.5rem;
  }

  .monthly-contributions__row {
    align-items: center;
    border-left: 0.5rem solid #0f766e;
    display: grid;
    gap: 0.25rem;
    grid-template-columns: minmax(8rem, 1fr) minmax(7rem, auto) minmax(8rem, auto);
    min-height: 2.5rem;
  }

  @media (max-width: 42rem) {
    .monthly-contributions__row {
      grid-template-columns: minmax(0, 1fr);
    }
  }

</style>
