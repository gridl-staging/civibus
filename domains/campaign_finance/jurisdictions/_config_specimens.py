"""Checked-in jurisdiction-config specimen paths shared by the config test modules.

The loader contract is exercised by three test modules — ``test_config_schema.py`` for
the whole-config reader discipline, ``test_contribution_limit_rules.py`` for the
structured ``laws.contribution_limit_rules`` contract, and
``test_contribution_limit_rule_seed_configs.py`` for what the checked-in seed configs
themselves must contain. The first two seed their temporary fixtures from the same
checked-in configs and the third reads them directly, so the specimen locations live
here rather than being duplicated, or imported from one pytest module into another.
"""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
JURISDICTIONS_DIR = REPO_ROOT / "domains" / "campaign_finance" / "jurisdictions"
TEMPLATE_CONFIG_PATH = JURISDICTIONS_DIR / "_template" / "config.yaml"
LA_CONFIG_PATH = JURISDICTIONS_DIR / "cities" / "LA" / "config.yaml"
NYC_CONFIG_PATH = JURISDICTIONS_DIR / "cities" / "NYC" / "config.yaml"
PHL_CONFIG_PATH = JURISDICTIONS_DIR / "cities" / "PHL" / "config.yaml"
SF_CONFIG_PATH = JURISDICTIONS_DIR / "cities" / "SF" / "config.yaml"
CA_CONFIG_PATH = JURISDICTIONS_DIR / "states" / "CA" / "config.yaml"
CO_CONFIG_PATH = JURISDICTIONS_DIR / "states" / "CO" / "config.yaml"
GA_CONFIG_PATH = JURISDICTIONS_DIR / "states" / "GA" / "config.yaml"
NC_CONFIG_PATH = JURISDICTIONS_DIR / "states" / "NC" / "config.yaml"
PILOT_CONFIG_PATHS = [
    CO_CONFIG_PATH,
    GA_CONFIG_PATH,
    NC_CONFIG_PATH,
]
EXPANDED_CONFIG_PATHS = [JURISDICTIONS_DIR / "cities" / code / "config.yaml" for code in ("LA", "NYC", "PHL", "SF")] + [
    JURISDICTIONS_DIR / "states" / code / "config.yaml"
    for code in (
        "AL",
        "CA",
        "CO",
        "FL",
        "GA",
        "IL",
        "IN",
        "KY",
        "LA",
        "MA",
        "MN",
        "NC",
        "NE",
        "NJ",
        "NY",
        "OH",
        "OR",
        "PA",
        "TX",
        "VA",
        "WA",
        "WI",
    )
]
EXPANDED_CONFIG_IDS = [f"{path.parent.parent.name}-{path.parent.name}" for path in EXPANDED_CONFIG_PATHS]
DIRECTORY_JURISDICTION_TYPES = {"cities": "municipality", "states": "state"}
