<script lang="ts">
  import { env } from "$env/dynamic/public";
  import { page } from "$app/stores";
  import { APP_SHELL } from "$lib/config/app";
  import SeoHead from "$lib/seo/SeoHead.svelte";
  import { buildSeoHeadModel } from "$lib/seo/head";
  import { buildMethodologyJsonLd } from "$lib/seo/jsonld";

  const routeMetadata = APP_SHELL.staticRoutes.methodology;

  $: headModel = buildSeoHeadModel({
    metadata: routeMetadata,
    ogType: "article",
    pageUrl: $page.url,
    publicOrigin: env.PUBLIC_ORIGIN
  });
  $: methodologyJsonLd = buildMethodologyJsonLd({
    pageUrl: $page.url,
    publicOrigin: env.PUBLIC_ORIGIN,
    description: routeMetadata.description
  });
</script>

<SeoHead {headModel} jsonLd={methodologyJsonLd} />

<section class="card methodology" aria-label="Methodology">
  <h2>{APP_SHELL.methodology.heading}</h2>
  <p>{APP_SHELL.methodology.coverageSummary}</p>

  {#each APP_SHELL.methodology.sections as section}
    <h3>{section.heading}</h3>
    <p>{section.body}</p>
  {/each}

  <h3>{APP_SHELL.methodology.confidenceHeading}</h3>
  <ul class="methodology__confidence-labels">
    {#each APP_SHELL.methodology.confidenceLabels as confidenceLabel}
      <li>
        <strong>{confidenceLabel.label}</strong>: {confidenceLabel.description}
      </li>
    {/each}
  </ul>

  <p>
    <a href={APP_SHELL.reportingLink.href}>{APP_SHELL.reportingLink.label}</a>
  </p>
</section>

<style>
  .methodology h3 {
    margin: 1.1rem 0 0.45rem;
  }

  .methodology__confidence-labels {
    margin: 0;
    padding-left: 1.2rem;
  }
</style>
