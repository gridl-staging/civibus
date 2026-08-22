/**
 * Pure equirectangular projection for the contiguous-US landing map.
 *
 * Hand-rolled instead of pulling d3-geo so the projection is unit-testable
 * to ±1px tolerance against hand-calculated expected values.
 */
import type {
  GeometryFeature,
  GeometryMultiPolygonCoordinates,
  GeometryPolygonCoordinates
} from "$lib/server/api/state-pages-contract";

export type Viewport = {
  width: number;
  height: number;
  lngMin: number;
  lngMax: number;
  latMin: number;
  latMax: number;
};

export const DEFAULT_US_VIEWPORT: Viewport = {
  width: 960,
  height: 500,
  lngMin: -125,
  lngMax: -66,
  latMin: 24,
  latMax: 50
};

export type ProjectedPoint = readonly [number, number];

type ProjectionRect = {
  lngMin: number;
  lngMax: number;
  latMin: number;
  latMax: number;
  xMin: number;
  xMax: number;
  yMin: number;
  yMax: number;
};

const ALASKA_INSET: ProjectionRect = {
  lngMin: -179.5,
  lngMax: -130,
  latMin: 51,
  latMax: 72,
  xMin: 36,
  xMax: 244,
  yMin: 320,
  yMax: 468
};

const HAWAII_INSET: ProjectionRect = {
  lngMin: -161,
  lngMax: -154,
  latMin: 18,
  latMax: 23,
  xMin: 268,
  xMax: 360,
  yMin: 406,
  yMax: 476
};

function projectIntoRect(
  longitude: number,
  latitude: number,
  rect: ProjectionRect
): ProjectedPoint {
  const x =
    rect.xMin +
    ((longitude - rect.lngMin) / (rect.lngMax - rect.lngMin)) *
      (rect.xMax - rect.xMin);
  const y =
    rect.yMax -
    ((latitude - rect.latMin) / (rect.latMax - rect.latMin)) *
      (rect.yMax - rect.yMin);
  return [x, y];
}

function getInsetRect(longitude: number, latitude: number): ProjectionRect | null {
  if (latitude >= ALASKA_INSET.latMin && (longitude <= ALASKA_INSET.lngMax || longitude >= 170)) {
    return ALASKA_INSET;
  }

  if (
    latitude >= HAWAII_INSET.latMin &&
    latitude <= HAWAII_INSET.latMax &&
    longitude >= HAWAII_INSET.lngMin &&
    longitude <= HAWAII_INSET.lngMax
  ) {
    return HAWAII_INSET;
  }

  return null;
}

export function projectPoint(
  longitude: number,
  latitude: number,
  viewport: Viewport = DEFAULT_US_VIEWPORT
): ProjectedPoint {
  const insetRect = getInsetRect(longitude, latitude);
  if (insetRect !== null) {
    return projectIntoRect(longitude, latitude, insetRect);
  }

  const x =
    ((longitude - viewport.lngMin) / (viewport.lngMax - viewport.lngMin)) *
    viewport.width;
  const y =
    ((viewport.latMax - latitude) / (viewport.latMax - viewport.latMin)) *
    viewport.height;
  return [x, y];
}

function ringToPathSegment(
  ring: number[][],
  viewport: Viewport
): string {
  const segments: string[] = [];
  for (let pointIndex = 0; pointIndex < ring.length; pointIndex += 1) {
    const [longitude, latitude] = ring[pointIndex];
    const [x, y] = projectPoint(longitude, latitude, viewport);
    const command = pointIndex === 0 ? "M" : "L";
    segments.push(`${command}${x.toFixed(2)},${y.toFixed(2)}`);
  }
  segments.push("Z");
  return segments.join("");
}

function polygonToPath(
  polygon: GeometryPolygonCoordinates,
  viewport: Viewport
): string {
  return polygon.map((ring) => ringToPathSegment(ring, viewport)).join("");
}

function multiPolygonToPath(
  multiPolygon: GeometryMultiPolygonCoordinates,
  viewport: Viewport
): string {
  return multiPolygon
    .map((polygon) => polygonToPath(polygon, viewport))
    .join("");
}

export function geometryFeatureToSvgPath(
  feature: GeometryFeature,
  viewport: Viewport = DEFAULT_US_VIEWPORT
): string {
  if (feature.geometry.type === "Polygon") {
    return polygonToPath(feature.geometry.coordinates, viewport);
  }
  return multiPolygonToPath(feature.geometry.coordinates, viewport);
}
