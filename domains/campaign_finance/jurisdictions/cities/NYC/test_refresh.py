from __future__ import annotations

from datetime import datetime, timezone
from functools import partial
from pathlib import Path

from core.refresh.runner import RefreshJob, RunnerParameters
from domains.campaign_finance.jurisdictions.cities.NYC.refresh import build_refresh_jobs
from domains.campaign_finance.jurisdictions.cities.NYC.scraper.cli import run_nyc_refresh
from domains.campaign_finance.jurisdictions.config_schema import (
    DataSourceConfig,
    JurisdictionConfig,
    load_jurisdiction_config,
)


_CONFIG_PATH = Path(__file__).with_name("config.yaml")
_NOW = datetime(2026, 4, 13, tzinfo=timezone.utc)


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


def test_build_refresh_jobs_preserves_new_york_city_job_contract() -> None:
    config = load_jurisdiction_config(_CONFIG_PATH)
    # NYC resolves its single job by exact source name, matching the core arm.
    source = _data_source_named(config, "NYC CFB Campaign Contributions")

    jobs = build_refresh_jobs(config, RunnerParameters(), _NOW)

    assert [job.key for job in jobs] == ["city-nyc-transactions"]
    job = jobs[0]
    assert job.domain == "campaign_finance"
    assert job.jurisdiction == "municipality/NYC"
    assert source.update_frequency == "monthly"
    _assert_job_uses_source(job, source)
    assert _refresh_call(job) == (
        run_nyc_refresh,
        {
            "data_type": "transactions",
            "download": True,
        },
    )


def test_build_refresh_jobs_returns_no_jobs_without_sources() -> None:
    config = load_jurisdiction_config(_CONFIG_PATH)
    config_without_sources = config.model_copy(update={"data_sources": []})

    assert build_refresh_jobs(config_without_sources, RunnerParameters(), _NOW) == []
