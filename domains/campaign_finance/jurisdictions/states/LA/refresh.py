"""Louisiana state-owned refresh builder.

Thin adapter: delegates all common ``RefreshJob`` construction to the shared
foundation and derives jurisdiction identity from the loaded config so the LA
state package can never be confused with the Los Angeles city package.
"""

from __future__ import annotations

from datetime import datetime

from core.refresh.jurisdiction_jobs import _build_download_jobs_for_state
from core.refresh.runner import RefreshJob, RunnerParameters
from domains.campaign_finance.jurisdictions.config_schema import JurisdictionConfig

from .scraper.cli import LA_LOADABLE_REFRESH_DATA_TYPES, run_la_refresh


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
        data_types=LA_LOADABLE_REFRESH_DATA_TYPES,
        refresh_callable=run_la_refresh,
        year=now.year,
    )
