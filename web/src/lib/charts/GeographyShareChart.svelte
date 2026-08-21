<script lang="ts">
  import ChartFrame from "./ChartFrame.svelte";
  import Chart from "./Chart.svelte";
  import { formatCount, formatCurrency, toExactRows } from "./finance";
  import type { ChartHeadingLevel, ChartFrameProps, ChartSeries, GeographyShareRow } from "./types";

  export let testId: string;
  export let cycle: number;
  export let coverageThrough: string | null;
  export let sources: ChartFrameProps["sources"] = [];
  // Outline depth for the inner chart heading; forwarded to the Chart
  // adapter (civibus-4yw). Default 3 preserves pre-prop rendering.
  export let headingLevel: ChartHeadingLevel = 3;
  export let rows: GeographyShareRow[] = [];
  export let approximationNote = "";
  export let unknownIncludedInDenominator = false;

  $: hasGeographyRows = rows.length > 0;
  $: unknownSummary = rows.find((row) => row.label === "Unknown");
  $: hasUnknownRow = Boolean(unknownSummary);
  $: chartSeries = buildChartSeries(rows);
  $: state =
    !hasGeographyRows
      ? { kind: "no-data" as const, message: "No geography rows are loaded yet." }
      : !hasUnknownRow
        ? {
            kind: "table-only" as const,
            message: "Unknown geography row is required before rendering a denominator chart."
          }
      : { kind: "ready" as const };
  $: exactRows = toExactRows(rows);
  $: summary = {
    sentence: getSummarySentence(hasGeographyRows, unknownSummary, unknownIncludedInDenominator)
  };

  function getSummarySentence(
    hasRows: boolean,
    unknownRow: GeographyShareRow | undefined,
    includesUnknown: boolean
  ): string {
    if (!hasRows) {
      return `No geography rows are loaded for the ${cycle} cycle.`;
    }
    if (unknownRow) {
      const denominatorCopy = includesUnknown
        ? "Unknown is included in the visible geography denominator"
        : "Unknown is shown outside the classified geography denominator";
      const denominatorLabel = includesUnknown ? "visible denominator" : "classified denominator";
      return `${denominatorCopy}. Unknown is ${formatCurrency(
        unknownRow.amount
      )} with ${formatCount(unknownRow.transactionCount)} reported transactions; ${denominatorLabel} is ${formatCurrency(
        unknownRow.denominator
      )}.`;
    }
    return `Geography includes visible denominators for the ${cycle} cycle.`;
  }

  function buildChartSeries(inputRows: GeographyShareRow[]): ChartSeries[] {
    return [
      {
        id: "geography_share",
        label: "Contributions",
        // Plots DOLLARS, not the amount/denominator fraction it used to plot.
        //
        // The frame declares unit="dollars", the rows below print
        // formatCurrency(amount) of formatCurrency(denominator), and the disclosure
        // table prints dollars — but the SVG plotted a unitless 0.0-0.5, so its axis
        // read as a fraction while everything around it read as money. Three
        // surfaces of one chart, three answers.
        //
        // Resolved toward the declared unit rather than by relabelling the frame as
        // a percentage: two of the three surfaces and the frame's own label already
        // said dollars, and this way one currency axis formatter serves every money
        // chart instead of this one needing a bespoke percentage axis. Bar heights
        // are unchanged where the denominator is shared across rows, since dividing
        // every row by the same number only rescales the axis.
        points: inputRows.map((row) => ({ x: row.label, y: row.amount }))
      }
    ];
  }
</script>

<ChartFrame
  {testId}
  title="Geography"
  unit="dollars"
  {cycle}
  {coverageThrough}
  {sources}
  {summary}
  {exactRows}
  {state}
>
  <div class="geography-share" data-testid="{testId}-plot">
    <Chart
      kind="bar"
      title="Geography dollar share"
      ariaLabel="Geography dollar share by contributor location"
      unit="dollars"
      series={chartSeries}
      {headingLevel}
    />
    {#each rows as row (row.id)}
      <div class="geography-share__row">
        <span>{row.label}</span>
        <span>{formatCurrency(row.amount)} of {formatCurrency(row.denominator)}</span>
        <span>{formatCount(row.transactionCount)} {row.transactionCount === 1 ? "transaction" : "transactions"}</span>
      </div>
    {/each}
    {#if approximationNote}
      <p>{approximationNote}</p>
    {/if}
  </div>
</ChartFrame>

<style>
  .geography-share {
    display: grid;
    gap: 0.5rem;
  }

  .geography-share__row {
    border-left: 0.5rem solid #334155;
    display: grid;
    gap: 0.25rem;
    min-height: 2.75rem;
    padding-left: 0.5rem;
  }

  .geography-share p {
    color: #475569;
    margin: 0;
  }
</style>
