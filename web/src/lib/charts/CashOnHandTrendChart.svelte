<script lang="ts">
  import ChartFrame from "./ChartFrame.svelte";
  import Chart from "./Chart.svelte";
  import { buildCashOnHandSeries, formatCurrency, formatDate } from "./finance";
  import type { CashOnHandPoint, ChartFrameProps, ExactDisclosureRow } from "./types";

  export let testId: string;
  export let cycle: number;
  export let coverageThrough: string | null;
  export let sources: ChartFrameProps["sources"] = [];
  export let points: CashOnHandPoint[] = [];

  $: orderedPoints = [...points].sort((left, right) => left.periodEnd.localeCompare(right.periodEnd));
  $: latestPoint = orderedPoints.at(-1);
  $: chartSeries = buildCashOnHandSeries(orderedPoints);
  $: state =
    orderedPoints.length >= 2
      ? { kind: "ready" as const }
      : {
          kind: "no-data" as const,
          message: "Cash on hand needs two or more dated filing-period values before plotting."
        };
  $: exactRows = orderedPoints.map(
    (point): ExactDisclosureRow => ({
      label: formatDate(point.periodEnd),
      values: [
        { label: "Cash on hand", value: formatCurrency(point.amount) },
        {
          label: "Coverage gap",
          value: point.missingIntervalBefore
            ? "Missing source coverage before this filing period."
            : "No explicit missing interval."
        }
      ]
    })
  );
  $: summary = {
    sentence: `Cash on hand is ${formatCurrency(latestPoint?.amount ?? 0)} at the latest filing period in the ${cycle} cycle.`
  };
</script>

<ChartFrame
  {testId}
  title="Cash on hand"
  unit="dollars"
  {cycle}
  {coverageThrough}
  {sources}
  {summary}
  {exactRows}
  {state}
>
  <div class="cash-trend" data-testid="{testId}-plot">
    <Chart
      kind="line"
      title="Cash on hand trend"
      ariaLabel="Cash on hand trend by filing period"
      series={chartSeries}
    />
    {#each orderedPoints as point (point.periodEnd)}
      <div class:cash-trend__gap={point.missingIntervalBefore}>
        <span>{formatDate(point.periodEnd)}</span>
        <strong>{formatCurrency(point.amount)}</strong>
        {#if point.missingIntervalBefore}
          <span>Missing source coverage before this filing period.</span>
        {/if}
      </div>
    {/each}
  </div>
</ChartFrame>

<style>
  .cash-trend {
    display: grid;
    gap: 0.5rem;
  }

  .cash-trend div {
    border-left: 0.5rem solid #334155;
    display: grid;
    gap: 0.25rem;
    min-height: 2.5rem;
    padding-left: 0.5rem;
  }

  .cash-trend__gap {
    border-left-color: #92400e;
  }
</style>
