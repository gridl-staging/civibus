import { describe, expect, it } from "vitest";
import type { CandidateListItem, CommitteeListItem } from "./contract";
import {
  buildCandidateListItemPresentation,
  buildCommitteeListItemPresentation,
  buildPaginationContext
} from "./list-presentation";

const CANDIDATE_ID = "44444444-4444-4444-8444-444444444444";
const COMMITTEE_ID = "33333333-3333-4333-8333-333333333333";

const FULL_CANDIDATE: CandidateListItem = {
  id: CANDIDATE_ID,
  fec_candidate_id: "H0NC01001",
  name: "Candidate One",
  party: "DEM",
  office: "H",
  state: "NC",
  district: "01",
  slug: "candidate-one",
  slug_is_unique: true,
  identity_is_safe: true
};

const SPARSE_CANDIDATE: CandidateListItem = {
  id: CANDIDATE_ID,
  fec_candidate_id: "H0NC01001",
  name: "Sparse Candidate",
  party: null,
  office: "President",
  state: null,
  district: null,
  slug: "sparse-candidate",
  slug_is_unique: true,
  identity_is_safe: true
};

const FULL_COMMITTEE: CommitteeListItem = {
  id: COMMITTEE_ID,
  fec_committee_id: "C12345678",
  name: "Committee One",
  committee_type: "Super PAC",
  party: "DEM",
  state: "NC",
  slug: "committee-one",
  slug_is_unique: true
};

const SPARSE_COMMITTEE: CommitteeListItem = {
  id: COMMITTEE_ID,
  fec_committee_id: "C12345678",
  name: "Sparse Committee",
  committee_type: null,
  party: null,
  state: null,
  slug: "sparse-committee",
  slug_is_unique: true
};

describe("buildCandidateListItemPresentation", () => {
  it("returns the candidate name, canonical href, and joined non-null segments", () => {
    const result = buildCandidateListItemPresentation(FULL_CANDIDATE);
    expect(result).toEqual({
      name: "Candidate One",
      href: "/candidate/candidate-one",
      contextLine: "DEM · H · NC-01"
    });
  });

  it("returns office only when all nullable fields are null", () => {
    const result = buildCandidateListItemPresentation(SPARSE_CANDIDATE);
    expect(result.contextLine).toBe("President");
  });

  it("falls back to the candidate id when the slug is not unique", () => {
    const result = buildCandidateListItemPresentation({
      ...FULL_CANDIDATE,
      slug_is_unique: false
    });

    expect(result.href).toBe(`/candidate/${CANDIDATE_ID}`);
  });

  it("includes party and office without trailing separator when state/district are null", () => {
    const result = buildCandidateListItemPresentation({
      ...SPARSE_CANDIDATE,
      party: "REP"
    });
    expect(result.contextLine).toBe("REP · President");
  });

  it("collapses state and district into one segment when both present", () => {
    const result = buildCandidateListItemPresentation({
      ...SPARSE_CANDIDATE,
      state: "NC",
      district: "01"
    });
    expect(result.contextLine).toBe("President · NC-01");
  });

  it("uses state alone when district is null", () => {
    const result = buildCandidateListItemPresentation({
      ...SPARSE_CANDIDATE,
      state: "NC"
    });
    expect(result.contextLine).toBe("President · NC");
  });

  it("uses district alone when state is null", () => {
    const result = buildCandidateListItemPresentation({
      ...SPARSE_CANDIDATE,
      district: "01"
    });
    expect(result.contextLine).toBe("President · 01");
  });
});

describe("buildCommitteeListItemPresentation", () => {
  it("returns the committee name, canonical href, and joined non-null fields", () => {
    const result = buildCommitteeListItemPresentation(FULL_COMMITTEE);
    expect(result).toEqual({
      name: "Committee One",
      href: "/committee/committee-one",
      contextLine: "Super PAC · DEM · NC"
    });
  });

  it("returns empty string when all nullable fields are null", () => {
    const result = buildCommitteeListItemPresentation(SPARSE_COMMITTEE);
    expect(result.contextLine).toBe("");
  });

  it("falls back to the committee id when the slug is not unique", () => {
    const result = buildCommitteeListItemPresentation({
      ...FULL_COMMITTEE,
      slug_is_unique: false
    });

    expect(result.href).toBe(`/committee/${COMMITTEE_ID}`);
  });

  it("returns committee_type alone when it is the only non-null field", () => {
    const result = buildCommitteeListItemPresentation({
      ...SPARSE_COMMITTEE,
      committee_type: "PAC"
    });
    expect(result.contextLine).toBe("PAC");
  });
});

describe("buildPaginationContext", () => {
  it("computes first page correctly", () => {
    const result = buildPaginationContext(0, 25, true, 25);
    expect(result.label).toBe("Showing 1\u201325");
    expect(result.hasPrevious).toBe(false);
    expect(result.hasNext).toBe(true);
  });

  it("computes middle page correctly", () => {
    const result = buildPaginationContext(50, 25, true, 25);
    expect(result.label).toBe("Showing 51\u201375");
    expect(result.hasPrevious).toBe(true);
    expect(result.hasNext).toBe(true);
  });

  it("computes last full page correctly", () => {
    const result = buildPaginationContext(50, 25, false, 25);
    expect(result.label).toBe("Showing 51\u201375");
    expect(result.hasPrevious).toBe(true);
    expect(result.hasNext).toBe(false);
  });

  it("computes partial last page with correct end value", () => {
    const result = buildPaginationContext(50, 25, false, 7);
    expect(result.label).toBe("Showing 51\u201357");
    expect(result.hasPrevious).toBe(true);
    expect(result.hasNext).toBe(false);
  });

  it("returns an empty-range label when current page has no items", () => {
    const result = buildPaginationContext(0, 25, false, 0);
    expect(result.label).toBe("Showing 0\u20130");
    expect(result.hasPrevious).toBe(false);
    expect(result.hasNext).toBe(false);
  });
});
