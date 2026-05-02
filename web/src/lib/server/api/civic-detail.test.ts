import { ApiResponseError } from "$lib/server/api/client";
import type {
  CandidacyDetailResponse,
  ContestDetailResponse,
  ElectionDateAggregateResponse,
  OfficeDetailResponse,
  OfficeholdingDetailResponse,
  UpcomingElectionTimelineEntry
} from "$lib/civic-detail/contract";
import { describe, expect, it, vi } from "vitest";
import type { ApiClient } from "./client";
import {
  fetchCandidacyDetail,
  fetchContestDetail,
  fetchElectionDateAggregate,
  fetchOfficeDetail,
  fetchOfficeholdingDetail,
  fetchUpcomingElectionTimeline
} from "./civic-detail";

const OFFICE_ID = "33333333-3333-4333-8333-333333333333";
const CONTEST_ID = "77777777-7777-4777-8777-777777777777";
const CANDIDACY_ID = "88888888-8888-4888-8888-888888888888";
const OFFICEHOLDING_ID = "44444444-4444-4444-8444-444444444444";
const PERSON_ID = "11111111-1111-4111-8111-111111111111";
const ELECTORAL_DIVISION_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const ELECTION_DATE = "2026-11-03";

describe("fetchOfficeDetail", () => {
  it("makes one request to /v1/offices/{id} and no ER/graph/transactions side calls", async () => {
    const requestJson = vi.fn(async (path: string) => {
      expect(path).toBe(`/v1/offices/${OFFICE_ID}`);

      return {
        id: OFFICE_ID,
        name: "North Carolina Governor",
        office_level: "state",
        title: "Governor",
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
      } satisfies OfficeDetailResponse;
    });

    await fetchOfficeDetail(
      { requestJson: requestJson as ApiClient["requestJson"] },
      { id: OFFICE_ID }
    );

    expect(requestJson).toHaveBeenCalledTimes(1);
    expect(requestJson).toHaveBeenCalledWith(`/v1/offices/${OFFICE_ID}`);
    const calledPaths = requestJson.mock.calls.map((call) => String(call[0]));
    expect(calledPaths.every((path) => !path.startsWith("/v1/er/"))).toBe(true);
    expect(calledPaths.every((path) => !path.startsWith("/v1/graph/"))).toBe(true);
    expect(calledPaths.every((path) => !path.startsWith("/v1/transactions"))).toBe(true);
  });

  it("accepts expanded office detail payload fields for holder-card, timeline, contest context, and map context", async () => {
    const requestJson = vi.fn(async () => ({
      id: OFFICE_ID,
      name: "North Carolina Governor",
      office_level: "state",
      title: "Governor",
      jurisdiction_id: null,
      state: "NC",
      is_elected: true,
      number_of_seats: 1,
      current_officeholders: [],
      current_holder_card: {
        officeholding_id: "44444444-4444-4444-8444-444444444444",
        person_id: PERSON_ID,
        person_name: "Jane Officeholder",
        holder_status: "elected",
        electoral_division_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        electoral_division_type: "county",
        electoral_division_state: "NC",
        valid_period_lower: "2025-01-01",
        valid_period_upper: null,
        date_precision: "day"
      },
      officeholding_timeline: [
        {
          officeholding_id: "44444444-4444-4444-8444-444444444444",
          person_id: PERSON_ID,
          person_name: "Jane Officeholder",
          holder_status: "elected",
          electoral_division_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
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
          electoral_division_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
          electoral_division_type: "county",
          electoral_division_state: "NC",
          is_partisan: true,
          candidate_list_incomplete: false
        }
      ],
      selected_electoral_division_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
      selected_electoral_division_type: "county",
      selected_electoral_division_state: "NC",
      incomplete_data_states: [],
      sources: []
    }));

    const response = await fetchOfficeDetail(
      { requestJson: requestJson as ApiClient["requestJson"] },
      { id: OFFICE_ID }
    );

    expect(response.current_holder_card?.person_name).toBe("Jane Officeholder");
    expect(response.officeholding_timeline[0]?.valid_period_lower).toBe("2025-01-01");
    expect(response.recent_contests[0]?.contest_id).toBe(CONTEST_ID);
    expect(response.selected_electoral_division_type).toBe("county");
  });

  it("preserves backend malformed UUID 422 semantics", async () => {
    const requestJson = vi
      .fn()
      .mockRejectedValue(
        new ApiResponseError(422, { detail: [{ loc: ["path", "office_id"], msg: "Input should be a valid UUID" }] })
      );

    await expect(
      fetchOfficeDetail(
        { requestJson: requestJson as ApiClient["requestJson"] },
        { id: "not-a-uuid" }
      )
    ).rejects.toMatchObject({
      status: 422,
      body: { detail: [{ loc: ["path", "office_id"], msg: "Input should be a valid UUID" }] }
    });
  });
});

