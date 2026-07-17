<script lang="ts">
  import { env } from "$env/dynamic/public";
  import { page } from "$app/stores";
  import Breadcrumb from "$lib/breadcrumb/Breadcrumb.svelte";
  import DetailPage from "$lib/entity-detail/DetailPage.svelte";
  import {
    buildEntityDetailMetadataFromDetail,
    type DetailRouteMetadata
  } from "$lib/entity-detail/presentation";
  import SeoHead from "$lib/seo/SeoHead.svelte";
  import { buildDetailRouteSeo } from "$lib/seo/head";
  import { buildBreadcrumbJsonLd, removeJsonLdContext, type JsonLdObject } from "$lib/seo/jsonld";
  import { buildCompareUrl } from "../../compare/people-query";
  import type { PageData } from "./$types";

  export let data: PageData;

  let routeMetadata: DetailRouteMetadata;
  $: routeMetadata = buildEntityDetailMetadataFromDetail({
    entityType: data.entityType,
    detail: data.detail
  });
  $: detailRouteSeo = buildDetailRouteSeo({
    metadata: routeMetadata,
    ogType: "profile",
    schemaType: "Person",
    name: data.detail.canonical_name,
    pageUrl: $page.url,
    publicOrigin: env.PUBLIC_ORIGIN
  });
  $: breadcrumbCrumbs = [
    { label: "Home", href: "/" },
    { label: data.detail.canonical_name }
  ];
  $: breadcrumbJsonLd = buildBreadcrumbJsonLd({
    crumbs: breadcrumbCrumbs,
    publicOrigin: env.PUBLIC_ORIGIN
  });
  $: compareHref = buildCompareUrl([data.detail.id]);
  $: detailJsonLdWithoutContext = removeJsonLdContext(detailRouteSeo.jsonLd);
  $: detailPageJsonLd = {
    "@context": "https://schema.org",
    "@graph": [detailJsonLdWithoutContext, breadcrumbJsonLd]
  } as JsonLdObject;
</script>

<SeoHead headModel={detailRouteSeo.headModel} jsonLd={detailPageJsonLd} />

<Breadcrumb crumbs={breadcrumbCrumbs} />
<DetailPage {data} {compareHref} />
