import { ApiResponseError } from "$lib/server/api/client";
import { describe, expect, it, vi } from "vitest";
import { load } from "./+page.server";

function createLoadEvent(url: string, requestJson: ReturnType<typeof vi.fn>) {
  return {
    url: new URL(url),
    locals: {
      api: {
        requestJson
      }
    }
  } as unknown as Parameters<typeof load>[0];
}

const COMMITTEE_LIST_RESPONSE = {
  items: [
    {
      id: "44444444-4444-4444-8444-444444444444",
      fec_committee_id: "C12345678",
      name: "Citizens for Civibus",
      committee_type: "Q",
      party: "DEM",
      state: "NC",
      slug: "citizens-for-civibus",
      slug_is_unique: true
    }
  ],
  has_next: true,
  offset: 50,
  limit: 25
};

describe("/committees +page.server load", () => {
  it("forwards state, committee_type, limit, and offset params to the committees list endpoint", async () => {
    const requestJson = vi.fn().mockResolvedValue(COMMITTEE_LIST_RESPONSE);

    const data = await load(
      createLoadEvent(
        "https://web.civibus.local/committees?state=NC&committee_type=Q&limit=25&offset=50",
        requestJson
      )
    );

    expect(data).toEqual(COMMITTEE_LIST_RESPONSE);
    const [calledPath] = requestJson.mock.calls[0] as [string];
    const parsed = new URL(calledPath, "https://web.civibus.local");

    expect(parsed.pathname).toBe("/v1/committees");
    expect(parsed.searchParams.get("state")).toBe("NC");
    expect(parsed.searchParams.get("committee_type")).toBe("Q");
    expect(parsed.searchParams.get("limit")).toBe("25");
    expect(parsed.searchParams.get("offset")).toBe("50");
  });

  it("returns default backend-owned list state when query params are absent", async () => {
    const requestJson = vi.fn().mockResolvedValue({
      items: [],
      has_next: false,
      offset: 0,
      limit: 50
    });

    const data = await load(createLoadEvent("https://web.civibus.local/committees", requestJson));

    expect(data).toEqual({
      items: [],
      has_next: false,
      offset: 0,
      limit: 50
    });
    expect(requestJson).toHaveBeenCalledWith("/v1/committees");
  });

  it("preserves backend plain-text failures via withApiResponseErrorHandling", async () => {
    const requestJson = vi.fn().mockRejectedValue(new ApiResponseError(503, "Backend unavailable"));

    await expect(
      load(createLoadEvent("https://web.civibus.local/committees?state=NC&limit=abc", requestJson))
    ).rejects.toMatchObject({
      status: 503,
      body: { message: "Backend unavailable" }
    });
    expect(requestJson).toHaveBeenCalledWith("/v1/committees?state=NC&limit=abc");
  });

  it("drops explicit blank committee filters while keeping populated values", async () => {
    const requestJson = vi.fn().mockResolvedValue(COMMITTEE_LIST_RESPONSE);

    await load(createLoadEvent("https://web.civibus.local/committees?committee_type=&state=", requestJson));
    await load(
      createLoadEvent("https://web.civibus.local/committees?state=&committee_type=Q&offset=25", requestJson)
    );

    expect(requestJson).toHaveBeenNthCalledWith(1, "/v1/committees");
    expect(requestJson).toHaveBeenNthCalledWith(2, "/v1/committees?committee_type=Q&offset=25");
  });
});
