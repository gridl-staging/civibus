import { describe, expect, it, vi } from "vitest";
import { buildCandidateHref } from "./contract";
import { loadCampaignFinanceDetailPage } from "./page-load";

const CANDIDATE_ID = "44444444-4444-4444-8444-444444444444";

describe("loadCampaignFinanceDetailPage", () => {
  it("returns canonical detail payloads when the resolved route stays canonical", async () => {
    const resolveRoute = vi.fn().mockResolvedValue({
      routeKind: "canonical-detail",
      canonicalId: CANDIDATE_ID,
      routeIdType: "uuid"
    });
    const fetchBundle = vi.fn().mockResolvedValue({
      detail: {
        id: CANDIDATE_ID,
        slug: "candidate-one",
        slug_is_unique: false,
        identity_is_safe: true
      },
      summary: { total_raised: "250.00" }
    });

    const data = await loadCampaignFinanceDetailPage({
      apiClient: { requestJson: vi.fn() },
      routeId: CANDIDATE_ID,
      fallbackMessage: "Backend candidate detail request failed.",
      resolveRoute,
      fetchBundle,
      buildCanonicalHref: buildCandidateHref
    });

    expect(data).toEqual({
      routeKind: "canonical-detail",
      detail: {
        id: CANDIDATE_ID,
        slug: "candidate-one",
        slug_is_unique: false,
        identity_is_safe: true
      },
      summary: { total_raised: "250.00" }
    });
    expect(resolveRoute).toHaveBeenCalledWith({ requestJson: expect.any(Function) }, CANDIDATE_ID);
    expect(fetchBundle).toHaveBeenCalledWith({ requestJson: expect.any(Function) }, { id: CANDIDATE_ID });
  });

  it("passes slug-collision payloads through without fetching a detail bundle", async () => {
    const apiClient = { requestJson: vi.fn() };
    const resolveRoute = vi.fn().mockResolvedValue({
      routeKind: "slug-collision",
      slug: "candidate-one",
      matches: [{ id: CANDIDATE_ID, name: "Candidate One" }]
    });
    const fetchBundle = vi.fn();

    const data = await loadCampaignFinanceDetailPage({
      apiClient,
      routeId: "candidate-one",
      fallbackMessage: "Backend candidate detail request failed.",
      resolveRoute,
      fetchBundle,
      buildCanonicalHref: (detail) => `/candidate/${detail.slug}`
    });

    expect(data).toEqual({
      routeKind: "slug-collision",
      slug: "candidate-one",
      matches: [{ id: CANDIDATE_ID, name: "Candidate One" }]
    });
    expect(fetchBundle).not.toHaveBeenCalled();
  });

  it("redirects UUID routes to canonical slug hrefs when the fetched detail has a unique slug", async () => {
    const resolveRoute = vi.fn().mockResolvedValue({
      routeKind: "canonical-detail",
      canonicalId: CANDIDATE_ID,
      routeIdType: "uuid"
    });
    const fetchBundle = vi.fn().mockResolvedValue({
      detail: {
        id: CANDIDATE_ID,
        slug: "candidate-one",
        slug_is_unique: true,
        identity_is_safe: true
      }
    });

    await expect(
      loadCampaignFinanceDetailPage({
        apiClient: { requestJson: vi.fn() },
        routeId: CANDIDATE_ID,
        fallbackMessage: "Backend candidate detail request failed.",
        resolveRoute,
        fetchBundle,
        buildCanonicalHref: (detail) => `/candidate/${detail.slug}`
      })
    ).rejects.toMatchObject({
      status: 308,
      location: "/candidate/candidate-one"
    });
  });

  it("does not redirect UUID candidate routes to unsafe slug hrefs", async () => {
    const resolveRoute = vi.fn().mockResolvedValue({
      routeKind: "canonical-detail",
      canonicalId: CANDIDATE_ID,
      routeIdType: "uuid"
    });
    const fetchBundle = vi.fn().mockResolvedValue({
      detail: {
        id: CANDIDATE_ID,
        slug: "212-n-half-w-john-rodney-howard-mr",
        slug_is_unique: true,
        identity_is_safe: false
      }
    });

    const data = await loadCampaignFinanceDetailPage({
      apiClient: { requestJson: vi.fn() },
      routeId: CANDIDATE_ID,
      fallbackMessage: "Backend candidate detail request failed.",
      resolveRoute,
      fetchBundle,
      buildCanonicalHref: buildCandidateHref
    });

    expect(data).toEqual({
      routeKind: "canonical-detail",
      detail: {
        id: CANDIDATE_ID,
        slug: "212-n-half-w-john-rodney-howard-mr",
        slug_is_unique: true,
        identity_is_safe: false
      }
    });
  });

  it("redirects direct unsafe slug requests back to the candidate UUID href", async () => {
    const unsafeSlug = "212-n-half-w-john-rodney-howard-mr";
    const resolveRoute = vi.fn().mockResolvedValue({
      routeKind: "canonical-detail",
      canonicalId: CANDIDATE_ID,
      routeIdType: "slug"
    });
    const fetchBundle = vi.fn().mockResolvedValue({
      detail: {
        id: CANDIDATE_ID,
        slug: unsafeSlug,
        slug_is_unique: true,
        identity_is_safe: false
      }
    });

    await expect(
      loadCampaignFinanceDetailPage({
        apiClient: { requestJson: vi.fn() },
        routeId: unsafeSlug,
        fallbackMessage: "Backend candidate detail request failed.",
        resolveRoute,
        fetchBundle,
        buildCanonicalHref: buildCandidateHref
      })
    ).rejects.toMatchObject({
      status: 308,
      location: `/candidate/${CANDIDATE_ID}`
    });
  });
});
