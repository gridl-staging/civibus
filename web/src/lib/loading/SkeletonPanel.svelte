<script lang="ts">
  // A small, reusable placeholder for async entity-detail sections.
  export let label: string;
  export let lines = 4;
</script>

<section class="skeleton-panel" aria-label={label} aria-busy="true">
  <h3>{label}</h3>
  <div class="skeleton-panel__rows">
    {#each Array(lines) as _, lineIndex (lineIndex)}
      <div class="skeleton-panel__line"></div>
    {/each}
  </div>
</section>
