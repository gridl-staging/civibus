import { describe, expect, it } from "vitest";
import { render } from "svelte/server";
import Portrait from "./Portrait.svelte";

describe("portrait fallback rendering", () => {
  it("renders deterministic initials when personId is present and no portrait URL is available", () => {
    const rendered = render(Portrait, {
      props: {
        personId: "11111111-1111-4111-8111-111111111111",
        canonicalName: "Jane A Doe",
        portrait: null
      }
    });

    expect(rendered.body).toContain('data-testid="entity-portrait-initials"');
    expect(rendered.body).toContain(">JD<");
    expect(rendered.body).not.toContain("No image");
  });

  it("keeps the no-image fallback for non-person contexts (personId absent)", () => {
    const rendered = render(Portrait, {
      props: {
        canonicalName: "Civibus Action Org",
        portrait: null
      }
    });

    expect(rendered.body).toContain('data-testid="entity-portrait-silhouette"');
    expect(rendered.body).toContain("No image");
  });

  it("derives initials from first and family name when canonical name ends with JR suffix", () => {
    const rendered = render(Portrait, {
      props: {
        personId: "11111111-1111-4111-8111-111111111111",
        canonicalName: "John Smith Jr",
        portrait: null
      }
    });

    expect(rendered.body).toContain('data-testid="entity-portrait-initials"');
    expect(rendered.body).toContain(">JS<");
  });

  it("derives initials from first and family name when canonical name ends with III suffix", () => {
    const rendered = render(Portrait, {
      props: {
        personId: "11111111-1111-4111-8111-111111111111",
        canonicalName: "Mary Jones III",
        portrait: null
      }
    });

    expect(rendered.body).toContain('data-testid="entity-portrait-initials"');
    expect(rendered.body).toContain(">MJ<");
  });
});
