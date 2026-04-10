from __future__ import annotations

from pathlib import Path

from domains.campaign_finance.jurisdictions._test_helpers import read

REPO_ROOT = Path(__file__).resolve().parents[6]
OH_DIR = REPO_ROOT / "domains" / "campaign_finance" / "jurisdictions" / "states" / "OH"
CONFIG_PATH = OH_DIR / "config.yaml"
LAWS_PATH = OH_DIR / "laws.md"


def test_config_restricted_fund_note_uses_10000_not_stale_adjusted_amount() -> None:
    config_text = read(CONFIG_PATH)

    assert "$13,669" not in config_text
    assert "$10,000 per calendar year to a state political party restricted fund" in config_text


def test_laws_markdown_restricted_fund_note_matches_config_authority() -> None:
    laws_text = read(LAWS_PATH)

    assert "$13,669" not in laws_text
    assert "$10,000 per calendar year to a state political party restricted fund" in laws_text
    assert "ORC §3517.13 (contributions by corporations and labor organizations)" not in laws_text
