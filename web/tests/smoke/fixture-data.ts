const fixtureConstants =
  (await import(new URL("./fixtures.ts", import.meta.url).href)) as typeof import("./fixtures");

const {
  SMOKE_CANDIDACY_ID,
  SMOKE_CANDIDACY_PERSON_NAME,
  SMOKE_CANDIDATE_ID,
  SMOKE_AL_CANDIDATE_ID,
  SMOKE_CANDIDATE_CASH_ON_HAND,
  SMOKE_CANDIDATE_COVERAGE_THROUGH,
  SMOKE_CANDIDATE_NAME,
  SMOKE_CANDIDATE_SELECTED_CYCLE,
  SMOKE_CANDIDATE_SLUG,
  SMOKE_COVERAGE_DOMAIN,
  SMOKE_COVERAGE_JURISDICTION,
  SMOKE_DATA_SOURCE_NAME,
  SMOKE_ELECTION_DATE,
  SMOKE_COLLIDING_CANDIDATE_ID,
  SMOKE_COLLIDING_CANDIDATE_SLUG,
  SMOKE_COLLIDING_COMMITTEE_ID,
  SMOKE_COLLIDING_COMMITTEE_SLUG,
  SMOKE_COMMITTEE_ID,
  SMOKE_COMMITTEE_IE_SOURCE_NAME,
  SMOKE_COMMITTEE_IE_SOURCE_RECORD_KEY,
  SMOKE_COMMITTEE_IE_SOURCE_URL,
  SMOKE_COMMITTEE_NAME,
  SMOKE_COMMITTEE_SLUG,
  SMOKE_CONGRESS_LEADER_NAME,
  SMOKE_CONGRESS_LEADER_PERSON_ID,
  SMOKE_CONGRESS_LEADER_SOURCE_HREF,
  SMOKE_CONGRESS_NO_MONEY_NAME,
  SMOKE_CONGRESS_NO_MONEY_PERSON_ID,
  SMOKE_CONGRESS_PORTRAIT_URL,
  SMOKE_CONGRESS_SECOND_NAME,
  SMOKE_CONGRESS_SECOND_PERSON_ID,
  SMOKE_CONGRESS_SECOND_SOURCE_HREF,
  SMOKE_CONTEST_ID,
  SMOKE_CONTEST_NAME,
  SMOKE_DEVIANT_CANDIDATE_ID,
  SMOKE_EMPTY_CANDIDATE_ID,
  SMOKE_EMPTY_COMMITTEE_ID,
  SMOKE_EMPTY_OFFICE_ID,
  SMOKE_EMPTY_OFFICE_NAME,
  SMOKE_EMPTY_PROPERTY_ID,
  SMOKE_EMPTY_PROPERTY_TITLE,
  SMOKE_FILING_ID,
  SMOKE_IE_COMMITTEE_A_ID,
  SMOKE_IE_COMMITTEE_A_NAME,
  SMOKE_IE_TRANSACTION_DISSEMINATION_DATE,
  SMOKE_GA_CANDIDATE_ID,
  SMOKE_NC_SHOWCASE_COUNTY_DIVISION_NAME,
  SMOKE_NC_SHOWCASE_COUNTY_SLUG,
  SMOKE_NC_SHOWCASE_DISTRICT_DIVISION_NAME,
  SMOKE_NC_SHOWCASE_RECIPIENT_NAME,
  SMOKE_NC_SHOWCASE_STATE_CODE,
  SMOKE_OFFICEHOLDING_ID,
  SMOKE_OFFICEHOLDING_PERSON_NAME,
  SMOKE_OFFICE_ID,
  SMOKE_OFFICE_NAME,
  SMOKE_OFFICE_OFFICEHOLDER_ID,
  SMOKE_OFFICE_OFFICEHOLDER_NAME,
  SMOKE_ORG_CANONICAL_NAME,
  SMOKE_ORG_ID,
  SMOKE_PHL_COMMITTEE_ID,
  SMOKE_PHL_COMMITTEE_NAME,
  SMOKE_PERSON_CANONICAL_NAME,
  SMOKE_PERSON_CASH_ON_HAND_DOLLARS,
  SMOKE_PERSON_ID,
  SMOKE_PERSON_ITEMIZED_DOLLARS,
  SMOKE_PERSON_LARGE_ITEMIZED_DOLLARS,
  SMOKE_PERSON_MISSING_PORTRAIT_CANONICAL_NAME,
  SMOKE_PERSON_MISSING_PORTRAIT_FIELD_ID,
  SMOKE_PERSON_NO_PORTRAIT_CANONICAL_NAME,
  SMOKE_PERSON_NO_PORTRAIT_ID,
  SMOKE_PERSON_PRIOR_UNITEMIZED_DOLLARS,
  SMOKE_PERSON_SELECTED_CYCLE,
  SMOKE_PERSON_SMALL_DOLLAR_DOLLARS,
  SMOKE_PERSON_SMALL_DOLLAR_SHARE,
  SMOKE_PERSON_SMALL_ITEMIZED_DOLLARS,
  SMOKE_PERSON_TOP_DONOR_ONE_NAME,
  SMOKE_PERSON_TOP_DONOR_TWO_NAME,
  SMOKE_PERSON_TOP_EMPLOYER_ONE_NAME,
  SMOKE_PERSON_TOP_EMPLOYER_TWO_NAME,
  SMOKE_PERSON_TOTAL_CONTRIBUTION_DOLLARS,
  SMOKE_PERSON_UNITEMIZED_DOLLARS,
  SMOKE_ROSTER_DURHAM_PERSON_CANONICAL_NAME,
  SMOKE_ROSTER_DURHAM_PERSON_ID,
  SMOKE_ROSTER_DURHAM_PORTRAIT_URL,
  SMOKE_ROSTER_NC_HOUSE_PERSON_CANONICAL_NAME,
  SMOKE_ROSTER_NC_HOUSE_PERSON_ID,
  SMOKE_ROSTER_NC_HOUSE_PORTRAIT_URL,
  SMOKE_PROPERTY_ID,
  SMOKE_PROPERTY_TITLE,
  SMOKE_STATE_DETAIL_IE_CAVEAT,
  SMOKE_STATE_DETAIL_TOP_CANDIDATE_NAME,
  SMOKE_STATE_DETAIL_TOP_CANDIDATE_TOTAL,
  SMOKE_STATE_DETAIL_TOP_COMMITTEE_NAME,
  SMOKE_STATE_DETAIL_TOP_COMMITTEE_TOTAL,
  SMOKE_STATE_DETAIL_TOP_IE_SPENDER_NAME,
  SMOKE_STATE_DETAIL_TOP_IE_SPENDER_TOTAL,
  SMOKE_SEARCH_CANDIDATE_QUERY,
  SMOKE_SEARCH_CANDIDATE_RESULT_NAME,
  SMOKE_SEARCH_CONTEST_QUERY,
  SMOKE_SEARCH_QUERY,
  SMOKE_SEARCH_RESULT_NAME,
  SMOKE_SEARCH_SLOW_QUERY,
  SMOKE_SEARCH_VALIDATION_QUERY,
  SMOKE_FILINGS_PAGED_COMMITTEE_ID,
  SMOKE_FILINGS_HIGH_TOTAL_COMMITTEE_ID,
  SMOKE_FILINGS_PAGED_COMMITTEE_NAME,
  SMOKE_FILINGS_HIGH_TOTAL_COMMITTEE_NAME
} = fixtureConstants;

// A day in milliseconds, used to walk deterministic filing coverage windows backward
// from a fixed base date so the newest filing is always rank 1.
const FILING_FIXTURE_DAY_MS = 24 * 60 * 60 * 1000;
// Fixed base date (2026-12-31). `new Date(<explicit ms>)` is deterministic — no wall clock.
const FILING_FIXTURE_BASE_MS = Date.UTC(2026, 11, 31);

function toIsoDateOnly(epochMs: number): string {
  return new Date(epochMs).toISOString().slice(0, 10);
}

/**
 * Builds `count` deterministic newest-first-verifiable filings for a committee fixture.
 *
 * Rank 1 is the newest filing (latest coverage end date) and is named "Filing 01" (zero
 * padded to the width of `count`, so 30 rows read "Filing 01".."Filing 30" and 200 rows
 * read "Filing 001".."Filing 200"). Distinct coverage end dates give the presenter an
 * unambiguous newest-first sort, so page-1 and page-2 row identities are exactly known.
 */
function buildDeterministicFilings(committeeId: string, count: number) {
  const rankWidth = String(count).length;
  return Array.from({ length: count }, (_unused, index) => {
    const rank = index + 1;
    const coverageEndMs = FILING_FIXTURE_BASE_MS - (rank - 1) * 7 * FILING_FIXTURE_DAY_MS;
    const paddedRank = String(rank).padStart(rankWidth, "0");
    return {
      filing_id: `${committeeId}:filing-${paddedRank}`,
      filing_fec_id: "F3N",
      filing_name: `Filing ${paddedRank}`,
      report_type: "Q",
      amendment_indicator: "N",
      coverage_start_date: toIsoDateOnly(coverageEndMs - 89 * FILING_FIXTURE_DAY_MS),
      coverage_end_date: toIsoDateOnly(coverageEndMs),
      receipt_date: toIsoDateOnly(coverageEndMs + 15 * FILING_FIXTURE_DAY_MS),
      total_raised: (1000 + rank).toFixed(2),
      total_spent: (500 + rank).toFixed(2),
      net: (500).toFixed(2),
      transaction_count: (rank % 5) + 1,
      cash_on_hand: (10000 - rank * 10).toFixed(2),
      row_id: `${committeeId}:filing-${paddedRank}:N`
    };
  });
}

/**
 * Builds a self-contained committee detail fixture whose only interesting surface is a
 * client-paginated filing table. Detail/summary/transactions/IE carry just enough valid
 * data for the detail page to render every panel without a backend-failure state, while
 * `filingBreakdown` carries the paginated window plus the backend pagination metadata the
 * client presenter intentionally ignores. `slug_is_unique` is false so navigating by id
 * stays on the id URL (no canonical-slug redirect), matching the PHL fixture's contract.
 */
