import { describe, expect, it } from "vitest";
import { formatPersonDisplayName } from "$lib/display-name";

// Contract: docs/reference/screen_specs/candidate_list.md -> "Name presentation
// contract". One owner, one format: `Last, First Middle` in title case, matching
// the convention core.person.canonical_name already ships on Person Detail.
describe("formatPersonDisplayName", () => {
  it("title-cases a raw all-caps FEC name into the person-spine format", () => {
    // The live specimen this whole change exists for: production renders
    // `OSSOFF, T. JONATHAN` on /candidates and `Ossoff, Jon` on /person/...
    expect(formatPersonDisplayName("OSSOFF, T. JONATHAN")).toBe("Ossoff, T. Jonathan");
  });

  it("leaves an already-formatted person-spine name untouched", () => {
    expect(formatPersonDisplayName("Ossoff, Jon")).toBe("Ossoff, Jon");
  });

  it("is idempotent, so re-formatting a formatted name cannot drift", () => {
    const once = formatPersonDisplayName("BLACK, GARY");
    expect(once).toBe("Black, Gary");
    expect(formatPersonDisplayName(once)).toBe(once);
  });

  it("formats other measured production browse rows", () => {
    // All three sampled live from /candidates?state=GA&office=S on 2026-08-19.
    expect(formatPersonDisplayName("AMUN, AKHENATEN HOTEP")).toBe("Amun, Akhenaten Hotep");
    expect(formatPersonDisplayName("BALENO, IRENE STEPHANIE")).toBe("Baleno, Irene Stephanie");
    expect(formatPersonDisplayName("BARTELL, ELBERT (AL)")).toBe("Bartell, Elbert (Al)");
  });

  it("re-cases only the all-caps tokens of a mixed-case name", () => {
    // Per-token, not whole-string: a partially corrected name still converges on
    // the one format instead of being passed through half-shouted.
    expect(formatPersonDisplayName("OSSOFF, Jon")).toBe("Ossoff, Jon");
  });

  it("capitalizes each segment of a hyphenated surname", () => {
    expect(formatPersonDisplayName("SMITH-JONES, MARY")).toBe("Smith-Jones, Mary");
  });

  it("capitalizes the letter after a leading-particle apostrophe", () => {
    expect(formatPersonDisplayName("O'BRIEN, SEAN")).toBe("O'Brien, Sean");
    expect(formatPersonDisplayName("D'AMATO, ALFONSE")).toBe("D'Amato, Alfonse");
  });

  it("does not capitalize after a possessive or trailing apostrophe", () => {
    // The particle rule is positional: only an apostrophe at index 1 splits a
    // name particle. Anything else is punctuation, not a name boundary.
    expect(formatPersonDisplayName("JONES', PAT")).toBe("Jones', Pat");
  });

  it("capitalizes the letter after a Mc prefix", () => {
    expect(formatPersonDisplayName("MCCONNELL, ADDISON MITCHELL")).toBe(
      "McConnell, Addison Mitchell"
    );
  });

  it("leaves Mac names alone, because Mac has too many false positives", () => {
    // MACON, MACK and MACIAS are ordinary surnames; a blanket Mac rule would
    // mangle all three to buy McArthur. Mc is safe, Mac is not.
    expect(formatPersonDisplayName("MACIAS, LUIS")).toBe("Macias, Luis");
  });

  it("preserves roman-numeral generational suffixes", () => {
    expect(formatPersonDisplayName("GRAVES, GARRET III")).toBe("Graves, Garret III");
    expect(formatPersonDisplayName("KENNEDY, JOSEPH II")).toBe("Kennedy, Joseph II");
  });

  it("title-cases abbreviated suffixes and honorifics", () => {
    expect(formatPersonDisplayName("DAVID, J SR SR")).toBe("David, J Sr Sr");
    expect(formatPersonDisplayName("JOHNSON, RODNEY MR.")).toBe("Johnson, Rodney Mr.");
  });

  it("preserves single-letter initials with and without a period", () => {
    expect(formatPersonDisplayName("SMITH, JOHN Q")).toBe("Smith, John Q");
    expect(formatPersonDisplayName("SMITH, JOHN Q.")).toBe("Smith, John Q.");
  });

  it("collapses the doubled whitespace FEC source strings carry", () => {
    // Measured shape of a real suppressed row: `212 N HALF  W. JOHN, RODNEY ...`
    expect(formatPersonDisplayName("SMITH,   JOHN")).toBe("Smith, John");
  });

  it("trims surrounding whitespace", () => {
    expect(formatPersonDisplayName("  BLACK, GARY  ")).toBe("Black, Gary");
  });

  it("returns an empty string for blank input rather than inventing a name", () => {
    expect(formatPersonDisplayName("")).toBe("");
    expect(formatPersonDisplayName("   ")).toBe("");
  });

  it("passes through digit-bearing tokens without corrupting them", () => {
    // Identity suppression keeps these out of browse, but candidate detail still
    // renders them, so the formatter must not damage the source evidence.
    expect(formatPersonDisplayName("212 N HALF W. JOHN, RODNEY")).toBe(
      "212 N Half W. John, Rodney"
    );
  });
});
