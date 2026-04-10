import { describe, expect, it } from "vitest";
import { render } from "svelte/server";
import SkeletonPanel from "./SkeletonPanel.svelte";

describe("SkeletonPanel", () => {
  it("renders an accessible busy panel with skeleton rows", () => {
    const rendered = render(SkeletonPanel, {
      props: {
        label: "Graph relationships"
      }
    });

    expect(rendered.body).toContain('class="skeleton-panel"');
    expect(rendered.body).toContain('aria-label="Graph relationships"');
    expect(rendered.body).toContain('aria-busy="true"');
    expect(rendered.body).toContain("skeleton-panel__line");
  });

  it("renders the requested number of skeleton lines", () => {
    const rendered = render(SkeletonPanel, {
      props: {
        label: "Entity internals",
        lines: 5
      }
    });

    expect((rendered.body.match(/skeleton-panel__line/g) ?? []).length).toBe(5);
  });

  it("defaults to four skeleton lines when lines prop is omitted", () => {
    const rendered = render(SkeletonPanel, {
      props: {
        label: "Civic Record"
      }
    });

    expect((rendered.body.match(/skeleton-panel__line/g) ?? []).length).toBe(4);
  });
});
