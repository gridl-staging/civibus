import { describe, expect, it } from "vitest";
import { render } from "svelte/server";
import SeoHead from "./SeoHead.svelte";

const HEAD_MODEL = {
  title: "Jane Doe | Candidate | Civibus",
  description: "Candidate profile from campaign-finance records.",
  canonicalUrl: "https://civibus.test/candidate/jane-doe",
  openGraph: {
    title: "Jane Doe | Candidate | Civibus",
    description: "Candidate profile from campaign-finance records.",
    type: "profile" as const,
    url: "https://civibus.test/candidate/jane-doe",
    image: "https://civibus.test/og-default.png"
  },
  twitter: {
    card: "summary_large_image",
    title: "Jane Doe | Candidate | Civibus",
    description: "Candidate profile from campaign-finance records.",
    image: "https://civibus.test/og-default.png"
  }
};

describe("SeoHead", () => {
  it("renders canonical, Open Graph, and Twitter tags from one shared head model", () => {
    const rendered = render(SeoHead, {
      props: {
        headModel: HEAD_MODEL
      }
    });

    expect(rendered.head).toContain("<title>Jane Doe | Candidate | Civibus</title>");
    expect(rendered.head).toContain(
      '<meta name="description" content="Candidate profile from campaign-finance records."'
    );
    expect(rendered.head).toContain('<meta property="og:type" content="profile"');
    expect(rendered.head).toContain('<meta property="og:image" content="https://civibus.test/og-default.png"');
    expect(rendered.head).toContain('<meta name="twitter:card" content="summary_large_image"');
    expect(rendered.head).toContain('<link rel="canonical" href="https://civibus.test/candidate/jane-doe"');
    expect(rendered.head).not.toContain("application/ld+json");
  });

  it("renders one escaped JSON-LD block when JSON-LD data is provided", () => {
    const rendered = render(SeoHead, {
      props: {
        headModel: HEAD_MODEL,
        jsonLd: {
          "@context": "https://schema.org",
          "@type": "Person",
          name: "Jane <Doe>"
        }
      }
    });

    expect(rendered.head).toContain('<script type="application/ld+json">');
    expect(rendered.head).toContain('"@type":"Person"');
    expect(rendered.head).toContain('"name":"Jane \\u003cDoe>"');
  });

  it("renders an optional robots directive from the shared head model", () => {
    const rendered = render(SeoHead, {
      props: {
        headModel: {
          ...HEAD_MODEL,
          robots: "noindex"
        }
      }
    });

    expect(rendered.head).toContain('<meta name="robots" content="noindex"');
  });

  it("omits canonical and absolute media tags when the head model does not provide trusted URLs", () => {
    const rendered = render(SeoHead, {
      props: {
        headModel: {
          ...HEAD_MODEL,
          canonicalUrl: null,
          openGraph: {
            ...HEAD_MODEL.openGraph,
            url: null,
            image: null
          },
          twitter: {
            ...HEAD_MODEL.twitter,
            image: null
          }
        }
      }
    });

    expect(rendered.head).not.toContain('property="og:url"');
    expect(rendered.head).not.toContain('property="og:image"');
    expect(rendered.head).not.toContain('name="twitter:image"');
    expect(rendered.head).not.toContain('rel="canonical"');
  });
});
