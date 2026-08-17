<script lang="ts">
  import { env } from "$env/dynamic/public";
  import { page } from "$app/stores";
  import { APP_SHELL } from "$lib/config/app";
  import SeoHead from "$lib/seo/SeoHead.svelte";
  import { buildSeoHeadModel } from "$lib/seo/head";
  import TrustPageSections from "$lib/trust-pages/TrustPageSections.svelte";

  const routeMetadata = APP_SHELL.staticRoutes.privacy;
  const privacyCopy = APP_SHELL.trustPages.privacy;

  $: headModel = buildSeoHeadModel({
    metadata: routeMetadata,
    ogType: "website",
    pageUrl: $page.url,
    publicOrigin: env.PUBLIC_ORIGIN
  });
</script>

<SeoHead {headModel} />

<section class="card" aria-label="Privacy" data-testid="privacy-page">
  <h2>{privacyCopy.heading}</h2>
  <TrustPageSections sections={privacyCopy.sections} />
</section>
