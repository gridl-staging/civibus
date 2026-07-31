/** Builds the public crawler entry point as a bounded sitemap index. */
import {
  buildSitemapIndexPaths,
  buildSitemapIndexXml,
  canonicalOrigin,
  sitemapHeaders
} from "$lib/server/sitemap";
import type { RequestHandler } from "@sveltejs/kit";

export const GET: RequestHandler = async (event) => {
  const shardPaths = await buildSitemapIndexPaths(event.locals.api);
  const xml = buildSitemapIndexXml(shardPaths, event.url.origin, canonicalOrigin());

  return new Response(xml, { headers: sitemapHeaders() });
};
