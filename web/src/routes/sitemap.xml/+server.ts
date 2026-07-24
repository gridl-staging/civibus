/** Builds the public sitemap from static routes plus campaign-finance detail pages. */
import { env } from "$env/dynamic/public";
import {
  buildCandidateHref,
  buildCandidateListPath,
  buildCommitteeHref,
  buildCommitteeListPath,
  hasCanonicalCandidateSlug,
  type CandidateListItem,
  type CandidateListResponse,
  type CommitteeListItem,
  type CommitteeListResponse
} from "$lib/campaign-finance-detail/contract";
import {
  CONGRESS_PAGE_PATH,
  buildElectionDateRoutePath
} from "$lib/civic-detail/contract";
import { buildEntityRouteHref } from "$lib/entity-detail/contract";
import { fetchCongressMembers, fetchUpcomingElectionTimeline } from "$lib/server/api/civic-detail";
import { buildCanonicalUrl } from "$lib/seo/canonical";
import { PERSON_ROUTE_INDEXABILITY } from "$lib/seo/person_indexability";
import type { RequestHandler } from "@sveltejs/kit";

// Keep the sitemap walker inside the backend's authoritative list max (`limit <= 200`).
const BATCH_LIMIT = 200;
const PAGINATION_CONCURRENCY = 6;

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
 * Walks a paginated list endpoint until `has_next` is false.
 */
async function collectAllItems<TItem>(
  requestJson: (path: string) => Promise<{ items: TItem[]; has_next: boolean; limit: number }>,
  buildPath: (params: { limit: number; offset: number }) => string
): Promise<TItem[]> {
  const pages = new Map<number, TItem[]>();
  const pendingPages = new Map<number, Promise<void>>();
  let nextOffset = 0;
  let terminalOffset: number | undefined;
  let firstError: unknown;

  const startPage = (offset: number) => {
    const pagePromise = Promise.resolve()
      .then(() => requestJson(buildPath({ limit: BATCH_LIMIT, offset })))
      .then((response) => {
        if (!Number.isInteger(response.limit) || response.limit <= 0) {
          throw new Error("Sitemap pagination requires a positive integer page size.");
        }
        if (response.limit !== BATCH_LIMIT) {
          throw new Error(
            `Sitemap pagination expected backend page size ${BATCH_LIMIT}, got ${response.limit}.`
          );
        }
        pages.set(offset, response.items);
        if (!response.has_next) {
          terminalOffset =
            terminalOffset === undefined ? offset : Math.min(terminalOffset, offset);
        }
      })
      .catch((error: unknown) => {
        firstError ??= error;
      })
      .finally(() => {
        pendingPages.delete(offset);
      });
    pendingPages.set(offset, pagePromise);
  };

  const fillPageWindow = () => {
    while (
      firstError === undefined &&
      terminalOffset === undefined &&
      pendingPages.size < PAGINATION_CONCURRENCY
    ) {
      startPage(nextOffset);
      nextOffset += BATCH_LIMIT;
    }
  };

  fillPageWindow();

  while (pendingPages.size > 0) {
    await Promise.race(pendingPages.values());
    fillPageWindow();
  }

  if (firstError !== undefined) {
    throw firstError;
  }

  if (terminalOffset === undefined) {
    throw new Error("Sitemap pagination did not receive a terminal page.");
  }

  // Concurrent pages can settle out of order; only the lowest terminal offset
  // defines the ordered sitemap item prefix to flatten.
  const orderedItems: TItem[] = [];
  for (let offset = 0; offset <= terminalOffset; offset += BATCH_LIMIT) {
    const pageItems = pages.get(offset);
    if (pageItems === undefined) {
      throw new Error("Sitemap pagination finished before all earlier pages resolved.");
    }
    orderedItems.push(...pageItems);
  }
  return orderedItems;
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
  const congressMemberPathsPromise = PERSON_ROUTE_INDEXABILITY.isIndexable
    ? fetchCongressMembers(api).then((members) =>
        members.flatMap((member) => {
          const personPath = buildEntityRouteHref("person", member.person_id);
          return personPath === null ? [] : [personPath];
        })
      )
    : Promise.resolve<string[]>([]);

  const [candidateItems, committeeItems, timelineEntries, congressMemberPaths] = await Promise.all([
    collectAllItems<CandidateListItem>(
      (path) => api.requestJson<CandidateListResponse>(path),
      buildCandidateListPath
    ),
    collectAllItems<CommitteeListItem>(
      (path) => api.requestJson<CommitteeListResponse>(path),
      buildCommitteeListPath
    ),
    fetchUpcomingElectionTimeline(api),
    congressMemberPathsPromise
  ]);
  const candidatePaths = candidateItems
    .filter(hasCanonicalCandidateSlug)
    .map((item) => buildCandidateHref(item));
  const committeePaths = committeeItems.map((item) => buildCommitteeHref(item));
  const electionPaths: string[] = timelineEntries.map((entry) => buildElectionDateRoutePath(entry.date));

  // Convert all paths to absolute canonical URLs.
  const allPaths = [
    ...STATIC_PATHS,
    ...candidatePaths,
    ...committeePaths,
    ...electionPaths,
    ...congressMemberPaths
  ];
  const xml = buildSitemapXml(allPaths, event.url.origin, origin);

  return new Response(xml, {
    headers: { "Content-Type": "application/xml" }
  });
};
