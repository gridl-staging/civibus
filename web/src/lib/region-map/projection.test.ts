import { describe, expect, it } from "vitest";
import {
  DEFAULT_US_VIEWPORT,
  geometryFeatureToSvgPath,
  projectPoint
} from "./projection";
import type { GeometryFeature } from "$lib/server/api/state-pages-contract";

const PIXEL_TOLERANCE = 1;

/**
 * Hand-calculated reference values for the default viewport
 * (width=960, height=500, lng[-125,-66], lat[24,50]):
 *
 *   NC centroid (-79.4, 35.6):
 *     x = ((-79.4 + 125) / 59) * 960 = 741.9661...
 *     y = ((50 - 35.6) / 26) * 500   = 276.9231...
 *
 *   CA centroid (-119.4, 36.7):
 *     x = ((-119.4 + 125) / 59) * 960 = 91.1186...
 *     y = ((50 - 36.7) / 26) * 500    = 255.7692...
 */

describe("projectPoint", () => {
  it("maps the NC centroid to a hand-calculated pixel within ±1px", () => {
    const [x, y] = projectPoint(-79.4, 35.6);

    expect(Math.abs(x - 741.97)).toBeLessThanOrEqual(PIXEL_TOLERANCE);
    expect(Math.abs(y - 276.92)).toBeLessThanOrEqual(PIXEL_TOLERANCE);
  });

  it("maps the CA centroid to a hand-calculated pixel within ±1px", () => {
    const [x, y] = projectPoint(-119.4, 36.7);

    expect(Math.abs(x - 91.12)).toBeLessThanOrEqual(PIXEL_TOLERANCE);
    expect(Math.abs(y - 255.77)).toBeLessThanOrEqual(PIXEL_TOLERANCE);
  });

  it("repositions the Alaska centroid into the shared SVG viewport", () => {
    const [x, y] = projectPoint(-150, 64);

    expect(Math.abs(x - 159.97)).toBeLessThanOrEqual(PIXEL_TOLERANCE);
    expect(Math.abs(y - 376.10)).toBeLessThanOrEqual(PIXEL_TOLERANCE);
  });

  it("repositions the Hawaii centroid into the shared SVG viewport", () => {
    const [x, y] = projectPoint(-157, 21);

    expect(Math.abs(x - 320.57)).toBeLessThanOrEqual(PIXEL_TOLERANCE);
    expect(Math.abs(y - 434.00)).toBeLessThanOrEqual(PIXEL_TOLERANCE);
  });

  it("places the lower-left viewport corner at the SVG bottom-left", () => {
    const [x, y] = projectPoint(
      DEFAULT_US_VIEWPORT.lngMin,
      DEFAULT_US_VIEWPORT.latMin
    );

    expect(x).toBeCloseTo(0, 6);
    expect(y).toBeCloseTo(DEFAULT_US_VIEWPORT.height, 6);
  });

  it("places the upper-right viewport corner at the SVG top-right", () => {
    const [x, y] = projectPoint(
      DEFAULT_US_VIEWPORT.lngMax,
      DEFAULT_US_VIEWPORT.latMax
    );

    expect(x).toBeCloseTo(DEFAULT_US_VIEWPORT.width, 6);
    expect(y).toBeCloseTo(0, 6);
  });
});

describe("geometryFeatureToSvgPath", () => {
  it("emits a closed Polygon path with M/L/Z commands using projected pixels", () => {
    const feature: GeometryFeature = {
      type: "Feature",
      geometry: {
        type: "Polygon",
        coordinates: [
          [
            [-125, 24],
            [-66, 24],
            [-66, 50],
            [-125, 50]
          ]
        ]
      },
      properties: {
        state: "ZZ",
        name: "Mock",
        division_type: "state",
        boundary_year: 2020
      }
    };

    const path = geometryFeatureToSvgPath(feature);

    expect(path).toBe(
      "M0.00,500.00L960.00,500.00L960.00,0.00L0.00,0.00Z"
    );
  });

  it("renders MultiPolygon geometries by concatenating each polygon path", () => {
    const feature: GeometryFeature = {
      type: "Feature",
      geometry: {
        type: "MultiPolygon",
        coordinates: [
          [
            [
              [-125, 24],
              [-66, 24],
              [-66, 50],
              [-125, 50]
            ]
          ],
          [
            [
              [-125, 24],
              [-66, 50],
              [-125, 50]
            ]
          ]
        ]
      },
      properties: {
        state: "ZZ",
        name: "Mock",
        division_type: "state",
        boundary_year: 2020
      }
    };

    const path = geometryFeatureToSvgPath(feature);
    const polygonStarts = (path.match(/M/g) ?? []).length;

    expect(polygonStarts).toBe(2);
    expect(path.endsWith("Z")).toBe(true);
  });
});
