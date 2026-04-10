import { describe, expect, it } from "vitest";
import { formatCountLabel } from "./count-label";

describe("formatCountLabel", () => {
  it("uses the singular label for a count of one", () => {
    expect(formatCountLabel(1, "result")).toBe("1 result");
  });

  it("uses the default plural suffix for counts other than one", () => {
    expect(formatCountLabel(2, "result")).toBe("2 results");
  });

  it("supports irregular plural labels", () => {
    expect(formatCountLabel(0, "ER match", "ER matches")).toBe("0 ER matches");
  });

  it("keeps singular wording at count=1 even when an irregular plural override is provided", () => {
    expect(formatCountLabel(1, "ER match", "ER matches")).toBe("1 ER match");
  });
});
