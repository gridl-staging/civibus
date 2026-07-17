<script lang="ts">
  import { env } from "$env/dynamic/public";
  import { goto } from "$app/navigation";
  import { page } from "$app/stores";
  import ListNavigationLoading from "$lib/campaign-finance-detail/ListNavigationLoading.svelte";
  import ComparisonBar from "$lib/charts/ComparisonBar.svelte";
  import { formatCurrency, formatCurrencyShort } from "$lib/charts/finance";
  import {
    buildCongressCompareHref,
    buildCongressDirectory,
    getCongressMoneyMetric,
    getCongressMoneySourceHref,
    type CongressDirectoryFilters,
    type CongressMemberRow,
    type CongressMoneySort
  } from "$lib/civic-detail/congress-directory";
  import { CONGRESS_PAGE_PATH } from "$lib/civic-detail/contract";
  import SkeletonPanel from "$lib/loading/SkeletonPanel.svelte";
  import SeoHead from "$lib/seo/SeoHead.svelte";
  import { buildSeoHeadModel } from "$lib/seo/head";
  import type { PageData } from "./$types";

  export let data: PageData;

  const CONGRESS_TITLE = "Congress | Civibus";
  const CONGRESS_DESCRIPTION = "Browse current federal officeholders by name, chamber, state or territory, and party.";
  const MONEY_SORT_OPTIONS: Array<{ value: CongressMoneySort; label: string }> = [
    { value: "total_raised", label: "Total raised" },
    { value: "outside_against", label: "Most spent to defeat them (outside against)" },
    { value: "outside_support", label: "Outside support" },
    { value: "cash_on_hand", label: "Cash on hand" }
  ];
  const MONEY_COLUMNS: Array<{
    label: string;
    value: (row: CongressMemberRow) => string | null;
  }> = [
    { label: "Total raised", value: (row) => row.totalRaised },
    { label: "Outside support", value: (row) => row.outsideSupport },
    { label: "Outside against", value: (row) => row.outsideAgainst },
    { label: "Cash on hand", value: (row) => row.cashOnHand }
  ];

  let selectedPersonIds: string[] = [];

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
  $: directory = buildCongressDirectory(
    data.members,
    rawFilters,
    data.moneySummaries,
    $page.url.searchParams.get("sort") ?? ""
  );
  $: resultCountLabel =
    directory.rows.length === 1 ? "1 member" : `${directory.rows.length} members`;
  $: activeMetricMaximum = Math.max(
    0,
    ...directory.rows
      .map((row) => getCongressMoneyMetric(row, directory.activeSort))
      .filter((value): value is number => value !== null)
  );
  $: compareHref = buildCongressCompareHref(selectedPersonIds);

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

  function updateSort(value: string): void {
    const nextUrl = new URL($page.url);
    if (value === "total_raised") {
      nextUrl.searchParams.delete("sort");
    } else {
      nextUrl.searchParams.set("sort", value);
    }
    void goto(`${CONGRESS_PAGE_PATH}${nextUrl.search}`, { keepFocus: true, noScroll: true });
  }

  function updateSelectedPerson(personId: string, selected: boolean): void {
    const nextSelectedIds = new Set(selectedPersonIds);
    if (selected) {
      nextSelectedIds.add(personId);
    } else {
      nextSelectedIds.delete(personId);
    }
    selectedPersonIds = [...nextSelectedIds];
  }

  function selectPersonFromEvent(personId: string, event: Event): void {
    updateSelectedPerson(personId, (event.currentTarget as HTMLInputElement).checked);
  }

  function navigateToComparison(): void {
    if (compareHref !== null) {
      void goto(compareHref);
    }
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

    <label for="congress-money-sort">Sort money by</label>
    <select
      id="congress-money-sort"
      name="sort"
      data-testid="congress-money-sort"
      on:change={(event) => updateSort(valueFromEvent(event))}
    >
      {#each MONEY_SORT_OPTIONS as option}
        <option value={option.value} selected={directory.activeSort === option.value}>{option.label}</option>
      {/each}
    </select>

    <a href={CONGRESS_PAGE_PATH}>Reset</a>
  </form>

  <ListNavigationLoading routePath={CONGRESS_PAGE_PATH} filterParams={["search", "chamber", "state", "party", "sort"]} label="Updating results…" let:isFilterNavigation>
    {#if isFilterNavigation}
      <SkeletonPanel label="Congress results loading" lines={4} />
    {:else if data.members.length === 0}
      <p>No Congress members are available right now.</p>
    {:else if directory.rows.length === 0}
      <p>No members match the active filters.</p>
    {:else}
      <div class="congress-directory__compare-control">
        <button type="button" disabled={compareHref === null} on:click={navigateToComparison}>
          Compare selected (2–4)
        </button>
      </div>
      <ul class="congress-directory__items">
        {#each directory.rows as row, index (row.id)}
          {@const activeMetric = getCongressMoneyMetric(row, directory.activeSort)}
          {@const moneySourceHref = getCongressMoneySourceHref(row)}
          <li class="congress-directory__item" data-testid={`congress-member-row-${index}`}>
            <div class="congress-directory__selection">
              <input
                id={`congress-compare-${row.id}`}
                type="checkbox"
                checked={selectedPersonIds.includes(row.id)}
                aria-label={`Select ${row.personName} for comparison`}
                on:change={(event) => selectPersonFromEvent(row.id, event)}
              />
            </div>
            <div class="congress-directory__item-content">
              <ComparisonBar
                entities={[{
                  id: row.id,
                  label: row.personName,
                  portrait: row.portrait,
                  href: row.personHref,
                  linkTestId: "congress-member-profile-link",
                  value: activeMetric,
                  valueLabel: activeMetric === null ? "" : formatCurrencyShort(activeMetric)
                }]}
                scaleMax={activeMetricMaximum}
              />
              <p class="congress-directory__context">{row.contextLine}</p>

              {#if row.hasFecMoney}
                <dl class="congress-directory__money" aria-label={`Money summary for ${row.personName}`}>
                  {#each MONEY_COLUMNS as column}
                    {@const value = column.value(row)}
                    <div class="congress-directory__money-cell">
                      <dt>{column.label}</dt>
                      <dd>
                        {#if value === null}
                          <span class="congress-directory__money-missing">Not reported/loaded</span>
                        {:else if moneySourceHref !== null}
                          <a href={moneySourceHref} target="_blank" rel="noreferrer">{formatCurrency(Number(value))}</a>
                        {:else}
                          <span>{formatCurrency(Number(value))}</span>
                          <span class="congress-directory__source-unavailable">Source link unavailable</span>
                        {/if}
                      </dd>
                    </div>
                  {/each}
                </dl>
              {/if}
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
    align-items: start;
    border-top: 1px solid #d8dee5;
    display: grid;
    gap: 0.5rem;
    grid-template-columns: max-content minmax(0, 1fr);
    min-width: 0;
    padding: 1rem 0;
  }

  .congress-directory__compare-control {
    display: flex;
    justify-content: flex-end;
    margin-bottom: 0.5rem;
  }

  .congress-directory__selection {
    padding-top: 0.7rem;
  }

  .congress-directory__selection input {
    height: 1.1rem;
    width: 1.1rem;
  }

  .congress-directory__item-content {
    min-width: 0;
  }

  .congress-directory__context {
    margin: 0.35rem 0 0;
    color: var(--text-secondary, #44515e);
    font-size: 0.95rem;
  }

  .congress-directory__money {
    display: grid;
    gap: 0.75rem;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    margin: 0.9rem 0 0;
  }

  .congress-directory__money-cell {
    min-width: 0;
  }

  .congress-directory__money-cell dt {
    color: var(--text-secondary, #44515e);
    font-size: 0.8rem;
  }

  .congress-directory__money-cell dd {
    margin: 0.15rem 0 0;
  }

  .congress-directory__money-cell a,
  .congress-directory__money-cell dd > span:first-child {
    font-variant-numeric: tabular-nums;
    font-weight: 650;
  }

  .congress-directory__source-unavailable,
  .congress-directory__money-missing {
    color: var(--text-secondary, #44515e);
    display: block;
    font-size: 0.8rem;
    font-weight: 400;
  }

  @media (max-width: 48rem) {
    .congress-directory__money {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
  }

  @media (max-width: 30rem) {
    .congress-directory__money {
      grid-template-columns: minmax(0, 1fr);
    }
  }
</style>
