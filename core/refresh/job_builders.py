"""Refresh job assembly: config discovery, job construction, and plan building."""

from __future__ import annotations

import shutil
import tempfile
import zipfile
from dataclasses import replace
from functools import partial
from pathlib import Path
from typing import Callable
from urllib.request import urlretrieve

from core.db import get_connection
from core.refresh.runner import (
    _CITY_JURISDICTION_TYPE,
    _REPO_ROOT,
    _SUPPORTED_CITY_CODES,
    _SUPPORTED_STATE_CODES,
    RefreshJob,
    RunnerParameters,
    _resolve_now,
)
from domains.campaign_finance.ingest.bulk_cli import (
    CliConfig,
    LoadRequest,
    dispatch_load,
    fec_schedule_b_url,
    fec_schedule_e_url,
)
from domains.campaign_finance.ingest.bulk_loader import (
    FEC_BULK_DATA_SOURCE_NAME,
    ensure_fec_bulk_data_source,
)
from domains.campaign_finance.ingest.cli import run_fec_refresh
from domains.campaign_finance.ingest.dark_money.download import (
    download_irs_527_full_data,
    extract_irs_527_txt,
)
from domains.campaign_finance.ingest.dark_money.loader import (
    _IRS_527_DATA_SOURCE_NAME,
    ensure_irs_527_data_source,
    load_irs_527_records,
)
from domains.campaign_finance.jurisdictions.config_schema import (
    JurisdictionConfig,
    discover_jurisdiction_configs,
    load_jurisdiction_config,
)
from domains.campaign_finance.jurisdictions.states.AL.scraper import load_supported_data_types as load_al_data_types
from domains.campaign_finance.jurisdictions.states.AL.scraper.cli import run_al_refresh
from domains.campaign_finance.jurisdictions.states.CA.scraper.cli import run_ca_refresh
from domains.campaign_finance.jurisdictions.states.CO.scraper.cli import run_co_refresh
from domains.campaign_finance.jurisdictions.states.FL.scraper.cli import run_fl_refresh
from domains.campaign_finance.jurisdictions.states.GA.scraper.cli import run_ga_refresh
from domains.campaign_finance.jurisdictions.states.IL.scraper.cli import run_il_refresh
from domains.campaign_finance.jurisdictions.states.IN.scraper.cli import run_in_refresh
from domains.campaign_finance.jurisdictions.states.KY.scraper import load_supported_data_types as load_ky_data_types
from domains.campaign_finance.jurisdictions.states.KY.scraper.cli import run_ky_refresh
from domains.campaign_finance.jurisdictions.states.LA.scraper import load_supported_data_types as load_la_data_types
from domains.campaign_finance.jurisdictions.states.LA.scraper.cli import run_la_refresh
from domains.campaign_finance.jurisdictions.states.MA.scraper.cli import run_ma_refresh
from domains.campaign_finance.jurisdictions.states.MN.scraper.cli import run_mn_refresh
from domains.campaign_finance.jurisdictions.states.NC.scraper.cli import run_nc_refresh
from domains.campaign_finance.jurisdictions.states.NC.scraper.load_support import (
    NC_COMMITTEE_DOCUMENT_SOURCE_NAME,
    NC_IE_TRANSACTION_TYPE,
    NC_TRANSACTION_SOURCE_NAME,
)
from domains.campaign_finance.jurisdictions.states.NE.scraper import load_supported_data_types as load_ne_data_types
from domains.campaign_finance.jurisdictions.states.NE.scraper.cli import run_ne_refresh
from domains.campaign_finance.jurisdictions.states.NJ.scraper.cli import run_nj_refresh
from domains.campaign_finance.jurisdictions.states.NY.scraper.cli import run_ny_refresh
from domains.campaign_finance.jurisdictions.states.OR.scraper import load_supported_data_types as load_or_data_types
from domains.campaign_finance.jurisdictions.states.OR.scraper.cli import run_or_refresh
from domains.campaign_finance.jurisdictions.states.PA.scraper.cli import (
    PA_LOADABLE_REFRESH_DATA_TYPES,
    run_pa_refresh,
)
from domains.campaign_finance.jurisdictions.states.TX.scraper.cli import run_tx_refresh
from domains.campaign_finance.jurisdictions.states.VA.scraper.cli import run_va_refresh
from domains.campaign_finance.jurisdictions.states.WA.scraper.cli import run_wa_refresh
from domains.campaign_finance.jurisdictions.states.WI.scraper.cli import run_wi_refresh
from domains.campaign_finance.jurisdictions.cities.LA.scraper.cli import run_la_refresh as run_la_city_refresh
from domains.campaign_finance.jurisdictions.cities.NYC.scraper.cli import run_nyc_refresh
from domains.campaign_finance.jurisdictions.cities.PHL.scraper.cli import run_phl_refresh
from domains.campaign_finance.jurisdictions.cities.SF.scraper.cli import run_sf_refresh
from domains.civics.loaders.ncsbe_candidate_listing import (
    _NCSBE_DATA_SOURCE_NAME,
    load_candidate_listing_from_source,
)
from domains.civics.loaders.nc_calendar import (
    available_nc_calendar_years,
    resolve_candidate_listing_refresh_cadence,
)
from domains.civics.loaders.ncsbe_results import (
    collect_ncsbe_refresh_data_source_names,
    run_ncsbe_results_refresh_2022_2024,
)
from domains.civics.loaders.official_rosters.source_templates import civic_roster_refresh_templates
from domains.civics.loaders.official_rosters.cli import main as run_official_roster_cli
from domains.civics.loaders.official_rosters.source_registry import list_nc_roster_source_metadata

