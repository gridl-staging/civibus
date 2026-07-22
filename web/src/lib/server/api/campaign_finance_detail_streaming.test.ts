import { ApiResponseError } from "$lib/server/api/client";
import {
  buildCandidateDetailPath,
  buildCandidateIndependentExpendituresPath,
  buildCandidateIndependentExpendituresSummaryPath,
  buildCandidateSummaryPath,
  buildCommitteeDetailPath,
  buildCommitteeFilingBreakdownPath,
  buildCommitteeIndependentExpendituresMadePath,
  buildCommitteeSummaryPath,
  buildCommitteeTransactionsPath
} from "$lib/campaign-finance-detail/contract";
import { describe, expect, it, vi } from "vitest";
import { fetchCandidateDetailBundle, fetchCommitteeDetailBundle } from "./campaign-finance-detail";
import type { ApiClient } from "./client";

const COMMITTEE_ID = "33333333-3333-4333-8333-333333333333";
const CANDIDATE_ID = "44444444-4444-4444-8444-444444444444";
const FILING_ID = "77777777-7777-4777-8777-777777777777";

const CANDIDATE_DETAIL = {
  id: CANDIDATE_ID,
  fec_candidate_id: "H0NC01001",
  name: "Candidate One",
  slug: "candidate-one",
  slug_is_unique: true,
  person_id: null,
  party: null,
  office: "H",
  state: null,
  district: null,
  incumbent_challenge: null,
  principal_committee_id: COMMITTEE_ID,
  sources: []
};

const COMMITTEE_SUMMARY = {
  committee_id: COMMITTEE_ID,
  committee_name: "Committee One",
  total_raised: "125.00",
  total_spent: "50.00",
  net: "75.00",
  transaction_count: 1,
  jurisdiction: "federal/fec",
  data_through: "2026-03-19T00:00:00Z",
  cash_receipts_total: "100.00",
  in_kind_receipts_total: "15.00",
  loan_receipts_total: "10.00",
  contribution_receipts_total: "125.00",
  top_donors: [{ name: "Donor One", total_amount: "80.00", transaction_count: 2 }],
  top_vendors: [{ name: "Vendor One", total_amount: "50.00", transaction_count: 1 }],
  spend_categories: [{ category: "media", total_amount: "25.00", transaction_count: 1 }],
  itemized_transaction_count: 1,
  cycle_summaries: [],
  summary_source: "derived" as const
};

const COMMITTEE_FILING_BREAKDOWN = {
  committee_id: COMMITTEE_ID,
  committee_name: "Committee One",
  filings: [
    {
      filing_id: FILING_ID,
      filing_fec_id: "FEC-100",
      filing_name: "Q1 filing",
      report_type: "Q1",
      amendment_indicator: "N",
      coverage_start_date: "2026-01-01",
      coverage_end_date: "2026-03-31",
      receipt_date: "2026-04-10",
      total_raised: "125.00",
      total_spent: "50.00",
      net: "75.00",
      transaction_count: 1,
      cash_on_hand: "75.00",
      row_id: `${FILING_ID}:N`
    }
  ]
};

const COMMITTEE_IE_ACTIVITY = {
  committee_id: COMMITTEE_ID,
  support_total: "0.00",
  oppose_total: "0.00",
  ie_transaction_count: 0,
  excluded_outlier_count: 0,
  targets: []
};

