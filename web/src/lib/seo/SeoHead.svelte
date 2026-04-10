<script lang="ts">
  import type { SeoHeadModel } from "./head";
  import type { JsonLdObject } from "./jsonld";
  import { serializeJsonLd } from "./jsonld";

  export let headModel: SeoHeadModel;
  export let jsonLd: JsonLdObject | null = null;

  $: serializedJsonLd = jsonLd === null ? null : serializeJsonLd(jsonLd);
</script>

<svelte:head>
  <title>{headModel.title}</title>
  <meta name="description" content={headModel.description} />
  <meta property="og:title" content={headModel.openGraph.title} />
  <meta property="og:description" content={headModel.openGraph.description} />
  <meta property="og:type" content={headModel.openGraph.type} />
  {#if headModel.openGraph.url !== null}
    <meta property="og:url" content={headModel.openGraph.url} />
  {/if}
  {#if headModel.openGraph.image !== null}
    <meta property="og:image" content={headModel.openGraph.image} />
  {/if}
  <meta name="twitter:card" content={headModel.twitter.card} />
  <meta name="twitter:title" content={headModel.twitter.title} />
  <meta name="twitter:description" content={headModel.twitter.description} />
  {#if headModel.twitter.image !== null}
    <meta name="twitter:image" content={headModel.twitter.image} />
  {/if}
  {#if headModel.canonicalUrl !== null}
    <link rel="canonical" href={headModel.canonicalUrl} />
  {/if}
  {#if serializedJsonLd !== null}
    {@html `<script type="application/ld+json">${serializedJsonLd}</script>`}
  {/if}
</svelte:head>
