<script lang="ts">
  /** Renders shared APP_SHELL trust-page section copy; the config remains the copy owner. */
  export let sections: ReadonlyArray<{
    heading: string;
    paragraphs: readonly string[];
  }>;
</script>

{#each sections as section}
  <section class="trust-page__section">
    <h3>{section.heading}</h3>
    {#each section.paragraphs as paragraph}
      <p>{paragraph}</p>
    {/each}
  </section>
{/each}

<style>
  .trust-page__section h3 {
    margin: 1.1rem 0 0.45rem;
  }
</style>
