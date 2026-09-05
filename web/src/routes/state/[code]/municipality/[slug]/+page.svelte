<script lang="ts">
  import { env } from "$env/dynamic/public";
  import { page } from "$app/stores";
  import Breadcrumb from "$lib/breadcrumb/Breadcrumb.svelte";
  import { buildRegionalBreadcrumbs, buildRegionalRouteMetadata } from "$lib/regional-navigation/presentation";
  import SeoHead from "$lib/seo/SeoHead.svelte";
  import { buildDetailRouteSeo } from "$lib/seo/head";
  import { buildBreadcrumbJsonLd, removeJsonLdContext, type JsonLdObject } from "$lib/seo/jsonld";
  import type { PageData } from "./$types";

  export let data: PageData;

  $: authorityContext = data.navigationNode.finance.authority_context;
  $: regionalMetadata = buildRegionalRouteMetadata(data.navigationNode);
  $: regionalSeo = buildDetailRouteSeo({
    metadata: regionalMetadata,
    ogType: "website",
    schemaType: "AdministrativeArea",
    name: data.municipalityName,
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

<section class="card municipality-detail" aria-label={`Municipality navigation for ${data.municipalityName}`}>
  <h2>{data.municipalityName}</h2>
  <p><strong>Municipality</strong> in <a href={`/state/${data.stateCode}`}>{data.navigationNode.state_name}</a></p>

  <section class="municipality-detail__panel" aria-labelledby="municipality-finance-status">
    <h3 id="municipality-finance-status">Campaign finance {data.navigationNode.finance.status}</h3>
    <p role="status">{data.navigationNode.finance.reason}</p>
  </section>

  <section class="municipality-detail__panel" aria-labelledby="municipality-authority">
    <h3 id="municipality-authority">Filing-authority boundary</h3>
    <dl>
      <dt>Displayed subject</dt>
      <dd>{authorityContext.subject.kind}/{authorityContext.subject.code}</dd>
      <dt>Authority relation</dt>
      <dd>{authorityContext.relation}</dd>
      <dt>Aggregation disposition</dt>
      <dd>{authorityContext.aggregation_disposition}</dd>
      <dt>Identity translation</dt>
      <dd>{authorityContext.translation_status}</dd>
    </dl>
    <ul>
      {#each authorityContext.filing_authorities as authority}
        <li>
          <strong>
            {#if authority.official_url}
              <a href={authority.official_url} target="_blank" rel="noopener nofollow">{authority.name}</a>
            {:else}
              {authority.name}
            {/if}
          </strong>
          ({authority.kind}/{authority.code})
          <p>{authority.scope}</p>
          <p>Provenance: {authority.provenance_scope}</p>
        </li>
      {/each}
    </ul>
    {#if authorityContext.refusal_reasons.length > 0}
      <h4>Refusals</h4>
      <ul>{#each authorityContext.refusal_reasons as reason}<li>{reason}</li>{/each}</ul>
    {/if}
    <p>No state, parent, child, or direct-target amount is guessed or combined on this page.</p>
  </section>

  <section class="municipality-detail__panel" aria-labelledby="municipality-authority-health">
    <h3 id="municipality-authority-health">Authority health and promotion refusal</h3>
    {#each data.navigationNode.finance.authority_health as health}
      <article>
        <h4>{health.authority_code}</h4>
        <p>
          Freshness: {health.freshness_status} · Recurrence: {health.recurrence_status} ·
          Revision parity: {health.revision_parity}
        </p>
        <p>Promotion eligible: {health.promotion_eligible ? "yes" : "no"}</p>
        {#if health.refusal_reasons.length > 0}
          <ul>{#each health.refusal_reasons as reason}<li>{reason}</li>{/each}</ul>
        {/if}
      </article>
    {/each}
  </section>
</section>

<style>
  .municipality-detail__panel {
    border: 1px solid var(--border-subtle, #d6dee6);
    border-radius: 0.5rem;
    margin: 1rem 0;
    padding: 0.9rem 1rem;
  }

  .municipality-detail dt {
    font-weight: 700;
    margin-top: 0.5rem;
  }

  .municipality-detail dd {
    margin-left: 0;
  }
</style>
