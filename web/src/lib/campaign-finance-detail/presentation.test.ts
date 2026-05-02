import { describe, expect, it } from "vitest";
import { buildTrustSection, PHL_FRESHNESS_NOTE } from "$lib/detail-trust/presentation";
import type { CommitteeDetailBundle } from "$lib/server/api/campaign-finance-detail";
import {
  buildCandidateDetailMetadata,
  buildCandidateDetailShellPresentation,
  buildCandidateFactRows,
  buildCandidateRoutePresentation,
  buildCommitteeDetailMetadata,
  buildCommitteeDetailMetadataFromBundle,
  buildCommitteeDetailShellPresentation,
  buildCommitteeFactRows,
  buildCommitteeRoutePresentation
} from "./presentation";
import {
  CANDIDATE_ID,
  COMMITTEE_ID,
  DEFAULT_CANDIDATE_DETAIL,
  DEFAULT_COMMITTEE_DETAIL,
  ORG_ID,
  PERSON_ID,
  buildCandidateBundle,
  buildCommitteeBundle
} from "./presentation_test_fixtures";

describe("campaign finance detail presentation", () => {
  it("builds committee fact rows including routable canonical organization links", () => {
    const rows = buildCommitteeFactRows({
      ...DEFAULT_COMMITTEE_DETAIL,
      organization_id: ORG_ID,
      committee_type: "Q",
      committee_designation: "P",
      party: "DEM",
      state: "NC",
      city: "Raleigh",
      zip_code: "27601",
      treasurer_name: "Treasurer One"
    });

    expect(rows).toContainEqual({
      label: "Canonical organization",
      value: `Organization record (${ORG_ID})`,
      href: `/org/${ORG_ID}`
    });
  });

  it("builds candidate fact rows with routable person and principal committee links", () => {
    const rows = buildCandidateFactRows({
      id: CANDIDATE_ID,
      fec_candidate_id: "H0NC01001",
      name: "Candidate One",
      slug: "candidate-one",
      slug_is_unique: true,
      person_id: PERSON_ID,
      party: "DEM",
      office: "H",
      state: "NC",
      district: "01",
      incumbent_challenge: "I",
      principal_committee_id: COMMITTEE_ID,
      sources: []
    });

    expect(rows).toContainEqual({
      label: "Canonical person",
      value: `Person record (${PERSON_ID})`,
      href: `/person/${PERSON_ID}`
    });
    expect(rows).toContainEqual({
      label: "Principal committee",
      value: `Committee record (${COMMITTEE_ID})`,
      href: `/committee/${COMMITTEE_ID}`
    });
  });

  it("builds committee trust-section data from the shared trust contract", () => {
    const sources = [
      {
        domain: "campaign_finance",
        jurisdiction: "federal/fec",
        data_source_name: "FEC",
        data_source_url: "https://www.fec.gov",
        source_record_key: "committee-1",
        record_url: "https://example.org/committee-1",
        pull_date: "2026-03-19T00:00:00Z"
      }
    ];
    const shell = buildCommitteeDetailShellPresentation({ ...DEFAULT_COMMITTEE_DETAIL, sources });

    expect(shell.trustSection).toEqual(buildTrustSection(sources));
  });

  it("builds candidate trust-section data from the shared trust contract when provenance is empty", () => {
    const shell = buildCandidateDetailShellPresentation(DEFAULT_CANDIDATE_DETAIL);

    expect(shell.trustSection).toEqual(buildTrustSection([]));
  });

  it("does not surface the retired Indiana freshness warning on campaign-finance detail pages", () => {
    // IN re-verdicted to weekly-or-better 2026-04-26
    // (see docs/research/in_freshness_recheck_2026_04_26.md). The
    // Indiana-specific banner is retired; campaign-finance committee
    // and candidate shells must no longer surface it for IN sources.
    const sources = [
      {
        domain: "campaign_finance",
        jurisdiction: "state/IN",
        data_source_name: "Indiana Campaign Finance",
        data_source_url: "https://campaignfinance.in.gov/PublicSite/Reporting/DataDownload.aspx",
        source_record_key: "committee-1",
        record_url: "https://example.org/committee-1",
        pull_date: "2026-03-19T00:00:00Z"
      }
    ];

    const committeeShell = buildCommitteeDetailShellPresentation({ ...DEFAULT_COMMITTEE_DETAIL, sources });
    const candidateShell = buildCandidateDetailShellPresentation({ ...DEFAULT_CANDIDATE_DETAIL, sources });

    expect(committeeShell.trustSection.freshnessNote).toBeNull();
    expect(candidateShell.trustSection.freshnessNote).toBeNull();
  });

  it("surfaces the Philadelphia freshness warning on campaign-finance detail pages", () => {
    const sources = [
      {
        domain: "campaign_finance",
        jurisdiction: "municipality/PHL",
        data_source_name: "Philadelphia Campaign Finance",
        data_source_url: "https://opendataphilly.org/",
        source_record_key: "committee-1",
        record_url: "https://example.org/committee-1",
        pull_date: "2026-03-19T00:00:00Z"
      }
    ];

    const committeeShell = buildCommitteeDetailShellPresentation({ ...DEFAULT_COMMITTEE_DETAIL, sources });
    const candidateShell = buildCandidateDetailShellPresentation({ ...DEFAULT_CANDIDATE_DETAIL, sources });

    expect(committeeShell.trustSection.freshnessNote).toBe(PHL_FRESHNESS_NOTE);
    expect(candidateShell.trustSection.freshnessNote).toBe(PHL_FRESHNESS_NOTE);
  });

  it("does not duplicate route metadata inside the committee detail shell", () => {
    const shell = buildCommitteeDetailShellPresentation(DEFAULT_COMMITTEE_DETAIL);

    expect("metadata" in shell).toBe(false);
  });

  it("does not duplicate route metadata inside the candidate detail shell", () => {
    const shell = buildCandidateDetailShellPresentation(DEFAULT_CANDIDATE_DETAIL);

    expect("metadata" in shell).toBe(false);
  });

  it("builds committee metadata from canonical name", () => {
    expect(buildCommitteeDetailMetadata("Committee One")).toEqual({
      title: "Committee One | Committee | Civibus",
      description: "Committee profile from campaign-finance records."
    });
  });

  it("builds candidate metadata from canonical candidate name", () => {
    expect(buildCandidateDetailMetadata("Candidate One")).toEqual({
      title: "Candidate One | Candidate | Civibus",
      description: "Candidate profile from campaign-finance records."
    });
  });

  it("falls back to a generic committee canonical name when detail name is blank", () => {
    const shell = buildCommitteeDetailShellPresentation({ ...DEFAULT_COMMITTEE_DETAIL, name: "" });

    expect(shell.canonicalName).toBe("Committee");
  });

  it("falls back to a generic candidate canonical name when detail name is blank", () => {
    const shell = buildCandidateDetailShellPresentation({ ...DEFAULT_CANDIDATE_DETAIL, name: "" });

    expect(shell.canonicalName).toBe("Candidate");
  });

  it("builds committee route metadata from shell-only detail (no transaction count)", () => {
    expect(
      buildCommitteeDetailMetadataFromBundle({ detail: DEFAULT_COMMITTEE_DETAIL } as CommitteeDetailBundle)
    ).toEqual({
      title: "Committee One | Committee | Civibus",
      description: "Committee profile from campaign-finance records."
    });
  });

  it("falls back to generic committee metadata when detail name is empty", () => {
    expect(
      buildCommitteeDetailMetadataFromBundle({
        detail: { ...DEFAULT_COMMITTEE_DETAIL, name: "" }
      } as CommitteeDetailBundle)
    ).toEqual({
      title: "Committee | Committee | Civibus",
      description: "Committee profile from campaign-finance records."
    });
  });

  it("builds candidate route presentation for canonical and slug-collision route states", () => {
    const canonicalPresentation = buildCandidateRoutePresentation({
      routeKind: "canonical-detail",
      ...buildCandidateBundle()
    });
    const collisionPresentation = buildCandidateRoutePresentation({
      routeKind: "slug-collision",
      slug: "candidate-one",
      matches: [
        {
          id: CANDIDATE_ID,
          fec_candidate_id: "H0NC01001",
          name: "Candidate One",
          party: "DEM",
          office: "H",
          state: "NC",
          district: "01",
          slug: "candidate-one",
          slug_is_unique: true
        },
        {
          id: "99999999-9999-4999-8999-999999999999",
          fec_candidate_id: "H0NC01002",
          name: "Candidate Two",
          party: "DEM",
          office: "H",
          state: "NC",
          district: "02",
          slug: "candidate-one",
          slug_is_unique: false
        }
      ]
    });

    expect(canonicalPresentation.routeKind).toBe("canonical-detail");
    expect(canonicalPresentation.entityType).toBe("candidate");
    if (canonicalPresentation.routeKind === "canonical-detail") {
      expect(canonicalPresentation.shell.canonicalName).toBe("Candidate One");
      expect(canonicalPresentation.summary).toBeInstanceOf(Promise);
      expect(canonicalPresentation.ieTransactions).toBeInstanceOf(Promise);
      expect(canonicalPresentation.ieSummary).toBeInstanceOf(Promise);
      expect("detail" in canonicalPresentation).toBe(false);
    }
    expect(collisionPresentation).toEqual({
      routeKind: "slug-collision",
      entityType: "candidate",
      slug: "candidate-one",
      heading: 'Multiple candidates match "candidate-one"',
      chooserLabel: "Select a candidate record",
      matches: [
        {
          id: CANDIDATE_ID,
          name: "Candidate One",
          href: "/candidate/candidate-one"
        },
        {
          id: "99999999-9999-4999-8999-999999999999",
          name: "Candidate Two",
          href: "/candidate/99999999-9999-4999-8999-999999999999"
        }
      ]
    });
  });

  it("builds committee route presentation for canonical and slug-collision route states", () => {
    const canonicalPresentation = buildCommitteeRoutePresentation({
      routeKind: "canonical-detail",
      ...buildCommitteeBundle()
    });
    const collisionPresentation = buildCommitteeRoutePresentation({
      routeKind: "slug-collision",
      slug: "committee-one",
      matches: [
        {
          id: COMMITTEE_ID,
          fec_committee_id: "C12345678",
          name: "Committee One",
          committee_type: "Q",
          party: "DEM",
          state: "NC",
          slug: "committee-one",
          slug_is_unique: true
        },
        {
          id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
          fec_committee_id: "C00000000",
          name: "Committee Two",
          committee_type: "P",
          party: "DEM",
          state: "NC",
          slug: "committee-one",
          slug_is_unique: false
        }
      ]
    });

    expect(canonicalPresentation.routeKind).toBe("canonical-detail");
    expect(canonicalPresentation.entityType).toBe("committee");
    if (canonicalPresentation.routeKind === "canonical-detail") {
      expect(canonicalPresentation.shell.canonicalName).toBe("Committee One");
      expect(canonicalPresentation.transactions).toBeInstanceOf(Promise);
      expect(canonicalPresentation.summary).toBeInstanceOf(Promise);
      expect(canonicalPresentation.filingBreakdown).toBeInstanceOf(Promise);
      expect("detail" in canonicalPresentation).toBe(false);
    }
    expect(collisionPresentation).toEqual({
      routeKind: "slug-collision",
      entityType: "committee",
      slug: "committee-one",
      heading: 'Multiple committees match "committee-one"',
      chooserLabel: "Select a committee record",
      matches: [
        {
          id: COMMITTEE_ID,
          name: "Committee One",
          href: "/committee/committee-one"
        },
        {
          id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
          name: "Committee Two",
          href: "/committee/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        }
      ]
    });
  });

  it("emits a section order for committee detail with summary before trust before metrics before deep records", () => {
    const shell = buildCommitteeDetailShellPresentation(DEFAULT_COMMITTEE_DETAIL);

    expect(shell.sectionOrder).toEqual([
      "summary",
      "trust",
      "metrics",
      "records"
    ]);
  });

  it("emits a section order for candidate detail with summary before trust before metrics before outside-spending before records", () => {
    const shell = buildCandidateDetailShellPresentation(DEFAULT_CANDIDATE_DETAIL);

    expect(shell.sectionOrder).toEqual([
      "summary",
      "trust",
      "metrics",
      "outside-spending",
      "records"
    ]);
  });

});
