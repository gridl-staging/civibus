"""Contract tests for the NC package-local refresh builder."""

from __future__ import annotations

from datetime import date, datetime, timezone
from importlib import import_module
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

import pytest

from core.refresh.runner import RefreshJob, RunnerParameters
from domains.campaign_finance.jurisdictions.config_schema import (
    JurisdictionConfig,
    load_jurisdiction_config,
)
from domains.civics.loaders.nc_calendar import (
    available_nc_calendar_years,
    resolve_candidate_listing_refresh_cadence,
)

_CONFIG_PATH = Path(__file__).resolve().parent / "config.yaml"

# 2026-06-01 sits outside every NC 2026 candidate-filing window, so the
# candidate-listing job resolves to the quarterly off-window cadence.
_NOW = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
# 2025-12-10 sits inside the December 2025 filing window for the 2026
# election, which is also the December look-ahead branch of the calendar
# year resolution.
_FILING_WINDOW_NOW = datetime(2025, 12, 10, 9, 30, tzinfo=timezone.utc)
_CANDIDATE_LISTING_CALENDAR_YEAR = 2026
_DEFAULT_YEAR_FROM = 2022

_TRANSACTION_SOURCE_NAME = "North Carolina SBoE Transaction Search"
_COMMITTEE_DOCUMENT_SOURCE_NAME = "North Carolina SBoE Committee/Document Search"
_IE_DOCUMENT_INDEX_SOURCE_NAME = "North Carolina SBoE IE Document Index"
_NCSBE_CANDIDATE_LISTING_SOURCE_NAME = "ncsbe_candidate_listing_2026"

_COMMITTEE_DOCS_PATH = Path("/tmp/nc-committee-docs.csv")
_IE_DOCUMENT_INDEX_PATH = Path("/tmp/nc-ie-document-index.csv")
_CANDIDATE_LISTING_PATH = Path("/tmp/nc-candidate-listing.csv")
_COMMITTEE_ID = "C12345"
_COMMITTEE_NAME = "Example Committee"

_MISSING_COMMITTEE_SCOPE_MESSAGE = (
    "NC refresh runner requires both nc_committee_id and nc_committee_name when nc_committee_docs_path is provided"
)
_REFRESH_MODULE_NAME = "domains.campaign_finance.jurisdictions.states.NC.refresh"

# Renaming the IE source leaves ``coverage.transaction_types`` untouched, so a
# coverage-keyed lookup still binds while a name-keyed lookup drops the jobs.
_RENAMED_IE_DOCUMENT_INDEX_SOURCE_NAME = "North Carolina SBoE Independent Expenditure Filings"
_IE_TRANSACTION_TYPE = "independent_expenditures"
_DUPLICATE_IE_COVERAGE_MESSAGE = (
    "Refresh runner expected one data source for NC transaction type 'independent_expenditures', found 2"
)
# Distinct from every real cadence string so the assertions prove the builder
# returns whatever the cadence resolver produced for the year it selected.
_SENTINEL_CADENCE = "sentinel-cadence"
# Cadence overrides distinct from every shipped NC cadence, so a per-key cadence
# map or a hard-coded literal cannot satisfy the assertions below.
_COMMITTEE_DOCUMENT_UPDATE_FREQUENCY = "monthly"
_IE_UPDATE_FREQUENCY = "quarterly"
_TRANSACTION_UPDATE_FREQUENCY = "annual"


def _load_nc_config() -> JurisdictionConfig:
    return load_jurisdiction_config(_CONFIG_PATH)


def _load_refresh_module() -> ModuleType:
    return import_module(_REFRESH_MODULE_NAME)


def _build_refresh_jobs(
    config: JurisdictionConfig,
    *,
    parameters: RunnerParameters,
    now: datetime,
) -> list[RefreshJob]:
    """Resolve the intentionally absent Stage 2 builder at test execution."""
    build_refresh_jobs = getattr(_load_refresh_module(), "build_refresh_jobs")

    return build_refresh_jobs(config, parameters=parameters, now=now)


