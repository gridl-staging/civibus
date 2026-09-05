from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from core.refresh.runner import RunnerParameters
from domains.campaign_finance.jurisdictions.config_schema import JurisdictionConfig, load_jurisdiction_config
from domains.campaign_finance.jurisdictions.states.OR import refresh as or_refresh
from domains.campaign_finance.jurisdictions.states.OR.scraper.cli import run_or_refresh

NOW = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
CONFIG_PATH = Path(__file__).with_name("config.yaml")
EXPECTED_JOBS = (
    ("state-or-contributions", "contributions"),
    ("state-or-expenditures", "expenditures"),
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


def test_build_refresh_jobs_matches_or_package_api() -> None:
    config = _load_config()
    jobs = or_refresh.build_refresh_jobs(config, RunnerParameters(), NOW)

    assert [job.key for job in jobs] == [key for key, _data_type in EXPECTED_JOBS]
    for job, (_key, data_type) in zip(jobs, EXPECTED_JOBS, strict=True):
        source = _source_for_data_type(config, data_type)
        assert job.domain == "campaign_finance"
        assert job.jurisdiction == "state/OR"
        assert job.cadence == source.update_frequency
        assert job.data_source_names == (source.name,)
        assert job.run_callable.func is run_or_refresh
        assert job.run_callable.keywords == {"data_type": data_type, "download": True, "year_from": 2022}

    alternate_jobs = or_refresh.build_refresh_jobs(
        _load_config(jurisdiction_code="ZZ"), RunnerParameters(), NOW.replace(year=2031)
    )
    assert [job.key for job in alternate_jobs] == [f"state-zz-{data_type}" for _key, data_type in EXPECTED_JOBS]
    assert all(job.jurisdiction == "state/ZZ" for job in alternate_jobs)
    assert all(job.run_callable.keywords["year_from"] == 2027 for job in alternate_jobs)


def test_build_refresh_jobs_omits_only_missing_source() -> None:
    config = _load_config()
    jobs = or_refresh.build_refresh_jobs(_without_data_type(config, "contributions"), RunnerParameters(), NOW)

    assert [job.key for job in jobs] == ["state-or-expenditures"]
