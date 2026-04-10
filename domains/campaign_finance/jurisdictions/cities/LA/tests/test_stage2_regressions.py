from __future__ import annotations

from pathlib import Path

from domains.campaign_finance.jurisdictions._test_helpers import assert_files_exist, read
from domains.campaign_finance.jurisdictions.config_schema import load_jurisdiction_config

REPO_ROOT = Path(__file__).resolve().parents[6]
LA_DIR = REPO_ROOT / "domains" / "campaign_finance" / "jurisdictions" / "cities" / "LA"
CONFIG_PATH = LA_DIR / "config.yaml"
README_PATH = LA_DIR / "README.md"
LAWS_PATH = LA_DIR / "laws.md"
SEMANTICS_PATH = LA_DIR / "data_semantics.md"
SCRAPER_INIT_PATH = LA_DIR / "scraper" / "__init__.py"


def _la_transaction_field_mappings() -> tuple[tuple[str, str], ...]:
    config = load_jurisdiction_config(CONFIG_PATH)
    transaction_source = next(
        source for source in config.data_sources if source.name == "LA Ethics Campaign Contributions"
    )
    return tuple(transaction_source.field_mappings.items())


def test_stage2_la_files_exist() -> None:
    assert_files_exist(CONFIG_PATH, README_PATH, LAWS_PATH, SEMANTICS_PATH, SCRAPER_INIT_PATH)


def test_data_semantics_defines_each_transaction_column_mapping() -> None:
    semantics_text = read(SEMANTICS_PATH)
    mappings = _la_transaction_field_mappings()

    assert len(mappings) >= 30
    missing_rows = [
        source_column
        for source_column, semantic_path in mappings
        if f"| `{source_column}` | `{semantic_path}` |" not in semantics_text
    ]

    assert not missing_rows, f"missing column definition rows for: {missing_rows}"
