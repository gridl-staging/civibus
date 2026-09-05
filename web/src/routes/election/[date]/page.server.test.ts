import { ApiResponseError } from "$lib/server/api/client";
import type { ElectionDateAggregateResponse } from "$lib/civic-detail/contract";
import { describe, expect, it, vi } from "vitest";

const ELECTION_DATE = "2026-11-03";
const CONTEST_ID = "77777777-7777-4777-8777-777777777777";
const OFFICE_ID = "33333333-3333-4333-8333-333333333333";
const ELECTORAL_DIVISION_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";

const { fetchElectionDateAggregateMock } = vi.hoisted(() => ({
  fetchElectionDateAggregateMock: vi.fn()
}));

vi.mock("$lib/server/api/civic-detail", () => ({
  fetchElectionDateAggregate: fetchElectionDateAggregateMock
}));

import { load } from "./+page.server";

function createLoadEvent(date = ELECTION_DATE) {
  const setHeaders = vi.fn();
  const event = {
    params: { date },
    locals: {
      api: {
        requestJson: vi.fn()
      }
    },
    setHeaders
  } as unknown as Parameters<typeof load>[0];

  return { event, setHeaders };
}

describe("/election/[date] +page.server load", () => {
  it("forwards params.date and returns payload from civic API wrapper", async () => {
    fetchElectionDateAggregateMock.mockResolvedValueOnce({
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
          electoral_division_type: "statewide",
          electoral_division_state: "NC",
          district_number: null,
          candidate_count: 2
        }
      ]
    } satisfies ElectionDateAggregateResponse);

    const { event } = createLoadEvent();
    const data = (await load(event)) as ElectionDateAggregateResponse;

    expect(fetchElectionDateAggregateMock).toHaveBeenCalledTimes(1);
    expect(fetchElectionDateAggregateMock).toHaveBeenCalledWith(event.locals.api, {
      date: ELECTION_DATE
    });
    expect(data.date).toBe(ELECTION_DATE);
    expect(data.total_contests).toBe(1);
  });

  it("sets cache headers for election pages", async () => {
    fetchElectionDateAggregateMock.mockResolvedValueOnce({
      date: ELECTION_DATE,
      total_contests: 0,
      total_candidacies: 0,
      contests: []
    } satisfies ElectionDateAggregateResponse);

    const { event, setHeaders } = createLoadEvent();
    await load(event);

    expect(setHeaders).toHaveBeenCalledWith({
      "cache-control": "public, max-age=120, s-maxage=120, stale-while-revalidate=60"
    });
  });

  it("maps ApiResponseError through withApiResponseErrorHandling", async () => {
    fetchElectionDateAggregateMock.mockRejectedValueOnce(
      new ApiResponseError(404, { detail: "Election date not found" })
    );

    const { event, setHeaders } = createLoadEvent();

    await expect(load(event)).rejects.toMatchObject({
      status: 404,
      body: { detail: "Election date not found" }
    });
    expect(setHeaders).not.toHaveBeenCalled();
  });

  it("preserves backend 502 plain-text error payloads for election date lookups", async () => {
    fetchElectionDateAggregateMock.mockRejectedValueOnce(
      new ApiResponseError(502, "Election service unavailable")
    );

    const { event, setHeaders } = createLoadEvent();

    await expect(load(event)).rejects.toMatchObject({
      status: 502,
      body: { message: "Election service unavailable" }
    });
    expect(setHeaders).not.toHaveBeenCalled();
  });

  it("rejects impossible calendar dates before any backend request", async () => {
    fetchElectionDateAggregateMock.mockClear();
    const { event, setHeaders } = createLoadEvent("2024-02-30");

    await expect(load(event)).rejects.toMatchObject({
      status: 400,
      body: {
        message: "Invalid election date.",
        detail: "Election date must be a real calendar date in YYYY-MM-DD format."
      }
    });
    expect(fetchElectionDateAggregateMock).not.toHaveBeenCalled();
    expect(setHeaders).not.toHaveBeenCalled();
  });

  it("passes through an empty election aggregate without coercing zero-count fields", async () => {
    const emptyAggregate: ElectionDateAggregateResponse = {
      date: ELECTION_DATE,
      total_contests: 0,
      total_candidacies: 0,
      contests: []
    };
    fetchElectionDateAggregateMock.mockResolvedValueOnce(emptyAggregate);

    const { event } = createLoadEvent();
    const data = (await load(event)) as ElectionDateAggregateResponse;

    expect(data).toBe(emptyAggregate);
    expect(data.contests).toEqual([]);
    expect(data.total_contests).toBe(0);
    expect(data.total_candidacies).toBe(0);
    expect(data.date).toBe(ELECTION_DATE);
  });

  it("passes contest payloads through unchanged including unrecognized division types and null district context", async () => {
    // The load function is a pass-through; the page's presentation layer is the
    // only place allowed to interpret these values. A division_type the frontend
    // has no label for, and a null district on a row that does have a division,
    // must both survive the load untouched rather than being coerced or dropped.
    const malformedAggregate = {
      date: ELECTION_DATE,
      total_contests: 1,
      total_candidacies: 0,
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
          electoral_division_type: "tribal_district",
          electoral_division_state: null,
          district_number: null,
          candidate_count: 0
        }
      ]
    } as unknown as ElectionDateAggregateResponse;
    fetchElectionDateAggregateMock.mockResolvedValueOnce(malformedAggregate);

    const { event } = createLoadEvent();
    const data = (await load(event)) as ElectionDateAggregateResponse;

    expect(data).toBe(malformedAggregate);
    expect(data.contests[0]?.electoral_division_type).toBe("tribal_district");
    expect(data.contests[0]?.electoral_division_state).toBeNull();
    expect(data.contests[0]?.district_number).toBeNull();
    expect(data.contests[0]?.candidate_count).toBe(0);
  });
});
