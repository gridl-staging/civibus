"""Package-owned refresh jobs for San Francisco campaign finance."""

from __future__ import annotations

from datetime import datetime

from core.refresh.jurisdiction_jobs import (
    _build_job_for_source,
    _download_refresh_callable,
    _find_data_source_by_name,
    _optional_job_list,
)
from core.refresh.runner import RefreshJob, RunnerParameters
from domains.campaign_finance.jurisdictions.config_schema import JurisdictionConfig

from .scraper.cli import run_sf_refresh


def build_refresh_jobs(
    config: JurisdictionConfig,
    parameters: RunnerParameters,
    now: datetime,
) -> list[RefreshJob]:
    del parameters, now
    return _optional_job_list(
        _build_job_for_source(
            key="city-sf-transactions",
            jurisdiction=f"{config.jurisdiction.type}/{config.jurisdiction.code}",
            source=_find_data_source_by_name(config, source_name="SF Ethics Campaign Finance Transactions"),
            run_callable=_download_refresh_callable(run_sf_refresh, data_type="transactions"),
        )
    )
