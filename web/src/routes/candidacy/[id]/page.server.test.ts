import { ApiResponseError } from "$lib/server/api/client";
import type { CandidacyDetailResponse } from "$lib/civic-detail/contract";
import { describe, expect, it, vi } from "vitest";
import { load } from "./+page.server";

const CANDIDACY_ID = "88888888-8888-4888-8888-888888888888";
const CONTEST_ID = "77777777-7777-4777-8777-777777777777";
const PERSON_ID = "11111111-1111-4111-8111-111111111111";

function createLoadEvent(requestJson: ReturnType<typeof vi.fn>, id = CANDIDACY_ID) {
  return {
    params: { id },
    locals: {
      api: { requestJson }
    }
  } as unknown as Parameters<typeof load>[0];
}

describe("/candidacy/[id] +page.server load", () => {
  it("returns candidacy detail from /v1/candidacies/{id} with no graph/ER/slug side lookups", async () => {
    const requestJson = vi.fn(async (path: string) => {
      if (path === `/v1/candidacies/${CANDIDACY_ID}`) {
        return {
          id: CANDIDACY_ID,
          person_id: PERSON_ID,
          person_name: "Jane Officeholder",
          contest_id: CONTEST_ID,
          party: "DEM",
          filing_date: "2026-02-01",
          status: "filed",
          incumbent_challenge: "I",
          candidate_number: "17",
          sources: []
        } satisfies CandidacyDetailResponse;
      }

      throw new Error(`unexpected path: ${path}`);
    });

    const data = (await load(createLoadEvent(requestJson))) as CandidacyDetailResponse;

    expect(data.id).toBe(CANDIDACY_ID);
    const calledPaths = requestJson.mock.calls.map(([path]) => String(path));
    expect(calledPaths).toEqual([`/v1/candidacies/${CANDIDACY_ID}`]);
    expect(calledPaths.every((path) => !path.startsWith("/v1/graph/"))).toBe(true);
    expect(calledPaths.every((path) => !path.startsWith("/v1/er/"))).toBe(true);
    expect(calledPaths.every((path) => !path.includes("slug"))).toBe(true);
  });

  it("preserves backend-owned 404 Candidacy not found semantics", async () => {
    const requestJson = vi.fn(async (path: string) => {
      expect(path).toBe(`/v1/candidacies/${CANDIDACY_ID}`);
      throw new ApiResponseError(404, { detail: "Candidacy not found" });
    });

    await expect(load(createLoadEvent(requestJson))).rejects.toMatchObject({
      status: 404,
      body: { detail: "Candidacy not found" }
    });

    expect(requestJson).toHaveBeenCalledTimes(1);
  });

  it("preserves backend plain-text 404 payload semantics", async () => {
    const requestJson = vi.fn(async (path: string) => {
      expect(path).toBe(`/v1/candidacies/${CANDIDACY_ID}`);
      throw new ApiResponseError(404, "Candidacy not found");
    });

    await expect(load(createLoadEvent(requestJson))).rejects.toMatchObject({
      status: 404,
      body: { message: "Candidacy not found" }
    });

    expect(requestJson).toHaveBeenCalledTimes(1);
  });

  it("preserves backend malformed UUID 422 semantics", async () => {
    const malformedId = "not-a-uuid";
    const requestJson = vi.fn(async (path: string) => {
      expect(path).toBe(`/v1/candidacies/${malformedId}`);
      throw new ApiResponseError(422, {
        detail: [{ loc: ["path", "candidacy_id"], msg: "Input should be a valid UUID" }]
      });
    });

    await expect(load(createLoadEvent(requestJson, malformedId))).rejects.toMatchObject({
      status: 422,
      body: { detail: [{ loc: ["path", "candidacy_id"], msg: "Input should be a valid UUID" }] }
    });

    expect(requestJson).toHaveBeenCalledTimes(1);
  });

  it("passes through a minimal candidacy with all-null optional fields and empty sources without coercion", async () => {
    const minimalPayload: CandidacyDetailResponse = {
      id: CANDIDACY_ID,
      person_id: PERSON_ID,
      person_name: "Jane Officeholder",
      contest_id: CONTEST_ID,
      party: null,
      filing_date: null,
      status: null,
      incumbent_challenge: null,
      candidate_number: null,
      sources: []
    };
    const requestJson = vi.fn(async (path: string) => {
      if (path === `/v1/candidacies/${CANDIDACY_ID}`) {
        return minimalPayload;
      }
      throw new Error(`unexpected path: ${path}`);
    });

    const data = (await load(createLoadEvent(requestJson))) as CandidacyDetailResponse;

    expect(data).toBe(minimalPayload);
    expect(data.party).toBeNull();
    expect(data.filing_date).toBeNull();
    expect(data.status).toBeNull();
    expect(data.incumbent_challenge).toBeNull();
    expect(data.candidate_number).toBeNull();
    expect(data.sources).toEqual([]);
    const calledPaths = requestJson.mock.calls.map(([path]) => String(path));
    expect(calledPaths).toEqual([`/v1/candidacies/${CANDIDACY_ID}`]);
  });

  it("passes candidacy payloads through unchanged when backend returns unrecognized status or extra fields", async () => {
    const malformedPayload = {
      id: CANDIDACY_ID,
      person_id: PERSON_ID,
      person_name: "Jane Officeholder",
      contest_id: CONTEST_ID,
      party: "WORK",
      filing_date: "2026-02-01",
      status: "withdrawn_late",
      incumbent_challenge: "X",
      candidate_number: "0",
      sources: [],
      legacy_field_we_do_not_know: "ignored"
    } as unknown as CandidacyDetailResponse;
    const requestJson = vi.fn(async (path: string) => {
      if (path === `/v1/candidacies/${CANDIDACY_ID}`) {
        return malformedPayload;
      }
      throw new Error(`unexpected path: ${path}`);
    });

    const data = (await load(createLoadEvent(requestJson))) as CandidacyDetailResponse & {
      legacy_field_we_do_not_know?: string;
    };

    expect(data).toBe(malformedPayload);
    expect(data.status).toBe("withdrawn_late");
    expect(data.incumbent_challenge).toBe("X");
    expect(data.legacy_field_we_do_not_know).toBe("ignored");
  });
});
