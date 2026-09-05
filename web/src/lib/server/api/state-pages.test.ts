import { describe, expect, it, vi } from "vitest";
import {
  buildWashingtonNode,
  WAKE_NODE
} from "$lib/regional-navigation/test-fixtures";
import { ApiResponseError } from "./client";
import {
  COUNTRY_GEOMETRY_PATH,
  buildRegionalChildrenPath,
  buildRegionalResolvePath,
  buildRegionalSearchPath,
  STATE_COVERAGE_TIER_VALUES,
  STATE_SUPPORT_STATUS_VALUES,
  type RegionalNavigationNode
} from "./state-pages-contract";
import {
  fetchCountryGeometry,
  fetchRegionalChildren,
  fetchRegionalNavigationNode,
  fetchRegionalNavigationSearch
} from "./state-pages";

const WA_NODE = buildWashingtonNode();

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

describe("regional navigation API contract", () => {
  it("builds exact resolver, children, and search paths", () => {
    expect(buildRegionalResolvePath({ kind: "state", stateCode: "WA" })).toBe(
      "/v1/regional-navigation/resolve?kind=state&state_code=WA"
    );
    expect(buildRegionalResolvePath({ kind: "county", stateCode: "NC", slug: "wake" })).toBe(
      "/v1/regional-navigation/resolve?kind=county&state_code=NC&slug=wake"
    );
    expect(buildRegionalChildrenPath("NC", "county")).toBe(
      "/v1/regional-navigation/children?state_code=NC&kind=county"
    );
    expect(buildRegionalSearchPath("Washington")).toBe(
      "/v1/regional-navigation/search?q=Washington&limit=20"
    );
  });

  it("fetches and validates one exact navigation node", async () => {
    const requestJson = vi.fn().mockResolvedValue(WA_NODE);

    await expect(
      fetchRegionalNavigationNode({ requestJson }, { kind: "state", stateCode: "WA" })
    ).resolves.toEqual(WA_NODE);
    expect(requestJson).toHaveBeenCalledWith(
      "/v1/regional-navigation/resolve?kind=state&state_code=WA"
    );
  });

  it("refuses a backend node whose path contradicts its typed identity", async () => {
    const requestJson = vi.fn().mockResolvedValue({
      ...WA_NODE,
      canonical_path: "/state/CA/municipality/washington"
    });

    await expect(
      fetchRegionalNavigationNode({ requestJson }, { kind: "state", stateCode: "WA" })
    ).rejects.toThrow("Regional navigation response did not contain one safe canonical node.");
  });

  it("refuses an untyped authority context", async () => {
    const requestJson = vi.fn().mockResolvedValue({
      ...WA_NODE,
      finance: { ...WA_NODE.finance, authority_context: "state-wa" }
    });

    await expect(
      fetchRegionalNavigationNode({ requestJson }, { kind: "state", stateCode: "WA" })
    ).rejects.toThrow("Regional navigation response did not contain one safe canonical node.");
  });

  it("accepts exact source clocks without collapsing transaction, pull, refresh, and registry time", async () => {
    const unavailableNode = buildWashingtonNode("unavailable");
    const requestJson = vi.fn().mockResolvedValue(unavailableNode);

    const node = await fetchRegionalNavigationNode(
      { requestJson },
      { kind: "state", stateCode: "WA" }
    );

    expect(node.finance_detail?.sources[0]?.last_successful_pull).toBeNull();
    expect(node.finance_detail?.sources[0]?.latest_refresh_completed_at).toBeNull();
    expect(node.finance_detail?.sources[0]?.latest_refresh_execution_origin).toBe("unknown");
    expect(node.finance_detail?.sources[0]?.recurrence_status).toBe("unknown");
    expect(node.finance_detail?.money[0]?.amount).toBeNull();
    expect(JSON.stringify(node)).not.toContain('"record_count"');
    expect(JSON.stringify(node)).not.toContain('"coverage_tier"');
  });

  it("refuses unsafe source URLs, malformed clocks, and undeclared finance fields", async () => {
    for (const financeDetail of [
      {
        ...WA_NODE.finance_detail!,
        sources: [
          {
            ...WA_NODE.finance_detail!.sources[0],
            url: "javascript:alert(1)"
          },
          ...WA_NODE.finance_detail!.sources.slice(1)
        ]
      },
      {
        ...WA_NODE.finance_detail!,
        as_of: "not-a-date"
      },
      {
        ...WA_NODE.finance_detail!,
        total_raised: "0"
      },
      {
        ...WA_NODE.finance_detail!,
        authority_health: []
      }
    ]) {
      const requestJson = vi.fn().mockResolvedValue({
        ...WA_NODE,
        finance_detail: financeDetail
      });

      await expect(
        fetchRegionalNavigationNode({ requestJson }, { kind: "state", stateCode: "WA" })
      ).rejects.toThrow("Regional navigation response did not contain one safe canonical node.");
    }
  });

  it("accepts navigation-only refusal and rejects a cross-subject finance detail", async () => {
    const navigationOnly = { ...WA_NODE, finance_detail: null };
    await expect(
      fetchRegionalNavigationNode(
        { requestJson: vi.fn().mockResolvedValue(navigationOnly) },
        { kind: "state", stateCode: "WA" }
      )
    ).resolves.toEqual(navigationOnly);

    const requestJson = vi.fn().mockResolvedValue({
      ...WA_NODE,
      finance_detail: {
        ...WA_NODE.finance_detail!,
        subject: { kind: "county", code: "NC_WAKE", name: "Wake County" }
      }
    });
    await expect(
      fetchRegionalNavigationNode({ requestJson }, { kind: "state", stateCode: "WA" })
    ).rejects.toThrow("Regional navigation response did not contain one safe canonical node.");
  });

  it("fails closed on an unsafe list row instead of silently omitting it", async () => {
    const requestJson = vi.fn().mockResolvedValue({
      items: [WA_NODE, { ...WA_NODE, canonical_path: "/state/OR" }],
      incomplete_node_kinds: ["county", "municipality"],
      has_unsafe_omissions: true
    });

    await expect(fetchRegionalNavigationSearch({ requestJson }, "Washington")).rejects.toThrow(
      "Regional navigation response contained an unsafe route or omission kind."
    );
  });

  it("refuses duplicate canonical nodes before cards can double count them", async () => {
    const requestJson = vi.fn().mockResolvedValue({
      items: [WA_NODE, WA_NODE],
      incomplete_node_kinds: ["county", "municipality"],
      has_unsafe_omissions: true
    });

    await expect(fetchRegionalNavigationSearch({ requestJson }, "Washington")).rejects.toThrow(
      "Regional navigation response contained duplicate canonical nodes."
    );
  });

  it("refuses distinct routes that claim the same typed geometry reference", async () => {
    const wakeNode: RegionalNavigationNode = WAKE_NODE;
    const requestJson = vi.fn().mockResolvedValue({
      items: [
        wakeNode,
        {
          ...wakeNode,
          name: "Wake County Alias",
          slug: "wake-county",
          canonical_path: "/state/NC/county/wake-county",
          finance: {
            ...wakeNode.finance,
            authority_context: {
              ...wakeNode.finance.authority_context,
              subject: {
                ...wakeNode.finance.authority_context.subject,
                name: "Wake County Alias"
              }
            }
          }
        }
      ],
      incomplete_node_kinds: ["county"],
      has_unsafe_omissions: true
    });

    await expect(fetchRegionalChildren({ requestJson }, "NC", "county")).rejects.toThrow(
      "Regional navigation response contained duplicate typed geometry references."
    );
  });

  it("fetches explicit children without converting absent municipalities into geography claims", async () => {
    const requestJson = vi.fn().mockResolvedValue({
      items: [],
      incomplete_node_kinds: ["municipality"],
      has_unsafe_omissions: true
    });

    await expect(fetchRegionalChildren({ requestJson }, "CA", "municipality")).resolves.toEqual({
      items: [],
      incomplete_node_kinds: ["municipality"],
      has_unsafe_omissions: true
    });
  });

  it("fails closed when the list envelope omits its explicit unsafe-omission flag", async () => {
    const requestJson = vi.fn().mockResolvedValue({ items: [], incomplete_node_kinds: [] });

    await expect(fetchRegionalNavigationSearch({ requestJson }, "Washington")).rejects.toThrow(
      "Regional navigation response did not contain one safe list envelope."
    );
  });
});
