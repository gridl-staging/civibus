/** Shared head-model builders for canonical, social, and structured SEO metadata. */
import { buildSocialImageUrl, buildTrustedCanonicalUrl, getSeoDefaults } from "./defaults";
import { buildDetailRouteJsonLd, type JsonLdObject } from "./jsonld";

export type SeoMetadataInput = {
  title: string;
  description: string;
};

export type SeoOpenGraphType = "website" | "article" | "profile";

export type SeoHeadModelInput = {
  metadata: SeoMetadataInput;
  ogType: SeoOpenGraphType;
  pageUrl: URL;
  publicOrigin: string | undefined;
  imagePath?: string | null;
};

export type DetailRouteSeoInput = SeoHeadModelInput & {
  schemaType: string;
  name: string;
  sameAs?: string[] | null;
};

/** Normalized head tag payload used by Svelte route components. */
export type SeoHeadModel = {
  title: string;
  description: string;
  canonicalUrl: string | null;
  openGraph: {
    title: string;
    description: string;
    type: SeoOpenGraphType;
    url: string | null;
    image: string | null;
  };
  twitter: {
    card: string;
    title: string;
    description: string;
    image: string | null;
  };
};

export type DetailRouteSeoModel = {
  headModel: SeoHeadModel;
  jsonLd: JsonLdObject;
};

/** Builds canonical, Open Graph, and Twitter card metadata for a page. */
export function buildSeoHeadModel(input: SeoHeadModelInput): SeoHeadModel {
  const defaults = getSeoDefaults();
  const canonicalUrl = buildTrustedCanonicalUrl(input.pageUrl, input.publicOrigin);
  const imageUrl = buildSocialImageUrl(input.pageUrl, input.publicOrigin, input.imagePath);

  return {
    title: input.metadata.title,
    description: input.metadata.description,
    canonicalUrl,
    openGraph: {
      title: input.metadata.title,
      description: input.metadata.description,
      type: input.ogType,
      url: canonicalUrl,
      image: imageUrl
    },
    twitter: {
      card: defaults.twitterCard,
      title: input.metadata.title,
      description: input.metadata.description,
      image: imageUrl
    }
  };
}

export function buildDetailRouteSeo(input: DetailRouteSeoInput): DetailRouteSeoModel {
  return {
    headModel: buildSeoHeadModel(input),
    jsonLd: buildDetailRouteJsonLd({
      pageUrl: input.pageUrl,
      publicOrigin: input.publicOrigin,
      schemaType: input.schemaType,
      name: input.name,
      description: input.metadata.description,
      imagePath: input.imagePath,
      sameAs: input.sameAs
    })
  };
}
