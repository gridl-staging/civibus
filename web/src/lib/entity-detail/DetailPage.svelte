<script lang="ts">
  import TrustSection from "$lib/detail-trust/TrustSection.svelte";
  import GraphViewer from "$lib/graph/GraphViewer.svelte";
  import { buildGraphElements } from "$lib/graph/transform";
  import SkeletonPanel from "$lib/loading/SkeletonPanel.svelte";
  import {
    buildCivicRecordSection,
    buildEntityDetailShellPresentation,
    buildTechnicalDisclosureSection,
    type EntityDetailShellPresentation
  } from "$lib/entity-detail/presentation";
  import type { EntityDetailBundle } from "$lib/server/api/entity-detail";

  export let data: EntityDetailBundle;

  let shellViewModel: EntityDetailShellPresentation;
  $: shellViewModel = buildEntityDetailShellPresentation({
    entityType: data.entityType,
    detail: data.detail
  });
</script>

<section class="card detail" aria-label="Entity detail">
  <header class="detail__header">
    <h2>{shellViewModel.canonicalName}</h2>
    <p class="detail__type">{shellViewModel.entityType}</p>
  </header>

  {#each shellViewModel.sectionOrder as sectionKey (sectionKey)}
    {#if sectionKey === "summary"}
      <section class="detail__panel">
        <h3>Core attributes</h3>
        <dl class="detail__rows">
          {#each shellViewModel.coreFactRows as row (row.label)}
            <div class="detail__row">
              <dt>{row.label}</dt>
              <dd>{row.value}</dd>
            </div>
          {/each}
        </dl>
      </section>
    {:else if sectionKey === "trust"}
      <TrustSection trustSection={shellViewModel.trustSection} />
    {:else if sectionKey === "metrics"}
      <section class="detail__panel">
        <h3>Key metrics</h3>
        <dl class="detail__rows">
          {#each shellViewModel.keyMetricRows as row (row.label)}
            <div class="detail__row">
              <dt>{row.label}</dt>
              <dd>{row.value}</dd>
            </div>
          {/each}
        </dl>
      </section>
    {:else if sectionKey === "records"}
      <section class="detail__panel">
        <h3>Identifiers</h3>
        {#if shellViewModel.identifierRows.length === 0}
          <p>{shellViewModel.identifierEmptyMessage}</p>
        {:else}
          <dl class="detail__rows">
            {#each shellViewModel.identifierRows as row (row.label)}
              <div class="detail__row">
                <dt>{row.label}</dt>
                <dd>{row.value}</dd>
              </div>
            {/each}
          </dl>
        {/if}
      </section>
    {:else if sectionKey === "civic-record"}
      {#await data.relationships}
        <SkeletonPanel label="Civic Record" lines={3} />
      {:then relationships}
        {@const civicRecordSection = buildCivicRecordSection(data.entityType, relationships.neighbors)}
        {#if civicRecordSection}
          <section class="detail__panel">
            <h3>{civicRecordSection.title}</h3>
            {#if civicRecordSection.rows.length === 0}
              <p>{civicRecordSection.emptyMessage}</p>
            {:else}
              <ul class="detail__list">
                {#each civicRecordSection.rows as row (row.recordHref)}
                  <li>
                    <p><a href={row.recordHref}>{row.recordName}</a></p>
                    <p>{row.recordType}</p>
                    {#if row.contextHref !== null && row.contextLabel !== null && row.contextName !== null}
                      <p>{row.contextLabel}: <a href={row.contextHref}>{row.contextName}</a></p>
                    {:else if row.contextLabel !== null && row.contextName !== null}
                      <p>{row.contextLabel}: {row.contextName}</p>
                    {/if}
                  </li>
                {/each}
              </ul>
            {/if}
          </section>
        {/if}
      {:catch}
        <section class="detail__panel">
          <h3>Civic Record</h3>
          <p>Civic record relationships are temporarily unavailable.</p>
        </section>
      {/await}
    {:else if sectionKey === "technical-disclosure"}
      {#await Promise.all([data.matches, data.relationships])}
        <SkeletonPanel label="Entity internals" lines={6} />
      {:then [matches, relationships]}
        {@const technicalDisclosure = buildTechnicalDisclosureSection(matches, relationships.neighbors, data.detail.id)}
        {@const graphElements = buildGraphElements(
          data.entityType,
          data.detail.id,
          data.detail.canonical_name,
          relationships.neighbors
        )}
        <details class="detail__panel" aria-label="Entity internals">
          <summary>{technicalDisclosure.summary}</summary>
          <section class="detail__panel">
            <h3>Entity resolution matches</h3>
            {#if technicalDisclosure.matchRows.length === 0}
              <p>{technicalDisclosure.matchEmptyMessage}</p>
            {:else}
              <ul class="detail__list">
                {#each technicalDisclosure.matchRows as row (row.counterpartEntityId + row.decidedAt)}
                  <li>
                    <p>counterpart: {row.counterpartEntityId}</p>
                    <p>decision: {row.decision}</p>
                    <p>confidence: {row.confidence}</p>
                    <p>decided at: {row.decidedAt}</p>
                  </li>
                {/each}
              </ul>
            {/if}
          </section>

          <section class="detail__panel">
            <h3>Graph relationships</h3>
            {#key `${data.entityType}:${data.detail.id}`}
              <GraphViewer
                elements={graphElements}
                totalCount={relationships.total_count}
                returnedCount={relationships.neighbors.length}
              />
            {/key}
            {#if technicalDisclosure.neighborRows.length === 0}
              <p>{technicalDisclosure.neighborEmptyMessage}</p>
            {:else}
              <ul class="detail__list">
                {#each technicalDisclosure.neighborRows as row (row.entityType + row.title + row.relationshipType + row.direction)}
                  <li>
                    {#if row.href}
                      <p><a href={row.href}>{row.title}</a></p>
                    {:else}
                      <p class="detail__metadata-only">{row.title}</p>
                    {/if}
                    <p>entity type: {row.entityType}</p>
                    <p>relationship: {row.relationshipType}</p>
                    <p>direction: {row.direction}</p>
                  </li>
                {/each}
              </ul>
            {/if}
          </section>
        </details>
      {:catch}
        <details class="detail__panel" aria-label="Entity internals">
          <summary>Entity-resolution and graph internals</summary>
          <p>Entity internals are temporarily unavailable.</p>
        </details>
      {/await}
    {/if}
  {/each}
</section>
