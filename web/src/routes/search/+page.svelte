<script lang="ts">
  import { enhance } from '$app/forms';
  import type { SubmitFunction } from '@sveltejs/kit';
  import SkeletonPanel from '$lib/loading/SkeletonPanel.svelte';
  import { SEARCH_QUERY_MIN_LENGTH } from '$lib/search/contract';
  import { buildSearchPagePresentation, buildSearchResultKey } from '$lib/search/presentation';
  import type { ActionData, PageData } from './$types';

  export let data: PageData;
  export let form: ActionData | null = null;
  export let isSubmitting = false;

  const enhanceSearchSubmit: SubmitFunction = () => {
    isSubmitting = true;

    return async ({ update }) => {
      await update();
      isSubmitting = false;
    };
  };

  $: viewModel = buildSearchPagePresentation({
    ...data,
    form: form ?? null,
    isSubmitting
  });
</script>

<svelte:head>
  <title>{viewModel.metadata.title}</title>
  <meta name="description" content={viewModel.metadata.description} />
</svelte:head>

<section class="card search" aria-label="Search records">
  <h2>Search</h2>
  <form method="POST" class="search__form" use:enhance={enhanceSearchSubmit}>
    <label for="search-query">Query</label>
    <input
      id="search-query"
      name="q"
      type="search"
      minlength={SEARCH_QUERY_MIN_LENGTH}
      value={viewModel.queryValue}
      placeholder={viewModel.queryPlaceholder}
      aria-describedby={viewModel.inlineValidationMessage !== '' ? 'search-validation-message' : undefined}
      aria-invalid={viewModel.inlineValidationMessage !== '' ? 'true' : undefined}
    />

    <label for="search-entity-type">Entity type</label>
    <select
      id="search-entity-type"
      name="entity_type"
    >
      <option value="">All types</option>
      {#each viewModel.entityTypeOptions as option (option.value)}
        <option value={option.value} selected={viewModel.selectedEntityType === option.value}>
          {option.label}
        </option>
      {/each}
    </select>

    <button type="submit" disabled={isSubmitting}>
      {viewModel.submitButtonLabel}
    </button>
  </form>

  {#if viewModel.inlineValidationMessage !== ''}
    <p id="search-validation-message" class="search__validation" role="alert">
      {viewModel.inlineValidationMessage}
    </p>
  {/if}

  <nav aria-label="Browse by record type">
    {#each viewModel.browseLinks as browseLink (browseLink.href)}
      <a href={browseLink.href}>{browseLink.label}</a>
    {/each}
  </nav>

  {#if viewModel.guidanceBlock !== ''}
    <p>{viewModel.guidanceBlock}</p>
  {/if}

  <p class="search__status" data-testid="search-status" role="status" aria-live="polite">
    {viewModel.statusMessage}
  </p>

  <div data-testid="search-results-region" aria-busy={viewModel.showResultsSkeleton ? 'true' : 'false'}>
    {#if viewModel.showResultsSkeleton}
      <SkeletonPanel label="Search results loading" lines={4} />
    {:else if viewModel.resultCards.length > 0}
      <ul class="search__results">
        {#each viewModel.resultCards as result (buildSearchResultKey(result))}
          <li class="card search__result">
            <h3><a href={result.href}>{result.name}</a></h3>
            <p class="search__badge-row">
              <span class="search__badge">{result.routeLabel}</span>
            </p>
            {#if result.contextLine !== ''}
              <p class="search__context-line">{result.contextLine}</p>
            {/if}
          </li>
        {/each}
      </ul>
    {/if}
  </div>
</section>
