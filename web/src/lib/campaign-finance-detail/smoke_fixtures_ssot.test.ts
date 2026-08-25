import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import {
  buildCongressSmokeSeedSql,
  discoverLiveLouisianaCommitteeRoute,
  getSeededStage6CommitteeRoute,
  SMOKE_PERSON_SMALL_DOLLAR_HEADLINE,
  SMOKE_STAGE6_COMMITTEE_ID,
  SMOKE_FILINGS_PAGED_COMMITTEE_ID,
  SMOKE_FILINGS_HIGH_TOTAL_COMMITTEE_ID,
  SMOKE_FILINGS_PAGE_1_FIRST_ROW_LABEL,
  SMOKE_FILINGS_PAGE_1_LAST_ROW_LABEL,
  SMOKE_FILINGS_PAGE_2_FIRST_ROW_LABEL,
  SMOKE_FILINGS_PAGE_2_LAST_ROW_LABEL,
  SMOKE_FILINGS_PAGE_1_LABEL,
  SMOKE_FILINGS_PAGE_2_LABEL,
  SMOKE_FILINGS_HIGH_TOTAL_LABEL,
  SMOKE_CANDIDATE_ID,
  SMOKE_CONTEST_ID,
  SMOKE_CONTEST_NAME,
  SMOKE_ELECTION_DATE,
  SMOKE_EMPTY_CANDIDATE_ID,
  SMOKE_LOADED_ZERO_CANDIDATE_ID,
  SMOKE_BACKEND_FAILURE_CANDIDATE_ID
} from "../../../tests/smoke/fixtures";
import {
  selectStandardCandidateDetailFixtures,
  smokeFixtures,
  STANDARD_CANDIDATE_DETAIL_FIXTURES
} from "../../../tests/smoke/fixture-data";
import {
  compareFixtureByCandidateSlug,
  compareFixtureById
} from "../../../tests/smoke/compare-fixtures";
import {
  COMMITTEE_FILINGS_PAGE_SIZE,
  COMMITTEE_SUMMARY_SOURCE_LABELS,
  buildCommitteeItemizedCoverageNote,
  buildPaginatedCommitteeFilingBreakdown
} from "./presentation";

const fixturesSource = readFileSync(
  resolve(__dirname, "../../../tests/smoke/fixtures.ts"),
  "utf-8"
);

function assignmentRHS(source: string, constName: string): string {
  const pattern = new RegExp(
    `export\\s+const\\s+${constName}\\s*=\\s*(.+?)\\s*;`
  );
  const match = source.match(pattern);
  if (!match) {
    throw new Error(`Could not find export const ${constName} in fixtures.ts`);
  }
  return match[1].trim();
}

function seededReceiptAmounts(seedSql: string): number[] {
  return [...seedSql.matchAll(/'smoke-congress-receipt-[^']+',\s*'2026-\d{2}-\d{2}',\s*([0-9.]+)/g)].map(
    (match) => Number(match[1])
  );
}

function seededCommitteeSummaryAmounts(seedSql: string): {
  totalReceipts: number;
  unitemizedReceipts: number;
} {
  const blockStart = seedSql.indexOf("INSERT INTO cf.committee_summary");
  const blockEnd = seedSql.indexOf("INSERT INTO civic.zcta_district", blockStart);
  if (blockStart === -1 || blockEnd === -1) {
    throw new Error("Could not find committee_summary seed values");
  }
  const block = seedSql.slice(blockStart, blockEnd);

  const rows = [
    ...block.matchAll(
      /'20\d{2}-\d{2}-\d{2}',\s*([0-9.]+),\s*[0-9.]+,\s*[0-9.]+,\s*([0-9.]+)/g
    )
  ];
  if (rows.length === 0) {
    throw new Error("Could not find committee_summary amount rows");
  }

  return rows.reduce(
    (totals, match) => ({
      totalReceipts: totals.totalReceipts + Number(match[1]),
      unitemizedReceipts: totals.unitemizedReceipts + Number(match[2])
    }),
    { totalReceipts: 0, unitemizedReceipts: 0 }
  );
}

