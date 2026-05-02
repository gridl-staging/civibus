import { describe, expect, it } from "vitest";
import { render } from "svelte/server";
import LayerToggle from "./LayerToggle.svelte";

describe("LayerToggle", () => {
  it("renders always-on layers as checked and disabled checkboxes", () => {
    const rendered = render(LayerToggle, {
      props: {
        pageLevel: "state",
        layerVisibility: {
          nc_statewide_boundary: true,
          nc_county_boundaries: true,
          nc_congressional_districts: false
        }
      }
    });

    expect(rendered.body).toContain('data-layer-id="nc_statewide_boundary"');
    expect(rendered.body).toMatch(
      /<input[^>]*id="layer-toggle-nc_statewide_boundary"[^>]*(checked[^>]*disabled|disabled[^>]*checked)/
    );
  });

  it("filters layer controls by applicable page levels", () => {
    const rendered = render(LayerToggle, {
      props: {
        pageLevel: "county",
        layerVisibility: {
          nc_statewide_boundary: true,
          nc_county_boundaries: true,
          nc_congressional_districts: false
        }
      }
    });

    expect(rendered.body).toContain("County boundaries");
    expect(rendered.body).toContain("Congressional districts");
    expect(rendered.body).not.toContain("State boundary");
  });
});
