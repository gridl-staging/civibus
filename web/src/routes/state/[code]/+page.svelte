<script lang="ts">
  import { env } from "$env/dynamic/public";
  import { page } from "$app/stores";
  import Breadcrumb from "$lib/breadcrumb/Breadcrumb.svelte";
  import { getMapLayersForLevel, type MapLayerVisibility } from "$lib/config/app";
  import LayerToggle, { type LayerToggleChangeDetail } from "$lib/region-map/LayerToggle.svelte";
  import RegionMap from "$lib/region-map/RegionMap.svelte";
  import {
    buildRegionalBreadcrumbs,
    buildRegionalRouteMetadata,
    buildRegionalStateFinancePresentation
  } from "$lib/regional-navigation/presentation";
  import SeoHead from "$lib/seo/SeoHead.svelte";
  import { buildDetailRouteSeo } from "$lib/seo/head";
  import { buildBreadcrumbJsonLd, removeJsonLdContext, type JsonLdObject } from "$lib/seo/jsonld";
  import type { PageData } from "./$types";

  export let data: PageData;
  let layerVisibility: MapLayerVisibility = { ...data.layerVisibilityDefaults };

  function handleLayerToggle(event: CustomEvent<LayerToggleChangeDetail>): void {
    const { layerId, visible } = event.detail;
    layerVisibility = { ...layerVisibility, [layerId]: visible };
  }

  $: stateName = data.navigationNode.name;
  $: availableLayers = getMapLayersForLevel(data.pageLevel);
  $: hasLayerControls = availableLayers.length > 0;
  $: regionalMetadata = buildRegionalRouteMetadata(data.navigationNode);
  $: regionalSeo = buildDetailRouteSeo({
    metadata: regionalMetadata,
    ogType: "website",
    schemaType: "AdministrativeArea",
    name: stateName,
    pageUrl: $page.url,
    publicOrigin: env.PUBLIC_ORIGIN,
    robots: regionalMetadata.robots
  });
  $: breadcrumbCrumbs = buildRegionalBreadcrumbs(data.navigationNode);
  $: financePresentation = buildRegionalStateFinancePresentation(data.navigationNode);
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

