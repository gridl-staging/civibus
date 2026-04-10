import { ApiResponseError } from "$lib/server/api/client";
import type {
  CandidacyDetailResponse,
  ContestDetailResponse,
  OfficeDetailResponse,
  OfficeholdingDetailResponse
} from "$lib/civic-detail/contract";
import { describe, expect, it, vi } from "vitest";
import type { ApiClient } from "./client";
import {
  fetchCandidacyDetail,
  fetchContestDetail,
  fetchOfficeDetail,
  fetchOfficeholdingDetail
} from "./civic-detail";

const OFFICE_ID = "33333333-3333-4333-8333-333333333333";
const CONTEST_ID = "77777777-7777-4777-8777-777777777777";
const CANDIDACY_ID = "88888888-8888-4888-8888-888888888888";
const OFFICEHOLDING_ID = "44444444-4444-4444-8444-444444444444";
const PERSON_ID = "11111111-1111-4111-8111-111111111111";
const ELECTORAL_DIVISION_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";

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