from datetime import datetime

_FEC_SOURCE_NAME = "FEC Schedule A API"
_PRIORITY_CADENCE = "daily"
AL_LOADABLE_REFRESH_DATA_TYPES = load_al_data_types()
KY_LOADABLE_REFRESH_DATA_TYPES = load_ky_data_types()
LA_LOADABLE_REFRESH_DATA_TYPES = load_la_data_types()
NE_LOADABLE_REFRESH_DATA_TYPES = load_ne_data_types()
OR_LOADABLE_REFRESH_DATA_TYPES = load_or_data_types()
FL_LOADABLE_REFRESH_DATA_TYPES: tuple[str, ...] = ("contributions", "expenditures", "transfers", "other")
_PRIORITY_STATE_TRANSACTION_TYPES: dict[str, frozenset[str]] = {
    "AL": frozenset({"contributions", "expenditures"}),
    "CA": frozenset({"contributions", "expenditures"}),
    "CO": frozenset({"contributions", "expenditures"}),
    "GA": frozenset({"contributions", "expenditures"}),
    "KY": frozenset({"contributions", "expenditures"}),
    "LA": frozenset({"contributions", "expenditures", "loans"}),
    "NE": frozenset({"contributions", "expenditures", "loans"}),
    "OR": frozenset({"contributions", "expenditures"}),
    "TX": frozenset({"contributions", "expenditures", "loans"}),
}


def _resolve_nc_candidate_listing_calendar_year(now: datetime) -> int:
    """Resolve the intended NC candidate-listing election calendar year.

    NC's primary filing window opens in December of the year before the
    election, so December runs target the next election year while other
    months target the current wall-clock year. In both cases we resolve to
    the smallest available NC civic-calendar year >= the target so an
    off-cycle pre-election run (e.g. November 2025 with only `nc_2026` on
    disk) still binds cadence to the upcoming election. If no calendar
    covers the target, fall back to the most recent calendar so refresh
    plan assembly stays runnable at year boundaries.
    """
    target_year = now.year + 1 if now.month == 12 else now.year
    available_years = available_nc_calendar_years()
    if not available_years:
        return now.year
    upcoming_years = [year for year in available_years if year >= target_year]
    if upcoming_years:
        return upcoming_years[0]
    return available_years[-1]


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


def _default_ga_date_range(now: datetime) -> tuple[str, str]:
    start_year = now.year - 4
    return f"01/01/{start_year}", now.strftime("%m/%d/%Y")


