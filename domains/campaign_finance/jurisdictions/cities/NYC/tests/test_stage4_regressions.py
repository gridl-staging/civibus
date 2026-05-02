"""Stage 4 regression tests for the NYC city pipeline surface."""

from __future__ import annotations

from pathlib import Path

from core.refresh import job_builders

_NYC_SCRAPER_DIR = Path(__file__).resolve().parent.parent / "scraper"


def test_nyc_loader_module_exists() -> None:
    assert (_NYC_SCRAPER_DIR / "load.py").is_file()


def test_nyc_cli_module_exists() -> None:
    assert (_NYC_SCRAPER_DIR / "cli.py").is_file()


def test_nyc_loader_exports_public_api() -> None:
    from domains.campaign_finance.jurisdictions.cities.NYC.scraper.load import (
        LoadResult,
        ensure_nyc_data_source,
        load_nyc_transactions_with_filings,
    )

    assert callable(ensure_nyc_data_source)
    assert callable(load_nyc_transactions_with_filings)
    assert LoadResult is not None


def test_nyc_cli_exports_public_api() -> None:
    from domains.campaign_finance.jurisdictions.cities.NYC.scraper.cli import (
        main,
        run_nyc_refresh,
    )

    assert callable(run_nyc_refresh)
    assert callable(main)


def test_build_refresh_plan_all_scope_includes_nyc_city_job() -> None:
    jobs = job_builders.build_refresh_plan(scope="all")
    job_keys = {job.key for job in jobs}

    assert "city-nyc-transactions" in job_keys


def test_nyc_city_job_metadata_matches_config() -> None:
    jobs = job_builders.build_refresh_plan(scope="all")
    nyc_jobs = [job for job in jobs if job.key == "city-nyc-transactions"]

    assert len(nyc_jobs) == 1
    nyc_job = nyc_jobs[0]
    assert nyc_job.domain == "campaign_finance"
    assert nyc_job.jurisdiction == "municipality/NYC"
    assert nyc_job.cadence == "monthly"
    assert nyc_job.data_source_names == ("NYC CFB Campaign Contributions",)
