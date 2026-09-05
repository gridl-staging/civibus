"""Philadelphia campaign-finance refresh-job builder.

PHL keeps one Carto SQL table per transaction type, so contributions and
expenditures each become their own job resolved by exact source name.
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
from domains.campaign_finance.jurisdictions.cities.PHL.scraper.cli import run_phl_refresh
from domains.campaign_finance.jurisdictions.config_schema import JurisdictionConfig


_SOURCE_NAME_BY_DATA_TYPE = {
    "contributions": "PHL Campaign Finance Contributions",
    "expenditures": "PHL Campaign Finance Expenditures",
}


def build_refresh_jobs(
    config: JurisdictionConfig,
    parameters: RunnerParameters,
    now: datetime,
) -> list[RefreshJob]:
    city_code = config.jurisdiction.code
    jurisdiction = f"{config.jurisdiction.type}/{city_code}"

    jobs: list[RefreshJob] = []
    for data_type, source_name in _SOURCE_NAME_BY_DATA_TYPE.items():
        jobs.extend(
            _optional_job_list(
                _build_job_for_source(
                    key=f"city-{city_code.lower()}-{data_type}",
                    jurisdiction=jurisdiction,
                    source=_find_data_source_by_name(config, source_name=source_name),
                    run_callable=_download_refresh_callable(run_phl_refresh, data_type=data_type),
                )
            )
        )
    return jobs
