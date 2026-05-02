<script lang="ts">
  import { APP_SHELL } from "$lib/config/app";
  import type { FreshnessSeverity, TrustSectionViewModel } from "$lib/detail-trust/presentation";

  export let trustSection: TrustSectionViewModel;

  function freshnessCopy(severity: FreshnessSeverity): string {
    if (severity === "fresh") return "Data is current.";
    if (severity === "stale") return "Data may be outdated. Source has not been refreshed recently.";
    return "Data freshness could not be determined.";
  }
</script>

<section class="detail__panel">
  <h3>Source and freshness</h3>
  <p class="detail__summary">{trustSection.lastPulledSummary}</p>
  <p class="detail__freshness detail__freshness--{trustSection.freshnessSeverity}">{freshnessCopy(trustSection.freshnessSeverity)}</p>
  {#if trustSection.freshnessNote}
    <p class="detail__freshness detail__freshness--stale">{trustSection.freshnessNote}</p>
  {/if}

  {#if trustSection.rows.length === 0}
    <p>{trustSection.emptyMessage}</p>
  {:else}
    <ul class="detail__list">
      {#each trustSection.rows as row (row.source + row.sourceRecordKey + row.pullDate)}
        <li>
          <p>{row.sourceLabel}</p>
          <p>Source record ID: {row.sourceRecordKey}</p>
          {#if row.recordUrl}
            <a href={row.recordUrl}>View source record</a>
          {:else}
            <p>Source record link unavailable.</p>
          {/if}
        </li>
      {/each}
    </ul>
  {/if}

  <p class="detail__advisory">{trustSection.advisoryMessage}</p>
  <p>
    <a href={APP_SHELL.reportingLink.href}>{APP_SHELL.reportingLink.label}</a>
  </p>
</section>
