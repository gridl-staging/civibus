import {
  buildCampaignFinanceShardPaths,
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

  const paths =
    shard.kind === "person"
      ? await buildPersonShardPaths(event.locals.api, shard.page)
      : await buildCampaignFinanceShardPaths(event.locals.api, shard.kind, shard.page);
  const xml = buildSitemapXml(paths, event.url.origin, canonicalOrigin());

  return new Response(xml, { headers: sitemapHeaders() });
};
