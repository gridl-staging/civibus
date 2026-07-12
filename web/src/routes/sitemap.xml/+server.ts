/** Builds the public sitemap from static routes plus campaign-finance detail pages. */
import { env } from "$env/dynamic/public";
import {
  buildCandidateHref,
  buildCandidateListPath,
  buildCommitteeHref,
  buildCommitteeListPath,
  type CandidateListItem,
  type CandidateListResponse,
  type CommitteeListItem,
  type CommitteeListResponse
} from "$lib/campaign-finance-detail/contract";
import {
  CONGRESS_PAGE_PATH,
  buildElectionDateRoutePath,
  type UpcomingElectionTimelineEntry
} from "$lib/civic-detail/contract";
import { fetchUpcomingElectionTimeline } from "$lib/server/api/civic-detail";
import { buildCanonicalUrl } from "$lib/seo/canonical";
import type { RequestHandler } from "@sveltejs/kit";

// Keep the sitemap walker inside the backend's authoritative list max (`limit <= 200`).
const BATCH_LIMIT = 200;

/** Static paths that always appear in the sitemap. */
const STATIC_PATHS = [
  "/",
  CONGRESS_PAGE_PATH,
  "/candidates",
  "/committees",
  "/coverage",
  "/calendar",
  "/data-sources"
];

/**
 * Walks a paginated list endpoint until `has_next` is false,
 * collecting all items across pages.
 */
async function collectAllItems<TItem>(
  requestJson: (path: string) => Promise<{ items: TItem[]; has_next: boolean; limit: number }>,
  buildPath: (params: { limit: number; offset: number }) => string
): Promise<TItem[]> {
  const items: TItem[] = [];
  let offset = 0;
  let hasNext = true;

  while (hasNext) {
    const response = await requestJson(buildPath({ limit: BATCH_LIMIT, offset }));
    if (!Number.isInteger(response.limit) || response.limit <= 0) {
      throw new Error("Sitemap pagination requires a positive integer page size.");
    }
    items.push(...response.items);
    hasNext = response.has_next;
    offset += response.limit;
  }

  return items;
}

function escapeXml(text: string): string {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function buildSitemapXml(paths: string[], eventOrigin: string, canonicalOrigin: string | undefined): string {
  const urls = paths.map((path) => buildCanonicalUrl(new URL(path, eventOrigin), canonicalOrigin));
  const urlEntries = urls.map((loc) => `  <url><loc>${escapeXml(loc)}</loc></url>`).join("\n");

  return [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    urlEntries,
    "</urlset>"
  ].join("\n");
}

/** Returns an XML sitemap that walks candidate and committee list pagination. */
export const GET: RequestHandler = async (event) => {
  const { api } = event.locals;
  const origin = env.PUBLIC_ORIGIN || undefined;
  // Start list and timeline fetches in parallel, then apply branch-local fallbacks.
  const listFetch = Promise.all([
    collectAllItems<CandidateListItem>(
      (path) => api.requestJson<CandidateListResponse>(path),
      buildCandidateListPath
    ),
    collectAllItems<CommitteeListItem>(
      (path) => api.requestJson<CommitteeListResponse>(path),
      buildCommitteeListPath
    )
  ]);
  const timelineFetch = fetchUpcomingElectionTimeline(api);

  const [listResult, timelineResult] = await Promise.allSettled([listFetch, timelineFetch]);

  const [candidatePaths, committeePaths] =
    listResult.status === "fulfilled"
      ? [
          listResult.value[0].map((item) => buildCandidateHref(item)),
          listResult.value[1].map((item) => buildCommitteeHref(item))
        ]
      : [[], []];

  const electionPaths: string[] =
    timelineResult.status === "fulfilled"
      ? timelineResult.value.map((entry) => buildElectionDateRoutePath(entry.date))
      : [];

  // Convert all paths to absolute canonical URLs.
  const allPaths = [...STATIC_PATHS, ...candidatePaths, ...committeePaths, ...electionPaths];
  const xml = buildSitemapXml(allPaths, event.url.origin, origin);

  return new Response(xml, {
    headers: { "Content-Type": "application/xml" }
  });
};
