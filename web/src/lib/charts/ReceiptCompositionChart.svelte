<script lang="ts">
  import ChartFrame from "./ChartFrame.svelte";
  import Chart from "./Chart.svelte";
  import { formatCurrency, formatPercent } from "./finance";
  import type { ChartFrameProps, ChartSeries, ExactDisclosureRow, ReceiptCompositionRow } from "./types";

  export let testId: string;
  export let cycle: number;
  export let coverageThrough: string | null;
  export let sources: ChartFrameProps["sources"] = [];
  export let rows: ReceiptCompositionRow[] = [];
  export let totalReceipts: number;
  export let canPlot: boolean;
  export let caveat = "";

  $: hasRows = rows.length > 0;
  $: canRenderPlot = hasRows && canPlot && rows.every((row) => row.canPlot);
  $: state = !hasRows
    ? { kind: "no-data" as const, message: "Receipt source components are not loaded yet." }
    : canRenderPlot
      ? { kind: "ready" as const }
      : {
          kind: "table-only" as const,
          message: caveat || "Source components do not reconcile cleanly enough for a proportional plot."
        };
  $: exactRows = buildExactRows(rows);
  $: chartSeries = buildChartSeries(rows);
  $: summary = {
    sentence: `Receipt components disclose ${formatCurrency(totalReceipts)} in total receipts for the ${cycle} cycle.`
  };

  function buildExactRows(inputRows: ReceiptCompositionRow[]): ExactDisclosureRow[] {
    return inputRows.map((row) => ({
      label: row.label,
      values: [
        { label: "Dollars", value: formatCurrency(row.amount) },
        { label: "Share", value: formatPercent(row.denominator === 0 ? 0 : row.amount / row.denominator) },
        { label: "Denominator", value: formatCurrency(totalReceipts) }
      ]
    }));
  }

  function buildChartSeries(inputRows: ReceiptCompositionRow[]): ChartSeries[] {
    return [
      {
        id: "receipt_source_amount",
        label: "Receipt source amount",
        points: inputRows.map((row) => ({ x: row.label, y: row.amount }))
      }
    ];
  }
</script>

<ChartFrame
  {testId}
  title="Sources of receipts"
  unit="dollars"
  {cycle}
  {coverageThrough}
  {sources}
  {summary}
  {exactRows}
  {state}
>
  <div class="receipt-composition" data-testid="{testId}-plot">
    <Chart
      kind="bar"
      title="Receipt source composition"
      ariaLabel="Receipt source composition by dollars"
      series={chartSeries}
    />
    {#each rows as row (row.id)}
      <div class="receipt-composition__row">
        <span>{row.label}</span>
        <span>{formatCurrency(row.amount)} ({formatPercent(row.denominator === 0 ? 0 : row.amount / row.denominator)})</span>
        <span
          class="receipt-composition__bar"
          style:--finance-share={`${row.denominator === 0 ? 0 : (row.amount / row.denominator) * 100}%`}
        ></span>
      </div>
    {/each}
  </div>
</ChartFrame>

<style>
  .receipt-composition {
    display: grid;
    gap: 0.5rem;
  }

  .receipt-composition__row {
    display: grid;
    gap: 0.25rem;
  }

  .receipt-composition__bar {
    background: linear-gradient(90deg, #0f766e var(--finance-share), #e2e8f0 0);
    border: 1px solid #cbd5e1;
    display: block;
    height: 0.875rem;
  }
</style>
