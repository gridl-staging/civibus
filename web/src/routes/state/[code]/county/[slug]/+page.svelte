<script lang="ts">
  import { env } from "$env/dynamic/public";
  import { page } from "$app/stores";
  import Breadcrumb from "$lib/breadcrumb/Breadcrumb.svelte";
  import type { MapLayerVisibility } from "$lib/config/app";
  import LayerToggle, { type LayerToggleChangeDetail } from "$lib/region-map/LayerToggle.svelte";
  import RegionMap from "$lib/region-map/RegionMap.svelte";
  import {
    buildRegionalBreadcrumbs,
    buildRegionalRouteMetadata
  } from "$lib/regional-navigation/presentation";
  import SeoHead from "$lib/seo/SeoHead.svelte";
  import { buildDetailRouteSeo } from "$lib/seo/head";
  import { buildBreadcrumbJsonLd, removeJsonLdContext, type JsonLdObject } from "$lib/seo/jsonld";
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

  $: regionalMetadata = buildRegionalRouteMetadata(data.navigationNode);
  $: regionalSeo = buildDetailRouteSeo({
    metadata: regionalMetadata,
    ogType: "website",
    schemaType: "AdministrativeArea",
    name: data.countyName,
    pageUrl: $page.url,
    publicOrigin: env.PUBLIC_ORIGIN,
    robots: regionalMetadata.robots
  });
  $: breadcrumbCrumbs = buildRegionalBreadcrumbs(data.navigationNode);
  $: regionalJsonLd = {
    "@context": "https://schema.org",
    "@graph": [
      removeJsonLdContext(regionalSeo.jsonLd),
      buildBreadcrumbJsonLd({ crumbs: breadcrumbCrumbs, publicOrigin: env.PUBLIC_ORIGIN })
    ]
  } as JsonLdObject;
</script>

<SeoHead headModel={regionalSeo.headModel} jsonLd={regionalJsonLd} />
<Breadcrumb crumbs={breadcrumbCrumbs} />

<section class="card county-map-page" aria-label={`County navigation for ${data.countyName}`}>
  <h2>{data.countyName}</h2>
  <p><strong>County</strong> in <a href={`/state/${data.stateCode}`}>{data.navigationNode.state_name}</a></p>

  <section class="county-map-page__panel" aria-labelledby="county-finance-status">
    <h3 id="county-finance-status">Campaign finance unavailable</h3>
    <p>{data.navigationNode.finance.reason}</p>
  </section>

  {#if !data.hasCountyGeometry}
    <p role="status">County boundary geometry is unavailable; this does not change the explicit finance refusal.</p>
  {/if}
  <LayerToggle pageLevel={data.pageLevel} {layerVisibility} on:change={handleLayerToggle} />
  <RegionMap
    pageLevel={data.pageLevel}
    stateCode={data.stateCode}
    {layerVisibility}
    geometryByLevel={data.geometryByLevel}
  />

  {#if data.navigationNode.proxy_analysis}
    <section class="county-map-page__panels" aria-labelledby="county-proxy-heading">
      <article class="county-map-page__panel">
        <h3 id="county-proxy-heading">Ordinary-locality proxy control</h3>
        <p><strong>Committee-city proxy</strong></p>
        <h4>{data.navigationNode.proxy_analysis.label}</h4>
        <p>{data.navigationNode.proxy_analysis.scope_label}</p>
        <p>This proxy excludes {data.navigationNode.proxy_analysis.excludes.join(", ")} and is not combined with state or county-wide totals.</p>
        <p>No aggregate-complete, source-record-backed proxy result is available.</p>
      </article>
    </section>
  {/if}
</section>

<style>
  .county-map-page__panels {
    display: grid;
    gap: 0.8rem;
    margin: 1rem 0;
  }

  .county-map-page__panel {
    border: 1px solid var(--border-subtle, #d6dee6);
    border-radius: 0.5rem;
    margin: 1rem 0;
    padding: 0.8rem 1rem;
  }

  .county-map-page__panel h4 {
    margin-bottom: 0.3rem;
  }

</style>
