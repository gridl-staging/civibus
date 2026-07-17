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

const CONGRESS_MONEY_SUMMARIES_RESPONSE = [
  {
    person_id: "11111111-1111-4111-8111-111111111111",
    person_name: "Jane Representative",
    has_fec_money: true,
    candidate_id: "H6NC01001",
    total_raised: "1234.56",
    total_spent: "1000.00",
    net: "234.56",
    cash_on_hand: "345.67",
    summary_source: "fec_candidate_totals",
    ie_support_total: "25.00",
    ie_oppose_total: "50.00",
    ie_support_count: 2,
    ie_oppose_count: 1,
    sources: []
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

type CongressLoadData = {
  members: typeof CONGRESS_MEMBERS_RESPONSE;
  moneySummaries: unknown[];
};

function assertCongressLoadData(data: Awaited<ReturnType<typeof load>>): asserts data is CongressLoadData {
  if (data === undefined || !("members" in data) || !("moneySummaries" in data)) {
    throw new Error("Expected Congress load data.");
  }
}

describe("/congress +page.server load", () => {
  it("returns the exact Congress member and money arrays from the backend without forwarding filter params", async () => {
    const requestJson = vi
      .fn()
      .mockResolvedValueOnce(CONGRESS_MEMBERS_RESPONSE)
      .mockResolvedValueOnce(CONGRESS_MONEY_SUMMARIES_RESPONSE);

    const data = await load(
      createLoadEvent("https://web.civibus.local/congress?search=jane&chamber=House&state=NC&party=Democratic", requestJson)
    );

    assertCongressLoadData(data);
    expect(data).toEqual({ members: CONGRESS_MEMBERS_RESPONSE, moneySummaries: CONGRESS_MONEY_SUMMARIES_RESPONSE });
    expect(requestJson).toHaveBeenCalledTimes(2);
    expect(requestJson).toHaveBeenNthCalledWith(1, "/v1/congress/members");
    expect(requestJson).toHaveBeenNthCalledWith(2, "/v1/congress/money-summaries");
  });

  it("keeps visible members available when the optional money request fails", async () => {
    const requestJson = vi
      .fn()
      .mockResolvedValueOnce(CONGRESS_MEMBERS_RESPONSE)
      .mockRejectedValueOnce(new ApiResponseError(500, { detail: "money unavailable" }));

    const data = await load(createLoadEvent("https://web.civibus.local/congress", requestJson));

    assertCongressLoadData(data);
    expect(data).toEqual({ members: CONGRESS_MEMBERS_RESPONSE, moneySummaries: [] });
    expect(data.members).toHaveLength(1);
    expect(data.members[0]?.person_name).toBe("Jane Representative");
    expect(requestJson).toHaveBeenCalledTimes(2);
    expect(requestJson).toHaveBeenNthCalledWith(1, "/v1/congress/members");
    expect(requestJson).toHaveBeenNthCalledWith(2, "/v1/congress/money-summaries");
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
