/** Fetch helpers for landing-map and state-detail routes. */
import type { ApiClient } from "./client";
import {
  COUNTRY_GEOMETRY_PATH,
  STATE_CAMPAIGN_FINANCE_DETAIL_PATH_PREFIX,
  STATE_CAMPAIGN_FINANCE_SUMMARY_PATH,
  type GeometryFeatureCollection,
  type StateDetailResponse,
  type StateSummaryItem
} from "./state-pages-contract";

export async function fetchCountryGeometry(
  apiClient: ApiClient
): Promise<GeometryFeatureCollection> {
  return apiClient.requestJson<GeometryFeatureCollection>(COUNTRY_GEOMETRY_PATH);
}

export async function fetchStateCampaignFinanceSummaries(
  apiClient: ApiClient
): Promise<StateSummaryItem[]> {
  return apiClient.requestJson<StateSummaryItem[]>(STATE_CAMPAIGN_FINANCE_SUMMARY_PATH);
}

function toStateDetailPath(stateCode: string): string {
  return `${STATE_CAMPAIGN_FINANCE_DETAIL_PATH_PREFIX}${stateCode.toUpperCase()}`;
}

export async function fetchStateCampaignFinanceDetail(
  apiClient: ApiClient,
  stateCode: string
): Promise<StateDetailResponse> {
  return apiClient.requestJson<StateDetailResponse>(toStateDetailPath(stateCode));
}
