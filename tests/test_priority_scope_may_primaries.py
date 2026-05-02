"""Verify that May-primary states appear in the priority refresh scope.

NE, LA, AL, KY, OR have daily/weekly cadence and must be included.
IN is annual and must be excluded.
"""

from __future__ import annotations

from pathlib import Path

from core.refresh.job_builders import _priority_source_names
from core.refresh.runner import RunnerParameters
from domains.campaign_finance.jurisdictions.config_schema import load_jurisdiction_config


REPO_ROOT = Path(__file__).resolve().parents[1]
_STATES_DIR = REPO_ROOT / "domains" / "campaign_finance" / "jurisdictions" / "states"


def _load_configs(*state_codes: str) -> dict[str, object]:
    configs = {}
    for code in state_codes:
        config_path = _STATES_DIR / code / "config.yaml"
        if config_path.exists():
            configs[code] = load_jurisdiction_config(config_path)
    return configs


def test_may_primary_states_in_priority_scope() -> None:
    """NE, LA, AL, KY, OR must appear in priority source names."""
    configs = _load_configs("NE", "LA", "AL", "KY", "OR", "CA", "CO", "GA", "TX")
    priority_names = _priority_source_names(configs, parameters=RunnerParameters())

    for state_code in ("NE", "LA", "AL", "KY", "OR"):
        config = configs[state_code]
        state_source_names = {ds.name for ds in config.data_sources}
        in_priority = state_source_names & priority_names
        assert in_priority, (
            f"{state_code} has no data sources in priority scope. "
            f"Sources: {state_source_names}, Priority: {priority_names}"
        )


def test_indiana_excluded_from_priority_scope() -> None:
    """IN is annual cadence — must NOT appear in priority source names."""
    configs = _load_configs("IN", "CA", "CO", "GA", "TX")
    priority_names = _priority_source_names(configs, parameters=RunnerParameters())

    in_config = configs["IN"]
    in_source_names = {ds.name for ds in in_config.data_sources}
    in_priority = in_source_names & priority_names
    assert not in_priority, f"IN should be excluded from priority scope (annual cadence) but found: {in_priority}"


def test_original_states_still_in_priority_scope() -> None:
    """CA, CO, GA, TX must remain in priority scope after expansion."""
    configs = _load_configs("CA", "CO", "GA", "TX")
    priority_names = _priority_source_names(configs, parameters=RunnerParameters())

    for state_code in ("CA", "CO", "GA", "TX"):
        config = configs[state_code]
        state_source_names = {ds.name for ds in config.data_sources}
        in_priority = state_source_names & priority_names
        assert in_priority, f"{state_code} should remain in priority scope but has no matching sources"
