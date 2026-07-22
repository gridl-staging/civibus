import { ApiResponseError } from "$lib/server/api/client";
import {
  COMMITTEE_TRANSACTIONS_LIMIT,
  buildCommitteeDetailPath,
  buildCommitteeIndependentExpendituresMadePath,
  buildCommitteeSummaryPath,
  buildCommitteeTransactionsPath,
  buildCommitteesBySlugPath,
  type CommitteeFilingBreakdown,
  type CommitteeFundraisingSummary,
  type CommitteeListItem
} from "$lib/campaign-finance-detail/contract";
import type { CommitteeDetailBundle } from "$lib/server/api/campaign-finance-detail";
import { describe, expect, it, vi } from "vitest";
import { load } from "./+page.server";

const COMMITTEE_ID = "33333333-3333-4333-8333-333333333333";
const COMMITTEE_ID_ALT = "66666666-6666-4666-8666-666666666666";
const COMMITTEE_SLUG = "committee-one";
const UUID_SHAPED_NON_UUID = "33333333-3333-4333-8333-33333333333z";
const COMMITTEE_FILING_BREAKDOWN_PATH = `/v1/committees/${COMMITTEE_ID}/filings/summary?limit=200`;
const COMMITTEE_ALT_FILING_BREAKDOWN_PATH = `/v1/committees/${COMMITTEE_ID_ALT}/filings/summary?limit=200`;
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

function createLoadEvent(requestJson: ReturnType<typeof vi.fn>, id = COMMITTEE_ID) {
  return {
    params: { id },
    locals: {
      api: { requestJson }
    }
  } as unknown as Parameters<typeof load>[0];
}

const BASE_COMMITTEE_DETAIL = {
  id: COMMITTEE_ID,
  fec_committee_id: "C12345678",
  name: "Committee One",
  slug: COMMITTEE_SLUG,
  slug_is_unique: false,
  organization_id: null,
  committee_type: null,
  committee_designation: null,
  party: null,
  state: null,
  city: null,
  zip_code: null,
  treasurer_name: null,
  sources: [],
  linked_candidates: []
};

function buildCommitteeDetail(overrides: Partial<typeof BASE_COMMITTEE_DETAIL> = {}) {
  return {
    ...BASE_COMMITTEE_DETAIL,
    ...overrides
  };
}

function buildCommitteeSummary(
  committeeId: string,
  committeeName = "Committee One"
): CommitteeFundraisingSummary {
  return {
    ...SELECTED_CYCLE_FIELDS,
    ...RECEIPT_SOURCE_FIELDS,
    committee_id: committeeId,
    committee_name: committeeName,
    total_raised: "0.00",
    total_spent: "0.00",
    net: "0.00",
    transaction_count: 0,
    jurisdiction: "federal/fec",
    data_through: "2026-03-19T00:00:00Z",
    cash_receipts_total: "0.00",
    in_kind_receipts_total: "0.00",
    loan_receipts_total: "0.00",
    contribution_receipts_total: "0.00",
    top_donors: [],
    top_vendors: [],
    spend_categories: null,
    itemized_transaction_count: 0,
    cycle_summaries: [],
    summary_source: "derived" as const
  };
}

function buildFilingBreakdown(
  committeeId: string,
  committeeName = "Committee One"
): CommitteeFilingBreakdown {
  return {
    committee_id: committeeId,
    committee_name: committeeName,
    filings: []
  };
}

function buildCommitteeIeActivity(committeeId: string) {
  return {
    committee_id: committeeId,
    support_total: "0.00",
    oppose_total: "0.00",
    ie_transaction_count: 0,
    excluded_outlier_count: 0,
    targets: []
  };
}

function buildSlugMatch(item: Partial<CommitteeListItem> & Pick<CommitteeListItem, "id" | "name" | "slug">): CommitteeListItem {
  return {
    id: item.id,
    fec_committee_id: item.fec_committee_id ?? "C12345678",
    name: item.name,
    committee_type: item.committee_type ?? null,
    party: item.party ?? null,
    state: item.state ?? null,
    slug: item.slug,
    slug_is_unique: item.slug_is_unique ?? false
  };
}

