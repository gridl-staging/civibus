import {
  buildCampaignFinanceShardPaths,
  buildContestShardPaths,
  buildPersonShardPaths,
  buildSitemapXml,
  canonicalOrigin,
  parseShardParams,
  sitemapHeaders
} from "$lib/server/sitemap";
import type { RequestHandler } from "@sveltejs/kit";

export const GET: RequestHandler = async (event) => {
  const shard = parseShardParams(event.params);
  if (shard === null) {
    return new Response("Not found", { status: 404 });
  }

  // Three shard families, each with its own id source: people from the congress
  // roster, contests from the upcoming-election timeline, and candidates and
  // committees from the paginated campaign-finance list endpoints.
  let paths: string[];
  if (shard.kind === "person") {
    paths = await buildPersonShardPaths(event.locals.api, shard.page);
  } else if (shard.kind === "contest") {
    paths = await buildContestShardPaths(event.locals.api, shard.page);
  } else {
    paths = await buildCampaignFinanceShardPaths(event.locals.api, shard.kind, shard.page);
  }
  const xml = buildSitemapXml(paths, event.url.origin, canonicalOrigin());

  return new Response(xml, { headers: sitemapHeaders() });
};