function percentHeadline(numerator: number, denominator: number): string {
  return `${Math.round((numerator / denominator) * 100)}%`;
}

describe("smoke fixtures single-source aliases", () => {
  it("SMOKE_CONTEST_WINNER_NAME is aliased to SMOKE_CANDIDACY_PERSON_NAME, not a string literal", () => {
    expect(assignmentRHS(fixturesSource, "SMOKE_CONTEST_WINNER_NAME")).toBe(
      "SMOKE_CANDIDACY_PERSON_NAME"
    );
  });

  it("SMOKE_OFFICE_RECENT_CONTEST_NAME is aliased to SMOKE_CONTEST_NAME, not a string literal", () => {
    expect(assignmentRHS(fixturesSource, "SMOKE_OFFICE_RECENT_CONTEST_NAME")).toBe(
      "SMOKE_CONTEST_NAME"
    );
  });

  // The seeded-route helper now reads the selected cycle out of the committee
  // summary the discovery step fetched, because the committee page renders the
  // cycle the API selected and that selection moves with
  // SUPPORTED_COMMITTEE_SUMMARY_CYCLES. A minimal stand-in summary is enough for
  // the alias assertions below, which are about the pinned values around it.
  const seededSummaryStub = {
    cycle_summaries: [{ cycle: 2026 }]
  } as unknown as Parameters<typeof getSeededStage6CommitteeRoute>[0];

  it("routes the seeded Stage 6 committee by stable fixture id instead of its collidable slug", () => {
    expect(getSeededStage6CommitteeRoute(seededSummaryStub).committeePath).toBe(
      `/committee/${SMOKE_STAGE6_COMMITTEE_ID}`
    );
  });

  it("refuses a seeded Stage 6 summary that carries no cycle row", () => {
    // A committee whose selected cycle has no summary renders the derived $0.00
    // path, which is exactly the false-$0 the journey exists to catch. Throwing
    // here is what stops the discovery step from handing the spec an expectation
    // built on an absent row.
    const summaryWithoutCycles = {
      cycle_summaries: []
    } as unknown as Parameters<typeof getSeededStage6CommitteeRoute>[0];

    expect(() => getSeededStage6CommitteeRoute(summaryWithoutCycles)).toThrow(
      /no cycle_summaries row/
    );
  });

  it("smoke fixtures use COMMITTEE_SUMMARY_SOURCE_LABELS from presentation.ts, not duplicate literals", () => {
    expect(fixturesSource).not.toContain('"Official FEC committee summary"');
    expect(fixturesSource).not.toContain('"Derived from itemized transactions"');
    expect(fixturesSource).toContain("COMMITTEE_SUMMARY_SOURCE_LABELS");
  });

  it("smoke fixtures use buildCommitteeItemizedCoverageNote from presentation.ts, not a duplicate builder", () => {
    expect(fixturesSource).not.toMatch(
      /function\s+buildSmokeItemizedCoverageNote/
    );
    expect(fixturesSource).toContain("buildCommitteeItemizedCoverageNote");
  });

  it("seeded smoke constants derive from the canonical presenter", () => {
    const seeded = getSeededStage6CommitteeRoute(seededSummaryStub);
    expect(seeded.expectedSummarySourceLabel).toBe(
      COMMITTEE_SUMMARY_SOURCE_LABELS.fec_committee_summary
    );
    expect(seeded.expectedItemizedCoverageNote).toBe(
      buildCommitteeItemizedCoverageNote({
        itemized_transaction_count: 0,
        summary_source: "fec_committee_summary"
      })
    );
  });

  it("fixture-mode person contribution insights match backend codes and share math", () => {
    const insights = smokeFixtures.person.contributionInsights;

    expect(insights.metadata.excluded_geography).toBeNull();
    expect(insights.metadata.caveats).toEqual([]);

    const smallDollarAmount = Number(insights.small_dollar_share.small_dollar_amount);
    const totalContributionAmount = Number(insights.small_dollar_share.total_contribution_amount);
    const share = Number(insights.small_dollar_share.share);

    expect(Number.isFinite(smallDollarAmount)).toBe(true);
    expect(Number.isFinite(totalContributionAmount)).toBe(true);
    expect(Number.isFinite(share)).toBe(true);
    expect(totalContributionAmount).toBeGreaterThan(0);
    expect(share).toBeCloseTo(smallDollarAmount / totalContributionAmount, 4);
  });

  it("fixture-mode person top employers expose server-owned industry metadata", () => {
    expect(smokeFixtures.person.topEmployers).toEqual([
      {
        employer: "GOOGLE",
        total_amount: "600.00",
        transaction_count: 3,
        industry: "Technology",
        industry_rollup_eligible: true
      },
      {
        employer: "ACME CORP",
        total_amount: "150.00",
        transaction_count: 1,
        industry: "UNKNOWN_INDUSTRY",
        industry_rollup_eligible: true
      },
      {
        employer: "Unclassified / not provided",
        total_amount: "25.00",
        transaction_count: 1,
        industry: "UNKNOWN_INDUSTRY",
        industry_rollup_eligible: false
      }
    ]);
  });

  it("live-mode seeded person small-dollar headline matches the exported smoke expectation", () => {
    const seedSql = buildCongressSmokeSeedSql();
    const { totalReceipts, unitemizedReceipts } = seededCommitteeSummaryAmounts(seedSql);
    const smallItemizedReceipts = seededReceiptAmounts(seedSql)
      .filter((amount) => amount <= 200)
      .reduce((total, amount) => total + amount, 0);

    expect(percentHeadline(unitemizedReceipts + smallItemizedReceipts, totalReceipts)).toBe(
      SMOKE_PERSON_SMALL_DOLLAR_HEADLINE
    );
  });

  it("derives fallback live committee assertions from discovered API records", async () => {
    const discoveredCommitteeId = "60000000-0000-4000-8000-000000000001";
    const apiResponses = new Map<string, { ok: boolean; status: number; body: unknown }>([
      ["/v1/committees/by-slug/mike-johnson-for-louisiana", { ok: false, status: 404, body: {} }],
      [
        "/v1/search?q=MIKE%20JOHNSON%20FOR%20LOUISIANA&entity_type=committee",
        {
          ok: true,
          status: 200,
          body: {
            items: [
              {
                entity_type: "committee",
                entity_id: discoveredCommitteeId,
                name: "MIKE JOHNSON FOR LOUISIANA"
              }
            ],
            has_next: false
          }
        }
      ],
      [
        `/v1/committees/${discoveredCommitteeId}`,
        {
          ok: true,
          status: 200,
          body: {
            linked_candidates: [
              {
                name: "LIVE MIKE JOHNSON"
              }
            ]
          }
        }
      ],
      [
        `/v1/committees/${discoveredCommitteeId}/summary`,
        {
          ok: true,
          status: 200,
          body: {
            total_raised: "2345678.90",
            itemized_transaction_count: 17,
            summary_source: "fec_committee_summary",
            cycle_summaries: [{ cycle: 2026 }]
          }
        }
      ],
      [
        `/v1/committees/${discoveredCommitteeId}/independent-expenditures-made`,
        {
          ok: true,
          status: 200,
          body: {
            ie_transaction_count: 1,
            targets: [{ candidate_name: "LIVE IE TARGET" }]
          }
        }
      ]
    ]);
    const page = {
      request: {
        get: async (url: string) => {
          const parsed = new URL(url);
          const response = apiResponses.get(`${parsed.pathname}${parsed.search}`);
          if (response === undefined) {
            throw new Error(`Unexpected API request: ${url}`);
          }
          return {
            ok: () => response.ok,
            status: () => response.status,
            json: async () => response.body
          };
        }
      }
    };

    const discovery = await discoverLiveLouisianaCommitteeRoute(page);

    expect(discovery).toEqual({
      committeePath: `/committee/${discoveredCommitteeId}`,
      expectedSummarySourceLabel: "Official FEC committee summary",
      expectedItemizedCoverageNote:
        "Itemized transactions loaded: 17. Official totals above come directly from the FEC committee summary and are not derived from these transactions.",
      expectedLinkedCandidateName: "LIVE MIKE JOHNSON",
      expectedCycleLabel: "2026",
      expectedTotalRaisedText: "$2,345,678.90",
      expectedOutsideSpendingEmptyText: null,
      expectedOutsideSpendingTargetName: "LIVE IE TARGET"
    });
  });
});

