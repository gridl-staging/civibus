"""Oregon state-owned refresh builder.

Thin adapter delegating common ``RefreshJob`` construction to the shared
foundation; jurisdiction identity is derived from the loaded config.
"""

from __future__ import annotations

from datetime import datetime

from core.refresh.jurisdiction_jobs import _build_download_jobs_for_state
from core.refresh.runner import RefreshJob, RunnerParameters
from domains.campaign_finance.jurisdictions.config_schema import JurisdictionConfig

from .scraper.cli import OR_LOADABLE_REFRESH_DATA_TYPES, run_or_refresh


def build_refresh_jobs(
    config: JurisdictionConfig,
    parameters: RunnerParameters,
    now: datetime,
) -> list[RefreshJob]:
    state_code = config.jurisdiction.code
    jurisdiction = f"state/{state_code}"
    return _build_download_jobs_for_state(
        config,
        jurisdiction=jurisdiction,
        state_code=state_code,
        data_types=OR_LOADABLE_REFRESH_DATA_TYPES,
        refresh_callable=run_or_refresh,
        year_from=now.year - 4,
    )
