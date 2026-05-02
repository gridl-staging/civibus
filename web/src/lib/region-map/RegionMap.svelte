<script context="module" lang="ts">
  import type { CivicGeometryLevel } from "$lib/config/app";
  import type { CivicGeometryFeatureCollection } from "$lib/server/api/civic-geometry";

  export type RegionMapGeometryByLevel = Partial<
    Record<CivicGeometryLevel, CivicGeometryFeatureCollection>
  >;
</script>

<script lang="ts">
  import {
    getMapLayersForLevel,
    type MapLayer,
    type MapLayerVisibility,
    type MapPageLevel
  } from "$lib/config/app";
  import { buildCountyDetailPathFromDivisionName } from "$lib/region-map/county-slug";
  import type { CivicGeometryFeature } from "$lib/server/api/civic-geometry";
  import type {
    GeometryFeatureCollection,
    StateSummaryItem
  } from "$lib/server/api/state-pages-contract";
  import { DEFAULT_US_VIEWPORT, geometryFeatureToSvgPath } from "./projection";

  export let geometry: GeometryFeatureCollection | null = null;
  export let stateSummaries: StateSummaryItem[] = [];
  export let title = "United States campaign-finance coverage";
  export let unsupportedLabel = "Coverage not yet available";

  export let pageLevel: MapPageLevel | null = null;
  export let layerVisibility: MapLayerVisibility | null = null;
  export let geometryByLevel: RegionMapGeometryByLevel = {};
  export let stateCode: string | null = null;
  export let highlightedFeatureId: string | null = null;

  type StateRow = {
    code: string;
    name: string;
    pathData: string;
    supported: boolean;
    disabledLabel: string;
    warningText: string | null;
    href: string | null;
  };

  function buildSummariesByCode(summaries: StateSummaryItem[]): Map<string, StateSummaryItem> {
    const byCode = new Map<string, StateSummaryItem>();
    for (const summary of summaries) {
      byCode.set(summary.state_code, summary);
    }
    return byCode;
  }

  function buildDisabledLabel(summary: StateSummaryItem | null): string {
    if (summary?.support_status === "warning") {
      return "Coverage incomplete";
    }

    return unsupportedLabel;
  }

  function getLayerFeatures(layer: MapLayer): CivicGeometryFeature[] {
    return geometryByLevel[layer.level]?.features ?? [];
  }

  function getCountyDetailPath(layer: MapLayer, divisionName: string): string | null {
    if (layer.level !== "county" || stateCode === null) {
      return null;
    }

    return buildCountyDetailPathFromDivisionName(divisionName, stateCode);
  }

  function isHighlightedFeature(feature: CivicGeometryFeature): boolean {
    if (highlightedFeatureId === null) {
      return false;
    }
    return feature.properties.id === highlightedFeatureId;
  }

  function shouldDeemphasizeFeature(layer: MapLayer, feature: CivicGeometryFeature): boolean {
    if (highlightedFeatureId === null) {
      return false;
    }

    const layerFeatures = getLayerFeatures(layer);
    const layerHasMatch = layerFeatures.some(
      (layerFeature) => layerFeature.properties.id === highlightedFeatureId
    );
    return layerHasMatch && !isHighlightedFeature(feature);
  }

  $: summariesByCode = buildSummariesByCode(stateSummaries);
  $: states =
    geometry?.features.map((feature): StateRow => {
      const code = feature.properties.state;
      const summary = summariesByCode.get(code) ?? null;
      const supported = summary?.supported === true;
      return {
        code,
        name: feature.properties.name,
        pathData: geometryFeatureToSvgPath(feature),
        supported,
        disabledLabel: buildDisabledLabel(summary),
        warningText: summary?.warning_text ?? null,
        href: supported ? `/state/${code}` : null
      };
    }) ?? [];
  $: visibleLayers =
    pageLevel === null || layerVisibility === null
      ? []
      : getMapLayersForLevel(pageLevel).filter((layer) => layer.alwaysOn || layerVisibility[layer.id]);
</script>

