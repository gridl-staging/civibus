import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  DATE_PRECISIONS,
  ELECTION_TYPES,
  OFFICEHOLDING_STATUSES,
  OFFICEHOLDER_STATUSES,
  OFFICE_INCOMPLETE_DATA_STATES,
  OFFICE_LEVELS,
  buildCandidacyDetailPath,
  buildCandidacyRoutePath,
  buildContestDetailPath,
  buildContestRoutePath,
  buildElectionDateAggregatePath,
  buildElectionDateRoutePath,
  buildOfficeholdingDetailPath,
  buildOfficeholdingRoutePath,
  buildOfficeDetailPath,
  buildOfficeRoutePath,
  buildUpcomingElectionTimelinePath,
  type CandidacyDetailResponse,
  type ContestDetailResponse,
  type OfficeholdingDetailResponse,
  type OfficeDetailResponse,
  type OfficeholderSummary
} from "./contract";

const OFFICE_ID = "33333333-3333-4333-8333-333333333333";
const OFFICEHOLDING_ID = "44444444-4444-4444-8444-444444444444";
const CONTEST_ID = "77777777-7777-4777-8777-777777777777";
const CANDIDACY_ID = "88888888-8888-4888-8888-888888888888";
const PERSON_ID = "11111111-1111-4111-8111-111111111111";
const ELECTORAL_DIVISION_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const ELECTION_DATE = "2026-11-03";
const testFilePath = fileURLToPath(import.meta.url);
const repoRoot = resolve(dirname(testFilePath), "../../../..");
const civicTypesSource = readFileSync(resolve(repoRoot, "domains/civics/types/models.py"), "utf8");
const coreTypesSource = readFileSync(resolve(repoRoot, "core/types/python/models.py"), "utf8");

function readLiteralValuesFromSource(source: string, literalName: string): string[] {
  const literalMatch = source.match(new RegExp(`${literalName}\\s*=\\s*Literal\\[(?<body>[\\s\\S]*?)\\]`, "m"));

  if (!literalMatch?.groups?.body) {
    throw new Error(`Could not find backend literal ${literalName}.`);
  }

  return [...literalMatch.groups.body.matchAll(/"([^"]+)"/g)].map((match) => match[1]);
}

function readBackendLiteralValues(literalName: string): string[] {
  return readLiteralValuesFromSource(civicTypesSource, literalName);
}

