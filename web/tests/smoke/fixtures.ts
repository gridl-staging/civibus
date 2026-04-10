export const SMOKE_API_HOST = "127.0.0.1";
export const SMOKE_API_PORT = 3999;
export const SMOKE_API_BASE_URL = `http://${SMOKE_API_HOST}:${SMOKE_API_PORT}`;

export const SMOKE_PERSON_ID = "11111111-1111-4111-8111-111111111111";
export const SMOKE_ORG_ID = "22222222-2222-4222-8222-222222222222";
export const SMOKE_FILING_ID = "33333333-3333-4333-8333-333333333333";
export const SMOKE_COMMITTEE_ID = "44444444-4444-4444-8444-444444444444";
export const SMOKE_CANDIDATE_ID = "55555555-5555-4555-8555-555555555555";
export const SMOKE_PROPERTY_ID = "66666666-6666-4666-8666-666666666666";
export const SMOKE_COMMITTEE_SLUG = "citizens-for-civibus";
export const SMOKE_CANDIDATE_SLUG = "pat-candidate";
export const SMOKE_COLLIDING_COMMITTEE_SLUG = "shared-committee";
export const SMOKE_COLLIDING_CANDIDATE_SLUG = "shared-candidate";
export const SMOKE_COLLIDING_COMMITTEE_ID = "77777777-7777-4777-8777-777777777777";
export const SMOKE_COLLIDING_CANDIDATE_ID = "88888888-8888-4888-8888-888888888888";
export const SMOKE_EMPTY_COMMITTEE_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
export const SMOKE_EMPTY_CANDIDATE_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
export const SMOKE_EMPTY_PROPERTY_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
export const SMOKE_OFFICE_ID = "ee111111-1111-4111-8111-111111111111";
export const SMOKE_EMPTY_OFFICE_ID = "ee222222-2222-4222-8222-222222222222";
export const SMOKE_OFFICE_OFFICEHOLDER_ID = "ff111111-1111-4111-8111-111111111111";

export const SMOKE_SEARCH_QUERY = "civ";
export const SMOKE_SEARCH_RESULT_NAME = "Civibus Action Org";
export const SMOKE_SEARCH_EMPTY_TITLE = "Search | Civibus";
export const SMOKE_SEARCH_EMPTY_DESCRIPTION =
  "Search people, organizations, committees, candidates, and offices across campaign-finance and civic records.";
export const SMOKE_SEARCH_TITLE = "civ (1 result) | Search | Civibus";
export const SMOKE_SEARCH_DESCRIPTION = '1 result for "civ" across Civibus records.';
export const SMOKE_HOME_TITLE = "Civibus | Public-records intelligence for journalists";
export const SMOKE_HOME_DESCRIPTION =
  "Investigate campaign-finance, civic office, and property records with source-linked evidence in Civibus search.";
export const SMOKE_HOME_HEADING = "Trace people, organizations, committees, and offices across jurisdictions.";
export const SMOKE_HOME_COVERAGE_HEADING = "Coverage at a glance";
export const SMOKE_HOME_COVERAGE_SUMMARY =
  "Coverage spans federal and state campaign-finance records, civic offices, and a property pilot. See methodology for current operational scope by jurisdiction.";
export const SMOKE_METHODOLOGY_TITLE = "Methodology | Civibus";
export const SMOKE_METHODOLOGY_DESCRIPTION =
  "Coverage scope, confidence labels, and source guidance for campaign-finance, civic office, and property records.";
export const SMOKE_METHODOLOGY_SECTION_HEADING = "Data freshness policy";
export const SMOKE_METHODOLOGY_SECTION_BODY =
  "Production support requires data that can be refreshed at least weekly near elections, with daily updates preferred. Sources that only publish annual or quarterly exports are not treated as fully launch-ready without a supplementary path.";