<section class="region-map" aria-label={geometry !== null ? title : "Region map"}>
  {#if geometry !== null}
    <svg
      class="region-map__svg"
      viewBox="0 0 {DEFAULT_US_VIEWPORT.width} {DEFAULT_US_VIEWPORT.height}"
      role="img"
      aria-hidden="true"
      preserveAspectRatio="xMidYMid meet"
    >
      {#each states as row (row.code)}
        <path
          d={row.pathData}
          class="region-map__region"
          class:region-map__region--disabled={!row.supported}
        />
      {/each}
    </svg>

    <ul class="region-map__states">
      {#each states as row (row.code)}
        <li class="region-map__state">
          {#if row.supported && row.href}
            <a class="region-map__link" href={row.href}>{row.name}</a>
            {#if row.warningText}
              <span class="region-map__warning">{row.warningText}</span>
            {/if}
          {:else}
            <span class="region-map__disabled" aria-disabled="true">
              {row.name} — {row.disabledLabel}
            </span>
            {#if row.warningText}
              <span class="region-map__warning">{row.warningText}</span>
            {/if}
          {/if}
        </li>
      {/each}
    </ul>

    {#if $$slots.loading}
      <div class="region-map__loading">
        <slot name="loading" />
      </div>
    {/if}

    {#if $$slots.error}
      <div class="region-map__error" role="alert">
        <slot name="error" />
      </div>
    {/if}
  {:else if pageLevel !== null && layerVisibility !== null}
    <h3>Map preview</h3>
    {#if visibleLayers.length === 0}
      <p>No map layers are currently visible.</p>
    {:else}
      <ul class="region-map__feature-list">
        {#each visibleLayers as layer (layer.id)}
          {@const features = getLayerFeatures(layer)}
          {#if features.length === 0}
            <li data-layer-id={layer.id} class="region-map__feature region-map__feature--empty">
              <strong>{layer.label}:</strong> No geometry available.
            </li>
          {:else}
            {#each features as feature (feature.properties.id)}
              <li
                data-layer-id={layer.id}
                data-feature-id={feature.properties.id}
                class="region-map__feature"
                class:region-map__feature--highlighted={isHighlightedFeature(feature)}
                class:region-map__feature--deemphasized={shouldDeemphasizeFeature(layer, feature)}
              >
                <strong>{layer.label}:</strong>
                {#if getCountyDetailPath(layer, feature.properties.name) !== null}
                  {@const countyDetailPath = getCountyDetailPath(layer, feature.properties.name)}
                  <a href={countyDetailPath}>{feature.properties.name}</a>
                {:else}
                  {feature.properties.name}
                {/if}
              </li>
            {/each}
          {/if}
        {/each}
      </ul>
    {/if}
  {:else}
    <p>No region map data available.</p>
  {/if}
</section>

<style>
  .region-map {
    display: grid;
    gap: 1rem;
  }

  .region-map__svg {
    width: 100%;
    height: auto;
    background: #f4f8fc;
    border: 1px solid #c6d7e7;
    border-radius: 0.6rem;
  }

  .region-map__region {
    fill: #2b6ea8;
    stroke: #ffffff;
    stroke-width: 0.75;
  }

  .region-map__region--disabled {
    fill: #c6d7e7;
  }

  .region-map__states {
    list-style: none;
    padding: 0;
    margin: 0;
    display: grid;
    gap: 0.35rem;
    grid-template-columns: repeat(auto-fit, minmax(15rem, 1fr));
  }

  .region-map__state {
    padding: 0.35rem 0.6rem;
    border-radius: 0.4rem;
    background: #ffffff;
    border: 1px solid #c6d7e7;
    display: grid;
    gap: 0.2rem;
  }

  .region-map__link {
    color: #0f4f79;
    font-weight: 600;
    text-decoration: none;
  }

  .region-map__disabled {
    color: #5a6e7f;
  }

  .region-map__warning {
    font-size: 0.85rem;
    color: #714400;
  }

  .region-map__feature-list {
    margin: 0;
    padding-left: 1.2rem;
  }

  .region-map__feature + .region-map__feature {
    margin-top: 0.35rem;
  }

  .region-map__feature--empty {
    color: #44515e;
  }

  .region-map__feature--highlighted {
    background: #edf6ff;
    border-left: 0.3rem solid #0f4f79;
    padding-left: 0.4rem;
  }

  .region-map__feature--deemphasized {
    opacity: 0.6;
  }

  @media (max-width: 36rem) {
    .region-map__states {
      grid-template-columns: 1fr;
    }
  }
</style>
