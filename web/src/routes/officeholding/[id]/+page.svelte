<script lang="ts">
  import { env } from "$env/dynamic/public";
  import { page } from "$app/stores";
  import Breadcrumb from "$lib/breadcrumb/Breadcrumb.svelte";
  import DetailPage from "$lib/civic-detail/DetailPage.svelte";
  import { buildOfficeholdingDetailMetadataFromDetail } from "$lib/civic-detail/presentation";
  import SeoHead from "$lib/seo/SeoHead.svelte";
  import { buildDetailRouteSeo } from "$lib/seo/head";
  import { buildBreadcrumbJsonLd, removeJsonLdContext, type JsonLdObject } from "$lib/seo/jsonld";
  import type { PageData } from "./$types";

  export let data: PageData;

  $: routeMetadata = buildOfficeholdingDetailMetadataFromDetail(data);
  $: detailRouteSeo = buildDetailRouteSeo({
    metadata: routeMetadata,
    ogType: "website",
    schemaType: "Role",
    name: data.person_name,
    pageUrl: $page.url,
    publicOrigin: env.PUBLIC_ORIGIN
  });
  $: breadcrumbCrumbs = [
    { label: "Home", href: "/" },
    { label: data.person_name }
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
<DetailPage entityType="officeholding" {data} />
