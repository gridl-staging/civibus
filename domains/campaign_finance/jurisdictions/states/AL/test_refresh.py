"""Contract tests for the AL package-local refresh builder."""

from __future__ import annotations

from datetime import datetime, timezone
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
from domains.campaign_finance.jurisdictions.states.AL.scraper import load_supported_data_types

_CONFIG_PATH = Path(__file__).resolve().parent / "config.yaml"
_NOW = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
_EXPECTED_YEAR_FROM = 2022
_CONTRIBUTIONS_SOURCE_NAME = "AL FCPA Campaign Finance — Contributions"
_EXPENDITURES_SOURCE_NAME = "AL FCPA Campaign Finance — Expenditures"
_RENAMED_CONTRIBUTIONS_SOURCE_NAME = "Renamed AL Contribution Feed"
_REFRESH_MODULE_NAME = "domains.campaign_finance.jurisdictions.states.AL.refresh"
# AL is the only one of the four packages whose loadable data types are derived
# from the on-disk data-source blocks rather than a literal in core, so the
# expected job keys are derived the same way and the derivation is asserted
# separately below.
_EXPECTED_DATA_TYPES = ("contributions", "expenditures")
_WEEKLY_UPDATE_FREQUENCY = "weekly"


def _load_al_config() -> JurisdictionConfig:
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


def test_build_refresh_jobs_returns_contributions_then_expenditures() -> None:
    jobs = _build_refresh_jobs(_load_al_config(), parameters=RunnerParameters(), now=_NOW)

    assert [job.key for job in jobs] == ["state-al-contributions", "state-al-expenditures"]


def test_al_jobs_carry_campaign_finance_metadata_and_daily_source_cadence() -> None:
    jobs = _build_refresh_jobs(_load_al_config(), parameters=RunnerParameters(), now=_NOW)

    jobs_by_key = {job.key: job for job in jobs}
    contributions_job = jobs_by_key["state-al-contributions"]
    expenditures_job = jobs_by_key["state-al-expenditures"]

    assert contributions_job.domain == "campaign_finance"
    assert contributions_job.jurisdiction == "state/AL"
    assert contributions_job.cadence == "daily"
    assert contributions_job.data_source_names == (_CONTRIBUTIONS_SOURCE_NAME,)

    assert expenditures_job.domain == "campaign_finance"
    assert expenditures_job.jurisdiction == "state/AL"
    assert expenditures_job.cadence == "daily"
    assert expenditures_job.data_source_names == (_EXPENDITURES_SOURCE_NAME,)


def test_al_jobs_omit_data_types_without_a_matching_data_source() -> None:
    config = _load_al_config()
    contributions_only_config = config.model_copy(
        update={
            "data_sources": [
                data_source for data_source in config.data_sources if data_source.name == _CONTRIBUTIONS_SOURCE_NAME
            ]
        }
    )
    sourceless_config = config.model_copy(update={"data_sources": []})

    contributions_only_jobs = _build_refresh_jobs(
        contributions_only_config,
        parameters=RunnerParameters(),
        now=_NOW,
    )
    sourceless_jobs = _build_refresh_jobs(
        sourceless_config,
        parameters=RunnerParameters(),
        now=_NOW,
    )

    assert [job.key for job in contributions_only_jobs] == ["state-al-contributions"]
    assert sourceless_jobs == []


def test_al_source_lookup_uses_transaction_type_coverage_not_source_name() -> None:
    config = _load_al_config()
    renamed_config = config.model_copy(
        update={
            "data_sources": [
                data_source.model_copy(update={"name": _RENAMED_CONTRIBUTIONS_SOURCE_NAME})
                if data_source.name == _CONTRIBUTIONS_SOURCE_NAME
                else data_source
                for data_source in config.data_sources
            ]
        }
    )

    jobs = _build_refresh_jobs(renamed_config, parameters=RunnerParameters(), now=_NOW)

    assert [job.key for job in jobs] == ["state-al-contributions", "state-al-expenditures"]
    assert jobs[0].data_source_names == (_RENAMED_CONTRIBUTIONS_SOURCE_NAME,)


