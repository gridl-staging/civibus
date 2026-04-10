"""Stage 4 regression tests for California (CA) campaign finance pipeline.

Supersedes the former test_stage2_regressions.py — all structural and config
consistency assertions live here, matching the TX/WA pattern where Stage 4
is the single regression surface per state.
"""

from __future__ import annotations

from pathlib import Path

from domains.campaign_finance.jurisdictions._test_helpers import (
    assert_files_exist,
    extract_named_block,
    read,
    scalar_value,
    shared_data_source_scalar,
)
from domains.campaign_finance.jurisdictions.states.CA.scraper import (
    INGESTION_TABLE_NAMES,
    _load_columns_for_table,
)

REPO_ROOT = Path(__file__).resolve().parents[6]
CA_DIR = REPO_ROOT / "domains" / "campaign_finance" / "jurisdictions" / "states" / "CA"
CONFIG_PATH = CA_DIR / "config.yaml"
README_PATH = CA_DIR / "README.md"
LAWS_PATH = CA_DIR / "laws.md"
SEMANTICS_PATH = CA_DIR / "data_semantics.md"
_FIXTURE_DIR = CA_DIR / "scraper" / "test_fixtures" / "sample_archive"
_SCRAPER_DIR = CA_DIR / "scraper"

# Mapping from CA table name prefix to the transaction type it represents.
# RCPT_CD = contributions, EXPN_CD = expenditures, LOAN_CD = loans.
# CVR_CAMPAIGN_DISCLOSURE_CD, FILERNAME_CD, FILERS_CD are metadata tables
# that support all three transaction types (no single-type mapping).
_TABLE_TO_TRANSACTION_TYPE = {
    "RCPT_CD": "contributions",
    "EXPN_CD": "expenditures",
    "LOAN_CD": "loans",
}


def test_stage4_files_exist() -> None:
    """Assert existence of config, docs, and all 6 fixture TSVs."""
    fixture_paths = [_FIXTURE_DIR / f"{table_name}.TSV" for table_name in INGESTION_TABLE_NAMES]
    assert_files_exist(
        CONFIG_PATH,
        README_PATH,
        LAWS_PATH,
        SEMANTICS_PATH,
        *fixture_paths,
    )


def test_required_stage4_scraper_files_exist() -> None:
    """Assert existence of all scraper implementation and test files."""
    implementation_files = [
        _SCRAPER_DIR / "__init__.py",
        _SCRAPER_DIR / "download.py",
        _SCRAPER_DIR / "parse.py",
        _SCRAPER_DIR / "extract.py",
        _SCRAPER_DIR / "load.py",
        _SCRAPER_DIR / "cli.py",
    ]
    test_files = [
        _SCRAPER_DIR / "test_download.py",
        _SCRAPER_DIR / "test_parse.py",
        _SCRAPER_DIR / "test_extract.py",
        _SCRAPER_DIR / "test_load.py",
        _SCRAPER_DIR / "test_cli.py",
        _SCRAPER_DIR / "test_init.py",
    ]
    assert_files_exist(*implementation_files, *test_files)


def test_sample_archive_fixture_headers_match_config_order() -> None:
    """Per-table field-order validation for all 6 locked CA ingestion tables.

    Moved from test_stage2_regressions.py — must exist in exactly one file.
    """
    for table_name in INGESTION_TABLE_NAMES:
        fixture_path = _FIXTURE_DIR / f"{table_name}.TSV"
        header = fixture_path.read_text(encoding="utf-8").splitlines()[0].split("\t")
        assert tuple(header) == _load_columns_for_table(table_name)


def test_readme_documents_current_source_and_laws_verification_dates() -> None:
    """Date-consistency check moved from test_stage2_regressions.py."""
    config_text = read(CONFIG_PATH)
    readme_text = read(README_PATH)
    source_verified = shared_data_source_scalar(config_text, "last_verified_working")
    laws_verified = scalar_value(extract_named_block(config_text, "laws"), "last_verified")

    assert f"- Source access and archive URL reachability: {source_verified}." in readme_text
    assert f"- Laws references: {laws_verified}." in readme_text


def test_config_coverage_transaction_types_match_ingestion_scope() -> None:
    """Assert config.yaml coverage.transaction_types is consistent with INGESTION_TABLE_NAMES.

    The three transaction-bearing tables (RCPT_CD, EXPN_CD, LOAN_CD) must each map
    to a declared transaction type, and vice versa.
    """
    config_text = read(CONFIG_PATH)
    coverage_block = extract_named_block(config_text, "coverage")
    transaction_types_block = extract_named_block(coverage_block, "transaction_types")

    # Parse the YAML list items from the transaction_types block
    declared_types = set()
    for line in transaction_types_block.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            declared_types.add(stripped[2:].strip())

    # Derive expected types from ingestion tables that map to a transaction type
    expected_types = {
        _TABLE_TO_TRANSACTION_TYPE[table] for table in INGESTION_TABLE_NAMES if table in _TABLE_TO_TRANSACTION_TYPE
    }

    assert declared_types == expected_types, (
        f"config.yaml transaction_types {sorted(declared_types)} does not match "
        f"ingestion scope {sorted(expected_types)}"
    )
