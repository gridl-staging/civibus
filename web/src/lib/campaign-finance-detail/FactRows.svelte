<script lang="ts">
  import type { KeyMetric } from "$lib/campaign-finance-detail/presentation";

  export let rows: KeyMetric[];
</script>

<dl class="detail__rows">
  {#each rows as row (row.label)}
    <div class="detail__row">
      <dt>{row.label}</dt>
      <dd>{row.value}</dd>
    </div>
  {/each}
</dl>
