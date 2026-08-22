import { formatCurrency } from "./finance";

const DEFAULT_NO_DATA_MESSAGE = "No comparison data is available.";
const LIGHTEN_RATIO = 0.4;

export type ComparisonSegmentInput = {
  id: string;
  label: string;
  value: number;
  color: string;
};

export type ComparisonSegment = ComparisonSegmentInput & {
  widthPct: number;
  percentage: number;
  tooltipText: string;
};

export type ComparisonSegmentsInput = {
  total: number;
  segments: ComparisonSegmentInput[];
  segmentOrder: readonly string[];
  noDataMessage?: string;
};

export type ReadyComparisonSegments = {
  kind: "ready";
  total: number;
  segments: ComparisonSegment[];
};

export type NoDataComparisonSegments = {
  kind: "no-data";
  message: string;
  total: number;
  segments: ComparisonSegment[];
};

export type ComparisonSegmentsResult = ReadyComparisonSegments | NoDataComparisonSegments;

export function sharedScaleWidthPct(value: number, scaleMax: number): number {
  if (!Number.isFinite(value) || !Number.isFinite(scaleMax) || scaleMax <= 0 || value <= 0) {
    return 0;
  }
  return value / scaleMax;
}

/**
 */
export function buildComparisonSegments(input: ComparisonSegmentsInput): ComparisonSegmentsResult {
  const orderedSegments = orderComparisonSegments(input.segments, input.segmentOrder);
  const normalizedTotal = getPositiveFiniteTotal(input.total);
  const segments = orderedSegments.map((segment) => normalizeComparisonSegment(segment, normalizedTotal));

  if (normalizedTotal === 0) {
    return {
      kind: "no-data",
      message: input.noDataMessage ?? DEFAULT_NO_DATA_MESSAGE,
      total: 0,
      segments
    };
  }

  return {
    kind: "ready",
    total: normalizedTotal,
    segments
  };
}

export function orderComparisonSegments(
  segments: readonly ComparisonSegmentInput[],
  segmentOrder: readonly string[]
): ComparisonSegmentInput[] {
  return [...segments].sort((left, right) => {
    const leftIndex = getSegmentOrderIndex(left.label, segmentOrder);
    const rightIndex = getSegmentOrderIndex(right.label, segmentOrder);
    if (leftIndex !== rightIndex) {
      return leftIndex - rightIndex;
    }
    return left.label.localeCompare(right.label);
  });
}

export function buildComparisonTooltip(value: number, percentage: number): string {
  return `${formatCurrency(value)} (${percentage.toFixed(1)}%)`;
}

export function hasNoComparisonData(result: ComparisonSegmentsResult): result is NoDataComparisonSegments {
  return result.kind === "no-data";
}

export function lightenColor(hexColor: string): string {
  const [red, green, blue] = parseHexColor(hexColor);
  return toHexColor([
    lightenChannel(red),
    lightenChannel(green),
    lightenChannel(blue)
  ]);
}

/**
 */
function normalizeComparisonSegment(
  segment: ComparisonSegmentInput,
  total: number
): ComparisonSegment {
  const value = getPositiveFiniteTotal(segment.value);
  const widthPct = sharedScaleWidthPct(value, total);
  const percentage = widthPct * 100;

  return {
    ...segment,
    value,
    widthPct,
    percentage,
    tooltipText: buildComparisonTooltip(value, percentage)
  };
}

function getPositiveFiniteTotal(value: number): number {
  if (!Number.isFinite(value) || value <= 0) {
    return 0;
  }
  return value;
}

function getSegmentOrderIndex(label: string, segmentOrder: readonly string[]): number {
  const index = segmentOrder.indexOf(label);
  return index === -1 ? Number.MAX_SAFE_INTEGER : index;
}

function lightenChannel(value: number): number {
  return Math.min(255, Math.round(value + (255 - value) * LIGHTEN_RATIO));
}

function toHexColor(channels: [number, number, number]): string {
  return `#${channels.map((channel) => channel.toString(16).padStart(2, "0")).join("")}`;
}

function parseHexColor(color: string): [number, number, number] {
  const normalized = color.replace("#", "");
  if (!/^[0-9a-fA-F]{6}$/.test(normalized)) {
    throw new Error(`Expected a 6-digit hex color, received ${color}`);
  }
  return [
    Number.parseInt(normalized.slice(0, 2), 16),
    Number.parseInt(normalized.slice(2, 4), 16),
    Number.parseInt(normalized.slice(4, 6), 16)
  ];
}
