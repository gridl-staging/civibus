<script lang="ts">
  import {
    getMapLayersForLevel,
    type MapLayerVisibility
  } from "$lib/config/app";
  import LayerToggle, { type LayerToggleChangeDetail } from "$lib/region-map/LayerToggle.svelte";
  import RegionMap from "$lib/region-map/RegionMap.svelte";
  import type { PageData } from "./$types";

  export let data: PageData;
  let layerVisibility: MapLayerVisibility = { ...data.layerVisibilityDefaults };

  function handleLayerToggle(event: CustomEvent<LayerToggleChangeDetail>): void {
    const { layerId, visible } = event.detail;
    layerVisibility = {
      ...layerVisibility,
      [layerId]: visible
    };
  }

  $: stateName = data.geometry.features.find(
    (feature) => feature.properties.state === data.stateCode
  )?.properties.name ?? data.stateCode;
  $: availableLayers = getMapLayersForLevel(data.pageLevel);
  $: hasLayerControls = availableLayers.length > 0;
</script>

<section class="card state-detail" aria-label={`State detail for ${stateName}`}>
  <h2>{stateName}</h2>
  <p class="state-detail__status" role="status">{data.retirement.heading}</p>
  <p>{data.retirement.message}</p>

  <section class="detail__panel state-detail__map-drilldown">
    <h3>{data.stateCode} map context</h3>
    <p class="state-detail__map-summary">
      State, county, and congressional district geometry remains available for navigation context.
    </p>

    {#if hasLayerControls}
      <LayerToggle pageLevel={data.pageLevel} {layerVisibility} on:change={handleLayerToggle} />
    {/if}
    <RegionMap
      pageLevel={data.pageLevel}
      stateCode={data.stateCode}
      {layerVisibility}
      geometryByLevel={data.geometryByLevel}
    />
  </section>

  <section class="detail__panel">
    <h3>Reopening state coverage</h3>
    <p>{data.retirement.reversalPath}</p>
  </section>
</section>

<style>
  .state-detail__status {
    color: #714400;
    font-weight: 700;
  }

  .state-detail__map-summary {
    margin-top: 0;
    color: #44515e;
  }
</style>