def _config_without_source_names(
    config: JurisdictionConfig,
    *,
    dropped_source_names: tuple[str, ...],
) -> JurisdictionConfig:
    """Copy the config with the named data sources removed."""
    return config.model_copy(
        update={
            "data_sources": [
                data_source for data_source in config.data_sources if data_source.name not in dropped_source_names
            ]
        }
    )


def _full_manual_parameters(
    *,
    nc_date_from: str | None = None,
    nc_date_to: str | None = None,
    nc_trans_type: str | None = None,
) -> RunnerParameters:
    """Parameters that unlock every NC job branch at once."""
    return RunnerParameters(
        nc_committee_docs_path=_COMMITTEE_DOCS_PATH,
        nc_committee_id=_COMMITTEE_ID,
        nc_committee_name=_COMMITTEE_NAME,
        nc_ie_document_index_path=_IE_DOCUMENT_INDEX_PATH,
        nc_date_from=nc_date_from,
        nc_date_to=nc_date_to,
        nc_trans_type=nc_trans_type,
    )


def _config_with_renamed_source(
    config: JurisdictionConfig,
    *,
    source_name: str,
    renamed_source_name: str,
) -> JurisdictionConfig:
    """Copy the config with one data source renamed and its coverage untouched."""
    return config.model_copy(
        update={
            "data_sources": [
                data_source.model_copy(update={"name": renamed_source_name})
                if data_source.name == source_name
                else data_source
                for data_source in config.data_sources
            ]
        }
    )


def _config_with_added_transaction_type(
    config: JurisdictionConfig,
    *,
    source_name: str,
    transaction_type: str,
) -> JurisdictionConfig:
    """Copy the config with ``transaction_type`` added to one source's coverage."""
    return config.model_copy(
        update={
            "data_sources": [
                data_source.model_copy(
                    update={
                        "coverage": data_source.coverage.model_copy(
                            update={
                                "transaction_types": [
                                    *data_source.coverage.transaction_types,
                                    transaction_type,
                                ]
                            }
                        )
                    }
                )
                if data_source.name == source_name
                else data_source
                for data_source in config.data_sources
            ]
        }
    )


def _patch_candidate_listing_calendar(
    monkeypatch: pytest.MonkeyPatch,
    *,
    available_years: tuple[int, ...],
) -> list[dict[str, object]]:
    """Pin the on-disk calendar years and record the resolved cadence inputs.

    Returns the recorded ``resolve_candidate_listing_refresh_cadence`` kwargs so
    a test can assert which calendar year the builder selected, independent of
    which years happen to ship under ``domains/civics/data``.
    """
    refresh_module = _load_refresh_module()
    cadence_calls: list[dict[str, object]] = []

    def _record_cadence(*, year: int, on_date: date) -> str:
        cadence_calls.append({"year": year, "on_date": on_date})
        return _SENTINEL_CADENCE

    monkeypatch.setattr(refresh_module, "available_nc_calendar_years", lambda: available_years)
    monkeypatch.setattr(refresh_module, "resolve_candidate_listing_refresh_cadence", _record_cadence)
    return cadence_calls


def _jobs_by_key(jobs: list[RefreshJob]) -> dict[str, RefreshJob]:
    return {job.key: job for job in jobs}


def test_no_manual_inputs_returns_committee_discovery_then_candidate_listing() -> None:
    jobs = _build_refresh_jobs(_load_nc_config(), parameters=RunnerParameters(), now=_NOW)

    assert [job.key for job in jobs] == [
        "state-nc-committee-discovery",
        "civic-nc-candidate-listing",
    ]


def test_committee_discovery_job_carries_campaign_finance_metadata() -> None:
    jobs = _build_refresh_jobs(_load_nc_config(), parameters=RunnerParameters(), now=_NOW)
    committee_discovery_job = _jobs_by_key(jobs)["state-nc-committee-discovery"]

    assert committee_discovery_job.domain == "campaign_finance"
    assert committee_discovery_job.jurisdiction == "state/NC"
    assert committee_discovery_job.cadence == "daily"
    assert committee_discovery_job.data_source_names == (_COMMITTEE_DOCUMENT_SOURCE_NAME,)


