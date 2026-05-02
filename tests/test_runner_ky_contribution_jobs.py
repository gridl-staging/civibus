"""Verify KY contribution jobs use election-date scoping instead of full export."""

from __future__ import annotations

from datetime import datetime, timezone

from core.refresh.job_builders import _KY_CONTRIBUTION_ELECTION_DATES, _build_ky_jobs


def _fake_config():
    """Build a minimal JurisdictionConfig-like object for KY."""
    from types import SimpleNamespace

    coverage = SimpleNamespace(transaction_types=["contributions", "expenditures"])
    return SimpleNamespace(
        data_sources=[
            SimpleNamespace(
                name="KY KREF Campaign Finance",
                update_frequency="weekly",
                coverage=coverage,
            ),
        ],
    )


def test_ky_jobs_contain_election_date_scoped_contributions() -> None:
    """Each KY election date should produce a separate contribution job."""
    config = _fake_config()
    now = datetime(2026, 4, 13, tzinfo=timezone.utc)
    jobs = _build_ky_jobs(config, jurisdiction="state/KY", now=now)

    contribution_jobs = [j for j in jobs if "contributions" in j.key]
    expenditure_jobs = [j for j in jobs if "expenditures" in j.key]

    # One expenditure job (standard full export)
    assert len(expenditure_jobs) == 1
    assert expenditure_jobs[0].key == "state-ky-expenditures"

    # One contribution job per election date
    assert len(contribution_jobs) == len(_KY_CONTRIBUTION_ELECTION_DATES)

    # Each contribution job key should contain a date
    for job in contribution_jobs:
        assert "contributions-" in job.key
        # Key should contain the election date with slashes replaced by dashes
        assert any(ed.replace("/", "-") in job.key for ed, _ in _KY_CONTRIBUTION_ELECTION_DATES)


def test_ky_contribution_jobs_have_total_of_8_jobs() -> None:
    """7 election dates + 1 expenditure = 8 total jobs."""
    config = _fake_config()
    now = datetime(2026, 4, 13, tzinfo=timezone.utc)
    jobs = _build_ky_jobs(config, jurisdiction="state/KY", now=now)
    assert len(jobs) == 8  # 7 election dates + 1 expenditure
