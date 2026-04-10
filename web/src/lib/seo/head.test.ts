import { describe, expect, it } from "vitest";
import { buildDetailRouteSeo, buildSeoHeadModel } from "./head";

function fakePageUrl(href: string): URL {
  return new URL(href);
}

describe("buildSeoHeadModel", () => {
  it("composes route-owned title/description with canonical and fallback social defaults", () => {
    const headModel = buildSeoHeadModel({
      metadata: {
        title: "Jane Doe | Candidate | Civibus",
        description: "Candidate profile from campaign-finance records."
      },
      ogType: "profile",
      pageUrl: fakePageUrl("https://internal.host:5173/candidate/jane-doe?tab=transactions"),
      publicOrigin: "https://civibus.us"
    });

    expect(headModel).toEqual({
      title: "Jane Doe | Candidate | Civibus",
      description: "Candidate profile from campaign-finance records.",
      canonicalUrl: "https://civibus.us/candidate/jane-doe",
      openGraph: {
        title: "Jane Doe | Candidate | Civibus",
        description: "Candidate profile from campaign-finance records.",
        type: "profile",
        url: "https://civibus.us/candidate/jane-doe",
        image: "https://civibus.us/og-default.png"
      },
      twitter: {
        card: "summary_large_image",
        title: "Jane Doe | Candidate | Civibus",
        description: "Candidate profile from campaign-finance records.",
        image: "https://civibus.us/og-default.png"
      }
    });
  });

  it("omits canonical and absolute media URLs when no trusted public origin is configured", () => {
    const headModel = buildSeoHeadModel({
      metadata: {
        title: "Jane Doe | Candidate | Civibus",
        description: "Candidate profile from campaign-finance records."
      },
      ogType: "profile",
      pageUrl: fakePageUrl("https://preview.internal:5173/candidate/jane-doe?tab=transactions"),
      publicOrigin: undefined
    });

    expect(headModel).toEqual({
      title: "Jane Doe | Candidate | Civibus",
      description: "Candidate profile from campaign-finance records.",
      canonicalUrl: null,
      openGraph: {
        title: "Jane Doe | Candidate | Civibus",
        description: "Candidate profile from campaign-finance records.",
        type: "profile",
        url: null,
        image: null
      },
      twitter: {
        card: "summary_large_image",
        title: "Jane Doe | Candidate | Civibus",
        description: "Candidate profile from campaign-finance records.",
        image: null
      }
    });
  });
});

describe("buildDetailRouteSeo", () => {
  it("builds the shared head model and detail JSON-LD from one route-owned input object", () => {
    const detailSeo = buildDetailRouteSeo({
      metadata: {
        title: "Jane Doe | Candidate | Civibus",
        description: "Candidate profile from campaign-finance records."
      },
      ogType: "profile",
      schemaType: "Person",
      name: "Jane Doe",
      pageUrl: fakePageUrl("https://internal.host:5173/candidate/jane-doe?tab=transactions"),
      publicOrigin: "https://civibus.us"
    });

    expect(detailSeo).toEqual({
      headModel: {
        title: "Jane Doe | Candidate | Civibus",
        description: "Candidate profile from campaign-finance records.",
        canonicalUrl: "https://civibus.us/candidate/jane-doe",
        openGraph: {
          title: "Jane Doe | Candidate | Civibus",
          description: "Candidate profile from campaign-finance records.",
          type: "profile",
          url: "https://civibus.us/candidate/jane-doe",
          image: "https://civibus.us/og-default.png"
        },
        twitter: {
          card: "summary_large_image",
          title: "Jane Doe | Candidate | Civibus",
          description: "Candidate profile from campaign-finance records.",
          image: "https://civibus.us/og-default.png"
        }
      },
      jsonLd: {
        "@context": "https://schema.org",
        "@type": "Person",
        name: "Jane Doe",
        description: "Candidate profile from campaign-finance records.",
        url: "https://civibus.us/candidate/jane-doe",
        image: "https://civibus.us/og-default.png"
      }
    });
  });
});
