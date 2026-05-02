export type ChartKind = "line" | "bar";

export type ChartX = string | number | Date;

export interface ChartPoint {
  x: ChartX;
  y: number;
}

export interface ChartSeries {
  id: string;
  label: string;
  points: ChartPoint[];
}

export interface ChartProps {
  kind: ChartKind;
  title: string;
  ariaLabel: string;
  series: ChartSeries[];
}
