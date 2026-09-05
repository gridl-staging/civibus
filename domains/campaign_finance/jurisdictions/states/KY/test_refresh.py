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
from domains.campaign_finance.jurisdictions.states.KY.refresh import (
    _CONTRIBUTION_ELECTION_DATES,
    build_refresh_jobs,
)
from domains.campaign_finance.jurisdictions.states.KY.scraper.cli import run_ky_refresh


_CONFIG_PATH = Path(__file__).with_name("config.yaml")
_NOW = datetime(2026, 4, 13, tzinfo=timezone.utc)


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


def test_build_refresh_jobs_preserves_kentucky_job_contract() -> None:
    config = load_jurisdiction_config(_CONFIG_PATH)

    jobs = build_refresh_jobs(config, RunnerParameters(), _NOW)

    assert [job.key for job in jobs] == [
        "state-ky-expenditures",
        *[
            f"state-ky-contributions-{election_date.replace('/', '-')}"
            for election_date in _CONTRIBUTION_ELECTION_DATES
        ],
    ]
    assert all(job.domain == "campaign_finance" for job in jobs)
    assert all(job.jurisdiction == "state/KY" for job in jobs)

    _assert_job_uses_source(jobs[0], _data_source_for_transaction_type(config, "expenditures"))
    assert _refresh_call(jobs[0]) == (
        run_ky_refresh,
        {
            "data_type": "expenditures",
            "download": True,
            "year_from": _NOW.year - 4,
        },
    )

    contribution_source = _data_source_for_transaction_type(config, "contributions")
    for job, election_date in zip(jobs[1:], _CONTRIBUTION_ELECTION_DATES, strict=True):
        _assert_job_uses_source(job, contribution_source)
        assert _refresh_call(job) == (
            run_ky_refresh,
            {
                "data_type": "contributions",
                "download": True,
                "year_from": _NOW.year - 4,
                "election_date": f"{election_date} 12:00:00 AM",
            },
        )


def test_build_refresh_jobs_returns_no_jobs_without_sources() -> None:
    config = load_jurisdiction_config(_CONFIG_PATH)
    config_without_sources = config.model_copy(update={"data_sources": []})

    assert build_refresh_jobs(config_without_sources, RunnerParameters(), _NOW) == []
