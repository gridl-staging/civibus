"""Package-owned refresh jobs for Virginia campaign finance."""

from __future__ import annotations

from datetime import datetime

from core.refresh.jurisdiction_jobs import _build_download_jobs_for_state
from core.refresh.runner import RefreshJob, RunnerParameters
from domains.campaign_finance.jurisdictions.config_schema import JurisdictionConfig

from .scraper.cli import run_va_refresh


def build_refresh_jobs(
    config: JurisdictionConfig,
    parameters: RunnerParameters,
    now: datetime,
) -> list[RefreshJob]:
    year_month = parameters.va_year_month if parameters.va_year_month is not None else f"{now.year}_{now.month:02d}"
    if year_month and not (
        len(year_month) == 7
        and year_month.isascii()
        and year_month[:4].isdigit()
        and year_month[4] == "_"
        and year_month[5:].isdigit()
        and 1 <= int(year_month[5:]) <= 12
    ):
        raise ValueError("VA year-month must use YYYY_MM format")
    return _build_download_jobs_for_state(
        config,
        jurisdiction=f"state/{config.jurisdiction.code}",
        state_code=config.jurisdiction.code,
        data_types=("contributions", "expenditures"),
        refresh_callable=run_va_refresh,
        year_month=year_month,
    )
