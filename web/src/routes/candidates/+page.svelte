<script lang="ts">
  import { env } from "$env/dynamic/public";
  import { page } from "$app/stores";
  import { CANDIDATES_PAGE_PATH, buildCandidatesPagePath } from "$lib/campaign-finance-detail/contract";
  import ListNavigationLoading from "$lib/campaign-finance-detail/ListNavigationLoading.svelte";
  import {
    FEC_CANDIDATE_OFFICE_OPTIONS,
    US_STATE_OPTIONS
  } from "$lib/campaign-finance-detail/filter-options";
  import {
    buildCandidateListItemPresentation,
    buildPaginationContext
  } from "$lib/campaign-finance-detail/list-presentation";
  import SkeletonPanel from "$lib/loading/SkeletonPanel.svelte";
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
  $: candidateItems = data.items.map((item) => ({
    item,
    presentation: buildCandidateListItemPresentation(item)
  }));
  $: activeState = $page.url.searchParams.get("state") ?? "";
  $: activeOffice = $page.url.searchParams.get("office") ?? "";
  $: paginationContext = buildPaginationContext(data.offset, data.limit, data.has_next, data.items.length);
  $: previousHref = paginationContext.hasPrevious
    ? buildCandidatesPagePath({
        state: activeState,
        office: activeOffice,
        offset: Math.max(data.offset - data.limit, 0),
        limit: data.limit
      })
    : null;
  $: nextHref = paginationContext.hasNext
    ? buildCandidatesPagePath({
        state: activeState,
        office: activeOffice,
        offset: data.offset + data.limit,
        limit: data.limit
      })
    : null;
  $: clearFiltersHref = buildCandidatesPagePath({ limit: data.limit });
</script>

<SeoHead {headModel} />

<section class="card campaign-list" aria-label="Candidates">
  <h2>Candidates</h2>
  <form method="GET" class="campaign-list__filters" aria-label="Candidate filters">
    <!-- Keep URL query params as the source of truth so SSR and deep links stay aligned. -->
    <label for="candidate-filter-state">State</label>
    <select id="candidate-filter-state" name="state">
      <option value="" selected={activeState === ""}>All states</option>
      {#each US_STATE_OPTIONS as option}
        <option value={option.code} selected={activeState === option.code}>{option.label}</option>
      {/each}
    </select>

    <label for="candidate-filter-office">Office</label>
    <select id="candidate-filter-office" name="office">
      <option value="" selected={activeOffice === ""}>All offices</option>
      {#each FEC_CANDIDATE_OFFICE_OPTIONS as option}
        <option value={option.code} selected={activeOffice === option.code}>{option.label}</option>
      {/each}
    </select>

    <!-- Preserve backend-owned page size while clearing stale offset on each filter submit. -->
    <input type="hidden" name="limit" value={data.limit} />

    <button type="submit">Apply filters</button>
    <a href={clearFiltersHref}>Clear filters</a>
  </form>
  <ListNavigationLoading routePath={CANDIDATES_PAGE_PATH} filterParams={["state", "office"]} label="Updating results…" let:isFilterNavigation>
    {#if isFilterNavigation}
      <!-- Swap stale list results for a busy placeholder while the filtered
           browse response streams in on the same route. -->
      <SkeletonPanel label="Candidate results loading" lines={4} />
    {:else}
      {#if data.items.length === 0}
        <p>No candidates found for the selected filters.</p>
      {:else}
        <ul class="campaign-list__items">
          {#each candidateItems as itemView (itemView.item.id)}
            <li class="campaign-list__item">
              <!-- The shared list presenter supplies the routed name plus compact
                   campaign metadata so same-name candidates stay distinguishable. -->
              <h3 class="campaign-list__name">
                <a href={itemView.presentation.href}>{itemView.presentation.name}</a>
              </h3>
              <p class="campaign-list__context">{itemView.presentation.contextLine}</p>
            </li>
          {/each}
        </ul>
      {/if}

      <nav class="campaign-list__pagination" aria-label="Candidates pagination">
        <!-- Keep the backend-owned page range visible alongside the previous/next
             controls so deep pagination still has position context. -->
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
