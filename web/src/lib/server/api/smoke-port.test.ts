import { describe, expect, it } from "vitest";

import { resolveSmokeApiPort, resolveSmokeWebPort } from "./smoke-port";

describe("resolveSmokeApiPort", () => {
  it("uses valid SMOKE_API_PORT override", () => {
    expect(resolveSmokeApiPort({ SMOKE_API_PORT: "4012" })).toBe(4012);
  });

  it("falls back to default when override is invalid", () => {
    expect(resolveSmokeApiPort({ SMOKE_API_PORT: "invalid" })).toBe(3999);
  });
});

describe("resolveSmokeWebPort", () => {
  it("uses valid SMOKE_WEB_PORT override", () => {
    expect(resolveSmokeWebPort({ SMOKE_WEB_PORT: "4174" })).toBe(4174);
  });

  it.each([
    { label: "missing", env: {} },
    { label: "invalid", env: { SMOKE_WEB_PORT: "invalid" } },
    { label: "zero", env: { SMOKE_WEB_PORT: "0" } },
    { label: "negative", env: { SMOKE_WEB_PORT: "-1" } },
    { label: "too large", env: { SMOKE_WEB_PORT: "65536" } }
  ])("falls back to default when override is $label", ({ env }) => {
    expect(resolveSmokeWebPort(env)).toBe(4173);
  });
});
