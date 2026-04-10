<script lang="ts">
  import { env } from "$env/dynamic/public";
  import { page } from "$app/stores";
  import { APP_SHELL } from "$lib/config/app";
  import SeoHead from "$lib/seo/SeoHead.svelte";
  import { buildSeoHeadModel } from "$lib/seo/head";
  import { buildHomepageJsonLd } from "$lib/seo/jsonld";

  const routeMetadata = APP_SHELL.staticRoutes.home;

  $: headModel = buildSeoHeadModel({
    metadata: routeMetadata,
    ogType: "website",
    pageUrl: $page.url,
    publicOrigin: env.PUBLIC_ORIGIN
  });
  $: homepageJsonLd = buildHomepageJsonLd({
    pageUrl: $page.url,
    publicOrigin: env.PUBLIC_ORIGIN,
    description: routeMetadata.description
  });
</script>

<SeoHead {headModel} jsonLd={homepageJsonLd} />

<section class="card landing" aria-label="Civibus landing">
  <p class="landing__eyebrow">{APP_SHELL.landing.eyebrow}</p>
  <h2>{APP_SHELL.landing.heading}</h2>
  <p>{APP_SHELL.landing.body}</p>

  <h3>Take action</h3>
  <div class="landing__actions">
    <article class="landing__action-card">
      <h4>{APP_SHELL.landing.cta.label}</h4>
      <p>{APP_SHELL.landing.cta.description}</p>
      <p>
        <a class="landing__cta" href={APP_SHELL.landing.cta.href}>{APP_SHELL.landing.cta.label}</a>
      </p>
    </article>
    {#each APP_SHELL.landing.actions as action}
      <article class="landing__action-card">
        <h4>{action.label}</h4>
        <p>{action.description}</p>
        <p>
          <a class="landing__action-link" href={action.href}>{action.label}</a>
        </p>
      </article>
    {/each}
  </div>

  <h3>{APP_SHELL.landing.coverageHeading}</h3>
  <p>{APP_SHELL.landing.coverageSummary}</p>
</section>

<style>
  .landing__eyebrow {
    margin: 0;
    font-size: 0.85rem;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: #285273;
  }

  .landing h2 {
    margin-top: 0.4rem;
  }

  .landing h3 {
    margin: 1.25rem 0 0.5rem;
  }

  .landing__actions {
    display: grid;
    gap: 0.75rem;
    grid-template-columns: repeat(auto-fit, minmax(14rem, 1fr));
  }

  .landing__action-card {
    border: 1px solid #c6d7e7;
    border-radius: 0.6rem;
    background: #ffffff;
    padding: 0.7rem 0.8rem;
  }

  .landing__action-card h4 {
    margin: 0;
  }

  .landing__action-card p {
    margin: 0.45rem 0 0;
  }

  .landing__cta {
    display: inline-block;
    text-decoration: none;
    border-radius: 0.45rem;
    padding: 0.45rem 0.8rem;
    background: #0f5d8f;
    border: 1px solid #0f5d8f;
    color: #f7fbff;
  }

  .landing__action-link {
    color: #0f4f79;
    font-weight: 600;
  }
</style>