def _resolve_ga_date_range(*, start: str | None, end: str | None, now: datetime) -> tuple[str, str]:
    default_start, default_end = _default_ga_date_range(now)
    return start or default_start, end or default_end


def _build_refresh_job(
    *,
    key: str,
    jurisdiction: str,
    source_name: str,
    cadence: str,
    run_callable: Callable[[], object],
) -> RefreshJob:
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
    ca_year_from = parameters.ca_year_from if parameters.ca_year_from is not None else now.year - 4
    return _optional_job_list(
        _build_job_for_source(
            key="state-ca-refresh",
            jurisdiction=jurisdiction,
            source=_find_data_source_for_transaction_type(config, transaction_type="contributions"),
            run_callable=partial(run_ca_refresh, download=True, year_from=ca_year_from),
        )
    )


# KY election dates for the 5-year contribution window (2022-2026).
# The full ExportContributors?ContributionSearchType=All endpoint returns 504
# because the server-side query times out on the full dataset. Election-date-scoped
# requests work reliably (~2-3s each).
_KY_CONTRIBUTION_ELECTION_DATES: list[tuple[str, str]] = [
    ("5/17/2022", "Primary"),
    ("11/8/2022", "General"),
    ("5/16/2023", "Primary"),
    ("11/7/2023", "General"),
    ("5/21/2024", "Primary"),
    ("11/5/2024", "General"),
    ("5/19/2026", "Primary"),
]


def _build_ky_jobs(
    config: JurisdictionConfig,
    *,
    jurisdiction: str,
    now: datetime,
) -> list[RefreshJob]:
    """Build KY jobs: election-date-scoped contributions + standard expenditures.

    The KY KREF ExportContributors endpoint returns 504 on full exports but
    works with election-date scoping. Each election date becomes a separate job.
    Expenditures use the standard full-export path.
    """
    jobs: list[RefreshJob] = []
    year_from = now.year - 4

    exp_job = _build_job_for_source(
        key="state-ky-expenditures",
        jurisdiction=jurisdiction,
        source=_find_data_source_for_transaction_type(config, transaction_type="expenditures"),
        run_callable=_download_refresh_callable(
            run_ky_refresh,
            data_type="expenditures",
            year_from=year_from,
        ),
    )
    if exp_job is not None:
        jobs.append(exp_job)

    for election_date, election_type in _KY_CONTRIBUTION_ELECTION_DATES:
        safe_key = election_date.replace("/", "-")
        job = _build_job_for_source(
            key=f"state-ky-contributions-{safe_key}",
            jurisdiction=jurisdiction,
            source=_find_data_source_for_transaction_type(config, transaction_type="contributions"),
            run_callable=_download_refresh_callable(
                run_ky_refresh,
                data_type="contributions",
                year_from=year_from,
                election_date=f"{election_date} 12:00:00 AM",
            ),
        )
        if job is not None:
            jobs.append(job)

    return jobs


