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
  buildElectionDateRoutePath,
  type CongressMemberSummary
} from "$lib/civic-detail/contract";
import { buildEntityRouteHref } from "$lib/entity-detail/contract";
import { buildCanonicalUrl } from "$lib/seo/canonical";
import { CANDIDATE_ROUTE_INDEXABILITY } from "$lib/seo/candidate_indexability";
import { PERSON_ROUTE_INDEXABILITY } from "$lib/seo/person_indexability";
import { fetchCongressMembers, fetchUpcomingElectionTimeline } from "$lib/server/api/civic-detail";
import type { ApiClient } from "$lib/server/api/client";

export const SITEMAP_API_PAGE_LIMIT = 200;
export const SITEMAP_SHARD_SIZE = 10_000;
export const SITEMAP_CACHE_CONTROL = "public, max-age=900";
export const SITEMAP_PROTOCOL_NAMESPACE = "http://www.sitemaps.org/schemas/sitemap/0.9";

const PAGINATION_CONCURRENCY = 6;

export const STATIC_PATHS = [
  "/",
  CONGRESS_PAGE_PATH,
  "/candidates",
  "/committees",
  "/coverage",
  "/calendar",
  "/data-sources"
];

type ListResponse<TItem> = {
  items: TItem[];
  has_next: boolean;
  limit: number;
  offset: number;
};

type ListKind = "candidate" | "committee";

export function sitemapHeaders(): HeadersInit {
  return {
    "Content-Type": "application/xml",
    "Cache-Control": SITEMAP_CACHE_CONTROL
  };
}

export function buildSitemapXml(
  paths: string[],
  eventOrigin: string,
  canonicalOrigin: string | undefined
): string {
  const urls = paths.map((path) => buildCanonicalUrl(new URL(path, eventOrigin), canonicalOrigin));
  const urlEntries = urls.map((loc) => `  <url><loc>${escapeXml(loc)}</loc></url>`).join("\n");

  return [
    '<?xml version="1.0" encoding="UTF-8"?>',
    `<urlset xmlns="${SITEMAP_PROTOCOL_NAMESPACE}">`,
    urlEntries,
    "</urlset>"
  ].join("\n");
}

export function buildSitemapIndexXml(
  shardPaths: string[],
  eventOrigin: string,
  canonicalOrigin: string | undefined
): string {
  const urls = shardPaths.map((path) => buildCanonicalUrl(new URL(path, eventOrigin), canonicalOrigin));
  const entries = urls.map((loc) => `  <sitemap><loc>${escapeXml(loc)}</loc></sitemap>`).join("\n");

  return [
    '<?xml version="1.0" encoding="UTF-8"?>',
    `<sitemapindex xmlns="${SITEMAP_PROTOCOL_NAMESPACE}">`,
    entries,
    "</sitemapindex>"
  ].join("\n");
}

export function canonicalOrigin(): string | undefined {
  return env.PUBLIC_ORIGIN || undefined;
}

export async function buildSitemapIndexPaths(api: ApiClient): Promise<string[]> {
  const [candidatePages, committeePages] = await Promise.all([
    discoverOccupiedShardPages(api, "candidate"),
    discoverOccupiedShardPages(api, "committee")
  ]);
  const paths = [
    "/sitemap-static.xml",
    ...candidatePages.map((page) => `/sitemap-candidate-${page}.xml`),
    ...committeePages.map((page) => `/sitemap-committee-${page}.xml`)
  ];
  if (PERSON_ROUTE_INDEXABILITY.isIndexable) {
    paths.push("/sitemap-person-0.xml");
  }
  return paths;
}

export async function buildStaticShardPaths(api: ApiClient): Promise<string[]> {
  const timelineEntries = await fetchUpcomingElectionTimeline(api);
  const electionPaths = timelineEntries.map((entry) => buildElectionDateRoutePath(entry.date));
  assertShardCapacity("static/election", STATIC_PATHS.length + electionPaths.length);
  return [...STATIC_PATHS, ...electionPaths];
}

export async function buildPersonShardPaths(api: ApiClient, page: number): Promise<string[]> {
  if (page !== 0) {
    throw new Error("Person sitemap shards only support page 0.");
  }
  if (!PERSON_ROUTE_INDEXABILITY.isIndexable) {
    return [];
  }
  const members = await fetchCongressMembers(api);
  assertShardCapacity("person", members.length);
  return members.flatMap(personPath);
}

export async function buildCampaignFinanceShardPaths(
  api: ApiClient,
  kind: ListKind,
  page: number
): Promise<string[]> {
  if (kind === "candidate") {
    const items = await collectShardItems<CandidateListItem>(api, buildCandidateListPath, page);
    return items.flatMap(candidatePath);
  }
  const items = await collectShardItems<CommitteeListItem>(api, buildCommitteeListPath, page);
  return items.map((item) => buildCommitteeHref(item));
}

export function parseShardParams(params: Record<string, string | undefined>):
  | { kind: "candidate" | "committee" | "person"; page: number }
  | null {
  const { kind, page } = params;
  if (kind !== "candidate" && kind !== "committee" && kind !== "person") {
    return null;
  }
  if (page === undefined || !/^(0|[1-9]\d*)$/.test(page)) {
    return null;
  }
  const parsedPage = Number(page);
  // Federal-first people are a single bounded shard, so nonzero pages are not
  // "empty success" cases: they are invalid sitemap routes.
  if (kind === "person" && parsedPage !== 0) {
    return null;
  }
  return { kind, page: parsedPage };
}

