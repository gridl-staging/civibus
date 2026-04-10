"""Campaign-finance refresh job assembly and execution helpers."""

from __future__ import annotations

import argparse
import sys
import tempfile
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from functools import partial
from pathlib import Path
from typing import Callable
from urllib.request import urlretrieve
from uuid import UUID

import psycopg

from core.db import get_connection
from domains.campaign_finance.ingest.bulk_cli import CliConfig, LoadRequest, dispatch_load, fec_schedule_e_url
from domains.campaign_finance.ingest.bulk_loader import (
    FEC_BULK_DATA_SOURCE_NAME,
    ensure_fec_bulk_data_source,
    sync_data_source_metadata,
)
from domains.campaign_finance.ingest.cli import run_fec_refresh
from domains.campaign_finance.jurisdictions.config_schema import (
    JurisdictionConfig,
    discover_jurisdiction_configs,
    load_jurisdiction_config,
)
from domains.campaign_finance.jurisdictions.states.AL.scraper import load_supported_data_types as load_al_data_types
from domains.campaign_finance.jurisdictions.states.AL.scraper.cli import run_al_refresh
from domains.campaign_finance.jurisdictions.states.CA.scraper.cli import run_ca_refresh
from domains.campaign_finance.jurisdictions.states.FL.scraper.cli import run_fl_refresh
from domains.campaign_finance.jurisdictions.states.CO.scraper.cli import run_co_refresh
from domains.campaign_finance.jurisdictions.states.GA.scraper.cli import run_ga_refresh
from domains.campaign_finance.jurisdictions.states.IL.scraper.cli import run_il_refresh
from domains.campaign_finance.jurisdictions.states.IN.scraper.cli import run_in_refresh
from domains.campaign_finance.jurisdictions.states.KY.scraper import load_supported_data_types as load_ky_data_types
from domains.campaign_finance.jurisdictions.states.KY.scraper.cli import run_ky_refresh
from domains.campaign_finance.jurisdictions.states.LA.scraper import load_supported_data_types as load_la_data_types
from domains.campaign_finance.jurisdictions.states.LA.scraper.cli import run_la_refresh
from domains.campaign_finance.jurisdictions.states.MN.scraper.cli import run_mn_refresh
from domains.campaign_finance.jurisdictions.states.NC.scraper.cli import run_nc_refresh
from domains.campaign_finance.jurisdictions.states.NE.scraper import load_supported_data_types as load_ne_data_types
from domains.campaign_finance.jurisdictions.states.NE.scraper.cli import run_ne_refresh
from domains.campaign_finance.jurisdictions.states.NJ.scraper.cli import run_nj_refresh
from domains.campaign_finance.jurisdictions.states.PA.scraper.cli import (
    PA_LOADABLE_REFRESH_DATA_TYPES,
    run_pa_refresh,
)
from domains.campaign_finance.jurisdictions.states.TX.scraper.cli import run_tx_refresh
from domains.campaign_finance.jurisdictions.states.MA.scraper.cli import run_ma_refresh
from domains.campaign_finance.jurisdictions.states.NY.scraper.cli import run_ny_refresh
from domains.campaign_finance.jurisdictions.states.OR.scraper import load_supported_data_types as load_or_data_types
from domains.campaign_finance.jurisdictions.states.OR.scraper.cli import run_or_refresh
from domains.campaign_finance.jurisdictions.states.WA.scraper.cli import run_wa_refresh
from domains.campaign_finance.jurisdictions.states.VA.scraper.cli import run_va_refresh
from domains.campaign_finance.jurisdictions.states.WI.scraper.cli import run_wi_refresh
from domains.campaign_finance.jurisdictions.cities.SF.scraper.cli import run_sf_refresh
from domains.campaign_finance.jurisdictions.cities.LA.scraper.cli import run_la_refresh as run_la_city_refresh
from domains.campaign_finance.jurisdictions.cities.NYC.scraper.cli import run_nyc_refresh

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SUPPORTED_STATE_CODES = (
    "AL",
    "CA",
    "CO",
    "FL",
    "GA",
    "IL",
    "IN",
    "KY",
    "LA",
    "MA",
    "MN",
    "NC",
    "NE",
    "NJ",
    "NY",
    "OR",
    "PA",
    "TX",
    "VA",
    "WA",
    "WI",
)

_SUPPORTED_CITY_CODES = ("LA", "NYC", "SF")

_CITY_JURISDICTION_TYPE = "municipality"

_CADENCE_INTERVALS = {
    "continuous": timedelta(0),
    "daily": timedelta(days=1),
    "weekly": timedelta(days=7),
    "monthly": timedelta(days=30),
    "quarterly": timedelta(days=90),
    "annual": timedelta(days=365),
}

