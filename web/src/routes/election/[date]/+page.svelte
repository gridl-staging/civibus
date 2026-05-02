<script lang="ts">
  import { env } from "$env/dynamic/public";
  import { page } from "$app/stores";
  import { buildElectionDateRoutePath } from "$lib/civic-detail/contract";
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
</script>

<SeoHead {headModel} jsonLd={electionJsonLd} />

<section class="card" aria-label="Election date overview">
  <h2>Election {data.date}</h2>
  <p><a href={electionPath}>Canonical election route</a></p>
  <p>Total contests: {data.total_contests}</p>
  <p>Total candidacies: {data.total_candidacies}</p>

  {#if data.contests.length === 0}
    <p>No contests found for this date.</p>
  {:else}
    <ul>
      {#each data.contests as contest (contest.contest_id)}
        <li>{contest.name}</li>
      {/each}
    </ul>
  {/if}
</section>