def _build_ga_jobs(
    config: JurisdictionConfig,
    *,
    jurisdiction: str,
    parameters: RunnerParameters,
    now: datetime,
) -> list[RefreshJob]:
    ga_date_start, ga_date_end = _resolve_ga_date_range(
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
    jobs: list[RefreshJob] = []
    ie_source = _find_data_source_for_transaction_type(config, transaction_type=NC_IE_TRANSACTION_TYPE)
    if parameters.nc_ie_document_index_path is not None and ie_source is not None:
        nc_ie_document_index_path = parameters.nc_ie_document_index_path

        def _run_nc_ie_document_index_job() -> object:
            return run_nc_refresh(
                data_type="ie-document-index",
                path=nc_ie_document_index_path,
            )

        ie_job = _build_job_for_source(
            key="state-nc-ie-document-index",
            jurisdiction=jurisdiction,
            source=ie_source,
            run_callable=_run_nc_ie_document_index_job,
        )
        if ie_job is not None:
            jobs.append(ie_job)

        def _run_nc_ie_transactions_job() -> object:
            return run_nc_refresh(data_type="ie-transactions")

        ie_transactions_job = _build_job_for_source(
            key="state-nc-ie-transactions",
            jurisdiction=jurisdiction,
            source=ie_source,
            run_callable=_run_nc_ie_transactions_job,
        )
        if ie_transactions_job is not None:
            jobs.append(ie_transactions_job)

    committee_discovery_source = _find_data_source_by_name(
        config,
        source_name=NC_COMMITTEE_DOCUMENT_SOURCE_NAME,
    )
    committee_discovery_job = _build_job_for_source(
        key="state-nc-committee-discovery",
        jurisdiction=jurisdiction,
        source=committee_discovery_source,
        run_callable=lambda: run_nc_refresh(data_type="committee-discovery"),
    )
    if committee_discovery_job is not None:
        jobs.append(committee_discovery_job)

    candidate_listing_year_from = parameters.year_from if parameters.year_from is not None else now.year - 4
    candidate_listing_calendar_year = _resolve_nc_candidate_listing_calendar_year(now)
    candidate_listing_cadence = resolve_candidate_listing_refresh_cadence(
        year=candidate_listing_calendar_year,
        on_date=now.date(),
    )
    candidate_listing_job = RefreshJob(
        key="civic-nc-candidate-listing",
        domain="civics",
        jurisdiction="state/NC",
        cadence=candidate_listing_cadence,
        data_source_names=(_NCSBE_DATA_SOURCE_NAME,),
        run_callable=lambda: load_candidate_listing_from_source(
            year_from=candidate_listing_year_from,
            candidate_listing_path=parameters.candidate_listing_path,
        ),
    )
    jobs.append(candidate_listing_job)

    if parameters.nc_committee_docs_path is None:
        return jobs

    source = _find_data_source_by_name(config, source_name=NC_TRANSACTION_SOURCE_NAME)
    if source is None:
        return jobs

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

    transaction_job = _build_job_for_source(
        key="state-nc-transactions",
        jurisdiction=jurisdiction,
        source=source,
        run_callable=_run_nc_job,
    )
    if transaction_job is not None:
        jobs.append(transaction_job)
    return jobs


def _build_state_jobs(config: JurisdictionConfig, *, parameters: RunnerParameters, now: datetime) -> list[RefreshJob]:
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
            return _build_ky_jobs(config, jurisdiction=jurisdiction, now=now)
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
                data_types=("contributions", "expenditures", "independent_expenditures"),
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
        case "PHL":
            # PHL has two distinct Carto SQL tables (campfin_contributions and
            # campfin_expenditures); each becomes its own runner job so per-job
            # status / cadence stays granular.
            jobs: list[RefreshJob] = []
            contrib_source = _find_data_source_by_name(
                config, source_name="PHL Campaign Finance Contributions"
            )
            jobs.extend(
                _optional_job_list(
                    _build_job_for_source(
                        key=f"city-{city_code.lower()}-contributions",
                        jurisdiction=jurisdiction,
                        source=contrib_source,
                        run_callable=_download_refresh_callable(
                            run_phl_refresh, data_type="contributions"
                        ),
                    )
                )
            )
            exp_source = _find_data_source_by_name(
                config, source_name="PHL Campaign Finance Expenditures"
            )
            jobs.extend(
                _optional_job_list(
                    _build_job_for_source(
                        key=f"city-{city_code.lower()}-expenditures",
                        jurisdiction=jurisdiction,
                        source=exp_source,
                        run_callable=_download_refresh_callable(
                            run_phl_refresh, data_type="expenditures"
                        ),
                    )
                )
            )
            return jobs
        case "SF":
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


def _build_official_roster_run_callable(source_id: str) -> Callable[[], object]:
    def _run_official_roster_job() -> object:
        exit_code = run_official_roster_cli(["--source-id", source_id])
        if exit_code != 0:
            raise RuntimeError(f"Official roster job failed for source_id={source_id} with exit_code={exit_code}")
        return exit_code

    return _run_official_roster_job


def _build_official_roster_jobs() -> list[RefreshJob]:
    jobs: list[RefreshJob] = []
    for source in list_nc_roster_source_metadata():
        jobs.append(
            RefreshJob(
                key=f"civics-roster-{source.source_id}",
                domain="civics",
                jurisdiction=source.jurisdiction,
                cadence=source.cadence,
                data_source_names=(source.name,),
                run_callable=_build_official_roster_run_callable(source.source_id),
            )
        )
    return jobs


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


def _build_fec_schedule_b_job(parameters: RunnerParameters) -> RefreshJob:
    def _run_fec_schedule_b_job() -> object:
        with tempfile.TemporaryDirectory(prefix="refresh-fec-schedule-b-") as temp_dir:
            temp_dir_path = Path(temp_dir)
            cycle_suffix = str(parameters.fec_cycle)[-2:]
            archive_path = temp_dir_path / f"oppexp{cycle_suffix}.zip"
            urlretrieve(fec_schedule_b_url(parameters.fec_cycle), archive_path)

            with zipfile.ZipFile(archive_path) as archive:
                txt_members = [name for name in archive.namelist() if name.lower().endswith(".txt")]
                if not txt_members:
                    raise ValueError(f"Schedule B archive has no .txt payload: {archive_path}")

                oppexp_members = [name for name in txt_members if Path(name).name.lower().startswith("oppexp")]
                selected_member = oppexp_members[0] if oppexp_members else txt_members[0]
                extracted_path = temp_dir_path / Path(selected_member).name
                with archive.open(selected_member) as source, extracted_path.open("wb") as destination:
                    shutil.copyfileobj(source, destination)

            connection = get_connection()
            try:
                with connection.transaction():
                    data_source_id = ensure_fec_bulk_data_source(connection)
                return dispatch_load(
                    conn=connection,
                    config=CliConfig(
                        mode="single",
                        cycle=parameters.fec_cycle,
                        file_type="schedule_b",
                        path=extracted_path,
                        directory=None,
                        batch_size=1000,
                        limit=parameters.fec_limit,
                        graph_enabled=False,
                        with_transactions=False,
                    ),
                    request=LoadRequest(file_type="schedule_b", path=extracted_path),
                    data_source_id=data_source_id,
                )
            finally:
                connection.close()

    return RefreshJob(
        key="federal-fec-schedule-b",
        domain="campaign_finance",
        jurisdiction="federal/fec",
        cadence="continuous",
        data_source_names=(FEC_BULK_DATA_SOURCE_NAME,),
        run_callable=_run_fec_schedule_b_job,
    )


def _build_irs_527_job() -> RefreshJob:
    def _run_irs_527_job() -> object:
        with tempfile.TemporaryDirectory(prefix="refresh-irs-527-") as temp_dir:
            temp_dir_path = Path(temp_dir)
            archive_path = download_irs_527_full_data(temp_dir_path)
            txt_path = extract_irs_527_txt(archive_path, temp_dir_path)

            connection = get_connection()
            try:
                with connection.transaction():
                    data_source_id = ensure_irs_527_data_source(connection)
                return load_irs_527_records(
                    connection,
                    txt_path,
                    data_source_id=data_source_id,
                )
            finally:
                connection.close()

    return RefreshJob(
        key="federal-irs-527",
        domain="campaign_finance",
        jurisdiction="federal/irs_527",
        cadence="continuous",
        data_source_names=(_IRS_527_DATA_SOURCE_NAME,),
        run_callable=_run_irs_527_job,
    )


def _build_nc_past_results_job() -> RefreshJob:
    return RefreshJob(
        key="civics-nc-past-results-2022-2024",
        domain="civics",
        jurisdiction="us/nc",
        cadence="weekly",
        data_source_names=collect_ncsbe_refresh_data_source_names(),
        run_callable=run_ncsbe_results_refresh_2022_2024,
    )


def _include_explicit_nc_past_results_job(*, job_key_prefixes: tuple[str, ...]) -> bool:
    """Only materialize the sample-backed ENRS job for explicit operator invocations."""
    if not job_key_prefixes:
        return False
    job_key = "civics-nc-past-results-2022-2024"
    return any(job_key.startswith(job_key_prefix) for job_key_prefix in job_key_prefixes)


def _priority_source_names(
    configs_by_state_code: dict[str, JurisdictionConfig],
    *,
    parameters: RunnerParameters,
) -> set[str]:
    priority_sources: set[str] = set()

    for state_code, transaction_types in _PRIORITY_STATE_TRANSACTION_TYPES.items():
        config = configs_by_state_code.get(state_code)
        if config is None:
            continue
        for data_source in config.data_sources:
            if set(data_source.coverage.transaction_types).intersection(transaction_types):
                priority_sources.add(data_source.name)

    nc_config = configs_by_state_code.get("NC")
    if nc_config is not None:
        if parameters.nc_committee_docs_path is not None:
            nc_source = _find_data_source_by_name(nc_config, source_name=NC_TRANSACTION_SOURCE_NAME)
            if nc_source is not None:
                priority_sources.add(nc_source[0])

        if parameters.nc_ie_document_index_path is not None:
            nc_ie_source = _find_data_source_for_transaction_type(
                nc_config,
                transaction_type=NC_IE_TRANSACTION_TYPE,
            )
            if nc_ie_source is not None:
                priority_sources.add(nc_ie_source[0])

    priority_sources.add(_NCSBE_DATA_SOURCE_NAME)

    return priority_sources


def _priority_cadence_for_job(job: RefreshJob) -> str:
    if job.key == "civic-nc-candidate-listing":
        return job.cadence
    return _PRIORITY_CADENCE


def _filter_jobs_by_key_prefixes(
    jobs: list[RefreshJob],
    *,
    job_key_prefixes: tuple[str, ...],
) -> list[RefreshJob]:
    if not job_key_prefixes:
        return jobs

    filtered_jobs = [
        job for job in jobs if any(job.key.startswith(job_key_prefix) for job_key_prefix in job_key_prefixes)
    ]
    if filtered_jobs:
        return filtered_jobs

    joined_prefixes = ", ".join(repr(prefix) for prefix in job_key_prefixes)
    raise ValueError(f"No refresh jobs matched job_key_prefixes: {joined_prefixes}")


def _build_civic_roster_jobs() -> list[RefreshJob]:
    from domains.civics.loaders.official_rosters.loader import harvest_official_roster

    jobs: list[RefreshJob] = []
    for template in civic_roster_refresh_templates():
        if template.refresh_job_key is None or template.refresh_jurisdiction is None:
            continue

        source_id = template.registry_source_id

        def _run_civic_roster_job(*, roster_source_id: str = source_id) -> object:
            connection = get_connection()
            try:
                result = harvest_official_roster(connection, source_id=roster_source_id, dry_run=False)
                connection.commit()
                return result
            finally:
                connection.close()

        jobs.append(
            RefreshJob(
                key=template.refresh_job_key,
                domain="civics",
                jurisdiction=template.refresh_jurisdiction,
                cadence="weekly",
                data_source_names=(template.name,),
                run_callable=_run_civic_roster_job,
            )
        )
    return jobs


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
    jobs.append(_build_fec_schedule_b_job(resolved_parameters))
    jobs.append(_build_fec_schedule_e_job(resolved_parameters))
    jobs.append(_build_irs_527_job())
    if _include_explicit_nc_past_results_job(job_key_prefixes=job_key_prefixes):
        jobs.append(_build_nc_past_results_job())
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
    jobs.extend(_build_civic_roster_jobs())
    jobs.extend(_build_official_roster_jobs())

    if scope == "priority":
        allowed_sources = _priority_source_names(configs_by_state_code, parameters=resolved_parameters)
        jobs = [
            replace(job, cadence=_priority_cadence_for_job(job))
            for job in jobs
            if any(source_name in allowed_sources for source_name in job.data_source_names)
        ]

    return _filter_jobs_by_key_prefixes(jobs, job_key_prefixes=job_key_prefixes)