_NC_TRANSACTION_SOURCE_NAME = "North Carolina SBoE Transaction Search"
_FEC_SOURCE_NAME = "FEC Schedule A API"
_PRIORITY_CADENCE = "daily"
AL_LOADABLE_REFRESH_DATA_TYPES = load_al_data_types()
KY_LOADABLE_REFRESH_DATA_TYPES = load_ky_data_types()
LA_LOADABLE_REFRESH_DATA_TYPES = load_la_data_types()
NE_LOADABLE_REFRESH_DATA_TYPES = load_ne_data_types()
OR_LOADABLE_REFRESH_DATA_TYPES = load_or_data_types()
# FL config now includes officeholder_directory entries that are loaded by a
# separate officeholder pipeline, not by run_fl_refresh's campaign-finance path.
FL_LOADABLE_REFRESH_DATA_TYPES: tuple[str, ...] = ("contributions", "expenditures", "transfers", "other")
_PRIORITY_STATE_TRANSACTION_TYPES: dict[str, frozenset[str]] = {
    "CA": frozenset({"contributions", "expenditures"}),
    "CO": frozenset({"contributions", "expenditures"}),
    "GA": frozenset({"contributions", "expenditures"}),
    "TX": frozenset({"contributions", "expenditures", "loans"}),
}


@dataclass(frozen=True, slots=True)
class RunnerParameters:
    fec_state: str = "NC"
    fec_cycle: int = 2024
    fec_limit: int = 100
    co_year: int | None = None
    pa_year: int | None = None
    # Empty string = all candidates (portal returns all results for the date range).
    # The GA portal's Candidate field is a name filter, not a race-type filter —
    # "STATEWIDE" matched nothing because no candidate is literally named that.
    ga_candidate: str = ""
    ga_date_start: str | None = None
    ga_date_end: str | None = None
    nc_committee_docs_path: Path | None = None
    nc_date_from: str | None = None
    nc_date_to: str | None = None
    nc_committee_id: str | None = None
    nc_committee_name: str | None = None
    nc_trans_type: str | None = None
    va_year_month: str | None = None  # YYYY_MM format; defaults to current month
    tx_year_from: int | None = None  # filter TX to rows >= this year (default: now-4 = 5 years)
    ca_year_from: int | None = None  # filter CA to rows >= this year (default: now-4 = 5 years)


@dataclass(frozen=True, slots=True)
class RefreshJob:
    key: str
    domain: str
    jurisdiction: str
    cadence: str
    data_source_names: tuple[str, ...]
    run_callable: Callable[[], object]


@dataclass(frozen=True, slots=True)
class RefreshRunResult:
    key: str
    status: str
    metadata_updates: int
    message: str
    error: str | None = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _resolve_now(now: datetime | None) -> datetime:
    return _normalize_datetime(now) if now is not None else _utc_now()


def _discover_configs_by_state_code() -> dict[str, JurisdictionConfig]:
    configs: dict[str, JurisdictionConfig] = {}
    for config_path in discover_jurisdiction_configs(_REPO_ROOT):
        config = load_jurisdiction_config(config_path)
        state_code = config.jurisdiction.code
        if state_code in _SUPPORTED_STATE_CODES:
            configs[state_code] = config
    return configs


def _discover_configs_by_city_code() -> dict[str, JurisdictionConfig]:
    configs: dict[str, JurisdictionConfig] = {}
    for config_path in discover_jurisdiction_configs(_REPO_ROOT):
        config = load_jurisdiction_config(config_path)
        if config.jurisdiction.type == _CITY_JURISDICTION_TYPE and config.jurisdiction.code in _SUPPORTED_CITY_CODES:
            configs[config.jurisdiction.code] = config
    return configs


def _data_source_identity(data_source: object) -> tuple[str, str]:
    return data_source.name, data_source.update_frequency


def _find_data_source_for_transaction_type(
    config: JurisdictionConfig,
    *,
    transaction_type: str,
) -> tuple[str, str] | None:
    """Return the unique source name/cadence pair for one transaction type."""
    matching_sources = [
        _data_source_identity(data_source)
        for data_source in config.data_sources
        if transaction_type in data_source.coverage.transaction_types
    ]
    if not matching_sources:
        return None
    if len(matching_sources) > 1:
        raise RuntimeError(
            "Refresh runner expected one data source for "
            f"{config.jurisdiction.code} transaction type {transaction_type!r}, "
            f"found {len(matching_sources)}"
        )
    return matching_sources[0]


def _find_data_source_by_name(config: JurisdictionConfig, *, source_name: str) -> tuple[str, str] | None:
    for data_source in config.data_sources:
        if data_source.name == source_name:
            return _data_source_identity(data_source)
    return None


def _default_date_range(now: datetime) -> tuple[str, str]:
    year = now.year
    return f"01/01/{year}", f"12/31/{year}"


def _resolve_date_range(*, start: str | None, end: str | None, now: datetime) -> tuple[str, str]:
    default_start, default_end = _default_date_range(now)
    return start or default_start, end or default_end


