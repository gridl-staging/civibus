import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "svelte/server";
import CandidateRoutePage from "../../routes/candidate/[id]/+page.svelte";
import CommitteeRoutePage from "../../routes/committee/[id]/+page.svelte";
import type {
  CampaignFinanceTransactionResponse,
  CandidateFundraisingSummary,
  CommitteeFilingBreakdown,
  CommitteeFundraisingSummary,
  IndependentExpenditureResponse,
  IndependentExpenditureSummary
} from "./contract";
import { CANDIDATE_CANONICAL_DATA, COMMITTEE_CANONICAL_DATA } from "./route-render.test-fixtures";

vi.mock("$env/dynamic/public", () => ({
  env: {
    PUBLIC_ORIGIN: "https://civibus.test"
  }
}));

vi.mock("$app/stores", () => ({
  page: {
    subscribe(run: (value: { url: URL }) => void): () => void {
      run({ url: new URL("https://civibus.test/mock-path") });
      return () => {};
    }
  }
}));

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-03-21T12:00:00Z"));
});

afterEach(() => {
  vi.useRealTimers();
});

describe("streaming detail shell with deferred sections", () => {
  it("candidate shell renders immediately with SkeletonPanel placeholders for pending secondary data", () => {
    const rendered = render(CandidateRoutePage, {
      props: {
        data: {
          ...CANDIDATE_CANONICAL_DATA,
          summary: new Promise<CandidateFundraisingSummary>(() => {}),
          ieTransactions: new Promise<IndependentExpenditureResponse[]>(() => {}),
          ieSummary: new Promise<IndependentExpenditureSummary | null>(() => {})
        }
      }
    });

    expect(rendered.body).toContain("Candidate detail");
    expect(rendered.body).toContain("Pat Candidate");
    expect(rendered.body).toContain("Core attributes");

    expect(rendered.body).toContain('aria-busy="true"');

    expect(rendered.body).not.toContain("$250.00");
    expect(rendered.body).not.toContain("$80.00");
  });

  it("committee shell renders immediately with SkeletonPanel placeholders for pending secondary data", () => {
    const rendered = render(CommitteeRoutePage, {
      props: {
        data: {
          ...COMMITTEE_CANONICAL_DATA,
          transactions: new Promise<CampaignFinanceTransactionResponse[]>(() => {}),
          summary: new Promise<CommitteeFundraisingSummary>(() => {})
        }
      }
    });

    expect(rendered.body).toContain("Committee detail");
    expect(rendered.body).toContain("Citizens for Civibus");
    expect(rendered.body).toContain("Core attributes");

    expect(rendered.body).toContain('aria-busy="true"');

    expect(rendered.body).not.toContain("$125.00");
    expect(rendered.body).not.toContain("$40.00");
  });
});