describe("office detail contract", () => {
  it("locks frontend office literal sets to the backend civic domain literals", () => {
    expect(OFFICE_LEVELS).toEqual(readBackendLiteralValues("OfficeLevelLiteral"));
    expect(OFFICE_INCOMPLETE_DATA_STATES).toEqual(
      readBackendLiteralValues("OfficeIncompleteDataStateLiteral")
    );
    expect(OFFICEHOLDING_STATUSES).toEqual(readBackendLiteralValues("OfficeholdingStatusLiteral"));
    expect(OFFICEHOLDER_STATUSES).toEqual(OFFICEHOLDING_STATUSES);
  });

  it("locks frontend election literal set to backend ElectionTypeLiteral", () => {
    expect(ELECTION_TYPES).toEqual(readBackendLiteralValues("ElectionTypeLiteral"));
  });

  it("locks frontend date precision literal set to backend DatePrecisionLiteral", () => {
    expect(DATE_PRECISIONS).toEqual(readLiteralValuesFromSource(coreTypesSource, "DatePrecisionLiteral"));
  });

  it("builds the backend-owned office detail path", () => {
    expect(buildOfficeDetailPath(OFFICE_ID)).toBe(`/v1/offices/${OFFICE_ID}`);
  });

  it("builds the UUID-only frontend /office/[id] route path", () => {
    const routePath = buildOfficeRoutePath(OFFICE_ID);
    const parsed = new URL(routePath, "https://web.civibus.local");

    expect(parsed.pathname).toBe(`/office/${OFFICE_ID}`);
    expect(parsed.search).toBe("");
    expect(parsed.hash).toBe("");
  });

  it("builds backend-owned contest/candidacy/officeholding detail paths", () => {
    expect(buildContestDetailPath(CONTEST_ID)).toBe(`/v1/contests/${CONTEST_ID}`);
    expect(buildCandidacyDetailPath(CANDIDACY_ID)).toBe(`/v1/candidacies/${CANDIDACY_ID}`);
    expect(buildOfficeholdingDetailPath(OFFICEHOLDING_ID)).toBe(
      `/v1/officeholdings/${OFFICEHOLDING_ID}`
    );
  });

  it("builds backend-owned election aggregate and timeline paths", () => {
    expect(buildElectionDateAggregatePath(ELECTION_DATE)).toBe(`/v1/elections/${ELECTION_DATE}`);
    expect(buildUpcomingElectionTimelinePath()).toBe("/v1/elections/timeline/upcoming");
  });

  it("builds slashless election-date route paths", () => {
    const electionPath = new URL(buildElectionDateRoutePath(ELECTION_DATE), "https://web.civibus.local");

    expect(electionPath.pathname).toBe(`/election/${ELECTION_DATE}`);
    expect(electionPath.search).toBe("");
    expect(electionPath.hash).toBe("");
  });

  it("builds UUID-only frontend contest/candidacy/officeholding route paths", () => {
    const contestPath = new URL(buildContestRoutePath(CONTEST_ID), "https://web.civibus.local");
    const candidacyPath = new URL(buildCandidacyRoutePath(CANDIDACY_ID), "https://web.civibus.local");
    const officeholdingPath = new URL(
      buildOfficeholdingRoutePath(OFFICEHOLDING_ID),
      "https://web.civibus.local"
    );

    expect(contestPath.pathname).toBe(`/contest/${CONTEST_ID}`);
    expect(contestPath.search).toBe("");
    expect(contestPath.hash).toBe("");
    expect(candidacyPath.pathname).toBe(`/candidacy/${CANDIDACY_ID}`);
    expect(candidacyPath.search).toBe("");
    expect(candidacyPath.hash).toBe("");
    expect(officeholdingPath.pathname).toBe(`/officeholding/${OFFICEHOLDING_ID}`);
    expect(officeholdingPath.search).toBe("");
    expect(officeholdingPath.hash).toBe("");
  });

  it("encodes office IDs in backend and frontend paths", () => {
    const maliciousId = "../search?entity_type=office";

    expect(buildOfficeDetailPath(maliciousId)).toBe("/v1/offices/..%2Fsearch%3Fentity_type%3Doffice");
    expect(buildOfficeRoutePath(maliciousId)).toBe("/office/..%2Fsearch%3Fentity_type%3Doffice");
    expect(buildContestDetailPath(maliciousId)).toBe("/v1/contests/..%2Fsearch%3Fentity_type%3Doffice");
    expect(buildContestRoutePath(maliciousId)).toBe("/contest/..%2Fsearch%3Fentity_type%3Doffice");
    expect(buildCandidacyDetailPath(maliciousId)).toBe("/v1/candidacies/..%2Fsearch%3Fentity_type%3Doffice");
    expect(buildCandidacyRoutePath(maliciousId)).toBe(
      "/candidacy/..%2Fsearch%3Fentity_type%3Doffice"
    );
    expect(buildOfficeholdingDetailPath(maliciousId)).toBe(
      "/v1/officeholdings/..%2Fsearch%3Fentity_type%3Doffice"
    );
    expect(buildOfficeholdingRoutePath(maliciousId)).toBe(
      "/officeholding/..%2Fsearch%3Fentity_type%3Doffice"
    );
    expect(buildElectionDateAggregatePath(maliciousId)).toBe(
      "/v1/elections/..%2Fsearch%3Fentity_type%3Doffice"
    );
    expect(buildElectionDateRoutePath(maliciousId)).toBe(
      "/election/..%2Fsearch%3Fentity_type%3Doffice"
    );
  });

  it("matches OfficeResponse fields for officeholder, completeness, and source provenance", () => {
    const officeholder = {
      officeholding_id: OFFICEHOLDING_ID,
      person_id: PERSON_ID,
      person_name: "Jane Officeholder",
      holder_status: "elected"
    } satisfies OfficeholderSummary;

    const response = {
      id: OFFICE_ID,
      name: "North Carolina Governor",
      office_level: "state",
      title: "Governor",
      jurisdiction_id: null,
      state: "NC",
      is_elected: true,
      number_of_seats: 1,
      current_officeholders: [officeholder],
      current_holder_card: {
        officeholding_id: OFFICEHOLDING_ID,
        person_id: PERSON_ID,
        person_name: "Jane Officeholder",
        holder_status: "elected",
        electoral_division_id: ELECTORAL_DIVISION_ID,
        electoral_division_type: "county",
        electoral_division_state: "NC",
        valid_period_lower: "2025-01-01",
        valid_period_upper: null,
        date_precision: "day"
      },
      officeholding_timeline: [
        {
          officeholding_id: OFFICEHOLDING_ID,
          person_id: PERSON_ID,
          person_name: "Jane Officeholder",
          holder_status: "elected",
          electoral_division_id: ELECTORAL_DIVISION_ID,
          electoral_division_type: "county",
          electoral_division_state: "NC",
          valid_period_lower: "2025-01-01",
          valid_period_upper: null,
          date_precision: "day",
          is_active: true,
          term_ended: false
        }
      ],
      recent_contests: [
        {
          contest_id: CONTEST_ID,
          contest_name: "Governor 2026 General Election",
          election_date: "2026-11-03",
          election_type: "general",
          filing_deadline: "2026-09-01",
          electoral_division_id: ELECTORAL_DIVISION_ID,
          electoral_division_type: "county",
          electoral_division_state: "NC",
          is_partisan: true,
          candidate_list_incomplete: false
        }
      ],
      selected_electoral_division_id: ELECTORAL_DIVISION_ID,
      selected_electoral_division_type: "county",
      selected_electoral_division_state: "NC",
      incomplete_data_states: ["no_officeholder", "no_active_contest"],
      sources: [
        {
          domain: "civics",
          jurisdiction: "us/nc",
          data_source_name: "NC Board of Elections",
          data_source_url: "https://example.org/nc",
          source_record_key: "office-1",
          record_url: "https://example.org/nc/offices/1",
          pull_date: "2026-03-30T00:00:00Z"
        }
      ]
    } satisfies OfficeDetailResponse;

    expect(response.current_officeholders[0].person_name).toBe("Jane Officeholder");
    expect(response.current_holder_card?.valid_period_lower).toBe("2025-01-01");
    expect(response.officeholding_timeline[0].is_active).toBe(true);
    expect(response.recent_contests[0].contest_id).toBe(CONTEST_ID);
    expect(response.selected_electoral_division_type).toBe("county");
    expect(response.incomplete_data_states).toEqual(["no_officeholder", "no_active_contest"]);
    expect(response.sources).toHaveLength(1);
  });

  it("matches ContestResponse fields for election metadata, candidacies, and source provenance", () => {
    const response = {
      id: CONTEST_ID,
      name: "Governor 2026 General Election",
      election_date: "2026-11-03",
      election_type: "general",
      office_id: OFFICE_ID,
      electoral_division_id: ELECTORAL_DIVISION_ID,
      number_of_seats: 1,
      filing_deadline: "2026-09-01",
      is_partisan: true,
      candidate_list_incomplete: false,
      candidacies: [
        {
          candidacy_id: CANDIDACY_ID,
          person_id: PERSON_ID,
          person_name: "Jane Officeholder",
          party: "DEM",
          status: "filed",
          incumbent_challenge: "I"
        }
      ],
      sources: []
    } satisfies ContestDetailResponse;

    expect(response.election_type).toBe("general");
    expect(response.candidacies).toHaveLength(1);
    expect(response.candidacies[0].person_name).toBe("Jane Officeholder");
  });

  it("matches CandidacyResponse fields for person linkage and filing/status metadata", () => {
    const response = {
      id: CANDIDACY_ID,
      person_id: PERSON_ID,
      person_name: "Jane Officeholder",
      contest_id: CONTEST_ID,
      party: "DEM",
      filing_date: "2026-02-01",
      status: "filed",
      incumbent_challenge: "I",
      candidate_number: "17",
      sources: []
    } satisfies CandidacyDetailResponse;

    expect(response.person_id).toBe(PERSON_ID);
    expect(response.contest_id).toBe(CONTEST_ID);
    expect(response.status).toBe("filed");
  });

  it("matches OfficeholdingResponse fields for holder status and valid-period bounds", () => {
    const response = {
      id: OFFICEHOLDING_ID,
      person_id: PERSON_ID,
      person_name: "Jane Officeholder",
      office_id: OFFICE_ID,
      electoral_division_id: ELECTORAL_DIVISION_ID,
      holder_status: "elected",
      valid_period_lower: "2025-01-01",
      valid_period_upper: null,
      date_precision: "day",
      sources: []
    } satisfies OfficeholdingDetailResponse;

    expect(response.holder_status).toBe("elected");
    expect(response.valid_period_lower).toBe("2025-01-01");
    expect(response.date_precision).toBe("day");
  });
});
