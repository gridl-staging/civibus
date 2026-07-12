import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it, vi } from "vitest";
import { render } from "svelte/server";

vi.mock("layerchart", async () => {
  const [{ default: BarChart }, { default: LineChart }] = await Promise.all([
    import("./BarChartMock.svelte"),
    import("./LineChartMock.svelte")
  ]);

  return {
    BarChart,
    LineChart
  };
});

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
  it("passes title and aria label through wrapper markup for line charts", () => {
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
    expect(rendered.body).toContain('data-chart-kind="line"');
    expect(rendered.body).not.toContain('data-chart-kind="bar"');
  });

  it("passes title and aria label through wrapper markup for bar charts", () => {
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
    expect(rendered.body).toContain('data-chart-kind="bar"');
    expect(rendered.body).not.toContain('data-chart-kind="line"');
  });

  it("wraps layerchart output in a stable chart body container", () => {
    const rendered = render(Chart, {
      props: {
        kind: "bar",
        title: "Weekly receipts",
        ariaLabel: "Weekly receipts trend",
        series: MINIMAL_SERIES
      }
    });

    expect(rendered.body).toMatch(/class="[^"]*\bchart-wrapper\b[^"]*"/);
    expect(rendered.body).toMatch(/class="[^"]*\bchart-wrapper__body\b[^"]*"/);
    expect(rendered.body).toMatch(
      /<section class="[^"]*\bchart-wrapper\b[^"]*"[^>]*aria-label="Weekly receipts trend"[\s\S]*<div class="[^"]*\bchart-wrapper__body\b[^"]*">[\s\S]*data-chart-kind="bar"/
    );
  });

  it("keeps the chart body and chart svg on an explicit fill contract", () => {
    expect(chartSource).toMatch(
      /\.chart-wrapper__body\s*\{[\s\S]*\bmin-height:\s*18rem;[\s\S]*\bheight:\s*18rem;[\s\S]*\bwidth:\s*100%;[\s\S]*\}/
    );
    expect(chartSource).toMatch(
      /\.chart-wrapper__body\s+:global\(svg\)\s*\{[\s\S]*\bwidth:\s*100%;[\s\S]*\bheight:\s*100%;[\s\S]*\}/
    );
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