def test_candidate_listing_job_carries_civics_metadata_and_off_window_cadence() -> None:
    jobs = _build_refresh_jobs(_load_nc_config(), parameters=RunnerParameters(), now=_NOW)
    candidate_listing_job = _jobs_by_key(jobs)["civic-nc-candidate-listing"]

    assert candidate_listing_job.domain == "civics"
    assert candidate_listing_job.jurisdiction == "state/NC"
    assert candidate_listing_job.data_source_names == (_NCSBE_CANDIDATE_LISTING_SOURCE_NAME,)
    assert candidate_listing_job.cadence == "quarterly"
    assert candidate_listing_job.cadence == resolve_candidate_listing_refresh_cadence(
        year=_CANDIDATE_LISTING_CALENDAR_YEAR,
        on_date=_NOW.date(),
    )


def test_candidate_listing_cadence_is_daily_inside_the_december_filing_window() -> None:
    assert _CANDIDATE_LISTING_CALENDAR_YEAR in available_nc_calendar_years()

    jobs = _build_refresh_jobs(_load_nc_config(), parameters=RunnerParameters(), now=_FILING_WINDOW_NOW)
    candidate_listing_job = _jobs_by_key(jobs)["civic-nc-candidate-listing"]

    assert candidate_listing_job.cadence == "daily"
    assert candidate_listing_job.cadence == resolve_candidate_listing_refresh_cadence(
        year=_CANDIDATE_LISTING_CALENDAR_YEAR,
        on_date=_FILING_WINDOW_NOW.date(),
    )


def test_full_manual_inputs_return_the_complete_ordered_nc_plan() -> None:
    jobs = _build_refresh_jobs(_load_nc_config(), parameters=_full_manual_parameters(), now=_NOW)

    assert [job.key for job in jobs] == [
        "state-nc-ie-document-index",
        "state-nc-ie-transactions",
        "state-nc-committee-discovery",
        "civic-nc-candidate-listing",
        "state-nc-transactions",
    ]
    assert {job.key: job.data_source_names for job in jobs} == {
        "state-nc-ie-document-index": (_IE_DOCUMENT_INDEX_SOURCE_NAME,),
        "state-nc-ie-transactions": (_IE_DOCUMENT_INDEX_SOURCE_NAME,),
        "state-nc-committee-discovery": (_COMMITTEE_DOCUMENT_SOURCE_NAME,),
        "civic-nc-candidate-listing": (_NCSBE_CANDIDATE_LISTING_SOURCE_NAME,),
        "state-nc-transactions": (_TRANSACTION_SOURCE_NAME,),
    }
    assert {job.key: job.cadence for job in jobs} == {
        "state-nc-ie-document-index": "weekly",
        "state-nc-ie-transactions": "weekly",
        "state-nc-committee-discovery": "daily",
        "civic-nc-candidate-listing": "quarterly",
        "state-nc-transactions": "daily",
    }
    assert {job.key: job.domain for job in jobs} == {
        "state-nc-ie-document-index": "campaign_finance",
        "state-nc-ie-transactions": "campaign_finance",
        "state-nc-committee-discovery": "campaign_finance",
        "civic-nc-candidate-listing": "civics",
        "state-nc-transactions": "campaign_finance",
    }

    for partial_date_parameters in (
        _full_manual_parameters(nc_date_from="01/01/2025"),
        _full_manual_parameters(nc_date_to="12/31/2025"),
    ):
        with pytest.raises(ValueError, match="nc_date_from and nc_date_to must be provided together"):
            _build_refresh_jobs(_load_nc_config(), parameters=partial_date_parameters, now=_NOW)


def test_ie_jobs_require_the_ie_document_index_path() -> None:
    jobs = _build_refresh_jobs(
        _load_nc_config(),
        parameters=RunnerParameters(
            nc_committee_docs_path=_COMMITTEE_DOCS_PATH,
            nc_committee_id=_COMMITTEE_ID,
            nc_committee_name=_COMMITTEE_NAME,
        ),
        now=_NOW,
    )

    assert [job.key for job in jobs] == [
        "state-nc-committee-discovery",
        "civic-nc-candidate-listing",
        "state-nc-transactions",
    ]