function buildFilingPaginationCommitteeFixture(params: {
  id: string;
  name: string;
  slug: string;
  filings: ReturnType<typeof buildDeterministicFilings>;
  totalFilings: number;
  storeLimit: number;
  hasNext: boolean;
}) {
  const { id, name, slug, filings, totalFilings, storeLimit, hasNext } = params;
  return {
    id,
    detail: {
      id,
      fec_committee_id: "C90000000",
      name,
      slug,
      slug_is_unique: false,
      organization_id: null,
      committee_type: "Q",
      committee_designation: "P",
      party: "DEM",
      state: "NC",
      city: "Raleigh",
      zip_code: "27601",
      treasurer_name: "Jordan Treasurer",
      linked_candidates: [],
      sources: [
        {
          domain: "campaign_finance",
          jurisdiction: "federal/fec",
          data_source_name: "FEC Filings",
          data_source_url: "https://www.fec.gov",
          source_record_key: `${id}-source`,
          record_url: "https://www.fec.gov",
          pull_date: "2026-03-19T00:00:00Z"
        }
      ]
    },
    transactions: [],
    summary: {
      committee_id: id,
      committee_name: name,
      selected_cycle: 2026,
      coverage_start_date: "2026-01-01",
      coverage_end_date: "2026-12-31",
      available_cycles: [2026],
      total_raised: "1000.00",
      total_spent: "500.00",
      net: "500.00",
      transaction_count: 0,
      jurisdiction: "federal/fec",
      data_through: "2026-12-31T00:00:00Z",
      cash_receipts_total: "1000.00",
      in_kind_receipts_total: "0.00",
      loan_receipts_total: "0.00",
      contribution_receipts_total: "1000.00",
      top_donors: [],
      top_vendors: [],
      spend_categories: null,
      itemized_transaction_count: 0,
      cycle_summaries: [],
      summary_source: "derived" as const
    },
    filingBreakdown: {
      committee_id: id,
      committee_name: name,
      total_filings: totalFilings,
      store_limit: storeLimit,
      has_next: hasNext,
      offset: 0,
      limit: storeLimit,
      filings
    },
    independentExpendituresMade: {
      committee_id: id,
      support_total: "0.00",
      oppose_total: "0.00",
      ie_transaction_count: 0,
      excluded_outlier_count: 0,
      targets: []
    }
  };
}

const committeeFilingsPagedFixture = buildFilingPaginationCommitteeFixture({
  id: SMOKE_FILINGS_PAGED_COMMITTEE_ID,
  name: SMOKE_FILINGS_PAGED_COMMITTEE_NAME,
  slug: "filing-pagination-committee",
  filings: buildDeterministicFilings(SMOKE_FILINGS_PAGED_COMMITTEE_ID, 30),
  totalFilings: 30,
  storeLimit: 200,
  hasNext: false
});

const committeeFilingsHighTotalFixture = buildFilingPaginationCommitteeFixture({
  id: SMOKE_FILINGS_HIGH_TOTAL_COMMITTEE_ID,
  name: SMOKE_FILINGS_HIGH_TOTAL_COMMITTEE_NAME,
  slug: "filing-high-total-committee",
  filings: buildDeterministicFilings(SMOKE_FILINGS_HIGH_TOTAL_COMMITTEE_ID, 200),
  totalFilings: 220706,
  storeLimit: 200,
  hasNext: true
});

