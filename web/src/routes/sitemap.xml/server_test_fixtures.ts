import type {
  CandidateListResponse,
  CommitteeListResponse
} from "$lib/campaign-finance-detail/contract";
import type {
  CongressMemberSummary,
  UpcomingElectionTimelineEntry
} from "$lib/civic-detail/contract";

export const CANDIDATE_PAGE_1: CandidateListResponse = {
  items: [
    {
      id: "11111111-1111-4111-8111-111111111111",
      fec_candidate_id: "H0NC01001",
      name: "Rich Candidate",
      party: "DEM",
      office: "H",
      state: "NC",
      district: "01",
      slug: "pat-candidate-2026",
      slug_is_unique: true,
      identity_is_safe: true,
      has_official_total: true
    },
    {
      id: "22222222-2222-4222-8222-222222222222",
      fec_candidate_id: "S0GA02002",
      name: "Duplicate Name",
      party: "REP",
      office: "S",
      state: "GA",
      district: null,
      slug: "duplicate-name",
      slug_is_unique: false,
      identity_is_safe: true,
      has_official_total: true
    },
    {
      id: "55555555-5555-4555-8555-555555555555",
      fec_candidate_id: "H0TX05005",
      name: "212 N HALF  W. JOHN, RODNEY HOWARD MR.",
      party: "DEM",
      office: "H",
      state: "TX",
      district: "05",
      slug: "212-n-half-w-john-rodney-howard-mr",
      slug_is_unique: true,
      identity_is_safe: false,
      has_official_total: true
    }
  ],
  has_next: true,
  offset: 0,
  limit: 200
};

export const CANDIDATE_PAGE_2: CandidateListResponse = {
  items: [
    {
      id: "33333333-3333-4333-8333-333333333333",
      fec_candidate_id: "P0US00003",
      name: "Out-of-Cycle Official Total Candidate",
      party: "IND",
      office: "P",
      state: "US",
      district: null,
      slug: "solo-runner-2026",
      slug_is_unique: true,
      identity_is_safe: true,
      has_official_total: true
    },
    {
      id: "66666666-6666-4666-8666-666666666666",
      fec_candidate_id: "H0NC06006",
      name: "!!!",
      party: "IND",
      office: "H",
      state: "NC",
      district: "06",
      slug: "",
      slug_is_unique: true,
      identity_is_safe: false,
      has_official_total: false
    },
    {
      id: "77777777-7777-4777-8777-777777777777",
      fec_candidate_id: "H0NC07007",
      name: "Thin Canonical Candidate",
      party: "IND",
      office: "H",
      state: "NC",
      district: "07",
      slug: "thin-canonical-candidate",
      slug_is_unique: true,
      identity_is_safe: true,
      has_official_total: false
    }
  ],
  has_next: false,
  offset: 200,
  limit: 200
};

export const COMMITTEE_PAGE_1: CommitteeListResponse = {
  items: [
    {
      id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
      fec_committee_id: "C00000001",
      name: "Citizens for Civibus",
      committee_type: "O",
      party: "DEM",
      state: "NC",
      slug: "citizens-for-civibus-2026",
      slug_is_unique: true
    }
  ],
  has_next: true,
  offset: 0,
  limit: 200
};

export const COMMITTEE_PAGE_2: CommitteeListResponse = {
  items: [
    {
      id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
      fec_committee_id: "C00000002",
      name: "Future Forward Civibus",
      committee_type: "P",
      party: null,
      state: "GA",
      slug: "future-forward-civibus-2026",
      slug_is_unique: true
    }
  ],
  has_next: true,
  offset: 200,
  limit: 200
};

export const COMMITTEE_PAGE_3: CommitteeListResponse = {
  items: [
    {
      id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
      fec_committee_id: "C00000003",
      name: "Local Civibus Committee",
      committee_type: "N",
      party: "IND",
      state: "TX",
      slug: "local-civibus-committee",
      slug_is_unique: false
    }
  ],
  has_next: false,
  offset: 400,
  limit: 200
};

export const TERMINAL_COMMITTEE_PAGE: CommitteeListResponse = {
  ...COMMITTEE_PAGE_1,
  has_next: false
};

// Contests are populated here on purpose: they are the source for the contest
// sitemap shard, and an all-empty fixture would let a shard that emits nothing
// pass its own test.
export const UPCOMING_TIMELINE: UpcomingElectionTimelineEntry[] = [
  {
    date: "2026-11-03",
    contests: [
      {
        contest_id: "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa",
        office_id: "11111111-1111-4111-8111-111111111111",
        name: "North Carolina 4th Congressional District — 2026 General Election",
        election_type: "general",
        office_name: "us_house",
        office_level: "federal",
        state: "NC",
        jurisdiction_id: null,
        electoral_division_id: "dddddddd-1111-4111-8111-dddddddddddd",
        electoral_division_type: "congressional_district",
        electoral_division_state: "NC",
        district_number: "04",
        candidate_count: 3
      },
      {
        contest_id: "aaaaaaaa-2222-4222-8222-aaaaaaaaaaaa",
        office_id: "22222222-2222-4222-8222-222222222222",
        name: "Georgia U.S. Senate — 2026 General Election",
        election_type: "general",
        office_name: "us_senate",
        office_level: "federal",
        state: "GA",
        jurisdiction_id: null,
        electoral_division_id: null,
        electoral_division_type: null,
        electoral_division_state: null,
        district_number: null,
        candidate_count: 5
      }
    ]
  },
  {
    date: "2027-03-09",
    contests: [
      {
        contest_id: "aaaaaaaa-3333-4333-8333-aaaaaaaaaaaa",
        office_id: "11111111-1111-4111-8111-111111111111",
        name: "Florida 1st Congressional District — 2027 General Election",
        election_type: "special",
        office_name: "us_house",
        office_level: "federal",
        state: "FL",
        jurisdiction_id: null,
        electoral_division_id: "dddddddd-3333-4333-8333-dddddddddddd",
        electoral_division_type: "congressional_district",
        electoral_division_state: "FL",
        district_number: "01",
        candidate_count: 2
      }
    ]
  }
];

export const CONGRESS_MEMBERS: CongressMemberSummary[] = [
  {
    person_id: "44444444-4444-4444-8444-444444444444",
    person_name: "Ada Representative",
    officeholding_id: "55555555-5555-4555-8555-555555555555",
    office_id: "66666666-6666-4666-8666-666666666666",
    office_name: "U.S. Representative for North Carolina's 4th congressional district",
    chamber: "House",
    state: "NC",
    district: "04",
    district_or_class: "04",
    party: "Democratic",
    portrait_source_image_url: null,
    person_detail_path: "/person/44444444-4444-4444-8444-444444444444"
  },
  {
    person_id: "77777777-7777-4777-8777-777777777777",
    person_name: "Ben Senator",
    officeholding_id: "88888888-8888-4888-8888-888888888888",
    office_id: "99999999-9999-4999-8999-999999999999",
    office_name: "U.S. Senator for Georgia",
    chamber: "Senate",
    state: "GA",
    district: null,
    district_or_class: "Class II",
    party: "Republican",
    portrait_source_image_url: null,
    person_detail_path: "/person/77777777-7777-4777-8777-777777777777"
  }
];
