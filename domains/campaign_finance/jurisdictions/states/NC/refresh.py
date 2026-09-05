"""Package-local refresh builder for North Carolina campaign finance."""

from __future__ import annotations

import tempfile
from datetime import datetime
from functools import partial
from pathlib import Path

from core.refresh.jurisdiction_jobs import (
    _build_job_for_source,
    _find_data_source_by_name,
    _find_data_source_for_transaction_type,
)
from core.refresh.runner import RefreshJob, RunnerParameters
from domains.campaign_finance.jurisdictions.config_schema import JurisdictionConfig
from domains.campaign_finance.jurisdictions.states.NC.scraper.cli import run_nc_refresh
from domains.campaign_finance.jurisdictions.states.NC.scraper.load_support import (
    NC_COMMITTEE_DOCUMENT_SOURCE_NAME,
    NC_IE_TRANSACTION_TYPE,
    NC_TRANSACTION_SOURCE_NAME,
)
from domains.civics.loaders.nc_calendar import (
    available_nc_calendar_years,
    resolve_candidate_listing_refresh_cadence,
)
from domains.civics.loaders.ncsbe_candidate_listing import (
    _NCSBE_DATA_SOURCE_NAME,
    load_candidate_listing_from_source,
)

_JURISDICTION = "state/NC"
_MISSING_COMMITTEE_SCOPE_MESSAGE = (
    "NC refresh runner requires both nc_committee_id and nc_committee_name when nc_committee_docs_path is provided"
)


def _resolve_candidate_listing_calendar_year(now: datetime) -> int:
    target_year = now.year + 1 if now.month == 12 else now.year
    available_years = available_nc_calendar_years()
    if not available_years:
        return now.year

    upcoming_years = [year for year in available_years if year >= target_year]
    if upcoming_years:
        return upcoming_years[0]
    return available_years[-1]


def _default_date_range(now: datetime) -> tuple[str, str]:
    year = now.year
    return f"01/01/{year}", f"12/31/{year}"


def _resolve_date_range(*, start: str | None, end: str | None, now: datetime) -> tuple[str, str]:
    if bool(start) != bool(end):
        raise ValueError("nc_date_from and nc_date_to must be provided together")
    default_start, default_end = _default_date_range(now)
    return start or default_start, end or default_end


def _build_ie_jobs(config: JurisdictionConfig, *, parameters: RunnerParameters) -> list[RefreshJob]:
    ie_source = _find_data_source_for_transaction_type(
        config,
        transaction_type=NC_IE_TRANSACTION_TYPE,
    )
    if parameters.nc_ie_document_index_path is None or ie_source is None:
        return []

    document_index_path = parameters.nc_ie_document_index_path
    jobs: list[RefreshJob] = []

    document_index_job = _build_job_for_source(
        key="state-nc-ie-document-index",
        jurisdiction=_JURISDICTION,
        source=ie_source,
        run_callable=partial(
            run_nc_refresh,
            data_type="ie-document-index",
            path=document_index_path,
        ),
    )
    if document_index_job is not None:
        jobs.append(document_index_job)

    transactions_job = _build_job_for_source(
        key="state-nc-ie-transactions",
        jurisdiction=_JURISDICTION,
        source=ie_source,
        run_callable=partial(run_nc_refresh, data_type="ie-transactions"),
    )
    if transactions_job is not None:
        jobs.append(transactions_job)

    return jobs


def _build_committee_discovery_job(config: JurisdictionConfig) -> RefreshJob | None:
    return _build_job_for_source(
        key="state-nc-committee-discovery",
        jurisdiction=_JURISDICTION,
        source=_find_data_source_by_name(
            config,
            source_name=NC_COMMITTEE_DOCUMENT_SOURCE_NAME,
        ),
        run_callable=partial(run_nc_refresh, data_type="committee-discovery"),
    )


def _build_candidate_listing_job(*, parameters: RunnerParameters, now: datetime) -> RefreshJob:
    calendar_year = _resolve_candidate_listing_calendar_year(now)
    return RefreshJob(
        key="civic-nc-candidate-listing",
        domain="civics",
        jurisdiction=_JURISDICTION,
        cadence=resolve_candidate_listing_refresh_cadence(
            year=calendar_year,
            on_date=now.date(),
        ),
        data_source_names=(_NCSBE_DATA_SOURCE_NAME,),
        run_callable=partial(
            load_candidate_listing_from_source,
            year_from=parameters.year_from if parameters.year_from is not None else now.year - 4,
            candidate_listing_path=parameters.candidate_listing_path,
        ),
    )


def _build_transaction_job(
    config: JurisdictionConfig,
    *,
    parameters: RunnerParameters,
    now: datetime,
) -> RefreshJob | None:
    if parameters.nc_committee_docs_path is None:
        return None

    source = _find_data_source_by_name(config, source_name=NC_TRANSACTION_SOURCE_NAME)
    if source is None:
        return None

    if not parameters.nc_committee_id or not parameters.nc_committee_name:
        raise ValueError(_MISSING_COMMITTEE_SCOPE_MESSAGE)

    date_from, date_to = _resolve_date_range(
        start=parameters.nc_date_from,
        end=parameters.nc_date_to,
        now=now,
    )

    def _run_transaction_job() -> object:
        with tempfile.TemporaryDirectory(prefix="refresh-nc-") as temp_dir:
            output_path = Path(temp_dir) / "transactions.csv"
            return run_nc_refresh(
                data_type="transactions",
                download=True,
                output_path=output_path,
                date_from=date_from,
                date_to=date_to,
                committee_id=parameters.nc_committee_id,
                committee_name=parameters.nc_committee_name,
                committee_docs_path=parameters.nc_committee_docs_path,
                trans_type=parameters.nc_trans_type,
            )

    return _build_job_for_source(
        key="state-nc-transactions",
        jurisdiction=_JURISDICTION,
        source=source,
        run_callable=_run_transaction_job,
    )


def build_refresh_jobs(
    config: JurisdictionConfig,
    parameters: RunnerParameters,
    now: datetime,
) -> list[RefreshJob]:
    """Build the package-local NC refresh plan."""
    jobs = _build_ie_jobs(config, parameters=parameters)

    committee_discovery_job = _build_committee_discovery_job(config)
    if committee_discovery_job is not None:
        jobs.append(committee_discovery_job)

    jobs.append(_build_candidate_listing_job(parameters=parameters, now=now))

    transaction_job = _build_transaction_job(config, parameters=parameters, now=now)
    if transaction_job is not None:
        jobs.append(transaction_job)

    return jobs
