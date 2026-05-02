import { describe, expectTypeOf, it } from "vitest";
import type { ChartKind, ChartPoint, ChartProps, ChartSeries } from "./types";

describe("charts/types", () => {
  it("exports a single chart kind union contract", () => {
    expectTypeOf<ChartKind>().toEqualTypeOf<"line" | "bar">();
  });

  it("enforces typed points and series for downstream consumers", () => {
    const point: ChartPoint = { x: "2026-01-01", y: 42 };
    const series: ChartSeries = {
      id: "raised",
      label: "Raised",
      points: [point]
    };
    const props: ChartProps = {
      kind: "line",
      title: "Weekly receipts",
      ariaLabel: "Weekly receipts trend",
      series: [series]
    };

    expectTypeOf(point.y).toEqualTypeOf<number>();
    expectTypeOf<ChartSeries["points"][number]>().toEqualTypeOf<ChartPoint>();
    expectTypeOf<ChartProps["series"][number]>().toEqualTypeOf<ChartSeries>();
  });
});
