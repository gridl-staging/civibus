import {
  buildSitemapXml,
  buildStaticShardPaths,
  canonicalOrigin,
  sitemapHeaders
} from "$lib/server/sitemap";
import type { RequestHandler } from "@sveltejs/kit";

export const GET: RequestHandler = async (event) => {
  const paths = await buildStaticShardPaths(event.locals.api);
  const xml = buildSitemapXml(paths, event.url.origin, canonicalOrigin());

  return new Response(xml, { headers: sitemapHeaders() });
};
