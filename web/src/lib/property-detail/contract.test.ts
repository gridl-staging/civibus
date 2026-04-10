import { describe, expect, it } from "vitest";
import { buildParcelDetailPath, buildParcelRoutePath } from "./contract";

const PARCEL_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";

describe("property detail contract", () => {
  it("builds the backend-owned parcel detail path", () => {
    expect(buildParcelDetailPath(PARCEL_ID)).toBe(`/v1/parcels/${PARCEL_ID}`);
  });

  it("builds the UUID-only frontend /property/[id] route path", () => {
    const routePath = buildParcelRoutePath(PARCEL_ID);
    const parsed = new URL(routePath, "https://web.civibus.local");

    expect(parsed.pathname).toBe(`/property/${PARCEL_ID}`);
    expect(parsed.search).toBe("");
    expect(parsed.hash).toBe("");
  });

  it("encodes parcel IDs in backend and frontend paths", () => {
    const maliciousId = "../search?entity_type=property";

    expect(buildParcelDetailPath(maliciousId)).toBe("/v1/parcels/..%2Fsearch%3Fentity_type%3Dproperty");
    expect(buildParcelRoutePath(maliciousId)).toBe("/property/..%2Fsearch%3Fentity_type%3Dproperty");
  });
});
