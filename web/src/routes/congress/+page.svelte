<script lang="ts">
  import { env } from "$env/dynamic/public";
  import { goto } from "$app/navigation";
  import { page } from "$app/stores";
  import ListNavigationLoading from "$lib/campaign-finance-detail/ListNavigationLoading.svelte";
  import {
    buildCongressDirectory,
    type CongressDirectoryFilters
  } from "$lib/civic-detail/congress-directory";
  import { CONGRESS_PAGE_PATH } from "$lib/civic-detail/contract";
  import SkeletonPanel from "$lib/loading/SkeletonPanel.svelte";
  import Portrait from "$lib/portrait/Portrait.svelte";
  import SeoHead from "$lib/seo/SeoHead.svelte";
  import { buildSeoHeadModel } from "$lib/seo/head";
  import type { PageData } from "./$types";

  export let data: PageData;

  const CONGRESS_TITLE = "Congress | Civibus";
  const CONGRESS_DESCRIPTION = "Browse current federal officeholders by name, chamber, state or territory, and party.";

  $: headModel = buildSeoHeadModel({
    metadata: {
      title: CONGRESS_TITLE,
      description: CONGRESS_DESCRIPTION
    },
    ogType: "website",
    pageUrl: $page.url,
    publicOrigin: env.PUBLIC_ORIGIN
  });
  $: rawFilters = {
    search: $page.url.searchParams.get("search") ?? "",
    chamber: $page.url.searchParams.get("chamber") ?? "",
    state: $page.url.searchParams.get("state") ?? "",
    party: $page.url.searchParams.get("party") ?? ""
  };
  $: directory = buildCongressDirectory(data.members, rawFilters);
  $: resultCountLabel =
    directory.rows.length === 1 ? "1 member" : `${directory.rows.length} members`;

  function valueFromEvent(event: Event): string {
    return (event.currentTarget as HTMLInputElement | HTMLSelectElement).value;
  }

  function updateFilter(name: keyof CongressDirectoryFilters, value: string): void {
    const nextUrl = new URL($page.url);
    const normalizedValue = name === "search" ? value.trim() : value;
    if (normalizedValue === "") {
      nextUrl.searchParams.delete(name);
    } else {
      nextUrl.searchParams.set(name, normalizedValue);
    }
    void goto(`${CONGRESS_PAGE_PATH}${nextUrl.search}`, { keepFocus: true, noScroll: true });
  }
</script>

<SeoHead {headModel} />

<section class="card congress-directory" aria-label="Congress">
  <header class="congress-directory__header">
    <h2>Congress</h2>
    <p class="congress-directory__count" data-testid="congress-result-count">{resultCountLabel}</p>
  </header>

  <form method="GET" class="congress-directory__filters" aria-label="Congress filters" on:submit|preventDefault>
    <label for="congress-filter-search">Search</label>
    <input
      id="congress-filter-search"
      name="search"
      type="search"
      value={directory.activeFilters.search}
      data-testid="congress-search"
      on:input={(event) => updateFilter("search", valueFromEvent(event))}
    />

    <label for="congress-filter-chamber">Chamber</label>
    <select
      id="congress-filter-chamber"
      name="chamber"
      on:change={(event) => updateFilter("chamber", valueFromEvent(event))}
    >
      <option value="" selected={directory.activeFilters.chamber === ""}>All chambers</option>
      {#each directory.chamberOptions as option}
        <option value={option.value} selected={directory.activeFilters.chamber === option.value}>{option.label}</option>
      {/each}
    </select>

    <label for="congress-filter-state">State</label>
    <select
      id="congress-filter-state"
      name="state"
      on:change={(event) => updateFilter("state", valueFromEvent(event))}
    >
      <option value="" selected={directory.activeFilters.state === ""}>All states and territories</option>
      {#each directory.stateOrTerritoryOptions as option}
        <option value={option.value} selected={directory.activeFilters.state === option.value}>{option.label}</option>
      {/each}
    </select>

    <label for="congress-filter-party">Party</label>
    <select
      id="congress-filter-party"
      name="party"
      on:change={(event) => updateFilter("party", valueFromEvent(event))}
    >
      <option value="" selected={directory.activeFilters.party === ""}>All parties</option>
      {#each directory.partyOptions as option}
        <option value={option.value} selected={directory.activeFilters.party === option.value}>{option.label}</option>
      {/each}
    </select>

    <a href={CONGRESS_PAGE_PATH}>Reset</a>
  </form>

  <ListNavigationLoading routePath={CONGRESS_PAGE_PATH} filterParams={["search", "chamber", "state", "party"]} label="Updating results…" let:isFilterNavigation>
    {#if isFilterNavigation}
      <SkeletonPanel label="Congress results loading" lines={4} />
    {:else if data.members.length === 0}
      <p>No Congress members are available right now.</p>
    {:else if directory.rows.length === 0}
      <p>No members match the active filters.</p>
    {:else}
      <ul class="congress-directory__items">
        {#each directory.rows as row, index (row.id)}
          <li class="congress-directory__item" data-testid={`congress-member-row-${index}`}>
            <Portrait canonicalName={row.personName} personId={row.id} portrait={row.portrait} />
            <div class="congress-directory__item-body">
              <h3 class="congress-directory__name">
                <a href={row.personHref}>{row.personName}</a>
              </h3>
              <p class="congress-directory__context">{row.contextLine}</p>
            </div>
          </li>
        {/each}
      </ul>
    {/if}
  </ListNavigationLoading>
</section>

<style>
  .congress-directory__header {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    justify-content: space-between;
    gap: 0.75rem;
  }

  .congress-directory__header h2,
  .congress-directory__count {
    margin: 0;
  }

  .congress-directory__filters {
    margin: 1rem 0;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem;
  }

  .congress-directory__filters input,
  .congress-directory__filters select {
    max-width: 100%;
  }

  .congress-directory__items {
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .congress-directory__item {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    min-width: 0;
  }

  .congress-directory__item + .congress-directory__item {
    margin-top: 0.75rem;
  }

  .congress-directory__item-body {
    min-width: 0;
  }

  .congress-directory__name {
    margin: 0;
    font-size: 1.05rem;
  }

  .congress-directory__context {
    margin: 0.2rem 0 0;
    color: var(--text-secondary, #44515e);
    font-size: 0.95rem;
  }
</style>