describe("fetchContestDetail", () => {
  it("makes one request to /v1/contests/{id}", async () => {
    const requestJson = vi.fn(async (path: string) => {
      expect(path).toBe(`/v1/contests/${CONTEST_ID}`);

      return {
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
        candidacies: [],
        sources: []
      } satisfies ContestDetailResponse;
    });

    await fetchContestDetail(
      { requestJson: requestJson as ApiClient["requestJson"] },
      { id: CONTEST_ID }
    );

    expect(requestJson).toHaveBeenCalledTimes(1);
    expect(requestJson).toHaveBeenCalledWith(`/v1/contests/${CONTEST_ID}`);
  });

  it("preserves backend malformed UUID 422 semantics", async () => {
    const requestJson = vi
      .fn()
      .mockRejectedValue(
        new ApiResponseError(422, { detail: [{ loc: ["path", "contest_id"], msg: "Input should be a valid UUID" }] })
      );

    await expect(
      fetchContestDetail(
        { requestJson: requestJson as ApiClient["requestJson"] },
        { id: "not-a-uuid" }
      )
    ).rejects.toMatchObject({
      status: 422,
      body: { detail: [{ loc: ["path", "contest_id"], msg: "Input should be a valid UUID" }] }
    });
  });
});

describe("fetchCandidacyDetail", () => {
  it("makes one request to /v1/candidacies/{id}", async () => {
    const requestJson = vi.fn(async (path: string) => {
      expect(path).toBe(`/v1/candidacies/${CANDIDACY_ID}`);

      return {
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
    });

    await fetchCandidacyDetail(
      { requestJson: requestJson as ApiClient["requestJson"] },
      { id: CANDIDACY_ID }
    );

    expect(requestJson).toHaveBeenCalledTimes(1);
    expect(requestJson).toHaveBeenCalledWith(`/v1/candidacies/${CANDIDACY_ID}`);
  });

  it("preserves backend malformed UUID 422 semantics", async () => {
    const requestJson = vi
      .fn()
      .mockRejectedValue(
        new ApiResponseError(422, { detail: [{ loc: ["path", "candidacy_id"], msg: "Input should be a valid UUID" }] })
      );

    await expect(
      fetchCandidacyDetail(
        { requestJson: requestJson as ApiClient["requestJson"] },
        { id: "not-a-uuid" }
      )
    ).rejects.toMatchObject({
      status: 422,
      body: { detail: [{ loc: ["path", "candidacy_id"], msg: "Input should be a valid UUID" }] }
    });
  });
});

describe("fetchOfficeholdingDetail", () => {
  it("makes one request to /v1/officeholdings/{id}", async () => {
    const requestJson = vi.fn(async (path: string) => {
      expect(path).toBe(`/v1/officeholdings/${OFFICEHOLDING_ID}`);

      return {
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
    });

    await fetchOfficeholdingDetail(
      { requestJson: requestJson as ApiClient["requestJson"] },
      { id: OFFICEHOLDING_ID }
    );

    expect(requestJson).toHaveBeenCalledTimes(1);
    expect(requestJson).toHaveBeenCalledWith(`/v1/officeholdings/${OFFICEHOLDING_ID}`);
  });

  it("preserves backend malformed UUID 422 semantics", async () => {
    const requestJson = vi
      .fn()
      .mockRejectedValue(
        new ApiResponseError(422, {
          detail: [{ loc: ["path", "officeholding_id"], msg: "Input should be a valid UUID" }]
        })
      );

    await expect(
      fetchOfficeholdingDetail(
        { requestJson: requestJson as ApiClient["requestJson"] },
        { id: "not-a-uuid" }
      )
    ).rejects.toMatchObject({
      status: 422,
      body: { detail: [{ loc: ["path", "officeholding_id"], msg: "Input should be a valid UUID" }] }
    });
  });
});

describe("fetchElectionDateAggregate", () => {
  it("makes one request to /v1/elections/{date}", async () => {
    const requestJson = vi.fn(async (path: string) => {
      expect(path).toBe(`/v1/elections/${ELECTION_DATE}`);

      return {
        date: ELECTION_DATE,
        total_contests: 1,
        total_candidacies: 2,
        contests: [
          {
            contest_id: CONTEST_ID,
            office_id: OFFICE_ID,
            name: "Governor 2026 General Election",
            election_type: "general",
            office_name: "Governor",
            office_level: "state",
            state: "NC",
            jurisdiction_id: null,
            electoral_division_id: ELECTORAL_DIVISION_ID,
            candidate_count: 2,
            result_status: null,
            winning_person_name: null
          }
        ]
      } satisfies ElectionDateAggregateResponse;
    });

    await fetchElectionDateAggregate(
      { requestJson: requestJson as ApiClient["requestJson"] },
      { date: ELECTION_DATE }
    );

    expect(requestJson).toHaveBeenCalledTimes(1);
    expect(requestJson).toHaveBeenCalledWith(`/v1/elections/${ELECTION_DATE}`);
  });

  it("preserves backend invalid-date 422 semantics", async () => {
    const requestJson = vi
      .fn()
      .mockRejectedValue(
        new ApiResponseError(422, {
          detail: [{ loc: ["path", "election_date"], msg: "Input should be a valid date" }]
        })
      );

    await expect(
      fetchElectionDateAggregate(
        { requestJson: requestJson as ApiClient["requestJson"] },
        { date: "not-a-date" }
      )
    ).rejects.toMatchObject({
      status: 422,
      body: { detail: [{ loc: ["path", "election_date"], msg: "Input should be a valid date" }] }
    });
  });
});

describe("fetchUpcomingElectionTimeline", () => {
  it("makes one request to /v1/elections/timeline/upcoming", async () => {
    const requestJson = vi.fn(async (path: string) => {
      expect(path).toBe("/v1/elections/timeline/upcoming");

      return [
        {
          date: ELECTION_DATE,
          contests: [
            {
              contest_id: CONTEST_ID,
              office_id: OFFICE_ID,
              name: "Governor 2026 General Election",
              election_type: "general",
              office_name: "Governor",
              office_level: "state",
              state: "NC",
              jurisdiction_id: null,
              electoral_division_id: ELECTORAL_DIVISION_ID,
              candidate_count: 2,
              result_status: null,
              winning_person_name: null
            }
          ]
        }
      ] satisfies UpcomingElectionTimelineEntry[];
    });

    await fetchUpcomingElectionTimeline({ requestJson: requestJson as ApiClient["requestJson"] });

    expect(requestJson).toHaveBeenCalledTimes(1);
    expect(requestJson).toHaveBeenCalledWith("/v1/elections/timeline/upcoming");
  });

  it("preserves backend ApiResponseError semantics", async () => {
    const requestJson = vi.fn().mockRejectedValue(new ApiResponseError(503, { detail: "service unavailable" }));

    await expect(
      fetchUpcomingElectionTimeline({ requestJson: requestJson as ApiClient["requestJson"] })
    ).rejects.toMatchObject({
      status: 503,
      body: { detail: "service unavailable" }
    });
  });
});
