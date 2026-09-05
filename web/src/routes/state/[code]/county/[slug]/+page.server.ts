import { redirect } from "@sveltejs/kit";
import {
  buildMapLayerVisibilityDefaults,
  type CivicGeometryLevel,
} from "$lib/config/app";
import { buildRegionalAliasRedirect } from "$lib/regional-navigation/presentation";
import { ApiResponseError } from "$lib/server/api/client";
import {
  fetchOptionalCivicGeometry,
  type CivicGeometryFeature,
  type CivicGeometryFeatureCollection,
} from "$lib/server/api/civic-geometry";
import { withApiResponseErrorHandling } from "$lib/server/api/error";
import { fetchRegionalNavigationNode } from "$lib/server/api/state-pages";
import type { RegionalNavigationNode } from "$lib/server/api/state-pages-contract";
import type { PageServerLoad } from "./$types";

function createEmptyFeatureCollection(): CivicGeometryFeatureCollection {
  return {
    type: "FeatureCollection",
    features: [],
  };
}

function createGeometryByLevelRecord(): Record<
  CivicGeometryLevel,
  CivicGeometryFeatureCollection
> {
  return {
    state: createEmptyFeatureCollection(),
    county: createEmptyFeatureCollection(),
    congressional_district: createEmptyFeatureCollection(),
  };
}

function findCountyFeatureByReference(
  countyFeatures: CivicGeometryFeature[],
  node: RegionalNavigationNode,
): CivicGeometryFeature | null {
  const reference = node.geometry_reference;
  if (reference === null) return null;

  const matches = countyFeatures.filter(
    (feature) =>
      feature.properties.name === reference.value &&
      feature.properties.state === node.state_code &&
      feature.properties.division_type === node.kind,
  );
  return matches.length === 1 ? matches[0] : null;
}

export const load: PageServerLoad = ({ params, url, locals }) =>
  withApiResponseErrorHandling(async () => {
    const stateCode = params.code.toUpperCase();
    const countySlug = params.slug;
    if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(countySlug)) {
      throw new ApiResponseError(404, {
        detail: "Regional navigation node not found",
      });
    }

    const navigationNode = await fetchRegionalNavigationNode(locals.api, {
      kind: "county",
      stateCode,
      slug: countySlug,
    });
    const canonicalRedirect = buildRegionalAliasRedirect(navigationNode, url);
    if (canonicalRedirect !== null) redirect(308, canonicalRedirect);

    const [countyGeometry, congressionalDistrictGeometry] = await Promise.all([
      fetchOptionalCivicGeometry(locals.api, {
        level: "county",
        state: stateCode,
      }),
      fetchOptionalCivicGeometry(locals.api, {
        level: "congressional_district",
        state: stateCode,
      }),
    ]);

    const matchedCountyFeature = findCountyFeatureByReference(
      countyGeometry.features,
      navigationNode,
    );

    const geometryByLevel = createGeometryByLevelRecord();
    if (matchedCountyFeature !== null) {
      geometryByLevel.county = {
        type: "FeatureCollection",
        features: [matchedCountyFeature],
      };
    }
    geometryByLevel.congressional_district = congressionalDistrictGeometry;

    return {
      stateCode,
      countySlug,
      countyName: navigationNode.name,
      hasCountyGeometry: matchedCountyFeature !== null,
      pageLevel: "county" as const,
      geometryByLevel,
      layerVisibilityDefaults: buildMapLayerVisibilityDefaults("county"),
      navigationNode,
      // The inherited summary endpoint cannot prove aggregate-level source
      // completeness. Keep the labeled control visible, but never expose its
      // amounts until an owner can prove every included transaction.
      proxySummary: null,
    };
  }, "Backend county drilldown request failed.");
