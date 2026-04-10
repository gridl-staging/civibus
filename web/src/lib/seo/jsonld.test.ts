import { describe, expect, it } from "vitest";
import { APP_SHELL } from "$lib/config/app";
import {
  buildBreadcrumbJsonLd,
  buildDetailRouteJsonLd,
  buildHomepageJsonLd,
  buildMethodologyJsonLd,
  removeJsonLdContext,
  serializeJsonLd
} from "./jsonld";

function fakePageUrl(href: string): URL {
  return new URL(href);
}

describe("buildHomepageJsonLd", () => {
  it("returns a plain, serializable WebSite payload with absolute URL fields", () => {
    const jsonLd = buildHomepageJsonLd({
      pageUrl: fakePageUrl("https://internal.host:5173/?utm_source=test"),
      publicOrigin: "https://civibus.us"
    });

    expect(jsonLd).toEqual({
      "@context": "https://schema.org",
      "@type": "WebSite",
      name: APP_SHELL.branding.name,
      url: "https://civibus.us/",
      description: APP_SHELL.staticRoutes.home.description
    });
    expect(JSON.parse(JSON.stringify(jsonLd))).toEqual(jsonLd);
  });
});

describe("buildMethodologyJsonLd", () => {
  it("returns a plain, serializable Article payload with absolute URL fields", () => {
    const jsonLd = buildMethodologyJsonLd({
      pageUrl: fakePageUrl("https://internal.host:5173/methodology?ref=nav"),
      publicOrigin: "https://civibus.us"
    });

    expect(jsonLd).toEqual({
      "@context": "https://schema.org",
      "@type": "Article",
      headline: APP_SHELL.staticRoutes.methodology.title,
      description: APP_SHELL.staticRoutes.methodology.description,
      url: "https://civibus.us/methodology",
      mainEntityOfPage: "https://civibus.us/methodology"
    });
    expect(JSON.parse(JSON.stringify(jsonLd))).toEqual(jsonLd);
  });
});

describe("buildDetailRouteJsonLd", () => {
  it("omits null fields while preserving absolute canonical URL output", () => {
    const jsonLd = buildDetailRouteJsonLd({
      schemaType: "ProfilePage",
      name: "Jane Doe | Candidate | Civibus",
      description: "Candidate profile from campaign-finance records.",
      pageUrl: fakePageUrl("https://internal.host:5173/candidate/jane-doe?tab=summary"),
      publicOrigin: "https://civibus.us",
      imagePath: null,
      sameAs: null
    });

    expect(jsonLd).toEqual({
      "@context": "https://schema.org",
      "@type": "ProfilePage",
      name: "Jane Doe | Candidate | Civibus",
      description: "Candidate profile from campaign-finance records.",
      url: "https://civibus.us/candidate/jane-doe"
    });
    expect(JSON.parse(JSON.stringify(jsonLd))).toEqual(jsonLd);
  });

  it("omits origin-derived URL fields when no trusted public origin is configured", () => {
    const jsonLd = buildDetailRouteJsonLd({
      schemaType: "ProfilePage",
      name: "Jane Doe | Candidate | Civibus",
      description: "Candidate profile from campaign-finance records.",
      pageUrl: fakePageUrl("https://preview.internal:5173/candidate/jane-doe?tab=summary"),
      publicOrigin: undefined
    });

    expect(jsonLd).toEqual({
      "@context": "https://schema.org",
      "@type": "ProfilePage",
      name: "Jane Doe | Candidate | Civibus",
      description: "Candidate profile from campaign-finance records."
    });
  });
});

describe("buildBreadcrumbJsonLd", () => {
  it("returns a BreadcrumbList with absolute URLs for linked crumbs", () => {
    const jsonLd = buildBreadcrumbJsonLd({
      crumbs: [
        { label: "Home", href: "/" },
        { label: "People", href: "/search?entityType=person" },
        { label: "Jane Doe" }
      ],
      publicOrigin: "https://civibus.us"
    });

    expect(jsonLd).toEqual({
      "@type": "BreadcrumbList",
      itemListElement: [
        {
          "@type": "ListItem",
          position: 1,
          name: "Home",
          item: "https://civibus.us/"
        },
        {
          "@type": "ListItem",
          position: 2,
          name: "People",
          item: "https://civibus.us/search?entityType=person"
        },
        {
          "@type": "ListItem",
          position: 3,
          name: "Jane Doe"
        }
      ]
    });
  });
});

describe("removeJsonLdContext", () => {
  it("drops the top-level @context field while preserving the remaining JSON-LD payload", () => {
    expect(
      removeJsonLdContext({
        "@context": "https://schema.org",
        "@type": "Person",
        name: "Jane Doe"
      })
    ).toEqual({
      "@type": "Person",
      name: "Jane Doe"
    });
  });
});

describe("serializeJsonLd", () => {
  it("escapes opening angle brackets so JSON-LD cannot terminate its script tag", () => {
    expect(
      serializeJsonLd({
        "@context": "https://schema.org",
        name: "</script><script>alert(1)</script>"
      })
    ).toContain('"name":"\\u003c/script>\\u003cscript>alert(1)\\u003c/script>"');
  });
});
