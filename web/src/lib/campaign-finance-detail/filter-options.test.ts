import { describe, expect, it } from "vitest";
import { COMMITTEE_TYPE_OPTIONS, FEC_CANDIDATE_OFFICE_OPTIONS, US_STATE_OPTIONS } from "./filter-options";

const EXPECTED_US_STATE_CODES = [
  "AL",
  "AK",
  "AZ",
  "AR",
  "CA",
  "CO",
  "CT",
  "DE",
  "DC",
  "FL",
  "GA",
  "HI",
  "ID",
  "IL",
  "IN",
  "IA",
  "KS",
  "KY",
  "LA",
  "ME",
  "MD",
  "MA",
  "MI",
  "MN",
  "MS",
  "MO",
  "MT",
  "NE",
  "NV",
  "NH",
  "NJ",
  "NM",
  "NY",
  "NC",
  "ND",
  "OH",
  "OK",
  "OR",
  "PA",
  "RI",
  "SC",
  "SD",
  "TN",
  "TX",
  "UT",
  "VT",
  "VA",
  "WA",
  "WV",
  "WI",
  "WY"
] as const;

describe("campaign-finance filter options", () => {
  it("exports all US states plus DC in stable order with unique codes", () => {
    const exportedCodes = US_STATE_OPTIONS.map((option) => option.code);
    const uniqueCodes = new Set(exportedCodes);

    expect(exportedCodes).toEqual(EXPECTED_US_STATE_CODES);
    expect(US_STATE_OPTIONS).toHaveLength(51);
    expect(uniqueCodes.size).toBe(US_STATE_OPTIONS.length);
  });

  it("exports exact FEC candidate office codes in canonical order with unique codes", () => {
    const exportedCodes = FEC_CANDIDATE_OFFICE_OPTIONS.map((option) => option.code);
    const uniqueCodes = new Set(exportedCodes);

    expect(FEC_CANDIDATE_OFFICE_OPTIONS).toEqual([
      { code: "H", label: "U.S. House" },
      { code: "S", label: "U.S. Senate" },
      { code: "P", label: "President" }
    ]);
    expect(exportedCodes).toEqual(["H", "S", "P"]);
    expect(uniqueCodes.size).toBe(FEC_CANDIDATE_OFFICE_OPTIONS.length);
  });

  it("exports FEC committee type codes in canonical order with unique codes", () => {
    const exportedCodes = COMMITTEE_TYPE_OPTIONS.map((option) => option.code);
    const uniqueCodes = new Set(exportedCodes);

    expect(exportedCodes).toEqual([
      "C", "D", "E", "H", "I", "N", "O", "P", "Q", "S", "U", "V", "W", "X", "Y", "Z"
    ]);
    expect(COMMITTEE_TYPE_OPTIONS).toHaveLength(16);
    expect(uniqueCodes.size).toBe(COMMITTEE_TYPE_OPTIONS.length);
  });

  it("has human-readable labels for all committee type codes", () => {
    for (const option of COMMITTEE_TYPE_OPTIONS) {
      expect(option.code).toMatch(/^[A-Z]$/);
      expect(option.label.length).toBeGreaterThan(0);
      expect(option.label).not.toBe(option.code);
    }
  });
});
