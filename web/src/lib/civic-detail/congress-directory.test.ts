import type { CongressMemberSummary } from "./contract";
import {
  buildCongressDirectory,
  buildCongressMemberRow,
  filterCongressMembers
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
      }
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
    expect(MEMBERS.map(buildCongressMemberRow).map((row) => row.contextLabel)).toEqual([
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
});
