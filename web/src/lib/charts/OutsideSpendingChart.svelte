<script lang="ts">
  import ChartFrame from "./ChartFrame.svelte";
  import Chart from "./Chart.svelte";
  import {
    FINANCE_CHART_COLORS,
    calculateOutsideSpendingDomain,
    formatCount,
    formatCurrency,
    toExactRows
  } from "./finance";
  import type { ChartFrameProps, ChartSeries, ExactDisclosureRow, OutsideSpendingRow } from "./types";

  export let testId: string;
  export let cycle: number;
  export let coverageThrough: string | null;
  export let sources: ChartFrameProps["sources"] = [];
  export let rows: OutsideSpendingRow[] = [];
  export let topSpenders: OutsideSpendingRow[] = [];
  // Supplied by comparison surfaces so sibling columns share one zero-centered
  // domain; omitted elsewhere, where the chart self-normalizes to its own rows.
  export let scaleMax: number | undefined = undefined;

  $: supportTotal = rows
    .filter((row) => row.stance === "support")
    .reduce((sum, row) => sum + row.amount, 0);
  $: opposeTotal = rows
    .filter((row) => row.stance === "oppose")
    .reduce((sum, row) => sum + row.amount, 0);
  $: hasActivity = supportTotal > 0 || opposeTotal > 0;
  $: domain = calculateOutsideSpendingDomain(rows, scaleMax);
  $: chartSeries = buildChartSeries(domain.signedRows, rows);
  $: state = hasActivity
    ? { kind: "ready" as const }
    : {
        kind: "no-data" as const,
        message: "No independent expenditure support or oppose activity is reported for this cycle."
      };
  $: exactRows = buildExactRows(rows, topSpenders);
  $: summary = {
    sentence: `Outside spending reports ${formatCurrency(supportTotal)} in support spending and ${formatCurrency(
      opposeTotal
    )} in oppose spending for the ${cycle} cycle.`
  };

  function buildExactRows(
    spendingRows: OutsideSpendingRow[],
    spenderRows: OutsideSpendingRow[]
  ): ExactDisclosureRow[] {
    return [
      ...toExactRows(spendingRows).map((row, index) =>
        withSourceFiling(row, spendingRows[index]?.sourceHref)
      ),
      ...spenderRows.map((row) => ({
        label: `Top spender: ${row.label}`,
        values: [
          { label: "Dollars", value: formatCurrency(row.amount) },
          { label: "Transactions", value: formatCount(row.transactionCount) },
          { label: "Stance", value: row.stance === "support" ? "Support spending" : "Oppose spending" },
          ...(row.sourceHref === undefined
            ? []
            : [{ label: "Source filing", value: "Source filing", href: row.sourceHref }])
        ]
      }))
    ];
  }

  function withSourceFiling(row: ExactDisclosureRow, sourceHref: string | undefined): ExactDisclosureRow {
    if (sourceHref === undefined) {
      return row;
    }
    return {
      ...row,
      values: [...row.values, { label: "Source filing", value: "Source filing", href: sourceHref }]
    };
  }

  function getStanceClass(rowId: string): string {
    const stance = rows.find((row) => row.id === rowId)?.stance ?? "support";
    return `outside-spending__row outside-spending__row--${stance}`;
  }

  /**
   * Two series, one per stance, so the diverging scale carries its meaning in
   * colour as well as in direction.
   *
   * This was a single series of signed amounts, which meant every bar was painted
   * the same palette colour and only its direction distinguished money spent FOR a
   * candidate from money spent AGAINST them — while the HTML rows immediately below
   * the plot already carried the stance in a coloured left border. Two encodings of
   * one fact, disagreeing.
   *
   * Each series carries a point for every row, zero where the row belongs to the
   * other stance, so both series share one x domain and a row's own bar is the only
   * one with height at its band. Colours come from FINANCE_CHART_COLORS, the same
   * tokens the rows below consume.
   */
  function buildChartSeries(
    signedRows: Array<{ id: string; label: string; signedAmount: number }>,
    spendingRows: OutsideSpendingRow[]
  ): ChartSeries[] {
    const stanceByRowId = new Map(spendingRows.map((row) => [row.id, row.stance]));

    const stanceSeries = (
      stance: OutsideSpendingRow["stance"],
      label: string,
      color: string
    ): ChartSeries => ({
      id: `outside_spending_${stance}`,
      label,
      color,
      points: signedRows.map((row) => ({
        x: row.label,
        y: stanceByRowId.get(row.id) === stance ? row.signedAmount : 0
      }))
    });

    return [
      stanceSeries("support", "Support spending", FINANCE_CHART_COLORS.support),
      stanceSeries("oppose", "Oppose spending", FINANCE_CHART_COLORS.oppose)
    ];
  }
</script>

<ChartFrame
  {testId}
  title="Outside spending"
  unit="dollars"
  {cycle}
  {coverageThrough}
  {sources}
  {summary}
  {exactRows}
  {state}
>
  <div
    class="outside-spending"
    data-testid="{testId}-plot"
    data-zero-centered="true"
    data-domain-min={domain.min}
    data-domain-max={domain.max}
  >
    <div
      class="outside-spending__axis"
      data-domain-min={domain.min}
      data-domain-max={domain.max}
    >
      Zero-centered support/oppose comparison
    </div>
    <Chart
      kind="bar"
      title="Zero-centered support/oppose comparison"
      ariaLabel="Zero-centered support and oppose spending comparison"
      unit="dollars"
      series={chartSeries}
      yDomain={[domain.min, domain.max]}
    />
    {#each domain.signedRows as row (row.id)}
      <div class={getStanceClass(row.id)}>
        <span>{row.label}</span>
        <span>{formatCurrency(Math.abs(row.signedAmount))}</span>
      </div>
    {/each}

    <section>
      <h4>Top spenders</h4>
      {#each topSpenders as spender (`${spender.id}-${spender.stance}`)}
        <p>
          {spender.label}: {formatCurrency(spender.amount)}; Transactions:
          {formatCount(spender.transactionCount)}
        </p>
      {/each}
    </section>

    <section>
      <h4>Transactions</h4>
      {#each rows as row (row.id)}
        <p>{row.label}: {formatCount(row.transactionCount)} transactions</p>
      {/each}
    </section>
  </div>
</ChartFrame>

<style>
  .outside-spending {
    display: grid;
    gap: 0.5rem;
  }

  .outside-spending__axis {
    border-top: 2px solid #334155;
    color: #475569;
    padding-top: 0.25rem;
  }

  .outside-spending__row {
    display: grid;
    gap: 0.25rem;
    min-height: 2.5rem;
    padding-left: 0.5rem;
  }

  /*
    These two must stay equal to FINANCE_CHART_COLORS.support / .oppose in
    finance.ts, which is what the plot's bars use. A Svelte <style> block cannot
    read a module constant, so the pairing is held by
    expectDivergingStanceFills in web/tests/smoke/smoke-helpers.ts, which asserts
    the bars paint in exactly those tokens. Change both or neither.
  */
  .outside-spending__row--support {
    border-left: 0.5rem solid #0f766e;
  }

  .outside-spending__row--oppose {
    border-left: 0.5rem solid #92400e;
  }

  .outside-spending h4,
  .outside-spending p {
    margin: 0;
  }
</style>
