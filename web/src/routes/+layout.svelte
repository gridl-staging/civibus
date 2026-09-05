<script lang="ts">
  import { navigating } from "$app/stores";
  import "../app.css";
  import { APP_SHELL } from "$lib/config/app";
  import { getSeoDefaults } from "$lib/seo/defaults";
  import NavigationProgress from "$lib/navigation/NavigationProgress.svelte";

  const seoDefaults = getSeoDefaults();
  const footerLinks = [...APP_SHELL.footer.links, ...APP_SHELL.footer.trustPageLinks];

  function shellRouteTestId(href: string): string {
    return href === "/" ? "home" : href.slice(1).replace(/[^a-z0-9]+/g, "-");
  }
</script>

<svelte:head>
  <title>{APP_SHELL.branding.appTitle}</title>
  <meta property="og:site_name" content={seoDefaults.siteName} />
</svelte:head>

<NavigationProgress isNavigating={$navigating !== null} />

<div class="shell">
  <a class="shell__skip-link" href="#main-content" data-testid="shell-skip-link">Skip to main content</a>
  <header class="shell__header" aria-label="Application shell" data-testid="shell-header">
    <span class="shell__stage">{APP_SHELL.branding.stageLabel}</span>
    <h1 class="shell__title">{APP_SHELL.branding.name}</h1>
    <p class="shell__tagline">{APP_SHELL.branding.tagline}</p>
    <nav class="shell__nav" aria-label="Primary" data-testid="shell-primary-nav">
      {#each APP_SHELL.shellNavigation as link}
        <a class="shell__nav-link" href={link.href} data-testid={`shell-nav-link-${shellRouteTestId(link.href)}`}>
          {link.label}
        </a>
      {/each}
    </nav>
  </header>
  <main id="main-content" tabindex="-1" aria-busy={$navigating !== null} data-testid="shell-main">
    <slot />
  </main>
  <footer class="shell__footer" data-testid="shell-footer">
    <nav aria-label="Footer" data-testid="shell-footer-nav">
      {#each footerLinks as link}
        <a class="shell__footer-link" href={link.href} data-testid={`shell-footer-link-${shellRouteTestId(link.href)}`}>
          {link.label}
        </a>
      {/each}
    </nav>
  </footer>
</div>
