<script lang="ts">
  import { BarChart, LineChart } from "layerchart";
  import type { ChartKind, ChartSeries } from "./types";

  export let kind: ChartKind;
  export let title: string;
  export let ariaLabel: string;
  export let series: ChartSeries[] = [];

  type LayerChartRow = {
    x: string | number | Date;
    [seriesKey: string]: string | number | Date;
  };

  type LayerChartSeries = {
    key: string;
    label: string;
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
    return inputSeries.map((item, index) => ({
      key: item.id,
      label: item.label,
      color: SERIES_COLORS[index % SERIES_COLORS.length]
    }));
  }

  $: hasPoints = series.some((item) => item.points.length > 0);
  $: chartRows = toLayerChartRows(series);
  $: layerSeries = toLayerChartSeries(series);
</script>

<section class="chart-wrapper" aria-label={ariaLabel}>
  <h3>{title}</h3>

  {#if hasPoints}
    {#if kind === "line"}
      <LineChart data={chartRows} x="x" series={layerSeries} axis={true} />
    {:else}
      <BarChart data={chartRows} x="x" series={layerSeries} axis={true} />
    {/if}
  {:else}
    <p>No chart data available.</p>
  {/if}
</section>
