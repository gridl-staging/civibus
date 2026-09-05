import { ApiResponseError } from "$lib/server/api/client";
import { NYC_NODE, SEATTLE_NODE } from "$lib/regional-navigation/test-fixtures";
import { describe, expect, it, vi } from "vitest";
import { load } from "./+page.server";
import type { RegionalFilingAuthority } from "$lib/server/api/state-pages-contract";

function createLoadEvent(
  requestJson: ReturnType<typeof vi.fn>,
  slug = "seattle",
  code = "WA",
  pathname = `/state/${code}/municipality/${slug}`
) {
  return {
    params: { code, slug },
    url: new URL(`https://civibus.test${pathname}`),
    locals: { api: { requestJson } }
  } as unknown as Parameters<typeof load>[0];
}

describe("/state/[code]/municipality/[slug] +page.server load", () => {
  it("preserves the shared resolver 404 for an unselected municipality", async () => {
    const requestJson = vi
      .fn()
      .mockRejectedValue(new ApiResponseError(404, { detail: "Regional navigation node not found." }));

    await expect(load(createLoadEvent(requestJson, "san-francisco", "CA"))).rejects.toMatchObject({
      status: 404
    });
    expect(requestJson).toHaveBeenCalledWith(
      "/v1/regional-navigation/resolve?kind=municipality&state_code=CA&slug=san-francisco"
    );
  });

  it("loads Seattle with every overlapping filing authority and no total", async () => {
    const requestJson = vi.fn().mockResolvedValue(SEATTLE_NODE);

    const data = await load(createLoadEvent(requestJson));
    if (!data) throw new Error("Expected Seattle page data.");

    expect(data).toMatchObject({
      stateCode: "WA",
      municipalityName: "Seattle",
      navigationNode: {
        finance: {
          status: "unavailable",
          authority_context: {
            relation: "partitioned_overlapping",
            aggregation_disposition: "refuse_combination"
          }
        },
        finance_detail: null
      }
    });
    expect(
      data.navigationNode.finance.authority_context.filing_authorities.map(
        (authority: RegionalFilingAuthority) => authority.code
      )
    ).toEqual(["WA", "WA_SEATTLE_CITY_CLERK", "WA_SEEC"]);
  });

  it("loads New York City as a bounded overlapping authority control", async () => {
    const requestJson = vi.fn().mockResolvedValue(NYC_NODE);

    const data = await load(createLoadEvent(requestJson, "new-york-city", "NY"));
    if (!data) throw new Error("Expected New York City page data.");

    expect(data.navigationNode.finance.authority_context).toMatchObject({
      relation: "partitioned_overlapping",
      aggregation_disposition: "refuse_combination"
    });
    expect(
      data.navigationNode.finance.authority_context.filing_authorities.map(
        (authority: RegionalFilingAuthority) => authority.code
      )
    ).toEqual(["NY", "NY_NEW_YORK"]);
    expect(data.navigationNode.finance_detail).toBeNull();
  });

  it("redirects a resolver-proven state-code alias only", async () => {
    const requestJson = vi.fn().mockResolvedValue(SEATTLE_NODE);

    await expect(
      load(createLoadEvent(requestJson, "seattle", "wa", "/state/wa/municipality/seattle?view=map"))
    ).rejects.toMatchObject({
      status: 308,
      location: "/state/WA/municipality/seattle?view=map"
    });
  });

  it("rejects non-canonical slugs before any backend request", async () => {
    const requestJson = vi.fn();

    await expect(load(createLoadEvent(requestJson, "San-Francisco"))).rejects.toMatchObject({
      status: 404
    });
    expect(requestJson).not.toHaveBeenCalled();
  });
});
