<script lang="ts">
  import type { MapLayerVisibility } from "$lib/config/app";
  import TrustSection from "$lib/detail-trust/TrustSection.svelte";
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

  function formatUsdFromCents(cents: number): string {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: "USD",
      maximumFractionDigits: 2
    }).format(cents / 100);
  }
</script>

<section class="card county-map-page" aria-label="County campaign finance detail">
  <h2>{data.countyName} County, {data.stateCode}</h2>
  <p class="county-map-page__summary">
    Committee-city proxy outflow totals with county boundary and congressional district overlays.
  </p>

  <LayerToggle pageLevel={data.pageLevel} {layerVisibility} on:change={handleLayerToggle} />

  <RegionMap pageLevel={data.pageLevel} {layerVisibility} geometryByLevel={data.geometryByLevel} />

  <section class="county-map-page__panels" aria-label="County campaign finance summaries">
    <article class="county-map-page__panel">
      <h3>Donor total</h3>
      <p class="county-map-page__value">{formatUsdFromCents(data.donor_total_cents)}</p>
      <p class="county-map-page__meta">{data.transaction_count} qualifying transactions</p>
    </article>

    <article class="county-map-page__panel">
      <h3>Top recipient committees</h3>
      {#if data.top_recipient_committees.length === 0}
        <p>No qualifying recipients for this county proxy mapping.</p>
      {:else}
        <ul>
          {#each data.top_recipient_committees as committee (committee.committee_id)}
            <li>
              <strong>{committee.committee_name}</strong>
              <span> {formatUsdFromCents(committee.donor_total_cents)} ({committee.transaction_count} txns)</span>
            </li>
          {/each}
        </ul>
      {/if}
    </article>

    <article class="county-map-page__panel">
      <h3>Top linked candidates</h3>
      {#if data.top_linked_candidates.length === 0}
        <p>No active linked candidates for this county proxy mapping.</p>
      {:else}
        <ul>
          {#each data.top_linked_candidates as candidate (candidate.candidate_id)}
            <li>
              <strong>{candidate.candidate_name}</strong>
              <span> {formatUsdFromCents(candidate.donor_total_cents)} ({candidate.transaction_count} txns)</span>
            </li>
          {/each}
        </ul>
      {/if}
    </article>
  </section>

  <TrustSection trustSection={data.trustSection} />
</section>

<style>
  .county-map-page__summary {
    margin-top: 0;
    color: var(--text-secondary, #44515e);
  }

  .county-map-page__panels {
    display: grid;
    gap: 0.8rem;
    margin: 1rem 0;
  }

  .county-map-page__panel {
    border: 1px solid var(--border-subtle, #d6dee6);
    border-radius: 0.5rem;
    padding: 0.8rem 1rem;
  }

  .county-map-page__value {
    font-size: 1.2rem;
    font-weight: 700;
    margin: 0.2rem 0;
  }

  .county-map-page__meta {
    margin: 0;
    color: var(--text-secondary, #44515e);
  }
</style>