export const smokeFixtures = {
  search: {
    query: SMOKE_SEARCH_QUERY,
    entityType: "org",
    results: [
      {
        entity_type: "org",
        entity_id: SMOKE_ORG_ID,
        name: SMOKE_SEARCH_RESULT_NAME
      }
    ]
  },
  searchValidation: {
    query: SMOKE_SEARCH_VALIDATION_QUERY,
    entityType: "candidate",
    status: 422,
    detail: [{ loc: ["query", "q"], msg: "Synthetic validation failure for smoke coverage" }]
  },
  searchSlow: {
    query: SMOKE_SEARCH_SLOW_QUERY,
    entityType: "org",
    delayMs: 350,
    results: [
      {
        entity_type: "org",
        entity_id: SMOKE_ORG_ID,
        name: SMOKE_SEARCH_RESULT_NAME
      }
    ]
  },
  searchCandidate: {
    query: SMOKE_SEARCH_CANDIDATE_QUERY,
    entityType: "candidate",
    results: [
      {
        entity_type: "candidate",
        entity_id: SMOKE_PERSON_ID,
        name: SMOKE_SEARCH_CANDIDATE_RESULT_NAME
      }
    ]
  },
  searchContest: {
    query: SMOKE_SEARCH_CONTEST_QUERY,
    entityType: "contest",
    results: [
      {
        entity_type: "contest",
        entity_id: SMOKE_CONTEST_ID,
        name: SMOKE_CONTEST_NAME
      }
    ]
  },
  congressMembers: [
    {
      person_id: SMOKE_PERSON_ID,
      person_name: SMOKE_PERSON_CANONICAL_NAME,
      officeholding_id: SMOKE_OFFICEHOLDING_ID,
      office_id: SMOKE_OFFICE_ID,
      office_name: "U.S. Representative for North Carolina's 1st congressional district",
      chamber: "House",
      state: "NC",
      district: "01",
      district_or_class: "District 01",
      party: "Democratic",
      portrait_source_image_url: SMOKE_CONGRESS_PORTRAIT_URL,
      person_detail_path: `/person/${SMOKE_PERSON_ID}`
    },
    {
      person_id: SMOKE_CONGRESS_SECOND_PERSON_ID,
      person_name: SMOKE_CONGRESS_SECOND_NAME,
      officeholding_id: "21111111-1111-4111-8111-111111111112",
      office_id: "21111111-1111-4111-8111-111111111113",
      office_name: "U.S. Senator from Georgia",
      chamber: "Senate",
      state: "GA",
      district: null,
      district_or_class: "Class II",
      party: "Republican",
      portrait_source_image_url: null,
      person_detail_path: `/person/${SMOKE_CONGRESS_SECOND_PERSON_ID}`
    },
    {
      person_id: SMOKE_CONGRESS_NO_MONEY_PERSON_ID,
      person_name: SMOKE_CONGRESS_NO_MONEY_NAME,
      officeholding_id: "31111111-1111-4111-8111-111111111112",
      office_id: "31111111-1111-4111-8111-111111111113",
      office_name: "Delegate to the U.S. House from Puerto Rico",
      chamber: "House",
      state: "PR",
      district: null,
      district_or_class: "Delegate",
      party: "Democratic",
      portrait_source_image_url: null,
      person_detail_path: `/person/${SMOKE_CONGRESS_NO_MONEY_PERSON_ID}`
    }
  ],
  congressMoneySummaries: [
    {
      person_id: SMOKE_CONGRESS_LEADER_PERSON_ID,
      person_name: SMOKE_CONGRESS_LEADER_NAME,
      has_fec_money: true,
      candidate_id: "H6NC01001",
      total_raised: "300.00",
      total_spent: "200.00",
      net: "100.00",
      cash_on_hand: "60.00",
      summary_source: "fec_candidate_totals",
      ie_support_total: "90.00",
      ie_oppose_total: "30.00",
      ie_support_count: 2,
      ie_oppose_count: 1,
      sources: [
        {
          domain: "fec",
          jurisdiction: "US",
          data_source_name: "FEC candidate summary",
          data_source_url: "https://api.open.fec.gov/developers/",
          source_record_key: "H6NC01001",
          record_url: SMOKE_CONGRESS_LEADER_SOURCE_HREF,
          pull_date: "2026-07-16"
        }
      ]
    },
    {
      person_id: SMOKE_CONGRESS_SECOND_PERSON_ID,
      person_name: SMOKE_CONGRESS_SECOND_NAME,
      has_fec_money: true,
      candidate_id: "S6GA00001",
      total_raised: "100.00",
      total_spent: "75.00",
      net: "25.00",
      cash_on_hand: "0.00",
      summary_source: "fec_candidate_totals",
      ie_support_total: "20.00",
      ie_oppose_total: "80.00",
      ie_support_count: 1,
      ie_oppose_count: 3,
      sources: [
        {
          domain: "fec",
          jurisdiction: "US",
          data_source_name: "FEC candidate summary",
          data_source_url: "https://api.open.fec.gov/developers/",
          source_record_key: "S6GA00001",
          record_url: SMOKE_CONGRESS_SECOND_SOURCE_HREF,
          pull_date: "2026-07-16"
        }
      ]
    },
    {
      person_id: SMOKE_CONGRESS_NO_MONEY_PERSON_ID,
      person_name: SMOKE_CONGRESS_NO_MONEY_NAME,
      has_fec_money: false,
      candidate_id: null,
      total_raised: "0.00",
      total_spent: "0.00",
      net: "0.00",
      cash_on_hand: null,
      summary_source: null,
      ie_support_total: "0.00",
      ie_oppose_total: "0.00",
      ie_support_count: 0,
      ie_oppose_count: 0,
      sources: []
    }
  ],
  coverageRegistry: [
    {
      domain: SMOKE_COVERAGE_DOMAIN,
      jurisdiction: SMOKE_COVERAGE_JURISDICTION,
      data_source_count: 1,
      latest_data_source_pull_at: "2026-04-25T13:00:00Z",
      latest_source_pull_date: "2026-04-25"
    }
  ],
  dataSourcesMetadata: [
    {
      data_source_id: "cf_nc",
      domain: SMOKE_COVERAGE_DOMAIN,
      jurisdiction: SMOKE_COVERAGE_JURISDICTION,
      name: SMOKE_DATA_SOURCE_NAME,
      source_url: "https://cf.ncsbe.gov/",
      update_frequency: "daily",
      last_pull_at: "2026-04-25T13:00:00Z",
      last_pull_status: "success",
      record_count: 1000,
      latest_source_record_id: "row-1",
      latest_source_record_key: "nc-2026-04-25",
      latest_source_record_url: "https://cf.ncsbe.gov/CFOrgLkup/",
      latest_source_pull_date: "2026-04-25"
    }
  ],
  upcomingElectionTimeline: [
    {
      date: SMOKE_ELECTION_DATE,
      contests: [
        {
          contest_id: SMOKE_CONTEST_ID,
          office_id: SMOKE_OFFICE_ID,
          name: SMOKE_CONTEST_NAME,
          election_type: "general" as const,
          office_name: SMOKE_OFFICE_NAME,
          office_level: "state" as const,
          state: "NC",
          jurisdiction_id: null,
          electoral_division_id: null,
          candidate_count: 1,
          result_status: null,
          winning_person_name: null
        }
      ]
    }
  ],
  electionDateAggregate: {
    date: SMOKE_ELECTION_DATE,
    total_contests: 1,
    total_candidacies: 1,
    contests: [
      {
        contest_id: SMOKE_CONTEST_ID,
        office_id: SMOKE_OFFICE_ID,
        name: SMOKE_CONTEST_NAME,
        election_type: "general" as const,
        office_name: SMOKE_OFFICE_NAME,
        office_level: "state" as const,
        state: "NC",
        jurisdiction_id: null,
        electoral_division_id: null,
        candidate_count: 1,
        result_status: null,
        winning_person_name: null
      }
    ]
  },
  person: {
    id: SMOKE_PERSON_ID,
    detail: {
      id: SMOKE_PERSON_ID,
      canonical_name: SMOKE_PERSON_CANONICAL_NAME,
      name_variants: ["Jane Q. Doe"],
      first_name: "Jane",
      middle_name: "Q",
      last_name: "Doe",
      suffix: null,
      date_of_birth: null,
      year_of_birth: 1984,
      bio_text: null,
      bio_source_url: null,
      bio_license: null,
      bio_pulled_at: null,
      identifiers: {
        fec_candidate_id: "H0NC99999"
      },
      primary_address_id: null,
      er_cluster_id: null,
      er_confidence: 0.97,
      portrait: {
        status: "active",
        rights_status: "licensed",
        source_image_url: "https://images.example.org/jane-doe.jpg",
        mime_type: "image/jpeg",
        width_px: 640,
        height_px: 480
      },
      sources: [
        {
          domain: "campaign_finance",
          jurisdiction: "federal/fec",
          data_source_name: "FEC",
          data_source_url: "https://www.fec.gov",
          source_record_key: "person-1",
          record_url: "https://example.org/person-1",
          pull_date: "2026-03-19T00:00:00Z"
        }
      ]
    },
    contributionInsights: {
      person_id: SMOKE_PERSON_ID,
      has_data: true,
      metadata: {
        selected_cycle: Number(SMOKE_PERSON_SELECTED_CYCLE),
        coverage_start_date: "2022-01-01",
        coverage_end_date: "2026-06-30",
        available_cycles: [2022, 2024, 2026],
        cycles_included: [2022, 2024, 2026],
        committee_count: 1,
        approximate_geography: true,
        excluded_geography: null,
        caveats: []
      },
      monthly_totals: [
        { month: "2026-01", total_amount: SMOKE_PERSON_SMALL_ITEMIZED_DOLLARS, transaction_count: 1 },
        { month: "2026-02", total_amount: SMOKE_PERSON_LARGE_ITEMIZED_DOLLARS, transaction_count: 1 }
      ],
      itemized_size_buckets: [
        {
          label: "$200 and under",
          min_amount: "0.01",
          max_amount: "200.00",
          total_amount: SMOKE_PERSON_SMALL_ITEMIZED_DOLLARS,
          transaction_count: 1
        },
        {
          label: "$200.01-$499.99",
          min_amount: "200.01",
          max_amount: "500.00",
          total_amount: SMOKE_PERSON_LARGE_ITEMIZED_DOLLARS,
          transaction_count: 1
        }
      ],
      dollars_by_size: [
        { label: "Unitemized (<$200)", total_amount: SMOKE_PERSON_UNITEMIZED_DOLLARS, source: "committee_summary" as const },
        { label: "$1-$200 itemized", total_amount: SMOKE_PERSON_SMALL_ITEMIZED_DOLLARS, source: "transactions" as const },
        { label: "$201-$500 itemized", total_amount: SMOKE_PERSON_LARGE_ITEMIZED_DOLLARS, source: "transactions" as const }
      ],
      cycle_totals: [
        {
          cycle: 2026,
          itemized_individual_contribution_amount: SMOKE_PERSON_ITEMIZED_DOLLARS,
          itemized_transaction_count: 2,
          unitemized_individual_contribution_amount: SMOKE_PERSON_UNITEMIZED_DOLLARS,
          total_individual_contribution_amount: SMOKE_PERSON_TOTAL_CONTRIBUTION_DOLLARS,
          source: "mixed_sources" as const
        }
      ],
      career_totals: {
        itemized_individual_contribution_amount: SMOKE_PERSON_ITEMIZED_DOLLARS,
        itemized_transaction_count: 2,
        unitemized_individual_contribution_amount: String(
          Number(SMOKE_PERSON_UNITEMIZED_DOLLARS) + Number(SMOKE_PERSON_PRIOR_UNITEMIZED_DOLLARS)
        ),
        total_individual_contribution_amount: String(
          Number(SMOKE_PERSON_TOTAL_CONTRIBUTION_DOLLARS) + Number(SMOKE_PERSON_PRIOR_UNITEMIZED_DOLLARS)
        ),
        source: "mixed_sources" as const
      },
      geography: {
        by_state: [{ label: "NC", total_amount: SMOKE_PERSON_ITEMIZED_DOLLARS, transaction_count: 2 }],
        by_district: [
          { label: "In district", total_amount: SMOKE_PERSON_SMALL_ITEMIZED_DOLLARS, transaction_count: 1 },
          { label: "Out of district", total_amount: SMOKE_PERSON_LARGE_ITEMIZED_DOLLARS, transaction_count: 1 }
        ],
        district_share: {
          in_district_amount: SMOKE_PERSON_SMALL_ITEMIZED_DOLLARS,
          out_of_district_amount: SMOKE_PERSON_LARGE_ITEMIZED_DOLLARS,
          unknown_district_amount: "0.00",
          share: String(
            Number(SMOKE_PERSON_SMALL_ITEMIZED_DOLLARS) /
              (Number(SMOKE_PERSON_SMALL_ITEMIZED_DOLLARS) + Number(SMOKE_PERSON_LARGE_ITEMIZED_DOLLARS))
          ),
          available: true
        },
        geography_mode: "district" as const,
        classified_amount: SMOKE_PERSON_ITEMIZED_DOLLARS,
        classified_transaction_count: 2,
        unknown_amount: "0.00",
        unknown_transaction_count: 0
      },
      small_dollar_share: {
        small_dollar_amount: SMOKE_PERSON_SMALL_DOLLAR_DOLLARS,
        total_contribution_amount: String(
          Number(SMOKE_PERSON_TOTAL_CONTRIBUTION_DOLLARS) + Number(SMOKE_PERSON_PRIOR_UNITEMIZED_DOLLARS)
        ),
        share: SMOKE_PERSON_SMALL_DOLLAR_SHARE,
        available: true
      }
    },
    topDonors: [
      {
        name: SMOKE_PERSON_TOP_DONOR_ONE_NAME,
        total_amount: SMOKE_PERSON_LARGE_ITEMIZED_DOLLARS,
        transaction_count: 1
      },
      {
        name: SMOKE_PERSON_TOP_DONOR_TWO_NAME,
        total_amount: SMOKE_PERSON_SMALL_ITEMIZED_DOLLARS,
        transaction_count: 1
      }
    ],
    topEmployers: [
      {
        employer: SMOKE_PERSON_TOP_EMPLOYER_ONE_NAME,
        total_amount: SMOKE_PERSON_LARGE_ITEMIZED_DOLLARS,
        transaction_count: 1
      },
      {
        employer: SMOKE_PERSON_TOP_EMPLOYER_TWO_NAME,
        total_amount: SMOKE_PERSON_SMALL_ITEMIZED_DOLLARS,
        transaction_count: 1
      }
    ]
  },
  personNoPortrait: {
    id: SMOKE_PERSON_NO_PORTRAIT_ID,
    detail: {
      id: SMOKE_PERSON_NO_PORTRAIT_ID,
      canonical_name: SMOKE_PERSON_NO_PORTRAIT_CANONICAL_NAME,
      name_variants: [],
      first_name: "Jordan",
      middle_name: null,
      last_name: "Portrait",
      suffix: null,
      date_of_birth: null,
      year_of_birth: null,
      bio_text: null,
      bio_source_url: null,
      bio_license: null,
      bio_pulled_at: null,
      identifiers: { fec_candidate_id: "H0NC00001" },
      primary_address_id: null,
      er_cluster_id: null,
      er_confidence: null,
      portrait: null,
      sources: []
    },
  },
  congressSecondPerson: {
    id: SMOKE_CONGRESS_SECOND_PERSON_ID,
    detail: {
      id: SMOKE_CONGRESS_SECOND_PERSON_ID,
      canonical_name: SMOKE_CONGRESS_SECOND_NAME,
      name_variants: [],
      first_name: "Alex",
      middle_name: null,
      last_name: "Money Senator",
      suffix: null,
      date_of_birth: null,
      year_of_birth: null,
      bio_text: null,
      bio_source_url: null,
      bio_license: null,
      bio_pulled_at: null,
      identifiers: { fec_candidate_id: "S6GA00001" },
      primary_address_id: null,
      er_cluster_id: null,
      er_confidence: null,
      portrait: null,
      sources: [
        {
          domain: "campaign_finance",
          jurisdiction: "federal/fec",
          data_source_name: "FEC",
          data_source_url: "https://www.fec.gov",
          source_record_key: "S6GA00001",
          record_url: SMOKE_CONGRESS_SECOND_SOURCE_HREF,
          pull_date: "2026-07-16"
        }
      ]
    },
    contributionInsights: {
      person_id: SMOKE_CONGRESS_SECOND_PERSON_ID,
      has_data: false,
      metadata: {
        selected_cycle: 2026,
        coverage_start_date: null,
        coverage_end_date: null,
        available_cycles: [2026],
        cycles_included: [2026],
        committee_count: 0,
        approximate_geography: false,
        excluded_geography: null,
        caveats: []
      },
      monthly_totals: [],
      itemized_size_buckets: [],
      dollars_by_size: [],
      cycle_totals: [],
      career_totals: {
        itemized_individual_contribution_amount: "0.00",
        itemized_transaction_count: 0,
        unitemized_individual_contribution_amount: "0.00",
        total_individual_contribution_amount: "0.00",
        source: "transactions" as const
      },
      geography: {
        by_state: [],
        by_district: [],
        district_share: {
          in_district_amount: "0.00",
          out_of_district_amount: "0.00",
          unknown_district_amount: "0.00",
          share: "0",
          available: false
        },
        geography_mode: "state" as const,
        classified_amount: "0.00",
        classified_transaction_count: 0,
        unknown_amount: "0.00",
        unknown_transaction_count: 0
      },
      small_dollar_share: {
        small_dollar_amount: "0.00",
        total_contribution_amount: "0.00",
        share: "0",
        available: false
      }
    },
    topDonors: [],
    topEmployers: []
  },
  rosterDurhamPerson: {
    id: SMOKE_ROSTER_DURHAM_PERSON_ID,
    detail: {
      id: SMOKE_ROSTER_DURHAM_PERSON_ID,
      canonical_name: SMOKE_ROSTER_DURHAM_PERSON_CANONICAL_NAME,
      name_variants: [],
      first_name: "Javiera",
      middle_name: null,
      last_name: "Caballero",
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
      portrait: {
        status: "active",
        rights_status: "licensed",
        source_image_url: SMOKE_ROSTER_DURHAM_PORTRAIT_URL,
        mime_type: "image/jpeg",
        width_px: 75,
        height_px: 75
      },
      sources: [
        {
          domain: "civics",
          jurisdiction: "state/NC",
          data_source_name: "Durham City Council Official Roster",
          data_source_url: "https://www.durhamnc.gov/1396/City-Council-Members",
          source_record_key: "official_roster:nc_durham_city_council_roster:snapshot",
          record_url: "https://www.durhamnc.gov/1396/City-Council-Members",
          pull_date: "2026-04-29T01:31:29Z"
        }
      ]
    },
  },
  rosterNcHousePerson: {
    id: SMOKE_ROSTER_NC_HOUSE_PERSON_ID,
    detail: {
      id: SMOKE_ROSTER_NC_HOUSE_PERSON_ID,
      canonical_name: SMOKE_ROSTER_NC_HOUSE_PERSON_CANONICAL_NAME,
      name_variants: [],
      first_name: "Pricey",
      middle_name: null,
      last_name: "Harrison",
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
      portrait: {
        status: "active",
        rights_status: "licensed",
        source_image_url: SMOKE_ROSTER_NC_HOUSE_PORTRAIT_URL,
        mime_type: "image/jpeg",
        width_px: 320,
        height_px: 400
      },
      sources: [
        {
          domain: "civics",
          jurisdiction: "state/NC",
          data_source_name: "North Carolina House Official Roster",
          data_source_url: "https://www.ncleg.gov/Members/MemberList/H",
          source_record_key: "official_roster:nc_general_assembly_house_roster:snapshot",
          record_url: "https://www.ncleg.gov/Members/MemberList/H",
          pull_date: "2026-04-29T01:31:29Z"
        }
      ]
    },
  },
  personMissingPortraitField: {
    id: SMOKE_PERSON_MISSING_PORTRAIT_FIELD_ID,
    detail: {
      id: SMOKE_PERSON_MISSING_PORTRAIT_FIELD_ID,
      canonical_name: SMOKE_PERSON_MISSING_PORTRAIT_CANONICAL_NAME,
      name_variants: [],
      first_name: "Avery",
      middle_name: null,
      last_name: "Missing",
      suffix: null,
      date_of_birth: null,
      year_of_birth: null,
      bio_text: null,
      bio_source_url: null,
      bio_license: null,
      bio_pulled_at: null,
      identifiers: { fec_candidate_id: "H0NC00002" },
      primary_address_id: null,
      er_cluster_id: null,
      er_confidence: null,
      sources: []
    },
  },
  org: {
    id: SMOKE_ORG_ID,
    detail: {
      id: SMOKE_ORG_ID,
      canonical_name: SMOKE_ORG_CANONICAL_NAME,
      name_variants: ["Civibus Action Committee"],
      org_type: "pac",
      registered_state: "NC",
      formation_date: "2014-05-01",
      dissolution_date: null,
      identifiers: {
        fec_committee_id: "C12345678"
      },
      primary_address_id: null,
      er_cluster_id: null,
      er_confidence: 0.91,
      sources: [
        {
          domain: "campaign_finance",
          jurisdiction: "federal/fec",
          data_source_name: "FEC",
          data_source_url: "https://www.fec.gov",
          source_record_key: "org-1",
          record_url: "https://example.org/org-1",
          pull_date: "2026-03-19T00:00:00Z"
        }
      ]
    },
  },
  committee: {
    id: SMOKE_COMMITTEE_ID,
    detail: {
      id: SMOKE_COMMITTEE_ID,
      fec_committee_id: "C12345678",
      name: SMOKE_COMMITTEE_NAME,
      slug: SMOKE_COMMITTEE_SLUG,
      slug_is_unique: true,
      organization_id: SMOKE_ORG_ID,
      committee_type: "Q",
      committee_designation: "P",
      party: "DEM",
      state: "NC",
      city: "Raleigh",
      zip_code: "27601",
      treasurer_name: "Jordan Treasurer",
      linked_candidates: [
        {
          id: SMOKE_CANDIDATE_ID,
          fec_candidate_id: "H0NC01001",
          name: SMOKE_CANDIDATE_NAME,
          person_id: SMOKE_PERSON_ID,
          party: "DEM",
          office: "H",
          state: "NC",
          district: "01",
          slug: SMOKE_CANDIDATE_SLUG,
          slug_is_unique: true
        }
      ],
      sources: [
        {
          domain: "campaign_finance",
          jurisdiction: "state/IN",
          data_source_name: "Indiana Campaign Finance",
          data_source_url: "https://campaignfinance.in.gov/PublicSite/Reporting/DataDownload.aspx",
          source_record_key: "committee-1",
          record_url: "https://example.org/committee-1",
          pull_date: "2026-03-19T00:00:00Z"
        }
      ]
    },
    transactions: [
      {
        id: "77777777-7777-4777-8777-777777777777",
        filing_id: SMOKE_FILING_ID,
        committee_id: SMOKE_COMMITTEE_ID,
        transaction_type: "contribution",
        transaction_identifier: "TX-001",
        transaction_date: "2026-03-18",
        amount: 125,
        contributor_name_raw: "Donor Example",
        contributor_employer: null,
        contributor_occupation: null,
        contributor_city: "Durham",
        contributor_state: "NC",
        contributor_zip: "27701",
        contributor_person_id: SMOKE_PERSON_ID,
        contributor_organization_id: SMOKE_ORG_ID,
        contributor_address_id: null,
        recipient_candidate_id: SMOKE_CANDIDATE_ID,
        recipient_committee_id: SMOKE_COMMITTEE_ID,
        memo_text: null,
        is_memo: false,
        amendment_indicator: "N",
        date_is_reliable: true
      }
    ],
    summary: {
      committee_id: SMOKE_COMMITTEE_ID,
      committee_name: SMOKE_COMMITTEE_NAME,
      selected_cycle: 2026,
      coverage_start_date: "2026-01-01",
      coverage_end_date: "2026-06-30",
      available_cycles: [2026],
      total_raised: "125.00",
      total_spent: "40.00",
      net: "85.00",
      transaction_count: 3,
      jurisdiction: "federal/fec",
      data_through: "2026-03-19T00:00:00Z",
      cash_receipts_total: "125.00",
      in_kind_receipts_total: "0.00",
      loan_receipts_total: "0.00",
      contribution_receipts_total: "125.00",
      top_donors: [],
      top_vendors: [],
      spend_categories: null,
      itemized_transaction_count: 3,
      cycle_summaries: [],
      summary_source: "derived" as const
    },
    filingBreakdown: {
      committee_id: SMOKE_COMMITTEE_ID,
      committee_name: SMOKE_COMMITTEE_NAME,
      filings: [
        {
          filing_id: SMOKE_FILING_ID,
          filing_fec_id: "F3N",
          filing_name: "Q1 Filing",
          report_type: "Q1",
          amendment_indicator: "N",
          coverage_start_date: "2026-01-01",
          coverage_end_date: "2026-03-31",
          receipt_date: "2026-04-15",
          total_raised: "125.00",
          total_spent: "40.00",
          net: "85.00",
          transaction_count: 3,
          cash_on_hand: "125.00",
          row_id: `${SMOKE_FILING_ID}:N`
        },
        {
          filing_id: "33333333-3333-4333-8333-333333333334",
          filing_fec_id: "F3N",
          filing_name: "Q2 Filing",
          report_type: "Q2",
          amendment_indicator: "N",
          coverage_start_date: "2026-06-01",
          coverage_end_date: "2026-06-30",
          receipt_date: "2026-07-15",
          total_raised: "250.50",
          total_spent: "100.00",
          net: "150.50",
          transaction_count: 2,
          cash_on_hand: "250.50",
          row_id: "33333333-3333-4333-8333-333333333334:N"
        }
      ]
    },
    independentExpendituresMade: {
      committee_id: SMOKE_COMMITTEE_ID,
      support_total: "1500.00",
      oppose_total: "250.00",
      ie_transaction_count: 3,
      excluded_outlier_count: 1,
      targets: [
        {
          candidate_id: SMOKE_CANDIDATE_ID,
          fec_candidate_id: "H0NC01001",
          candidate_name: SMOKE_CANDIDATE_NAME,
          person_id: SMOKE_PERSON_ID,
          party: "DEM",
          office: "H",
          state: "NC",
          district: "01",
          slug: SMOKE_CANDIDATE_SLUG,
          slug_is_unique: true,
          support_total: "1500.00",
          oppose_total: "250.00",
          transaction_count: 3,
          sources: [
            {
              domain: "campaign_finance",
              jurisdiction: "federal/fec",
              data_source_name: SMOKE_COMMITTEE_IE_SOURCE_NAME,
              data_source_url: "https://www.fec.gov",
              source_record_key: SMOKE_COMMITTEE_IE_SOURCE_RECORD_KEY,
              record_url: SMOKE_COMMITTEE_IE_SOURCE_URL,
              pull_date: "2026-03-19T00:00:00Z"
            }
          ]
        }
      ]
    }
  },
  committeeFilingsPaged: committeeFilingsPagedFixture,
  committeeFilingsHighTotal: committeeFilingsHighTotalFixture,
  committeeEmpty: {
    id: SMOKE_EMPTY_COMMITTEE_ID,
    detail: {
      id: SMOKE_EMPTY_COMMITTEE_ID,
      fec_committee_id: "C00000000",
      name: "Committee Empty",
      slug: "committee-empty",
      slug_is_unique: false,
      organization_id: null,
      committee_type: null,
      committee_designation: null,
      party: null,
      state: null,
      city: null,
      zip_code: null,
      treasurer_name: null,
      linked_candidates: [],
      sources: []
    },
    transactions: [],
    summary: {
      committee_id: SMOKE_EMPTY_COMMITTEE_ID,
      committee_name: "Committee Empty",
      total_raised: "0.00",
      total_spent: "0.00",
      net: "0.00",
      transaction_count: 0,
      jurisdiction: null,
      data_through: null,
      cash_receipts_total: "0.00",
      in_kind_receipts_total: "0.00",
      loan_receipts_total: "0.00",
      contribution_receipts_total: "0.00",
      top_donors: [],
      top_vendors: [],
      spend_categories: [],
      itemized_transaction_count: 0,
      cycle_summaries: [],
      summary_source: "derived" as const
    },
    filingBreakdown: {
      committee_id: SMOKE_EMPTY_COMMITTEE_ID,
      committee_name: "Committee Empty",
      filings: []
    },
    independentExpendituresMade: {
      committee_id: SMOKE_EMPTY_COMMITTEE_ID,
      support_total: "0.00",
      oppose_total: "0.00",
      ie_transaction_count: 0,
      excluded_outlier_count: 0,
      targets: []
    }
  },
  committeePhl: {
    id: SMOKE_PHL_COMMITTEE_ID,
    detail: {
      id: SMOKE_PHL_COMMITTEE_ID,
      fec_committee_id: "PHL-CF-0001",
      name: SMOKE_PHL_COMMITTEE_NAME,
      slug: "philadelphia-transit-neighbors",
      slug_is_unique: false,
      organization_id: SMOKE_ORG_ID,
      committee_type: "Q",
      committee_designation: "P",
      party: "DEM",
      state: "PA",
      city: "Philadelphia",
      zip_code: "19107",
      treasurer_name: "Taylor Treasurer",
      linked_candidates: [],
      sources: [
        {
          domain: "campaign_finance",
          jurisdiction: "municipality/PHL",
          data_source_name: "Philadelphia Campaign Finance",
          data_source_url: "https://www.opendataphilly.org/dataset/campaign-finance",
          source_record_key: "phl-committee-1",
          record_url: "https://www.opendataphilly.org/dataset/campaign-finance",
          pull_date: "2026-03-19T00:00:00Z"
        }
      ]
    },
    transactions: [
      {
        id: "17171717-1717-4171-8171-171717171717",
        filing_id: SMOKE_FILING_ID,
        committee_id: SMOKE_PHL_COMMITTEE_ID,
        transaction_type: "contribution",
        transaction_identifier: "PHL-TX-001",
        transaction_date: "2026-03-17",
        amount: 2100,
        contributor_name_raw: "SEPTA Riders PAC",
        contributor_employer: null,
        contributor_occupation: null,
        contributor_city: "Philadelphia",
        contributor_state: "PA",
        contributor_zip: "19103",
        contributor_person_id: SMOKE_PERSON_ID,
        contributor_organization_id: SMOKE_ORG_ID,
        contributor_address_id: null,
        recipient_candidate_id: SMOKE_CANDIDATE_ID,
        recipient_committee_id: SMOKE_PHL_COMMITTEE_ID,
        memo_text: null,
        is_memo: false,
        amendment_indicator: "N",
        date_is_reliable: true
      }
    ],
    summary: {
      committee_id: SMOKE_PHL_COMMITTEE_ID,
      committee_name: SMOKE_PHL_COMMITTEE_NAME,
      total_raised: "2100.00",
      total_spent: "300.00",
      net: "1800.00",
      transaction_count: 1,
      jurisdiction: "municipality/PHL",
      data_through: "2026-03-19T00:00:00Z",
      cash_receipts_total: "2100.00",
      in_kind_receipts_total: "0.00",
      loan_receipts_total: "0.00",
      contribution_receipts_total: "2100.00",
      top_donors: [],
      top_vendors: [],
      spend_categories: null,
      itemized_transaction_count: 1,
      cycle_summaries: [],
      summary_source: "derived" as const
    },
    filingBreakdown: {
      committee_id: SMOKE_PHL_COMMITTEE_ID,
      committee_name: SMOKE_PHL_COMMITTEE_NAME,
      filings: [
        {
          filing_id: SMOKE_FILING_ID,
          filing_fec_id: "PHL-Q1",
          filing_name: "Q1 Local Filing",
          report_type: "Q1",
          amendment_indicator: "N",
          coverage_start_date: "2026-01-01",
          coverage_end_date: "2026-03-31",
          receipt_date: "2026-04-15",
          total_raised: "2100.00",
          total_spent: "300.00",
          net: "1800.00",
          transaction_count: 1,
          cash_on_hand: null
        }
      ]
    },
    independentExpendituresMade: {
      committee_id: SMOKE_PHL_COMMITTEE_ID,
      support_total: "0.00",
      oppose_total: "0.00",
      ie_transaction_count: 0,
      excluded_outlier_count: 0,
      targets: []
    }
  },
  candidate: {
    id: SMOKE_CANDIDATE_ID,
    detail: {
      id: SMOKE_CANDIDATE_ID,
      fec_candidate_id: "H0NC01001",
      name: SMOKE_CANDIDATE_NAME,
      slug: SMOKE_CANDIDATE_SLUG,
      slug_is_unique: true,
      person_id: SMOKE_PERSON_ID,
      party: "DEM",
      office: "H",
      state: "NC",
      district: "01",
      incumbent_challenge: "I",
      principal_committee_id: SMOKE_COMMITTEE_ID,
      sources: [
        {
          domain: "campaign_finance",
          jurisdiction: "state/IN",
          data_source_name: "Indiana Campaign Finance",
          data_source_url: "https://campaignfinance.in.gov/PublicSite/Reporting/DataDownload.aspx",
          source_record_key: "candidate-1",
          record_url: "https://example.org/candidate-1",
          pull_date: "2026-03-19T00:00:00Z"
        }
      ]
    },
    summary: {
      candidate_id: SMOKE_CANDIDATE_ID,
      candidate_name: SMOKE_CANDIDATE_NAME,
      selected_cycle: Number(SMOKE_CANDIDATE_SELECTED_CYCLE),
      coverage_start_date: "2026-01-01",
      coverage_end_date: SMOKE_CANDIDATE_COVERAGE_THROUGH,
      available_cycles: [Number(SMOKE_CANDIDATE_SELECTED_CYCLE)],
      total_raised: "250.00",
      total_spent: "80.00",
      net: "170.00",
      transaction_count: 5,
      debts_owed_by_committee: "0.00",
      receipt_source_composition: [
        {
          label: "Gross individual contributions",
          total_amount: "125.00",
          source: "fec_committee_summary" as const
        },
        {
          label: "PAC/other committee contributions",
          total_amount: "125.00",
          source: "fec_committee_summary" as const
        }
      ],
      selected_cycle_coverage_complete: true,
      can_render_share: true,
      receipt_source_caveats: [],
      committees: [
        {
          committee_id: SMOKE_COMMITTEE_ID,
          committee_name: SMOKE_COMMITTEE_NAME,
          slug: SMOKE_COMMITTEE_SLUG,
          slug_is_unique: true,
          total_raised: "250.00",
          total_spent: "80.00",
          net: "170.00",
          transaction_count: 5,
          jurisdiction: "federal/fec",
          data_through: "2026-03-19T00:00:00Z",
          selected_cycle: Number(SMOKE_CANDIDATE_SELECTED_CYCLE),
          coverage_start_date: "2026-01-01",
          coverage_end_date: SMOKE_CANDIDATE_COVERAGE_THROUGH,
          available_cycles: [Number(SMOKE_CANDIDATE_SELECTED_CYCLE)],
          cash_receipts_total: "250.00",
          in_kind_receipts_total: "0.00",
          loan_receipts_total: "0.00",
          contribution_receipts_total: "250.00",
          top_donors: [],
          top_vendors: [],
          spend_categories: null,
          itemized_transaction_count: 5,
          cycle_summaries: [],
          summary_source: "derived" as const
        }
      ],
      cash_on_hand: SMOKE_CANDIDATE_CASH_ON_HAND.replace("$", "").replace(",", ""),
      summary_source: "fec_weball" as const,
      itemized_transaction_count: 5
    },
    ieTransactions: [
      {
        id: "dd222222-2222-4222-8222-222222222222",
        filing_id: SMOKE_FILING_ID,
        committee_id: SMOKE_IE_COMMITTEE_A_ID,
        committee_name: SMOKE_IE_COMMITTEE_A_NAME,
        amount: 5000,
        transaction_date: "2026-03-19",
        purpose: "Independent expenditure",
        dissemination_date: SMOKE_IE_TRANSACTION_DISSEMINATION_DATE,
        aggregate_amount: 5000,
        support_oppose: "S" as const
      }
    ],
    ieSummary: {
      candidate_id: SMOKE_CANDIDATE_ID,
      selected_cycle: Number(SMOKE_CANDIDATE_SELECTED_CYCLE),
      coverage_start_date: "2026-01-01",
      coverage_end_date: SMOKE_CANDIDATE_COVERAGE_THROUGH,
      available_cycles: [Number(SMOKE_CANDIDATE_SELECTED_CYCLE)],
      support_total: "15000.00",
      oppose_total: "8500.00",
      support_count: 12,
      oppose_count: 5,
      top_spenders: [
        {
          committee_id: SMOKE_IE_COMMITTEE_A_ID,
          committee_name: SMOKE_IE_COMMITTEE_A_NAME,
          support_oppose: "S" as const,
          total_amount: "10000.00",
          transaction_count: 8
        }
      ],
      excluded_outlier_count: 0
    }
  },
  candidateEmpty: {
    id: SMOKE_EMPTY_CANDIDATE_ID,
    detail: {
      id: SMOKE_EMPTY_CANDIDATE_ID,
      fec_candidate_id: "H0NC99998",
      name: "Candidate Empty",
      slug: "candidate-empty",
      slug_is_unique: false,
      person_id: null,
      party: null,
      office: "H",
      state: null,
      district: null,
      incumbent_challenge: null,
      principal_committee_id: null,
      sources: []
    },
    summary: {
      candidate_id: SMOKE_EMPTY_CANDIDATE_ID,
      candidate_name: "Candidate Empty",
      total_raised: "0.00",
      total_spent: "0.00",
      net: "0.00",
      transaction_count: 0,
      committees: []
    }
  },
  candidateDeviant: {
    id: SMOKE_DEVIANT_CANDIDATE_ID,
    detail: {
      id: SMOKE_DEVIANT_CANDIDATE_ID,
      fec_candidate_id: "H0NC99997",
      name: "Candidate Deviant",
      slug: "candidate-deviant",
      slug_is_unique: false,
      person_id: null,
      party: "DEM",
      office: "H",
      state: "NC",
      district: "09",
      incumbent_challenge: "C",
      principal_committee_id: SMOKE_COMMITTEE_ID,
      keel_l10_reference: {
        totalRaised: "1000.00",
        sourceLabel: "NC SBOE anchor",
        methodologyHref: "/methodology",
        deviationThresholdRatio: 0.2
      },
      sources: []
    },
    summary: {
      candidate_id: SMOKE_DEVIANT_CANDIDATE_ID,
      candidate_name: "Candidate Deviant",
      total_raised: "250.00",
      total_spent: "80.00",
      net: "170.00",
      transaction_count: 5,
      committees: [
        {
          committee_id: SMOKE_COMMITTEE_ID,
          committee_name: SMOKE_COMMITTEE_NAME,
          slug: SMOKE_COMMITTEE_SLUG,
          slug_is_unique: true,
          total_raised: "250.00",
          total_spent: "80.00",
          net: "170.00",
          transaction_count: 5,
          jurisdiction: "federal/fec",
          data_through: "2026-03-19T00:00:00Z"
        }
      ]
    }
  },
  candidateAl: {
    id: SMOKE_AL_CANDIDATE_ID,
    detail: {
      id: SMOKE_AL_CANDIDATE_ID,
      fec_candidate_id: "H0AL00001",
      name: "Candidate Alabama",
      slug: "candidate-alabama",
      slug_is_unique: false,
      person_id: null,
      party: "REP",
      office: "S",
      state: "AL",
      district: null,
      incumbent_challenge: "C",
      principal_committee_id: SMOKE_COMMITTEE_ID,
      sources: [
        {
          domain: "campaign_finance",
          jurisdiction: "state/AL",
          data_source_name: "Alabama Campaign Finance",
          data_source_url: "https://fcpa.alabamavotes.gov/page.request.do?page=page.acfPublicDownloadData",
          source_record_key: "candidate-al-1",
          record_url: "https://example.org/candidate-al-1",
          pull_date: "2026-03-19T00:00:00Z"
        }
      ]
    },
    summary: {
      candidate_id: SMOKE_AL_CANDIDATE_ID,
      candidate_name: "Candidate Alabama",
      total_raised: "900.00",
      total_spent: "325.00",
      net: "575.00",
      transaction_count: 4,
      committees: [
        {
          committee_id: SMOKE_COMMITTEE_ID,
          committee_name: SMOKE_COMMITTEE_NAME,
          slug: SMOKE_COMMITTEE_SLUG,
          slug_is_unique: true,
          total_raised: "900.00",
          total_spent: "325.00",
          net: "575.00",
          transaction_count: 4,
          jurisdiction: "state/AL",
          data_through: "2026-03-19T00:00:00Z"
        }
      ]
    }
  },
  candidateGa: {
    id: SMOKE_GA_CANDIDATE_ID,
    detail: {
      id: SMOKE_GA_CANDIDATE_ID,
      fec_candidate_id: "H0GA00001",
      name: "Candidate Georgia",
      slug: "candidate-georgia",
      slug_is_unique: false,
      person_id: null,
      party: "DEM",
      office: "S",
      state: "GA",
      district: null,
      incumbent_challenge: "C",
      principal_committee_id: SMOKE_COMMITTEE_ID,
      sources: [
        {
          domain: "campaign_finance",
          jurisdiction: "state/GA",
          data_source_name: "Georgia Campaign Finance",
          data_source_url: "https://media.ethics.ga.gov/search/Campaign/Campaign_ByContributions.aspx",
          source_record_key: "candidate-ga-1",
          record_url: "https://example.org/candidate-ga-1",
          pull_date: "2026-03-19T00:00:00Z"
        }
      ]
    },
    summary: {
      candidate_id: SMOKE_GA_CANDIDATE_ID,
      candidate_name: "Candidate Georgia",
      total_raised: "1200.00",
      total_spent: "475.00",
      net: "725.00",
      transaction_count: 6,
      committees: [
        {
          committee_id: SMOKE_COMMITTEE_ID,
          committee_name: SMOKE_COMMITTEE_NAME,
          slug: SMOKE_COMMITTEE_SLUG,
          slug_is_unique: true,
          total_raised: "1200.00",
          total_spent: "475.00",
          net: "725.00",
          transaction_count: 6,
          jurisdiction: "state/GA",
          data_through: "2026-03-19T00:00:00Z"
        }
      ]
    }
  },
  candidateList: {
    items: [
      {
        id: SMOKE_CANDIDATE_ID,
        fec_candidate_id: "H0NC01001",
        name: SMOKE_CANDIDATE_NAME,
        person_id: SMOKE_PERSON_ID,
        party: "DEM",
        office: "H",
        state: "NC",
        district: "01",
        slug: SMOKE_CANDIDATE_SLUG,
        slug_is_unique: true
      },
      {
        id: SMOKE_EMPTY_CANDIDATE_ID,
        fec_candidate_id: "H0NC99998",
        name: "Candidate Empty",
        person_id: null,
        party: null,
        office: "H",
        state: null,
        district: null,
        slug: "candidate-empty",
        slug_is_unique: false
      }
    ],
    has_next: true,
    offset: 0,
    limit: 1
  },
  committeeList: {
    items: [
      {
        id: SMOKE_COMMITTEE_ID,
        fec_committee_id: "C12345678",
        name: SMOKE_COMMITTEE_NAME,
        committee_type: "Q",
        party: "DEM",
        state: "NC",
        slug: SMOKE_COMMITTEE_SLUG,
        slug_is_unique: true
      },
      {
        id: SMOKE_EMPTY_COMMITTEE_ID,
        fec_committee_id: "C00000000",
        name: "Committee Empty",
        committee_type: null,
        party: null,
        state: null,
        slug: "committee-empty",
        slug_is_unique: false
      }
    ],
    has_next: true,
    offset: 0,
    limit: 1
  },
  slugLookups: {
    candidates: {
      [SMOKE_CANDIDATE_SLUG]: [
        {
          id: SMOKE_CANDIDATE_ID,
          fec_candidate_id: "H0NC01001",
          name: SMOKE_CANDIDATE_NAME,
          party: "DEM",
          office: "H",
          state: "NC",
          district: "01",
          slug: SMOKE_CANDIDATE_SLUG,
          slug_is_unique: true
        }
      ],
      [SMOKE_COLLIDING_CANDIDATE_SLUG]: [
        {
          id: SMOKE_CANDIDATE_ID,
          fec_candidate_id: "H0NC01001",
          name: SMOKE_CANDIDATE_NAME,
          party: "DEM",
          office: "H",
          state: "NC",
          district: "01",
          slug: SMOKE_COLLIDING_CANDIDATE_SLUG,
          slug_is_unique: false
        },
        {
          id: SMOKE_COLLIDING_CANDIDATE_ID,
          fec_candidate_id: "H0NC01003",
          name: "Pat Candidate Jr",
          party: "DEM",
          office: "H",
          state: "NC",
          district: "02",
          slug: SMOKE_COLLIDING_CANDIDATE_SLUG,
          slug_is_unique: false
        }
      ]
    },
    committees: {
      [SMOKE_COMMITTEE_SLUG]: [
        {
          id: SMOKE_COMMITTEE_ID,
          fec_committee_id: "C12345678",
          name: SMOKE_COMMITTEE_NAME,
          committee_type: "Q",
          party: "DEM",
          state: "NC",
          slug: SMOKE_COMMITTEE_SLUG,
          slug_is_unique: true
        }
      ],
      [SMOKE_COLLIDING_COMMITTEE_SLUG]: [
        {
          id: SMOKE_COMMITTEE_ID,
          fec_committee_id: "C12345678",
          name: SMOKE_COMMITTEE_NAME,
          committee_type: "Q",
          party: "DEM",
          state: "NC",
          slug: SMOKE_COLLIDING_COMMITTEE_SLUG,
          slug_is_unique: false
        },
        {
          id: SMOKE_COLLIDING_COMMITTEE_ID,
          fec_committee_id: "C00009999",
          name: "Citizens for Civibus NC",
          committee_type: "P",
          party: "DEM",
          state: "NC",
          slug: SMOKE_COLLIDING_COMMITTEE_SLUG,
          slug_is_unique: false
        }
      ]
    }
  },
  ncCountyDrilldown: {
    stateCode: SMOKE_NC_SHOWCASE_STATE_CODE,
    countySlug: SMOKE_NC_SHOWCASE_COUNTY_SLUG,
    geometryByLevel: {
      state: {
        type: "FeatureCollection",
        features: [
          {
            type: "Feature",
            geometry: { type: "Polygon", coordinates: [] },
            properties: {
              id: "state-nc",
              name: "North Carolina",
              division_type: "statewide",
              state: "NC",
              district_number: null,
              boundary_year: 2024
            }
          }
        ]
      },
      county: {
        type: "FeatureCollection",
        features: [
          {
            type: "Feature",
            geometry: { type: "Polygon", coordinates: [] },
            properties: {
              id: "county-nc-wake",
              name: SMOKE_NC_SHOWCASE_COUNTY_DIVISION_NAME,
              division_type: "county",
              state: "NC",
              district_number: null,
              boundary_year: 2024
            }
          },
          {
            type: "Feature",
            geometry: { type: "Polygon", coordinates: [] },
            properties: {
              id: "county-nc-durham",
              name: "nc_county_durham",
              division_type: "county",
              state: "NC",
              district_number: null,
              boundary_year: 2024
            }
          }
        ]
      },
      congressional_district: {
        type: "FeatureCollection",
        features: [
          {
            type: "Feature",
            geometry: { type: "Polygon", coordinates: [] },
            properties: {
              id: "district-nc-01",
              name: SMOKE_NC_SHOWCASE_DISTRICT_DIVISION_NAME,
              division_type: "congressional_district",
              state: "NC",
              district_number: "01",
              boundary_year: 2024
            }
          }
        ]
      }
    },
    campaignFinanceSummary: {
      state: "nc",
      county_slug: SMOKE_NC_SHOWCASE_COUNTY_SLUG,
      donor_total_cents: 123456,
      transaction_count: 7,
      top_recipient_committees: [
        {
          committee_id: "0a111111-1111-4111-8111-111111111111",
          committee_name: SMOKE_NC_SHOWCASE_RECIPIENT_NAME,
          donor_total_cents: 82500,
          transaction_count: 4
        }
      ],
      top_linked_candidates: [
        {
          candidate_id: "0b222222-2222-4222-8222-222222222222",
          candidate_name: "Casey Example",
          donor_total_cents: 61000,
          transaction_count: 3
        }
      ],
      sources: [
        {
          domain: "campaign_finance",
          jurisdiction: "state/nc",
          data_source_name: "NC Campaign Finance",
          data_source_url: "https://cf.ncsbe.gov",
          source_record_key: "wake_proxy_summary_2026_04_20",
          record_url: "https://cf.ncsbe.gov/CFOrgLkup/",
          pull_date: "2026-04-20T12:00:00Z"
        }
      ]
    }
  },
  property: {
    id: SMOKE_PROPERTY_ID,
    detail: {
      id: SMOKE_PROPERTY_ID,
      reid: "200000001",
      pin: "0999999999",
      site_address: SMOKE_PROPERTY_TITLE,
      property_description: "Single family home",
      city: "Durham",
      zoning_class: "R-20",
      land_class: "Residential",
      acreage: "1.2500",
      neighborhood: "Northside",
      fire_district: "Durham",
      is_pending: false,
      deed_date: "2024-01-15",
      deed_book: "1234",
      deed_page: "567",
      jurisdiction_id: null,
      sources: [
        {
          domain: "property",
          jurisdiction: "us/nc/durham",
          data_source_name: "Durham County",
          data_source_url: "https://example.org/durham",
          source_record_key: "parcel-1",
          record_url: "https://example.org/parcel-1",
          pull_date: "2026-03-19T00:00:00Z"
        }
      ],
      ownership: [
        {
          id: "88888888-8888-4888-8888-888888888888",
          owner_name: "Civibus Homeowner",
          owner_mail_line1: "123 MAIN ST",
          owner_mail_line2: null,
          owner_mail_line3: null,
          owner_mail_city: "Durham",
          owner_mail_state: "NC",
          owner_mail_zip5: "27701",
          ownership_recorded_at: "2024-02-01",
          valid_period: "[2024-02-01,)",
          date_precision: "day",
          owner_person_id: SMOKE_PERSON_ID,
          owner_organization_id: SMOKE_ORG_ID,
          owner_address_id: null,
          sources: []
        }
      ],
      assessments: [
        {
          id: "99999999-9999-4999-8999-999999999999",
          tax_year: 2025,
          land_assessed_value: "150000.00",
          improvement_assessed_value: "350000.00",
          total_assessed_value: "500000.00",
          assessed_at: "2025-01-31",
          heated_area: 2500,
          exemption_description: "Homestead",
          sources: []
        }
      ]
    }
  },
  propertyEmpty: {
    id: SMOKE_EMPTY_PROPERTY_ID,
    detail: {
      id: SMOKE_EMPTY_PROPERTY_ID,
      reid: "200000099",
      pin: "0999999900",
      site_address: SMOKE_EMPTY_PROPERTY_TITLE,
      property_description: null,
      city: "Durham",
      zoning_class: null,
      land_class: null,
      acreage: null,
      neighborhood: null,
      fire_district: null,
      is_pending: false,
      deed_date: null,
      deed_book: null,
      deed_page: null,
      jurisdiction_id: null,
      sources: [],
      ownership: [],
      assessments: []
    }
  },
  office: {
    id: SMOKE_OFFICE_ID,
    detail: {
      id: SMOKE_OFFICE_ID,
      name: SMOKE_OFFICE_NAME,
      office_level: "federal",
      title: "Senator",
      jurisdiction_id: null,
      state: "NC",
      is_elected: true,
      number_of_seats: 1,
      current_officeholders: [
        {
          officeholding_id: SMOKE_OFFICE_OFFICEHOLDER_ID,
          person_id: SMOKE_PERSON_ID,
          person_name: SMOKE_OFFICE_OFFICEHOLDER_NAME,
          holder_status: "elected"
        }
      ],
      current_holder_card: {
        officeholding_id: SMOKE_OFFICE_OFFICEHOLDER_ID,
        person_id: SMOKE_PERSON_ID,
        person_name: SMOKE_OFFICE_OFFICEHOLDER_NAME,
        holder_status: "elected",
        electoral_division_id: null,
        electoral_division_type: "state",
        electoral_division_state: "NC",
        valid_period_lower: "2021-01-03",
        valid_period_upper: null,
        date_precision: "day" as const
      },
      officeholding_timeline: [
        {
          officeholding_id: SMOKE_OFFICE_OFFICEHOLDER_ID,
          person_id: SMOKE_PERSON_ID,
          person_name: SMOKE_OFFICE_OFFICEHOLDER_NAME,
          holder_status: "elected",
          electoral_division_id: null,
          electoral_division_type: "state",
          electoral_division_state: "NC",
          valid_period_lower: "2021-01-03",
          valid_period_upper: null,
          date_precision: "day" as const,
          is_active: true,
          term_ended: false
        }
      ],
      recent_contests: [
        {
          contest_id: SMOKE_CONTEST_ID,
          contest_name: SMOKE_CONTEST_NAME,
          election_date: "2026-11-03",
          election_type: "general" as const,
          filing_deadline: "2026-06-15",
          electoral_division_id: null,
          electoral_division_type: "state",
          electoral_division_state: "NC",
          is_partisan: true,
          candidate_list_incomplete: false
        }
      ],
      selected_electoral_division_id: null,
      selected_electoral_division_type: "state",
      selected_electoral_division_state: "NC",
      incomplete_data_states: [],
      sources: [
        {
          domain: "civic",
          jurisdiction: "federal/us",
          data_source_name: "Civic Records",
          data_source_url: "https://example.org/civic",
          source_record_key: "office-1",
          record_url: "https://example.org/office-1",
          pull_date: "2026-03-19T00:00:00Z"
        }
      ]
    }
  },
  officeEmpty: {
    id: SMOKE_EMPTY_OFFICE_ID,
    detail: {
      id: SMOKE_EMPTY_OFFICE_ID,
      name: SMOKE_EMPTY_OFFICE_NAME,
      office_level: "state",
      title: "State Auditor",
      jurisdiction_id: null,
      state: "NC",
      is_elected: true,
      number_of_seats: 1,
      current_officeholders: [],
      current_holder_card: null,
      officeholding_timeline: [],
      recent_contests: [],
      selected_electoral_division_id: null,
      selected_electoral_division_type: null,
      selected_electoral_division_state: null,
      incomplete_data_states: ["no_officeholder"],
      sources: []
    }
  },
  contest: {
    id: SMOKE_CONTEST_ID,
    detail: {
      id: SMOKE_CONTEST_ID,
      name: SMOKE_CONTEST_NAME,
      election_date: "2026-11-03",
      election_type: "general" as const,
      office_id: SMOKE_OFFICE_ID,
      electoral_division_id: null,
      number_of_seats: 1,
      filing_deadline: "2026-06-15",
      is_partisan: true,
      candidate_list_incomplete: false,
      result_winner_candidacy_id: SMOKE_CANDIDACY_ID,
      result_winner_person_id: SMOKE_PERSON_ID,
      result_winner_person_name: SMOKE_CANDIDACY_PERSON_NAME,
      candidacies: [
        {
          candidacy_id: SMOKE_CANDIDACY_ID,
          person_id: SMOKE_PERSON_ID,
          person_name: SMOKE_CANDIDACY_PERSON_NAME,
          party: "DEM",
          status: "filed",
          incumbent_challenge: "I"
        }
      ],
      sources: [
        {
          domain: "civic",
          jurisdiction: "federal/us",
          data_source_name: "Civic Records",
          data_source_url: "https://example.org/civic",
          source_record_key: "contest-1",
          record_url: "https://example.org/contest-1",
          pull_date: "2026-03-19T00:00:00Z"
        }
      ]
    }
  },
  candidacy: {
    id: SMOKE_CANDIDACY_ID,
    detail: {
      id: SMOKE_CANDIDACY_ID,
      person_id: SMOKE_PERSON_ID,
      person_name: SMOKE_CANDIDACY_PERSON_NAME,
      contest_id: SMOKE_CONTEST_ID,
      party: "DEM",
      filing_date: "2026-01-15",
      status: "filed",
      incumbent_challenge: "I",
      candidate_number: null,
      sources: [
        {
          domain: "civic",
          jurisdiction: "federal/us",
          data_source_name: "Civic Records",
          data_source_url: "https://example.org/civic",
          source_record_key: "candidacy-1",
          record_url: "https://example.org/candidacy-1",
          pull_date: "2026-03-19T00:00:00Z"
        }
      ]
    }
  },
  officeholding: {
    id: SMOKE_OFFICEHOLDING_ID,
    detail: {
      id: SMOKE_OFFICEHOLDING_ID,
      person_id: SMOKE_PERSON_ID,
      person_name: SMOKE_OFFICEHOLDING_PERSON_NAME,
      office_id: SMOKE_OFFICE_ID,
      electoral_division_id: null,
      holder_status: "elected" as const,
      valid_period_lower: "2021-01-03",
      valid_period_upper: null,
      date_precision: "day" as const,
      sources: [
        {
          domain: "civic",
          jurisdiction: "federal/us",
          data_source_name: "Civic Records",
          data_source_url: "https://example.org/civic",
          source_record_key: "officeholding-1",
          record_url: "https://example.org/officeholding-1",
          pull_date: "2026-03-19T00:00:00Z"
        }
      ]
    }
  },
  landingMap: {
    geometry: {
      type: "FeatureCollection" as const,
      features: [
        {
          type: "Feature" as const,
          geometry: {
            type: "Polygon" as const,
            coordinates: [
              [
                [-84, 34],
                [-75, 34],
                [-75, 36.5],
                [-84, 36.5],
                [-84, 34]
              ]
            ]
          },
          properties: {
            state: "NC",
            name: "North Carolina",
            division_type: "state",
            boundary_year: 2020
          }
        },
        {
          type: "Feature" as const,
          geometry: {
            type: "Polygon" as const,
            coordinates: [
              [
                [-94, 33],
                [-89, 33],
                [-89, 35],
                [-94, 35],
                [-94, 33]
              ]
            ]
          },
          properties: {
            state: "AR",
            name: "Arkansas",
            division_type: "state",
            boundary_year: 2020
          }
        },
        {
          type: "Feature" as const,
          geometry: {
            type: "Polygon" as const,
            coordinates: [
              [
                [-97, 43],
                [-90, 43],
                [-90, 49],
                [-97, 49],
                [-97, 43]
              ]
            ]
          },
          properties: {
            state: "MN",
            name: "Minnesota",
            division_type: "state",
            boundary_year: 2020
          }
        },
        {
          type: "Feature" as const,
          geometry: {
            type: "Polygon" as const,
            coordinates: [
              [
                [-85, 30],
                [-80, 30],
                [-80, 35],
                [-85, 35],
                [-85, 30]
              ]
            ]
          },
          properties: {
            state: "LA",
            name: "Louisiana",
            division_type: "state",
            boundary_year: 2020
          }
        }
      ]
    },
    summaries: [
      {
        state_code: "NC",
        total_raised: "1234.56",
        total_spent: "1000.00",
        net: "234.56",
        committee_count: 3,
        transaction_count: 12,
        federal_candidate_count: 2,
        ie_support_total: null,
        ie_oppose_total: null,
        ie_support_count: null,
        ie_oppose_count: null,
        coverage_tier: "launch-support candidate" as const,
        support_status: "supported" as const,
        supported: true,
        warning_text: null,
        data_through: "2026-04-20T00:00:00Z"
      },
      {
        state_code: "AR",
        total_raised: "0",
        total_spent: "0",
        net: "0",
        committee_count: 0,
        transaction_count: 0,
        federal_candidate_count: 0,
        ie_support_total: null,
        ie_oppose_total: null,
        ie_support_count: null,
        ie_oppose_count: null,
        coverage_tier: null,
        support_status: "unsupported" as const,
        supported: false,
        warning_text: null,
        data_through: null
      },
      {
        state_code: "MN",
        total_raised: "500.00",
        total_spent: "400.00",
        net: "100.00",
        committee_count: 1,
        transaction_count: 4,
        federal_candidate_count: 1,
        ie_support_total: null,
        ie_oppose_total: null,
        ie_support_count: null,
        ie_oppose_count: null,
        coverage_tier: "freshness-limited" as const,
        support_status: "warning" as const,
        supported: false,
        warning_text: "Quarterly bulk only; refresh cadence below weekly target.",
        data_through: "2026-03-30T00:00:00Z"
      },
      {
        state_code: "LA",
        total_raised: "400.00",
        total_spent: "25.00",
        net: "375.00",
        committee_count: 1,
        transaction_count: 3,
        federal_candidate_count: 0,
        ie_support_total: null,
        ie_oppose_total: null,
        ie_support_count: null,
        ie_oppose_count: null,
        coverage_tier: "launch-support candidate" as const,
        support_status: "supported" as const,
        supported: true,
        warning_text: SMOKE_STATE_DETAIL_IE_CAVEAT,
        data_through: "2026-03-27T12:00:00Z"
      }
    ]
  },
  stateDetails: {
    NC: {
      state_code: "NC",
      total_raised: "390.00",
      total_spent: "130.00",
      net: "260.00",
      committee_count: 2,
      transaction_count: 6,
      federal_candidate_count: 2,
      ie_support_total: "20.00",
      ie_oppose_total: "80.00",
      ie_support_count: 1,
      ie_oppose_count: 1,
      coverage_tier: "launch-support candidate" as const,
      support_status: "supported" as const,
      supported: true,
      warning_text: null,
      data_through: "2026-03-26T12:00:00Z",
      sources: [
        {
          domain: "campaign_finance",
          jurisdiction: "state/NC",
          data_source_name: "NC State Campaign Finance",
          data_source_url: "https://cf.ncsbe.gov",
          source_record_key: "nc-state-summary-2026-03-26",
          record_url: "https://cf.ncsbe.gov/CFOrgLkup/",
          pull_date: "2026-03-26T12:00:00Z"
        }
      ],
      top_candidates: [
        {
          candidate_id: SMOKE_CANDIDATE_ID,
          candidate_name: SMOKE_STATE_DETAIL_TOP_CANDIDATE_NAME,
          total_raised: SMOKE_STATE_DETAIL_TOP_CANDIDATE_TOTAL.replace("$", "").replace(",", "")
        }
      ],
      top_committees: [
        {
          committee_id: SMOKE_COMMITTEE_ID,
          committee_name: SMOKE_STATE_DETAIL_TOP_COMMITTEE_NAME,
          total_raised: SMOKE_STATE_DETAIL_TOP_COMMITTEE_TOTAL.replace("$", "").replace(",", "")
        }
      ],
      top_ie_spenders: [
        {
          committee_id: SMOKE_IE_COMMITTEE_A_ID,
          committee_name: SMOKE_STATE_DETAIL_TOP_IE_SPENDER_NAME,
          total_amount: SMOKE_STATE_DETAIL_TOP_IE_SPENDER_TOTAL.replace("$", "").replace(",", "")
        }
      ]
    },
    AR: {
      state_code: "AR",
      total_raised: "0",
      total_spent: "0",
      net: "0",
      committee_count: 0,
      transaction_count: 0,
      federal_candidate_count: 0,
      ie_support_total: null,
      ie_oppose_total: null,
      ie_support_count: null,
      ie_oppose_count: null,
      coverage_tier: null,
      support_status: "unsupported" as const,
      supported: false,
      warning_text: null,
      data_through: null,
      sources: [],
      top_candidates: [],
      top_committees: [],
      top_ie_spenders: []
    },
    MN: {
      state_code: "MN",
      total_raised: "500.00",
      total_spent: "400.00",
      net: "100.00",
      committee_count: 1,
      transaction_count: 4,
      federal_candidate_count: 1,
      ie_support_total: null,
      ie_oppose_total: null,
      ie_support_count: null,
      ie_oppose_count: null,
      coverage_tier: "freshness-limited" as const,
      support_status: "warning" as const,
      supported: false,
      warning_text: "Quarterly bulk only; refresh cadence below weekly target.",
      data_through: "2026-03-30T00:00:00Z",
      sources: [],
      top_candidates: [],
      top_committees: [],
      top_ie_spenders: []
    },
    LA: {
      state_code: "LA",
      total_raised: "400.00",
      total_spent: "25.00",
      net: "375.00",
      committee_count: 1,
      transaction_count: 3,
      federal_candidate_count: 0,
      ie_support_total: null,
      ie_oppose_total: null,
      ie_support_count: null,
      ie_oppose_count: null,
      coverage_tier: "launch-support candidate" as const,
      support_status: "supported" as const,
      supported: true,
      warning_text: SMOKE_STATE_DETAIL_IE_CAVEAT,
      data_through: "2026-03-27T12:00:00Z",
      sources: [],
      top_candidates: [],
      top_committees: [],
      top_ie_spenders: []
    }
  }
} as const;
