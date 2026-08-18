<script lang="ts">
  import { env } from "$env/dynamic/public";
  import { page } from "$app/stores";
  import { APP_SHELL } from "$lib/config/app";
  import { buildElectionCalendarPresentation } from "$lib/civic-detail/presentation";
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

  // Linking, ordering, and labelling live in the shared civic presentation
  // owner, which /election/[date] also uses — the two surfaces must not be able
  // to describe the same contest differently.
  $: calendarEntries = buildElectionCalendarPresentation(data.timelineEntries);
</script>

<SeoHead {headModel} />

<section class="card" aria-label="Upcoming election calendar">
  <h2>Election calendar</h2>

  {#if calendarEntries.length === 0}
    <p>No upcoming elections found.</p>
  {:else}
    <!--
      This page is the top of the race discovery chain: it sits in the shell
      navigation and in the sitemap's static shard. It used to render every
      contest as bare text, so no race page was reachable from navigation at
      all. Every date and every contest here is a link.
    -->
    {#each calendarEntries as entry (entry.date)}
      <section class="calendar-date">
        <h3><a href={entry.dateHref}>{entry.date}</a></h3>
        <p class="calendar-date__count">{entry.contestCountLabel}</p>
        {#if entry.emptyMessage}
          <p class="calendar-date__empty">{entry.emptyMessage}</p>
        {:else}
          <ul class="calendar-date__list">
            {#each entry.rows as row (row.contestId)}
              <li class="calendar-row">
                <a href={row.contestHref} aria-label={row.linkAriaLabel}>{row.contestName}</a>
                <p class="calendar-row__context">{row.contextLine}</p>
              </li>
            {/each}
          </ul>
        {/if}
      </section>
    {/each}
  {/if}
</section>

<style>
  .calendar-date {
    margin-top: 1.5rem;
  }

  .calendar-date__count,
  .calendar-date__empty {
    margin: 0.25rem 0 0.5rem;
    font-size: 0.875rem;
    opacity: 0.75;
  }

  .calendar-date__list {
    list-style: none;
    margin: 0;
    padding: 0;
  }

  .calendar-row {
    padding: 0.5rem 0;
    border-top: 1px solid rgba(128, 128, 128, 0.25);
  }

  .calendar-row__context {
    margin: 0.125rem 0 0;
    font-size: 0.875rem;
    opacity: 0.75;
  }
</style>
