<script lang="ts">
  import { SEARCH_QUERY_MIN_LENGTH } from '$lib/search/contract';
  import { buildSearchPagePresentation } from '$lib/search/presentation';
  import type { PageData } from './$types';

  export let data: PageData;

  $: viewModel = buildSearchPagePresentation(data);
</script>

<svelte:head>
  <title>{viewModel.metadata.title}</title>
  <meta name="description" content={viewModel.metadata.description} />
</svelte:head>

<section class="card search" aria-label="Search records">
  <h2>Search</h2>
  <form method="GET" class="search__form">
    <label for="search-query">Query</label>
    <input
      id="search-query"
      name="q"
      type="search"
      minlength={SEARCH_QUERY_MIN_LENGTH}
      value={data.query}
      placeholder={viewModel.queryPlaceholder}
    />

    <label for="search-entity-type">Entity type</label>
    <select id="search-entity-type" name="entity_type">
      <option value="">All types</option>
      {#each viewModel.entityTypeOptions as option (option.value)}
        <option value={option.value} selected={viewModel.selectedEntityType === option.value}>
          {option.label}
        </option>
      {/each}
    </select>

    <button type="submit">Search</button>
  </form>

  <nav aria-label="Browse by record type">
    {#each viewModel.browseLinks as browseLink (browseLink.href)}
      <a href={browseLink.href}>{browseLink.label}</a>
    {/each}
  </nav>

  {#if viewModel.guidanceBlock !== ''}
    <p>{viewModel.guidanceBlock}</p>
  {/if}

  <p class="search__status">{viewModel.statusMessage}</p>

  {#if viewModel.resultCards.length > 0}
    <ul class="search__results">
      {#each viewModel.resultCards as result (result.entityId)}
        <li class="card search__result">
          <h3><a href={result.href}>{result.name}</a></h3>
          <p>{result.routeLabel}</p>
        </li>
      {/each}
    </ul>
  {/if}
</section>
