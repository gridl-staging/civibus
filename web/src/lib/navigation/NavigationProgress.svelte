<script lang="ts">
  // The shell toggles this from SvelteKit's $navigating store so every route
  // transition gets lightweight global loading feedback.
  // The animation is decorative because <main aria-busy> announces the same state.
  export let isNavigating = false;
</script>

<div
  class={`navigation-progress ${isNavigating ? "navigation-progress--active" : ""}`}
  aria-hidden="true"
>
  <span class="navigation-progress__bar"></span>
</div>
