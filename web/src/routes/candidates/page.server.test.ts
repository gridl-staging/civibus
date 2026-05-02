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

const CANDIDATE_LIST_RESPONSE = {
  items: [
    {
      id: "55555555-5555-4555-8555-555555555555",
      fec_candidate_id: "H0NC01001",
      name: "Pat Candidate",
      party: "DEM",
      office: "H",
      state: "NC",
      district: "01",
      slug: "pat-candidate",
      slug_is_unique: true
    }
  ],
  has_next: true,
  offset: 25,
  limit: 25
};

describe("/candidates +page.server load", () => {
  it("forwards state, office, limit, and offset params to the candidates list endpoint", async () => {
    const requestJson = vi.fn().mockResolvedValue(CANDIDATE_LIST_RESPONSE);

    const data = await load(
      createLoadEvent("https://web.civibus.local/candidates?state=NC&office=H&limit=25&offset=25", requestJson)
    );

    expect(data).toEqual(CANDIDATE_LIST_RESPONSE);
    const [calledPath] = requestJson.mock.calls[0] as [string];
    const parsed = new URL(calledPath, "https://web.civibus.local");

    expect(parsed.pathname).toBe("/v1/candidates");
    expect(parsed.searchParams.get("state")).toBe("NC");
    expect(parsed.searchParams.get("office")).toBe("H");
    expect(parsed.searchParams.get("limit")).toBe("25");
    expect(parsed.searchParams.get("offset")).toBe("25");
  });

  it("returns default backend-owned list state when query params are absent", async () => {
    const requestJson = vi.fn().mockResolvedValue({
      items: [],
      has_next: false,
      offset: 0,
      limit: 50
    });

    const data = await load(createLoadEvent("https://web.civibus.local/candidates", requestJson));

    expect(data).toEqual({
      items: [],
      has_next: false,
      offset: 0,
      limit: 50
    });
    expect(requestJson).toHaveBeenCalledWith("/v1/candidates");
  });

  it("preserves backend 422 payloads via withApiResponseErrorHandling", async () => {
    const requestJson = vi
      .fn()
      .mockRejectedValue(
        new ApiResponseError(422, { detail: [{ loc: ["query", "offset"], msg: "Input should be greater than or equal to 0" }] })
      );

    await expect(
      load(createLoadEvent("https://web.civibus.local/candidates?offset=-1", requestJson))
    ).rejects.toMatchObject({
      status: 422,
      body: { detail: [{ loc: ["query", "offset"], msg: "Input should be greater than or equal to 0" }] }
    });
    expect(requestJson).toHaveBeenCalledWith("/v1/candidates?offset=-1");
  });

  it("drops explicit blank state and office filters so all-option submits behave like no filter", async () => {
    const requestJson = vi.fn().mockResolvedValue(CANDIDATE_LIST_RESPONSE);

    await load(
      createLoadEvent("https://web.civibus.local/candidates?state=&office=&limit=25", requestJson)
    );

    expect(requestJson).toHaveBeenCalledWith("/v1/candidates?limit=25");
  });

  it("keeps populated filters while dropping blank filters from mixed submissions", async () => {
    const requestJson = vi.fn().mockResolvedValue(CANDIDATE_LIST_RESPONSE);

    await load(
      createLoadEvent("https://web.civibus.local/candidates?state=NC&office=&limit=25", requestJson)
    );

    expect(requestJson).toHaveBeenCalledWith("/v1/candidates?state=NC&limit=25");
  });
});
