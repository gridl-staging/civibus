import { describe, expect, it } from "vitest";
import { render } from "svelte/server";
import Breadcrumb from "./Breadcrumb.svelte";

describe("Breadcrumb", () => {
  it("renders accessible breadcrumb markup with linked and current crumbs", () => {
    const rendered = render(Breadcrumb, {
      props: {
        crumbs: [
          { label: "Home", href: "/" },
          { label: "People", href: "/search?entityType=person" },
          { label: "Jane Doe" }
        ]
      }
    });

    expect(rendered.body).toContain('<nav aria-label="Breadcrumb"');
    expect(rendered.body).toContain("<ol");
    expect(rendered.body).toContain('<a href="/">Home</a>');
    expect(rendered.body).toContain('<a href="/search?entityType=person">People</a>');
    expect(rendered.body).toContain('aria-current="page"');
    expect(rendered.body).toContain("Jane Doe");
  });
});
