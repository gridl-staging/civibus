<script lang="ts">
  import { env } from "$env/dynamic/public";
  import { page } from "$app/stores";
  import Breadcrumb from "$lib/breadcrumb/Breadcrumb.svelte";
  import DetailPage from "$lib/property-detail/DetailPage.svelte";
  import {
    buildPropertyDetailMetadataFromDetail,
    type DetailRouteMetadata
  } from "$lib/property-detail/presentation";
  import SeoHead from "$lib/seo/SeoHead.svelte";
  import { buildDetailRouteSeo } from "$lib/seo/head";
  import { buildBreadcrumbJsonLd, removeJsonLdContext, type JsonLdObject } from "$lib/seo/jsonld";
  import type { PageData } from "./$types";

  export let data: PageData;

  let routeMetadata: DetailRouteMetadata;
  $: routeMetadata = buildPropertyDetailMetadataFromDetail(data);
  $: detailRouteSeo = buildDetailRouteSeo({
    metadata: routeMetadata,
    ogType: "website",
    schemaType: "Place",
    name: data.site_address,
    pageUrl: $page.url,
    publicOrigin: env.PUBLIC_ORIGIN
  });
  $: breadcrumbCrumbs = [
    { label: "Home", href: "/" },
    { label: data.site_address }
  ];
  $: breadcrumbJsonLd = buildBreadcrumbJsonLd({
    crumbs: breadcrumbCrumbs,
    publicOrigin: env.PUBLIC_ORIGIN
  });
  $: detailJsonLdWithoutContext = removeJsonLdContext(detailRouteSeo.jsonLd);
  $: detailPageJsonLd = {
    "@context": "https://schema.org",
    "@graph": [detailJsonLdWithoutContext, breadcrumbJsonLd]
  } as JsonLdObject;
</script>

<SeoHead headModel={detailRouteSeo.headModel} jsonLd={detailPageJsonLd} />

<Breadcrumb crumbs={breadcrumbCrumbs} />
<DetailPage {data} />
