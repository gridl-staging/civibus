import { beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "svelte/server";

type NavigatingValue = null | {
  from: { url: URL } | null;
  to: { url: URL } | null;
};

let currentNavigating: NavigatingValue = null;

vi.mock("$app/stores", () => ({
  navigating: {
    subscribe(run: (value: NavigatingValue) => void): () => void {
      run(currentNavigating);
      return () => {};
    }
  }
}));

import ListNavigationLoading from "./ListNavigationLoading.svelte";

describe("ListNavigationLoading", () => {
  beforeEach(() => {
    currentNavigating = null;
  });

  it("is hidden when navigating is null", () => {
    currentNavigating = null;
    const rendered = render(ListNavigationLoading, {
      props: {
        routePath: "/candidates",
        filterParams: ["state", "office"],
        label: "Updating results…"
      }
    });

    expect(rendered.body).not.toContain("Updating results");
  });

  it("keeps a non-announcing container mounted while inactive to avoid layout shift", () => {
    currentNavigating = null;
    const rendered = render(ListNavigationLoading, {
      props: {
        routePath: "/candidates",
        filterParams: ["state", "office"],
        label: "Updating results…"
      }
    });

    expect(rendered.body).toContain("list-navigation-loading-region");
    expect(rendered.body).toContain('aria-hidden="true"');
    expect(rendered.body).not.toContain('role="status"');
  });

  it("shows indicator during same-route filter navigation", () => {
    currentNavigating = {
      from: { url: new URL("https://civibus.test/candidates?state=NC") },
      to: { url: new URL("https://civibus.test/candidates?state=GA") }
    };
    const rendered = render(ListNavigationLoading, {
      props: {
        routePath: "/candidates",
        filterParams: ["state", "office"],
        label: "Updating results…"
      }
    });

    expect(rendered.body).toContain("Updating results");
    expect(rendered.body).toContain('role="status"');
    expect(rendered.body).toContain('aria-live="polite"');
  });

  it("stays hidden for outbound navigation to a different route", () => {
    currentNavigating = {
      from: { url: new URL("https://civibus.test/candidates") },
      to: { url: new URL("https://civibus.test/candidate/jane-candidate") }
    };
    const rendered = render(ListNavigationLoading, {
      props: {
        routePath: "/candidates",
        filterParams: ["state", "office"],
        label: "Updating results…"
      }
    });

    expect(rendered.body).not.toContain("Updating results");
  });

  it("stays hidden for same-route pagination-only query change", () => {
    currentNavigating = {
      from: { url: new URL("https://civibus.test/candidates?state=NC&offset=0&limit=25") },
      to: { url: new URL("https://civibus.test/candidates?state=NC&offset=25&limit=25") }
    };
    const rendered = render(ListNavigationLoading, {
      props: {
        routePath: "/candidates",
        filterParams: ["state", "office"],
        label: "Updating results…"
      }
    });

    expect(rendered.body).not.toContain("Updating results");
  });

  it("shows indicator when a filter param is added on same route", () => {
    currentNavigating = {
      from: { url: new URL("https://civibus.test/candidates") },
      to: { url: new URL("https://civibus.test/candidates?office=S") }
    };
    const rendered = render(ListNavigationLoading, {
      props: {
        routePath: "/candidates",
        filterParams: ["state", "office"],
        label: "Updating results…"
      }
    });

    expect(rendered.body).toContain("Updating results");
  });

  it("shows indicator when a filter param is removed (cleared)", () => {
    currentNavigating = {
      from: { url: new URL("https://civibus.test/candidates?state=NC&office=S") },
      to: { url: new URL("https://civibus.test/candidates") }
    };
    const rendered = render(ListNavigationLoading, {
      props: {
        routePath: "/candidates",
        filterParams: ["state", "office"],
        label: "Updating results…"
      }
    });

    expect(rendered.body).toContain("Updating results");
  });

  it("works with committee filter params", () => {
    currentNavigating = {
      from: { url: new URL("https://civibus.test/committees?state=NC") },
      to: { url: new URL("https://civibus.test/committees?state=NC&committee_type=Q") }
    };
    const rendered = render(ListNavigationLoading, {
      props: {
        routePath: "/committees",
        filterParams: ["state", "committee_type"],
        label: "Updating results…"
      }
    });

    expect(rendered.body).toContain("Updating results");
  });

  it("stays hidden when navigating.from is null", () => {
    currentNavigating = {
      from: null,
      to: { url: new URL("https://civibus.test/candidates?state=NC") }
    };
    const rendered = render(ListNavigationLoading, {
      props: {
        routePath: "/candidates",
        filterParams: ["state", "office"],
        label: "Updating results…"
      }
    });

    expect(rendered.body).not.toContain("Updating results");
  });

  it("stays hidden when navigating.to is null", () => {
    currentNavigating = {
      from: { url: new URL("https://civibus.test/candidates?state=NC") },
      to: null
    };
    const rendered = render(ListNavigationLoading, {
      props: {
        routePath: "/candidates",
        filterParams: ["state", "office"],
        label: "Updating results…"
      }
    });

    expect(rendered.body).not.toContain("Updating results");
  });
});
