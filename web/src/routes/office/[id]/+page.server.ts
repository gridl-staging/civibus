import { withApiResponseErrorHandling } from "$lib/server/api/error";
import { fetchOfficeDetail } from "$lib/server/api/civic-detail";
import {
  createGeometryByLevelRecord,
  fetchOptionalCivicGeometry,
  toCivicGeometryLevel
} from "$lib/server/api/civic-geometry";
import type { PageServerLoad } from "./$types";

export const load: PageServerLoad = ({ params, locals }) =>
  withApiResponseErrorHandling(async () => {
    const office = await fetchOfficeDetail(locals.api, { id: params.id });
    const level = toCivicGeometryLevel(office.selected_electoral_division_type);
    const stateCode = office.selected_electoral_division_state?.toUpperCase() ?? null;
    const geometryByLevel = createGeometryByLevelRecord();

    if (level !== null && stateCode !== null) {
      geometryByLevel[level] = await fetchOptionalCivicGeometry(locals.api, {
        level,
        state: stateCode
      });
    }

    return { office, geometryByLevel };
  }, "Backend office detail request failed.");
