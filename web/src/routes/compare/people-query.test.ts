import { describe, expect, it } from "vitest";
import { buildCompareUrl, normalizePeopleQuery } from "./people-query";

const PERSON_A = "11111111-1111-4111-8111-111111111111";
const PERSON_B = "22222222-2222-4222-8222-222222222222";
const PERSON_C = "33333333-3333-4333-8333-333333333333";
const UNKNOWN_PERSON = "99999999-9999-4999-8999-999999999999";

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

  it("keeps only UUID people tokens while preserving repeated params, order, duplicates, and notices", () => {
    const searchParams = new URLSearchParams();
    searchParams.append(
      "people",
      `00000000-0000-4000-8000-00000000000z,${PERSON_B},${UNKNOWN_PERSON}`
    );
    searchParams.append("people", `${PERSON_C},${PERSON_A},${PERSON_B},still-not-a-uuid`);
    searchParams.append("notice", "unknown-people-dropped");
    searchParams.append("notice", "max-4,unknown-people-dropped");

    const query = normalizePeopleQuery(searchParams);

    expect(query.peopleIds).toEqual([PERSON_A, PERSON_B, PERSON_C, UNKNOWN_PERSON]);
    expect(query.notices).toEqual(["max-4", "unknown-people-dropped"]);
    expect(query.hadPopulatedInput).toBe(true);
    expect(query.wasCapped).toBe(false);
    expect(query.isCanonicalFor(query.peopleIds)).toBe(false);
  });
});
