from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from core.refresh.runner import RunnerParameters
from domains.campaign_finance.jurisdictions.config_schema import JurisdictionConfig, load_jurisdiction_config
from domains.campaign_finance.jurisdictions.states.MN import refresh as mn_refresh
from domains.campaign_finance.jurisdictions.states.MN.scraper.cli import run_mn_refresh

NOW = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
CONFIG_PATH = Path(__file__).with_name("config.yaml")
EXPECTED_JOBS = (
    ("state-mn-contributions", "contributions"),
    ("state-mn-expenditures", "expenditures"),
    ("state-mn-independent_expenditures", "independent_expenditures"),
)


def _load_config(*, jurisdiction_code: str | None = None) -> JurisdictionConfig:
    config = load_jurisdiction_config(CONFIG_PATH)
    if jurisdiction_code is None:
        return config
    jurisdiction = config.jurisdiction.model_copy(update={"code": jurisdiction_code})
    return config.model_copy(update={"jurisdiction": jurisdiction})


def _source_for_data_type(config: JurisdictionConfig, data_type: str):
    return next(source for source in config.data_sources if data_type in source.coverage.transaction_types)


def _without_data_type(config: JurisdictionConfig, data_type: str) -> JurisdictionConfig:
    omitted_source = _source_for_data_type(config, data_type)
    return config.model_copy(
        update={"data_sources": [source for source in config.data_sources if source != omitted_source]}
    )


def test_build_refresh_jobs_matches_mn_package_api() -> None:
    config = _load_config()
    jobs = mn_refresh.build_refresh_jobs(config, RunnerParameters(), NOW)

    assert [job.key for job in jobs] == [key for key, _data_type in EXPECTED_JOBS]
    for job, (_key, data_type) in zip(jobs, EXPECTED_JOBS, strict=True):
        source = _source_for_data_type(config, data_type)
        assert job.domain == "campaign_finance"
        assert job.jurisdiction == "state/MN"
        assert job.cadence == source.update_frequency
        assert job.data_source_names == (source.name,)
        assert job.run_callable.func is run_mn_refresh
        assert job.run_callable.keywords == {"data_type": data_type, "download": True}

    alternate_jobs = mn_refresh.build_refresh_jobs(_load_config(jurisdiction_code="ZZ"), RunnerParameters(), NOW)
    assert [job.key for job in alternate_jobs] == [f"state-zz-{data_type}" for _key, data_type in EXPECTED_JOBS]
    assert all(job.jurisdiction == "state/ZZ" for job in alternate_jobs)


def test_build_refresh_jobs_omits_only_missing_source() -> None:
    config = _load_config()
    jobs = mn_refresh.build_refresh_jobs(_without_data_type(config, "expenditures"), RunnerParameters(), NOW)

    assert [job.key for job in jobs] == ["state-mn-contributions", "state-mn-independent_expenditures"]
