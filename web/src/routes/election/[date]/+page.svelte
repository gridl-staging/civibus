<script lang="ts">
  import { env } from "$env/dynamic/public";
  import { page } from "$app/stores";
  import { buildElectionDateRoutePath } from "$lib/civic-detail/contract";
  import { buildElectionIndexPresentation } from "$lib/civic-detail/presentation";
  import SeoHead from "$lib/seo/SeoHead.svelte";
  import { buildSeoHeadModel } from "$lib/seo/head";
  import { buildDetailRouteJsonLd } from "$lib/seo/jsonld";
  import type { PageData } from "./$types";

  export let data: PageData;

  $: routeMetadata = {
    title: `Election ${data.date} | Civibus`,
    description: `Election results and contest overview for ${data.date} across supported jurisdictions.`
  };
  $: canonicalPageUrl = new URL(buildElectionDateRoutePath(data.date), $page.url);
  $: headModel = buildSeoHeadModel({
    metadata: routeMetadata,
    ogType: "website",
    pageUrl: canonicalPageUrl,
    publicOrigin: env.PUBLIC_ORIGIN
  });
  $: electionJsonLd = buildDetailRouteJsonLd({
    pageUrl: canonicalPageUrl,
    publicOrigin: env.PUBLIC_ORIGIN,
    schemaType: "Election",
    name: `Election ${data.date}`,
    description: routeMetadata.description
  });

  $: electionPath = buildElectionDateRoutePath(data.date);
  // All grouping, ordering, linking, and labelling lives in the shared civic
  // presentation owner so it is unit-testable without rendering the route.
  $: index = buildElectionIndexPresentation(data);
</script>

<SeoHead {headModel} jsonLd={electionJsonLd} />

<section class="card" aria-label="Election date overview">
  <h2>Election {data.date}</h2>
  <p><a href={electionPath}>Canonical election route</a></p>
  <p>{index.totalContestsLabel}</p>
  <p>{index.totalCandidaciesLabel}</p>

  {#if index.isEmpty}
    <p>No contests found for this date.</p>
  {:else}
    <!--
      One section per state so a 515-row federal date is scannable. Each row is a
      link: this page is the only race index on the site, so a text-only row is a
      dead end. Screen spec: docs/reference/screen_specs/election_date.md
    -->
    {#each index.groups as group (group.key)}
      <section class="election-group">
        <h3>{group.heading}</h3>
        <p class="election-group__count">{group.contestCountLabel}</p>
        <ul class="election-group__list">
          {#each group.rows as row (row.contestId)}
            <li class="election-row">
              <a href={row.contestHref} aria-label={row.linkAriaLabel}>{row.contestName}</a>
              <p class="election-row__context">{row.contextLine}</p>
            </li>
          {/each}
        </ul>
      </section>
    {/each}
  {/if}
</section>

<style>
  .election-group {
    margin-top: 1.5rem;
  }

  .election-group__count {
    margin: 0.25rem 0 0.5rem;
    font-size: 0.875rem;
    opacity: 0.75;
  }

  .election-group__list {
    list-style: none;
    margin: 0;
    padding: 0;
  }

  .election-row {
    padding: 0.5rem 0;
    border-top: 1px solid rgba(128, 128, 128, 0.25);
  }

  .election-row__context {
    margin: 0.125rem 0 0;
    font-size: 0.875rem;
    opacity: 0.75;
  }
</style>
