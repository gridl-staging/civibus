<script lang="ts">
  import { env } from "$env/dynamic/public";
  import { page } from "$app/stores";
  import { APP_SHELL } from "$lib/config/app";
  import SeoHead from "$lib/seo/SeoHead.svelte";
  import { buildSeoHeadModel } from "$lib/seo/head";
  import TrustPageSections from "$lib/trust-pages/TrustPageSections.svelte";

  const routeMetadata = APP_SHELL.staticRoutes.about;
  const aboutCopy = APP_SHELL.trustPages.about;

  $: headModel = buildSeoHeadModel({
    metadata: routeMetadata,
    ogType: "website",
    pageUrl: $page.url,
    publicOrigin: env.PUBLIC_ORIGIN
  });
</script>

<SeoHead {headModel} />

<section class="card" aria-label="About" data-testid="about-page">
  <h2>{aboutCopy.heading}</h2>
  <TrustPageSections sections={aboutCopy.sections} />
</section>
