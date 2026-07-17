import { ApiResponseError } from "$lib/server/api/client";
import {
  buildCandidateDetailPath,
  buildCandidateIndependentExpendituresPath,
  buildCandidateIndependentExpendituresSummaryPath,
  buildCandidateSummaryPath,
  buildCandidatesBySlugPath,
  type CandidateFundraisingSummary,
  type CandidateListItem,
  type CommitteeFundraisingSummary
} from "$lib/campaign-finance-detail/contract";
import type { CandidateDetailBundle } from "$lib/server/api/campaign-finance-detail";
import { describe, expect, it, vi } from "vitest";
import { load } from "./+page.server";

const CANDIDATE_ID = "44444444-4444-4444-8444-444444444444";
const CANDIDATE_ID_ALT = "55555555-5555-4555-8555-555555555555";
const COMMITTEE_ID = "33333333-3333-4333-8333-333333333333";
const CANDIDATE_SLUG = "candidate-one";
const UUID_SHAPED_NON_UUID = "44444444-4444-4444-8444-44444444444z";
const SELECTED_CYCLE_FIELDS = {
  selected_cycle: 2026,
  coverage_start_date: "2025-01-01",
  coverage_end_date: "2026-12-31",
  available_cycles: [2022, 2024, 2026]
};
const RECEIPT_SOURCE_FIELDS = {
  receipt_source_composition: [],
  selected_cycle_coverage_complete: false,
  can_render_share: false,
  receipt_source_caveats: []
};

function createLoadEvent(requestJson: ReturnType<typeof vi.fn>, id = CANDIDATE_ID) {
  return {
    params: { id },
    locals: {
      api: { requestJson }
    }
  } as unknown as Parameters<typeof load>[0];
}

const BASE_CANDIDATE_DETAIL = {
  id: CANDIDATE_ID,
  fec_candidate_id: "H0NC01001",
  name: "Candidate One",
  slug: CANDIDATE_SLUG,
  slug_is_unique: false,
  person_id: null,
  party: null,
  office: "H",
  state: null,
  district: null,
  incumbent_challenge: null,
  principal_committee_id: COMMITTEE_ID,
  sources: []
};

function buildCandidateDetail(overrides: Partial<typeof BASE_CANDIDATE_DETAIL> = {}) {
  return {
    ...BASE_CANDIDATE_DETAIL,
    ...overrides
  };
}

function buildCandidateCommitteeSummary(
  committeeId: string,
  committeeName = "Committee One"
): CommitteeFundraisingSummary {
  return {
    ...SELECTED_CYCLE_FIELDS,
    ...RECEIPT_SOURCE_FIELDS,
    committee_id: committeeId,
    committee_name: committeeName,
    total_raised: "250.00",
    total_spent: "100.00",
    net: "150.00",
    transaction_count: 5,
    jurisdiction: "federal/fec",
    data_through: "2026-03-19T00:00:00Z",
    cash_receipts_total: "250.00",
    in_kind_receipts_total: "0.00",
    loan_receipts_total: "0.00",
    contribution_receipts_total: "250.00",
    top_donors: [],
    top_vendors: [],
    spend_categories: null,
    itemized_transaction_count: 5,
    cycle_summaries: [],
    summary_source: "derived"
  };
}

function buildCandidateSummary(candidateId: string, candidateName = "Candidate One"): CandidateFundraisingSummary {
  return {
    ...SELECTED_CYCLE_FIELDS,
    ...RECEIPT_SOURCE_FIELDS,
    candidate_id: candidateId,
    candidate_name: candidateName,
    total_raised: "250.00",
    total_spent: "100.00",
    net: "150.00",
    transaction_count: 5,
    committees: [buildCandidateCommitteeSummary(COMMITTEE_ID)],
    cash_on_hand: null,
    net_self_funding: null,
    summary_source: "derived" as const,
    itemized_transaction_count: 5
  };
}

function buildSlugMatch(item: Partial<CandidateListItem> & Pick<CandidateListItem, "id" | "name" | "slug">): CandidateListItem {
  return {
    id: item.id,
    fec_candidate_id: item.fec_candidate_id ?? "H0NC01001",
    name: item.name,
    party: item.party ?? null,
    office: item.office ?? "H",
    state: item.state ?? null,
    district: item.district ?? null,
    slug: item.slug,
    slug_is_unique: item.slug_is_unique ?? false
  };
}

