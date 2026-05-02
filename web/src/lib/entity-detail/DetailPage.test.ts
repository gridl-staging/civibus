import { readFileSync } from "node:fs";
import { describe, expect, it, vi } from "vitest";
import { render } from "svelte/server";
import type {
  EntityDetailBundle,
  EntityDetailPageBundle,
  PersonCivicHistorySections
} from "$lib/server/api/entity-detail";
import type { PersonCandidateFinanceSection } from "$lib/server/api/campaign-finance-detail";
import DetailPage from "./DetailPage.svelte";

vi.mock("$app/navigation", () => ({
  goto: vi.fn()
}));

const PERSON_ID = "11111111-1111-4111-8111-111111111111";
const OFFICEHOLDING_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const OFFICE_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const CANDIDACY_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
const CONTEST_ID = "dddddddd-dddd-4ddd-8ddd-dddddddddddd";
const CANDIDATE_ID = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee";
const COMMITTEE_ID = "ffffffff-ffff-4fff-8fff-ffffffffffff";

function asSettled<T>(value: T): Promise<T> {
  return value as unknown as Promise<T>;
}

function buildPersonCivicHistory(
  overrides: Partial<PersonCivicHistorySections> = {}
): PersonCivicHistorySections {
  return {
    officeholdings: [],
    candidacies: [],
    officeholdingLabelsById: {},
    officeLabelsById: {},
    candidacyLabelsById: {},
    contestLabelsById: {},
    ...overrides
  };
}

function buildPersonFinanceSection(
  overrides: Partial<PersonCandidateFinanceSection> = {}
): PersonCandidateFinanceSection {
  return {
    candidate: {
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
    },
    summary: asSettled({
      candidate_id: CANDIDATE_ID,
      candidate_name: "Candidate One",
      total_raised: "1000.00",
      total_spent: "600.00",
      net: "400.00",
      transaction_count: 3,
      committees: [
        {
          committee_id: COMMITTEE_ID,
          committee_name: "Friends of Candidate One",
          slug: "friends-of-candidate-one",
          slug_is_unique: true,
          total_raised: "750.00",
          total_spent: "400.00",
          net: "350.00",
          transaction_count: 2,
          jurisdiction: "NC",
          data_through: "2026-03-31",
          cash_receipts_total: "700.00",
          in_kind_receipts_total: "20.00",
          loan_receipts_total: "30.00",
          contribution_receipts_total: "710.00",
          top_donors: [],
          top_vendors: [],
          spend_categories: null
        }
      ]
    }),
    ieTransactions: asSettled([
      {
        id: "ie-1",
        filing_id: null,
        committee_id: COMMITTEE_ID,
        committee_name: "Outside Group A",
        amount: 1250,
        transaction_date: "2026-02-01",
        purpose: "Digital ads",
        dissemination_date: "2026-02-02",
        aggregate_amount: null,
        support_oppose: "S"
      }
    ]),
    ieSummary: asSettled({
      candidate_id: CANDIDATE_ID,
      support_total: "1250.00",
      oppose_total: "200.00",
      support_count: 1,
      oppose_count: 1,
      top_spenders: [
        {
          committee_id: COMMITTEE_ID,
          committee_name: "Outside Group A",
          support_oppose: "S",
          total_amount: "1250.00",
          transaction_count: 1
        }
      ]
    }),
    donorVendorTransactions: asSettled([
      {
        id: "tx-1",
        filing_id: "filing-1",
        committee_id: COMMITTEE_ID,
        transaction_type: "CONTRIBUTION",
        transaction_identifier: null,
        transaction_date: "2026-01-15",
        amount: 125.5,
        contributor_name_raw: "Acme Donor LLC",
        contributor_employer: null,
        contributor_occupation: null,
        contributor_city: null,
        contributor_state: null,
        contributor_zip: null,
        contributor_person_id: null,
        contributor_organization_id: null,
        contributor_address_id: null,
        recipient_candidate_id: CANDIDATE_ID,
        recipient_committee_id: COMMITTEE_ID,
        memo_text: null,
        is_memo: false,
        amendment_indicator: "N",
        date_is_reliable: true
      }
    ]),
    ...overrides
  };
}

