import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { render } from "svelte/server";

import Chart from "./Chart.svelte";
import type { ChartProps } from "./types";

const chartSource = readFileSync(
  resolve(fileURLToPath(new URL(".", import.meta.url)), "Chart.svelte"),
  "utf8"
);

const MINIMAL_SERIES: ChartProps["series"] = [
  {
    id: "raised",
    label: "Raised",
    points: [
      { x: "2026-01-01", y: 100 },
      { x: "2026-01-08", y: 125 }
    ]
  }
];

describe("charts/Chart.svelte", () => {
  it("renders line charts through the installed package with stable wrapper markup", () => {
    const rendered = render(Chart, {
      props: {
        kind: "line",
        title: "Weekly receipts",
        ariaLabel: "Weekly receipts trend",
        series: MINIMAL_SERIES
      }
    });

    expect(rendered.body).toContain("Weekly receipts");
    expect(rendered.body).toContain('aria-label="Weekly receipts trend"');
    expect(rendered.body).toMatch(/class="[^"]*\bchart-wrapper\b[^"]*"/);
    expect(rendered.body).toMatch(/class="[^"]*\bchart-wrapper__body\b[^"]*"/);
    expect(rendered.body).not.toContain('data-chart-kind="line"');
    expect(rendered.body).not.toContain('data-chart-kind="bar"');
  });

  it("renders bar charts through the installed package with stable wrapper markup", () => {
    const rendered = render(Chart, {
      props: {
        kind: "bar",
        title: "Weekly receipts",
        ariaLabel: "Weekly receipts trend",
        series: MINIMAL_SERIES
      }
    });

    expect(rendered.body).toContain("Weekly receipts");
    expect(rendered.body).toContain('aria-label="Weekly receipts trend"');
    expect(rendered.body).toMatch(/class="[^"]*\bchart-wrapper\b[^"]*"/);
    expect(rendered.body).toMatch(/class="[^"]*\bchart-wrapper__body\b[^"]*"/);
    expect(rendered.body).not.toContain('data-chart-kind="line"');
    expect(rendered.body).not.toContain('data-chart-kind="bar"');
  });

  it("keeps the chart body and chart svg on an explicit fill contract", () => {
    expect(chartSource).toMatch(
      /\.chart-wrapper__body\s*\{[\s\S]*\bmin-height:\s*18rem;[\s\S]*\bheight:\s*18rem;[\s\S]*\bwidth:\s*100%;[\s\S]*\}/
    );
    expect(chartSource).toMatch(
      /\.chart-wrapper__body\s+:global\(svg\)\s*\{[\s\S]*\bwidth:\s*100%;[\s\S]*\bheight:\s*100%;[\s\S]*\}/
    );
  });

  it("imports LayerChart core CSS from the chart boundary without adding Tailwind", () => {
    const packageSource = readFileSync(
      resolve(fileURLToPath(new URL("../../..", import.meta.url)), "package.json"),
      "utf8"
    );
    const packageJson = JSON.parse(packageSource) as {
      dependencies?: Record<string, string>;
      devDependencies?: Record<string, string>;
    };
    const dependencyNames = new Set([
      ...Object.keys(packageJson.dependencies ?? {}),
      ...Object.keys(packageJson.devDependencies ?? {})
    ]);

    expect(chartSource).toMatch(/import\s+["']layerchart\/core\.css["'];?/);
    expect(chartSource).not.toMatch(/tailwind/i);
    expect(Array.from(dependencyNames).filter((name) => name.includes("tailwind"))).toEqual([]);
  });

  it("renders a stable fallback when series is empty", () => {
    const rendered = render(Chart, {
      props: {
        kind: "line",
        title: "Weekly receipts",
        ariaLabel: "Weekly receipts trend",
        series: []
      }
    });

    expect(rendered.body).toContain("No chart data available.");
    expect(rendered.body).toContain("Weekly receipts");
    expect(rendered.body).toContain('aria-label="Weekly receipts trend"');
    expect(rendered.body).toMatch(
      /<div class="[^"]*\bchart-wrapper__body\b[^"]*">[\s\S]*No chart data available\./
    );
    expect(rendered.body).not.toContain("<svg");
  });
});
