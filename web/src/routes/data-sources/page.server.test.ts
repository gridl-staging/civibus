import { ApiResponseError } from "$lib/server/api/client";
import type { DataSourceMetadataResponse } from "$lib/metadata/contract";
import { describe, expect, it, vi } from "vitest";

const { fetchDataSourcesMetadataMock } = vi.hoisted(() => ({
  fetchDataSourcesMetadataMock: vi.fn()
}));

vi.mock("$lib/server/api/metadata", () => ({
  fetchDataSourcesMetadata: fetchDataSourcesMetadataMock
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

describe("/data-sources +page.server load", () => {
  it("calls metadata API wrapper and returns payload", async () => {
    fetchDataSourcesMetadataMock.mockResolvedValueOnce([
      {
        data_source_id: "11111111-1111-4111-8111-111111111111",
        domain: "campaign_finance",
        jurisdiction: "state/nc",
        name: "NC Disclosure",
        source_url: "https://example.org/source",
        update_frequency: "daily",
        last_pull_at: "2026-04-29T12:00:00Z",
        last_pull_status: "success",
        record_count: 10,
        latest_source_record_id: "22222222-2222-4222-8222-222222222222",
        latest_source_record_key: "record-1",
        latest_source_record_url: "https://example.org/record-1",
        latest_source_pull_date: "2026-04-28T12:00:00Z"
      }
    ] satisfies DataSourceMetadataResponse[]);

    const { event } = createLoadEvent();
    const data = (await load(event)) as { dataSources: DataSourceMetadataResponse[] };

    expect(fetchDataSourcesMetadataMock).toHaveBeenCalledTimes(1);
    expect(fetchDataSourcesMetadataMock).toHaveBeenCalledWith(event.locals.api);
    expect(data.dataSources[0].name).toBe("NC Disclosure");
  });

  it("sets cache headers for data-source pages", async () => {
    fetchDataSourcesMetadataMock.mockResolvedValueOnce([] satisfies DataSourceMetadataResponse[]);

    const { event, setHeaders } = createLoadEvent();
    await load(event);

    expect(setHeaders).toHaveBeenCalledWith({
      "cache-control": "public, max-age=300, s-maxage=300, stale-while-revalidate=60"
    });
  });

  it("maps ApiResponseError through withApiResponseErrorHandling", async () => {
    fetchDataSourcesMetadataMock.mockRejectedValueOnce(
      new ApiResponseError(422, {
        detail: [{ loc: ["query", "limit"], msg: "Input should be less than or equal to 200" }]
      })
    );

    const { event } = createLoadEvent();

    await expect(load(event)).rejects.toMatchObject({
      status: 422,
      body: {
        detail: [{ loc: ["query", "limit"], msg: "Input should be less than or equal to 200" }]
      }
    });
  });
});
