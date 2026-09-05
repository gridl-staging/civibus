from __future__ import annotations

from datetime import datetime, timezone
from functools import partial
from pathlib import Path

from core.refresh.runner import RefreshJob, RunnerParameters
from domains.campaign_finance.jurisdictions.config_schema import (
    DataSourceConfig,
    JurisdictionConfig,
    load_jurisdiction_config,
)
from domains.campaign_finance.jurisdictions.states.GA.refresh import build_refresh_jobs
from domains.campaign_finance.jurisdictions.states.GA.scraper.cli import run_ga_refresh


_CONFIG_PATH = Path(__file__).with_name("config.yaml")
_NOW = datetime(2026, 4, 11, 12, 0, tzinfo=timezone.utc)


def _data_source_for_transaction_type(config: JurisdictionConfig, transaction_type: str) -> DataSourceConfig:
    matches = [source for source in config.data_sources if transaction_type in source.coverage.transaction_types]
    assert len(matches) == 1, (
        f"expected exactly one {config.jurisdiction.code} source covering {transaction_type!r}, "
        f"found {[source.name for source in matches]}"
    )
    return matches[0]


def _refresh_call(job: RefreshJob) -> tuple[object, dict[str, object]]:
    call = job.run_callable
    assert isinstance(call, partial), f"expected a partial run_callable for job {job.key!r}"
    assert not call.args, f"expected a keyword-only refresh binding for job {job.key!r}"
    return call.func, dict(call.keywords)


def _assert_job_uses_source(job: RefreshJob, source: DataSourceConfig) -> None:
    assert job.data_source_names == (source.name,), (
        f"job {job.key!r} expected data sources {(source.name,)!r}, got {job.data_source_names!r}"
    )
    assert job.cadence == source.update_frequency, (
        f"job {job.key!r} expected cadence {source.update_frequency!r}, got {job.cadence!r}"
    )


def test_build_refresh_jobs_uses_default_date_window_and_candidate() -> None:
    config = load_jurisdiction_config(_CONFIG_PATH)
    parameters = RunnerParameters(ga_candidate="Candidate Name")

    jobs = build_refresh_jobs(config, parameters, _NOW)

    assert [job.key for job in jobs] == [
        "state-ga-contributions",
        "state-ga-expenditures",
    ]
    assert all(job.domain == "campaign_finance" for job in jobs)
    assert all(job.jurisdiction == "state/GA" for job in jobs)

    for job, data_type in zip(jobs, ("contributions", "expenditures"), strict=True):
        _assert_job_uses_source(job, _data_source_for_transaction_type(config, data_type))
        assert _refresh_call(job) == (
            run_ga_refresh,
            {
                "data_type": data_type,
                "download": True,
                "candidate": parameters.ga_candidate,
                "date_start": f"01/01/{_NOW.year - 4}",
                "date_end": _NOW.strftime("%m/%d/%Y"),
            },
        )


def test_build_refresh_jobs_preserves_explicit_date_overrides() -> None:
    config = load_jurisdiction_config(_CONFIG_PATH)
    parameters = RunnerParameters(
        ga_date_start="02/03/2024",
        ga_date_end="03/04/2025",
    )

    jobs = build_refresh_jobs(config, parameters, _NOW)

    assert [job.key for job in jobs] == [
        "state-ga-contributions",
        "state-ga-expenditures",
    ]
    for job in jobs:
        _, keywords = _refresh_call(job)
        assert keywords["date_start"] == parameters.ga_date_start
        assert keywords["date_end"] == parameters.ga_date_end


def test_build_refresh_jobs_returns_no_jobs_without_sources() -> None:
    config = load_jurisdiction_config(_CONFIG_PATH)
    config_without_sources = config.model_copy(update={"data_sources": []})

    assert build_refresh_jobs(config_without_sources, RunnerParameters(), _NOW) == []
