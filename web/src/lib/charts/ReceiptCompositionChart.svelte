<script lang="ts">
  import ChartFrame from "./ChartFrame.svelte";
  import { formatChartMoneyValue, formatPercent } from "./finance";
  import type { ChartHeadingLevel, ChartFrameProps, ExactDisclosureRow, ReceiptCompositionRow } from "./types";

  export let testId: string;
  export let disclosureContext: string;
  export let cycle: number;
  export let coverageThrough: string | null;
  export let sources: ChartFrameProps["sources"] = [];
  // Retained for the public DetailPage contract after the duplicate inner
  // chart heading was removed; the HTML bar list has no nested heading.
  export let headingLevel: ChartHeadingLevel = 3;
  void headingLevel;
  export let rows: ReceiptCompositionRow[] = [];
  export let totalReceipts: number | null;
  export let canPlot: boolean;
  export let caveat = "";

  $: hasRows = rows.length > 0;
  $: canRenderPlot =
    hasRows &&
    canPlot &&
    totalReceipts !== null &&
    rows.every((row) => row.canPlot && row.amount !== null && row.denominator !== null);
  $: state = !hasRows
    ? { kind: "no-data" as const, message: "Receipt source components are not loaded yet." }
    : canRenderPlot
      ? { kind: "ready" as const }
      : {
          kind: "table-only" as const,
          message: caveat || "Source components do not reconcile cleanly enough for a proportional plot."
        };
  $: exactRows = buildExactRows(rows);
  $: summary = {
    sentence: `Receipt components disclose ${formatChartMoneyValue(
      totalReceipts,
      rows[0]?.denominatorLabel
    )} in total receipts for the ${cycle} cycle.`
  };

  function rowShare(row: ReceiptCompositionRow): number | null {
    if (row.amount === null || row.denominator === null) {
      return null;
    }
    return row.denominator === 0 ? 0 : row.amount / row.denominator;
  }

  function buildExactRows(inputRows: ReceiptCompositionRow[]): ExactDisclosureRow[] {
    return inputRows.map((row) => ({
      label: row.label,
      values: [
        { label: "Dollars", value: formatChartMoneyValue(row.amount, row.amountLabel) },
        {
          label: "Share",
          value: rowShare(row) === null ? "Not safely plottable" : formatPercent(rowShare(row) ?? 0)
        },
        {
          label: "Denominator",
          value: formatChartMoneyValue(row.denominator, row.denominatorLabel)
        }
      ]
    }));
  }

</script>

<ChartFrame
  {testId}
  {disclosureContext}
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
    {#each rows as row (row.id)}
      {@const share = rowShare(row) ?? 0}
      <div class="receipt-composition__row">
        <span>{row.label}</span>
        <span>{formatChartMoneyValue(row.amount, row.amountLabel)} ({formatPercent(share)})</span>
        <span
          class="receipt-composition__bar"
          style:--finance-share={`${share * 100}%`}
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