export const SMOKE_METHODOLOGY_CONFIDENCE_HEADING = "Entity resolution confidence labels";
export const SMOKE_SHELL_NAV_HOME = "Home";
export const SMOKE_SHELL_NAV_SEARCH = "Search";
export const SMOKE_SHELL_NAV_CANDIDATES = "Candidates";
export const SMOKE_SHELL_NAV_COMMITTEES = "Committees";
export const SMOKE_SHELL_NAV_METHODOLOGY = "Methodology";

export const SMOKE_PERSON_CANONICAL_NAME = "Jane Doe";
export const SMOKE_PERSON_RELATIONSHIP_NAME = "Q1 Filing";
export const SMOKE_PERSON_TITLE = "Jane Doe | Person | Civibus";
export const SMOKE_PERSON_DESCRIPTION =
  "Person profile with 1 identifier and source-linked records.";

export const SMOKE_ORG_CANONICAL_NAME = "Civibus Action Org";
export const SMOKE_ORG_RELATIONSHIP_NAME = "Org Filing 2026-Q1";
export const SMOKE_ORG_TITLE = "Civibus Action Org | Organization | Civibus";
export const SMOKE_ORG_DESCRIPTION =
  "Organization profile with 1 identifier and source-linked records.";

export const SMOKE_COMMITTEE_NAME = "Citizens for Civibus";
export const SMOKE_CANDIDATE_NAME = "Pat Candidate";
export const SMOKE_COMMITTEE_TITLE = "Citizens for Civibus | Committee | Civibus";
export const SMOKE_COMMITTEE_DESCRIPTION = "Committee profile with 1 recent transaction.";
export const SMOKE_COMMITTEES_TITLE = "Committees | Civibus";
export const SMOKE_COMMITTEES_DESCRIPTION = "Campaign-finance committees with server-rendered pagination.";
export const SMOKE_COMMITTEE_TOTAL_RAISED = "$125.00";
export const SMOKE_COMMITTEE_TOTAL_SPENT = "$40.00";
export const SMOKE_COMMITTEE_NET_TOTAL = "$85.00";
export const SMOKE_COMMITTEE_FILING_ROW_LABEL = "Q1 Filing (F3N)";
export const SMOKE_COMMITTEE_FILING_SUMMARY_EMPTY_STATE = "No filing-period fundraising data available.";
export const SMOKE_COMMITTEE_ORG_LINK_TEXT = `Organization record (${SMOKE_ORG_ID})`;
export const SMOKE_COMMITTEE_CONTRIBUTOR_PERSON_LINK_TEXT = "View contributor person record";
export const SMOKE_COMMITTEE_CONTRIBUTOR_ORG_LINK_TEXT = "View contributor organization record";
export const SMOKE_COMMITTEE_RECIPIENT_CANDIDATE_LINK_TEXT = "View recipient candidate record";
export const SMOKE_COMMITTEE_RECIPIENT_COMMITTEE_LINK_TEXT = "View recipient committee record";
export const SMOKE_CANDIDATE_TITLE = "Pat Candidate | Candidate | Civibus";
export const SMOKE_CANDIDATE_DESCRIPTION = "Candidate profile from campaign-finance records.";
export const SMOKE_CANDIDATES_TITLE = "Candidates | Civibus";
export const SMOKE_CANDIDATES_DESCRIPTION = "Campaign-finance candidates with server-rendered pagination.";
export const SMOKE_CANDIDATE_TOTAL_RAISED = "$250.00";
export const SMOKE_CANDIDATE_TOTAL_SPENT = "$80.00";
export const SMOKE_CANDIDATE_NET_TOTAL = "$170.00";
export const SMOKE_CANDIDATE_DATA_THROUGH = "2026-03-19";
export const SMOKE_CANDIDATE_PERSON_LINK_TEXT = `Person record (${SMOKE_PERSON_ID})`;
export const SMOKE_CANDIDATE_COMMITTEE_LINK_TEXT = `Committee record (${SMOKE_COMMITTEE_ID})`;
export const SMOKE_EMPTY_COMMITTEE_TITLE = "Committee Empty | Committee | Civibus";
export const SMOKE_EMPTY_COMMITTEE_DESCRIPTION = "Committee profile with 0 recent transactions.";
export const SMOKE_EMPTY_CANDIDATE_TITLE = "Candidate Empty | Candidate | Civibus";
export const SMOKE_EMPTY_CANDIDATE_DESCRIPTION = "Candidate profile from campaign-finance records.";

