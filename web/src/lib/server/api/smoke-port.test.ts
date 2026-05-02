import { describe, expect, it } from "vitest";

import { resolveSmokeApiPort } from "./smoke-port";

describe("resolveSmokeApiPort", () => {
  it("uses valid SMOKE_API_PORT override", () => {
    expect(resolveSmokeApiPort({ SMOKE_API_PORT: "4012" })).toBe(4012);
  });

  it("falls back to default when override is invalid", () => {
    expect(resolveSmokeApiPort({ SMOKE_API_PORT: "invalid" })).toBe(3999);
  });
});
