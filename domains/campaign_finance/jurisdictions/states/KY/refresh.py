"""Kentucky campaign-finance refresh-job builder.

KY contributions are election-date scoped because the KREF ExportContributors
endpoint 504s on a full export; each election date becomes its own job.
Expenditures use the standard full-export path. This mirrors the behavior that
the package owns the election-date window needed to build those jobs.
"""

from __future__ import annotations

from datetime import datetime

from core.refresh.jurisdiction_jobs import (
    _build_job_for_source,
    _download_refresh_callable,
    _find_data_source_for_transaction_type,
)
from core.refresh.runner import RefreshJob, RunnerParameters
from domains.campaign_finance.jurisdictions.config_schema import JurisdictionConfig
from domains.campaign_finance.jurisdictions.states.KY.scraper.cli import run_ky_refresh


# KREF's full contributions export times out, so the recent-history window is
# split across the election dates the source can serve reliably.
_CONTRIBUTION_ELECTION_DATES = (
    "5/17/2022",
    "11/8/2022",
    "5/16/2023",
    "11/7/2023",
    "5/21/2024",
    "11/5/2024",
    "5/19/2026",
)


def build_refresh_jobs(
    config: JurisdictionConfig,
    parameters: RunnerParameters,
    now: datetime,
) -> list[RefreshJob]:
    jurisdiction = f"state/{config.jurisdiction.code}"
    year_from = now.year - 4
    jobs: list[RefreshJob] = []

    expenditures_job = _build_job_for_source(
        key="state-ky-expenditures",
        jurisdiction=jurisdiction,
        source=_find_data_source_for_transaction_type(config, transaction_type="expenditures"),
        run_callable=_download_refresh_callable(
            run_ky_refresh,
            data_type="expenditures",
            year_from=year_from,
        ),
    )
    if expenditures_job is not None:
        jobs.append(expenditures_job)

    for election_date in _CONTRIBUTION_ELECTION_DATES:
        contribution_job = _build_job_for_source(
            key=f"state-ky-contributions-{election_date.replace('/', '-')}",
            jurisdiction=jurisdiction,
            source=_find_data_source_for_transaction_type(config, transaction_type="contributions"),
            run_callable=_download_refresh_callable(
                run_ky_refresh,
                data_type="contributions",
                year_from=year_from,
                election_date=f"{election_date} 12:00:00 AM",
            ),
        )
        if contribution_job is not None:
            jobs.append(contribution_job)

    return jobs