def test_transactions_job_requires_the_committee_docs_path() -> None:
    jobs = _build_refresh_jobs(
        _load_nc_config(),
        parameters=RunnerParameters(nc_ie_document_index_path=_IE_DOCUMENT_INDEX_PATH),
        now=_NOW,
    )

    assert [job.key for job in jobs] == [
        "state-nc-ie-document-index",
        "state-nc-ie-transactions",
        "state-nc-committee-discovery",
        "civic-nc-candidate-listing",
    ]


def test_jobs_are_omitted_when_their_data_source_is_absent() -> None:
    config = _config_without_source_names(
        _load_nc_config(),
        dropped_source_names=(
            _IE_DOCUMENT_INDEX_SOURCE_NAME,
            _COMMITTEE_DOCUMENT_SOURCE_NAME,
            _TRANSACTION_SOURCE_NAME,
        ),
    )

    jobs = _build_refresh_jobs(config, parameters=_full_manual_parameters(), now=_NOW)

    assert [job.key for job in jobs] == ["civic-nc-candidate-listing"]


def test_missing_transaction_source_keeps_the_rest_of_the_plan() -> None:
    config = _config_without_source_names(
        _load_nc_config(),
        dropped_source_names=(_TRANSACTION_SOURCE_NAME,),
    )

    jobs = _build_refresh_jobs(config, parameters=_full_manual_parameters(), now=_NOW)

    assert [job.key for job in jobs] == [
        "state-nc-ie-document-index",
        "state-nc-ie-transactions",
        "state-nc-committee-discovery",
        "civic-nc-candidate-listing",
    ]


def test_missing_transaction_source_precedes_committee_scope_validation() -> None:
    config = _config_without_source_names(
        _load_nc_config(),
        dropped_source_names=(_TRANSACTION_SOURCE_NAME,),
    )

    jobs = _build_refresh_jobs(
        config,
        parameters=RunnerParameters(nc_committee_docs_path=_COMMITTEE_DOCS_PATH),
        now=_NOW,
    )

    assert [job.key for job in jobs] == [
        "state-nc-committee-discovery",
        "civic-nc-candidate-listing",
    ]


def test_ie_document_index_job_forwards_the_manual_path(monkeypatch: pytest.MonkeyPatch) -> None:
    run_nc_refresh = MagicMock()
    monkeypatch.setattr(_load_refresh_module(), "run_nc_refresh", run_nc_refresh)

    jobs = _build_refresh_jobs(_load_nc_config(), parameters=_full_manual_parameters(), now=_NOW)
    _jobs_by_key(jobs)["state-nc-ie-document-index"].run_callable()

    run_nc_refresh.assert_called_once_with(
        data_type="ie-document-index",
        path=_IE_DOCUMENT_INDEX_PATH,
    )


def test_ie_transactions_job_calls_the_pathless_loader(monkeypatch: pytest.MonkeyPatch) -> None:
    run_nc_refresh = MagicMock()
    monkeypatch.setattr(_load_refresh_module(), "run_nc_refresh", run_nc_refresh)

    jobs = _build_refresh_jobs(_load_nc_config(), parameters=_full_manual_parameters(), now=_NOW)
    _jobs_by_key(jobs)["state-nc-ie-transactions"].run_callable()

    run_nc_refresh.assert_called_once_with(data_type="ie-transactions")


def test_committee_discovery_job_calls_the_discovery_loader(monkeypatch: pytest.MonkeyPatch) -> None:
    run_nc_refresh = MagicMock()
    monkeypatch.setattr(_load_refresh_module(), "run_nc_refresh", run_nc_refresh)

    jobs = _build_refresh_jobs(_load_nc_config(), parameters=RunnerParameters(), now=_NOW)
    _jobs_by_key(jobs)["state-nc-committee-discovery"].run_callable()

    run_nc_refresh.assert_called_once_with(data_type="committee-discovery")


