<script lang="ts">
  import { env } from "$env/dynamic/public";
  import { page } from "$app/stores";
  import { APP_SHELL } from "$lib/config/app";
  import SeoHead from "$lib/seo/SeoHead.svelte";
  import { buildSeoHeadModel } from "$lib/seo/head";

  const routeMetadata = APP_SHELL.staticRoutes.contact;
  const contactCopy = APP_SHELL.trustPages.contact;

  $: headModel = buildSeoHeadModel({
    metadata: routeMetadata,
    ogType: "website",
    pageUrl: $page.url,
    publicOrigin: env.PUBLIC_ORIGIN
  });
</script>

<SeoHead {headModel} />

<section class="card" aria-label="Contact" data-testid="contact-page">
  <h2>{contactCopy.heading}</h2>
  {#each contactCopy.paragraphs as paragraph}
    <p>{paragraph}</p>
  {/each}
  <p>
    <a href={contactCopy.action.href}>{contactCopy.action.label}</a>
  </p>
</section>
