import { ApiResponseError } from "$lib/server/api/client";
import type { ContestDetailResponse } from "$lib/civic-detail/contract";
import { describe, expect, it, vi } from "vitest";
import { load } from "./+page.server";

const CONTEST_ID = "77777777-7777-4777-8777-777777777777";
const OFFICE_ID = "33333333-3333-4333-8333-333333333333";
const ELECTORAL_DIVISION_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const PERSON_ID = "11111111-1111-4111-8111-111111111111";
const GEOMETRY_PATH = "/v1/civics/geometry?level=county&state=NC";

function createLoadEvent(
  requestJson: ReturnType<typeof vi.fn>,
  id = CONTEST_ID,
  url = new URL(`https://example.test/contest/${id}`)
) {
  return {
    params: { id },
    url,
    locals: {
      api: { requestJson }
    }
  } as unknown as Parameters<typeof load>[0];
}

describe("/contest/[id] +page.server load", () => {
  it("returns contest detail and deterministic contest geometry with no graph/ER/slug side lookups", async () => {
    const requestJson = vi.fn(async (path: string) => {
      if (path === `/v1/contests/${CONTEST_ID}`) {
        return {
          id: CONTEST_ID,
          name: "Governor 2026 General Election",
          election_date: "2026-11-03",
          election_type: "general",
          office_id: OFFICE_ID,
          electoral_division_id: ELECTORAL_DIVISION_ID,
          electoral_division_type: "county",
          electoral_division_state: "NC",
          number_of_seats: 1,
          filing_deadline: "2026-09-01",
          is_partisan: true,
          candidate_list_incomplete: false,
          result_winner_candidacy_id: null,
          result_winner_person_id: null,
          result_winner_person_name: null,
          candidacies: [],
          sources: []
        } satisfies ContestDetailResponse;
      }
      if (path === GEOMETRY_PATH) {
        return {
          type: "FeatureCollection",
          features: []
        };
      }

      throw new Error(`unexpected path: ${path}`);
    });

    const data = (await load(createLoadEvent(requestJson))) as {
      contest: ContestDetailResponse;
      geometryByLevel: Record<string, { type: string; features: unknown[] }>;
      contestCandidateFinanceByPersonId: Record<string, unknown>;
      contestSelectedCycle: number | null;
    };

    expect(data.contest.id).toBe(CONTEST_ID);
    expect(data.geometryByLevel.county.features).toEqual([]);
    expect(data.contestCandidateFinanceByPersonId).toEqual({});
    expect(data.contestSelectedCycle).toBe(2026);
    const calledPaths = requestJson.mock.calls.map(([path]) => String(path));
    expect(calledPaths).toEqual([`/v1/contests/${CONTEST_ID}`, GEOMETRY_PATH]);
    expect(calledPaths.every((path) => !path.startsWith("/v1/graph/"))).toBe(true);
    expect(calledPaths.every((path) => !path.startsWith("/v1/er/"))).toBe(true);
    expect(calledPaths.every((path) => !path.includes("slug"))).toBe(true);
  });

  it("loads contest-linked candidate finance and IE sections by candidacy person id", async () => {
    const requestJson = vi.fn(async (path: string) => {
      if (path === `/v1/contests/${CONTEST_ID}`) {
        return {
          id: CONTEST_ID,
          name: "Governor 2026 General Election",
          election_date: "2026-11-03",
          election_type: "general",
          office_id: OFFICE_ID,
          electoral_division_id: ELECTORAL_DIVISION_ID,
          electoral_division_type: "county",
          electoral_division_state: "NC",
          number_of_seats: 1,
          filing_deadline: "2026-09-01",
          is_partisan: true,
          candidate_list_incomplete: false,
          result_winner_candidacy_id: null,
          result_winner_person_id: null,
          result_winner_person_name: null,
          candidacies: [
            {
              candidacy_id: "candidacy-1",
              person_id: PERSON_ID,
              person_name: "Jane Candidate",
              party: "DEM",
              status: "won",
              incumbent_challenge: "I"
            }
          ],
          sources: []
        } satisfies ContestDetailResponse;
      }
      if (path === GEOMETRY_PATH) {
        return { type: "FeatureCollection", features: [] };
      }
      if (path === `/v1/candidates?person_id=${PERSON_ID}&limit=10&offset=0`) {
        return {
          items: [
            {
              id: "candidate-1",
              fec_candidate_id: "H0NC01001",
              name: "Jane Candidate",
              person_id: PERSON_ID,
              party: "DEM",
              office: "H",
              state: "NC",
              district: "01",
              slug: "jane-candidate",
              slug_is_unique: true,
              identity_is_safe: true
            }
          ],
          has_next: false,
          offset: 0,
          limit: 10
        };
      }
      if (path === "/v1/candidates/candidate-1") {
        return {
          id: "candidate-1",
          fec_candidate_id: "H0NC01001",
          name: "Jane Candidate",
          slug: "jane-candidate",
          slug_is_unique: true,
          identity_is_safe: true,
          person_id: PERSON_ID,
          party: "DEM",
          office: "H",
          state: "NC",
          district: "01",
          incumbent_challenge: "I",
          principal_committee_id: null,
          sources: []
        };
      }
      if (path === "/v1/candidates/candidate-1/summary?cycle=2026") {
        return {
          candidate_id: "candidate-1",
          candidate_name: "Jane Candidate",
          total_raised: "5000.00",
          total_spent: "2000.00",
          net: "3000.00",
          transaction_count: 42,
          selected_cycle: 2026,
          coverage_start_date: "2025-01-01",
          coverage_end_date: "2026-12-31",
          available_cycles: [2022, 2024, 2026],
          cash_on_hand: "1000.00",
          summary_source: "fec_weball",
          itemized_transaction_count: 42,
          committees: []
        };
      }
      if (path === "/v1/candidates/candidate-1/independent-expenditures?cycle=2026") {
        return [];
      }
      if (path === "/v1/candidates/candidate-1/independent-expenditures/summary?cycle=2026") {
        return {
          candidate_id: "candidate-1",
          support_total: "100.00",
          oppose_total: "50.00",
          support_count: 1,
          oppose_count: 1,
          selected_cycle: 2026,
          coverage_start_date: "2025-01-01",
          coverage_end_date: "2026-12-31",
          available_cycles: [2022, 2024, 2026],
          excluded_outlier_count: 0,
          top_spenders: []
        };
      }
      throw new Error(`unexpected path: ${path}`);
    });

    const data = (await load(createLoadEvent(requestJson))) as {
      contestCandidateFinanceByPersonId: Record<
        string,
        {
          personId: string;
          candidateHref: string | null;
          summary: { total_raised: string };
          ieSummary: { support_total: string } | null;
          ieTransactions: unknown[];
        }
      >;
    };

    expect(data.contestCandidateFinanceByPersonId[PERSON_ID]).toMatchObject({
      personId: PERSON_ID,
      candidateHref: "/candidate/jane-candidate",
      summary: {
        selected_cycle: 2026,
        coverage_end_date: "2026-12-31",
        total_raised: "5000.00",
        cash_on_hand: "1000.00"
      },
      ieSummary: {
        selected_cycle: 2026,
        coverage_end_date: "2026-12-31",
        support_total: "100.00"
      },
      ieTransactions: []
    });
    expect(requestJson.mock.calls.map(([path]) => path)).toEqual([
      `/v1/contests/${CONTEST_ID}`,
      GEOMETRY_PATH,
      `/v1/candidates?person_id=${PERSON_ID}&limit=10&offset=0`,
      "/v1/candidates/candidate-1",
      "/v1/candidates/candidate-1/summary?cycle=2026",
      "/v1/candidates/candidate-1/independent-expenditures?cycle=2026",
      "/v1/candidates/candidate-1/independent-expenditures/summary?cycle=2026"
    ]);
  });

  it("uses the cycle query override for contest-linked candidate finance", async () => {
    const requestJson = vi.fn(async (path: string) => {
      if (path === `/v1/contests/${CONTEST_ID}`) {
        return {
          id: CONTEST_ID,
          name: "Governor 2026 General Election",
          election_date: "2026-11-03",
          election_type: "general",
          office_id: OFFICE_ID,
          electoral_division_id: ELECTORAL_DIVISION_ID,
          electoral_division_type: "county",
          electoral_division_state: "NC",
          number_of_seats: 1,
          filing_deadline: "2026-09-01",
          is_partisan: true,
          candidate_list_incomplete: false,
          result_winner_candidacy_id: null,
          result_winner_person_id: null,
          result_winner_person_name: null,
          candidacies: [
            {
              candidacy_id: "candidacy-1",
              person_id: PERSON_ID,
              person_name: "Jane Candidate",
              party: "DEM",
              status: "won",
              incumbent_challenge: "I"
            }
          ],
          sources: []
        } satisfies ContestDetailResponse;
      }
      if (path === GEOMETRY_PATH) {
        return { type: "FeatureCollection", features: [] };
      }
      if (path === `/v1/candidates?person_id=${PERSON_ID}&limit=10&offset=0`) {
        return {
          items: [
            {
              id: "candidate-1",
              fec_candidate_id: "H0NC01001",
              name: "Jane Candidate",
              person_id: PERSON_ID,
              party: "DEM",
              office: "H",
              state: "NC",
              district: "01",
              slug: "jane-candidate",
              slug_is_unique: true,
              identity_is_safe: true
            }
          ],
          has_next: false,
          offset: 0,
          limit: 10
        };
      }
      if (path === "/v1/candidates/candidate-1") {
        return {
          id: "candidate-1",
          fec_candidate_id: "H0NC01001",
          name: "Jane Candidate",
          slug: "jane-candidate",
          slug_is_unique: true,
          identity_is_safe: true,
          person_id: PERSON_ID,
          party: "DEM",
          office: "H",
          state: "NC",
          district: "01",
          incumbent_challenge: "I",
          principal_committee_id: null,
          sources: []
        };
      }
      if (path === "/v1/candidates/candidate-1/summary?cycle=2024") {
        return {
          selected_cycle: 2024,
          coverage_start_date: "2023-01-01",
          coverage_end_date: "2024-12-31",
          available_cycles: [2022, 2024, 2026],
          candidate_id: "candidate-1",
          candidate_name: "Jane Candidate",
          total_raised: "4000.00",
          total_spent: "3000.00",
          net: "1000.00",
          transaction_count: 24,
          itemized_transaction_count: 24,
          cash_on_hand: "500.00",
          summary_source: "fec_weball",
          committees: []
        };
      }
      if (path === "/v1/candidates/candidate-1/independent-expenditures?cycle=2024") {
        return [];
      }
      if (path === "/v1/candidates/candidate-1/independent-expenditures/summary?cycle=2024") {
        return {
          selected_cycle: 2024,
          coverage_start_date: "2023-01-01",
          coverage_end_date: "2024-12-31",
          available_cycles: [2022, 2024, 2026],
          candidate_id: "candidate-1",
          support_total: "0.00",
          oppose_total: "0.00",
          support_count: 0,
          oppose_count: 0,
          top_spenders: [],
          excluded_outlier_count: 0
        };
      }
      throw new Error(`unexpected path: ${path}`);
    });

    const data = (await load(
      createLoadEvent(
        requestJson,
        CONTEST_ID,
        new URL(`https://example.test/contest/${CONTEST_ID}?cycle=2024`)
      )
    )) as { contestSelectedCycle: number | null };

    expect(data.contestSelectedCycle).toBe(2024);
    expect(requestJson.mock.calls.map(([path]) => path)).toContain(
      "/v1/candidates/candidate-1/summary?cycle=2024"
    );
  });

  it("omits selected-cycle candidate finance paths when the contest has no usable cycle", async () => {
    const requestJson = vi.fn(async (path: string) => {
      if (path === `/v1/contests/${CONTEST_ID}`) {
        return {
          id: CONTEST_ID,
          name: "Governor date pending",
          election_date: null,
          election_type: "general",
          office_id: OFFICE_ID,
          electoral_division_id: ELECTORAL_DIVISION_ID,
          electoral_division_type: "county",
          electoral_division_state: "NC",
          number_of_seats: 1,
          filing_deadline: null,
          is_partisan: true,
          candidate_list_incomplete: false,
          result_winner_candidacy_id: null,
          result_winner_person_id: null,
          result_winner_person_name: null,
          candidacies: [
            {
              candidacy_id: "candidacy-1",
              person_id: PERSON_ID,
              person_name: "Jane Candidate",
              party: "DEM",
              status: "filed",
              incumbent_challenge: "I"
            }
          ],
          sources: []
        } satisfies ContestDetailResponse;
      }
      if (path === GEOMETRY_PATH) {
        return { type: "FeatureCollection", features: [] };
      }
      if (path === `/v1/candidates?person_id=${PERSON_ID}&limit=10&offset=0`) {
        return { items: [], has_next: false, offset: 0, limit: 10 };
      }
      throw new Error(`unexpected path: ${path}`);
    });

    const data = (await load(createLoadEvent(requestJson))) as {
      contestSelectedCycle: number | null;
    };

    expect(data.contestSelectedCycle).toBeNull();
    expect(requestJson.mock.calls.map(([path]) => path)).toEqual([
      `/v1/contests/${CONTEST_ID}`,
      GEOMETRY_PATH,
      `/v1/candidates?person_id=${PERSON_ID}&limit=10&offset=0`
    ]);
  });

  it("preserves backend-owned 404 Contest not found semantics", async () => {
    const requestJson = vi.fn(async (path: string) => {
      expect(path).toBe(`/v1/contests/${CONTEST_ID}`);
      throw new ApiResponseError(404, { detail: "Contest not found" });
    });

    await expect(load(createLoadEvent(requestJson))).rejects.toMatchObject({
      status: 404,
      body: { detail: "Contest not found" }
    });

    expect(requestJson).toHaveBeenCalledTimes(1);
  });

  it("preserves backend malformed UUID 422 semantics", async () => {
    const malformedId = "not-a-uuid";
    const requestJson = vi.fn(async (path: string) => {
      expect(path).toBe(`/v1/contests/${malformedId}`);
      throw new ApiResponseError(422, {
        detail: [{ loc: ["path", "contest_id"], msg: "Input should be a valid UUID" }]
      });
    });

    await expect(load(createLoadEvent(requestJson, malformedId))).rejects.toMatchObject({
      status: 422,
      body: { detail: [{ loc: ["path", "contest_id"], msg: "Input should be a valid UUID" }] }
    });

    expect(requestJson).toHaveBeenCalledTimes(1);
  });

  it("falls back to empty contest geometry when civic geometry returns backend-owned 404", async () => {
    const requestJson = vi.fn(async (path: string) => {
      if (path === `/v1/contests/${CONTEST_ID}`) {
        return {
          id: CONTEST_ID,
          name: "Governor 2026 General Election",
          election_date: "2026-11-03",
          election_type: "general",
          office_id: OFFICE_ID,
          electoral_division_id: ELECTORAL_DIVISION_ID,
          electoral_division_type: "county",
          electoral_division_state: "NC",
          number_of_seats: 1,
          filing_deadline: "2026-09-01",
          is_partisan: true,
          candidate_list_incomplete: false,
          result_winner_candidacy_id: null,
          result_winner_person_id: null,
          result_winner_person_name: null,
          candidacies: [],
          sources: []
        } satisfies ContestDetailResponse;
      }
      if (path === GEOMETRY_PATH) {
        throw new ApiResponseError(404, { detail: "Geometry not found for state NC" });
      }
      throw new Error(`unexpected path: ${path}`);
    });

    const data = (await load(createLoadEvent(requestJson))) as {
      contest: ContestDetailResponse;
      geometryByLevel: Record<string, { type: string; features: unknown[] }>;
    };
    expect(data.geometryByLevel.county.features).toEqual([]);
  });

  it("falls back cleanly to empty geometry map when contest division type is unsupported", async () => {
    const requestJson = vi.fn(async (path: string) => {
      if (path === `/v1/contests/${CONTEST_ID}`) {
        return {
          id: CONTEST_ID,
          name: "Governor 2026 General Election",
          election_date: "2026-11-03",
          election_type: "general",
          office_id: OFFICE_ID,
          electoral_division_id: ELECTORAL_DIVISION_ID,
          electoral_division_type: "municipal_ward",
          electoral_division_state: "NC",
          number_of_seats: 1,
          filing_deadline: "2026-09-01",
          is_partisan: true,
          candidate_list_incomplete: false,
          result_winner_candidacy_id: null,
          result_winner_person_id: null,
          result_winner_person_name: null,
          candidacies: [],
          sources: []
        } satisfies ContestDetailResponse;
      }
      throw new Error(`unexpected path: ${path}`);
    });

    const data = (await load(createLoadEvent(requestJson))) as {
      geometryByLevel: Record<string, { type: string; features: unknown[] }>;
    };

    expect(data.geometryByLevel.state.features).toEqual([]);
    expect(data.geometryByLevel.county.features).toEqual([]);
    expect(data.geometryByLevel.congressional_district.features).toEqual([]);
    const calledPaths = requestJson.mock.calls.map(([path]) => String(path));
    expect(calledPaths).toEqual([`/v1/contests/${CONTEST_ID}`]);
  });
});
