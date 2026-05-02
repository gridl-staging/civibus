<script context="module" lang="ts">
  import type { MapLayerId } from "$lib/config/app";

  export type LayerToggleChangeDetail = {
    layerId: MapLayerId;
    visible: boolean;
  };
</script>

<script lang="ts">
  import { createEventDispatcher } from "svelte";
  import {
    getMapLayersForLevel,
    type MapLayer,
    type MapLayerVisibility,
    type MapPageLevel
  } from "$lib/config/app";

  export let pageLevel: MapPageLevel;
  export let layerVisibility: MapLayerVisibility;

  const dispatch = createEventDispatcher<{
    change: LayerToggleChangeDetail;
  }>();

  $: pageLayers = getMapLayersForLevel(pageLevel);

  function isLayerVisible(layer: MapLayer): boolean {
    return layer.alwaysOn || layerVisibility[layer.id];
  }

  function handleLayerToggle(layerId: MapLayerId, event: Event): void {
    const target = event.currentTarget;
    if (!(target instanceof HTMLInputElement)) {
      return;
    }

    dispatch("change", {
      layerId,
      visible: target.checked
    });
  }
</script>

<fieldset class="layer-toggle" aria-label="Map layer controls">
  <legend>Map layers</legend>
  {#each pageLayers as layer (layer.id)}
    <label class="layer-toggle__row" data-layer-id={layer.id} for={"layer-toggle-" + layer.id}>
      <input
        id={"layer-toggle-" + layer.id}
        type="checkbox"
        checked={isLayerVisible(layer)}
        disabled={layer.alwaysOn}
        on:change={(event) => handleLayerToggle(layer.id, event)}
      />
      <span>{layer.label}</span>
    </label>
  {/each}
</fieldset>

<style>
  .layer-toggle {
    border: 1px solid var(--border-subtle, #d6dee6);
    border-radius: 0.5rem;
    padding: 0.75rem 1rem 1rem;
    margin: 0 0 1rem;
    display: grid;
    gap: 0.55rem;
  }

  .layer-toggle__row {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.96rem;
  }
</style>