def _build_refresh_job(
    *,
    key: str,
    jurisdiction: str,
    source_name: str,
    cadence: str,
    run_callable: Callable[[], object],
) -> RefreshJob:
    """Create the canonical job record used by the refresh runner."""
    return RefreshJob(
        key=key,
        domain="campaign_finance",
        jurisdiction=jurisdiction,
        cadence=cadence,
        data_source_names=(source_name,),
        run_callable=run_callable,
    )


def _optional_job_list(job: RefreshJob | None) -> list[RefreshJob]:
    return [] if job is None else [job]


def _build_job_for_source(
    *,
    key: str,
    jurisdiction: str,
    source: tuple[str, str] | None,
    run_callable: Callable[[], object],
) -> RefreshJob | None:
    """Create a refresh job only when the requested config-backed source exists."""
    if source is None:
        return None

    source_name, cadence = source
    return _build_refresh_job(
        key=key,
        jurisdiction=jurisdiction,
        source_name=source_name,
        cadence=cadence,
        run_callable=run_callable,
    )


def _build_transaction_jobs(
    config: JurisdictionConfig,
    *,
    jurisdiction: str,
    key_prefix: str,
    data_types: tuple[str, ...],
    build_run_callable: Callable[[str], Callable[[], object]],
) -> list[RefreshJob]:
    """Build one refresh job per transaction type for a jurisdiction package."""
    jobs: list[RefreshJob] = []
    for data_type in data_types:
        job = _build_job_for_source(
            key=f"{key_prefix}-{data_type}",
            jurisdiction=jurisdiction,
            source=_find_data_source_for_transaction_type(config, transaction_type=data_type),
            run_callable=build_run_callable(data_type),
        )
        if job is not None:
            jobs.append(job)
    return jobs


def _download_refresh_callable(
    refresh_callable: Callable[..., object],
    *,
    data_type: str,
    **refresh_kwargs: object,
) -> Callable[[], object]:
    return partial(refresh_callable, data_type=data_type, download=True, **refresh_kwargs)


def _build_download_transaction_jobs(
    config: JurisdictionConfig,
    *,
    jurisdiction: str,
    key_prefix: str,
    data_types: tuple[str, ...],
    refresh_callable: Callable[..., object],
    **refresh_kwargs: object,
) -> list[RefreshJob]:
    """Build download-first transaction jobs that preserve config-derived source metadata."""
    return _build_transaction_jobs(
        config,
        jurisdiction=jurisdiction,
        key_prefix=key_prefix,
        data_types=data_types,
        build_run_callable=lambda data_type: _download_refresh_callable(
            refresh_callable,
            data_type=data_type,
            **refresh_kwargs,
        ),
    )


def _build_download_jobs_for_state(
    config: JurisdictionConfig,
    *,
    jurisdiction: str,
    state_code: str,
    data_types: tuple[str, ...],
    refresh_callable: Callable[..., object],
    **refresh_kwargs: object,
) -> list[RefreshJob]:
    """Build standard download-backed jobs for one state package."""
    return _build_download_transaction_jobs(
        config,
        jurisdiction=jurisdiction,
        key_prefix=f"state-{state_code.lower()}",
        data_types=data_types,
        refresh_callable=refresh_callable,
        **refresh_kwargs,
    )


def _resolve_year(override_year: int | None, *, now: datetime) -> int:
    return now.year if override_year is None else override_year


def _resolve_year_month(override: str | None, *, now: datetime) -> str:
    """Return YYYY_MM string; uses current month if no override provided."""
    if override is not None:
        return override
    return f"{now.year}_{now.month:02d}"


def _build_ca_jobs(
    config: JurisdictionConfig,
    *,
    jurisdiction: str,
    parameters: RunnerParameters,
    now: datetime,
) -> list[RefreshJob]:
    # CA data goes back to 1999. Default to past 5 years (current_year - 4)
    # to keep load times viable — same pattern as TX year filter.
    ca_year_from = parameters.ca_year_from if parameters.ca_year_from is not None else now.year - 4
    return _optional_job_list(
        _build_job_for_source(
            key="state-ca-refresh",
            jurisdiction=jurisdiction,
            source=_find_data_source_for_transaction_type(config, transaction_type="contributions"),
            run_callable=partial(run_ca_refresh, download=True, year_from=ca_year_from),
        )
    )


def _build_ga_jobs(
    config: JurisdictionConfig,
    *,
    jurisdiction: str,
    parameters: RunnerParameters,
    now: datetime,
) -> list[RefreshJob]:
    """Build Georgia jobs with resolved candidate and date-range filters."""
    ga_date_start, ga_date_end = _resolve_date_range(
        start=parameters.ga_date_start,
        end=parameters.ga_date_end,
        now=now,
    )
    return _build_download_transaction_jobs(
        config,
        jurisdiction=jurisdiction,
        key_prefix="state-ga",
        data_types=("contributions", "expenditures"),
        refresh_callable=run_ga_refresh,
        candidate=parameters.ga_candidate,
        date_start=ga_date_start,
        date_end=ga_date_end,
    )


