import {
  buildMapLayerVisibilityDefaults,
  getMapLayersForLevel
} from "$lib/config/app";
import {
  createGeometryByLevelRecord,
  fetchOptionalCivicGeometry,
} from "$lib/server/api/civic-geometry";
import { withApiResponseErrorHandling } from "$lib/server/api/error";
import {
  fetchCountryGeometry,
  fetchStateCampaignFinanceDetail,
  fetchStateCampaignFinanceSummaries
} from "$lib/server/api/state-pages";
import type { PageServerLoad } from "./$types";

export const load: PageServerLoad = ({ params, locals }) =>
  withApiResponseErrorHandling(async () => {
    const stateDetail = await fetchStateCampaignFinanceDetail(locals.api, params.code);
    const stateCode = params.code.toUpperCase();
    const pageLevel = "state" as const;
    const layers = getMapLayersForLevel(pageLevel);
    const uniqueLevels = [...new Set(layers.map((layer) => layer.level))];
    const geometryByLevel = createGeometryByLevelRecord();

    const [geometry, stateSummaries, geometryResponses] = await Promise.all([
      fetchCountryGeometry(locals.api),
      fetchStateCampaignFinanceSummaries(locals.api),
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
      stateDetail,
      geometry,
      stateSummaries
    };
  }, "Backend state detail request failed.");
