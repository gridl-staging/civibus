import type { CongressMemberMoneySummary, CongressMemberSummary } from "./contract";
import {
  buildCongressCompareHref,
  buildCongressDirectory,
  buildCongressMemberRow,
  filterCongressMembers,
  getCongressMoneyMetric,
  getCongressMoneySourceHref
} from "./congress-directory";
import { describe, expect, it } from "vitest";

const MEMBERS: CongressMemberSummary[] = [
  {
    person_id: "11111111-1111-4111-8111-111111111111",
    person_name: "Jane A. Representative",
    officeholding_id: "44444444-4444-4444-8444-444444444444",
    office_id: "33333333-3333-4333-8333-333333333333",
    office_name: "U.S. Representative for North Carolina's 1st congressional district",
    chamber: "House",
    state: "NC",
    district: "01",
    district_or_class: "01",
    party: "Democratic",
    portrait_source_image_url: "https://example.test/jane.jpg",
    person_detail_path: "/person/11111111-1111-4111-8111-111111111111"
  },
  {
    person_id: "22222222-2222-4222-8222-222222222222",
    person_name: "Alex Senator",
    officeholding_id: "55555555-5555-4555-8555-555555555555",
    office_id: "66666666-6666-4666-8666-666666666666",
    office_name: "U.S. Senator from Georgia",
    chamber: "Senate",
    state: "GA",
    district: null,
    district_or_class: "Class II",
    party: "Republican",
    portrait_source_image_url: null,
    person_detail_path: "/person/22222222-2222-4222-8222-222222222222"
  },
  {
    person_id: "77777777-7777-4777-8777-777777777777",
    person_name: "Maria Delegate",
    officeholding_id: "88888888-8888-4888-8888-888888888888",
    office_id: "99999999-9999-4999-8999-999999999999",
    office_name: "Delegate to the U.S. House from Puerto Rico",
    chamber: "House",
    state: "PR",
    district: null,
    district_or_class: "Delegate",
    party: "Democratic",
    portrait_source_image_url: null,
    person_detail_path: "/person/77777777-7777-4777-8777-777777777777"
  },
  {
    person_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    person_name: "Sam President",
    officeholding_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    office_id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
    office_name: "President of the United States",
    chamber: "Executive",
    state: "US",
    district: null,
    district_or_class: null,
    party: "Independent",
    portrait_source_image_url: null,
    person_detail_path: "/person/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
  }
];