def _build_nc_jobs(
    config: JurisdictionConfig,
    *,
    jurisdiction: str,
    parameters: RunnerParameters,
    now: datetime,
) -> list[RefreshJob]:
    # NC transaction downloads need a committee-document export to build
    # filing and cf.transaction rows. Skip this state unless the operator
    # provides the matching document export path explicitly.
    if parameters.nc_committee_docs_path is None:
        return []

    source = _find_data_source_by_name(config, source_name=_NC_TRANSACTION_SOURCE_NAME)
    if source is None:
        return []

    if not parameters.nc_committee_id or not parameters.nc_committee_name:
        raise ValueError(
            "NC refresh runner requires both nc_committee_id and nc_committee_name "
            "when nc_committee_docs_path is provided"
        )

    nc_date_from, nc_date_to = _resolve_date_range(
        start=parameters.nc_date_from,
        end=parameters.nc_date_to,
        now=now,
    )
    nc_committee_id = parameters.nc_committee_id
    nc_committee_name = parameters.nc_committee_name

    def _run_nc_job() -> object:
        with tempfile.TemporaryDirectory(prefix="refresh-nc-") as temp_dir:
            output_path = Path(temp_dir) / "transactions.csv"
            return run_nc_refresh(
                data_type="transactions",
                download=True,
                output_path=output_path,
                date_from=nc_date_from,
                date_to=nc_date_to,
                committee_id=nc_committee_id,
                committee_name=nc_committee_name,
                committee_docs_path=parameters.nc_committee_docs_path,
                trans_type=parameters.nc_trans_type,
            )

    return _optional_job_list(
        _build_job_for_source(
            key="state-nc-transactions",
            jurisdiction=jurisdiction,
            source=source,
            run_callable=_run_nc_job,
        )
    )


def _build_state_jobs(config: JurisdictionConfig, *, parameters: RunnerParameters, now: datetime) -> list[RefreshJob]:
    """Dispatch to the state-specific job builder for one implemented package."""
    state_code = config.jurisdiction.code
    jurisdiction = f"state/{state_code}"

    match state_code:
        case "AL":
            return _build_download_jobs_for_state(
                config,
                jurisdiction=jurisdiction,
                state_code=state_code,
                data_types=AL_LOADABLE_REFRESH_DATA_TYPES,
                refresh_callable=run_al_refresh,
                year_from=now.year - 4,
            )
        case "CA":
            return _build_ca_jobs(config, jurisdiction=jurisdiction, parameters=parameters, now=now)
        case "FL":
            return _build_download_jobs_for_state(
                config,
                jurisdiction=jurisdiction,
                state_code=state_code,
                data_types=FL_LOADABLE_REFRESH_DATA_TYPES,
                refresh_callable=run_fl_refresh,
            )
        case "CO":
            # CO's TRACER server (tracer.sos.colorado.gov) doesn't send its
            # intermediate SSL cert, so both certifi and system CA stores fail.
            # allow_insecure_tls=True + CIVIBUS_ALLOW_INSECURE_TLS_RETRY=1 env
            # var enables the download break-glass (retry with verify=False).
            return _build_download_jobs_for_state(
                config,
                jurisdiction=jurisdiction,
                state_code=state_code,
                data_types=("contributions", "expenditures"),
                refresh_callable=run_co_refresh,
                year=_resolve_year(parameters.co_year, now=now),
                allow_insecure_tls=True,
            )
        case "GA":
            return _build_ga_jobs(config, jurisdiction=jurisdiction, parameters=parameters, now=now)
        case "IL":
            return _build_download_jobs_for_state(
                config,
                jurisdiction=jurisdiction,
                state_code=state_code,
                data_types=("contributions", "expenditures"),
                refresh_callable=run_il_refresh,
            )
        case "IN":
            return _build_download_jobs_for_state(
                config,
                jurisdiction=jurisdiction,
                state_code=state_code,
                data_types=("contributions", "expenditures"),
                refresh_callable=run_in_refresh,
                year=now.year,
            )
        case "KY":
            return _build_download_jobs_for_state(
                config,
                jurisdiction=jurisdiction,
                state_code=state_code,
                data_types=KY_LOADABLE_REFRESH_DATA_TYPES,
                refresh_callable=run_ky_refresh,
                year_from=now.year - 4,
            )
        case "MN":
            return _build_download_jobs_for_state(
                config,
                jurisdiction=jurisdiction,
                state_code=state_code,
                data_types=("contributions", "expenditures", "independent_expenditures"),
                refresh_callable=run_mn_refresh,
            )
        case "LA":
            return _build_download_jobs_for_state(
                config,
                jurisdiction=jurisdiction,
                state_code=state_code,
                data_types=LA_LOADABLE_REFRESH_DATA_TYPES,
                refresh_callable=run_la_refresh,
                year=_resolve_year(None, now=now),
            )
        case "NC":
            return _build_nc_jobs(config, jurisdiction=jurisdiction, parameters=parameters, now=now)
        case "NE":
            return _build_download_jobs_for_state(
                config,
                jurisdiction=jurisdiction,
                state_code=state_code,
                data_types=NE_LOADABLE_REFRESH_DATA_TYPES,
                refresh_callable=run_ne_refresh,
                year=_resolve_year(None, now=now),
            )
        case "NJ":
            return _build_download_jobs_for_state(
                config,
                jurisdiction=jurisdiction,
                state_code=state_code,
                data_types=("contributions",),
                refresh_callable=run_nj_refresh,
            )
        case "OR":
            return _build_download_jobs_for_state(
                config,
                jurisdiction=jurisdiction,
                state_code=state_code,
                data_types=OR_LOADABLE_REFRESH_DATA_TYPES,
                refresh_callable=run_or_refresh,
                year_from=now.year - 4,
            )
        case "PA":
            return _build_download_jobs_for_state(
                config,
                jurisdiction=jurisdiction,
                state_code=state_code,
                data_types=PA_LOADABLE_REFRESH_DATA_TYPES,
                refresh_callable=run_pa_refresh,
                year=_resolve_year(parameters.pa_year, now=now),
            )
        case "TX":
            # TX bulk ZIP has 33M+ historical rows. Default to past 5 years
            # (current_year - 4) to keep load times under ~30 min.
            tx_year_from = parameters.tx_year_from if parameters.tx_year_from is not None else now.year - 4
            return _build_download_jobs_for_state(
                config,
                jurisdiction=jurisdiction,
                state_code=state_code,
                data_types=("contributions", "expenditures", "loans"),
                refresh_callable=run_tx_refresh,
                year_from=tx_year_from,
            )
        case "VA":
            # VA uses monthly CSV directories (YYYY_MM format), updated daily
            return _build_download_jobs_for_state(
                config,
                jurisdiction=jurisdiction,
                state_code=state_code,
                data_types=("contributions", "expenditures"),
                refresh_callable=run_va_refresh,
                year_month=_resolve_year_month(parameters.va_year_month, now=now),
            )
        case "MA":
            return _build_download_jobs_for_state(
                config,
                jurisdiction=jurisdiction,
                state_code=state_code,
                data_types=("contributions", "expenditures"),
                refresh_callable=run_ma_refresh,
            )
        case "NY":
            return _build_download_jobs_for_state(
                config,
                jurisdiction=jurisdiction,
                state_code=state_code,
                data_types=("contributions", "expenditures"),
                refresh_callable=run_ny_refresh,
            )
        case "WA":
            return _build_download_jobs_for_state(
                config,
                jurisdiction=jurisdiction,
                state_code=state_code,
                data_types=("contributions", "expenditures", "independent_expenditures", "loans"),
                refresh_callable=run_wa_refresh,
            )
        case "WI":
            return _build_download_jobs_for_state(
                config,
                jurisdiction=jurisdiction,
                state_code=state_code,
                data_types=("transactions",),
                refresh_callable=run_wi_refresh,
            )
        case _:
            return []