describe("/committee/[id] +page.server load", () => {
  it("returns canonical detail payload for UUID route ids when slug is not unique", async () => {
    const detail = buildCommitteeDetail({ slug_is_unique: false });
    const summary = buildCommitteeSummary(COMMITTEE_ID);
    const filingBreakdown = buildFilingBreakdown(COMMITTEE_ID);
    const independentExpendituresMade = buildCommitteeIeActivity(COMMITTEE_ID);

    const requestJson = vi.fn(async (path: string) => {
      if (path === buildCommitteeDetailPath(COMMITTEE_ID)) {
        return detail;
      }

      if (path === buildCommitteeTransactionsPath(COMMITTEE_ID)) {
        return [];
      }

      if (path === buildCommitteeSummaryPath(COMMITTEE_ID)) {
        return summary;
      }

      if (path === COMMITTEE_FILING_BREAKDOWN_PATH) {
        return filingBreakdown;
      }

      if (path === buildCommitteeIndependentExpendituresMadePath(COMMITTEE_ID)) {
        return independentExpendituresMade;
      }

      throw new Error(`unexpected path: ${path}`);
    });

    const data = (await load(createLoadEvent(requestJson))) as CommitteeDetailBundle & {
      routeKind: string;
    };

    expect(data.routeKind).toBe("canonical-detail");
    expect(data.detail).toEqual(detail);

    expect(data.transactions).toBeInstanceOf(Promise);
    expect(data.summary).toBeInstanceOf(Promise);
    expect(data.filingBreakdown).toEqual(filingBreakdown);
    expect(data.independentExpendituresMade).toBeInstanceOf(Promise);

    expect(await data.transactions).toEqual([]);
    expect(await data.summary).toEqual(summary);
    expect(await data.independentExpendituresMade).toEqual(independentExpendituresMade);

    expect(requestJson.mock.calls.map(([path]) => path)).toEqual([
      buildCommitteeDetailPath(COMMITTEE_ID),
      `/v1/transactions?committee_id=${COMMITTEE_ID}&limit=${COMMITTEE_TRANSACTIONS_LIMIT}`,
      buildCommitteeSummaryPath(COMMITTEE_ID),
      COMMITTEE_FILING_BREAKDOWN_PATH,
      buildCommitteeIndependentExpendituresMadePath(COMMITTEE_ID)
    ]);
  });

  it("dispatches slug route ids through fetchCommitteesBySlug before fetching canonical detail bundle", async () => {
    const detail = buildCommitteeDetail({ slug_is_unique: true });
    const summary = buildCommitteeSummary(COMMITTEE_ID);
    const filingBreakdown = buildFilingBreakdown(COMMITTEE_ID);
    const independentExpendituresMade = buildCommitteeIeActivity(COMMITTEE_ID);
    const matches = [buildSlugMatch({ id: COMMITTEE_ID, name: "Committee One", slug: COMMITTEE_SLUG, slug_is_unique: true })];

    const requestJson = vi.fn(async (path: string) => {
      if (path === buildCommitteesBySlugPath(COMMITTEE_SLUG)) {
        return matches;
      }

      if (path === buildCommitteeDetailPath(COMMITTEE_ID)) {
        return detail;
      }

      if (path === buildCommitteeTransactionsPath(COMMITTEE_ID)) {
        return [];
      }

      if (path === buildCommitteeSummaryPath(COMMITTEE_ID)) {
        return summary;
      }

      if (path === COMMITTEE_FILING_BREAKDOWN_PATH) {
        return filingBreakdown;
      }

      if (path === buildCommitteeIndependentExpendituresMadePath(COMMITTEE_ID)) {
        return independentExpendituresMade;
      }

      throw new Error(`unexpected path: ${path}`);
    });

    const data = (await load(createLoadEvent(requestJson, COMMITTEE_SLUG))) as CommitteeDetailBundle & {
      routeKind: string;
    };

    expect(data.routeKind).toBe("canonical-detail");
    expect(data.detail.id).toBe(COMMITTEE_ID);
    expect(requestJson.mock.calls.map(([path]) => path)).toEqual([
      buildCommitteesBySlugPath(COMMITTEE_SLUG),
      buildCommitteeDetailPath(COMMITTEE_ID),
      buildCommitteeTransactionsPath(COMMITTEE_ID),
      buildCommitteeSummaryPath(COMMITTEE_ID),
      COMMITTEE_FILING_BREAKDOWN_PATH,
      buildCommitteeIndependentExpendituresMadePath(COMMITTEE_ID)
    ]);
  });

  it("treats 36-character non-UUID ids as slugs and avoids UUID detail requests", async () => {
    const detail = buildCommitteeDetail({ id: COMMITTEE_ID_ALT, slug: UUID_SHAPED_NON_UUID, slug_is_unique: true });
    const summary = buildCommitteeSummary(COMMITTEE_ID_ALT, "Committee Alias");
    const filingBreakdown = buildFilingBreakdown(COMMITTEE_ID_ALT, "Committee Alias");
    const independentExpendituresMade = buildCommitteeIeActivity(COMMITTEE_ID_ALT);
    const matches = [
      buildSlugMatch({
        id: COMMITTEE_ID_ALT,
        name: "Committee Alias",
        slug: UUID_SHAPED_NON_UUID,
        slug_is_unique: true
      })
    ];

    const requestJson = vi.fn(async (path: string) => {
      if (path === buildCommitteesBySlugPath(UUID_SHAPED_NON_UUID)) {
        return matches;
      }

      if (path === buildCommitteeDetailPath(COMMITTEE_ID_ALT)) {
        return detail;
      }

      if (path === buildCommitteeTransactionsPath(COMMITTEE_ID_ALT)) {
        return [];
      }

      if (path === buildCommitteeSummaryPath(COMMITTEE_ID_ALT)) {
        return summary;
      }

      if (path === COMMITTEE_ALT_FILING_BREAKDOWN_PATH) {
        return filingBreakdown;
      }

      if (path === buildCommitteeIndependentExpendituresMadePath(COMMITTEE_ID_ALT)) {
        return independentExpendituresMade;
      }

      throw new Error(`unexpected path: ${path}`);
    });

    const data = (await load(createLoadEvent(requestJson, UUID_SHAPED_NON_UUID))) as CommitteeDetailBundle;

    expect(data.detail.id).toBe(COMMITTEE_ID_ALT);
    expect(requestJson).not.toHaveBeenCalledWith(buildCommitteeDetailPath(UUID_SHAPED_NON_UUID));
    expect(requestJson.mock.calls.map(([path]) => path)).toEqual([
      buildCommitteesBySlugPath(UUID_SHAPED_NON_UUID),
      buildCommitteeDetailPath(COMMITTEE_ID_ALT),
      buildCommitteeTransactionsPath(COMMITTEE_ID_ALT),
      buildCommitteeSummaryPath(COMMITTEE_ID_ALT),
      COMMITTEE_ALT_FILING_BREAKDOWN_PATH,
      buildCommitteeIndependentExpendituresMadePath(COMMITTEE_ID_ALT)
    ]);
  });

  it("redirects UUID routes to canonical slug paths with 308 when detail slug is unique", async () => {
    const requestJson = vi.fn(async (path: string) => {
      if (path === buildCommitteeDetailPath(COMMITTEE_ID)) {
        return buildCommitteeDetail({ slug: COMMITTEE_SLUG, slug_is_unique: true });
      }

      if (path === buildCommitteeTransactionsPath(COMMITTEE_ID)) {
        return [];
      }

      if (path === buildCommitteeSummaryPath(COMMITTEE_ID)) {
        return buildCommitteeSummary(COMMITTEE_ID);
      }

      if (path === COMMITTEE_FILING_BREAKDOWN_PATH) {
        return buildFilingBreakdown(COMMITTEE_ID);
      }

      if (path === buildCommitteeIndependentExpendituresMadePath(COMMITTEE_ID)) {
        return buildCommitteeIeActivity(COMMITTEE_ID);
      }

      throw new Error(`unexpected path: ${path}`);
    });

    await expect(load(createLoadEvent(requestJson))).rejects.toMatchObject({
      status: 308,
      location: `/committee/${COMMITTEE_SLUG}`
    });
  });

  it("returns canonical detail when filing breakdown fetch fails and degrades that panel to null", async () => {
    const detail = buildCommitteeDetail({ slug_is_unique: false });
    const summary = buildCommitteeSummary(COMMITTEE_ID);
    const independentExpendituresMade = buildCommitteeIeActivity(COMMITTEE_ID);
    const filingBreakdownFailure = new ApiResponseError(503, { detail: "filing summary unavailable" });

    const requestJson = vi.fn(async (path: string) => {
      if (path === buildCommitteeDetailPath(COMMITTEE_ID)) {
        return detail;
      }

      if (path === buildCommitteeTransactionsPath(COMMITTEE_ID)) {
        return [];
      }

      if (path === buildCommitteeSummaryPath(COMMITTEE_ID)) {
        return summary;
      }

      if (path === COMMITTEE_FILING_BREAKDOWN_PATH) {
        throw filingBreakdownFailure;
      }

      if (path === buildCommitteeIndependentExpendituresMadePath(COMMITTEE_ID)) {
        return independentExpendituresMade;
      }

      throw new Error(`unexpected path: ${path}`);
    });

    const data = (await load(createLoadEvent(requestJson))) as CommitteeDetailBundle & {
      routeKind: string;
    };

    expect(data.routeKind).toBe("canonical-detail");
    expect(data.detail).toEqual(detail);
    expect(data.filingBreakdown).toBeNull();
    await expect(data.transactions).resolves.toEqual([]);
    await expect(data.summary).resolves.toEqual(summary);
    await expect(data.independentExpendituresMade).resolves.toEqual(independentExpendituresMade);
  });

  it("returns deterministic slug-collision payloads without guessing a winner", async () => {
    const requestJson = vi.fn(async (path: string) => {
      if (path === buildCommitteesBySlugPath(COMMITTEE_SLUG)) {
        return [
          buildSlugMatch({ id: COMMITTEE_ID_ALT, name: "Committee Alpha", slug: COMMITTEE_SLUG }),
          buildSlugMatch({ id: COMMITTEE_ID, name: "Committee Zeta", slug: COMMITTEE_SLUG })
        ];
      }

      throw new Error(`unexpected path: ${path}`);
    });

    const data = (await load(createLoadEvent(requestJson, COMMITTEE_SLUG))) as {
      routeKind: string;
      slug: string;
      matches: CommitteeListItem[];
    };

    expect(data).toEqual({
      routeKind: "slug-collision",
      slug: COMMITTEE_SLUG,
      matches: [
        buildSlugMatch({ id: COMMITTEE_ID_ALT, name: "Committee Alpha", slug: COMMITTEE_SLUG }),
        buildSlugMatch({ id: COMMITTEE_ID, name: "Committee Zeta", slug: COMMITTEE_SLUG })
      ]
    });
  });

  it("returns 404 when a slug lookup resolves to zero committee matches", async () => {
    const requestJson = vi.fn(async (path: string) => {
      if (path === buildCommitteesBySlugPath(COMMITTEE_SLUG)) {
        return [];
      }

      throw new Error(`unexpected path: ${path}`);
    });

    await expect(load(createLoadEvent(requestJson, COMMITTEE_SLUG))).rejects.toMatchObject({
      status: 404,
      body: { detail: `Committee slug not found: ${COMMITTEE_SLUG}` }
    });
  });

  it("preserves backend 404 payloads", async () => {
    const requestJson = vi.fn().mockRejectedValue(new ApiResponseError(404, { detail: "Committee not found" }));

    await expect(load(createLoadEvent(requestJson))).rejects.toMatchObject({
      status: 404,
      body: { detail: "Committee not found" }
    });
  });

  it("preserves backend malformed UUID 422 payloads on the UUID detail branch", async () => {
    const requestJson = vi
      .fn()
      .mockRejectedValue(
        new ApiResponseError(422, { detail: [{ loc: ["path", "committee_id"], msg: "Input should be a valid UUID" }] })
      );

    await expect(load(createLoadEvent(requestJson, COMMITTEE_ID))).rejects.toMatchObject({
      status: 422,
      body: { detail: [{ loc: ["path", "committee_id"], msg: "Input should be a valid UUID" }] }
    });
  });
});