def test_candidate_listing_job_defaults_year_from_and_path(monkeypatch: pytest.MonkeyPatch) -> None:
    load_candidate_listing_from_source = MagicMock()
    monkeypatch.setattr(
        _load_refresh_module(),
        "load_candidate_listing_from_source",
        load_candidate_listing_from_source,
    )

    jobs = _build_refresh_jobs(_load_nc_config(), parameters=RunnerParameters(), now=_NOW)
    _jobs_by_key(jobs)["civic-nc-candidate-listing"].run_callable()

    load_candidate_listing_from_source.assert_called_once_with(
        year_from=_DEFAULT_YEAR_FROM,
        candidate_listing_path=None,
    )


def test_candidate_listing_job_forwards_explicit_year_from_and_path(monkeypatch: pytest.MonkeyPatch) -> None:
    load_candidate_listing_from_source = MagicMock()
    monkeypatch.setattr(
        _load_refresh_module(),
        "load_candidate_listing_from_source",
        load_candidate_listing_from_source,
    )

    jobs = _build_refresh_jobs(
        _load_nc_config(),
        parameters=RunnerParameters(
            year_from=2019,
            candidate_listing_path=_CANDIDATE_LISTING_PATH,
        ),
        now=_NOW,
    )
    _jobs_by_key(jobs)["civic-nc-candidate-listing"].run_callable()

    load_candidate_listing_from_source.assert_called_once_with(
        year_from=2019,
        candidate_listing_path=_CANDIDATE_LISTING_PATH,
    )


def test_transactions_job_uses_the_default_calendar_year_date_range(monkeypatch: pytest.MonkeyPatch) -> None:
    run_nc_refresh = MagicMock()
    monkeypatch.setattr(_load_refresh_module(), "run_nc_refresh", run_nc_refresh)

    jobs = _build_refresh_jobs(_load_nc_config(), parameters=_full_manual_parameters(), now=_NOW)
    _jobs_by_key(jobs)["state-nc-transactions"].run_callable()

    run_nc_refresh.assert_called_once()
    assert run_nc_refresh.call_args.args == ()
    call_kwargs = dict(run_nc_refresh.call_args.kwargs)
    output_path = call_kwargs.pop("output_path")
    assert call_kwargs == {
        "data_type": "transactions",
        "download": True,
        "date_from": "01/01/2026",
        "date_to": "12/31/2026",
        "committee_id": _COMMITTEE_ID,
        "committee_name": _COMMITTEE_NAME,
        "committee_docs_path": _COMMITTEE_DOCS_PATH,
        "trans_type": None,
    }
    assert output_path.name == "transactions.csv"


def test_transactions_job_forwards_explicit_dates_and_trans_type(monkeypatch: pytest.MonkeyPatch) -> None:
    run_nc_refresh = MagicMock()
    monkeypatch.setattr(_load_refresh_module(), "run_nc_refresh", run_nc_refresh)

    jobs = _build_refresh_jobs(
        _load_nc_config(),
        parameters=_full_manual_parameters(
            nc_date_from="01/01/2026",
            nc_date_to="03/31/2026",
            nc_trans_type="exp",
        ),
        now=_NOW,
    )
    _jobs_by_key(jobs)["state-nc-transactions"].run_callable()

    call_kwargs = run_nc_refresh.call_args.kwargs
    assert call_kwargs["date_from"] == "01/01/2026"
    assert call_kwargs["date_to"] == "03/31/2026"
    assert call_kwargs["trans_type"] == "exp"
    assert call_kwargs["committee_docs_path"] == _COMMITTEE_DOCS_PATH
    assert call_kwargs["committee_id"] == _COMMITTEE_ID
    assert call_kwargs["committee_name"] == _COMMITTEE_NAME


def test_transactions_job_output_path_is_removed_after_the_run(monkeypatch: pytest.MonkeyPatch) -> None:
    observed_paths: list[Path] = []

    def _record_output_path(**kwargs: object) -> object:
        output_path = kwargs["output_path"]
        assert isinstance(output_path, Path)
        assert output_path.parent.is_dir()
        observed_paths.append(output_path)
        return None

    monkeypatch.setattr(_load_refresh_module(), "run_nc_refresh", _record_output_path)

    jobs = _build_refresh_jobs(_load_nc_config(), parameters=_full_manual_parameters(), now=_NOW)
    _jobs_by_key(jobs)["state-nc-transactions"].run_callable()

    assert len(observed_paths) == 1
    assert not observed_paths[0].parent.exists()