function buildCommitteeDetailResponse() {
  return {
    id: COMMITTEE_ID,
    fec_committee_id: "C12345678",
    name: "Committee One",
    slug: "committee-one",
    slug_is_unique: true,
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
}

describe("campaign-finance detail api streaming bundle behavior", () => {
  it("starts candidate secondary requests before detail resolves", async () => {
    let resolveDetail: (value: typeof CANDIDATE_DETAIL) => void = () => {};
    const detailPromise = new Promise<typeof CANDIDATE_DETAIL>((resolve) => {
      resolveDetail = resolve;
    });
    const requestJson = vi.fn((path: string) => {
      if (path === buildCandidateDetailPath(CANDIDATE_ID)) {
        return detailPromise;
      }

      if (path === buildCandidateSummaryPath(CANDIDATE_ID)) {
        return Promise.resolve({
          candidate_id: CANDIDATE_ID,
          candidate_name: "Candidate One",
          total_raised: "250.00",
          total_spent: "100.00",
          net: "150.00",
          transaction_count: 5,
          committees: [COMMITTEE_SUMMARY],
          cash_on_hand: null,
          summary_source: "derived",
          itemized_transaction_count: 5
        });
      }

      if (path === buildCandidateIndependentExpendituresPath(CANDIDATE_ID)) {
        return Promise.resolve([]);
      }

      if (path === buildCandidateIndependentExpendituresSummaryPath(CANDIDATE_ID)) {
        return Promise.resolve(null);
      }

      throw new Error(`unexpected path: ${path}`);
    });

    const bundlePromise = fetchCandidateDetailBundle(
      { requestJson: requestJson as ApiClient["requestJson"] },
      { id: CANDIDATE_ID }
    );

    expect(requestJson).toHaveBeenCalledTimes(4);

    resolveDetail(CANDIDATE_DETAIL);
    await bundlePromise;
  });

  it("starts committee secondary requests before detail resolves", async () => {
    let resolveDetail: (value: ReturnType<typeof buildCommitteeDetailResponse>) => void = () => {};
    const detailPromise = new Promise<ReturnType<typeof buildCommitteeDetailResponse>>((resolve) => {
      resolveDetail = resolve;
    });
    const requestJson = vi.fn((path: string) => {
      if (path === buildCommitteeDetailPath(COMMITTEE_ID)) {
        return detailPromise;
      }

      if (path === buildCommitteeTransactionsPath(COMMITTEE_ID)) {
        return Promise.resolve([]);
      }

      if (path === buildCommitteeSummaryPath(COMMITTEE_ID)) {
        return Promise.resolve(COMMITTEE_SUMMARY);
      }

      if (path === buildCommitteeFilingBreakdownPath(COMMITTEE_ID)) {
        return Promise.resolve(COMMITTEE_FILING_BREAKDOWN);
      }

      if (path === buildCommitteeIndependentExpendituresMadePath(COMMITTEE_ID)) {
        return Promise.resolve(COMMITTEE_IE_ACTIVITY);
      }

      throw new Error(`unexpected path: ${path}`);
    });

    const bundlePromise = fetchCommitteeDetailBundle(
      { requestJson: requestJson as ApiClient["requestJson"] },
      { id: COMMITTEE_ID }
    );

    expect(requestJson).toHaveBeenCalledTimes(5);

    resolveDetail(buildCommitteeDetailResponse());
    await bundlePromise;
  });

  it("falls back to empty IE data when candidate IE endpoints return 404", async () => {
    const candidateSummary = {
      candidate_id: CANDIDATE_ID,
      candidate_name: "Candidate Empty",
      total_raised: "0.00",
      total_spent: "0.00",
      net: "0.00",
      transaction_count: 0,
      committees: [],
      cash_on_hand: null,
      summary_source: "derived",
      itemized_transaction_count: 0
    };
    const missingIeError = new ApiResponseError(404, { detail: "No IE records found" });

    const requestJson = vi.fn(async (path: string) => {
      if (path === buildCandidateDetailPath(CANDIDATE_ID)) {
        return {
          ...CANDIDATE_DETAIL,
          name: "Candidate Empty"
        };
      }

      if (path === buildCandidateSummaryPath(CANDIDATE_ID)) {
        return candidateSummary;
      }

      if (path === buildCandidateIndependentExpendituresPath(CANDIDATE_ID)) {
        throw missingIeError;
      }

      if (path === buildCandidateIndependentExpendituresSummaryPath(CANDIDATE_ID)) {
        throw missingIeError;
      }

      throw new Error(`unexpected path: ${path}`);
    });

    const bundle = await fetchCandidateDetailBundle(
      { requestJson: requestJson as ApiClient["requestJson"] },
      { id: CANDIDATE_ID }
    );

    expect(bundle.detail.name).toBe("Candidate Empty");

    expect(bundle.summary).toBeInstanceOf(Promise);
    expect(bundle.ieTransactions).toBeInstanceOf(Promise);
    expect(bundle.ieSummary).toBeInstanceOf(Promise);

    expect(await bundle.summary).toEqual(candidateSummary);
    expect(await bundle.ieTransactions).toEqual([]);
    expect(await bundle.ieSummary).toBeNull();

    expect(requestJson.mock.calls.map(([path]) => path)).toEqual([
      buildCandidateDetailPath(CANDIDATE_ID),
      buildCandidateSummaryPath(CANDIDATE_ID),
      buildCandidateIndependentExpendituresPath(CANDIDATE_ID),
      buildCandidateIndependentExpendituresSummaryPath(CANDIDATE_ID)
    ]);
  });

  it("does not emit unhandled rejections when candidate IE rejects before detail resolves", async () => {
    const earlyIeFailure = new Error("IE request failed");
    let resolveDetail: (value: typeof CANDIDATE_DETAIL) => void = () => {};
    const detailPromise = new Promise<typeof CANDIDATE_DETAIL>((resolve) => {
      resolveDetail = resolve;
    });
    const requestJson = vi.fn((path: string) => {
      if (path === buildCandidateDetailPath(CANDIDATE_ID)) {
        return detailPromise;
      }

      if (path === buildCandidateSummaryPath(CANDIDATE_ID)) {
        return Promise.resolve({
          candidate_id: CANDIDATE_ID,
          candidate_name: "Candidate One",
          total_raised: "250.00",
          total_spent: "100.00",
          net: "150.00",
          transaction_count: 5,
          committees: [COMMITTEE_SUMMARY],
          cash_on_hand: null,
          summary_source: "derived",
          itemized_transaction_count: 5
        });
      }

      if (path === buildCandidateIndependentExpendituresPath(CANDIDATE_ID)) {
        return Promise.reject(earlyIeFailure);
      }

      if (path === buildCandidateIndependentExpendituresSummaryPath(CANDIDATE_ID)) {
        return Promise.resolve(null);
      }

      throw new Error(`unexpected path: ${path}`);
    });

    const unhandled: unknown[] = [];
    const handleUnhandledRejection = (reason: unknown) => {
      unhandled.push(reason);
    };
    process.on("unhandledRejection", handleUnhandledRejection);

    try {
      const bundlePromise = fetchCandidateDetailBundle(
        { requestJson: requestJson as ApiClient["requestJson"] },
        { id: CANDIDATE_ID }
      );

      await Promise.resolve();
      await new Promise<void>((resolve) => {
        setTimeout(resolve, 0);
      });

      expect(unhandled).toEqual([]);

      resolveDetail(CANDIDATE_DETAIL);
      const bundle = await bundlePromise;
      await expect(bundle.summary).resolves.toMatchObject({ candidate_id: CANDIDATE_ID });
      await expect(bundle.ieTransactions).rejects.toThrow("IE request failed");
      await expect(bundle.ieSummary).resolves.toBeNull();
      expect(unhandled).toEqual([]);
    } finally {
      process.off("unhandledRejection", handleUnhandledRejection);
    }
  });

  it("does not emit unhandled rejections when committee secondary requests reject before detail resolves", async () => {
    const earlyTransactionsFailure = new Error("transactions request failed");
    let resolveDetail: (value: ReturnType<typeof buildCommitteeDetailResponse>) => void = () => {};
    const detailPromise = new Promise<ReturnType<typeof buildCommitteeDetailResponse>>((resolve) => {
      resolveDetail = resolve;
    });
    const requestJson = vi.fn((path: string) => {
      if (path === buildCommitteeDetailPath(COMMITTEE_ID)) {
        return detailPromise;
      }

      if (path === buildCommitteeTransactionsPath(COMMITTEE_ID)) {
        return Promise.reject(earlyTransactionsFailure);
      }

      if (path === buildCommitteeSummaryPath(COMMITTEE_ID)) {
        return Promise.resolve(COMMITTEE_SUMMARY);
      }

      if (path === buildCommitteeFilingBreakdownPath(COMMITTEE_ID)) {
        return Promise.resolve(COMMITTEE_FILING_BREAKDOWN);
      }

      if (path === buildCommitteeIndependentExpendituresMadePath(COMMITTEE_ID)) {
        return Promise.resolve(COMMITTEE_IE_ACTIVITY);
      }

      throw new Error(`unexpected path: ${path}`);
    });

    const unhandled: unknown[] = [];
    const handleUnhandledRejection = (reason: unknown) => {
      unhandled.push(reason);
    };
    process.on("unhandledRejection", handleUnhandledRejection);

    try {
      const bundlePromise = fetchCommitteeDetailBundle(
        { requestJson: requestJson as ApiClient["requestJson"] },
        { id: COMMITTEE_ID }
      );

      await Promise.resolve();
      await new Promise<void>((resolve) => {
        setTimeout(resolve, 0);
      });

      expect(unhandled).toEqual([]);

      resolveDetail(buildCommitteeDetailResponse());
      const bundle = await bundlePromise;
      await expect(bundle.transactions).rejects.toThrow("transactions request failed");
      await expect(bundle.summary).resolves.toEqual(COMMITTEE_SUMMARY);
      await expect(bundle.independentExpendituresMade).resolves.toEqual(COMMITTEE_IE_ACTIVITY);
      expect(bundle.filingBreakdown).toEqual(COMMITTEE_FILING_BREAKDOWN);
      expect(unhandled).toEqual([]);
    } finally {
      process.off("unhandledRejection", handleUnhandledRejection);
    }
  });

  it("degrades committee filing breakdown to null when the filing-summary endpoint rejects", async () => {
    let resolveDetail: (value: ReturnType<typeof buildCommitteeDetailResponse>) => void = () => {};
    const detailPromise = new Promise<ReturnType<typeof buildCommitteeDetailResponse>>((resolve) => {
      resolveDetail = resolve;
    });
    const filingBreakdownFailure = new ApiResponseError(503, { detail: "filings unavailable" });
    const requestJson = vi.fn((path: string) => {
      if (path === buildCommitteeDetailPath(COMMITTEE_ID)) {
        return detailPromise;
      }

      if (path === buildCommitteeTransactionsPath(COMMITTEE_ID)) {
        return Promise.resolve([]);
      }

      if (path === buildCommitteeSummaryPath(COMMITTEE_ID)) {
        return Promise.resolve(COMMITTEE_SUMMARY);
      }

      if (path === buildCommitteeFilingBreakdownPath(COMMITTEE_ID)) {
        return Promise.reject(filingBreakdownFailure);
      }

      if (path === buildCommitteeIndependentExpendituresMadePath(COMMITTEE_ID)) {
        return Promise.resolve(COMMITTEE_IE_ACTIVITY);
      }

      throw new Error(`unexpected path: ${path}`);
    });

    const unhandled: unknown[] = [];
    const handleUnhandledRejection = (reason: unknown) => {
      unhandled.push(reason);
    };
    process.on("unhandledRejection", handleUnhandledRejection);

    try {
      const bundlePromise = fetchCommitteeDetailBundle(
        { requestJson: requestJson as ApiClient["requestJson"] },
        { id: COMMITTEE_ID }
      );

      await Promise.resolve();
      await new Promise<void>((resolve) => {
        setTimeout(resolve, 0);
      });

      expect(unhandled).toEqual([]);

      const detail = buildCommitteeDetailResponse();
      resolveDetail(detail);
      const bundle = await bundlePromise;
      expect(bundle.detail).toEqual(detail);
      expect(bundle.filingBreakdown).toBeNull();
      await expect(bundle.transactions).resolves.toEqual([]);
      await expect(bundle.summary).resolves.toEqual(COMMITTEE_SUMMARY);
      await expect(bundle.independentExpendituresMade).resolves.toEqual(COMMITTEE_IE_ACTIVITY);
      expect(unhandled).toEqual([]);
    } finally {
      process.off("unhandledRejection", handleUnhandledRejection);
    }
  });

  it("settles candidate secondary promises when detail rejects", async () => {
    const detailFailure = new ApiResponseError(422, {
      detail: [{ loc: ["path", "candidate_id"], msg: "Input should be a valid UUID" }]
    });
    const allSettledSpy = vi.spyOn(Promise, "allSettled");
    const requestJson = vi.fn((path: string) => {
      if (path === buildCandidateDetailPath(CANDIDATE_ID)) {
        return Promise.reject(detailFailure);
      }

      if (path === buildCandidateSummaryPath(CANDIDATE_ID)) {
        return Promise.resolve({
          candidate_id: CANDIDATE_ID,
          candidate_name: "Candidate One",
          total_raised: "250.00",
          total_spent: "100.00",
          net: "150.00",
          transaction_count: 5,
          committees: [COMMITTEE_SUMMARY],
          cash_on_hand: null,
          summary_source: "derived",
          itemized_transaction_count: 5
        });
      }

      if (path === buildCandidateIndependentExpendituresPath(CANDIDATE_ID)) {
        return Promise.resolve([]);
      }

      if (path === buildCandidateIndependentExpendituresSummaryPath(CANDIDATE_ID)) {
        return Promise.resolve(null);
      }

      throw new Error(`unexpected path: ${path}`);
    });

    try {
      await expect(
        fetchCandidateDetailBundle(
          { requestJson: requestJson as ApiClient["requestJson"] },
          { id: CANDIDATE_ID }
        )
      ).rejects.toBe(detailFailure);

      expect(allSettledSpy).toHaveBeenCalledTimes(1);
      const [secondaryPromises] = allSettledSpy.mock.calls[0];
      expect(Array.isArray(secondaryPromises)).toBe(true);
      expect(secondaryPromises).toHaveLength(3);
    } finally {
      allSettledSpy.mockRestore();
    }
  });

  it("settles committee secondary promises when detail rejects", async () => {
    const detailFailure = new ApiResponseError(422, {
      detail: [{ loc: ["path", "committee_id"], msg: "Input should be a valid UUID" }]
    });
    const allSettledSpy = vi.spyOn(Promise, "allSettled");
    const requestJson = vi.fn((path: string) => {
      if (path === buildCommitteeDetailPath(COMMITTEE_ID)) {
        return Promise.reject(detailFailure);
      }

      if (path === buildCommitteeTransactionsPath(COMMITTEE_ID)) {
        return Promise.resolve([]);
      }

      if (path === buildCommitteeSummaryPath(COMMITTEE_ID)) {
        return Promise.resolve(COMMITTEE_SUMMARY);
      }

      if (path === buildCommitteeFilingBreakdownPath(COMMITTEE_ID)) {
        return Promise.resolve(COMMITTEE_FILING_BREAKDOWN);
      }

      if (path === buildCommitteeIndependentExpendituresMadePath(COMMITTEE_ID)) {
        return Promise.resolve(COMMITTEE_IE_ACTIVITY);
      }

      throw new Error(`unexpected path: ${path}`);
    });

    try {
      await expect(
        fetchCommitteeDetailBundle(
          { requestJson: requestJson as ApiClient["requestJson"] },
          { id: COMMITTEE_ID }
        )
      ).rejects.toBe(detailFailure);

      expect(allSettledSpy).toHaveBeenCalledTimes(1);
      const [secondaryPromises] = allSettledSpy.mock.calls[0];
      expect(Array.isArray(secondaryPromises)).toBe(true);
      expect(secondaryPromises).toHaveLength(4);
    } finally {
      allSettledSpy.mockRestore();
    }
  });
});
