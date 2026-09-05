"""New York City campaign-finance refresh-job builder.

NYC emits a single transactions job, resolved by exact source name.
"""

from __future__ import annotations

from datetime import datetime

from core.refresh.jurisdiction_jobs import (
    _build_job_for_source,
    _download_refresh_callable,
    _find_data_source_by_name,
    _optional_job_list,
)
from core.refresh.runner import RefreshJob, RunnerParameters
from domains.campaign_finance.jurisdictions.cities.NYC.scraper.cli import run_nyc_refresh
from domains.campaign_finance.jurisdictions.config_schema import JurisdictionConfig


def build_refresh_jobs(
    config: JurisdictionConfig,
    parameters: RunnerParameters,
    now: datetime,
) -> list[RefreshJob]:
    city_code = config.jurisdiction.code
    return _optional_job_list(
        _build_job_for_source(
            key=f"city-{city_code.lower()}-transactions",
            jurisdiction=f"{config.jurisdiction.type}/{city_code}",
            source=_find_data_source_by_name(config, source_name="NYC CFB Campaign Contributions"),
            run_callable=_download_refresh_callable(run_nyc_refresh, data_type="transactions"),
        )
    )
