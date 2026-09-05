"""Package-owned refresh jobs for Wisconsin campaign finance."""

from __future__ import annotations

from datetime import datetime

from core.refresh.jurisdiction_jobs import _build_download_jobs_for_state
from core.refresh.runner import RefreshJob, RunnerParameters
from domains.campaign_finance.jurisdictions.config_schema import JurisdictionConfig

from .scraper.cli import run_wi_refresh


def build_refresh_jobs(
    config: JurisdictionConfig,
    parameters: RunnerParameters,
    now: datetime,
) -> list[RefreshJob]:
    del parameters, now
    return _build_download_jobs_for_state(
        config,
        jurisdiction=f"state/{config.jurisdiction.code}",
        state_code=config.jurisdiction.code,
        data_types=("transactions",),
        refresh_callable=run_wi_refresh,
    )