async function discoverOccupiedShardPages(api: ApiClient, kind: ListKind): Promise<number[]> {
  const buildPath = kind === "candidate" ? buildCandidateListPath : buildCommitteeListPath;
  const hasItemsAtPage = async (page: number): Promise<boolean> => {
    const offset = page * SITEMAP_SHARD_SIZE;
    const response = await requestListPage(api, buildPath, offset);
    return response.items.length > 0;
  };

  if (!(await hasItemsAtPage(0))) {
    return [];
  }

  let lowOccupied = 0;
  let highEmpty = 1;
  while (await hasItemsAtPage(highEmpty)) {
    lowOccupied = highEmpty;
    highEmpty *= 2;
  }

  while (highEmpty - lowOccupied > 1) {
    const middle = lowOccupied + Math.floor((highEmpty - lowOccupied) / 2);
    if (await hasItemsAtPage(middle)) {
      lowOccupied = middle;
    } else {
      highEmpty = middle;
    }
  }

  return Array.from({ length: lowOccupied + 1 }, (_, page) => page);
}

async function collectShardItems<TItem>(
  api: ApiClient,
  buildPath: (params: { limit: number; offset: number }) => string,
  page: number
): Promise<TItem[]> {
  const startOffset = page * SITEMAP_SHARD_SIZE;
  const endOffset = startOffset + SITEMAP_SHARD_SIZE;
  const pages = new Map<number, TItem[]>();
  const pending = new Map<number, Promise<void>>();
  let nextOffset = startOffset;
  let terminalOffset: number | undefined;
  let firstError: unknown;

  const startPage = (offset: number) => {
    const promise = requestListPage<TItem>(api, buildPath, offset)
      .then((response) => {
        pages.set(offset, response.items);
        if (!response.has_next || response.items.length === 0) {
          terminalOffset =
            terminalOffset === undefined ? offset : Math.min(terminalOffset, offset);
        }
      })
      .catch((error: unknown) => {
        firstError ??= error;
      })
      .finally(() => pending.delete(offset));
    pending.set(offset, promise);
  };

  const fillWindow = () => {
    while (
      firstError === undefined &&
      terminalOffset === undefined &&
      nextOffset < endOffset &&
      pending.size < PAGINATION_CONCURRENCY
    ) {
      startPage(nextOffset);
      nextOffset += SITEMAP_API_PAGE_LIMIT;
    }
  };

  fillWindow();
  while (pending.size > 0) {
    await Promise.race(pending.values());
    fillWindow();
  }
  if (firstError !== undefined) {
    throw firstError;
  }

  const lastOffset =
    terminalOffset === undefined ? endOffset - SITEMAP_API_PAGE_LIMIT : terminalOffset;
  const items: TItem[] = [];
  for (let offset = startOffset; offset <= lastOffset; offset += SITEMAP_API_PAGE_LIMIT) {
    const pageItems = pages.get(offset);
    if (pageItems === undefined) {
      throw new Error("Sitemap pagination finished before all earlier pages resolved.");
    }
    items.push(...pageItems);
  }
  return items;
}

async function requestListPage<TItem>(
  api: ApiClient,
  buildPath: (params: { limit: number; offset: number }) => string,
  offset: number
): Promise<ListResponse<TItem>> {
  const response = await api.requestJson<ListResponse<TItem>>(
    buildPath({ limit: SITEMAP_API_PAGE_LIMIT, offset })
  );
  // Sitemaps are correctness-sensitive: changed pagination units would silently
  // skip or duplicate canonical URLs unless the backend echoes the exact window.
  if (response.limit !== SITEMAP_API_PAGE_LIMIT || response.offset !== offset) {
    throw new Error("Sitemap pagination response drifted from the requested limit or offset.");
  }
  if (!Number.isInteger(response.limit) || response.limit <= 0 || !Number.isInteger(response.offset)) {
    throw new Error("Sitemap pagination requires positive integer limit and integer offset.");
  }
  if (response.items.length === 0 && response.has_next) {
    throw new Error("Sitemap pagination cannot advertise additional pages after an empty result window.");
  }
  return response;
}

function candidatePath(item: CandidateListItem): string[] {
  // Candidate route inclusion must follow the canonical route-policy owners;
  // emitting fallback UUIDs would publish non-canonical crawler targets.
  if (!hasCanonicalCandidateSlug(item) || !CANDIDATE_ROUTE_INDEXABILITY.isIndexable(item)) {
    return [];
  }
  return [buildCandidateHref(item)];
}

function personPath(member: CongressMemberSummary): string[] {
  const path = buildEntityRouteHref("person", member.person_id);
  return path === null ? [] : [path];
}

function assertShardCapacity(kind: string, count: number): void {
  if (count > SITEMAP_SHARD_SIZE) {
    throw new Error(`${kind} collection exceeds sitemap shard size ${SITEMAP_SHARD_SIZE}.`);
  }
}

function escapeXml(text: string): string {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