function renderedFilingRowLabel(row: { filingName: string; filingFecId: string }): string {
  // Mirrors the DetailPage.svelte filing cell: `{row.filingName} ({row.filingFecId})`.
  return `${row.filingName} (${row.filingFecId})`;
}

describe("candidate money smoke fixture readiness", () => {
  it("serves contract-complete candidate details for every compare fixture", () => {
    for (const fixture of compareFixtureById.values()) {
      const hasOfficialTotal = fixture.candidateSummary !== null;

      expect(fixture.candidate).toMatchObject({
        identity_is_safe: true,
        has_official_total: hasOfficialTotal,
        candidacies: []
      });
      expect(fixture.candidateList.items).toEqual([
        expect.objectContaining({
          identity_is_safe: true,
          has_official_total: hasOfficialTotal
        })
      ]);
    }
  });

  it.each(STANDARD_CANDIDATE_DETAIL_FIXTURES)(
    "keeps candidate office and FEC id prefix coherent for standard fixture %#",
    (fixture) => {
      expect(fixture.detail.fec_candidate_id[0]).toBe(fixture.detail.office);
    }
  );

  it("gives every registered compare candidate slug a one-to-one detail identity", () => {
    // The backend answers /v1/candidates/by-slug/<slug> with the compare
    // fixture's candidate LIST item, and the candidate page then re-fetches the
    // detail by that item's id. getCompareCandidateResponse short-circuits on
    // isStandardCandidateFixtureId, so a compare fixture that reuses a standard
    // candidate id serves a different person's detail under its own slug.
    const standardCandidateIds = new Set(
      STANDARD_CANDIDATE_DETAIL_FIXTURES.map((standardFixture) => standardFixture.id)
    );

    expect(compareFixtureByCandidateSlug.size).toBeGreaterThan(0);
    for (const [slug, fixture] of compareFixtureByCandidateSlug) {
      expect(standardCandidateIds.has(fixture.candidate.id)).toBe(false);
      expect(fixture.candidate.slug).toBe(slug);
      expect(fixture.candidateList.items).toEqual([
        expect.objectContaining({
          id: fixture.candidate.id,
          name: fixture.candidate.name,
          slug
        })
      ]);
    }
  });

  it("keeps the populated House candidate, contest, and office semantically coherent", () => {
    const candidate = smokeFixtures.candidate.detail;
    const candidacy = candidate.candidacies[0];
    const contestMoneyRow = smokeFixtures.contest.candidateMoney.rows.find(
      (row) => row.candidate_id === candidate.id
    );

    expect(candidate).toMatchObject({ office: "H", state: "NC", district: "01" });
    expect(candidacy).toEqual({
      contest_id: smokeFixtures.contest.id,
      contest_name: "North Carolina House District 1 General",
      election_date: SMOKE_ELECTION_DATE
    });
    expect(smokeFixtures.contest.detail).toMatchObject({
      name: candidacy.contest_name,
      office_id: smokeFixtures.office.id
    });
    expect(smokeFixtures.office.detail).toMatchObject({
      name: "U.S. Representative for North Carolina's 1st congressional district",
      title: "Representative",
      state: "NC"
    });
    expect(contestMoneyRow?.fec_candidate_id).toBe(candidate.fec_candidate_id);
  });

  it("classifies the House NC-01 contest as federal across every response surface", () => {
    const canonicalOfficeLevel = smokeFixtures.office.detail.office_level;
    expect(canonicalOfficeLevel).toBe("federal");

    const electionIndexRows = [
      smokeFixtures.upcomingElectionTimeline[0].contests[0],
      smokeFixtures.electionDateAggregate.contests[0]
    ];
    for (const row of electionIndexRows) {
      expect(row.office_id).toBe(smokeFixtures.office.id);
      expect(row.office_level).toBe(canonicalOfficeLevel);
      // House district seat context: NC-01 congressional district, not a bare state row.
      expect(row.electoral_division_type).toBe("congressional_district");
      expect(row.electoral_division_state).toBe("NC");
      expect(row.district_number).toBe("01");
    }

    const personCandidacy = smokeFixtures.personNoPortrait.detail.candidacies[0];
    expect(personCandidacy.office_id).toBe(smokeFixtures.office.id);
    expect(personCandidacy.office_level).toBe(canonicalOfficeLevel);
  });

  it("selects the NC-01 congressional district on every House office division surface", () => {
    const office = smokeFixtures.office.detail;
    // The geometry the fixture backend actually serves for
    // /v1/civics/geometry?level=congressional_district&state=NC. The office
    // page highlights by selected_electoral_division_id, so the office's
    // division metadata has to name a feature in this collection or the map
    // silently renders no district context.
    const districtFeatures =
      smokeFixtures.ncCountyDrilldown.geometryByLevel.congressional_district.features;
    const districtFeature = districtFeatures.find(
      (feature) => feature.properties.district_number === smokeFixtures.candidate.detail.district
    );
    expect(districtFeature).toBeDefined();
    expect(districtFeature?.properties.state).toBe(office.state);

    const expectedDivision = {
      electoral_division_id: districtFeature?.properties.id,
      electoral_division_type: districtFeature?.properties.division_type,
      electoral_division_state: office.state
    };

    expect(office.current_holder_card).toMatchObject(expectedDivision);
    expect(office.officeholding_timeline[0]).toMatchObject(expectedDivision);
    expect(office.recent_contests[0]).toMatchObject(expectedDivision);
    expect(smokeFixtures.contest.detail).toMatchObject(expectedDivision);
    expect({
      electoral_division_id: office.selected_electoral_division_id,
      electoral_division_type: office.selected_electoral_division_type,
      electoral_division_state: office.selected_electoral_division_state
    }).toEqual(expectedDivision);
  });

  it("derives the standard registry when a candidate detail fixture is added", () => {
    const additionalCandidateFixture = {
      id: "55555555-5555-4555-8555-555555555556",
      detail: {
        fec_candidate_id: "H6NC01002",
        office: "H"
      }
    } as const;

    const selectedFixtures = selectStandardCandidateDetailFixtures({
      ...smokeFixtures,
      additionalCandidateFixture
    });

    expect(selectedFixtures).toEqual([
      ...STANDARD_CANDIDATE_DETAIL_FIXTURES,
      additionalCandidateFixture
    ]);
  });

  it("excludes detail-bearing fixtures that are not candidate details", () => {
    // The registry is derived by shape, and every selected fixture is served at
    // /v1/candidates/{id}. A discriminator loose enough to admit an office,
    // contest, or committee fixture would silently reroute those ids.
    const nonCandidateDetailFixture = {
      id: "66666666-6666-4666-8666-666666666666",
      detail: { office_level: "federal", title: "Representative" }
    } as const;

    const selectedFixtures = selectStandardCandidateDetailFixtures({
      ...smokeFixtures,
      nonCandidateDetailFixture
    });

    expect(selectedFixtures).toEqual([...STANDARD_CANDIDATE_DETAIL_FIXTURES]);
    for (const excluded of [smokeFixtures.office, smokeFixtures.contest, smokeFixtures.committee]) {
      expect(STANDARD_CANDIDATE_DETAIL_FIXTURES).not.toContain(excluded);
    }
  });

  it.each(STANDARD_CANDIDATE_DETAIL_FIXTURES)(
    "provides contract-complete candidacies for standard candidate fixture %#",
    (fixture) => {
      expect(Object.hasOwn(fixture.detail, "candidacies")).toBe(true);
      expect(Array.isArray(fixture.detail.candidacies)).toBe(true);

      const expectedCandidacies =
        fixture === smokeFixtures.candidate
          ? [
              {
                contest_id: SMOKE_CONTEST_ID,
                contest_name: SMOKE_CONTEST_NAME,
                election_date: SMOKE_ELECTION_DATE
              }
            ]
          : [];
      expect(fixture.detail.candidacies).toEqual(expectedCandidacies);
    }
  );

  const candidateFixtures = [
    {
      label: "populated",
      fixture: smokeFixtures.candidate,
      fundraisingCoverage: {
        activity_state: "populated",
        completeness: "complete",
        basis: "fec_official_candidate_summary"
      },
      ieCoverage: {
        activity_state: "populated",
        completeness: "complete",
        basis: "fec_schedule_e_transactions"
      },
      fundraisingMetadata: ["2026-01-01", "2026-12-31", [2026]],
      ieMetadata: ["2026-01-01", "2026-12-31", [2026]]
    },
    {
      label: "not loaded",
      fixture: smokeFixtures.candidateEmpty,
      fundraisingCoverage: {
        activity_state: "not_loaded",
        completeness: "unknown",
        basis: "no_authoritative_load_evidence"
      },
      ieCoverage: {
        activity_state: "not_loaded",
        completeness: "unknown",
        basis: "no_authoritative_load_evidence"
      },
      fundraisingMetadata: [null, null, []],
      ieMetadata: [null, null, []]
    },
    {
      label: "loaded zero",
      fixture: smokeFixtures.candidateLoadedZero,
      fundraisingCoverage: {
        activity_state: "loaded_zero",
        completeness: "complete",
        basis: "authoritative_load_evidence"
      },
      ieCoverage: {
        activity_state: "loaded_zero",
        completeness: "complete",
        basis: "authoritative_load_evidence"
      },
      fundraisingMetadata: ["2026-01-01", "2026-12-31", [2026]],
      ieMetadata: ["2026-01-01", "2026-12-31", [2026]]
    },
    {
      label: "deviant",
      fixture: smokeFixtures.candidateDeviant,
      fundraisingCoverage: {
        activity_state: "populated",
        completeness: "complete",
        basis: "qualifying_transactions"
      },
      ieCoverage: {
        activity_state: "not_loaded",
        completeness: "unknown",
        basis: "no_authoritative_load_evidence"
      },
      fundraisingMetadata: ["2026-01-01", "2026-12-31", [2026]],
      ieMetadata: [null, null, []]
    },
    {
      label: "Alabama",
      fixture: smokeFixtures.candidateAl,
      fundraisingCoverage: {
        activity_state: "populated",
        completeness: "complete",
        basis: "qualifying_transactions"
      },
      ieCoverage: {
        activity_state: "not_loaded",
        completeness: "unknown",
        basis: "no_authoritative_load_evidence"
      },
      fundraisingMetadata: ["2026-01-01", "2026-12-31", [2026]],
      ieMetadata: [null, null, []]
    },
    {
      label: "Georgia",
      fixture: smokeFixtures.candidateGa,
      fundraisingCoverage: {
        activity_state: "populated",
        completeness: "complete",
        basis: "qualifying_transactions"
      },
      ieCoverage: {
        activity_state: "not_loaded",
        completeness: "unknown",
        basis: "no_authoritative_load_evidence"
      },
      fundraisingMetadata: ["2026-01-01", "2026-12-31", [2026]],
      ieMetadata: [null, null, []]
    }
  ];

  it.each(candidateFixtures)(
    "$label candidate has contract-complete coverage and selected-cycle metadata",
    ({ fixture, fundraisingCoverage, ieCoverage, fundraisingMetadata, ieMetadata }) => {
      expect(fixture.summary.candidate_id).toBe(fixture.id);
      expect(fixture.summary.selected_cycle).toBe(2026);
      expect([
        fixture.summary.coverage_start_date,
        fixture.summary.coverage_end_date,
        fixture.summary.available_cycles
      ]).toEqual(fundraisingMetadata);
      expect(fixture.summary.coverage).toEqual(fundraisingCoverage);
      expect(Object.hasOwn(fixture.summary, "cash_on_hand")).toBe(true);
      expect(fixture.summary).toEqual(
        expect.objectContaining({
          summary_source: expect.stringMatching(/^(fec_weball|derived)$/),
          itemized_transaction_count: expect.any(Number),
          receipt_source_composition: expect.any(Array),
          selected_cycle_coverage_complete: expect.any(Boolean),
          can_render_share: expect.any(Boolean),
          receipt_source_caveats: expect.any(Array)
        })
      );
      for (const committee of fixture.summary.committees) {
        expect(committee).toEqual(
          expect.objectContaining({
            selected_cycle: 2026,
            coverage_start_date: "2026-01-01",
            coverage_end_date: "2026-12-31",
            available_cycles: [2026],
            cycle_summaries: expect.any(Array),
            receipt_source_composition: expect.any(Array),
            receipt_source_caveats: expect.any(Array)
          })
        );
      }

      expect(fixture.ieSummary.candidate_id).toBe(fixture.id);
      expect(fixture.ieSummary.selected_cycle).toBe(2026);
      expect([
        fixture.ieSummary.coverage_start_date,
        fixture.ieSummary.coverage_end_date,
        fixture.ieSummary.available_cycles
      ]).toEqual(ieMetadata);
      expect(fixture.ieSummary.coverage).toEqual(ieCoverage);
      expect(fixture.ieTransactions).toEqual(expect.any(Array));
    }
  );

  it("pins deterministic populated, not-loaded, and loaded-zero values used by the browser proof", () => {
    expect(smokeFixtures.candidate.id).toBe(SMOKE_CANDIDATE_ID);
    expect(smokeFixtures.candidate.summary).toMatchObject({
      total_raised: "250.00",
      total_spent: "80.00",
      cash_on_hand: "125.00"
    });
    expect(smokeFixtures.candidate.ieSummary).toMatchObject({
      support_total: "15000.00",
      oppose_total: "8500.00",
      support_count: 12,
      oppose_count: 5
    });

    expect(smokeFixtures.candidateEmpty.id).toBe(SMOKE_EMPTY_CANDIDATE_ID);
    expect(smokeFixtures.candidateEmpty.summary).toMatchObject({
      total_raised: "0.00",
      total_spent: "0.00",
      itemized_transaction_count: 0
    });

    expect(smokeFixtures.candidateLoadedZero.id).toBe(SMOKE_LOADED_ZERO_CANDIDATE_ID);
    expect(smokeFixtures.candidateLoadedZero.summary).toMatchObject({
      total_raised: "0.00",
      total_spent: "0.00",
      itemized_transaction_count: 0
    });
    expect(smokeFixtures.candidateLoadedZero.ieSummary).toMatchObject({
      support_total: "0.00",
      oppose_total: "0.00",
      support_count: 0,
      oppose_count: 0
    });
  });

  it("pins all three candidate money failures to the maintained backend response fixture", () => {
    expect(smokeFixtures.candidateBackendFailure.id).toBe(SMOKE_BACKEND_FAILURE_CANDIDATE_ID);
    expect(smokeFixtures.candidateBackendFailure.behavior).toEqual({
      summaryStatus: 503,
      ieSummaryStatus: 503,
      ieTransactionsStatus: 503
    });
  });
});

