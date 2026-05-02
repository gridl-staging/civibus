import { ApiResponseError } from "$lib/server/api/client";
import type { CoverageRegistryResponse } from "$lib/metadata/contract";
import { describe, expect, it, vi } from "vitest";

const { fetchCoverageRegistryMock } = vi.hoisted(() => ({
  fetchCoverageRegistryMock: vi.fn()
}));

vi.mock("$lib/server/api/metadata", () => ({
  fetchCoverageRegistry: fetchCoverageRegistryMock
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

describe("/coverage +page.server load", () => {
  it("calls metadata API wrapper and returns payload", async () => {
    fetchCoverageRegistryMock.mockResolvedValueOnce([
      {
        domain: "campaign_finance",
        jurisdiction: "state/nc",
        data_source_count: 2,
        latest_data_source_pull_at: "2026-04-29T12:00:00Z",
        latest_source_pull_date: "2026-04-28T12:00:00Z"
      }
    ] satisfies CoverageRegistryResponse[]);

    const { event } = createLoadEvent();
    const data = (await load(event)) as { coverageRows: CoverageRegistryResponse[] };

    expect(fetchCoverageRegistryMock).toHaveBeenCalledTimes(1);
    expect(fetchCoverageRegistryMock).toHaveBeenCalledWith(event.locals.api);
    expect(data.coverageRows[0].jurisdiction).toBe("state/nc");
  });

  it("sets cache headers for coverage pages", async () => {
    fetchCoverageRegistryMock.mockResolvedValueOnce([] satisfies CoverageRegistryResponse[]);

    const { event, setHeaders } = createLoadEvent();
    await load(event);

    expect(setHeaders).toHaveBeenCalledWith({
      "cache-control": "public, max-age=300, s-maxage=300, stale-while-revalidate=60"
    });
  });

  it("maps ApiResponseError through withApiResponseErrorHandling", async () => {
    fetchCoverageRegistryMock.mockRejectedValueOnce(
      new ApiResponseError(503, { detail: "service unavailable" })
    );

    const { event } = createLoadEvent();

    await expect(load(event)).rejects.toMatchObject({
      status: 503,
      body: { detail: "service unavailable" }
    });
  });
});
