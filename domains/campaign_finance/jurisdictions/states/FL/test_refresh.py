"""Contract tests for the FL package-local refresh builder."""

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

_CONFIG_PATH = Path(__file__).resolve().parent / "config.yaml"
_NOW = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
_CONTRIBUTIONS_SOURCE_NAME = "FL DOS Campaign Finance - Contributions"
_EXPENDITURES_SOURCE_NAME = "FL DOS Campaign Finance - Expenditures"
_TRANSFERS_SOURCE_NAME = "FL DOS Campaign Finance - Transfers"
_OTHER_SOURCE_NAME = "FL DOS Campaign Finance - Other Disbursements"
_RENAMED_CONTRIBUTIONS_SOURCE_NAME = "Renamed FL Contribution Feed"
_REFRESH_MODULE_NAME = "domains.campaign_finance.jurisdictions.states.FL.refresh"
_WEEKLY_UPDATE_FREQUENCY = "weekly"
_OFFICEHOLDER_SOURCE_NAMES = (
    "FL Senate Officeholder Directory",
    "FL House Representatives Directory (Blocked in Datacenter)",
)
_EXPECTED_JOB_KEYS = [
    "state-fl-contributions",
    "state-fl-expenditures",
    "state-fl-transfers",
    "state-fl-other",
]
_EXPECTED_SOURCE_NAMES_BY_KEY = {
    "state-fl-contributions": (_CONTRIBUTIONS_SOURCE_NAME,),
    "state-fl-expenditures": (_EXPENDITURES_SOURCE_NAME,),
    "state-fl-transfers": (_TRANSFERS_SOURCE_NAME,),
    "state-fl-other": (_OTHER_SOURCE_NAME,),
}


def _load_fl_config() -> JurisdictionConfig:
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


def _config_keeping_only(
    config: JurisdictionConfig,
    *,
    source_names: tuple[str, ...] = (),
) -> JurisdictionConfig:
    """Copy the config keeping only the named data sources."""
    return config.model_copy(
        update={
            "data_sources": [data_source for data_source in config.data_sources if data_source.name in source_names]
        }
    )


def test_build_refresh_jobs_returns_the_four_fl_transaction_jobs_in_order() -> None:
    jobs = _build_refresh_jobs(_load_fl_config(), parameters=RunnerParameters(), now=_NOW)

    assert [job.key for job in jobs] == _EXPECTED_JOB_KEYS


def test_fl_jobs_carry_daily_campaign_finance_metadata_and_matching_source_names() -> None:
    jobs = _build_refresh_jobs(_load_fl_config(), parameters=RunnerParameters(), now=_NOW)

    for job in jobs:
        assert job.domain == "campaign_finance"
        assert job.jurisdiction == "state/FL"
        assert job.cadence == "daily"
    assert {job.key: job.data_source_names for job in jobs} == _EXPECTED_SOURCE_NAMES_BY_KEY


def test_fl_jobs_exclude_the_weekly_officeholder_directory_sources() -> None:
    jobs = _build_refresh_jobs(_load_fl_config(), parameters=RunnerParameters(), now=_NOW)

    bound_source_names = {source_name for job in jobs for source_name in job.data_source_names}
    assert bound_source_names.isdisjoint(_OFFICEHOLDER_SOURCE_NAMES)


def test_fl_jobs_omit_data_types_without_a_matching_data_source() -> None:
    config = _load_fl_config()

    partial_jobs = _build_refresh_jobs(
        _config_keeping_only(config, source_names=(_CONTRIBUTIONS_SOURCE_NAME, _TRANSFERS_SOURCE_NAME)),
        parameters=RunnerParameters(),
        now=_NOW,
    )
    officeholder_only_jobs = _build_refresh_jobs(
        _config_keeping_only(config, source_names=_OFFICEHOLDER_SOURCE_NAMES),
        parameters=RunnerParameters(),
        now=_NOW,
    )

    assert [job.key for job in partial_jobs] == ["state-fl-contributions", "state-fl-transfers"]
    assert officeholder_only_jobs == []


def test_fl_source_lookup_uses_transaction_type_coverage_not_source_name() -> None:
    config = _load_fl_config()
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

    assert [job.key for job in jobs] == _EXPECTED_JOB_KEYS
    assert jobs[0].data_source_names == (_RENAMED_CONTRIBUTIONS_SOURCE_NAME,)


def test_fl_source_lookup_rejects_duplicate_transaction_type_coverage() -> None:
    config = _load_fl_config()
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
        "Refresh runner expected one data source for FL transaction type 'contributions', found 2"
    )


def test_fl_run_callables_forward_download_kwargs_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    run_fl_refresh = MagicMock()
    monkeypatch.setattr(_load_refresh_module(), "run_fl_refresh", run_fl_refresh)

    jobs = _build_refresh_jobs(_load_fl_config(), parameters=RunnerParameters(), now=_NOW)
    for job in jobs:
        job.run_callable()

    assert [call.args for call in run_fl_refresh.call_args_list] == [(), (), (), ()]
    assert [call.kwargs for call in run_fl_refresh.call_args_list] == [
        {"data_type": "contributions", "download": True},
        {"data_type": "expenditures", "download": True},
        {"data_type": "transfers", "download": True},
        {"data_type": "other", "download": True},
    ]


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


def test_fl_job_cadence_follows_the_matched_source_update_frequency() -> None:
    """Cadence is read from the matched source, not hard-coded to the shipped daily."""
    weekly_contributions_config = _config_with_update_frequency(
        _load_fl_config(),
        source_name=_CONTRIBUTIONS_SOURCE_NAME,
        update_frequency=_WEEKLY_UPDATE_FREQUENCY,
    )

    jobs = _build_refresh_jobs(weekly_contributions_config, parameters=RunnerParameters(), now=_NOW)

    assert {job.key: job.cadence for job in jobs} == {
        "state-fl-contributions": _WEEKLY_UPDATE_FREQUENCY,
        "state-fl-expenditures": "daily",
        "state-fl-transfers": "daily",
        "state-fl-other": "daily",
    }
