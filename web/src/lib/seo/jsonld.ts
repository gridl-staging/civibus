import { APP_SHELL } from "$lib/config/app";
import { buildSocialImageUrl, buildTrustedCanonicalUrl, getTrustedPublicOrigin } from "./defaults";

type JsonLdValue =
  | string
  | number
  | boolean
  | null
  | JsonLdValue[]
  | {
      [key: string]: JsonLdValue;
    };

export type JsonLdObject = {
  [key: string]: JsonLdValue;
};

type BaseJsonLdInput = {
  pageUrl: URL;
  publicOrigin: string | undefined;
};

export type HomepageJsonLdInput = BaseJsonLdInput & {
  description?: string;
};

export type MethodologyJsonLdInput = BaseJsonLdInput & {
  description?: string;
};

export type DetailRouteJsonLdInput = BaseJsonLdInput & {
  schemaType: string;
  name: string;
  description?: string | null;
  imagePath?: string | null;
  sameAs?: string[] | null;
};

export type BreadcrumbCrumbInput = {
  label: string;
  href?: string;
};

export type BreadcrumbJsonLdInput = {
  crumbs: BreadcrumbCrumbInput[];
  publicOrigin: string | undefined;
};

function omitNullFields(record: JsonLdObject): JsonLdObject {
  return Object.fromEntries(
    Object.entries(record).filter(([, value]) => value !== null && value !== undefined)
  ) as JsonLdObject;
}

function buildBreadcrumbItemUrl(href: string, publicOrigin: string | undefined): string | null {
  const trustedOrigin = getTrustedPublicOrigin(publicOrigin);
  if (trustedOrigin === null) {
    return null;
  }

  try {
    return new URL(href, trustedOrigin).href;
  } catch {
    return null;
  }
}

export function buildHomepageJsonLd(input: HomepageJsonLdInput): JsonLdObject {
  const canonicalUrl = buildTrustedCanonicalUrl(input.pageUrl, input.publicOrigin);

  return omitNullFields({
    "@context": "https://schema.org",
    "@type": "WebSite",
    name: APP_SHELL.branding.name,
    url: canonicalUrl,
    description: APP_SHELL.staticRoutes.home.description
  });
}

export function buildMethodologyJsonLd(input: MethodologyJsonLdInput): JsonLdObject {
  const canonicalUrl = buildTrustedCanonicalUrl(input.pageUrl, input.publicOrigin);

  return omitNullFields({
    "@context": "https://schema.org",
    "@type": "Article",
    headline: APP_SHELL.staticRoutes.methodology.title,
    description: input.description ?? APP_SHELL.staticRoutes.methodology.description,
    url: canonicalUrl,
    mainEntityOfPage: canonicalUrl
  });
}

export function buildDetailRouteJsonLd(input: DetailRouteJsonLdInput): JsonLdObject {
  const canonicalUrl = buildTrustedCanonicalUrl(input.pageUrl, input.publicOrigin);
  const imageUrl = buildSocialImageUrl(input.pageUrl, input.publicOrigin, input.imagePath);

  return omitNullFields({
    "@context": "https://schema.org",
    "@type": input.schemaType,
    name: input.name,
    description: input.description ?? null,
    url: canonicalUrl,
    image: imageUrl,
    sameAs: input.sameAs ?? null
  });
}

export function buildBreadcrumbJsonLd(input: BreadcrumbJsonLdInput): JsonLdObject {
  return {
    "@type": "BreadcrumbList",
    itemListElement: input.crumbs.map((crumb, index) =>
      omitNullFields({
        "@type": "ListItem",
        position: index + 1,
        name: crumb.label,
        item: crumb.href ? buildBreadcrumbItemUrl(crumb.href, input.publicOrigin) : null
      })
    )
  };
}

export function removeJsonLdContext(jsonLd: JsonLdObject): JsonLdObject {
  const { "@context": _context, ...rest } = jsonLd;
  return rest;
}

export function serializeJsonLd(jsonLd: JsonLdObject): string {
  // Escape opening angle brackets so embedded JSON-LD cannot terminate the script tag.
  return JSON.stringify(jsonLd).replaceAll("<", "\\u003c");
}