const MONEY_SUMMARIES: CongressMemberMoneySummary[] = [
  {
    person_id: "11111111-1111-4111-8111-111111111111",
    person_name: "Jane A. Representative",
    has_fec_money: true,
    candidate_id: "H6NC01001",
    total_raised: "300.00",
    total_spent: "200.00",
    net: "100.00",
    cash_on_hand: "500.00",
    summary_source: "fec_candidate_totals",
    ie_support_total: "1000.00",
    ie_oppose_total: "20.00",
    ie_support_count: 3,
    ie_oppose_count: 1,
    sources: [
      {
        domain: "fec",
        jurisdiction: "US",
        data_source_name: "FEC candidate summary",
        data_source_url: "https://api.open.fec.gov/developers/",
        source_record_key: "H6NC01001",
        record_url: "https://www.fec.gov/data/candidate/H6NC01001/",
        pull_date: "2026-07-16"
      }
    ]
  },
  {
    person_id: "22222222-2222-4222-8222-222222222222",
    person_name: "Alex Senator",
    has_fec_money: true,
    candidate_id: "S6GA00001",
    total_raised: "300.00",
    total_spent: "250.00",
    net: "50.00",
    cash_on_hand: null,
    summary_source: "fec_candidate_totals",
    ie_support_total: "10.00",
    ie_oppose_total: "900.00",
    ie_support_count: 1,
    ie_oppose_count: 4,
    sources: []
  },
  {
    person_id: "77777777-7777-4777-8777-777777777777",
    person_name: "Maria Delegate",
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
];

describe("Congress directory presentation", () => {
  it("maps exact API fields to row view models and passes through person_detail_path", () => {
    const row = buildCongressMemberRow(MEMBERS[0]!);

    expect(row).toEqual({
      id: "11111111-1111-4111-8111-111111111111",
      personName: "Jane A. Representative",
      personHref: "/person/11111111-1111-4111-8111-111111111111",
      chamber: "House",
      stateOrTerritory: "NC",
      contextLabel: "District 01",
      party: "Democratic",
      contextLine: "House · NC · District 01 · Democratic",
      portrait: {
        status: "available",
        rights_status: "usable",
        source_image_url: "https://example.test/jane.jpg",
        mime_type: null,
        width_px: null,
        height_px: null
      },
      hasFecMoney: false,
      totalRaised: null,
      outsideSupport: null,
      outsideAgainst: null,
      cashOnHand: null,
      moneySources: []
    });
  });

  it("returns portrait data for image rows and initials fallback data for missing portraits", () => {
    const imageRow = buildCongressMemberRow(MEMBERS[0]!);
    const fallbackRow = buildCongressMemberRow(MEMBERS[1]!);

    expect(imageRow.portrait?.source_image_url).toBe("https://example.test/jane.jpg");
    expect(fallbackRow.portrait).toBeNull();
    expect(fallbackRow.personName).toBe("Alex Senator");
    expect(fallbackRow.id).toBe("22222222-2222-4222-8222-222222222222");
  });

  it("formats district, class, delegate, and executive context labels", () => {
    expect(MEMBERS.map((member) => buildCongressMemberRow(member)).map((row) => row.contextLabel)).toEqual([
      "District 01",
      "Class II",
      "Delegate",
      "President of the United States"
    ]);
  });

  it("treats empty and whitespace-only search as no search constraint", () => {
    expect(filterCongressMembers(MEMBERS, { search: "   ", chamber: "", state: "", party: "" }).map((row) => row.personName)).toEqual([
      "Jane A. Representative",
      "Alex Senator",
      "Maria Delegate",
      "Sam President"
    ]);
  });

  it("matches names case-insensitively", () => {
    const rows = filterCongressMembers(MEMBERS, {
      search: "jane",
      chamber: "",
      state: "",
      party: ""
    });

    expect(rows.map((row) => row.personName)).toEqual(["Jane A. Representative"]);
  });

  it("matches normalized names with punctuation and extra spaces removed", () => {
    const rows = filterCongressMembers(MEMBERS, {
      search: "JaneARepresentative",
      chamber: "",
      state: "",
      party: ""
    });

    expect(rows.map((row) => row.personName)).toEqual(["Jane A. Representative"]);
  });

  it("derives chamber, state-or-territory, and party options from loaded members", () => {
    const directory = buildCongressDirectory(MEMBERS, { search: "", chamber: "", state: "", party: "" });

    expect(directory.chamberOptions).toEqual([
      { value: "Executive", label: "Executive" },
      { value: "House", label: "House" },
      { value: "Senate", label: "Senate" }
    ]);
    expect(directory.stateOrTerritoryOptions).toEqual([
      { value: "GA", label: "GA" },
      { value: "NC", label: "NC" },
      { value: "PR", label: "PR" },
      { value: "US", label: "US" }
    ]);
    expect(directory.partyOptions).toEqual([
      { value: "Democratic", label: "Democratic" },
      { value: "Independent", label: "Independent" },
      { value: "Republican", label: "Republican" }
    ]);
  });

  it("applies combined chamber, state-or-territory, and party filters with hand-calculated results", () => {
    const rows = filterCongressMembers(MEMBERS, {
      search: "",
      chamber: "House",
      state: "PR",
      party: "Democratic"
    });

    expect(rows.map((row) => row.personName)).toEqual(["Maria Delegate"]);
  });

  it("treats invalid chamber, state, and party params as unselected filters", () => {
    const directory = buildCongressDirectory(MEMBERS, {
      search: "",
      chamber: "Invalid",
      state: "ZZ",
      party: "Unknown"
    });

    expect(directory.activeFilters).toEqual({ search: "", chamber: "", state: "", party: "" });
    expect(directory.rows).toHaveLength(4);
  });

  it("maps fetched money summaries by person and leaves no-money rows with null usable money", () => {
    const directory = buildCongressDirectory(MEMBERS, {}, MONEY_SUMMARIES);

    expect(directory.rows.find((row) => row.personName === "Jane A. Representative")).toMatchObject({
      hasFecMoney: true,
      totalRaised: "300.00",
      outsideSupport: "1000.00",
      outsideAgainst: "20.00",
      cashOnHand: "500.00",
      moneySources: MONEY_SUMMARIES[0]!.sources
    });
    expect(directory.rows.find((row) => row.personName === "Maria Delegate")).toMatchObject({
      hasFecMoney: false,
      totalRaised: null,
      outsideSupport: null,
      outsideAgainst: null,
      cashOnHand: null,
      moneySources: []
    });
    expect(directory.rows.find((row) => row.personName === "Sam President")).toMatchObject({
      hasFecMoney: false,
      totalRaised: null,
      outsideSupport: null,
      outsideAgainst: null,
      cashOnHand: null,
      moneySources: []
    });
  });

  it.each([
    ["total_raised", ["Alex Senator", "Jane A. Representative", "Maria Delegate", "Sam President"]],
    ["outside_against", ["Alex Senator", "Jane A. Representative", "Maria Delegate", "Sam President"]],
    ["outside_support", ["Jane A. Representative", "Alex Senator", "Maria Delegate", "Sam President"]],
    ["cash_on_hand", ["Jane A. Representative", "Alex Senator", "Maria Delegate", "Sam President"]]
  ])("sorts by %s descending with ties and null money last", (sort, expectedNames) => {
    const directory = buildCongressDirectory(MEMBERS, {}, MONEY_SUMMARIES, sort);

    expect(directory.activeSort).toBe(sort);
    expect(directory.rows.map((row) => row.personName)).toEqual(expectedNames);
  });

  it("falls back to total_raised when the sort param is invalid", () => {
    const directory = buildCongressDirectory(MEMBERS, {}, MONEY_SUMMARIES, "not_a_sort");

    expect(directory.activeSort).toBe("total_raised");
    expect(directory.rows.map((row) => row.personName)).toEqual([
      "Alex Senator",
      "Jane A. Representative",
      "Maria Delegate",
      "Sam President"
    ]);
  });

  it("returns null money fields and the default active sort when no money summaries are fetched", () => {
    const directory = buildCongressDirectory(MEMBERS, {}, []);

    expect(directory.activeSort).toBe("total_raised");
    expect(directory.rows).toHaveLength(4);
    expect(directory.rows.every((row) => row.hasFecMoney === false)).toBe(true);
    expect(directory.rows.every((row) => row.totalRaised === null)).toBe(true);
    expect(directory.rows.every((row) => row.moneySources.length === 0)).toBe(true);
  });

  it("keeps search, chamber, state, and party filters unchanged when money is present", () => {
    const directory = buildCongressDirectory(
      MEMBERS,
      {
        search: "MariaDelegate",
        chamber: "House",
        state: "PR",
        party: "Democratic"
      },
      MONEY_SUMMARIES
    );

    expect(directory.activeFilters).toEqual({
      search: "mariadelegate",
      chamber: "House",
      state: "PR",
      party: "Democratic"
    });
    expect(directory.rows.map((row) => row.personName)).toEqual(["Maria Delegate"]);
  });

  it("returns the active numeric metric without collapsing reported zero into missing money", () => {
    const reportedRow = buildCongressMemberRow(MEMBERS[1]!, {
      ...MONEY_SUMMARIES[1]!,
      cash_on_hand: "0.00"
    });
    const noMoneyRow = buildCongressMemberRow(MEMBERS[2]!, MONEY_SUMMARIES[2]);

    expect(getCongressMoneyMetric(reportedRow, "total_raised")).toBe(300);
    expect(getCongressMoneyMetric(reportedRow, "outside_against")).toBe(900);
    expect(getCongressMoneyMetric(reportedRow, "outside_support")).toBe(10);
    expect(getCongressMoneyMetric(reportedRow, "cash_on_hand")).toBe(0);
    expect(getCongressMoneyMetric(noMoneyRow, "cash_on_hand")).toBeNull();
  });

  it("prefers a safe FEC record URL, then a safe data-source URL", () => {
    const row = buildCongressMemberRow(MEMBERS[0]!, {
      ...MONEY_SUMMARIES[0]!,
      sources: [
        {
          ...MONEY_SUMMARIES[0]!.sources[0]!,
          record_url: "javascript:alert(1)",
          data_source_url: "https://api.open.fec.gov/developers/"
        },
        {
          ...MONEY_SUMMARIES[0]!.sources[0]!,
          record_url: "https://www.fec.gov/data/candidate/H6NC01001/",
          data_source_url: "https://example.test/fallback"
        }
      ]
    });

    expect(getCongressMoneySourceHref(row)).toBe("https://www.fec.gov/data/candidate/H6NC01001/");
    expect(
      getCongressMoneySourceHref({
        ...row,
        moneySources: [
          {
            ...MONEY_SUMMARIES[0]!.sources[0]!,
            record_url: "file:///private/fec.json",
            data_source_url: "https://api.open.fec.gov/developers/"
          }
        ]
      })
    ).toBe("https://api.open.fec.gov/developers/");
    expect(getCongressMoneySourceHref({ ...row, moneySources: [] })).toBeNull();
  });

  it("builds a canonical compare href only for two to four unique people", () => {
    expect(buildCongressCompareHref(["person-c", "person-a", "person-c", "person-b"])).toBe(
      "/compare?people=person-a,person-b,person-c"
    );
    expect(buildCongressCompareHref(["person-b", "person-a"])).toBe(
      "/compare?people=person-a,person-b"
    );
    expect(buildCongressCompareHref(["person-a", "person-a"])).toBeNull();
    expect(buildCongressCompareHref(["person-e", "person-d", "person-c", "person-b", "person-a"])).toBeNull();
  });
});
