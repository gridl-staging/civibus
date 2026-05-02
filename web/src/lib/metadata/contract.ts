export type DataSourceMetadataResponse = {
  data_source_id: string;
  domain: string;
  jurisdiction: string | null;
  name: string;
  source_url: string;
  update_frequency: string | null;
  last_pull_at: string | null;
  last_pull_status: string | null;
  record_count: number | null;
  latest_source_record_id: string | null;
  latest_source_record_key: string | null;
  latest_source_record_url: string | null;
  latest_source_pull_date: string | null;
};

export type CoverageRegistryResponse = {
  domain: string;
  jurisdiction: string | null;
  data_source_count: number;
  latest_data_source_pull_at: string | null;
  latest_source_pull_date: string | null;
};

export function buildCoverageRegistryPath(): string {
  return "/v1/coverage/registry";
}

export function buildDataSourcesPath(): string {
  return "/v1/data-sources";
}

export function buildCoverageRoutePath(): string {
  return "/coverage";
}

export function buildDataSourcesRoutePath(): string {
  return "/data-sources";
}
