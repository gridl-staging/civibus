"""Package-owned refresh jobs for California campaign finance."""

from __future__ import annotations

from datetime import datetime
from functools import partial

from core.refresh.jurisdiction_jobs import (
    _build_job_for_source,
    _find_data_source_for_transaction_type,
    _optional_job_list,
)
from core.refresh.runner import RefreshJob, RunnerParameters
from domains.campaign_finance.jurisdictions.config_schema import JurisdictionConfig

from .scraper.cli import run_ca_refresh


def build_refresh_jobs(
    config: JurisdictionConfig,
    parameters: RunnerParameters,
    now: datetime,
) -> list[RefreshJob]:
    ca_year_from = parameters.ca_year_from if parameters.ca_year_from is not None else now.year - 4
    return _optional_job_list(
        _build_job_for_source(
            key="state-ca-refresh",
            jurisdiction=f"state/{config.jurisdiction.code}",
            source=_find_data_source_for_transaction_type(config, transaction_type="contributions"),
            run_callable=partial(run_ca_refresh, download=True, year_from=ca_year_from),
        )
    )
