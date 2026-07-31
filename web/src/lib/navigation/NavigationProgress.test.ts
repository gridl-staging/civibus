import { describe, expect, it } from "vitest";
import { render } from "svelte/server";
import NavigationProgress from "./NavigationProgress.svelte";

describe("NavigationProgress", () => {
  it("keeps the inactive visual indicator out of the accessibility tree", () => {
    const rendered = render(NavigationProgress, {
      props: {
        isNavigating: false
      }
    });

    expect(rendered.body).toContain('aria-hidden="true"');
    expect(rendered.body).not.toContain('role="progressbar"');
    expect(rendered.body).not.toContain("aria-value");
    expect(rendered.body).not.toContain("aria-busy");
    expect(rendered.body).not.toContain("navigation-progress--active");
  });

  it("keeps the active visual indicator out of the accessibility tree", () => {
    const rendered = render(NavigationProgress, {
      props: {
        isNavigating: true
      }
    });

    expect(rendered.body).toContain('aria-hidden="true"');
    expect(rendered.body).not.toContain('role="progressbar"');
    expect(rendered.body).not.toContain("aria-value");
    expect(rendered.body).not.toContain("aria-busy");
    expect(rendered.body).toContain("navigation-progress--active");
  });
});
