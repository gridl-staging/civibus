import { render } from "svelte/server";
import { describe, expect, it } from "vitest";

import ComparisonBar from "./ComparisonBar.svelte";
import { FINANCE_CHART_COLORS } from "./finance";

describe("ComparisonBar SSR presentation component", () => {
  it("preserves caller order and renders linked and unlinked entity labels", () => {
    const rendered = render(ComparisonBar, {
      props: {
        scaleMax: 300_000,
        entities: [
          {
            id: "person_b",
            label: "Beta Senator",
            href: "/person/person_b",
            linkTestId: "beta-profile-link",
            value: 125_000,
            valueLabel: "$125,000.00"
          },
          {
            id: "person_a",
            label: "Alpha Representative",
            value: 300_000,
            valueLabel: "$300,000 exact"
          }
        ]
      }
    });

    expect(rendered.body.indexOf('data-testid="comparison-row-person_b"')).toBeLessThan(
      rendered.body.indexOf('data-testid="comparison-row-person_a"')
    );
    expect(rendered.body).toMatch(/<a[^>]*href="\/person\/person_b"[^>]*>Beta Senator<\/a>/);
    expect(rendered.body).toContain('data-testid="beta-profile-link"');
    expect(rendered.body).toMatch(/<span[^>]*>Alpha Representative<\/span>/);
    expect(rendered.body).toContain('data-testid="comparison-bar-person_b"');
    expect(rendered.body).toContain('data-testid="comparison-end-label-person_a"');
    expect(rendered.body).toContain("$300,000 exact");
    expect(rendered.body).not.toContain("$300.0K");
  });

  it("renders unsafe or external href values as plain text", () => {
    const rendered = render(ComparisonBar, {
      props: {
        scaleMax: 100,
        entities: [
          {
            id: "person_script",
            label: "Script Scheme",
            href: "javascript:alert(document.domain)",
            value: 100,
            valueLabel: "$100.00"
          },
          {
            id: "person_external",
            label: "External Origin",
            href: "//attacker.example/person_external",
            value: 50,
            valueLabel: "$50.00"
          }
        ]
      }
    });

    expect(rendered.body).not.toContain("javascript:");
    expect(rendered.body).not.toContain("attacker.example");
    expect(rendered.body).not.toMatch(/<a[^>]*>Script Scheme<\/a>/);
    expect(rendered.body).not.toMatch(/<a[^>]*>External Origin<\/a>/);
    expect(rendered.body).toMatch(/<span[^>]*>Script Scheme<\/span>/);
    expect(rendered.body).toMatch(/<span[^>]*>External Origin<\/span>/);
  });

  it("replaces unsafe segment colors instead of emitting injected CSS declarations", () => {
    const rendered = render(ComparisonBar, {
      props: {
        scaleMax: 100,
        entities: [
          {
            id: "person_unsafe_color",
            label: "Unsafe Color",
            value: 100,
            valueLabel: "$100.00",
            segments: [
              {
                id: "unsafe",
                label: "Unsafe",
                value: 100,
                color: "red; background-image: url(https://attacker.example/pixel)"
              }
            ]
          }
        ]
      }
    });

    expect(rendered.body).not.toContain("background-image");
    expect(rendered.body).not.toContain("attacker.example");
    expect(rendered.body).toContain(
      `--comparison-segment-fill: ${FINANCE_CHART_COLORS.neutral}`
    );
  });

  it("rejects an unsafe caller-computed width instead of emitting CSS declarations", () => {
    const rendered = render(ComparisonBar, {
      props: {
        scaleMax: "100",
        entities: [
          {
            id: "person_unsafe_width",
            label: "Unsafe Width",
            value: "100",
            valueLabel: "$100.00",
            widthPercentage: "100%; background-image: url(https://attacker.example/pixel)"
          }
        ]
      }
    });

    expect(rendered.body).not.toContain("background-image");
    expect(rendered.body).not.toContain("attacker.example");
    expect(rendered.body).not.toContain('data-testid="comparison-bar-person_unsafe_width"');
    expect(rendered.body).toContain("No reported/loaded money.");
  });

  it("renders exact shared-scale widths and caller-supplied end labels", () => {
    const rendered = render(ComparisonBar, {
      props: {
        scaleMax: 300_000,
        entities: [
          {
            id: "person_full_scale",
            label: "Full Scale Official",
            value: 300_000,
            valueLabel: "$300,000 exact caller label"
          },
          {
            id: "person_one_third",
            label: "One Third Official",
            value: 100_000,
            valueLabel: "$100,000 exact caller label"
          }
        ]
      }
    });

    function getOpeningTag(testId: string): string {
      const openingTag = rendered.body.match(
        new RegExp(`<[^>]+data-testid="${testId}"[^>]*>`)
      )?.[0];
      expect(openingTag).toBeDefined();
      return openingTag ?? "";
    }

    function getTrackWidth(entityId: string): string {
      const openingTag = getOpeningTag(`comparison-bar-${entityId}`);
      const inlineStyle = openingTag.match(/\bstyle="([^"]*)"/)?.[1];
      expect(inlineStyle).toBeDefined();

      const declaration = inlineStyle
        ?.split(";")
        .map((candidate) => candidate.trim())
        .find((candidate) => candidate.startsWith("--comparison-track-width:"));
      expect(declaration).toBeDefined();
      return declaration?.slice("--comparison-track-width:".length).trim() ?? "";
    }

    function getEndLabel(entityId: string): string {
      const testId = `comparison-end-label-${entityId}`;
      const innerHtml = rendered.body.match(
        new RegExp(`<span[^>]+data-testid="${testId}"[^>]*>([\\s\\S]*?)<\\/span>`)
      )?.[1];
      expect(innerHtml).toBeDefined();
      return innerHtml?.replace(/<!--[\s\S]*?-->/g, "").trim() ?? "";
    }

    expect(getTrackWidth("person_full_scale")).toBe("100%");
    expect(getTrackWidth("person_one_third")).toBe("33.33333333333333%");
    expect(getEndLabel("person_full_scale")).toBe("$300,000 exact caller label");
    expect(getEndLabel("person_one_third")).toBe("$100,000 exact caller label");
    expect(rendered.body).not.toContain("$300K");
    expect(rendered.body).not.toContain("$100K");
  });

  it("renders caller-computed exact decimal widths without narrowing money values", () => {
    const rendered = render(ComparisonBar, {
      props: {
        scaleMax: 0,
        entities: [
          {
            id: "person_close_lower",
            label: "Close Lower",
            value: "9007199254740993.01",
            valueLabel: "$9,007,199,254,740,993.01",
            widthPercentage: "99.999999999999999889%"
          },
          {
            id: "person_close_higher",
            label: "Close Higher",
            value: "9007199254740993.02",
            valueLabel: "$9,007,199,254,740,993.02",
            widthPercentage: "100%"
          },
          {
            id: "person_overflow_half",
            label: "Overflow Half",
            value: "1e400",
            valueLabel: `$10${",000".repeat(133)}.00`,
            widthPercentage: "50%"
          }
        ]
      }
    });

    expect(rendered.body).toContain("--comparison-track-width: 99.999999999999999889%");
    expect(rendered.body).toContain("--comparison-track-width: 100%");
    expect(rendered.body).toContain("--comparison-track-width: 50%");
    expect(rendered.body).toContain("$9,007,199,254,740,993.01");
    expect(rendered.body).toContain("$9,007,199,254,740,993.02");
  });

  it("delegates image and initials fallback rendering to the shared Portrait component", () => {
    const rendered = render(ComparisonBar, {
      props: {
        scaleMax: 20_000,
        entities: [
          {
            id: "person_image",
            label: "Image Official",
            portrait: {
              status: "available",
              rights_status: "public_domain",
              source_image_url: "https://example.test/image-official.jpg",
              mime_type: "image/jpeg",
              width_px: 300,
              height_px: 300
            },
            value: 20_000,
            valueLabel: "$20,000.00"
          },
          {
            id: "person_initials",
            label: "Initials Official",
            portrait: null,
            value: 10_000,
            valueLabel: "$10,000.00"
          }
        ]
      }
    });

    expect(rendered.body).toContain('data-testid="entity-portrait-image"');
    expect(rendered.body).toContain('alt="Portrait of Image Official"');
    expect(rendered.body).toContain('data-testid="entity-portrait-initials"');
    expect(rendered.body).toContain(">IO<");
    expect(rendered.body).not.toContain("comparison-portrait-fallback");
  });

  it("renders caller-ordered segments with transform-built tooltip text and colors", () => {
    const rendered = render(ComparisonBar, {
      props: {
        scaleMax: 100_000,
        entities: [
          {
            id: "person_segments",
            label: "Segmented Official",
            value: 100_000,
            valueLabel: "$100,000.00",
            segments: [
              {
                id: "other",
                label: "Other Donations",
                value: 75_000,
                color: FINANCE_CHART_COLORS.support
              },
              {
                id: "self",
                label: "Self-Funded",
                value: 25_000,
                color: "#6fada8"
              }
            ]
          }
        ],
        segmentOrder: ["Self-Funded", "Other Donations"]
      }
    });

    expect(rendered.body.indexOf('data-testid="comparison-segment-person_segments-self"')).toBeLessThan(
      rendered.body.indexOf('data-testid="comparison-segment-person_segments-other"')
    );
    expect(rendered.body).toContain('title="$25,000.00 (25.0%)"');
    expect(rendered.body).toContain('title="$75,000.00 (75.0%)"');
    expect(rendered.body).toContain("--comparison-segment-width: 25%");
    expect(rendered.body).toContain(`--comparison-segment-fill: #6fada8`);
    expect(rendered.body).toContain(`--comparison-segment-fill: ${FINANCE_CHART_COLORS.support}`);
  });

  it("renders honest no-data copy for missing money without fabricating a bar or value label", () => {
    const rendered = render(ComparisonBar, {
      props: {
        scaleMax: 100_000,
        entities: [
          {
            id: "person_missing",
            label: "Missing Official",
            href: "/person/person_missing",
            value: null,
            valueLabel: "$123,456.00",
            segments: [
              {
                id: "self",
                label: "Self-Funded",
                value: 0,
                color: "#6fada8"
              }
            ]
          },
          {
            id: "person_unavailable",
            label: "Unavailable Official",
            href: "/person/person_unavailable",
            value: null,
            valueLabel: "$999,999.00",
            showMissingValueLabel: false
          }
        ],
        segmentOrder: ["Self-Funded"]
      }
    });

    expect(rendered.body).toContain('data-testid="comparison-row-person_missing"');
    expect(rendered.body).toContain('data-testid="comparison-end-label-person_missing"');
    expect(rendered.body).toContain('data-testid="comparison-row-person_unavailable"');
    expect(rendered.body).toContain('data-testid="comparison-end-label-person_unavailable"');
    expect(rendered.body).toContain("No reported/loaded money.");
    expect(rendered.body.match(/No reported\/loaded money\./g)).toHaveLength(1);
    expect(rendered.body).not.toContain('data-testid="comparison-bar-person_missing"');
    expect(rendered.body).not.toContain('data-testid="comparison-bar-person_unavailable"');
    expect(rendered.body).not.toContain('data-testid="comparison-segment-person_missing-self"');
    expect(rendered.body).not.toContain("$123,456.00");
    expect(rendered.body).not.toContain("$999,999.00");
  });

  it("renders a reported zero with its caller value label and bar rather than no-data copy", () => {
    const rendered = render(ComparisonBar, {
      props: {
        scaleMax: 100_000,
        entities: [
          {
            id: "person_zero",
            label: "Zero Official",
            href: "/person/person_zero",
            value: 0,
            valueLabel: "$0.00",
            segments: [
              {
                id: "self",
                label: "Self-Funded",
                value: 0,
                color: "#6fada8"
              }
            ]
          }
        ],
        segmentOrder: ["Self-Funded"]
      }
    });

    expect(rendered.body).toContain('data-testid="comparison-row-person_zero"');
    expect(rendered.body).toContain('data-testid="comparison-bar-person_zero"');
    expect(rendered.body).toContain('data-testid="comparison-end-label-person_zero"');
    expect(rendered.body).toContain("$0.00");
    expect(rendered.body).not.toContain("No reported/loaded money.");
    expect(rendered.body).not.toContain('data-testid="comparison-segment-person_zero-self"');
  });
});