export const SMOKE_IE_COMMITTEE_A_ID = "dd111111-1111-4111-8111-111111111111";
export const SMOKE_IE_COMMITTEE_A_NAME = "Super PAC Alpha";
export const SMOKE_IE_TRANSACTION_DISSEMINATION_DATE = "2026-03-20";
export const SMOKE_CANDIDATE_SUPPORT_TOTAL = "$15,000.00";
export const SMOKE_CANDIDATE_OPPOSE_TOTAL = "$8,500.00";
export const SMOKE_CANDIDATE_OUTSIDE_SPENDING_EMPTY =
  "Outside-spending data is not yet available for this candidate. Coverage may be incomplete.";

export const SMOKE_PROPERTY_TITLE = "123 MAIN ST";
export const SMOKE_PROPERTY_GEOMETRY_PLACEHOLDER_MESSAGE =
  "Map data unavailable: this parcel response does not include coordinates or boundary geometry.";
export const SMOKE_PROPERTY_PAGE_TITLE = "123 MAIN ST | Property | Civibus";
export const SMOKE_PROPERTY_DESCRIPTION = "Property profile with 1 ownership record and 1 assessment.";
export const SMOKE_EMPTY_PROPERTY_TITLE = "999 EMPTY RD";
export const SMOKE_EMPTY_PROPERTY_PAGE_TITLE = "999 EMPTY RD | Property | Civibus";
export const SMOKE_EMPTY_PROPERTY_DESCRIPTION = "Property profile with 0 ownership records and 0 assessments.";

export const SMOKE_CONTEST_ID = "ab111111-1111-4111-8111-111111111111";
export const SMOKE_CANDIDACY_ID = "ac111111-1111-4111-8111-111111111111";
export const SMOKE_OFFICEHOLDING_ID = "ad111111-1111-4111-8111-111111111111";

export const SMOKE_CONTEST_NAME = "2026 NC Senate General";
export const SMOKE_CONTEST_TITLE = "2026 NC Senate General | Contest | Civibus";
export const SMOKE_CONTEST_DESCRIPTION = "Contest profile with 1 candidacy.";

export const SMOKE_CANDIDACY_PERSON_NAME = "Jane Doe";
export const SMOKE_CANDIDACY_TITLE = "Jane Doe | Candidacy | Civibus";
export const SMOKE_CANDIDACY_DESCRIPTION = "Candidacy profile for Jane Doe.";

export const SMOKE_OFFICEHOLDING_PERSON_NAME = "Jane Doe";
export const SMOKE_OFFICEHOLDING_TITLE = "Jane Doe | Officeholding | Civibus";
export const SMOKE_OFFICEHOLDING_DESCRIPTION = "Officeholding profile for Jane Doe.";

export const SMOKE_OFFICE_NAME = "U.S. Senator, North Carolina";
export const SMOKE_OFFICE_TITLE = "U.S. Senator, North Carolina | Office | Civibus";
export const SMOKE_OFFICE_DESCRIPTION = "Office profile with 1 current officeholder.";
export const SMOKE_OFFICE_OFFICEHOLDER_NAME = "Jane Doe";
export const SMOKE_EMPTY_OFFICE_NAME = "State Auditor, North Carolina";
export const SMOKE_EMPTY_OFFICE_TITLE = "State Auditor, North Carolina | Office | Civibus";
export const SMOKE_EMPTY_OFFICE_DESCRIPTION = "Office profile with 0 current officeholders.";
export const SMOKE_OFFICE_INCOMPLETE_DATA_WARNING = "Current officeholder data is incomplete for this office.";

