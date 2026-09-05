"""Package-local refresh builder for Los Angeles campaign finance."""

from __future__ import annotations

from datetime import datetime

from core.refresh.jurisdiction_jobs import (
    _build_job_for_source,
    _download_refresh_callable,
    _find_data_source_by_name,
    _optional_job_list,
)
from core.refresh.runner import RefreshJob, RunnerParameters
from domains.campaign_finance.jurisdictions.cities.LA.scraper.cli import run_la_refresh
from domains.campaign_finance.jurisdictions.config_schema import JurisdictionConfig

_JURISDICTION = "municipality/LA"
_SOURCE_NAME = "LA Ethics Campaign Contributions"


def build_refresh_jobs(
    config: JurisdictionConfig,
    parameters: RunnerParameters,
    now: datetime,
) -> list[RefreshJob]:
    """Build the package-local Los Angeles refresh plan."""
    del parameters, now

    return _optional_job_list(
        _build_job_for_source(
            key="city-la-transactions",
            jurisdiction=_JURISDICTION,
            source=_find_data_source_by_name(config, source_name=_SOURCE_NAME),
            run_callable=_download_refresh_callable(run_la_refresh, data_type="transactions"),
        )
    )
