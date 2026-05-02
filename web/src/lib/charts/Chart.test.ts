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
    expect(rendered.body).not.toContain("<svg");
  });
});
