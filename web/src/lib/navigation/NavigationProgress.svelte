<script lang="ts">
  // The shell toggles this from SvelteKit's $navigating store so every route
  // transition gets lightweight global loading feedback.
  export let isNavigating = false;

  $: progressValue = isNavigating ? 100 : 0;
</script>

<div
  class={`navigation-progress ${isNavigating ? "navigation-progress--active" : ""}`}
  role="progressbar"
  aria-valuemin="0"
  aria-valuemax="100"
  aria-valuenow={progressValue}
  aria-busy={isNavigating ? "true" : "false"}
>
  <span class="navigation-progress__bar"></span>
</div>
