import { describe, expect, it } from "vitest";
import { buildTrustSection } from "$lib/detail-trust/presentation";
import {
  buildPersonCandidacyRows,
  buildPersonOfficeholdingTimelineRows,
  buildPersonSummaryChartSeries,
  buildPersonOutsideSpendingChartSeries,
  type ResolvedEntityDetailBundle,
  buildCanonicalDetailFacts,
  buildEntityDetailShellPresentation,
  buildEntityDetailMetadata,
  buildEntityDetailMetadataFromDetail,
  buildEntityDetailPresentation,
  buildErMatchSummaries,
  buildGraphNeighborRows,
  buildIdentifierRows,
  getEmptyPanelMessage
} from "./presentation";

const PERSON_ID = "11111111-1111-4111-8111-111111111111";
const ORG_ID = "22222222-2222-4222-8222-222222222222";

describe("entity detail presentation", () => {
  it("builds canonical person facts from backend detail payload", () => {
    const facts = buildCanonicalDetailFacts("person", {
      id: PERSON_ID,
      canonical_name: "Jane Doe",
      name_variants: ["J. Doe"],
      first_name: "Jane",
      middle_name: null,
      last_name: "Doe",
      suffix: null,
      occupation: "Attorney",
      education: "State University",
      date_of_birth: null,
      year_of_birth: 1980,
      bio_text: null,
      bio_source_url: null,
      bio_license: null,
      bio_pulled_at: null,
      identifiers: {},
      primary_address_id: null,
      er_cluster_id: null,
      er_confidence: 0.93,
      sources: []
    });

    expect(facts).toEqual([
      { label: "Canonical name", value: "Jane Doe" },
      { label: "First name", value: "Jane" },
      { label: "Last name", value: "Doe" },
      { label: "Occupation", value: "Attorney" },
      { label: "Education", value: "State University" },
      { label: "Year of birth", value: "1980" },
      { label: "ER confidence", value: "0.93" }
    ]);
  });

  it("builds deterministic officeholding timeline rows sorted by period then id", () => {
    const rows = buildPersonOfficeholdingTimelineRows([
      {
        id: "33333333-3333-4333-8333-333333333333",
        person_id: PERSON_ID,
        person_name: "Jane Doe",
        office_id: "office-3",
        electoral_division_id: null,
        holder_status: "elected",
        valid_period_lower: "2024-01-01",
        valid_period_upper: null,
        date_precision: "day",
        sources: []
      },
      {
        id: "11111111-1111-4111-8111-111111111111",
        person_id: PERSON_ID,
        person_name: "Jane Doe",
        office_id: "office-1",
        electoral_division_id: null,
        holder_status: "former",
        valid_period_lower: "2022-01-01",
        valid_period_upper: "2023-01-01",
        date_precision: "day",
        sources: []
      },
      {
        id: "22222222-2222-4222-8222-222222222222",
        person_id: PERSON_ID,
        person_name: "Jane Doe",
        office_id: "office-2",
        electoral_division_id: null,
        holder_status: "appointed",
        valid_period_lower: "2022-01-01",
        valid_period_upper: null,
        date_precision: "day",
        sources: []
      }
    ]);

    expect(rows.map((row) => row.officeholdingId)).toEqual([
      "33333333-3333-4333-8333-333333333333",
      "11111111-1111-4111-8111-111111111111",
      "22222222-2222-4222-8222-222222222222"
    ]);
    expect(rows[0]).toMatchObject({
      officeholdingLabel: "Officeholding record",
      officeLabel: "Office record"
    });
  });

  it("builds deterministic candidacy rows sorted by filing date then id", () => {
    const rows = buildPersonCandidacyRows([
      {
        id: "33333333-3333-4333-8333-333333333333",
        person_id: PERSON_ID,
        person_name: "Jane Doe",
        contest_id: "contest-3",
        party: null,
        filing_date: null,
        status: "qualified",
        incumbent_challenge: null,
        candidate_number: null,
        sources: []
      },
      {
        id: "11111111-1111-4111-8111-111111111111",
        person_id: PERSON_ID,
        person_name: "Jane Doe",
        contest_id: "contest-1",
        party: "DEM",
        filing_date: "2026-01-05",
        status: "qualified",
        incumbent_challenge: "I",
        candidate_number: "17",
        sources: []
      },
      {
        id: "22222222-2222-4222-8222-222222222222",
        person_id: PERSON_ID,
        person_name: "Jane Doe",
        contest_id: "contest-2",
        party: "DEM",
        filing_date: "2026-01-05",
        status: "filed",
        incumbent_challenge: "C",
        candidate_number: "18",
        sources: []
      }
    ]);

    expect(rows.map((row) => row.candidacyId)).toEqual([
      "11111111-1111-4111-8111-111111111111",
      "22222222-2222-4222-8222-222222222222",
      "33333333-3333-4333-8333-333333333333"
    ]);
    expect(rows[0]).toMatchObject({
      candidacyLabel: "Candidacy record",
      contestLabel: "Contest record"
    });
  });

  it("uses provided civic-history label lookups instead of raw ids/paths", () => {
    const officeholdingRows = buildPersonOfficeholdingTimelineRows(
      [
        {
          id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
          person_id: PERSON_ID,
          person_name: "Jane Doe",
          office_id: "office-1",
          electoral_division_id: null,
          holder_status: "elected",
          valid_period_lower: "2025-01-01",
          valid_period_upper: null,
          date_precision: "day",
          sources: []
        }
      ],
      {
        officeholdingLabelsById: { "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa": "Jane Doe officeholding" },
        officeLabelsById: { "office-1": "US House NC-01" }
      }
    );
    expect(officeholdingRows[0].officeholdingLabel).toBe("Jane Doe officeholding");
    expect(officeholdingRows[0].officeLabel).toBe("US House NC-01");

    const candidacyRows = buildPersonCandidacyRows(
      [
        {
          id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
          person_id: PERSON_ID,
          person_name: "Jane Doe",
          contest_id: "contest-1",
          party: "DEM",
          filing_date: "2026-01-10",
          status: "qualified",
          incumbent_challenge: "I",
          candidate_number: "17",
          sources: []
        }
      ],
      {
        candidacyLabelsById: { "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb": "Jane Doe candidacy" },
        contestLabelsById: { "contest-1": "NC-01 General Election" }
      }
    );
    expect(candidacyRows[0].candidacyLabel).toBe("Jane Doe candidacy");
    expect(candidacyRows[0].contestLabel).toBe("NC-01 General Election");
  });

  it("builds person summary and outside-spending chart series from finance values", () => {
    expect(
      buildPersonSummaryChartSeries({
        total_raised: "125.00",
        total_spent: "75.00",
        net: "50.00"
      })
    ).toEqual([
      {
        id: "finance",
        label: "Finance",
        points: [
          { x: "Raised", y: 125 },
          { x: "Spent", y: 75 },
          { x: "Net", y: 50 }
        ]
      }
    ]);

    expect(
      buildPersonOutsideSpendingChartSeries({
        support_total: "200.00",
        oppose_total: "80.00"
      })
    ).toEqual([
      {
        id: "outside-spending",
        label: "Outside spending",
        points: [
          { x: "Support", y: 200 },
          { x: "Oppose", y: 80 }
        ]
      }
    ]);
    expect(buildPersonOutsideSpendingChartSeries(null)).toEqual([]);
  });

  it("builds canonical organization facts from backend detail payload", () => {
    const facts = buildCanonicalDetailFacts("org", {
      id: ORG_ID,
      canonical_name: "Civibus Action Org",
      name_variants: [],
      org_type: "pac",
      identifiers: {},
      registered_state: "NC",
      formation_date: "2014-05-01",
      dissolution_date: null,
      primary_address_id: null,
      er_cluster_id: null,
      er_confidence: 0.88,
      sources: []
    });

    expect(facts).toEqual([
      { label: "Canonical name", value: "Civibus Action Org" },
      { label: "Organization type", value: "pac" },
      { label: "Registered state", value: "NC" },
      { label: "Formation date", value: "2014-05-01" },
      { label: "ER confidence", value: "0.88" }
    ]);
  });

  it("builds stable identifier rows sorted by key", () => {
    expect(
      buildIdentifierRows({
        zeta_id: "Z-1",
        alpha_id: "A-1"
      })
    ).toEqual([
      { label: "alpha_id", value: "A-1" },
      { label: "zeta_id", value: "Z-1" }
    ]);
  });

  it("builds trust-section data from the shared trust contract when provenance is present", () => {
    const sources = [
      {
        domain: "campaign_finance",
        jurisdiction: "federal/fec",
        data_source_name: "FEC",
        data_source_url: "https://www.fec.gov",
        source_record_key: "person-1",
        record_url: "https://example.org/person-1",
        pull_date: "2026-03-19T00:00:00Z"
      }
    ];
    const viewModel = buildEntityDetailPresentation({
      entityType: "person",
      detail: {
        id: PERSON_ID,
        canonical_name: "Jane Doe",
        name_variants: [],
        first_name: "Jane",
        middle_name: null,
        last_name: "Doe",
        suffix: null,
        date_of_birth: null,
        year_of_birth: null,
        bio_text: null,
        bio_source_url: null,
        bio_license: null,
        bio_pulled_at: null,
        identifiers: {},
        primary_address_id: null,
        er_cluster_id: null,
        er_confidence: null,
        sources
      },
      matches: [],
      relationships: {
        entity_type: "person",
        entity_id: PERSON_ID,
        neighbors: [],
        total_count: 0
      }
    } satisfies ResolvedEntityDetailBundle);

    expect(viewModel.trustSection).toEqual(buildTrustSection(sources));
  });

  it("builds ER match summaries against the subject entity ID", () => {
    const rows = buildErMatchSummaries(
      [
        {
          id: "44444444-4444-4444-8444-444444444444",
          entity_type: "person",
          entity_id_a: PERSON_ID,
          entity_id_b: ORG_ID,
          decision: "match",
          confidence: 0.97,
          decided_by: "splink_v1",
          decision_method: "probabilistic",
          match_evidence: { name_similarity: 0.98 },
          decided_at: "2026-03-19T00:00:00Z"
        }
      ],
      PERSON_ID
    );

    expect(rows).toEqual([
      {
        counterpartEntityId: ORG_ID,
        decision: "match",
        confidence: "0.97",
        decidedAt: "2026-03-19T00:00:00Z"
      }
    ]);
  });

  it("builds graph neighbor rows with committee/candidate links and metadata-only unsupported types", () => {
    const rows = buildGraphNeighborRows([
      {
        entity_type: "person",
        entity_id: PERSON_ID,
        name: "Jane Doe",
        relationship_type: "SAME_AS",
        direction: "outbound"
      },
      {
        entity_type: "filing",
        entity_id: ORG_ID,
        name: "Q1 Filing",
        relationship_type: "FILED",
        direction: "inbound"
      },
      {
        entity_type: "committee",
        entity_id: ORG_ID,
        name: "Committee XYZ",
        relationship_type: "AFFILIATED_WITH",
        direction: "outbound"
      },
      {
        entity_type: "candidate",
        entity_id: ORG_ID,
        name: "Candidate ABC",
        relationship_type: "SUPPORTS",
        direction: "outbound"
      }
    ]);

    expect(rows).toEqual([
      {
        title: "Jane Doe",
        entityType: "person",
        relationshipType: "SAME_AS",
        direction: "outbound",
        href: `/person/${PERSON_ID}`
      },
      {
        title: "Q1 Filing",
        entityType: "filing",
        relationshipType: "FILED",
        direction: "inbound",
        href: null
      },
      {
        title: "Committee XYZ",
        entityType: "committee",
        relationshipType: "AFFILIATED_WITH",
        direction: "outbound",
        href: `/committee/${ORG_ID}`
      },
      {
        title: "Candidate ABC",
        entityType: "candidate",
        relationshipType: "SUPPORTS",
        direction: "outbound",
        href: `/candidate/${ORG_ID}`
      }
    ]);
  });

  it("returns stable empty panel messaging", () => {
    expect(getEmptyPanelMessage("identifiers")).toBe(
      "No identifiers are available yet. Check related records after the next refresh."
    );
    expect(getEmptyPanelMessage("matches")).toBe(
      "No entity-resolution matches are available yet. Check back after the next ER refresh."
    );
    expect(getEmptyPanelMessage("neighbors")).toBe(
      "No graph relationships are available yet. Linked records will appear after future ingests."
    );
  });

  it("builds shell key metrics for person detail from identifier rows while ER and graph data are loading", () => {
    const shellViewModel = buildEntityDetailShellPresentation({
      entityType: "person",
      detail: {
        id: PERSON_ID,
        canonical_name: "Jane Doe",
        name_variants: [],
        first_name: "Jane",
        middle_name: null,
        last_name: "Doe",
        suffix: null,
        date_of_birth: null,
        year_of_birth: null,
        bio_text: null,
        bio_source_url: null,
        bio_license: null,
        bio_pulled_at: null,
        identifiers: {
          alpha_id: "A-1",
          beta_id: "B-1",
          gamma_id: "C-1"
        },
        primary_address_id: null,
        er_cluster_id: null,
        er_confidence: null,
        sources: []
      }
    });

    expect(shellViewModel.keyMetricRows).toEqual([
      { label: "Identifiers", value: "3" },
      { label: "ER matches", value: "Loading..." },
      { label: "Graph relationships", value: "Loading..." }
    ]);
  });

  it("builds org shell key metrics with loading placeholders and excludes civic-record from section order", () => {
    const shellViewModel = buildEntityDetailShellPresentation({
      entityType: "org",
      detail: {
        id: ORG_ID,
        canonical_name: "Civibus Action Org",
        name_variants: [],
        org_type: "pac",
        identifiers: {
          fec_committee_id: "C12345678",
          state_committee_id: "NC-001"
        },
        registered_state: "NC",
        formation_date: "2014-05-01",
        dissolution_date: null,
        primary_address_id: null,
        er_cluster_id: null,
        er_confidence: null,
        sources: []
      }
    });

    expect(shellViewModel.keyMetricRows).toEqual([
      { label: "Identifiers", value: "2" },
      { label: "ER matches", value: "Loading..." },
      { label: "Graph relationships", value: "Loading..." }
    ]);
    expect(shellViewModel.sectionOrder).toEqual([
      "summary",
      "trust",
      "metrics",
      "records",
      "technical-disclosure"
    ]);
    expect(shellViewModel.sectionOrder).not.toContain("civic-record");
  });

  it("builds page view data with empty-state messages when panels have no rows", () => {
    const sources: ResolvedEntityDetailBundle["detail"]["sources"] = [];
    const viewModel = buildEntityDetailPresentation({
      entityType: "person",
      detail: {
        id: PERSON_ID,
        canonical_name: "Jane Doe",
        name_variants: [],
        first_name: "Jane",
        middle_name: null,
        last_name: "Doe",
        suffix: null,
        date_of_birth: null,
        year_of_birth: null,
        bio_text: null,
        bio_source_url: null,
        bio_license: null,
        bio_pulled_at: null,
        identifiers: {},
        primary_address_id: null,
        er_cluster_id: null,
        er_confidence: null,
        sources
      },
      matches: [],
      relationships: {
        entity_type: "person",
        entity_id: PERSON_ID,
        neighbors: [],
        total_count: 0
      }
    } satisfies ResolvedEntityDetailBundle);

    expect(viewModel.canonicalName).toBe("Jane Doe");
    expect(viewModel.sectionOrder).toEqual([
      "summary",
      "trust",
      "metrics",
      "records",
      "civic-record",
      "person-civic-history",
      "person-campaign-finance",
      "technical-disclosure"
    ]);
    expect(viewModel.keyMetricRows).toEqual([
      { label: "Identifiers", value: "0" },
      { label: "ER matches", value: "0" },
      { label: "Graph relationships", value: "0" }
    ]);
    expect(viewModel.identifierRows).toEqual([]);
    expect(viewModel.identifierEmptyMessage).toBe(
      "No identifiers are available yet. Check related records after the next refresh."
    );
    expect(viewModel.matchRows).toEqual([]);
    expect(viewModel.matchEmptyMessage).toBe(
      "No entity-resolution matches are available yet. Check back after the next ER refresh."
    );
    expect(viewModel.neighborRows).toEqual([]);
    expect(viewModel.neighborEmptyMessage).toBe(
      "No graph relationships are available yet. Linked records will appear after future ingests."
    );
    expect(viewModel.trustSection).toEqual(buildTrustSection(sources));
  });

  it("derives key metrics from payload counts while keeping internals in technical disclosure content", () => {
    const viewModel = buildEntityDetailPresentation({
      entityType: "org",
      detail: {
        id: ORG_ID,
        canonical_name: "Civibus Action Org",
        name_variants: [],
        org_type: "pac",
        identifiers: {
          alpha_id: "A-1",
          beta_id: "B-1"
        },
        registered_state: "NC",
        formation_date: "2014-05-01",
        dissolution_date: null,
        primary_address_id: null,
        er_cluster_id: null,
        er_confidence: null,
        sources: []
      },
      matches: [
        {
          id: "33333333-3333-4333-8333-333333333333",
          entity_type: "organization",
          entity_id_a: ORG_ID,
          entity_id_b: PERSON_ID,
          decision: "possible_match",
          confidence: 0.74,
          decided_by: "splink_v1",
          decision_method: "probabilistic",
          match_evidence: { name_similarity: 0.8 },
          decided_at: "2026-03-19T00:00:00Z"
        }
      ],
      relationships: {
        entity_type: "org",
        entity_id: ORG_ID,
        neighbors: [
          {
            entity_type: "filing",
            entity_id: "f-1",
            name: "Org Filing",
            relationship_type: "FILED",
            direction: "inbound"
          }
        ],
        total_count: 7
      }
    } satisfies ResolvedEntityDetailBundle);

    expect(viewModel.keyMetricRows).toEqual([
      { label: "Identifiers", value: "2" },
      { label: "ER matches", value: "1" },
      { label: "Graph relationships", value: "7" }
    ]);
    expect(viewModel.technicalDisclosure.summary).toBe(
      "Entity-resolution and graph internals"
    );
    expect(viewModel.technicalDisclosure.matchRows).toEqual(viewModel.matchRows);
    expect(viewModel.technicalDisclosure.neighborRows).toEqual(viewModel.neighborRows);
  });

  it("builds a structured civic record section for person detail from candidacy/officeholding graph neighbors", () => {
    const viewModel = buildEntityDetailPresentation({
      entityType: "person",
      detail: {
        id: PERSON_ID,
        canonical_name: "Jane Doe",
        name_variants: [],
        first_name: "Jane",
        middle_name: null,
        last_name: "Doe",
        suffix: null,
        date_of_birth: null,
        year_of_birth: null,
        bio_text: null,
        bio_source_url: null,
        bio_license: null,
        bio_pulled_at: null,
        identifiers: {},
        primary_address_id: null,
        er_cluster_id: null,
        er_confidence: null,
        sources: []
      },
      matches: [],
      relationships: {
        entity_type: "person",
        entity_id: PERSON_ID,
        neighbors: [
          {
            entity_type: "candidacy",
            entity_id: "88888888-8888-4888-8888-888888888888",
            name: "Jane Doe candidacy",
            relationship_type: "CANDIDACY_OF",
            direction: "outbound"
          },
          {
            entity_type: "officeholding",
            entity_id: "99999999-9999-4999-8999-999999999999",
            name: "Jane Doe officeholding",
            relationship_type: "HOLDS",
            direction: "outbound"
          },
          {
            entity_type: "contest",
            entity_id: "77777777-7777-4777-8777-777777777777",
            name: "NC-01 General",
            relationship_type: "RUNS_IN",
            direction: "outbound"
          },
          {
            entity_type: "office",
            entity_id: "33333333-3333-4333-8333-333333333333",
            name: "US House NC-01",
            relationship_type: "HOLDS",
            direction: "outbound"
          }
        ],
        total_count: 4
      }
    } satisfies ResolvedEntityDetailBundle);

    const contract = viewModel as unknown as Record<string, unknown>;
    expect(contract.sectionOrder).toEqual([
      "summary",
      "trust",
      "metrics",
      "records",
      "civic-record",
      "person-civic-history",
      "person-campaign-finance",
      "technical-disclosure"
    ]);
    expect(contract.civicRecordSection).toEqual({
      title: "Civic Record",
      rows: [
        {
          recordType: "Candidacy",
          recordName: "Jane Doe candidacy",
          recordHref: "/candidacy/88888888-8888-4888-8888-888888888888",
          contextLabel: "Contest",
          contextName: "NC-01 General",
          contextHref: "/contest/77777777-7777-4777-8777-777777777777"
        },
        {
          recordType: "Officeholding",
          recordName: "Jane Doe officeholding",
          recordHref: "/officeholding/99999999-9999-4999-8999-999999999999",
          contextLabel: "Office",
          contextName: "US House NC-01",
          contextHref: "/office/33333333-3333-4333-8333-333333333333"
        }
      ],
      emptyMessage: null
    });
    expect(viewModel.technicalDisclosure.neighborRows).toHaveLength(4);
  });

  it("keeps civic record section visible with empty-state copy when person neighbors have no civic rows", () => {
    const viewModel = buildEntityDetailPresentation({
      entityType: "person",
      detail: {
        id: PERSON_ID,
        canonical_name: "Jane Doe",
        name_variants: [],
        first_name: "Jane",
        middle_name: null,
        last_name: "Doe",
        suffix: null,
        date_of_birth: null,
        year_of_birth: null,
        bio_text: null,
        bio_source_url: null,
        bio_license: null,
        bio_pulled_at: null,
        identifiers: {},
        primary_address_id: null,
        er_cluster_id: null,
        er_confidence: null,
        sources: []
      },
      matches: [],
      relationships: {
        entity_type: "person",
        entity_id: PERSON_ID,
        neighbors: [
          {
            entity_type: "office",
            entity_id: "33333333-3333-4333-8333-333333333333",
            name: "US House NC-01",
            relationship_type: "ELIGIBLE_FOR",
            direction: "outbound"
          }
        ],
        total_count: 1
      }
    } satisfies ResolvedEntityDetailBundle);

    expect(viewModel.sectionOrder).toContain("civic-record");
    expect(viewModel.civicRecordSection).toEqual({
      title: "Civic Record",
      rows: [],
      emptyMessage: "No civic record relationships are available yet."
    });
  });

  it("excludes civic record section from org detail and omits it from org section order", () => {
    const viewModel = buildEntityDetailPresentation({
      entityType: "org",
      detail: {
        id: ORG_ID,
        canonical_name: "Civibus Action Org",
        name_variants: [],
        org_type: "pac",
        identifiers: {},
        registered_state: "NC",
        formation_date: "2014-05-01",
        dissolution_date: null,
        primary_address_id: null,
        er_cluster_id: null,
        er_confidence: null,
        sources: []
      },
      matches: [],
      relationships: {
        entity_type: "org",
        entity_id: ORG_ID,
        neighbors: [],
        total_count: 0
      }
    } satisfies ResolvedEntityDetailBundle);

    expect(viewModel.civicRecordSection).toBeNull();
    expect(viewModel.sectionOrder).toEqual([
      "summary",
      "trust",
      "metrics",
      "records",
      "technical-disclosure"
    ]);
    expect(viewModel.sectionOrder).not.toContain("civic-record");
  });

  it("does not duplicate route metadata inside the entity detail view model", () => {
    const viewModel = buildEntityDetailPresentation({
      entityType: "person",
      detail: {
        id: PERSON_ID,
        canonical_name: "Jane Doe",
        name_variants: [],
        first_name: "Jane",
        middle_name: null,
        last_name: "Doe",
        suffix: null,
        date_of_birth: null,
        year_of_birth: null,
        bio_text: null,
        bio_source_url: null,
        bio_license: null,
        bio_pulled_at: null,
        identifiers: {},
        primary_address_id: null,
        er_cluster_id: null,
        er_confidence: null,
        sources: []
      },
      matches: [],
      relationships: {
        entity_type: "person",
        entity_id: PERSON_ID,
        neighbors: [],
        total_count: 0
      }
    } satisfies ResolvedEntityDetailBundle);

    expect("metadata" in viewModel).toBe(false);
  });

  it("builds metadata title and description from entity detail presentation data", () => {
    expect(
      buildEntityDetailMetadata({
        entityType: "person",
        canonicalName: "Jane Doe",
        identifierCount: 2,
        matchCount: 1,
        neighborCount: 0
      })
    ).toEqual({
      title: "Jane Doe | Person | Civibus",
      description: "Person profile with 2 identifiers, 1 ER match, and 0 graph relationships."
    });
  });

  it("uses irregular plural labels for ER matches in metadata descriptions", () => {
    expect(
      buildEntityDetailMetadata({
        entityType: "person",
        canonicalName: "Jane Doe",
        identifierCount: 1,
        matchCount: 0,
        neighborCount: 1
      })
    ).toEqual({
      title: "Jane Doe | Person | Civibus",
      description: "Person profile with 1 identifier, 0 ER matches, and 1 graph relationship."
    });
  });

  it("builds organization metadata labels for org detail routes", () => {
    expect(
      buildEntityDetailMetadata({
        entityType: "org",
        canonicalName: "Civibus Action Org",
        identifierCount: 1,
        matchCount: 0,
        neighborCount: 1
      })
    ).toEqual({
      title: "Civibus Action Org | Organization | Civibus",
      description: "Organization profile with 1 identifier, 0 ER matches, and 1 graph relationship."
    });
  });

  it("builds entity route metadata directly from detail payload only", () => {
    expect(
      buildEntityDetailMetadataFromDetail({
        entityType: "person",
        detail: {
          id: PERSON_ID,
          canonical_name: "Jane Doe",
          name_variants: [],
          first_name: "Jane",
          middle_name: null,
          last_name: "Doe",
          suffix: null,
          date_of_birth: null,
          year_of_birth: null,
          bio_text: null,
          bio_source_url: null,
          bio_license: null,
          bio_pulled_at: null,
          identifiers: {
            alpha_id: "A-1"
          },
          primary_address_id: null,
          er_cluster_id: null,
          er_confidence: null,
          sources: []
        }
      })
    ).toEqual({
      title: "Jane Doe | Person | Civibus",
      description: "Person profile with 1 identifier and source-linked records."
    });
  });

  it("builds organization route metadata directly from detail payload only", () => {
    expect(
      buildEntityDetailMetadataFromDetail({
        entityType: "org",
        detail: {
          id: ORG_ID,
          canonical_name: "Civibus Action Org",
          name_variants: [],
          org_type: "pac",
          identifiers: {
            fec_committee_id: "C12345678",
            state_committee_id: "NC-001"
          },
          registered_state: "NC",
          formation_date: "2014-05-01",
          dissolution_date: null,
          primary_address_id: null,
          er_cluster_id: null,
          er_confidence: null,
          sources: []
        }
      })
    ).toEqual({
      title: "Civibus Action Org | Organization | Civibus",
      description: "Organization profile with 2 identifiers and source-linked records."
    });
  });
});
