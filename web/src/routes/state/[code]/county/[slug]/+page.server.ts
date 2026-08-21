import {
  buildMapLayerVisibilityDefaults,
  type CivicGeometryLevel
} from "$lib/config/app";
import { buildTrustSection } from "$lib/detail-trust/presentation";
import { extractCountySlugFromDivisionName } from "$lib/region-map/county-slug";
import {
  fetchCountyCampaignFinanceSummary
} from "$lib/server/api/campaign-finance-detail";
import { ApiResponseError } from "$lib/server/api/client";
import {
  fetchCivicGeometry,
  type CivicGeometryFeature,
  type CivicGeometryFeatureCollection
} from "$lib/server/api/civic-geometry";
import { withApiResponseErrorHandling } from "$lib/server/api/error";
import type { IdentityGatedCountySummaryLinkedCandidate } from "$lib/server/api/state-pages-contract";
import type { PageServerLoad } from "./$types";

function createEmptyFeatureCollection(): CivicGeometryFeatureCollection {
  return {
    type: "FeatureCollection",
    features: []
  };
}

function createGeometryByLevelRecord(): Record<CivicGeometryLevel, CivicGeometryFeatureCollection> {
  return {
    state: createEmptyFeatureCollection(),
    county: createEmptyFeatureCollection(),
    congressional_district: createEmptyFeatureCollection()
  };
}

function buildCountyName(countySlug: string): string {
  return countySlug
    .split("_")
    .filter((segment) => segment !== "")
    .map((segment) => `${segment[0]?.toUpperCase() ?? ""}${segment.slice(1)}`)
    .join(" ");
}

function findCountyFeatureBySlug(
  countyFeatures: CivicGeometryFeature[],
  stateCode: string,
  countySlug: string
): CivicGeometryFeature | null {
  for (const countyFeature of countyFeatures) {
    const featureCountySlug = extractCountySlugFromDivisionName(countyFeature.properties.name, stateCode);
    if (featureCountySlug === countySlug) {
      return countyFeature;
    }
  }

  return null;
}

/**
 */
export const load: PageServerLoad = ({ params, locals }) =>
  withApiResponseErrorHandling(async () => {
    const stateCode = params.code.toUpperCase();
    const countySlug = params.slug.toLowerCase();

    // Slug rule must stay aligned with `_slugify_name` in tiger_geometry.py and
    // `_COUNTY_PROXY_CITIES_BY_STATE` keys: lowercase with non-alphanumeric runs collapsed to `_`.
    const [countyGeometry, congressionalDistrictGeometry] = await Promise.all([
      fetchCivicGeometry(locals.api, { level: "county", state: stateCode }),
      fetchCivicGeometry(locals.api, { level: "congressional_district", state: stateCode })
    ]);

    const matchedCountyFeature = findCountyFeatureBySlug(countyGeometry.features, stateCode, countySlug);
    if (matchedCountyFeature === null) {
      throw new ApiResponseError(404, { detail: "County geometry not found" });
    }

    const summary = await fetchCountyCampaignFinanceSummary(locals.api, {
      state: stateCode,
      countySlug
    });
    // County linked-candidate rows are cf.candidate-derived (the API joins
    // cf.candidate through cf.candidate_committee_link), so the candidate
    // identity gate applies directly: the API computes identity_is_safe per
    // row and the render routes candidate_name through the shared
    // formatCandidatePublicName owner. Retyping (not casting a lie: the extra
    // field is optional) is what carries the flag into PageData for the page.
    const topLinkedCandidates: IdentityGatedCountySummaryLinkedCandidate[] =
      summary.top_linked_candidates;

    const geometryByLevel = createGeometryByLevelRecord();
    geometryByLevel.county = {
      type: "FeatureCollection",
      features: [matchedCountyFeature]
    };
    geometryByLevel.congressional_district = congressionalDistrictGeometry;

    return {
      stateCode,
      countySlug,
      countyName: buildCountyName(countySlug),
      pageLevel: "county" as const,
      geometryByLevel,
      layerVisibilityDefaults: buildMapLayerVisibilityDefaults("county"),
      donor_total_cents: summary.donor_total_cents,
      transaction_count: summary.transaction_count,
      top_recipient_committees: summary.top_recipient_committees,
      top_linked_candidates: topLinkedCandidates,
      trustSection: buildTrustSection(summary.sources, { includeJurisdictionFreshnessNote: true })
    };
  }, "Backend county drilldown request failed.");
