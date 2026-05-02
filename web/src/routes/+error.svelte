<script lang="ts">
  import { APP_SHELL } from '$lib/config/app';
  import { getApiErrorDisplayMessage } from '$lib/api/error-display';
  import { page } from '$app/stores';

  export let status: number | undefined;
  export let error: App.Error;

  type ErrorRouteCopy = {
    title: string;
    heading: string;
    summary: string;
    description: string;
  };

  function getErrorRouteCopy(statusCode: number): ErrorRouteCopy {
    if (statusCode === 404) {
      return {
        title: 'Page not found',
        heading: 'Page not found',
        summary: 'The page may have moved, been removed, or the URL may be incorrect.',
        description: 'The requested page could not be found. Try search or return to the homepage.'
      };
    }

    if (statusCode >= 400 && statusCode < 500) {
      return {
        title: 'Request could not be completed',
        heading: 'Request could not be completed',
        summary: 'The server rejected this request. Check the URL or try searching for a record.',
        description: 'The request could not be completed. Review your input or try another page.'
      };
    }

    if (statusCode >= 500 && statusCode < 600) {
      return {
        title: 'Service temporarily unavailable',
        heading: 'Service temporarily unavailable',
        summary: 'Civibus is having trouble loading this page right now. Please try again shortly.',
        description: 'Civibus could not complete this request because a service is unavailable.'
      };
    }

    return {
      title: 'Unexpected response status',
      heading: 'Unexpected response status',
      summary: 'This response status is not recognized by the route-level error buckets.',
      description: 'Civibus received an unexpected response status for this request.'
    };
  }

  function resolveStatusCode(statusCode: number | undefined, pageStatusCode: number | undefined): number {
    if (typeof statusCode === 'number') {
      return statusCode;
    }

    if (typeof pageStatusCode === 'number') {
      return pageStatusCode;
    }

    return 500;
  }

  let resolvedStatus: number;
  let statusCopy: ErrorRouteCopy;
  let displayMessage: string;

  $: resolvedStatus = resolveStatusCode(status, $page.status);
  $: statusCopy = getErrorRouteCopy(resolvedStatus);
  $: displayMessage = getApiErrorDisplayMessage(error);
</script>

<svelte:head>
  <title>{statusCopy.title} | {APP_SHELL.branding.name}</title>
  <meta name="description" content={statusCopy.description} />
  <meta name="robots" content="noindex" />
</svelte:head>

<section class="card error" aria-live="assertive">
  <h2>{statusCopy.heading}</h2>
  <p class="error__summary">{statusCopy.summary}</p>
  <p class="error__status">HTTP {resolvedStatus}</p>
  <p>{displayMessage}</p>
  <p class="error__actions">
    <a href="/">Return home</a>
    <span aria-hidden="true">&middot;</span>
    <a href="/search">Go to search</a>
  </p>
</section>

<style>
  .error {
    display: grid;
    gap: 0.65rem;
  }

  .error h2,
  .error p {
    margin: 0;
  }

  .error__summary {
    color: #274d68;
  }

  .error__actions {
    display: flex;
    flex-wrap: wrap;
    gap: 0.45rem;
    align-items: center;
    font-weight: 600;
  }

  .error__actions a {
    color: #8a1932;
    text-underline-offset: 0.16rem;
  }
</style>
