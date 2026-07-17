import { describe, expect, it } from "vitest";
import { buildCompareUrl } from "./people-query";

describe("compare people query helpers", () => {
  it("builds canonical sorted, deduplicated, capped compare URLs", () => {
    expect(buildCompareUrl(["delta", "bravo", "alpha", "bravo", "charlie", "echo"])).toBe(
      "/compare?people=alpha,bravo,charlie,delta"
    );
  });

  it("keeps sorted notices separate from the identity key", () => {
    expect(buildCompareUrl(["ben", "ada"], ["unknown-people-dropped", "max-4"])).toBe(
      "/compare?people=ada,ben&notice=max-4,unknown-people-dropped"
    );
  });
});