def _build_city_jobs(config: JurisdictionConfig) -> list[RefreshJob]:
    """Build refresh jobs for a city jurisdiction package."""
    city_code = config.jurisdiction.code
    jurisdiction = f"{config.jurisdiction.type}/{city_code}"

    match city_code:
        case "LA":
            source = _find_data_source_by_name(config, source_name="LA Ethics Campaign Contributions")
            return _optional_job_list(
                _build_job_for_source(
                    key=f"city-{city_code.lower()}-transactions",
                    jurisdiction=jurisdiction,
                    source=source,
                    run_callable=_download_refresh_callable(run_la_city_refresh, data_type="transactions"),
                )
            )
        case "NYC":
            source = _find_data_source_by_name(config, source_name="NYC CFB Campaign Contributions")
            return _optional_job_list(
                _build_job_for_source(
                    key=f"city-{city_code.lower()}-transactions",
                    jurisdiction=jurisdiction,
                    source=source,
                    run_callable=_download_refresh_callable(run_nyc_refresh, data_type="transactions"),
                )
            )
        case "SF":
            # SF serves all transaction types (contributions, expenditures, loans, IE)
            # from a single SODA endpoint, so we use _find_data_source_by_name
            # rather than _find_data_source_for_transaction_type.
            source = _find_data_source_by_name(config, source_name="SF Ethics Campaign Finance Transactions")
            return _optional_job_list(
                _build_job_for_source(
                    key=f"city-{city_code.lower()}-transactions",
                    jurisdiction=jurisdiction,
                    source=source,
                    run_callable=_download_refresh_callable(run_sf_refresh, data_type="transactions"),
                )
            )
        case _:
            return []


def _build_fec_job(parameters: RunnerParameters) -> RefreshJob:
    return RefreshJob(
        key="federal-fec-schedule-a",
        domain="campaign_finance",
        jurisdiction="federal/fec",
        cadence="continuous",
        data_source_names=(_FEC_SOURCE_NAME,),
        run_callable=lambda: run_fec_refresh(
            state=parameters.fec_state,
            cycle=parameters.fec_cycle,
            limit=parameters.fec_limit,
        ),
    )


