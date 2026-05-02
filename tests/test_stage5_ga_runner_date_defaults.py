from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.refresh.job_builders import _build_ga_jobs
from core.refresh.runner import RunnerParameters
from domains.campaign_finance.jurisdictions.config_schema import load_jurisdiction_config


REPO_ROOT = Path(__file__).resolve().parents[1]
GA_CONFIG_PATH = REPO_ROOT / "domains" / "campaign_finance" / "jurisdictions" / "states" / "GA" / "config.yaml"


def _ga_job_run_kwargs(parameters: RunnerParameters, *, now: datetime) -> dict[str, dict[str, Any]]:
    config = load_jurisdiction_config(GA_CONFIG_PATH)
    jobs = _build_ga_jobs(config, jurisdiction="state/GA", parameters=parameters, now=now)

    return {job.key: dict(getattr(job.run_callable, "keywords", {})) for job in jobs}


def test_ga_jobs_default_to_five_year_window_when_dates_are_not_supplied() -> None:
    now = datetime(2026, 4, 11, 12, 0, tzinfo=timezone.utc)

    job_kwargs = _ga_job_run_kwargs(RunnerParameters(), now=now)

    assert job_kwargs["state-ga-contributions"]["date_start"] == "01/01/2022"
    assert job_kwargs["state-ga-contributions"]["date_end"] == "04/11/2026"
    assert job_kwargs["state-ga-expenditures"]["date_start"] == "01/01/2022"
    assert job_kwargs["state-ga-expenditures"]["date_end"] == "04/11/2026"


def test_ga_jobs_preserve_explicit_date_overrides() -> None:
    now = datetime(2026, 4, 11, 12, 0, tzinfo=timezone.utc)
    parameters = RunnerParameters(ga_date_start="02/03/2024", ga_date_end="03/04/2025")

    job_kwargs = _ga_job_run_kwargs(parameters, now=now)

    assert job_kwargs["state-ga-contributions"]["date_start"] == "02/03/2024"
    assert job_kwargs["state-ga-contributions"]["date_end"] == "03/04/2025"
    assert job_kwargs["state-ga-expenditures"]["date_start"] == "02/03/2024"
    assert job_kwargs["state-ga-expenditures"]["date_end"] == "03/04/2025"
