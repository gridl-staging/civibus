<script lang="ts">
  import { env } from "$env/dynamic/public";
  import { page } from "$app/stores";
  import { buildCandidateHref } from "$lib/campaign-finance-detail/contract";
  import SeoHead from "$lib/seo/SeoHead.svelte";
  import { buildSeoHeadModel } from "$lib/seo/head";
  import type { PageData } from "./$types";

  export let data: PageData;

  const CANDIDATES_TITLE = "Candidates | Civibus";
  const CANDIDATES_DESCRIPTION = "Campaign-finance candidates with server-rendered pagination.";

  $: headModel = buildSeoHeadModel({
    metadata: {
      title: CANDIDATES_TITLE,
      description: CANDIDATES_DESCRIPTION
    },
    ogType: "website",
    pageUrl: $page.url,
    publicOrigin: env.PUBLIC_ORIGIN
  });
  $: previousHref = data.offset > 0 ? buildOffsetHref(Math.max(data.offset - data.limit, 0)) : null;
  $: nextHref = data.has_next ? buildOffsetHref(data.offset + data.limit) : null;

  function buildOffsetHref(offset: number): string {
    const searchParams = new URLSearchParams($page.url.searchParams);
    searchParams.set("offset", String(offset));
    searchParams.set("limit", String(data.limit));
    const queryString = searchParams.toString();
    return queryString === "" ? $page.url.pathname : `${$page.url.pathname}?${queryString}`;
  }
</script>

<SeoHead {headModel} />

<section class="card campaign-list" aria-label="Candidates">
  <h2>Candidates</h2>

  {#if data.items.length === 0}
    <p>No candidates found for the selected filters.</p>
  {:else}
    <ul class="campaign-list__items">
      {#each data.items as item (item.id)}
        <li>
          <a href={buildCandidateHref(item)}>{item.name}</a>
        </li>
      {/each}
    </ul>
  {/if}

  <nav class="campaign-list__pagination" aria-label="Candidates pagination">
    {#if previousHref !== null}
      <a href={previousHref}>Previous</a>
    {/if}
    {#if nextHref !== null}
      <a href={nextHref}>Next</a>
    {/if}
  </nav>
</section>

<style>
  .campaign-list__items {
    margin: 0;
    padding-left: 1.2rem;
  }

  .campaign-list__pagination {
    margin-top: 1rem;
    display: flex;
    gap: 1rem;
  }
</style>
