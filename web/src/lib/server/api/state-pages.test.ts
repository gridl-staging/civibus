import { describe, expect, it, vi } from "vitest";
import { ApiResponseError } from "./client";
import {
  COUNTRY_GEOMETRY_PATH,
  STATE_CAMPAIGN_FINANCE_SUMMARY_PATH,
  STATE_COVERAGE_TIER_VALUES,
  STATE_SUPPORT_STATUS_VALUES
} from "./state-pages-contract";
import {
  fetchCountryGeometry,
  fetchStateCampaignFinanceDetail,
  fetchStateCampaignFinanceSummaries
} from "./state-pages";

describe("fetchCountryGeometry", () => {
  it("requests the shared country-geometry endpoint", async () => {
    const requestJson = vi
      .fn()
      .mockResolvedValue({ type: "FeatureCollection", features: [] });

    const result = await fetchCountryGeometry({ requestJson });

    expect(requestJson).toHaveBeenCalledWith(COUNTRY_GEOMETRY_PATH);
    expect(result).toEqual({ type: "FeatureCollection", features: [] });
  });

  it("propagates ApiResponseError unchanged", async () => {
    const cause = new ApiResponseError(500, { detail: "boom" });
    const requestJson = vi.fn().mockRejectedValue(cause);

    await expect(fetchCountryGeometry({ requestJson })).rejects.toBe(cause);
  });
});

describe("state-pages backend enum contract", () => {
  it("keeps support_status literals aligned with the backend response model", () => {
    expect(STATE_SUPPORT_STATUS_VALUES).toEqual([
      "supported",
      "warning",
      "unsupported"
    ]);
  });

  it("keeps coverage_tier literals aligned with the backend response model", () => {
    expect(STATE_COVERAGE_TIER_VALUES).toEqual([
      "launch-support candidate",
      "implemented but unproven",
      "freshness-limited",
      "deferred/blocked"
    ]);
  });
});

describe("fetchStateCampaignFinanceSummaries", () => {
  it("requests the shared states-summary endpoint", async () => {
    const requestJson = vi.fn().mockResolvedValue([]);

    const result = await fetchStateCampaignFinanceSummaries({ requestJson });

    expect(requestJson).toHaveBeenCalledWith(STATE_CAMPAIGN_FINANCE_SUMMARY_PATH);
    expect(result).toEqual([]);
  });

  it("propagates ApiResponseError unchanged", async () => {
    const cause = new ApiResponseError(503, "unavailable");
    const requestJson = vi.fn().mockRejectedValue(cause);

    await expect(
      fetchStateCampaignFinanceSummaries({ requestJson })
    ).rejects.toBe(cause);
  });
});

describe("fetchStateCampaignFinanceDetail", () => {
  it("requests the shared state-detail endpoint path", async () => {
    const requestJson = vi.fn().mockResolvedValue({
      state_code: "NC",
      total_raised: "0",
      total_spent: "0",
      net: "0",
      committee_count: 0,
      transaction_count: 0,
      federal_candidate_count: 0,
      ie_support_total: null,
      ie_oppose_total: null,
      ie_support_count: null,
      ie_oppose_count: null,
      coverage_tier: null,
      support_status: "supported",
      supported: true,
      warning_text: null,
      data_through: null,
      sources: [],
      top_candidates: [],
      top_committees: [],
      top_ie_spenders: []
    });

    const result = await fetchStateCampaignFinanceDetail({ requestJson }, "NC");

    expect(requestJson).toHaveBeenCalledWith("/v1/campaign-finance/states/NC");
    expect(result.state_code).toBe("NC");
  });

  it("normalizes state code path segment to uppercase", async () => {
    const requestJson = vi.fn().mockResolvedValue({
      state_code: "NC",
      total_raised: "0",
      total_spent: "0",
      net: "0",
      committee_count: 0,
      transaction_count: 0,
      federal_candidate_count: 0,
      ie_support_total: null,
      ie_oppose_total: null,
      ie_support_count: null,
      ie_oppose_count: null,
      coverage_tier: null,
      support_status: "supported",
      supported: true,
      warning_text: null,
      data_through: null,
      sources: [],
      top_candidates: [],
      top_committees: [],
      top_ie_spenders: []
    });

    await fetchStateCampaignFinanceDetail({ requestJson }, "nc");

    expect(requestJson).toHaveBeenCalledWith("/v1/campaign-finance/states/NC");
  });

  it("propagates ApiResponseError unchanged", async () => {
    const cause = new ApiResponseError(422, { detail: "invalid state code" });
    const requestJson = vi.fn().mockRejectedValue(cause);

    await expect(fetchStateCampaignFinanceDetail({ requestJson }, "n@")).rejects.toBe(cause);
  });
});
