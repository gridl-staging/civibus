<script lang="ts">
  import { navigating } from '$app/stores';
  import { buildDonorPagePath, DONOR_SEARCH_BY_MODES, DONOR_SEARCH_PAGE_PATH } from '$lib/donors/contract';
  import SkeletonPanel from '$lib/loading/SkeletonPanel.svelte';
  import type { PageData } from './$types';

  export let data: PageData;
  export let isSubmitting = false;

  const currencyFormatter = new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD'
  });
  const SCOPE_NOTE =
    'Results cover itemized contributions to committees of current federal officeholders only. Unitemized (<$200) contributions are not included.';
  const LANDING_MESSAGE = 'Enter a donor name, employer, or 5-digit ZIP to search itemized federal contributions.';
  const SHORT_QUERY_MESSAGE = 'Enter at least 3 characters to search by name or employer.';
  const ZERO_RESULTS_MESSAGE = 'No donors match this search.';

  $: isLoading = isSubmitting || $navigating !== null;
  $: hasSubmittedQuery = data.query.trim() !== '';
  $: hasResults = data.results.length > 0;
  $: statusMessage = getStatusMessage({
    isLoading,
    validationMessage: data.validationMessage,
    shortQueryGuidance: data.shortQueryGuidance,
    hasSubmittedQuery,
    hasResults,
    offset: data.offset,
    resultCount: data.results.length
  });
  $: previousPageHref = buildDonorPagePath({
    q: data.query,
    by: data.by,
    limit: data.limit,
    offset: Math.max(0, data.offset - data.limit)
  });
  $: nextPageHref = buildDonorPagePath({
    q: data.query,
    by: data.by,
    limit: data.limit,
    offset: data.offset + data.limit
  });

  function getStatusMessage(state: {
    isLoading: boolean;
    validationMessage?: string;
    shortQueryGuidance?: boolean;
    hasSubmittedQuery: boolean;
    hasResults: boolean;
    offset: number;
    resultCount: number;
  }): string {
    if (state.isLoading) {
      return 'Searching donors...';
    }

    if (state.validationMessage) {
      return state.validationMessage;
    }

    if (state.shortQueryGuidance) {
      return SHORT_QUERY_MESSAGE;
    }

    if (!state.hasSubmittedQuery) {
      return LANDING_MESSAGE;
    }

    if (!state.hasResults) {
      return ZERO_RESULTS_MESSAGE;
    }

    return `Showing donors ${state.offset + 1}-${state.offset + state.resultCount}.`;
  }

  function formatCurrency(value: string): string {
    return currencyFormatter.format(Number(value));
  }

  function formatNullable(value: string | null | undefined): string {
    const trimmedValue = value?.trim();
    return trimmedValue ? trimmedValue : '—';
  }

  function formatLocation(city: string | null | undefined, state: string | null | undefined): string {
    const cityValue = city?.trim() ?? '';
    const stateValue = state?.trim() ?? '';

    if (cityValue !== '' && stateValue !== '') {
      return `${cityValue}, ${stateValue}`;
    }

    return formatNullable(cityValue || stateValue);
  }

  function formatDate(value: string | null | undefined): string {
    return formatNullable(value);
  }
</script>

<svelte:head>
  <title>Donor Lookup | Civibus</title>
  <meta
    name="description"
    content="Look up itemized federal donor contributions to committees of current federal officeholders."
  />
</svelte:head>

