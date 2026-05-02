<script lang="ts">
  export let data: unknown[] = [];
  export let series: Array<{ key: string }> = [];
  export let x: string = "";
  export let axis: boolean = false;
</script>

<div
  data-chart-kind="bar"
  data-row-count={data.length}
  data-series-count={series.length}
  data-x-key={x}
  data-axis-enabled={axis}
></div>
