<script lang="ts">
  import { enhance } from '$app/forms';
  import { onMount } from 'svelte';
  import type { SubmitFunction } from '@sveltejs/kit';
  import SkeletonPanel from '$lib/loading/SkeletonPanel.svelte';
  import { SEARCH_QUERY_MIN_LENGTH } from '$lib/search/contract';
  import {
    buildSearchPagePresentation,
    buildSearchResultKey,
    type SearchPageFormState
  } from '$lib/search/presentation';
  import type { ActionData, PageData } from './$types';

  export let data: PageData;
  export let form: ActionData | null = null;
  export let isSubmitting = false;

  let isEnhanced = false;
  let pendingForm: SearchPageFormState | null = null;

  onMount(() => {
    isEnhanced = true;
  });

  function readFormValueAsString(formData: FormData, key: string): string {
    const rawValue = formData.get(key);
    return typeof rawValue === 'string' ? rawValue : '';
  }

  const enhanceSearchSubmit: SubmitFunction = ({ formData }) => {
    pendingForm = {
      query: readFormValueAsString(formData, 'q'),
      entityType: readFormValueAsString(formData, 'entity_type'),
      validationMessage: ''
    };
    isSubmitting = true;

    return async ({ update }) => {
      try {
        await update();
      } finally {
        isSubmitting = false;
        pendingForm = null;
      }
    };
  };

  $: viewModel = buildSearchPagePresentation({
    ...data,
    form: form ?? pendingForm,
    isSubmitting
  });
</script>

<svelte:head>
  <title>{viewModel.metadata.title}</title>
  <meta name="description" content={viewModel.metadata.description} />
</svelte:head>

<section class="card search" aria-label="Search records">
  <h2>Search</h2>
  <form
    method="POST"
    class="search__form"
    data-testid="search-form"
    data-enhanced={isEnhanced}
    use:enhance={enhanceSearchSubmit}
  >
    <label for="search-query">Query</label>
    <input
      id="search-query"
      name="q"
      type="search"
      minlength={SEARCH_QUERY_MIN_LENGTH}
      value={viewModel.queryValue}
      placeholder={viewModel.queryPlaceholder}
      aria-describedby={viewModel.queryHasValidationError ? 'search-validation-message' : undefined}
      aria-invalid={viewModel.queryHasValidationError ? 'true' : undefined}
    />

    <label for="search-entity-type">Search type</label>
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

  {#if viewModel.regionalCards.length > 0}
    <section aria-labelledby="regional-search-results">
      <h3 id="regional-search-results">Regions</h3>
      {#if viewModel.regionalCards.length > 0}
        <ul class="search__results">
          {#each viewModel.regionalCards as region (region.key)}
            <li class="card search__result">
              <h4><a href={region.href}>{region.name}</a></h4>
              <p class="search__badge-row"><span class="search__badge">{region.routeLabel}</span></p>
              <p class="search__context-line">{region.contextLine}</p>
            </li>
          {/each}
        </ul>
      {/if}
    </section>
  {/if}

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
    {#if viewModel.pagination !== null}
      <!-- Same shape as the /candidates pagination nav: position label plus
           Previous/Next links. The view model already suppresses this during
           submits and validation errors, and renders a previous-only escape
           hatch when a stale offset overshoots the result set. -->
      <nav class="search__pagination" aria-label="Search results pagination">
        <p class="search__pagination-label">{viewModel.pagination.label}</p>
        {#if viewModel.pagination.previousHref !== null}
          <a href={viewModel.pagination.previousHref}>Previous</a>
        {/if}
        {#if viewModel.pagination.nextHref !== null}
          <a href={viewModel.pagination.nextHref}>Next</a>
        {/if}
      </nav>
    {/if}
  </div>
</section>
