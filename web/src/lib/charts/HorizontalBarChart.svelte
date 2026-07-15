<script lang="ts">
  import ChartFrame from "./ChartFrame.svelte";
  import Chart from "./Chart.svelte";
  import { formatCount, formatCurrency, toExactRows } from "./finance";
  import type { ChartFrameProps, ChartSeries, HorizontalBarRow } from "./types";

  export let testId: string;
  export let title: string;
  export let cycle: number;
  export let coverageThrough: string | null;
  export let sources: ChartFrameProps["sources"] = [];
  export let rows: HorizontalBarRow[] = [];

  $: plottedRows = rows.filter((row) => row.canPlot);
  $: maxRowValue = Math.max(0, ...plottedRows.map((row) => getRowValue(row)));
  $: chartSeries = buildChartSeries(plottedRows);
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
    if (maxRowValue === 0) {
      return "0%";
    }
    return `${(getRowValue(row) / maxRowValue) * 100}%`;
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

  function buildChartSeries(inputRows: HorizontalBarRow[]): ChartSeries[] {
    return [
      {
        id: "horizontal_bar_value",
        label: inputRows[0]?.unit === "reported_transactions" ? "Reported transactions" : "Dollars",
        points: inputRows.map((row) => ({ x: row.label, y: getRowValue(row) }))
      }
    ];
  }
</script>

<ChartFrame
  {testId}
  {title}
  unit={plottedRows[0]?.unit ?? "dollars"}
  {cycle}
  {coverageThrough}
  {sources}
  {summary}
  {exactRows}
  {state}
>
  <div class="horizontal-bars" data-testid="{testId}-plot">
    <Chart
      kind="bar"
      title={title}
      ariaLabel={`${title} bar chart`}
      series={chartSeries}
    />
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

  .horizontal-bars__bar {
    background: linear-gradient(90deg, #0f766e var(--finance-width), #e2e8f0 0);
    border: 1px solid #cbd5e1;
    display: block;
    height: 0.875rem;
  }
</style>
