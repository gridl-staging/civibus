import { ApiResponseError } from "$lib/server/api/client";
import type { UpcomingElectionTimelineEntry } from "$lib/civic-detail/contract";
import { describe, expect, it, vi } from "vitest";

const CONTEST_ID = "77777777-7777-4777-8777-777777777777";
const OFFICE_ID = "33333333-3333-4333-8333-333333333333";
const ELECTORAL_DIVISION_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";

const { fetchUpcomingElectionTimelineMock } = vi.hoisted(() => ({
  fetchUpcomingElectionTimelineMock: vi.fn()
}));

vi.mock("$lib/server/api/civic-detail", () => ({
  fetchUpcomingElectionTimeline: fetchUpcomingElectionTimelineMock
}));

import { load } from "./+page.server";

function createLoadEvent() {
  const setHeaders = vi.fn();
  const event = {
    locals: {
      api: {
        requestJson: vi.fn()
      }
    },
    setHeaders
  } as unknown as Parameters<typeof load>[0];

  return { event, setHeaders };
}

describe("/calendar +page.server load", () => {
  it("calls civic API wrapper and returns payload", async () => {
    fetchUpcomingElectionTimelineMock.mockResolvedValueOnce([
      {
        date: "2026-11-03",
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
    ] satisfies UpcomingElectionTimelineEntry[]);

    const { event } = createLoadEvent();
    const data = (await load(event)) as { timelineEntries: UpcomingElectionTimelineEntry[] };

    expect(fetchUpcomingElectionTimelineMock).toHaveBeenCalledTimes(1);
    expect(fetchUpcomingElectionTimelineMock).toHaveBeenCalledWith(event.locals.api);
    expect(data.timelineEntries).toHaveLength(1);
    expect(data.timelineEntries[0].contests[0].name).toBe("Governor 2026 General Election");
  });

  it("sets cache headers for calendar pages", async () => {
    fetchUpcomingElectionTimelineMock.mockResolvedValueOnce([] satisfies UpcomingElectionTimelineEntry[]);

    const { event, setHeaders } = createLoadEvent();
    await load(event);

    expect(setHeaders).toHaveBeenCalledWith({
      "cache-control": "public, max-age=300, s-maxage=300, stale-while-revalidate=60"
    });
  });

  it("maps ApiResponseError through withApiResponseErrorHandling", async () => {
    fetchUpcomingElectionTimelineMock.mockRejectedValueOnce(
      new ApiResponseError(503, { detail: "service unavailable" })
    );

    const { event } = createLoadEvent();

    await expect(load(event)).rejects.toMatchObject({
      status: 503,
      body: { detail: "service unavailable" }
    });
  });
});
