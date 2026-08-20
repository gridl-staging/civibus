<script lang="ts">
  import "layerchart/core.css";
  import { BarChart, LineChart } from "layerchart/svg";
  import { AXIS_VALUE_FORMATTERS, TOOLTIP_VALUE_FORMATTERS } from "./finance";
  import type { ChartKind, ChartSeries, FinanceChartUnit } from "./types";

  export let kind: ChartKind;
  export let title: string;
  export let ariaLabel: string;
  // The unit the enclosing ChartFrame declares. Selects the value-axis and tooltip
  // formatters below, so the plot cannot disagree with the frame's own "Unit: …"
  // label the way GeographyShareChart did. See docs/reference/ui_chart_encoding.md §3.
  export let unit: FinanceChartUnit;
  export let series: ChartSeries[] = [];
  export let yDomain: [number, number] | undefined = undefined;

  // Gutters reserved inside the chart's own <svg> for the axes, in CSS pixels.
  //
  // These are not cosmetic. layerchart draws tick labels in the padding, so a
  // gutter narrower than the widest label leaves that label hanging outside the
  // svg and overlapping whatever sits beside it. Measured before this existed:
  // production y-labels ("$1,250,000.00") escaped by 28-34px.
  //
  // Each number is sized to a real rendered label at ~5.6px per character:
  //   left   the widest abbreviated currency tick the axis can emit, "-$999.9M"
  //          (8 chars ~ 45px) plus the 4px tick mark and a few px of air. Sized
  //          against the ABBREVIATED formatter — full-precision currency would
  //          need ~90px, which is why the formatter and this number are one
  //          decision. Re-measure this if AXIS_VALUE_FORMATTERS changes.
  //   right  half of the last x tick label, which is centred on its band and so
  //          overhangs the plot by half its width ("2026-06" ~ 37px -> 19px).
  //   bottom one line of x tick label plus its tick mark.
  //   top    a full line of text, not the half-line the topmost y tick strictly
  //          needs. The extra is headroom for font metrics: these gutters are
  //          asserted on CI's Linux runner, whose Liberation faces are taller than
  //          the macOS ones a developer measures against, and at half a line the
  //          measured slack was 1.5px. The support/oppose chart escaped the top by
  //          2.5px with no top padding at all.
  //
  // Measured slack at the tightest tick, fixture data, macOS: left 26px, right
  // 22px, bottom 15px, top 9.5px. web/tests/smoke/smoke-helpers.ts
  // expectTickLabelsInsidePlotBox holds these to a 0.5px tolerance in a real
  // browser; it is the reason a future session cannot quietly "clean up" these
  // numbers.
  const AXIS_PADDING = { top: 16, right: 24, bottom: 32, left: 56 } as const;

  // Minimum horizontal room per x tick label, which is what makes a band axis
  // subsample instead of drawing every category. layerchart defaults band scales
  // to tickSpacing: null, i.e. "render the entire domain", so 54 months rendered
  // as 54 overlapping labels — an unreadable smear rather than an axis. 80px fits
  // a "2026-06" label with air, thins labels out as the viewport narrows, and is
  // a no-op for the categorical charts, whose handful of bands stays under the
  // resulting count. See docs/reference/ui_chart_encoding.md §5.
  const X_TICK_SPACING_PX = 80;

  type LayerChartRow = {
    x: string | number | Date;
    [seriesKey: string]: string | number | Date;
  };

  type LayerChartSeries = {
    key: string;
    label: string;
    value: string;
    color: string;
  };

  const SERIES_COLORS = [
    "hsl(210 90% 45%)",
    "hsl(150 65% 40%)",
    "hsl(35 90% 50%)",
    "hsl(345 70% 50%)"
  ] as const;

  function toLayerChartRows(inputSeries: ChartSeries[]): LayerChartRow[] {
    const rowsByX = new Map<string, LayerChartRow>();

    for (const item of inputSeries) {
      for (const point of item.points) {
        const rowKey = `${typeof point.x}:${String(point.x)}`;
        const existingRow = rowsByX.get(rowKey);

        if (existingRow) {
          existingRow[item.id] = point.y;
          continue;
        }

        rowsByX.set(rowKey, { x: point.x, [item.id]: point.y });
      }
    }

    return Array.from(rowsByX.values());
  }

  function toLayerChartSeries(inputSeries: ChartSeries[]): LayerChartSeries[] {
    const colorIndexByLabel = new Map<string, number>();
    let nextColorIndex = 0;

    return inputSeries.map((item) => {
      const existingColorIndex = colorIndexByLabel.get(item.label);
      const colorIndex = existingColorIndex ?? nextColorIndex++;

      if (existingColorIndex === undefined) {
        colorIndexByLabel.set(item.label, colorIndex);
      }

      return {
        key: item.id,
        label: item.label,
        value: item.id,
        // A series may name its own colour when the colour IS the encoding — the
        // diverging support/oppose scale, whose two hues have to match the stance
        // colours the surrounding HTML rows already use. Everything else takes the
        // palette by position.
        color: item.color ?? SERIES_COLORS[colorIndex % SERIES_COLORS.length]
      };
    });
  }

  $: hasPoints = series.some((item) => item.points.length > 0);
  $: chartRows = toLayerChartRows(series);
  $: layerSeries = toLayerChartSeries(series);
  $: chartProps = {
    yAxis: { format: AXIS_VALUE_FORMATTERS[unit] },
    xAxis: { tickSpacing: X_TICK_SPACING_PX },
    tooltip: {
      item: { format: TOOLTIP_VALUE_FORMATTERS[unit] },
      // layerchart's tooltip carries no role of its own. Naming it lets a browser
      // probe locate it semantically and assert what it says, instead of asserting
      // the CSS that used to suppress it.
      root: { props: { root: { role: "tooltip" } } }
    }
  };
</script>

<section class="chart-wrapper" aria-label={ariaLabel}>
  <h3>{title}</h3>

  <div class="chart-wrapper__body">
    {#if hasPoints}
      {#if kind === "line"}
        <LineChart
          data={chartRows}
          x="x"
          series={layerSeries}
          axis={true}
          height={288}
          padding={AXIS_PADDING}
          props={chartProps}
          {yDomain}
        />
      {:else}
        <BarChart
          data={chartRows}
          x="x"
          series={layerSeries}
          axis={true}
          height={288}
          padding={AXIS_PADDING}
          props={chartProps}
          {yDomain}
        />
      {/if}
    {:else}
      <p>No chart data available.</p>
    {/if}
  </div>
</section>

<style>
  .chart-wrapper {
    display: grid;
    gap: 0.75rem;
  }

  .chart-wrapper__body {
    min-height: 18rem;
    height: 18rem;
    max-height: 24rem;
    width: 100%;
  }

  .chart-wrapper__body :global(svg) {
    display: block;
    width: 100%;
    height: 100%;
    /*
      No `pointer-events: none` here, deliberately.

      It was here, and it silently discarded a feature the package already ships:
      layerchart's BarChart defaults `tooltipContext` to true, so every chart in
      this repo had a working hover tooltip that no reader could ever reach. The
      charts were pictures to be trusted rather than data to be questioned.

      Guarded by expectChartTooltipOnHover in web/tests/smoke/smoke-helpers.ts,
      which asserts the tooltip's CONTENT rather than this property — asserting
      the CSS would assert the harness instead of the behaviour.
    */
  }

  .chart-wrapper__body p {
    margin: 0;
  }
</style>
