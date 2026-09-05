"""Contract tests for the Los Angeles package-local refresh builder."""

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
_CONTRIBUTIONS_SOURCE_NAME = "LA Ethics Campaign Contributions"
_REFRESH_MODULE_NAME = "domains.campaign_finance.jurisdictions.cities.LA.refresh"
_WEEKLY_UPDATE_FREQUENCY = "weekly"


def _load_la_config() -> JurisdictionConfig:
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


def test_build_refresh_jobs_returns_the_single_la_transactions_job() -> None:
    jobs = _build_refresh_jobs(_load_la_config(), parameters=RunnerParameters(), now=_NOW)

    assert len(jobs) == 1
    job = jobs[0]
    assert job.key == "city-la-transactions"
    assert job.domain == "campaign_finance"
    assert job.jurisdiction == "municipality/LA"
    assert job.cadence == "daily"
    assert job.data_source_names == (_CONTRIBUTIONS_SOURCE_NAME,)


def test_la_job_is_omitted_when_the_named_source_is_absent() -> None:
    config = _load_la_config()
    sourceless_config = config.model_copy(update={"data_sources": []})
    renamed_config = config.model_copy(
        update={
            "data_sources": [
                data_source.model_copy(update={"name": "LA Ethics Something Else"})
                for data_source in config.data_sources
            ]
        }
    )

    assert _build_refresh_jobs(sourceless_config, parameters=RunnerParameters(), now=_NOW) == []
    assert _build_refresh_jobs(renamed_config, parameters=RunnerParameters(), now=_NOW) == []


# The city loader entry point is ``run_la_refresh``; the central switchboard
# imports it aliased as ``run_la_city_refresh`` to avoid colliding with the
# state LA loader. Inside this package either name is a correct local import,
# so accept both rather than pinning an incidental alias.
_CITY_REFRESH_CALLABLE_NAMES = ("run_la_refresh", "run_la_city_refresh")


def _patch_city_refresh_callable(monkeypatch: pytest.MonkeyPatch, replacement: MagicMock) -> str:
    la_refresh = _load_refresh_module()
    for attribute_name in _CITY_REFRESH_CALLABLE_NAMES:
        if hasattr(la_refresh, attribute_name):
            monkeypatch.setattr(la_refresh, attribute_name, replacement)
            return attribute_name
    raise AssertionError(
        f"LA city refresh module exposes none of {_CITY_REFRESH_CALLABLE_NAMES}; "
        "the transactions job cannot be wired to the package loader"
    )


def test_la_run_callable_forwards_download_kwargs(monkeypatch: pytest.MonkeyPatch) -> None:
    run_city_refresh = MagicMock()
    _patch_city_refresh_callable(monkeypatch, run_city_refresh)

    jobs = _build_refresh_jobs(_load_la_config(), parameters=RunnerParameters(), now=_NOW)
    jobs[0].run_callable()

    run_city_refresh.assert_called_once_with(data_type="transactions", download=True)


def test_la_job_cadence_follows_the_matched_source_update_frequency() -> None:
    """Cadence is read from the matched source, not hard-coded to the shipped daily."""
    config = _load_la_config()
    weekly_config = config.model_copy(
        update={
            "data_sources": [
                data_source.model_copy(update={"update_frequency": _WEEKLY_UPDATE_FREQUENCY})
                if data_source.name == _CONTRIBUTIONS_SOURCE_NAME
                else data_source
                for data_source in config.data_sources
            ]
        }
    )

    jobs = _build_refresh_jobs(weekly_config, parameters=RunnerParameters(), now=_NOW)

    assert len(jobs) == 1
    assert jobs[0].cadence == _WEEKLY_UPDATE_FREQUENCY
