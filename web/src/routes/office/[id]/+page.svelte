<script lang="ts">
  import { env } from "$env/dynamic/public";
  import { page } from "$app/stores";
  import Breadcrumb from "$lib/breadcrumb/Breadcrumb.svelte";
  import { buildMapLayerVisibilityDefaults } from "$lib/config/app";
  import DetailPage from "$lib/civic-detail/DetailPage.svelte";
  import { buildOfficeDetailMetadataFromDetail } from "$lib/civic-detail/presentation";
  import SeoHead from "$lib/seo/SeoHead.svelte";
  import { buildDetailRouteSeo } from "$lib/seo/head";
  import { buildBreadcrumbJsonLd, removeJsonLdContext, type JsonLdObject } from "$lib/seo/jsonld";
  import type { PageData } from "./$types";

  export let data: PageData;

  $: routeMetadata = buildOfficeDetailMetadataFromDetail(data.office);
  $: detailRouteSeo = buildDetailRouteSeo({
    metadata: routeMetadata,
    ogType: "website",
    schemaType: "GovernmentOffice",
    name: data.office.name,
    pageUrl: $page.url,
    publicOrigin: env.PUBLIC_ORIGIN
  });
  $: breadcrumbCrumbs = [
    { label: "Home", href: "/" },
    { label: data.office.name }
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
  $: officeMap = {
    pageLevel: "state" as const,
    layerVisibility: buildMapLayerVisibilityDefaults("state"),
    geometryByLevel: data.geometryByLevel ?? {},
    stateCode: data.office.selected_electoral_division_state?.toUpperCase() ?? null
  };
</script>

<SeoHead headModel={detailRouteSeo.headModel} jsonLd={detailPageJsonLd} />

<Breadcrumb crumbs={breadcrumbCrumbs} />
<DetailPage entityType="office" data={data.office} contestMap={officeMap} />
