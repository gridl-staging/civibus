import { error } from "@sveltejs/kit";
import {
  buildMapLayerVisibilityDefaults,
  getMapLayersForLevel
} from "$lib/config/app";
import { US_STATE_OPTIONS } from "$lib/campaign-finance-detail/filter-options";
import {
  createGeometryByLevelRecord,
  fetchOptionalCivicGeometry,
} from "$lib/server/api/civic-geometry";
import { withApiResponseErrorHandling } from "$lib/server/api/error";
import { fetchCountryGeometry } from "$lib/server/api/state-pages";
import type { PageServerLoad } from "./$types";

const STATE_CAMPAIGN_FINANCE_RETIRED_PAGE = {
  heading: "State campaign finance is outside federal-first v1",
  message:
    "Civibus v1 is focused on federal officials, candidates, committees, and independent expenditures. State campaign-finance totals will return after refresh-time state aggregates and bounded provenance are in place.",
  reversalPath:
    "Reversal requires later refresh-time state aggregates, bounded state provenance, and production query plans that meet the public route latency budget."
};

const VALID_STATE_CODES = new Set(US_STATE_OPTIONS.map((option) => option.code));

/**
 */
export const load: PageServerLoad = ({ params, locals }) =>
  withApiResponseErrorHandling(async () => {
    const stateCode = params.code.toUpperCase();
    if (!VALID_STATE_CODES.has(stateCode)) {
      throw error(404, "State not found.");
    }

    const pageLevel = "state" as const;
    const layers = getMapLayersForLevel(pageLevel);
    const uniqueLevels = [...new Set(layers.map((layer) => layer.level))];
    const geometryByLevel = createGeometryByLevelRecord();

    const [geometry, geometryResponses] = await Promise.all([
      fetchCountryGeometry(locals.api),
      Promise.all(
        uniqueLevels.map(async (level) => {
          const civicGeometry = await fetchOptionalCivicGeometry(locals.api, {
            level,
            state: stateCode
          });
          return { level, geometry: civicGeometry } as const;
        })
      )
    ]);

    for (const response of geometryResponses) {
      geometryByLevel[response.level] = response.geometry;
    }

    return {
      stateCode,
      pageLevel,
      geometryByLevel,
      layerVisibilityDefaults: buildMapLayerVisibilityDefaults(pageLevel),
      geometry,
      retirement: STATE_CAMPAIGN_FINANCE_RETIRED_PAGE
    };
  }, "Backend state detail request failed.");
