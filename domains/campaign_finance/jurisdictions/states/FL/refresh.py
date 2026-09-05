"""Package-local refresh builder for Florida campaign finance."""

from __future__ import annotations

from datetime import datetime

from core.refresh.jurisdiction_jobs import _build_download_jobs_for_state
from core.refresh.runner import RefreshJob, RunnerParameters
from domains.campaign_finance.jurisdictions.config_schema import JurisdictionConfig
from domains.campaign_finance.jurisdictions.states.FL.scraper import (
    _load_bulk_download_url_for_data_type,
    load_supported_data_types,
)
from domains.campaign_finance.jurisdictions.states.FL.scraper.cli import run_fl_refresh

_JURISDICTION = "state/FL"
_STATE_CODE = "FL"


def _loadable_download_data_types() -> tuple[str, ...]:
    data_types: list[str] = []
    for data_type in load_supported_data_types():
        try:
            _load_bulk_download_url_for_data_type(data_type)
        except RuntimeError:
            continue
        data_types.append(data_type)
    return tuple(data_types)


def build_refresh_jobs(
    config: JurisdictionConfig,
    parameters: RunnerParameters,
    now: datetime,
) -> list[RefreshJob]:
    """Build the package-local FL refresh plan."""
    del parameters, now

    return _build_download_jobs_for_state(
        config,
        jurisdiction=_JURISDICTION,
        state_code=_STATE_CODE,
        data_types=_loadable_download_data_types(),
        refresh_callable=run_fl_refresh,
    )
