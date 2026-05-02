<script lang="ts">
  import { navigating } from "$app/stores";

  export let routePath: string;
  export let filterParams: string[];
  export let label: string;

  $: isFilterNavigation = deriveFilterNavigation($navigating, routePath, filterParams);

  function deriveFilterNavigation(
    nav: typeof $navigating,
    path: string,
    watched: string[]
  ): boolean {
    if (!nav?.from?.url || !nav?.to?.url) return false;
    if (nav.from.url.pathname !== path || nav.to.url.pathname !== path) return false;

    const fromParams = nav.from.url.searchParams;
    const toParams = nav.to.url.searchParams;

    for (const param of watched) {
      if ((fromParams.get(param) ?? "") !== (toParams.get(param) ?? "")) {
        return true;
      }
    }

    return false;
  }
</script>

<div class="list-navigation-loading-region" aria-hidden={!isFilterNavigation}>
  {#if isFilterNavigation}
    <p class="list-navigation-loading" role="status" aria-live="polite">{label}</p>
  {/if}
</div>

<slot {isFilterNavigation} />

<style>
  .list-navigation-loading-region {
    margin: 0.5rem 0 0;
    min-height: 1.2rem;
  }

  .list-navigation-loading {
    margin: 0;
    font-size: 0.9rem;
    line-height: 1.2rem;
    color: var(--text-secondary, #44515e);
  }
</style>