<section class="card state-detail" aria-label={`State detail for ${stateName}`}>
  <h2>{stateName}</h2>
  <p><strong>State</strong> in the United States</p>

  <section class="detail__panel" aria-labelledby="state-finance-status">
    <h3 id="state-finance-status">Campaign finance {data.navigationNode.finance.status}</h3>
    <p role="status">{data.navigationNode.finance.reason}</p>
    <dl>
      <dt>Displayed subject</dt>
      <dd>{data.navigationNode.finance.authority_context.subject.kind}/{data.navigationNode.finance.authority_context.subject.code}</dd>
      <dt>Filing-authority relation</dt>
      <dd>{data.navigationNode.finance.authority_context.relation}</dd>
      <dt>Aggregation disposition</dt>
      <dd>{data.navigationNode.finance.authority_context.aggregation_disposition}</dd>
      <dt>Identity translation</dt>
      <dd>{data.navigationNode.finance.authority_context.translation_status}</dd>
      <dt>Acquisition scope</dt>
      <dd>{data.navigationNode.finance.authority_context.acquisition_scope ?? "Unproved"}</dd>
      <dt>Provenance scope</dt>
      <dd>{data.navigationNode.finance.authority_context.provenance_scope ?? "Unproved"}</dd>
    </dl>
    {#if data.navigationNode.finance.authority_context.filing_authorities.length > 0}
      <h4>Filing authorities</h4>
      <ul>
        {#each data.navigationNode.finance.authority_context.filing_authorities as authority}
          <li>
            <strong>{authority.name}</strong> ({authority.kind}/{authority.code}) — {authority.scope}
            <p>Provenance: {authority.provenance_scope}</p>
          </li>
        {/each}
      </ul>
    {/if}
    {#if data.navigationNode.finance.authority_context.refusal_reasons.length > 0}
      <h4>Authority refusals</h4>
      <ul>
        {#each data.navigationNode.finance.authority_context.refusal_reasons as reason}<li>{reason}</li>{/each}
      </ul>
    {/if}
  </section>

  {#if financePresentation}
    <section class="detail__panel" aria-labelledby="state-money-heading">
      <h3 id="state-money-heading">Authority-scoped reporting window</h3>
      <p>{financePresentation.windowLabel}. Amounts are exact source decimals, not estimates.</p>
      <div class="state-detail__money-grid">
        {#each financePresentation.money as row}
          <article class="state-detail__money-card" aria-label={row.label}>
            <h4>{row.label}</h4>
            <p class="state-detail__amount">{row.amountLabel}</p>
            <p><strong>{row.status}</strong> · {row.transactionLabel}</p>
            <p>
              Transaction data through:
              {#if row.dataThrough.datetime}
                <time datetime={row.dataThrough.datetime}>{row.dataThrough.label}</time>
              {:else}
                {row.dataThrough.label}
              {/if}
            </p>
            <p>{row.reason}</p>
          </article>
        {/each}
      </div>
    </section>

    <section class="detail__panel" aria-labelledby="state-candidates-heading">
      <h3 id="state-candidates-heading">Authority-scoped candidates and civic connections</h3>
      {#if financePresentation.candidates.length > 0}
        <ul class="state-detail__entity-list">
          {#each financePresentation.candidates as candidate}
            <li>
              <h4><a href={candidate.personHref}>{candidate.personName}</a></h4>
              <p>
                <a href={candidate.candidacyHref}>Candidacy</a> for
                <a href={candidate.contestHref}>{candidate.contestName}</a> ·
                <a href={candidate.officeHref}>{candidate.officeName}</a>
              </p>
              {#if candidate.divisionName}<p>Division: {candidate.divisionName}</p>{/if}
              {#if candidate.party}<p>Party: {candidate.party}</p>{/if}
              <p>{candidate.connectionLabel}: {candidate.moneyLabel} · {candidate.transactionLabel}</p>
              {#if candidate.currentOfficeholdingHref}
                <p><a href={candidate.currentOfficeholdingHref}>Current officeholding</a></p>
              {/if}
            </li>
          {/each}
        </ul>
      {:else}
        <p>No current-window candidacy connection is available. Valid authority-scoped money remains visible.</p>
      {/if}
    </section>

    <section class="detail__panel" aria-labelledby="state-committees-heading">
      <h3 id="state-committees-heading">Committees in this bounded activity</h3>
      {#if financePresentation.committees.length > 0}
        <ul class="state-detail__entity-list">
          {#each financePresentation.committees as committee}
            <li>
              <h4><a href={committee.href}>{committee.name}</a></h4>
              <p>{committee.activityLabel} · {committee.transactionLabel}</p>
              <p>
                Data through:
                {#if committee.dataThrough.datetime}
                  <time datetime={committee.dataThrough.datetime}>{committee.dataThrough.label}</time>
                {:else}
                  {committee.dataThrough.label}
                {/if}
              </p>
            </li>
          {/each}
        </ul>
      {:else}
        <p>No committee is present in the bounded activity set.</p>
      {/if}
    </section>

    <section class="detail__panel" aria-labelledby="state-coverage-boundary">
      <h3 id="state-coverage-boundary">Coverage boundary</h3>
      <h4>Included</h4>
      <ul>{#each financePresentation.included as item}<li>{item}</li>{/each}</ul>
      <h4>Excluded</h4>
      <ul>{#each financePresentation.excluded as item}<li>{item}</li>{/each}</ul>
      <p>No authority amount is combined with county, municipality, school-district, special-district, or committee-city proxy totals.</p>
    </section>

    <section class="detail__panel" aria-labelledby="authority-health-heading">
      <h3 id="authority-health-heading">Authority health and promotion gate</h3>
      {#each financePresentation.authorityHealth as health}
        <article>
          <h4>{health.authorityCode}</h4>
          <p>
            Freshness: {health.freshnessStatus} · Recurrence: {health.recurrenceStatus} ·
            Revision parity: {health.revisionParity}
          </p>
          <p>Promotion eligible: {health.promotionEligible ? "yes" : "no"}</p>
          {#if health.degradedSourceNames.length > 0}
            <p>Degraded or unproved sources: {health.degradedSourceNames.join(", ")}</p>
          {/if}
          {#if health.refusalReasons.length > 0}
            <ul>{#each health.refusalReasons as reason}<li>{reason}</li>{/each}</ul>
          {/if}
        </article>
      {/each}
    </section>

    <section class="detail__panel" aria-labelledby="state-source-freshness">
      <h3 id="state-source-freshness">Sources, provenance, and freshness</h3>
      <p>
        Response as of:
        <time datetime={financePresentation.asOf.datetime ?? undefined}>{financePresentation.asOf.label}</time>
      </p>
      <div class="state-detail__source-grid">
        {#each financePresentation.sources as source}
          <article>
            <h4>
              {#if source.href}
                <a href={source.href} target="_blank" rel="noopener nofollow">{source.name}</a>
              {:else}
                {source.name}
              {/if}
            </h4>
            <p>{source.authorityCode} · {source.sourceIdentity}</p>
            <p><strong>{source.status}</strong>: {source.reason}</p>
            <dl>
              <dt>Last successful source pull</dt>
              <dd>{source.lastSuccessfulPull.label}</dd>
              <dt>Latest refresh run</dt>
              <dd>{source.latestRefreshStatus} · {source.latestRefreshExecutionOrigin} · {source.latestRefreshCompletedAt.label}</dd>
              <dt>Recurrence</dt>
              <dd>{source.recurrenceStatus}</dd>
              <dt>Source last verified working</dt>
              <dd>{source.lastVerifiedWorking.label}</dd>
            </dl>
          </article>
        {/each}
      </div>
      <dl>
        <dt>Registry evidence date</dt>
        <dd>{financePresentation.registryEvidenceDate.label}</dd>
        <dt>Lifecycle observation date</dt>
        <dd>{financePresentation.lifecycleRegistryUpdatedAt.label}</dd>
      </dl>
    </section>

    <section class="detail__panel" aria-labelledby="state-named-gaps">
      <h3 id="state-named-gaps">Named gaps and limitations</h3>
      {#if financePresentation.namedGaps.length > 0}
        <ul>{#each financePresentation.namedGaps as gap}<li>{gap}</li>{/each}</ul>
      {:else}
        <p>No additional gap is recorded for this bounded response.</p>
      {/if}
    </section>
  {:else}
    <section class="detail__panel" aria-labelledby="state-product-unavailable">
      <h3 id="state-product-unavailable">State campaign-finance product unavailable</h3>
      <p>This state has no exact authority-scoped finance detail. Federal, parent, or local totals are not substituted.</p>
    </section>
  {/if}

  <section class="detail__panel state-detail__map-drilldown" aria-labelledby="state-map-heading">
    <h3 id="state-map-heading">{data.stateCode} map context</h3>
    <p class="state-detail__map-summary">
      State, county, and congressional district geometry is navigation context and does not imply finance coverage.
    </p>
    {#if hasLayerControls}
      <LayerToggle pageLevel={data.pageLevel} {layerVisibility} on:change={handleLayerToggle} />
    {/if}
    <RegionMap
      pageLevel={data.pageLevel}
      stateCode={data.stateCode}
      {layerVisibility}
      geometryByLevel={data.geometryByLevel}
      featureLinks={data.featureLinks}
    />
  </section>
</section>

<style>
  .detail__panel {
    border: 1px solid var(--border-subtle, #d6dee6);
    border-radius: 0.5rem;
    margin: 1rem 0;
    padding: 0.9rem 1rem;
  }

  .state-detail__money-grid,
  .state-detail__source-grid {
    display: grid;
    gap: 0.8rem;
    grid-template-columns: repeat(auto-fit, minmax(14rem, 1fr));
  }

  .state-detail__money-card,
  .state-detail__source-grid article,
  .state-detail__entity-list li {
    border: 1px solid var(--border-subtle, #d6dee6);
    border-radius: 0.4rem;
    padding: 0.75rem;
  }

  .state-detail__amount {
    font-size: 1.4rem;
    font-weight: 700;
    margin: 0.25rem 0;
  }

  .state-detail__entity-list {
    display: grid;
    gap: 0.75rem;
    list-style: none;
    padding: 0;
  }

  .state-detail dl {
    margin-bottom: 0;
  }

  .state-detail dt {
    font-weight: 700;
    margin-top: 0.5rem;
  }

  .state-detail dd {
    margin-left: 0;
  }

  .state-detail__map-summary {
    color: #44515e;
    margin-top: 0;
  }
</style>
