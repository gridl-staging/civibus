/** Backend contract types for landing-page and state-detail data fetches. */
import type { SourceInfo } from "$lib/entity-detail/contract";

export const STATE_SUPPORT_STATUS_VALUES = [
  "supported",
  "warning",
  "unsupported"
] as const;

export const STATE_COVERAGE_TIER_VALUES = [
  "launch-support candidate",
  "implemented but unproven",
  "freshness-limited",
  "deferred/blocked"
] as const;

export type StateSupportStatus = (typeof STATE_SUPPORT_STATUS_VALUES)[number];
export type StateCoverageTier = (typeof STATE_COVERAGE_TIER_VALUES)[number] | null;

export type StateSummaryItem = {
  state_code: string;
  total_raised: string | null;
  total_spent: string | null;
  net: string | null;
  committee_count: number;
  transaction_count: number;
  federal_candidate_count: number;
  ie_support_total: string | null;
  ie_oppose_total: string | null;
  ie_support_count: number | null;
  ie_oppose_count: number | null;
  coverage_tier: StateCoverageTier;
  support_status: StateSupportStatus;
  supported: boolean;
  warning_text: string | null;
  data_through: string | null;
};

export type StateCandidateTopEntry = {
  candidate_id: string;
  candidate_name: string;
  total_raised: string;
};

export type StateCommitteeTopEntry = {
  committee_id: string;
  committee_name: string;
  total_raised: string;
};

export type StateIndependentExpenditureTopSpender = {
  committee_id: string;
  committee_name: string;
  total_amount: string;
};

export type StateDetailResponse = StateSummaryItem & {
  top_candidates: StateCandidateTopEntry[];
  top_committees: StateCommitteeTopEntry[];
  top_ie_spenders: StateIndependentExpenditureTopSpender[];
  sources: SourceInfo[];
};

export type GeometryFeatureProperties = {
  state: string;
  name: string;
  division_type: string;
  boundary_year: number | null;
};

export type GeometryRingCoordinates = number[][];
export type GeometryPolygonCoordinates = GeometryRingCoordinates[];
export type GeometryMultiPolygonCoordinates = GeometryPolygonCoordinates[];

export type GeometryPolygon = {
  type: "Polygon";
  coordinates: GeometryPolygonCoordinates;
};

export type GeometryMultiPolygon = {
  type: "MultiPolygon";
  coordinates: GeometryMultiPolygonCoordinates;
};

export type GeometryFeature = {
  type: "Feature";
  geometry: GeometryPolygon | GeometryMultiPolygon;
  properties: GeometryFeatureProperties;
};

export type GeometryFeatureCollection = {
  type: "FeatureCollection";
  features: GeometryFeature[];
};

export const COUNTRY_GEOMETRY_PATH = "/v1/geometry?level=country";
export const STATE_CAMPAIGN_FINANCE_SUMMARY_PATH = "/v1/campaign-finance/states/summary";
export const STATE_CAMPAIGN_FINANCE_DETAIL_PATH_PREFIX = "/v1/campaign-finance/states/";
