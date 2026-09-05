import { error, redirect } from "@sveltejs/kit";
import {
  buildMapLayerVisibilityDefaults,
  getMapLayersForLevel,
} from "$lib/config/app";
import { US_STATE_OPTIONS } from "$lib/campaign-finance-detail/filter-options";
import {
  createGeometryByLevelRecord,
  fetchOptionalCivicGeometry,
} from "$lib/server/api/civic-geometry";
import { withApiResponseErrorHandling } from "$lib/server/api/error";
import {
  fetchCountryGeometry,
  fetchRegionalChildren,
  fetchRegionalNavigationNode,
} from "$lib/server/api/state-pages";
import {
  buildRegionalAliasRedirect,
  buildRegionalFeatureLinks,
} from "$lib/regional-navigation/presentation";
import type { PageServerLoad } from "./$types";

const VALID_STATE_CODES = new Set(
  US_STATE_OPTIONS.map((option) => option.code),
);

/**
 */
export const load: PageServerLoad = ({ params, url, locals }) =>
  withApiResponseErrorHandling(async () => {
    const stateCode = params.code.toUpperCase();
    if (!VALID_STATE_CODES.has(stateCode)) {
      throw error(404, "State not found.");
    }

    const navigationNode = await fetchRegionalNavigationNode(locals.api, {
      kind: "state",
      stateCode,
    });
    const aliasRedirect = buildRegionalAliasRedirect(navigationNode, url);
    if (aliasRedirect !== null) {
      throw redirect(308, aliasRedirect);
    }

    const pageLevel = "state" as const;
    const layers = getMapLayersForLevel(pageLevel);
    const uniqueLevels = [...new Set(layers.map((layer) => layer.level))];
    const geometryByLevel = createGeometryByLevelRecord();

    const [geometry, geometryResponses, countyNavigation] = await Promise.all([
      fetchCountryGeometry(locals.api),
      Promise.all(
        uniqueLevels.map(async (level) => {
          const civicGeometry = await fetchOptionalCivicGeometry(locals.api, {
            level,
            state: stateCode,
          });
          return { level, geometry: civicGeometry } as const;
        }),
      ),
      fetchRegionalChildren(locals.api, stateCode, "county"),
    ]);

    for (const response of geometryResponses) {
      geometryByLevel[response.level] = response.geometry;
    }

    return {
      stateCode,
      navigationNode,
      pageLevel,
      geometryByLevel,
      featureLinks: buildRegionalFeatureLinks(
        countyNavigation.items,
        geometryByLevel.county,
      ),
      layerVisibilityDefaults: buildMapLayerVisibilityDefaults(pageLevel),
      geometry,
    };
  }, "Backend state detail request failed.");
