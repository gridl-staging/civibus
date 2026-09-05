from __future__ import annotations

import inspect
from datetime import datetime, timezone
from pathlib import Path

from core.refresh.runner import RunnerParameters
from domains.campaign_finance.jurisdictions.config_schema import load_jurisdiction_config
from domains.campaign_finance.jurisdictions.states.WI.refresh import build_refresh_jobs
from domains.campaign_finance.jurisdictions.states.WI.scraper.cli import run_wi_refresh


CONFIG = load_jurisdiction_config(Path(__file__).with_name("config.yaml"))
NOW = datetime(2026, 8, 25, 14, 0, tzinfo=timezone.utc)


def test_build_refresh_jobs_preserves_metadata_and_callable_arguments() -> None:
    jobs = build_refresh_jobs(CONFIG, RunnerParameters(), NOW)

    assert [(job.key, job.domain, job.jurisdiction, job.cadence, job.data_source_names) for job in jobs] == [
        (
            "state-wi-transactions",
            "campaign_finance",
            "state/WI",
            "daily",
            ("WI Sunshine Transactions Export",),
        )
    ]
    assert jobs[0].run_callable.func is run_wi_refresh
    assert jobs[0].run_callable.args == ()
    assert jobs[0].run_callable.keywords == {"data_type": "transactions", "download": True}
    inspect.signature(jobs[0].run_callable).bind()


def test_build_refresh_jobs_omits_job_without_transaction_source() -> None:
    config_without_transactions = CONFIG.model_copy(
        update={
            "data_sources": [
                source for source in CONFIG.data_sources if "transactions" not in source.coverage.transaction_types
            ]
        }
    )

    assert build_refresh_jobs(config_without_transactions, RunnerParameters(), NOW) == []
