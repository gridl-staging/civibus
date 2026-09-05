"""Package-owned refresh jobs for Pennsylvania campaign finance."""

from __future__ import annotations

from datetime import datetime

from core.refresh.jurisdiction_jobs import _build_download_jobs_for_state
from core.refresh.runner import RefreshJob, RunnerParameters
from domains.campaign_finance.jurisdictions.config_schema import JurisdictionConfig

from .scraper.cli import PA_LOADABLE_REFRESH_DATA_TYPES, run_pa_refresh


def build_refresh_jobs(
    config: JurisdictionConfig,
    parameters: RunnerParameters,
    now: datetime,
) -> list[RefreshJob]:
    year = now.year if parameters.pa_year is None else parameters.pa_year
    return _build_download_jobs_for_state(
        config,
        jurisdiction=f"state/{config.jurisdiction.code}",
        state_code=config.jurisdiction.code,
        data_types=PA_LOADABLE_REFRESH_DATA_TYPES,
        refresh_callable=run_pa_refresh,
        year=year,
    )