describe("filing pagination smoke fixtures", () => {
  it("paged committee fixture is a 30-row window carrying backend pagination metadata", () => {
    const fixture = smokeFixtures.committeeFilingsPaged;
    expect(fixture.id).toBe(SMOKE_FILINGS_PAGED_COMMITTEE_ID);
    expect(fixture.filingBreakdown.filings).toHaveLength(30);
    expect(fixture.filingBreakdown.total_filings).toBe(30);
    expect(fixture.filingBreakdown.store_limit).toBe(200);
    expect(fixture.filingBreakdown.has_next).toBe(false);
    expect(fixture.filingBreakdown.offset).toBe(0);
    expect(fixture.filingBreakdown.limit).toBe(200);
  });

  it("high-total committee fixture fetches the full 200-row window over a larger all-time count", () => {
    const fixture = smokeFixtures.committeeFilingsHighTotal;
    expect(fixture.id).toBe(SMOKE_FILINGS_HIGH_TOTAL_COMMITTEE_ID);
    expect(fixture.filingBreakdown.filings).toHaveLength(200);
    expect(fixture.filingBreakdown.total_filings).toBe(220706);
    expect(fixture.filingBreakdown.store_limit).toBe(200);
  });

  it("exported page-1/page-2 labels and row identities match the real presenter", () => {
    const { filingBreakdown } = smokeFixtures.committeeFilingsPaged;
    const pageOne = buildPaginatedCommitteeFilingBreakdown(filingBreakdown, "0");
    const pageTwo = buildPaginatedCommitteeFilingBreakdown(
      filingBreakdown,
      String(COMMITTEE_FILINGS_PAGE_SIZE)
    );

    expect(pageOne.label).toBe(SMOKE_FILINGS_PAGE_1_LABEL);
    expect(pageTwo.label).toBe(SMOKE_FILINGS_PAGE_2_LABEL);

    expect(pageOne.rows).toHaveLength(25);
    expect(pageTwo.rows).toHaveLength(5);

    expect(renderedFilingRowLabel(pageOne.rows[0])).toBe(SMOKE_FILINGS_PAGE_1_FIRST_ROW_LABEL);
    expect(renderedFilingRowLabel(pageOne.rows[24])).toBe(SMOKE_FILINGS_PAGE_1_LAST_ROW_LABEL);
    expect(renderedFilingRowLabel(pageTwo.rows[0])).toBe(SMOKE_FILINGS_PAGE_2_FIRST_ROW_LABEL);
    expect(renderedFilingRowLabel(pageTwo.rows[4])).toBe(SMOKE_FILINGS_PAGE_2_LAST_ROW_LABEL);
  });

  it("exported high-total label matches the real presenter for the 200-row window", () => {
    const { filingBreakdown } = smokeFixtures.committeeFilingsHighTotal;
    const pageOne = buildPaginatedCommitteeFilingBreakdown(filingBreakdown, "0");
    expect(pageOne.label).toBe(SMOKE_FILINGS_HIGH_TOTAL_LABEL);
  });

  it("filing pagination fixtures use a summary_source known to COMMITTEE_SUMMARY_SOURCE_LABELS", () => {
    expect(COMMITTEE_SUMMARY_SOURCE_LABELS).toHaveProperty(
      smokeFixtures.committeeFilingsPaged.summary.summary_source
    );
    expect(COMMITTEE_SUMMARY_SOURCE_LABELS).toHaveProperty(
      smokeFixtures.committeeFilingsHighTotal.summary.summary_source
    );
  });
});