function buildPersonPageBundle(
  overrides: Partial<EntityDetailPageBundle> = {}
): EntityDetailPageBundle {
  return {
    entityType: "person",
    detail: {
      id: PERSON_ID,
      canonical_name: "Jane Doe",
      name_variants: [],
      first_name: "Jane",
      middle_name: null,
      last_name: "Doe",
      suffix: null,
      occupation: "Attorney",
      education: "State University",
      date_of_birth: null,
      year_of_birth: 1985,
      bio_text: null,
      bio_source_url: null,
      bio_license: null,
      bio_pulled_at: null,
      identifiers: {},
      primary_address_id: null,
      er_cluster_id: null,
      er_confidence: null,
      portrait: {
        status: "active",
        rights_status: "licensed",
        source_image_url: "https://images.example.org/jane-doe.jpg",
        mime_type: "image/jpeg",
        width_px: 512,
        height_px: 512
      },
      sources: []
    },
    matches: asSettled([]),
    relationships: asSettled({
      entity_type: "person",
      entity_id: PERSON_ID,
      neighbors: [],
      total_count: 0
    }),
    personCivicHistory: asSettled(buildPersonCivicHistory()),
    personFinanceSections: asSettled([]),
    ...overrides
  };
}

describe("entity detail page rendering", () => {
  it("uses the shared portrait primitive in the header for person detail", () => {
    const source = readFileSync(new URL("./DetailPage.svelte", import.meta.url), "utf8");

    expect(source).toContain('import Portrait from "$lib/portrait/Portrait.svelte";');
    expect(source).toContain('{#if data.entityType === "person"}');
    expect(source).toContain('<Portrait canonicalName={shellViewModel.canonicalName} personId={data.detail.id} {portrait} />');
  });

  it("keeps metrics await wiring inline with explicit resolved and catch branches", () => {
    const source = readFileSync(new URL("./DetailPage.svelte", import.meta.url), "utf8");
    const metricsSectionStart = source.indexOf('{:else if sectionKey === "metrics"}');
    const recordsSectionStart = source.indexOf('{:else if sectionKey === "records"}');

    expect(metricsSectionStart).toBeGreaterThan(-1);
    expect(recordsSectionStart).toBeGreaterThan(metricsSectionStart);

    const metricsSection = source.slice(metricsSectionStart, recordsSectionStart);

    expect(metricsSection).toContain("{#await Promise.all([data.matches, data.relationships])}");
    expect(metricsSection).toContain("{:then [matches, relationships]}");
    expect(metricsSection).toContain("{:catch}");
    expect(metricsSection).toMatch(
      /buildResolvedKeyMetrics\(\s*shellViewModel\.identifierRows,\s*matches,\s*relationships\s*\)/
    );
    expect(metricsSection).toMatch(
      /buildUnavailableKeyMetrics\(\s*shellViewModel\.identifierRows\s*\)/
    );
    expect(metricsSection).not.toContain("{#await keyMetricRowsPromise}");
  });

  it("renders shell key metrics with identifier count and loading placeholders while async resources are pending", () => {
    const pendingRelationships = new Promise<never>(() => {});
    const pendingMatches = new Promise<never>(() => {});
    const data: EntityDetailBundle = {
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
          beta_id: "B-1"
        },
        primary_address_id: null,
        er_cluster_id: null,
        er_confidence: null,
        sources: []
      },
      matches: pendingMatches,
      relationships: pendingRelationships
    };

    const rendered = render(DetailPage, { props: { data } });

    expect(rendered.body).toContain("<h3>Key metrics</h3>");
    expect(rendered.body).toContain("<dt>Identifiers</dt>");
    expect(rendered.body).toContain("<dd>2</dd>");
    expect(rendered.body).toContain("<dt>ER matches</dt>");
    expect(rendered.body).toContain("<dt>Graph relationships</dt>");
    expect(rendered.body).toContain('data-testid="entity-metric-identifiers"');
    expect(rendered.body).toContain('data-testid="entity-metric-er-matches"');
    expect(rendered.body).toContain('data-testid="entity-metric-graph-relationships"');
    expect(rendered.body).toContain("Loading...");
  });

  it("renders person bio section with source link and mapped license label", () => {
    const data: EntityDetailBundle = {
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
        year_of_birth: 1980,
        bio_text: "Jane Doe is serving her third term in office.",
        bio_source_url: "https://www.ncleg.gov/Members/Biography/H/57",
        bio_license: "licensed",
        bio_pulled_at: "2026-04-29T14:30:00Z",
        identifiers: {},
        primary_address_id: null,
        er_cluster_id: null,
        er_confidence: null,
        portrait: null,
        sources: []
      },
      matches: Promise.resolve([]),
      relationships: Promise.resolve({
        entity_type: "person",
        entity_id: PERSON_ID,
        neighbors: [],
        total_count: 0
      })
    };

    const rendered = render(DetailPage, { props: { data } });
    expect(rendered.body).toContain("<h3>Biography</h3>");
    expect(rendered.body).toContain("Jane Doe is serving her third term in office.");
    expect(rendered.body).toContain('href="https://www.ncleg.gov/Members/Biography/H/57"');
    expect(rendered.body).toContain('rel="noopener noreferrer"');
    expect(rendered.body).toContain("Licensed (CC BY-SA)");
  });

  it("does not render a clickable bio link for unsafe bio source URL schemes", () => {
    const data: EntityDetailBundle = {
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
        year_of_birth: 1980,
        bio_text: "Jane Doe is serving her third term in office.",
        bio_source_url: "javascript:alert(1)",
        bio_license: "unknown",
        bio_pulled_at: "2026-04-29T14:30:00Z",
        identifiers: {},
        primary_address_id: null,
        er_cluster_id: null,
        er_confidence: null,
        portrait: null,
        sources: []
      },
      matches: Promise.resolve([]),
      relationships: Promise.resolve({
        entity_type: "person",
        entity_id: PERSON_ID,
        neighbors: [],
        total_count: 0
      })
    };

    const rendered = render(DetailPage, { props: { data } });
    expect(rendered.body).not.toContain('href="javascript:alert(1)"');
    expect(rendered.body).toContain("Biography source unavailable");
  });

  it("maps all supported bio license values to the expected labels", () => {
    const cases = [
      { value: "public_domain", label: "Public domain" },
      { value: "licensed", label: "Licensed (CC BY-SA)" },
      { value: "restricted", label: "Used with attribution" },
      { value: "unknown", label: "Source unknown" }
    ] as const;

    for (const testCase of cases) {
      const data: EntityDetailBundle = {
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
          bio_text: "Test biography",
          bio_source_url: "https://example.org/bio",
          bio_license: testCase.value,
          bio_pulled_at: null,
          identifiers: {},
          primary_address_id: null,
          er_cluster_id: null,
          er_confidence: null,
          portrait: null,
          sources: []
        },
        matches: Promise.resolve([]),
        relationships: Promise.resolve({
          entity_type: "person",
          entity_id: PERSON_ID,
          neighbors: [],
          total_count: 0
        })
      };

      const rendered = render(DetailPage, { props: { data } });
      expect(rendered.body).toContain(testCase.label);
    }
  });

  it("iterates resolved key metric rows only in the metrics then-branch", () => {
    const source = readFileSync(new URL("./DetailPage.svelte", import.meta.url), "utf8");
    const metricsSectionStart = source.indexOf('{:else if sectionKey === "metrics"}');
    const recordsSectionStart = source.indexOf('{:else if sectionKey === "records"}');
    const thenBranchStart = source.indexOf("{:then [matches, relationships]}", metricsSectionStart);
    const catchBranchStart = source.indexOf("{:catch}", thenBranchStart);

    expect(thenBranchStart).toBeGreaterThan(metricsSectionStart);
    expect(catchBranchStart).toBeGreaterThan(thenBranchStart);

    const thenBranch = source.slice(thenBranchStart, catchBranchStart);
    expect(recordsSectionStart).toBeGreaterThan(metricsSectionStart);
    expect(thenBranch).toContain("{@const resolvedKeyMetricRows = buildResolvedKeyMetrics(");
    expect(thenBranch).toContain("{#each resolvedKeyMetricRows as row (row.label)}");
    expect(thenBranch).not.toContain("{#each shellViewModel.keyMetricRows as row (row.label)}");
    expect(thenBranch).not.toContain("{#each unavailableKeyMetricRows as row (row.label)}");
  });

  it("iterates unavailable key metric rows only in the metrics catch-branch", () => {
    const source = readFileSync(new URL("./DetailPage.svelte", import.meta.url), "utf8");
    const metricsSectionStart = source.indexOf('{:else if sectionKey === "metrics"}');
    const recordsSectionStart = source.indexOf('{:else if sectionKey === "records"}');
    const catchBranchStart = source.indexOf("{:catch}", metricsSectionStart);

    expect(catchBranchStart).toBeGreaterThan(metricsSectionStart);
    expect(recordsSectionStart).toBeGreaterThan(catchBranchStart);

    const catchBranch = source.slice(catchBranchStart, recordsSectionStart);
    expect(catchBranch).toContain("{@const unavailableKeyMetricRows = buildUnavailableKeyMetrics(");
    expect(catchBranch).toContain("{#each unavailableKeyMetricRows as row (row.label)}");
    expect(catchBranch).not.toContain("{#each shellViewModel.keyMetricRows as row (row.label)}");
    expect(catchBranch).not.toContain("{#each resolvedKeyMetricRows as row (row.label)}");
  });

  it("verifies civic-record then-branch table markup via source inspection and removes debug labels", () => {
    const source = readFileSync(new URL("./DetailPage.svelte", import.meta.url), "utf8");
    const civicRecordStart = source.indexOf('{:else if sectionKey === "civic-record"}');
    const technicalStart = source.indexOf('{:else if sectionKey === "technical-disclosure"}');

    expect(civicRecordStart).toBeGreaterThan(-1);
    expect(technicalStart).toBeGreaterThan(civicRecordStart);

    const civicRecordSection = source.slice(civicRecordStart, technicalStart);

    expect(civicRecordSection).toContain("{#await data.relationships}");
    expect(civicRecordSection).toContain("{:then relationships}");
    expect(civicRecordSection).toContain('class="detail__table-scroll"');
    expect(civicRecordSection).toContain("<table>");
    expect(civicRecordSection).toContain("<thead>");
    expect(civicRecordSection).toMatch(/<th(?:\s+scope="col")?>Record<\/th>/);
    expect(civicRecordSection).toMatch(/<th(?:\s+scope="col")?>Record type<\/th>/);
    expect(civicRecordSection).toMatch(/<th(?:\s+scope="col")?>Office\/contest context<\/th>/);
    expect(civicRecordSection).not.toContain('<ul class="detail__list">');
    expect(civicRecordSection).not.toContain("record type:");
  });

  it("verifies technical-disclosure then-branch table markup via source inspection and removes debug labels", () => {
    const source = readFileSync(new URL("./DetailPage.svelte", import.meta.url), "utf8");
    const technicalStart = source.indexOf('{:else if sectionKey === "technical-disclosure"}');
    const templateEnd = source.length;

    expect(technicalStart).toBeGreaterThan(-1);

    const technicalSection = source.slice(technicalStart, templateEnd);

    expect(technicalSection).toContain("{#await Promise.all([data.matches, data.relationships])}");
    expect(technicalSection).toContain("{:then [matches, relationships]}");
    expect(technicalSection).toMatch(/<th(?:\s+scope="col")?>Counterpart entity<\/th>/);
    expect(technicalSection).toMatch(/<th(?:\s+scope="col")?>Decision<\/th>/);
    expect(technicalSection).toMatch(/<th(?:\s+scope="col")?>Confidence<\/th>/);
    expect(technicalSection).toMatch(/<th(?:\s+scope="col")?>Decided at<\/th>/);
    expect(technicalSection).toMatch(/<th(?:\s+scope="col")?>Neighbor<\/th>/);
    expect(technicalSection).toMatch(/<th(?:\s+scope="col")?>Entity type<\/th>/);
    expect(technicalSection).toMatch(/<th(?:\s+scope="col")?>Relationship<\/th>/);
    expect(technicalSection).toMatch(/<th(?:\s+scope="col")?>Direction<\/th>/);
    expect(technicalSection).toContain(
      "<p id={graphNeighborListId}>{technicalDisclosure.neighborEmptyMessage}</p>"
    );
    expect(technicalSection).not.toContain('<ul class="detail__list">');
    expect(technicalSection).not.toContain("entity type:");
    expect(technicalSection).not.toContain("relationship:");
    expect(technicalSection).not.toContain("direction:");
    expect(technicalSection).not.toContain("counterpart:");
    expect(technicalSection).not.toContain("decision:");
    expect(technicalSection).not.toContain("confidence:");
    expect(technicalSection).not.toContain("decided at:");
  });

  it("renders person civic-history and campaign-finance sections inside the canonical section-order loop", () => {
    const source = readFileSync(new URL("./DetailPage.svelte", import.meta.url), "utf8");
    const civicHistoryBranchStart = source.indexOf('{:else if sectionKey === "person-civic-history"}');
    const campaignFinanceBranchStart = source.indexOf('{:else if sectionKey === "person-campaign-finance"}');
    const technicalDisclosureBranchStart = source.indexOf('{:else if sectionKey === "technical-disclosure"}');

    expect(civicHistoryBranchStart).toBeGreaterThan(-1);
    expect(campaignFinanceBranchStart).toBeGreaterThan(civicHistoryBranchStart);
    expect(technicalDisclosureBranchStart).toBeGreaterThan(campaignFinanceBranchStart);
    expect(source).toContain("<h3>Officeholding timeline</h3>");
    expect(source).toContain("<h3>Candidacies</h3>");
    expect(source).toContain("<h3>Campaign finance</h3>");
    expect(source).toContain("<h4>Donors and vendors</h4>");
    expect(source).toContain("<h4>Outside Spending</h4>");
    expect(source).toContain("<Chart");
    expect(source).toContain('kind="bar"');
    expect(source).not.toContain("person-page-local finance warning");
    expect(source).toContain("{row.officeholdingLabel}");
    expect(source).toContain("{row.officeLabel}");
    expect(source).toContain("{row.candidacyLabel}");
    expect(source).toContain("{row.contestLabel}");
    expect(source).not.toContain("{row.officeholdingId}</a>");
    expect(source).not.toContain("{row.officeHref}</a>");
    expect(source).not.toContain("{row.candidacyId}</a>");
    expect(source).not.toContain("{row.contestHref}</a>");
  });

  it("renders outside-spending chart only when the section is not in an empty state", () => {
    const source = readFileSync(new URL("./DetailPage.svelte", import.meta.url), "utf8");
    const outsideSpendingBranchStart = source.indexOf(
      "{@const outsideSpending = buildPersonOutsideSpendingSection(ieSummary, ieTransactions)}"
    );
    const outsideSpendingCatchStart = source.indexOf("{:catch}", outsideSpendingBranchStart);
    const outsideSpendingBranch = source.slice(outsideSpendingBranchStart, outsideSpendingCatchStart);
    const emptyIfStart = outsideSpendingBranch.indexOf("{#if outsideSpending.emptyMessage}");
    const emptyElseStart = outsideSpendingBranch.indexOf("{:else}", emptyIfStart);
    const emptyIfEnd = outsideSpendingBranch.indexOf("{/if}", emptyElseStart);
    const chartStart = outsideSpendingBranch.indexOf("<Chart", emptyElseStart);

    expect(outsideSpendingBranchStart).toBeGreaterThan(-1);
    expect(outsideSpendingCatchStart).toBeGreaterThan(outsideSpendingBranchStart);
    expect(emptyIfStart).toBeGreaterThan(-1);
    expect(emptyElseStart).toBeGreaterThan(emptyIfStart);
    expect(emptyIfEnd).toBeGreaterThan(emptyElseStart);
    expect(chartStart).toBeGreaterThan(emptyElseStart);
    expect(chartStart).toBeLessThan(emptyIfEnd);
  });

  it("renders populated person civic-history and campaign-finance rows with human-readable labels", () => {
    const data = buildPersonPageBundle({
      personCivicHistory: asSettled(
        buildPersonCivicHistory({
          officeholdings: [
            {
              id: OFFICEHOLDING_ID,
              person_id: PERSON_ID,
              person_name: "Jane Doe",
              office_id: OFFICE_ID,
              electoral_division_id: null,
              holder_status: "elected",
              valid_period_lower: "2025-01-03",
              valid_period_upper: null,
              date_precision: "day",
              sources: []
            }
          ],
          candidacies: [
            {
              id: CANDIDACY_ID,
              person_id: PERSON_ID,
              person_name: "Jane Doe",
              contest_id: CONTEST_ID,
              party: "DEM",
              filing_date: "2026-02-11",
              status: "qualified",
              incumbent_challenge: "I",
              candidate_number: "17",
              sources: []
            }
          ],
          officeholdingLabelsById: { [OFFICEHOLDING_ID]: "Councilmember Ward 1" },
          officeLabelsById: { [OFFICE_ID]: "City Council Ward 1" },
          candidacyLabelsById: { [CANDIDACY_ID]: "2026 Re-election filing" },
          contestLabelsById: { [CONTEST_ID]: "Ward 1 General Election" }
        })
      ),
      personFinanceSections: asSettled([buildPersonFinanceSection()])
    });

    const rendered = render(DetailPage, { props: { data } });

    expect(rendered.body).toContain("Portrait of Jane Doe");
    expect(rendered.body).toContain("Councilmember Ward 1");
    expect(rendered.body).toContain("City Council Ward 1");
    expect(rendered.body).toContain("2026 Re-election filing");
    expect(rendered.body).toContain("Ward 1 General Election");
    expect(rendered.body).toContain("Candidate One");
    expect(rendered.body).toContain("Total raised");
    expect(rendered.body).toContain("$1,000.00");
    expect(rendered.body).toContain("Friends of Candidate One");
    expect(rendered.body).toContain("Acme Donor LLC");
    expect(rendered.body).toContain("2026-01-15");
    expect(rendered.body).toContain("CONTRIBUTION");
    expect(rendered.body).toContain("<h4>Outside Spending</h4>");
    expect(rendered.body).toContain('aria-label="Outside spending"');
    expect(rendered.body).toContain("Finance chart: Candidate One");
  });

  it("encodes person finance candidate hrefs with the shared route builder", () => {
    const data = buildPersonPageBundle({
      personFinanceSections: asSettled([
        buildPersonFinanceSection({
          candidate: {
            id: CANDIDATE_ID,
            fec_candidate_id: "H0NC01001",
            name: "Candidate One",
            slug: "a/b",
            slug_is_unique: true,
            person_id: PERSON_ID,
            party: "DEM",
            office: "H",
            state: "NC",
            district: "01",
            incumbent_challenge: "I",
            principal_committee_id: COMMITTEE_ID,
            sources: []
          }
        })
      ])
    });

    const rendered = render(DetailPage, { props: { data } });

    expect(rendered.body).toContain('href="/candidate/a%2Fb"');
    expect(rendered.body).not.toContain('href="/candidate/a/b"');
  });

  it("renders explicit person empty-state copy and portrait fallback when person data is missing", () => {
    const data = buildPersonPageBundle({
      detail: {
        id: PERSON_ID,
        canonical_name: "Jane Doe",
        name_variants: [],
        first_name: "Jane",
        middle_name: null,
        last_name: "Doe",
        suffix: null,
        occupation: null,
        education: null,
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
        portrait: null,
        sources: []
      },
      personCivicHistory: asSettled(buildPersonCivicHistory()),
      personFinanceSections: asSettled([buildPersonFinanceSection({
        summary: asSettled({
          candidate_id: CANDIDATE_ID,
          candidate_name: "Candidate One",
          total_raised: "0.00",
          total_spent: "0.00",
          net: "0.00",
          transaction_count: 0,
          committees: []
        }),
        donorVendorTransactions: asSettled([]),
        ieSummary: asSettled(null),
        ieTransactions: asSettled([])
      })])
    });

    const rendered = render(DetailPage, { props: { data } });

    expect(rendered.body).toContain('data-testid="entity-portrait-initials"');
    expect(rendered.body).toContain("Initials avatar for Jane Doe");
    expect(rendered.body).toContain("No officeholding history is available yet.");
    expect(rendered.body).toContain("No candidacy history is available yet.");
    expect(rendered.body).toContain("No linked committee summaries are available yet.");
    expect(rendered.body).toContain("No donor/vendor transactions are available yet.");
    expect(rendered.body).toContain("<h4>Outside Spending</h4>");
    expect(rendered.body).toContain('aria-label="Outside spending"');
  });

  it("renders both empty-state banners when linked committees and donor/vendor transactions are absent", () => {
    const data = buildPersonPageBundle({
      personFinanceSections: asSettled([buildPersonFinanceSection({
        summary: asSettled({
          candidate_id: CANDIDATE_ID,
          candidate_name: "Candidate One",
          total_raised: "0.00",
          total_spent: "0.00",
          net: "0.00",
          transaction_count: 0,
          committees: []
        }),
        donorVendorTransactions: asSettled([])
      })])
    });

    const rendered = render(DetailPage, { props: { data } });

    expect(rendered.body).toContain("No linked committee summaries are available yet.");
    expect(rendered.body).toContain("No donor/vendor transactions are available yet.");
  });

  it("renders only the zero-transactions Stage 6 banner when linked committees exist", () => {
    const data = buildPersonPageBundle({
      personFinanceSections: asSettled([buildPersonFinanceSection({
        donorVendorTransactions: asSettled([])
      })])
    });

    const rendered = render(DetailPage, { props: { data } });

    expect(rendered.body).toContain("No donor/vendor transactions are available yet.");
    expect(rendered.body).not.toContain("No linked committee summaries are available yet.");
  });

  it("does not render a Stage 6 empty-state banner when linked committees and transactions exist", () => {
    const data = buildPersonPageBundle({
      personFinanceSections: asSettled([buildPersonFinanceSection()])
    });

    const rendered = render(DetailPage, { props: { data } });

    expect(rendered.body).not.toContain("No linked committee summaries are available yet.");
    expect(rendered.body).not.toContain("No donor/vendor transactions are available yet.");
  });

  it("renders donor/vendor await as a sibling of summary await so the two failures stay isolated", () => {
    // A nested donor/vendor await would couple the two sections: a summary
    // rejection would hide the donor/vendor section entirely and skeletons
    // would render sequentially instead of in parallel.
    const source = readFileSync(new URL("./DetailPage.svelte", import.meta.url), "utf8");
    const personFinanceStart = source.indexOf('{:else if sectionKey === "person-campaign-finance"}');
    expect(personFinanceStart).toBeGreaterThan(-1);

    const personFinanceSlice = source.slice(personFinanceStart);
    const summaryAwaitIndex = personFinanceSlice.indexOf("{#await section.summary}");
    const summaryCatchIndex = personFinanceSlice.indexOf("Candidate fundraising summary is temporarily unavailable.");
    const summaryAwaitEndIndex = personFinanceSlice.indexOf("{/await}", summaryCatchIndex);
    const donorVendorAwaitIndex = personFinanceSlice.indexOf("{#await section.donorVendorTransactions}");

    expect(summaryAwaitIndex).toBeGreaterThan(-1);
    expect(summaryCatchIndex).toBeGreaterThan(summaryAwaitIndex);
    expect(summaryAwaitEndIndex).toBeGreaterThan(summaryCatchIndex);
    expect(donorVendorAwaitIndex).toBeGreaterThan(summaryAwaitEndIndex);
  });
});
