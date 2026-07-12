import { ApiResponseError } from "$lib/server/api/client";
import { describe, expect, it, vi } from "vitest";
import { load } from "./+page.server";

const CONGRESS_MEMBERS_RESPONSE = [
  {
    person_id: "11111111-1111-4111-8111-111111111111",
    person_name: "Jane Representative",
    officeholding_id: "44444444-4444-4444-8444-444444444444",
    office_id: "33333333-3333-4333-8333-333333333333",
    office_name: "U.S. Representative for North Carolina's 1st congressional district",
    chamber: "House",
    state: "NC",
    district: "01",
    district_or_class: "District 01",
    party: "Democratic",
    portrait_source_image_url: "https://example.test/jane.jpg",
    person_detail_path: "/person/11111111-1111-4111-8111-111111111111"
  }
];

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

describe("/congress +page.server load", () => {
  it("returns the exact Congress member array from the backend without forwarding filter params", async () => {
    const requestJson = vi.fn().mockResolvedValue(CONGRESS_MEMBERS_RESPONSE);

    const data = await load(
      createLoadEvent("https://web.civibus.local/congress?search=jane&chamber=House&state=NC&party=Democratic", requestJson)
    );

    expect(data).toEqual({ members: CONGRESS_MEMBERS_RESPONSE });
    expect(requestJson).toHaveBeenCalledTimes(1);
    expect(requestJson).toHaveBeenCalledWith("/v1/congress/members");
  });

  it("preserves backend error payloads via withApiResponseErrorHandling", async () => {
    const requestJson = vi
      .fn()
      .mockRejectedValue(new ApiResponseError(503, { detail: "service unavailable" }));

    await expect(
      load(createLoadEvent("https://web.civibus.local/congress", requestJson))
    ).rejects.toMatchObject({
      status: 503,
      body: { detail: "service unavailable" }
    });
    expect(requestJson).toHaveBeenCalledWith("/v1/congress/members");
  });
});