def _build_fec_schedule_e_job(parameters: RunnerParameters) -> RefreshJob:
    def _run_fec_schedule_e_job() -> object:
        with tempfile.TemporaryDirectory(prefix="refresh-fec-schedule-e-") as temp_dir:
            destination_path = Path(temp_dir) / f"independent_expenditure_{parameters.fec_cycle}.csv"
            urlretrieve(fec_schedule_e_url(parameters.fec_cycle), destination_path)

            connection = get_connection()
            try:
                with connection.transaction():
                    data_source_id = ensure_fec_bulk_data_source(connection)
                return dispatch_load(
                    conn=connection,
                    config=CliConfig(
                        mode="single",
                        cycle=parameters.fec_cycle,
                        file_type="schedule_e",
                        path=destination_path,
                        directory=None,
                        batch_size=1000,
                        limit=None,
                        graph_enabled=False,
                        with_transactions=False,
                    ),
                    request=LoadRequest(file_type="schedule_e", path=destination_path),
                    data_source_id=data_source_id,
                )
            finally:
                connection.close()

    return RefreshJob(
        key="federal-fec-schedule-e",
        domain="campaign_finance",
        jurisdiction="federal/fec",
        cadence="continuous",
        data_source_names=(FEC_BULK_DATA_SOURCE_NAME,),
        run_callable=_run_fec_schedule_e_job,
    )


def _build_result(
    *,
    key: str,
    status: str,
    message: str,
    metadata_updates: int = 0,
    error: str | None = None,
) -> RefreshRunResult:
    return RefreshRunResult(
        key=key,
        status=status,
        metadata_updates=metadata_updates,
        message=message,
        error=error,
    )


def _priority_source_names(
    configs_by_state_code: dict[str, JurisdictionConfig],
    *,
    parameters: RunnerParameters,
) -> set[str]:
    """Return the source names that qualify for priority-scope refresh runs."""
    priority_sources: set[str] = set()

    for state_code, transaction_types in _PRIORITY_STATE_TRANSACTION_TYPES.items():
        config = configs_by_state_code.get(state_code)
        if config is None:
            continue
        for data_source in config.data_sources:
            if set(data_source.coverage.transaction_types).intersection(transaction_types):
                priority_sources.add(data_source.name)

    if parameters.nc_committee_docs_path is not None:
        nc_config = configs_by_state_code.get("NC")
        if nc_config is not None:
            nc_source = _find_data_source_by_name(nc_config, source_name=_NC_TRANSACTION_SOURCE_NAME)
            if nc_source is not None:
                priority_sources.add(nc_source[0])

    return priority_sources


def _filter_jobs_by_key_prefixes(
    jobs: list[RefreshJob],
    *,
    job_key_prefixes: tuple[str, ...],
) -> list[RefreshJob]:
    """Return only jobs whose canonical keys match one of the requested prefixes."""
    if not job_key_prefixes:
        return jobs

    filtered_jobs = [
        job for job in jobs if any(job.key.startswith(job_key_prefix) for job_key_prefix in job_key_prefixes)
    ]
    if filtered_jobs:
        return filtered_jobs

    joined_prefixes = ", ".join(repr(prefix) for prefix in job_key_prefixes)
    raise ValueError(f"No refresh jobs matched job_key_prefixes: {joined_prefixes}")


def build_refresh_plan(
    *,
    scope: str = "all",
    parameters: RunnerParameters | None = None,
    job_key_prefixes: tuple[str, ...] = (),
    now: datetime | None = None,
) -> list[RefreshJob]:

    if scope not in {"all", "priority"}:
        raise ValueError(f"Unsupported scope: {scope!r}")

    resolved_now = _resolve_now(now)
    resolved_parameters = parameters or RunnerParameters()
    configs_by_state_code = _discover_configs_by_state_code()

    jobs: list[RefreshJob] = [_build_fec_job(resolved_parameters)]
    jobs.append(_build_fec_schedule_e_job(resolved_parameters))
    for state_code in _SUPPORTED_STATE_CODES:
        config = configs_by_state_code.get(state_code)
        if config is None:
            continue
        jobs.extend(_build_state_jobs(config, parameters=resolved_parameters, now=resolved_now))

    configs_by_city_code = _discover_configs_by_city_code()
    for city_code in _SUPPORTED_CITY_CODES:
        config = configs_by_city_code.get(city_code)
        if config is None:
            continue
        jobs.extend(_build_city_jobs(config))

    if scope == "priority":
        allowed_sources = _priority_source_names(configs_by_state_code, parameters=resolved_parameters)
        jobs = [
            replace(job, cadence=_PRIORITY_CADENCE)
            for job in jobs
            if any(source_name in allowed_sources for source_name in job.data_source_names)
        ]

    return _filter_jobs_by_key_prefixes(jobs, job_key_prefixes=job_key_prefixes)


