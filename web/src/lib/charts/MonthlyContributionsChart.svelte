<script lang="ts">
  import ChartFrame from "./ChartFrame.svelte";
  import Chart from "./Chart.svelte";
  import {
    formatCount,
    formatCurrency,
    formatMonthKey,
    getReadableTickCeiling,
    zeroFillCoveredMonths
  } from "./finance";
  import type { ChartFrameProps, ChartSeries, ExactDisclosureRow, MonthlyContributionRow } from "./types";

  export let testId: string;
  export let cycle: number;
  export let coverageThrough: string | null;
  export let sources: ChartFrameProps["sources"] = [];
  export let rows: MonthlyContributionRow[] = [];
  export let coveredMonths: string[] = [];
  // Supplied by comparison surfaces so sibling columns plot against one domain;
  // omitted elsewhere, where the chart self-normalizes to its own largest month.
  export let scaleMax: number | undefined = undefined;

  $: filledRows = zeroFillCoveredMonths(rows, coveredMonths);
  $: totalAmount = filledRows.reduce((sum, row) => sum + row.amount, 0);
  $: maxAmount = Math.max(0, ...filledRows.map((row) => row.amount));
  $: tickCeiling = getReadableTickCeiling(scaleMax ?? maxAmount);
  $: chartSeries = buildChartSeries(filledRows, tickCeiling);
  $: state =
    filledRows.length === 0
      ? {
          kind: "no-data" as const,
          message: "No itemized individual contribution rows are loaded yet."
        }
      : { kind: "ready" as const };
  $: exactRows = filledRows.map(
    (row): ExactDisclosureRow => ({
      label: formatMonthKey(row.month),
      values: [
        { label: "Dollars", value: formatCurrency(row.amount) },
        { label: "Transactions", value: formatCount(row.transactionCount) },
        { label: "Coverage", value: row.covered ? "Covered" : "Missing source coverage" }
      ]
    })
  );
  $: summary = {
    sentence: `Itemized individual contributions total ${formatCurrency(totalAmount)} in the ${cycle} cycle.`
  };

  function buildChartSeries(
    inputRows: MonthlyContributionRow[],
    readableCeiling: number
  ): ChartSeries[] {
    return [
      {
        id: "monthly_contributions",
        label: `Monthly contribution dollars; readable ceiling ${formatCurrency(readableCeiling)}`,
        points: inputRows.map((row) => ({ x: row.month, y: row.amount }))
      }
    ];
  }
</script>

<ChartFrame
  {testId}
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
      series={chartSeries}
      yDomain={tickCeiling > 0 ? [0, tickCeiling] : undefined}
    />
    {#each filledRows as row (row.month)}
      <div class="monthly-contributions__row">
        <span>{formatMonthKey(row.month)}</span>
        <span>{formatCurrency(row.amount)}</span>
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
