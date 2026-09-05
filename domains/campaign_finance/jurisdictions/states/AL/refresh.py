"""Package-local refresh builder for Alabama campaign finance."""

from __future__ import annotations

from datetime import datetime

from core.refresh.jurisdiction_jobs import _build_download_jobs_for_state
from core.refresh.runner import RefreshJob, RunnerParameters
from domains.campaign_finance.jurisdictions.config_schema import JurisdictionConfig
from domains.campaign_finance.jurisdictions.states.AL.scraper import load_supported_data_types
from domains.campaign_finance.jurisdictions.states.AL.scraper.cli import run_al_refresh

_JURISDICTION = "state/AL"
_STATE_CODE = "AL"


def build_refresh_jobs(
    config: JurisdictionConfig,
    parameters: RunnerParameters,
    now: datetime,
) -> list[RefreshJob]:
    """Build the package-local AL refresh plan."""
    return _build_download_jobs_for_state(
        config,
        jurisdiction=_JURISDICTION,
        state_code=_STATE_CODE,
        data_types=load_supported_data_types(),
        refresh_callable=run_al_refresh,
        year_from=parameters.year_from if parameters.year_from is not None else now.year - 4,
    )