def should_run_job(job: RefreshJob, *, last_pull_at: datetime | None, now: datetime | None = None) -> bool:
    interval = _CADENCE_INTERVALS.get(job.cadence)
    if interval is None:
        raise ValueError(f"Unsupported cadence: {job.cadence!r}")

    if last_pull_at is None:
        return True

    if interval == timedelta(0):
        return True

    resolved_now = _resolve_now(now)
    resolved_last_pull_at = _normalize_datetime(last_pull_at)
    return resolved_now - resolved_last_pull_at >= interval


def _select_data_source_id(
    connection: psycopg.Connection,
    *,
    domain: str,
    jurisdiction: str,
    name: str,
) -> UUID | None:

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id
            FROM core.data_source
            WHERE domain = %s
              AND jurisdiction = %s
              AND name = %s
            LIMIT 1
            """,
            (domain, jurisdiction, name),
        )
        row = cursor.fetchone()
    if row is None:
        return None
    return row[0]


def _select_latest_pull_at(connection: psycopg.Connection, job: RefreshJob) -> datetime | None:

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT MAX(last_pull_at)
            FROM core.data_source
            WHERE domain = %s
              AND jurisdiction = %s
              AND name = ANY(%s)
            """,
            (job.domain, job.jurisdiction, list(job.data_source_names)),
        )
        row = cursor.fetchone()

    if row is None:
        return None
    return row[0]


def _sync_job_metadata(connection: psycopg.Connection, job: RefreshJob, *, pull_status: str) -> int:
    metadata_updates = 0
    for source_name in job.data_source_names:
        data_source_id = _select_data_source_id(
            connection,
            domain=job.domain,
            jurisdiction=job.jurisdiction,
            name=source_name,
        )
        if data_source_id is None:
            continue
        sync_data_source_metadata(connection, data_source_id, pull_status=pull_status)
        metadata_updates += 1
    return metadata_updates


def _dry_run_result(job_key: str) -> RefreshRunResult:
    return _build_result(key=job_key, status="dry_run", message="Dry-run: job not executed")


def _load_result_summary_message(execution_result: object) -> str | None:
    """Summarize row-count results when a refresh callable returns loader-style counts."""
    count_fields = ("inserted", "skipped", "quarantined", "superseded", "errors")
    if not all(hasattr(execution_result, field_name) for field_name in count_fields):
        return None

    return " ".join(f"{field_name}={getattr(execution_result, field_name)}" for field_name in count_fields)


def _format_result_line(result: RefreshRunResult) -> str:
    line = f"{result.key}: status={result.status} metadata_updates={result.metadata_updates} message={result.message}"
    if result.error:
        return f"{line} error={result.error}"
    return line


def _record_result(
    results: list[RefreshRunResult],
    result: RefreshRunResult,
    *,
    on_result: Callable[[RefreshRunResult], None] | None,
) -> None:
    results.append(result)
    if on_result is not None:
        on_result(result)


def _run_gated_job(
    connection: psycopg.Connection,
    job: RefreshJob,
    *,
    force: bool,
    now: datetime,
) -> RefreshRunResult:
    if not force:
        latest_pull_at = _select_latest_pull_at(connection, job)
        if not should_run_job(job, last_pull_at=latest_pull_at, now=now):
            return _build_result(key=job.key, status="skipped", message="Skipped by cadence gate")

    return run_job(connection, job, dry_run=False)


def run_job(
    connection: psycopg.Connection,
    job: RefreshJob,
    *,
    dry_run: bool = False,
) -> RefreshRunResult:

    if dry_run:
        return _dry_run_result(job.key)

    metadata_updates = 0
    execution_error: Exception | None = None
    execution_result: object | None = None

    try:
        execution_result = job.run_callable()
    except Exception as error:  # noqa: BLE001
        execution_error = error

    pull_status = "failed" if execution_error is not None else "success"
    try:
        metadata_updates = _sync_job_metadata(connection, job, pull_status=pull_status)
    except Exception as metadata_error:  # noqa: BLE001
        return _build_result(
            key=job.key,
            status="failed",
            message="Metadata sync failed",
            metadata_updates=metadata_updates,
            error=str(metadata_error),
        )

    if execution_error is not None:
        return _build_result(
            key=job.key,
            status="failed",
            message="Refresh job failed",
            metadata_updates=metadata_updates,
            error=str(execution_error),
        )

    success_message = "Refresh job succeeded"
    load_result_summary = _load_result_summary_message(execution_result)
    if load_result_summary is not None:
        success_message = f"{success_message}: {load_result_summary}"

    return _build_result(
        key=job.key,
        status="success",
        metadata_updates=metadata_updates,
        message=success_message,
    )


