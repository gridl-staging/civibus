<script lang="ts">
  import TrustSection from "$lib/detail-trust/TrustSection.svelte";
  import {
    buildPropertyDetailPresentation,
    type PropertyDetailPresentation
  } from "$lib/property-detail/presentation";
  import type { ParcelDetailResponse } from "$lib/property-detail/contract";

  export let data: ParcelDetailResponse;

  let viewModel: PropertyDetailPresentation;
  $: viewModel = buildPropertyDetailPresentation(data);
</script>

<section class="card detail" aria-label="Property detail">
  <header class="detail__header">
    <h2>{viewModel.title}</h2>
    <p class="detail__type">property</p>
  </header>

  {#each viewModel.sectionOrder as sectionKey (sectionKey)}
    {#if sectionKey === "summary"}
      <section class="detail__panel">
        <h3>Parcel facts</h3>
        <dl class="detail__rows">
          {#each viewModel.factRows as row (row.label)}
            <div class="detail__row">
              <dt>{row.label}</dt>
              <dd>{row.value}</dd>
            </div>
          {/each}
        </dl>
      </section>
    {:else if sectionKey === "trust"}
      <TrustSection trustSection={viewModel.trustSection} />
    {:else if sectionKey === "metrics"}
      <section class="detail__panel">
        <h3>Key metrics</h3>
        <dl class="detail__rows">
          {#each viewModel.keyMetricRows as row (row.label)}
            <div class="detail__row">
              <dt>{row.label}</dt>
              <dd>{row.value}</dd>
            </div>
          {/each}
        </dl>
      </section>
    {:else if sectionKey === "records"}
      <section class="detail__panel">
        <h3>Ownership history</h3>
        {#if viewModel.ownershipRows.length === 0}
          <p>{viewModel.ownershipEmptyMessage}</p>
        {:else}
          <ul class="detail__list">
            {#each viewModel.ownershipRows as row (row.id)}
              <li>
                <p>owner: {row.ownerName}</p>
                <p>recorded at: {row.ownershipRecordedAt}</p>
                <p>valid period: {row.validPeriod}</p>
                <p>date precision: {row.datePrecision}</p>
                <p>mailing address: {row.mailingAddress}</p>
                {#if row.ownerPersonHref}
                  <p><a href={row.ownerPersonHref}>linked person</a></p>
                {/if}
                {#if row.ownerOrganizationHref}
                  <p><a href={row.ownerOrganizationHref}>linked organization</a></p>
                {/if}
              </li>
            {/each}
          </ul>
        {/if}
      </section>

      <section class="detail__panel">
        <h3>Assessment history</h3>
        {#if viewModel.assessmentRows.length === 0}
          <p>{viewModel.assessmentEmptyMessage}</p>
        {:else}
          <ul class="detail__list">
            {#each viewModel.assessmentRows as row (row.id)}
              <li>
                <p>tax year: {row.taxYear}</p>
                <p>land assessed value: {row.landAssessedValue}</p>
                <p>improvement assessed value: {row.improvementAssessedValue}</p>
                <p>total assessed value: {row.totalAssessedValue}</p>
                <p>assessed at: {row.assessedAt}</p>
                <p>heated area: {row.heatedArea}</p>
                <p>exemption: {row.exemptionDescription}</p>
              </li>
            {/each}
          </ul>
        {/if}
      </section>
    {:else if sectionKey === "caveats"}
      <section class="detail__panel" aria-label="Parcel geometry placeholder">
        <h3>Map and geometry</h3>
        <p>{viewModel.geometryPlaceholderMessage}</p>
      </section>
    {/if}
  {/each}
</section>
