"""Georgia campaign-finance refresh-job builder.

GA emits one contributions and one expenditures download job over a candidate-
and date-scoped window. The package owns its default window and candidate
policy so the central registry can compose it without a core import cycle.
"""

from __future__ import annotations

from datetime import datetime

from core.refresh.jurisdiction_jobs import _build_download_transaction_jobs
from core.refresh.runner import RefreshJob, RunnerParameters
from domains.campaign_finance.jurisdictions.config_schema import JurisdictionConfig
from domains.campaign_finance.jurisdictions.states.GA.scraper.cli import run_ga_refresh


def _resolve_date_range(*, start: str | None, end: str | None, now: datetime) -> tuple[str, str]:
    default_start = f"01/01/{now.year - 4}"
    default_end = now.strftime("%m/%d/%Y")
    return start or default_start, end or default_end


def build_refresh_jobs(
    config: JurisdictionConfig,
    parameters: RunnerParameters,
    now: datetime,
) -> list[RefreshJob]:
    date_start, date_end = _resolve_date_range(
        start=parameters.ga_date_start,
        end=parameters.ga_date_end,
        now=now,
    )
    return _build_download_transaction_jobs(
        config,
        jurisdiction=f"state/{config.jurisdiction.code}",
        key_prefix="state-ga",
        data_types=("contributions", "expenditures"),
        refresh_callable=run_ga_refresh,
        candidate=parameters.ga_candidate,
        date_start=date_start,
        date_end=date_end,
    )