def test_committee_docs_path_without_full_committee_scope_raises() -> None:
    with pytest.raises(ValueError) as error_info:
        _build_refresh_jobs(
            _load_nc_config(),
            parameters=RunnerParameters(nc_committee_docs_path=_COMMITTEE_DOCS_PATH),
            now=_NOW,
        )

    assert str(error_info.value) == _MISSING_COMMITTEE_SCOPE_MESSAGE


def test_committee_docs_path_with_only_committee_id_raises() -> None:
    with pytest.raises(ValueError) as error_info:
        _build_refresh_jobs(
            _load_nc_config(),
            parameters=RunnerParameters(
                nc_committee_docs_path=_COMMITTEE_DOCS_PATH,
                nc_committee_id=_COMMITTEE_ID,
            ),
            now=_NOW,
        )

    assert str(error_info.value) == _MISSING_COMMITTEE_SCOPE_MESSAGE


def test_candidate_listing_year_selects_the_nearest_available_calendar_year(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing target year resolves forward to the smallest available year >= it."""
    cadence_calls = _patch_candidate_listing_calendar(monkeypatch, available_years=(2024, 2028, 2030))

    jobs = _build_refresh_jobs(_load_nc_config(), parameters=RunnerParameters(), now=_NOW)
    candidate_listing_job = _jobs_by_key(jobs)["civic-nc-candidate-listing"]

    # _NOW is June 2026, so the target year is 2026; it is absent, and 2028 is
    # the nearest available year at or after it. Pinning 2028 rejects now.year,
    # now.year + 1, a hard-coded 2026, and the latest-available year.
    assert cadence_calls == [{"year": 2028, "on_date": date(2026, 6, 1)}]
    assert candidate_listing_job.cadence == _SENTINEL_CADENCE


def test_candidate_listing_year_falls_back_to_the_latest_available_calendar_year(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no calendar at or after the target year, the latest available year wins."""
    cadence_calls = _patch_candidate_listing_calendar(monkeypatch, available_years=(2018, 2020))

    jobs = _build_refresh_jobs(_load_nc_config(), parameters=RunnerParameters(), now=_FILING_WINDOW_NOW)
    candidate_listing_job = _jobs_by_key(jobs)["civic-nc-candidate-listing"]

    # December look-ahead targets 2026, which no available calendar covers, so
    # the latest available year is used rather than the earliest.
    assert cadence_calls == [{"year": 2020, "on_date": date(2025, 12, 10)}]
    assert candidate_listing_job.cadence == _SENTINEL_CADENCE


def test_candidate_listing_year_uses_the_wall_clock_year_without_any_calendars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cadence_calls = _patch_candidate_listing_calendar(monkeypatch, available_years=())

    jobs = _build_refresh_jobs(_load_nc_config(), parameters=RunnerParameters(), now=_FILING_WINDOW_NOW)
    candidate_listing_job = _jobs_by_key(jobs)["civic-nc-candidate-listing"]

    # No calendars on disk drops the December look-ahead and uses now.year.
    assert cadence_calls == [{"year": 2025, "on_date": date(2025, 12, 10)}]
    assert candidate_listing_job.cadence == _SENTINEL_CADENCE


def test_ie_source_lookup_uses_transaction_type_coverage_not_source_name() -> None:
    config = _config_with_renamed_source(
        _load_nc_config(),
        source_name=_IE_DOCUMENT_INDEX_SOURCE_NAME,
        renamed_source_name=_RENAMED_IE_DOCUMENT_INDEX_SOURCE_NAME,
    )

    jobs = _build_refresh_jobs(config, parameters=_full_manual_parameters(), now=_NOW)

    assert [job.key for job in jobs] == [
        "state-nc-ie-document-index",
        "state-nc-ie-transactions",
        "state-nc-committee-discovery",
        "civic-nc-candidate-listing",
        "state-nc-transactions",
    ]
    assert jobs[0].data_source_names == (_RENAMED_IE_DOCUMENT_INDEX_SOURCE_NAME,)
    assert jobs[1].data_source_names == (_RENAMED_IE_DOCUMENT_INDEX_SOURCE_NAME,)
    assert jobs[0].cadence == "weekly"
    assert jobs[1].cadence == "weekly"


def test_ie_source_lookup_rejects_duplicate_transaction_type_coverage() -> None:
    config = _config_with_added_transaction_type(
        _load_nc_config(),
        source_name=_TRANSACTION_SOURCE_NAME,
        transaction_type=_IE_TRANSACTION_TYPE,
    )

    with pytest.raises(RuntimeError) as error_info:
        _build_refresh_jobs(config, parameters=_full_manual_parameters(), now=_NOW)

    assert str(error_info.value) == _DUPLICATE_IE_COVERAGE_MESSAGE


def test_duplicate_ie_coverage_raises_even_without_the_ie_document_index_path() -> None:
    """IE ambiguity is resolved before manual-input gating, so it always raises."""
    config = _config_with_added_transaction_type(
        _load_nc_config(),
        source_name=_TRANSACTION_SOURCE_NAME,
        transaction_type=_IE_TRANSACTION_TYPE,
    )

    with pytest.raises(RuntimeError) as error_info:
        _build_refresh_jobs(config, parameters=RunnerParameters(), now=_NOW)

    assert str(error_info.value) == _DUPLICATE_IE_COVERAGE_MESSAGE


def _config_with_update_frequencies(
    config: JurisdictionConfig,
    *,
    update_frequencies_by_source_name: dict[str, str],
) -> JurisdictionConfig:
    """Copy the config replacing ``update_frequency`` on the named data sources."""
    return config.model_copy(
        update={
            "data_sources": [
                data_source.model_copy(update={"update_frequency": update_frequencies_by_source_name[data_source.name]})
                if data_source.name in update_frequencies_by_source_name
                else data_source
                for data_source in config.data_sources
            ]
        }
    )


def test_nc_job_cadence_follows_each_matched_source_update_frequency() -> None:
    """Every source-backed NC job reads cadence from its own matched data source.

    The candidate-listing job is deliberately excluded: its cadence comes from
    ``resolve_candidate_listing_refresh_cadence`` rather than a data source, and
    is pinned by the calendar-year tests above.
    """
    config = _config_with_update_frequencies(
        _load_nc_config(),
        update_frequencies_by_source_name={
            _COMMITTEE_DOCUMENT_SOURCE_NAME: _COMMITTEE_DOCUMENT_UPDATE_FREQUENCY,
            _IE_DOCUMENT_INDEX_SOURCE_NAME: _IE_UPDATE_FREQUENCY,
            _TRANSACTION_SOURCE_NAME: _TRANSACTION_UPDATE_FREQUENCY,
        },
    )

    jobs = _build_refresh_jobs(config, parameters=_full_manual_parameters(), now=_NOW)

    assert {job.key: job.cadence for job in jobs if job.key != "civic-nc-candidate-listing"} == {
        "state-nc-ie-document-index": _IE_UPDATE_FREQUENCY,
        "state-nc-ie-transactions": _IE_UPDATE_FREQUENCY,
        "state-nc-committee-discovery": _COMMITTEE_DOCUMENT_UPDATE_FREQUENCY,
        "state-nc-transactions": _TRANSACTION_UPDATE_FREQUENCY,
    }


def test_candidate_listing_year_from_default_tracks_the_supplied_now(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The default ``year_from`` is ``now.year - 4``, not a frozen literal."""
    load_candidate_listing_from_source = MagicMock()
    monkeypatch.setattr(
        _load_refresh_module(),
        "load_candidate_listing_from_source",
        load_candidate_listing_from_source,
    )

    jobs = _build_refresh_jobs(
        _load_nc_config(),
        parameters=RunnerParameters(),
        now=datetime(2030, 1, 15, tzinfo=timezone.utc),
    )
    _jobs_by_key(jobs)["civic-nc-candidate-listing"].run_callable()

    load_candidate_listing_from_source.assert_called_once_with(
        year_from=2026,
        candidate_listing_path=None,
    )
