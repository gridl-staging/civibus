<script lang="ts">
  import { env } from "$env/dynamic/public";
  import { page } from "$app/stores";
  import Breadcrumb from "$lib/breadcrumb/Breadcrumb.svelte";
  import DetailPage from "$lib/campaign-finance-detail/DetailPage.svelte";
  import {
    buildCandidateDetailMetadata,
    buildCandidateRoutePresentation,
    type CandidateDetailRoutePresentation
  } from "$lib/campaign-finance-detail/presentation";
  import SeoHead from "$lib/seo/SeoHead.svelte";
  import { buildDetailRouteSeo, type DetailRouteSeoModel } from "$lib/seo/head";
  import { buildBreadcrumbJsonLd, removeJsonLdContext, type JsonLdObject } from "$lib/seo/jsonld";
  import type { PageData } from "./$types";

  export let data: PageData;

  let routePresentation: CandidateDetailRoutePresentation;
  let detailRouteSeo: DetailRouteSeoModel | null = null;
  let detailPageJsonLd: JsonLdObject | null = null;
  let canonicalName: string | null = null;

  $: routePresentation = buildCandidateRoutePresentation(data as Parameters<typeof buildCandidateRoutePresentation>[0]);
  $: canonicalName =
    routePresentation.routeKind === "canonical-detail" ? routePresentation.shell.canonicalName : null;

  $: breadcrumbCrumbs = routePresentation.routeKind === "canonical-detail"
    ? [{ label: "Home", href: "/" }, { label: routePresentation.shell.canonicalName }]
    : [{ label: "Home", href: "/" }, { label: "Candidates" }];

  $: if (canonicalName !== null) {
    const metadata = buildCandidateDetailMetadata(canonicalName);

    detailRouteSeo = buildDetailRouteSeo({
      metadata,
      ogType: "profile",
      schemaType: "Person",
      name: canonicalName,
      pageUrl: $page.url,
      publicOrigin: env.PUBLIC_ORIGIN
    });

    const breadcrumbJsonLd = buildBreadcrumbJsonLd({
      crumbs: breadcrumbCrumbs,
      publicOrigin: env.PUBLIC_ORIGIN
    });
    detailPageJsonLd = {
      "@context": "https://schema.org",
      "@graph": [removeJsonLdContext(detailRouteSeo.jsonLd), breadcrumbJsonLd]
    } as JsonLdObject;
  } else {
    detailRouteSeo = null;
    detailPageJsonLd = null;
  }
</script>

{#if detailRouteSeo !== null && detailPageJsonLd !== null}
  <SeoHead headModel={detailRouteSeo.headModel} jsonLd={detailPageJsonLd} />
{/if}

<Breadcrumb crumbs={breadcrumbCrumbs} />
<DetailPage presentation={routePresentation} />
