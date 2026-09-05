from __future__ import annotations

from datetime import datetime, timezone
from functools import partial
from pathlib import Path

from core.refresh.runner import RefreshJob, RunnerParameters
from domains.campaign_finance.jurisdictions.cities.PHL.refresh import build_refresh_jobs
from domains.campaign_finance.jurisdictions.cities.PHL.scraper.cli import run_phl_refresh
from domains.campaign_finance.jurisdictions.config_schema import (
    DataSourceConfig,
    JurisdictionConfig,
    load_jurisdiction_config,
)


_CONFIG_PATH = Path(__file__).with_name("config.yaml")
_NOW = datetime(2026, 4, 13, tzinfo=timezone.utc)

# PHL keeps one Carto SQL table per transaction type, and the core arm resolves
# each job by exact source name rather than by coverage.
_SOURCE_NAMES_BY_DATA_TYPE = {
    "contributions": "PHL Campaign Finance Contributions",
    "expenditures": "PHL Campaign Finance Expenditures",
}


def _data_source_named(config: JurisdictionConfig, source_name: str) -> DataSourceConfig:
    matches = [source for source in config.data_sources if source.name == source_name]
    assert len(matches) == 1, (
        f"expected exactly one {config.jurisdiction.code} source named {source_name!r}, found {len(matches)}"
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


def test_build_refresh_jobs_preserves_philadelphia_job_contract() -> None:
    config = load_jurisdiction_config(_CONFIG_PATH)

    jobs = build_refresh_jobs(config, RunnerParameters(), _NOW)

    assert [job.key for job in jobs] == [
        "city-phl-contributions",
        "city-phl-expenditures",
    ]
    assert all(job.domain == "campaign_finance" for job in jobs)
    assert all(job.jurisdiction == "municipality/PHL" for job in jobs)

    for job, data_type in zip(jobs, ("contributions", "expenditures"), strict=True):
        _assert_job_uses_source(job, _data_source_named(config, _SOURCE_NAMES_BY_DATA_TYPE[data_type]))
        assert _refresh_call(job) == (
            run_phl_refresh,
            {
                "data_type": data_type,
                "download": True,
            },
        )


def test_build_refresh_jobs_returns_no_jobs_without_sources() -> None:
    config = load_jurisdiction_config(_CONFIG_PATH)
    config_without_sources = config.model_copy(update={"data_sources": []})

    assert build_refresh_jobs(config_without_sources, RunnerParameters(), _NOW) == []