def run_all_jobs(
    connection: psycopg.Connection | None,
    jobs: list[RefreshJob],
    *,
    dry_run: bool = False,
    force: bool = False,
    now: datetime | None = None,
    on_result: Callable[[RefreshRunResult], None] | None = None,
) -> list[RefreshRunResult]:

    if not dry_run and connection is None:
        raise ValueError("run_all_jobs requires a database connection when dry_run=False")

    results: list[RefreshRunResult] = []
    resolved_now = _resolve_now(now)
    for job in jobs:
        if dry_run:
            _record_result(results, _dry_run_result(job.key), on_result=on_result)
            continue

        assert connection is not None  # guarded above
        try:
            result = _run_gated_job(connection, job, force=force, now=resolved_now)
        except Exception as error:  # noqa: BLE001
            result = _build_result(
                key=job.key,
                status="failed",
                message="Refresh orchestration failed",
                error=str(error),
            )
        _record_result(results, result, on_result=on_result)

    return results


def build_argument_parser() -> argparse.ArgumentParser:

    parser = argparse.ArgumentParser(description="Run campaign-finance refresh jobs from config-driven cadence")
    parser.add_argument("--scope", choices=["all", "priority"], default="all", help="Refresh scope to execute")
    parser.add_argument(
        "--job-key-prefix",
        dest="job_key_prefixes",
        action="append",
        default=[],
        help="Optional canonical refresh-job key prefix filter; may be repeated",
    )
    parser.add_argument("--dry-run", action="store_true", help="Plan and report without executing jobs")
    parser.add_argument("--force", action="store_true", help="Ignore cadence gating and execute all scoped jobs")
    parser.add_argument("--fec-state", default="NC", help="Default FEC state filter")
    parser.add_argument("--fec-cycle", default=2024, type=int, help="Default FEC cycle")
    parser.add_argument("--fec-limit", default=100, type=int, help="Default FEC row limit")
    parser.add_argument("--co-year", type=int, help="CO year override (defaults to current year)")
    parser.add_argument("--pa-year", type=int, help="PA year override (defaults to current year)")
    parser.add_argument(
        "--tx-year-from",
        type=int,
        help="TX year filter: only load rows from this year onwards (default: current_year - 4)",
    )
    parser.add_argument(
        "--ca-year-from",
        type=int,
        help="CA year filter: only load rows from this year onwards (default: current_year - 4)",
    )
    parser.add_argument("--ga-candidate", default="", help="GA candidate name filter (empty = all candidates)")
    parser.add_argument("--ga-date-start", help="GA date-start filter (MM/DD/YYYY)")
    parser.add_argument("--ga-date-end", help="GA date-end filter (MM/DD/YYYY)")
    parser.add_argument(
        "--nc-committee-docs-path",
        type=Path,
        help="Path to an NC committee-document export required for filing-aware NC refresh jobs",
    )
    parser.add_argument("--nc-date-from", help="NC transaction date-from filter (MM/DD/YYYY)")
    parser.add_argument("--nc-date-to", help="NC transaction date-to filter (MM/DD/YYYY)")
    parser.add_argument("--nc-committee-id", help="NC committee id filter for committee-scoped runner execution")
    parser.add_argument(
        "--nc-committee-name",
        help="NC visible committee name filter for committee-scoped runner execution",
    )
    parser.add_argument("--nc-trans-type", choices=["all", "rec", "exp"], help="NC transaction type filter")
    return parser


def main(argv: list[str] | None = None) -> int:

    args = build_argument_parser().parse_args(argv)

    parameters = RunnerParameters(
        fec_state=args.fec_state,
        fec_cycle=args.fec_cycle,
        fec_limit=args.fec_limit,
        co_year=args.co_year,
        pa_year=args.pa_year,
        ga_candidate=args.ga_candidate,
        ga_date_start=args.ga_date_start,
        ga_date_end=args.ga_date_end,
        nc_committee_docs_path=args.nc_committee_docs_path,
        nc_date_from=args.nc_date_from,
        nc_date_to=args.nc_date_to,
        nc_committee_id=args.nc_committee_id,
        nc_committee_name=args.nc_committee_name,
        nc_trans_type=args.nc_trans_type,
        tx_year_from=args.tx_year_from,
        ca_year_from=args.ca_year_from,
    )

    jobs = build_refresh_plan(
        scope=args.scope,
        parameters=parameters,
        job_key_prefixes=tuple(args.job_key_prefixes),
    )

    def _stream_result(result: RefreshRunResult) -> None:
        print(_format_result_line(result), flush=True)

    if args.dry_run:
        results = run_all_jobs(None, jobs, dry_run=True, force=args.force, on_result=_stream_result)
    else:
        connection: psycopg.Connection | None = None
        try:
            connection = get_connection()
            results = run_all_jobs(connection, jobs, dry_run=False, force=args.force, on_result=_stream_result)
        except Exception as error:  # noqa: BLE001
            print(f"Refresh runner failed: {error}", file=sys.stderr)
            return 1
        finally:
            if connection is not None:
                connection.close()

    return 1 if any(result.status == "failed" for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
