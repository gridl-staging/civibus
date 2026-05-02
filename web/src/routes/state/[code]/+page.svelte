<script lang="ts">
  import TrustSection from "$lib/detail-trust/TrustSection.svelte";
  import { buildTrustSection } from "$lib/detail-trust/presentation";
  import { APP_SHELL } from "$lib/config/app";
  import type { MapLayerVisibility } from "$lib/config/app";
  import LayerToggle, { type LayerToggleChangeDetail } from "$lib/region-map/LayerToggle.svelte";
  import RegionMap from "$lib/region-map/RegionMap.svelte";
  import type { StateSupportStatus } from "$lib/server/api/state-pages-contract";
  import type { PageData } from "./$types";

  export let data: PageData;
  let layerVisibility: MapLayerVisibility = { ...data.layerVisibilityDefaults };

  const currencyFormatter = new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  });

  function formatMoney(value: string | null): string {
    if (value === null) {
      return "No data available";
    }

    const parsed = Number(value);
    if (!Number.isFinite(parsed)) {
      return "No data available";
    }

    return currencyFormatter.format(parsed);
  }

  function formatCount(value: number | null): string {
    return value === null ? "No data available" : String(value);
  }

  function supportStatusLabel(supportStatus: StateSupportStatus): string {
    if (supportStatus === "warning") {
      return "Incomplete";
    }

    return supportStatus === "supported" ? "Supported" : "Unsupported";
  }

  function handleLayerToggle(event: CustomEvent<LayerToggleChangeDetail>): void {
    const { layerId, visible } = event.detail;
    layerVisibility = {
      ...layerVisibility,
      [layerId]: visible
    };
  }

  $: stateName = data.geometry.features.find(
    (feature) => feature.properties.state === data.stateDetail.state_code
  )?.properties.name ?? data.stateDetail.state_code;
  $: hasTotalsData =
    data.stateDetail.total_raised !== null &&
    data.stateDetail.total_spent !== null &&
    data.stateDetail.net !== null;
  $: hasAnyData = hasTotalsData || data.stateDetail.transaction_count > 0;
  $: supportLabel = supportStatusLabel(data.stateDetail.support_status);
  $: trustSection = buildTrustSection(data.stateDetail.sources ?? []);
</script>

<section class="card state-detail" aria-label={`State detail for ${stateName}`}>
  <h2>{stateName} campaign finance</h2>
  <p>
    Coverage status: <strong>{supportLabel}</strong>
  </p>

  {#if data.stateDetail.support_status === "unsupported"}
    <p class="state-detail__warning" role="status">
      Coverage is not currently supported for this state.
    </p>
  {/if}

  {#if data.stateDetail.warning_text}
    <p class="state-detail__warning" role="status">{data.stateDetail.warning_text}</p>
  {/if}

  {#if !hasAnyData}
    <p class="state-detail__warning" role="status">No data available for this state.</p>
  {/if}

  <RegionMap
    geometry={data.geometry}
    stateSummaries={data.stateSummaries}
    title={`${stateName} in national campaign-finance coverage`}
    unsupportedLabel={APP_SHELL.landing.mapUnsupportedLabel}
  />

  <section class="detail__panel state-detail__map-drilldown">
    <h3>{data.stateCode} map overview</h3>
    <p class="state-detail__map-summary">
      Shared statewide geometry layers for county drilldown and district context.
    </p>

    <LayerToggle pageLevel={data.pageLevel} {layerVisibility} on:change={handleLayerToggle} />
    <RegionMap
      pageLevel={data.pageLevel}
      stateCode={data.stateCode}
      {layerVisibility}
      geometryByLevel={data.geometryByLevel}
    />
  </section>

  <section class="detail__panel">
    <h3>Key metrics</h3>
    <dl class="state-detail__metrics">
      <div>
        <dt>Total raised</dt>
        <dd>{formatMoney(data.stateDetail.total_raised)}</dd>
      </div>
      <div>
        <dt>Total spent</dt>
        <dd>{formatMoney(data.stateDetail.total_spent)}</dd>
      </div>
      <div>
        <dt>Net</dt>
        <dd>{formatMoney(data.stateDetail.net)}</dd>
      </div>
      <div>
        <dt>Transactions</dt>
        <dd>{formatCount(data.stateDetail.transaction_count)}</dd>
      </div>
      <div>
        <dt>Committees</dt>
        <dd>{formatCount(data.stateDetail.committee_count)}</dd>
      </div>
    </dl>
  </section>

  <section class="detail__panel" data-testid="top-candidates-panel">
    <h3>Top candidates</h3>
    {#if data.stateDetail.top_candidates.length > 0}
      <ol class="state-detail__ranked-list">
        {#each data.stateDetail.top_candidates as candidate, index (candidate.candidate_id)}
          <li class="state-detail__ranked-row" data-testid={`top-candidate-row-${index}`}>
            <span>{candidate.candidate_name}</span>
            <strong>{formatMoney(candidate.total_raised)}</strong>
          </li>
        {/each}
      </ol>
    {:else}
      <p>No top candidates available.</p>
    {/if}
  </section>

  <section class="detail__panel" data-testid="top-committees-panel">
    <h3>Top committees</h3>
    {#if data.stateDetail.top_committees.length > 0}
      <ol class="state-detail__ranked-list">
        {#each data.stateDetail.top_committees as committee, index (committee.committee_id)}
          <li class="state-detail__ranked-row" data-testid={`top-committee-row-${index}`}>
            <span>{committee.committee_name}</span>
            <strong>{formatMoney(committee.total_raised)}</strong>
          </li>
        {/each}
      </ol>
    {:else}
      <p>No top committees available.</p>
    {/if}
  </section>

  <section class="detail__panel" data-testid="top-ie-spenders-panel">
    <h3>Top independent expenditure spenders</h3>
    {#if data.stateDetail.top_ie_spenders.length > 0}
      <ol class="state-detail__ranked-list">
        {#each data.stateDetail.top_ie_spenders as committee, index (committee.committee_id)}
          <li class="state-detail__ranked-row" data-testid={`top-ie-spender-row-${index}`}>
            <span>{committee.committee_name}</span>
            <strong>{formatMoney(committee.total_amount)}</strong>
          </li>
        {/each}
      </ol>
    {:else}
      <p>No top independent expenditure spenders available.</p>
    {/if}
  </section>

  {#if trustSection.rows.length > 0}
    <TrustSection {trustSection} />
  {/if}
</section>

<style>
  .state-detail__warning {
    color: #714400;
  }

  .state-detail__metrics {
    display: grid;
    gap: 0.75rem;
    grid-template-columns: repeat(auto-fit, minmax(10rem, 1fr));
    margin: 0;
  }

  .state-detail__metrics dt {
    font-weight: 600;
  }

  .state-detail__metrics dd {
    margin: 0.25rem 0 0;
  }

  .state-detail__map-summary {
    margin-top: 0;
    color: #44515e;
  }

  .state-detail__ranked-list {
    margin: 0;
    padding-left: 1.25rem;
    display: grid;
    gap: 0.5rem;
  }

  .state-detail__ranked-row {
    display: flex;
    justify-content: space-between;
    gap: 1rem;
  }
</style>
