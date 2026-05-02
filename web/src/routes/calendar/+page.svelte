<script lang="ts">
  import { env } from "$env/dynamic/public";
  import { page } from "$app/stores";
  import { APP_SHELL } from "$lib/config/app";
  import SeoHead from "$lib/seo/SeoHead.svelte";
  import { buildSeoHeadModel } from "$lib/seo/head";
  import type { PageData } from "./$types";

  export let data: PageData;

  const routeMetadata = APP_SHELL.staticRoutes.calendar;

  $: headModel = buildSeoHeadModel({
    metadata: routeMetadata,
    ogType: "website",
    pageUrl: $page.url,
    publicOrigin: env.PUBLIC_ORIGIN
  });
</script>

<SeoHead {headModel} />

<section class="card" aria-label="Upcoming election calendar">
  <h2>Election calendar</h2>

  {#if data.timelineEntries.length === 0}
    <p>No upcoming elections found.</p>
  {:else}
    {#each data.timelineEntries as entry (entry.date)}
      <h3>{entry.date}</h3>
      <ul>
        {#each entry.contests as contest (contest.contest_id)}
          <li>{contest.name}</li>
        {/each}
      </ul>
    {/each}
  {/if}
</section>