def test_al_source_lookup_rejects_duplicate_transaction_type_coverage() -> None:
    config = _load_al_config()
    duplicate_config = config.model_copy(
        update={
            "data_sources": [
                data_source.model_copy(
                    update={
                        "coverage": data_source.coverage.model_copy(
                            update={"transaction_types": ["contributions", "expenditures"]}
                        )
                    }
                )
                if data_source.name == _EXPENDITURES_SOURCE_NAME
                else data_source
                for data_source in config.data_sources
            ]
        }
    )

    with pytest.raises(RuntimeError) as error_info:
        _build_refresh_jobs(duplicate_config, parameters=RunnerParameters(), now=_NOW)

    assert str(error_info.value) == (
        "Refresh runner expected one data source for AL transaction type 'contributions', found 2"
    )


def test_al_run_callables_forward_download_kwargs(monkeypatch: pytest.MonkeyPatch) -> None:
    run_al_refresh = MagicMock()
    monkeypatch.setattr(_load_refresh_module(), "run_al_refresh", run_al_refresh)

    jobs = _build_refresh_jobs(
        _load_al_config(),
        parameters=RunnerParameters(year_from=2019),
        now=_NOW,
    )
    for job in jobs:
        job.run_callable()

    assert [call.args for call in run_al_refresh.call_args_list] == [(), ()]
    assert [call.kwargs for call in run_al_refresh.call_args_list] == [
        {"year_from": 2019, "data_type": "contributions", "download": True},
        {"year_from": 2019, "data_type": "expenditures", "download": True},
    ]


def test_al_year_from_default_tracks_the_supplied_now(monkeypatch: pytest.MonkeyPatch) -> None:
    run_al_refresh = MagicMock()
    monkeypatch.setattr(_load_refresh_module(), "run_al_refresh", run_al_refresh)

    jobs = _build_refresh_jobs(
        _load_al_config(),
        parameters=RunnerParameters(),
        now=datetime(2030, 1, 15, tzinfo=timezone.utc),
    )
    next(job for job in jobs if job.key == "state-al-contributions").run_callable()

    run_al_refresh.assert_called_once_with(year_from=2026, data_type="contributions", download=True)


def _config_with_update_frequency(
    config: JurisdictionConfig,
    *,
    source_name: str,
    update_frequency: str,
) -> JurisdictionConfig:
    """Copy the config with one data source's ``update_frequency`` replaced."""
    return config.model_copy(
        update={
            "data_sources": [
                data_source.model_copy(update={"update_frequency": update_frequency})
                if data_source.name == source_name
                else data_source
                for data_source in config.data_sources
            ]
        }
    )


def test_al_job_keys_are_derived_from_the_scraper_supported_data_types() -> None:
    """The AL data types come from the scraper package, not a hard-coded tuple."""
    supported_data_types = load_supported_data_types()

    jobs = _build_refresh_jobs(_load_al_config(), parameters=RunnerParameters(), now=_NOW)

    assert supported_data_types == _EXPECTED_DATA_TYPES
    assert [job.key for job in jobs] == [f"state-al-{data_type}" for data_type in supported_data_types]


def test_al_job_cadence_follows_the_matched_source_update_frequency() -> None:
    """Cadence is read from the matched source, not hard-coded to the shipped daily."""
    weekly_contributions_config = _config_with_update_frequency(
        _load_al_config(),
        source_name=_CONTRIBUTIONS_SOURCE_NAME,
        update_frequency=_WEEKLY_UPDATE_FREQUENCY,
    )

    jobs = _build_refresh_jobs(weekly_contributions_config, parameters=RunnerParameters(), now=_NOW)

    assert {job.key: job.cadence for job in jobs} == {
        "state-al-contributions": _WEEKLY_UPDATE_FREQUENCY,
        "state-al-expenditures": "daily",
    }
