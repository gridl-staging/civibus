<script lang="ts">
  import { env } from "$env/dynamic/public";
  import { page } from "$app/stores";
  import { COMMITTEES_PAGE_PATH, buildCommitteesPagePath } from "$lib/campaign-finance-detail/contract";
  import ListNavigationLoading from "$lib/campaign-finance-detail/ListNavigationLoading.svelte";
  import { COMMITTEE_TYPE_OPTIONS, US_STATE_OPTIONS } from "$lib/campaign-finance-detail/filter-options";
  import {
    buildCommitteeListItemPresentation,
    buildPaginationContext
  } from "$lib/campaign-finance-detail/list-presentation";
  import SkeletonPanel from "$lib/loading/SkeletonPanel.svelte";
  import SeoHead from "$lib/seo/SeoHead.svelte";
  import { buildSeoHeadModel } from "$lib/seo/head";
  import type { PageData } from "./$types";

  export let data: PageData;

  const COMMITTEES_TITLE = "Committees | Civibus";
  const COMMITTEES_DESCRIPTION = "Campaign-finance committees with server-rendered pagination.";

  $: headModel = buildSeoHeadModel({
    metadata: {
      title: COMMITTEES_TITLE,
      description: COMMITTEES_DESCRIPTION
    },
    ogType: "website",
    pageUrl: $page.url,
    publicOrigin: env.PUBLIC_ORIGIN
  });
  $: committeeItems = data.items.map((item) => ({
    item,
    presentation: buildCommitteeListItemPresentation(item)
  }));
  $: activeState = $page.url.searchParams.get("state") ?? "";
  $: activeCommitteeType = $page.url.searchParams.get("committee_type") ?? "";
  $: paginationContext = buildPaginationContext(data.offset, data.limit, data.has_next, data.items.length);
  $: previousHref = paginationContext.hasPrevious
    ? buildCommitteesPagePath({
        state: activeState,
        committee_type: activeCommitteeType,
        offset: Math.max(data.offset - data.limit, 0),
        limit: data.limit
      })
    : null;
  $: nextHref = paginationContext.hasNext
    ? buildCommitteesPagePath({
        state: activeState,
        committee_type: activeCommitteeType,
        offset: data.offset + data.limit,
        limit: data.limit
      })
    : null;
  $: clearFiltersHref = buildCommitteesPagePath({ limit: data.limit });
</script>

<SeoHead {headModel} />

<section class="card campaign-list" aria-label="Committees">
  <h2>Committees</h2>
  <form method="GET" class="campaign-list__filters" aria-label="Committee filters">
    <!-- Keep URL query params as the source of truth so SSR and deep links stay aligned. -->
    <label for="committee-filter-state">State</label>
    <select id="committee-filter-state" name="state">
      <option value="" selected={activeState === ""}>All states</option>
      {#each US_STATE_OPTIONS as option}
        <option value={option.code} selected={activeState === option.code}>{option.label}</option>
      {/each}
    </select>

    <label for="committee-filter-type">Committee type</label>
    <select id="committee-filter-type" name="committee_type">
      <option value="" selected={activeCommitteeType === ""}>All committee types</option>
      {#each COMMITTEE_TYPE_OPTIONS as option}
        <option value={option.code} selected={activeCommitteeType === option.code}>{option.label}</option>
      {/each}
    </select>

    <!-- Preserve backend-owned page size while clearing stale offset on each filter submit. -->
    <input type="hidden" name="limit" value={data.limit} />

    <button type="submit">Apply filters</button>
    <a href={clearFiltersHref}>Clear filters</a>
  </form>
  <ListNavigationLoading routePath={COMMITTEES_PAGE_PATH} filterParams={["state", "committee_type"]} label="Updating results…" let:isFilterNavigation>
    {#if isFilterNavigation}
      <!-- Replace stale committee rows while a new filtered response is still
           in flight so the list does not imply the old filter state is current. -->
      <SkeletonPanel label="Committee results loading" lines={4} />
    {:else}
      {#if data.items.length === 0}
        <p>No committees found for the selected filters.</p>
      {:else}
        <ul class="campaign-list__items">
          {#each committeeItems as itemView (itemView.item.id)}
            <li class="campaign-list__item">
              <!-- The list presenter packages the canonical route target with the
                   committee metadata needed to distinguish similar committee names. -->
              <h3 class="campaign-list__name">
                <a href={itemView.presentation.href}>{itemView.presentation.name}</a>
              </h3>
              {#if itemView.presentation.contextLine !== ""}
                <p class="campaign-list__context">{itemView.presentation.contextLine}</p>
              {/if}
            </li>
          {/each}
        </ul>
      {/if}

      <nav class="campaign-list__pagination" aria-label="Committees pagination">
        <!-- Preserve previous/next links while exposing the current browse range
             from the backend-owned pagination envelope. -->
        <p class="campaign-list__pagination-label">{paginationContext.label}</p>
        {#if previousHref !== null}
          <a href={previousHref}>Previous</a>
        {/if}
        {#if nextHref !== null}
          <a href={nextHref}>Next</a>
        {/if}
      </nav>
    {/if}
  </ListNavigationLoading>
</section>

<style>
  .campaign-list__items {
    margin: 0;
    padding-left: 1.2rem;
  }

  .campaign-list__filters {
    margin-bottom: 1rem;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem;
  }

  .campaign-list__item + .campaign-list__item {
    margin-top: 0.5rem;
  }

  .campaign-list__name {
    margin: 0;
    font-size: 1.05rem;
  }

  .campaign-list__context {
    margin: 0.2rem 0 0;
    color: var(--text-secondary, #44515e);
    font-size: 0.95rem;
  }

  .campaign-list__pagination {
    margin-top: 1rem;
    display: flex;
    align-items: center;
    gap: 1rem;
  }

  .campaign-list__pagination-label {
    margin: 0;
  }
</style>