describe("/candidate/[id] +page.server load", () => {
  it("returns canonical detail payload for UUID route ids when slug is not unique", async () => {
    const detail = buildCandidateDetail({ slug_is_unique: false });
    const summary = buildCandidateSummary(CANDIDATE_ID);

    const requestJson = vi.fn(async (path: string) => {
      if (path === buildCandidateDetailPath(CANDIDATE_ID)) {
        return detail;
      }

      if (path === buildCandidateSummaryPath(CANDIDATE_ID)) {
        return summary;
      }

      if (path === buildCandidateIndependentExpendituresPath(CANDIDATE_ID)) {
        return [];
      }

      if (path === buildCandidateIndependentExpendituresSummaryPath(CANDIDATE_ID)) {
        return null;
      }

      throw new Error(`unexpected path: ${path}`);
    });

    const data = (await load(createLoadEvent(requestJson))) as CandidateDetailBundle & {
      routeKind: string;
    };

    expect(data.routeKind).toBe("canonical-detail");
    expect(data.detail).toEqual(detail);

    expect(data.summary).toBeInstanceOf(Promise);
    expect(data.ieTransactions).toBeInstanceOf(Promise);
    expect(data.ieSummary).toBeInstanceOf(Promise);

    expect(await data.summary).toEqual(summary);
    expect(await data.ieTransactions).toEqual([]);
    expect(await data.ieSummary).toBeNull();

    expect(requestJson.mock.calls.map(([path]) => path)).toEqual([
      buildCandidateDetailPath(CANDIDATE_ID),
      buildCandidateSummaryPath(CANDIDATE_ID),
      buildCandidateIndependentExpendituresPath(CANDIDATE_ID),
      buildCandidateIndependentExpendituresSummaryPath(CANDIDATE_ID)
    ]);
  });

  it("dispatches slug route ids through fetchCandidatesBySlug before fetching canonical detail bundle", async () => {
    const detail = buildCandidateDetail();
    const summary = buildCandidateSummary(CANDIDATE_ID);
    const matches = [buildSlugMatch({ id: CANDIDATE_ID, name: "Candidate One", slug: CANDIDATE_SLUG, slug_is_unique: true })];

    const requestJson = vi.fn(async (path: string) => {
      if (path === buildCandidatesBySlugPath(CANDIDATE_SLUG)) {
        return matches;
      }

      if (path === buildCandidateDetailPath(CANDIDATE_ID)) {
        return detail;
      }

      if (path === buildCandidateSummaryPath(CANDIDATE_ID)) {
        return summary;
      }

      if (path === buildCandidateIndependentExpendituresPath(CANDIDATE_ID)) {
        return [];
      }

      if (path === buildCandidateIndependentExpendituresSummaryPath(CANDIDATE_ID)) {
        return null;
      }

      throw new Error(`unexpected path: ${path}`);
    });

    const data = (await load(createLoadEvent(requestJson, CANDIDATE_SLUG))) as CandidateDetailBundle & {
      routeKind: string;
    };

    expect(data.routeKind).toBe("canonical-detail");
    expect(data.detail.id).toBe(CANDIDATE_ID);
    expect(requestJson.mock.calls.map(([path]) => path)).toEqual([
      buildCandidatesBySlugPath(CANDIDATE_SLUG),
      buildCandidateDetailPath(CANDIDATE_ID),
      buildCandidateSummaryPath(CANDIDATE_ID),
      buildCandidateIndependentExpendituresPath(CANDIDATE_ID),
      buildCandidateIndependentExpendituresSummaryPath(CANDIDATE_ID)
    ]);
  });

  it("treats 36-character non-UUID ids as slugs and avoids UUID detail requests", async () => {
    const detail = buildCandidateDetail({ id: CANDIDATE_ID_ALT, slug: UUID_SHAPED_NON_UUID, slug_is_unique: true });
    const summary = buildCandidateSummary(CANDIDATE_ID_ALT, "Candidate Alias");
    const matches = [
      buildSlugMatch({
        id: CANDIDATE_ID_ALT,
        name: "Candidate Alias",
        slug: UUID_SHAPED_NON_UUID,
        slug_is_unique: true
      })
    ];

    const requestJson = vi.fn(async (path: string) => {
      if (path === buildCandidatesBySlugPath(UUID_SHAPED_NON_UUID)) {
        return matches;
      }

      if (path === buildCandidateDetailPath(CANDIDATE_ID_ALT)) {
        return detail;
      }

      if (path === buildCandidateSummaryPath(CANDIDATE_ID_ALT)) {
        return summary;
      }

      if (path === buildCandidateIndependentExpendituresPath(CANDIDATE_ID_ALT)) {
        return [];
      }

      if (path === buildCandidateIndependentExpendituresSummaryPath(CANDIDATE_ID_ALT)) {
        return null;
      }

      throw new Error(`unexpected path: ${path}`);
    });

    const data = (await load(createLoadEvent(requestJson, UUID_SHAPED_NON_UUID))) as CandidateDetailBundle;

    expect(data.detail.id).toBe(CANDIDATE_ID_ALT);
    expect(requestJson).not.toHaveBeenCalledWith(buildCandidateDetailPath(UUID_SHAPED_NON_UUID));
    expect(requestJson.mock.calls.map(([path]) => path)).toEqual([
      buildCandidatesBySlugPath(UUID_SHAPED_NON_UUID),
      buildCandidateDetailPath(CANDIDATE_ID_ALT),
      buildCandidateSummaryPath(CANDIDATE_ID_ALT),
      buildCandidateIndependentExpendituresPath(CANDIDATE_ID_ALT),
      buildCandidateIndependentExpendituresSummaryPath(CANDIDATE_ID_ALT)
    ]);
  });

  it("redirects UUID routes to canonical slug paths with 308 when detail slug is unique", async () => {
    const requestJson = vi.fn(async (path: string) => {
      if (path === buildCandidateDetailPath(CANDIDATE_ID)) {
        return buildCandidateDetail({ slug: CANDIDATE_SLUG, slug_is_unique: true });
      }

      if (path === buildCandidateSummaryPath(CANDIDATE_ID)) {
        return buildCandidateSummary(CANDIDATE_ID);
      }

      if (path === buildCandidateIndependentExpendituresPath(CANDIDATE_ID)) {
        return [];
      }

      if (path === buildCandidateIndependentExpendituresSummaryPath(CANDIDATE_ID)) {
        return null;
      }

      throw new Error(`unexpected path: ${path}`);
    });

    await expect(load(createLoadEvent(requestJson))).rejects.toMatchObject({
      status: 308,
      location: `/candidate/${CANDIDATE_SLUG}`
    });
  });

  it("returns deterministic slug-collision payloads without guessing a winner", async () => {
    const requestJson = vi.fn(async (path: string) => {
      if (path === buildCandidatesBySlugPath(CANDIDATE_SLUG)) {
        return [
          buildSlugMatch({ id: CANDIDATE_ID_ALT, name: "Candidate Alpha", slug: CANDIDATE_SLUG }),
          buildSlugMatch({ id: CANDIDATE_ID, name: "Candidate Zeta", slug: CANDIDATE_SLUG })
        ];
      }

      throw new Error(`unexpected path: ${path}`);
    });

    const data = (await load(createLoadEvent(requestJson, CANDIDATE_SLUG))) as {
      routeKind: string;
      slug: string;
      matches: CandidateListItem[];
    };

    expect(data).toEqual({
      routeKind: "slug-collision",
      slug: CANDIDATE_SLUG,
      matches: [
        buildSlugMatch({ id: CANDIDATE_ID_ALT, name: "Candidate Alpha", slug: CANDIDATE_SLUG }),
        buildSlugMatch({ id: CANDIDATE_ID, name: "Candidate Zeta", slug: CANDIDATE_SLUG })
      ]
    });
  });

  it("returns 404 when a slug lookup resolves to zero candidate matches", async () => {
    const requestJson = vi.fn(async (path: string) => {
      if (path === buildCandidatesBySlugPath(CANDIDATE_SLUG)) {
        return [];
      }

      throw new Error(`unexpected path: ${path}`);
    });

    await expect(load(createLoadEvent(requestJson, CANDIDATE_SLUG))).rejects.toMatchObject({
      status: 404,
      body: { detail: `Candidate slug not found: ${CANDIDATE_SLUG}` }
    });
  });

  it("keeps candidate detail routes renderable when IE endpoints return 404", async () => {
    const detail = buildCandidateDetail({ name: "Candidate Empty", slug_is_unique: false });
    const summary = buildCandidateSummary(CANDIDATE_ID, "Candidate Empty");
    const missingIeError = new ApiResponseError(404, { detail: "No IE records found" });

    const requestJson = vi.fn(async (path: string) => {
      if (path === buildCandidateDetailPath(CANDIDATE_ID)) {
        return detail;
      }

      if (path === buildCandidateSummaryPath(CANDIDATE_ID)) {
        return summary;
      }

      if (path === buildCandidateIndependentExpendituresPath(CANDIDATE_ID)) {
        throw missingIeError;
      }

      if (path === buildCandidateIndependentExpendituresSummaryPath(CANDIDATE_ID)) {
        throw missingIeError;
      }

      throw new Error(`unexpected path: ${path}`);
    });

    const data = (await load(createLoadEvent(requestJson))) as CandidateDetailBundle & {
      routeKind: string;
    };

    expect(data.routeKind).toBe("canonical-detail");
    expect(data.detail.name).toBe("Candidate Empty");

    expect(data.ieTransactions).toBeInstanceOf(Promise);
    expect(data.ieSummary).toBeInstanceOf(Promise);

    expect(await data.ieTransactions).toEqual([]);
    expect(await data.ieSummary).toBeNull();
  });

  it("preserves backend 404 payloads", async () => {
    const requestJson = vi.fn().mockRejectedValue(new ApiResponseError(404, { detail: "Candidate not found" }));

    await expect(load(createLoadEvent(requestJson))).rejects.toMatchObject({
      status: 404,
      body: { detail: "Candidate not found" }
    });
  });

  it("preserves backend malformed UUID 422 payloads on the UUID detail branch", async () => {
    const requestJson = vi
      .fn()
      .mockRejectedValue(
        new ApiResponseError(422, { detail: [{ loc: ["path", "candidate_id"], msg: "Input should be a valid UUID" }] })
      );

    await expect(load(createLoadEvent(requestJson, CANDIDATE_ID))).rejects.toMatchObject({
      status: 422,
      body: { detail: [{ loc: ["path", "candidate_id"], msg: "Input should be a valid UUID" }] }
    });
  });
});
