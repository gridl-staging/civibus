import { error, redirect } from "@sveltejs/kit";
import { ApiResponseError } from "$lib/server/api/client";
import { withApiResponseErrorHandling } from "$lib/server/api/error";
import { fetchRegionalNavigationNode } from "$lib/server/api/state-pages";
import { buildRegionalAliasRedirect } from "$lib/regional-navigation/presentation";
import type { PageServerLoad } from "./$types";

export const load: PageServerLoad = ({ params, url, locals }) =>
  withApiResponseErrorHandling(async () => {
    if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(params.slug)) {
      throw new ApiResponseError(404, {
        detail: "Regional navigation node not found",
      });
    }

    const navigationNode = await fetchRegionalNavigationNode(locals.api, {
      kind: "municipality",
      stateCode: params.code.toUpperCase(),
      slug: params.slug,
    });
    if (
      navigationNode.finance.authority_context.filing_authorities.length === 0
    ) {
      throw error(404, "Municipality authority is not publication-ready.");
    }
    const aliasRedirect = buildRegionalAliasRedirect(navigationNode, url);
    if (aliasRedirect !== null) throw redirect(308, aliasRedirect);
    return {
      navigationNode,
      stateCode: navigationNode.state_code,
      municipalityName: navigationNode.name,
    };
  }, "Backend municipality navigation request failed.");
