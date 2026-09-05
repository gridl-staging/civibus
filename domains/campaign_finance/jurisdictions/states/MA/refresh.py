"""Massachusetts campaign-finance refresh-job builder.

MA emits one contributions and one expenditures download job, resolving each by
transaction-type coverage.
"""

from __future__ import annotations

from datetime import datetime

from core.refresh.jurisdiction_jobs import _build_download_jobs_for_state
from core.refresh.runner import RefreshJob, RunnerParameters
from domains.campaign_finance.jurisdictions.config_schema import JurisdictionConfig
from domains.campaign_finance.jurisdictions.states.MA.scraper.cli import run_ma_refresh


def build_refresh_jobs(
    config: JurisdictionConfig,
    parameters: RunnerParameters,
    now: datetime,
) -> list[RefreshJob]:
    state_code = config.jurisdiction.code
    return _build_download_jobs_for_state(
        config,
        jurisdiction=f"state/{state_code}",
        state_code=state_code,
        data_types=("contributions", "expenditures"),
        refresh_callable=run_ma_refresh,
    )
