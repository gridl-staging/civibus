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

  function buildOwnerRecordAriaLabel(recordType: "person" | "organization", ownerName: string): string {
    return `View ${recordType} record for ${ownerName}`;
  }
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
          <div class="detail__table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Owner</th>
                  <th>Recorded at</th>
                  <th>Valid period</th>
                  <th>Date precision</th>
                  <th>Mailing address</th>
                  <th>Linked records</th>
                </tr>
              </thead>
              <tbody>
                {#each viewModel.ownershipRows as row (row.id)}
                  <tr>
                    <td class="detail__table-cell-wrap">{row.ownerName}</td>
                    <td>{row.ownershipRecordedAt}</td>
                    <td class="detail__table-cell-wrap">{row.validPeriod}</td>
                    <td>{row.datePrecision}</td>
                    <td class="detail__table-cell-wrap">{row.mailingAddress}</td>
                    <td class="detail__table-cell-wrap">
                      {#if row.ownerPersonHref || row.ownerOrganizationHref}
                        <div class="detail__inline-links">
                          {#if row.ownerPersonHref}
                            <a
                              href={row.ownerPersonHref}
                              aria-label={buildOwnerRecordAriaLabel("person", row.ownerName)}
                            >
                              View person record
                            </a>
                          {/if}
                          {#if row.ownerOrganizationHref}
                            <a
                              href={row.ownerOrganizationHref}
                              aria-label={buildOwnerRecordAriaLabel("organization", row.ownerName)}
                            >
                              View organization record
                            </a>
                          {/if}
                        </div>
                      {:else}
                        —
                      {/if}
                    </td>
                  </tr>
                {/each}
              </tbody>
            </table>
          </div>
        {/if}
      </section>

      <section class="detail__panel">
        <h3>Assessment history</h3>
        {#if viewModel.assessmentRows.length === 0}
          <p>{viewModel.assessmentEmptyMessage}</p>
        {:else}
          <div class="detail__table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Tax year</th>
                  <th>Land assessed value</th>
                  <th>Improvement assessed value</th>
                  <th>Total assessed value</th>
                  <th>Assessed at</th>
                  <th>Heated area</th>
                  <th>Exemption</th>
                </tr>
              </thead>
              <tbody>
                {#each viewModel.assessmentRows as row (row.id)}
                  <tr>
                    <td>{row.taxYear}</td>
                    <td>{row.landAssessedValue}</td>
                    <td>{row.improvementAssessedValue}</td>
                    <td>{row.totalAssessedValue}</td>
                    <td>{row.assessedAt}</td>
                    <td>{row.heatedArea}</td>
                    <td class="detail__table-cell-wrap">{row.exemptionDescription}</td>
                  </tr>
                {/each}
              </tbody>
            </table>
          </div>
        {/if}
      </section>
    {:else if sectionKey === "caveats"}
      <section class="detail__panel caveat-banner" role="note" aria-label="Parcel geometry placeholder">
        <h3>Map and geometry</h3>
        <p>{viewModel.geometryPlaceholderMessage}</p>
      </section>
    {/if}
  {/each}
</section>
