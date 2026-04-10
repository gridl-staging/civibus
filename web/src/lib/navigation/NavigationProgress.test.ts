import { describe, expect, it } from "vitest";
import { render } from "svelte/server";
import NavigationProgress from "./NavigationProgress.svelte";

describe("NavigationProgress", () => {
  it("renders an accessible inactive progressbar state", () => {
    const rendered = render(NavigationProgress, {
      props: {
        isNavigating: false
      }
    });

    expect(rendered.body).toContain('role="progressbar"');
    expect(rendered.body).toContain('aria-valuemin="0"');
    expect(rendered.body).toContain('aria-valuemax="100"');
    expect(rendered.body).toContain('aria-valuenow="0"');
    expect(rendered.body).toContain('aria-busy="false"');
    expect(rendered.body).not.toContain("navigation-progress--active");
  });

  it("renders an active progressbar state while navigating", () => {
    const rendered = render(NavigationProgress, {
      props: {
        isNavigating: true
      }
    });

    expect(rendered.body).toContain('aria-busy="true"');
    expect(rendered.body).toContain('aria-valuenow="100"');
    expect(rendered.body).toContain("navigation-progress--active");
  });
});