export const SMOKE_PROVENANCE_SOURCE_NAME = "FEC (campaign_finance/federal/fec)";
export const SMOKE_PROPERTY_PROVENANCE_SOURCE_NAME = "Durham County (property/us/nc/durham)";
export const SMOKE_PROVENANCE_LAST_PULLED = /^Last pulled: (?:today|\d+ days? ago) \(\d{4}-\d{2}-\d{2}\)$/;
export const SMOKE_PROVENANCE_SOURCE_KEY = "Source record ID: person-1";
export const SMOKE_PROPERTY_PROVENANCE_SOURCE_KEY = "Source record ID: parcel-1";
export const SMOKE_TRUST_ADVISORY = "Review source records before publication.";
export const SMOKE_TRUST_EMPTY_MESSAGE = "No source records are available for this detail yet.";
export const SMOKE_TRUST_LAST_PULLED_UNAVAILABLE = "Last pulled: unavailable";
export const SMOKE_COMMITTEE_EMPTY_STATE = "No recent committee transactions found.";
export const SMOKE_GRAPH_EMPTY_STATE = "No graph relationships are available yet. Linked records will appear after future ingests.";
export const SMOKE_ER_EMPTY_STATE = "No entity-resolution matches are available yet. Check back after the next ER refresh.";
export const SMOKE_TECHNICAL_DISCLOSURE_SUMMARY = "Entity-resolution and graph internals";
export const SMOKE_PROPERTY_EMPTY_OWNERSHIP_STATE = "No ownership history is available yet. Check back after the next county refresh.";
export const SMOKE_PROPERTY_EMPTY_ASSESSMENT_STATE = "No assessment history is available yet. Check back after the next county refresh.";
export const SMOKE_OFFICEHOLDER_EMPTY_STATE = "No current officeholders are linked yet. Check back after the next records refresh.";

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
      identifiers: {
        fec_candidate_id: "H0NC99999"
      },
      primary_address_id: null,
      er_cluster_id: null,
      er_confidence: 0.97,
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
    matches: [],
    relationships: {
      entity_type: "person",
      entity_id: SMOKE_PERSON_ID,
      neighbors: [
        {
          entity_type: "filing",
          entity_id: SMOKE_FILING_ID,
          name: SMOKE_PERSON_RELATIONSHIP_NAME,
          relationship_type: "FILED",
          direction: "inbound"
        }
      ],
      total_count: 1
    }
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
    matches: [],
    relationships: {
      entity_type: "org",
      entity_id: SMOKE_ORG_ID,
      neighbors: [
        {
          entity_type: "filing",
          entity_id: SMOKE_FILING_ID,
          name: SMOKE_ORG_RELATIONSHIP_NAME,
          relationship_type: "FILED",
          direction: "inbound"
        }
      ],
      total_count: 1
    }
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
      sources: [
        {
          domain: "campaign_finance",
          jurisdiction: "federal/fec",
          data_source_name: "FEC",
          data_source_url: "https://www.fec.gov",
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
      total_raised: "125.00",
      total_spent: "40.00",
      net: "85.00",
      transaction_count: 3,
      jurisdiction: "federal/fec",
      data_through: "2026-03-19T00:00:00Z"
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
          transaction_count: 3
        }
      ]
    }
  },
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
      data_through: null
    },
    filingBreakdown: {
      committee_id: SMOKE_EMPTY_COMMITTEE_ID,
      committee_name: "Committee Empty",
      filings: []
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
          jurisdiction: "federal/fec",
          data_source_name: "FEC",
          data_source_url: "https://www.fec.gov",
          source_record_key: "candidate-1",
          record_url: "https://example.org/candidate-1",
          pull_date: "2026-03-19T00:00:00Z"
        }
      ]
    },
    summary: {
      candidate_id: SMOKE_CANDIDATE_ID,
      candidate_name: SMOKE_CANDIDATE_NAME,
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
    },
    ieTransactions: [
      {
        id: "dd222222-2222-4222-8222-222222222222",
        filing_id: null,
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
      ]
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
  candidateList: {
    items: [
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
      },
      {
        id: SMOKE_EMPTY_CANDIDATE_ID,
        fec_candidate_id: "H0NC99998",
        name: "Candidate Empty",
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
  }
} as const;