<section class="card donor-lookup" aria-label="Donor lookup">
  <h2>Donor Lookup</h2>
  <p class="donor-lookup__scope" data-testid="donor-scope-note">{SCOPE_NOTE}</p>

  <form method="GET" action={DONOR_SEARCH_PAGE_PATH} class="donor-lookup__form">
    <label class="donor-lookup__field" for="donor-search-query">
      <span>Query</span>
      <input
        id="donor-search-query"
        data-testid="donor-search-input"
        name="q"
        type="search"
        value={data.query}
        aria-describedby="donor-search-status"
      />
    </label>

    <label class="donor-lookup__field" for="donor-search-mode">
      <span>Search by</span>
      <select id="donor-search-mode" data-testid="donor-search-by" name="by">
        {#each DONOR_SEARCH_BY_MODES as mode}
          <option value={mode} selected={data.by === mode}>{mode}</option>
        {/each}
      </select>
    </label>

    <input type="hidden" name="limit" value={data.limit} />
    <input type="hidden" name="offset" value="0" />
    <button type="submit" disabled={isLoading}>Search</button>
  </form>

  <p
    id="donor-search-status"
    class="donor-lookup__status"
    data-testid="donor-search-status"
    role="status"
    aria-live="polite"
  >
    {statusMessage}
  </p>

  {#if hasResults && !isLoading}
    <p class="donor-lookup__count" data-testid="donor-result-count">{statusMessage}</p>
  {/if}

  <div class="donor-lookup__results" aria-busy={isLoading ? 'true' : 'false'}>
    {#if isLoading}
      <SkeletonPanel label="Donor results loading" lines={5} />
    {:else if hasResults}
      <div class="donor-lookup__table-wrap">
        <table>
          <thead>
            <tr>
              <th>Donor</th>
              <th>Employer</th>
              <th>Occupation</th>
              <th>Location</th>
              <th>ZIP</th>
              <th>Total</th>
              <th>Count</th>
              <th>Latest</th>
              <th>Recipients</th>
              <th>Sources</th>
            </tr>
          </thead>
          <tbody>
            {#each data.results as result (result.id)}
              <tr data-testid="donor-result-row">
                <td>{result.contributor_name}</td>
                <td>{formatNullable(result.contributor_employer)}</td>
                <td>{formatNullable(result.contributor_occupation)}</td>
                <td>{formatLocation(result.contributor_city, result.contributor_state)}</td>
                <td>{formatNullable(result.normalized_zip5)}</td>
                <td>{formatCurrency(result.total_amount)}</td>
                <td>{result.transaction_count}</td>
                <td>{formatDate(result.latest_transaction_date)}</td>
                <td>
                  {#if result.recipients.length > 0}
                    <ul class="donor-lookup__nested-list">
                      {#each result.recipients as recipient (recipient.person_id + recipient.committee_id)}
                        <li>
                          <a href={`/person/${recipient.person_id}`}>{recipient.candidate_name}</a>
                        </li>
                      {/each}
                    </ul>
                  {/if}
                </td>
                <td>
                  {#if result.sources.length > 0}
                    <ul class="donor-lookup__nested-list">
                      {#each result.sources as source (source.source_record_key ?? source.data_source_url)}
                        <li>
                          <a href={source.data_source_url}>{source.data_source_name}</a>
                          {#if source.record_url}
                            <a href={source.record_url}>Record</a>
                          {/if}
                        </li>
                      {/each}
                    </ul>
                  {/if}
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>

      <nav class="donor-lookup__pagination" aria-label="Donor result pages">
        {#if data.offset > 0}
          <a href={previousPageHref}>Previous</a>
        {:else}
          <span aria-disabled="true">Previous</span>
        {/if}

        {#if data.results.length === data.limit}
          <a href={nextPageHref}>Next</a>
        {:else}
          <span aria-disabled="true">Next</span>
        {/if}
      </nav>
    {/if}
  </div>
</section>

<style>
  .donor-lookup {
    display: grid;
    gap: 1rem;
  }

  .donor-lookup h2 {
    margin: 0;
  }

  .donor-lookup__scope,
  .donor-lookup__status,
  .donor-lookup__count {
    margin: 0;
  }

  .donor-lookup__form {
    display: grid;
    gap: 0.65rem;
    grid-template-columns: minmax(12rem, 1fr) minmax(9rem, 0.35fr) auto;
    align-items: end;
  }

  .donor-lookup__field {
    display: grid;
    gap: 0.3rem;
    font-weight: 700;
  }

  .donor-lookup__form input[type='search'],
  .donor-lookup__form select {
    min-width: 0;
    width: 100%;
    box-sizing: border-box;
  }

  .donor-lookup__form button {
    min-height: 2.35rem;
  }

  .donor-lookup__table-wrap {
    overflow-x: auto;
  }

  .donor-lookup table {
    width: 100%;
    border-collapse: collapse;
  }

  .donor-lookup th,
  .donor-lookup td {
    padding: 0.55rem;
    border-bottom: 1px solid #d6e1ea;
    text-align: left;
    vertical-align: top;
  }

  .donor-lookup th {
    background: #f4f8fb;
    color: #1f4058;
  }

  .donor-lookup__nested-list {
    display: grid;
    gap: 0.25rem;
    margin: 0;
    padding-left: 1rem;
  }

  .donor-lookup__pagination {
    display: flex;
    gap: 0.75rem;
    margin-top: 0.8rem;
  }

  .donor-lookup__pagination a,
  .donor-lookup__pagination span {
    display: inline-flex;
    align-items: center;
    min-height: 2rem;
  }

  @media (max-width: 760px) {
    .donor-lookup__form {
      grid-template-columns: 1fr;
    }
  }
</style>
