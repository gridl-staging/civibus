from __future__ import annotations

import inspect
from datetime import datetime, timezone
from pathlib import Path

from core.refresh.runner import RunnerParameters
from domains.campaign_finance.jurisdictions.config_schema import load_jurisdiction_config
from domains.campaign_finance.jurisdictions.states.CA.refresh import build_refresh_jobs
from domains.campaign_finance.jurisdictions.states.CA.scraper.cli import run_ca_refresh


CONFIG = load_jurisdiction_config(Path(__file__).with_name("config.yaml"))
NOW = datetime(2026, 8, 25, 14, 0, tzinfo=timezone.utc)


def test_build_refresh_jobs_preserves_metadata_and_year_override() -> None:
    jobs = build_refresh_jobs(CONFIG, RunnerParameters(ca_year_from=2023), NOW)

    assert [(job.key, job.domain, job.jurisdiction, job.cadence, job.data_source_names) for job in jobs] == [
        (
            "state-ca-refresh",
            "campaign_finance",
            "state/CA",
            "daily",
            ("CAL-ACCESS Raw Data Export",),
        )
    ]
    assert jobs[0].run_callable.func is run_ca_refresh
    assert jobs[0].run_callable.args == ()
    assert jobs[0].run_callable.keywords == {"download": True, "year_from": 2023}
    inspect.signature(jobs[0].run_callable).bind()


def test_build_refresh_jobs_uses_four_year_fallback() -> None:
    jobs = build_refresh_jobs(CONFIG, RunnerParameters(), NOW)

    assert jobs[0].run_callable.keywords == {"download": True, "year_from": 2022}


def test_build_refresh_jobs_omits_job_without_contribution_source() -> None:
    config_without_contributions = CONFIG.model_copy(
        update={
            "data_sources": [
                source for source in CONFIG.data_sources if "contributions" not in source.coverage.transaction_types
            ]
        }
    )

    assert build_refresh_jobs(config_without_contributions, RunnerParameters(), NOW) == []
