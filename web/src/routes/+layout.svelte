<script lang="ts">
  import { navigating } from "$app/stores";
  import "../app.css";
  import { APP_SHELL } from "$lib/config/app";
  import { getSeoDefaults } from "$lib/seo/defaults";
  import NavigationProgress from "$lib/navigation/NavigationProgress.svelte";

  const seoDefaults = getSeoDefaults();
</script>

<svelte:head>
  <title>{APP_SHELL.branding.appTitle}</title>
  <meta property="og:site_name" content={seoDefaults.siteName} />
</svelte:head>

<NavigationProgress isNavigating={$navigating !== null} />

<div class="shell">
  <header class="shell__header" aria-label="Application shell">
    <span class="shell__stage">{APP_SHELL.branding.stageLabel}</span>
    <h1 class="shell__title">{APP_SHELL.branding.name}</h1>
    <p class="shell__tagline">{APP_SHELL.branding.tagline}</p>
    <nav class="shell__nav" aria-label="Primary">
      {#each APP_SHELL.shellNavigation as link}
        <a class="shell__nav-link" href={link.href}>{link.label}</a>
      {/each}
    </nav>
  </header>
  <main aria-busy={$navigating !== null}>
    <slot />
  </main>
  <footer class="shell__footer">
    <nav aria-label="Footer">
      {#each APP_SHELL.footer.links as link}
        <a class="shell__footer-link" href={link.href}>{link.label}</a>
      {/each}
    </nav>
  </footer>
</div>
