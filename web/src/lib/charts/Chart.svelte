<script lang="ts">
  import "layerchart/core.css";
  import { BarChart, LineChart } from "layerchart/svg";
  import type { ChartKind, ChartSeries } from "./types";

  export let kind: ChartKind;
  export let title: string;
  export let ariaLabel: string;
  export let series: ChartSeries[] = [];
  export let yDomain: [number, number] | undefined = undefined;

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
        color: SERIES_COLORS[colorIndex % SERIES_COLORS.length]
      };
    });
  }

  $: hasPoints = series.some((item) => item.points.length > 0);
  $: chartRows = toLayerChartRows(series);
  $: layerSeries = toLayerChartSeries(series);
</script>

<section class="chart-wrapper" aria-label={ariaLabel}>
  <h3>{title}</h3>

  <div class="chart-wrapper__body">
    {#if hasPoints}
      {#if kind === "line"}
        <LineChart data={chartRows} x="x" series={layerSeries} axis={true} height={288} {yDomain} />
      {:else}
        <BarChart data={chartRows} x="x" series={layerSeries} axis={true} height={288} {yDomain} />
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
    pointer-events: none;
  }

  .chart-wrapper__body p {
    margin: 0;
  }
</style>
