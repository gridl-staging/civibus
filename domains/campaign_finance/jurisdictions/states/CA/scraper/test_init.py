from __future__ import annotations

from pathlib import Path

import pytest

from _test_helpers import nested_keys, read, source_block_by_name
from domains.campaign_finance.jurisdictions.states.CA.scraper import (
    INGESTION_MEMBERS,
    INGESTION_TABLE_NAMES,
    _get_raw_data_source,
    _load_ca_config,
    _load_ca_data_source_blocks,
    _load_columns_for_table,
)

REPO_ROOT = Path(__file__).resolve().parents[6]
CA_DIR = REPO_ROOT / "domains" / "campaign_finance" / "jurisdictions" / "states" / "CA"
CONFIG_PATH = CA_DIR / "config.yaml"
_RAW_DATA_SOURCE_NAME = "CAL-ACCESS Raw Data Export"


def _expected_ingestion_tables_from_config() -> tuple[str, ...]:
    config_text = read(CONFIG_PATH)
    raw_source_block = source_block_by_name(config_text, _RAW_DATA_SOURCE_NAME)
    field_mapping_keys = nested_keys(raw_source_block, "field_mappings")
    return tuple(dict.fromkeys(field_mapping.split(".", maxsplit=1)[0] for field_mapping in field_mapping_keys))


def test_config_loads_successfully():
    config = _load_ca_config()
    assert config.jurisdiction.code == "CA"
    assert config.jurisdiction.name == "California"
    assert config.jurisdiction.type == "state"
    assert config.jurisdiction.fips == "06"


def test_raw_data_source_block_exists():
    block = _get_raw_data_source()
    assert block.name == "CAL-ACCESS Raw Data Export"
    assert block.bulk_download_url == "https://campaignfinance.cdn.sos.ca.gov/dbwebexport.zip"
    assert "contributions" in block.transaction_types
    assert "expenditures" in block.transaction_types
    assert "loans" in block.transaction_types


def test_data_source_blocks_include_documentation_bundle():
    blocks = _load_ca_data_source_blocks()
    names = {b.name for b in blocks}
    assert "CAL-ACCESS Raw Data Export" in names
    assert "CAL-ACCESS Documentation Bundle" in names


def test_ingestion_members_are_locked_set():
    expected_members = tuple(f"CalAccess/DATA/{table}.TSV" for table in _expected_ingestion_tables_from_config())
    assert INGESTION_MEMBERS == expected_members
    assert len(INGESTION_MEMBERS) == 6


def test_ingestion_table_names_derived_from_members():
    expected_ordered_tables = _expected_ingestion_tables_from_config()
    assert INGESTION_TABLE_NAMES == expected_ordered_tables
    assert len(INGESTION_TABLE_NAMES) == 6


def test_columns_for_cvr_campaign_disclosure_derive_from_config():
    columns = _load_columns_for_table("CVR_CAMPAIGN_DISCLOSURE_CD")
    assert "FILER_ID" in columns
    assert "FILING_ID" in columns
    assert "AMEND_ID" in columns
    assert "RPT_DATE" in columns
    assert "OFFICE_CD" in columns
    assert "FORM_TYPE" in columns


def test_columns_for_rcpt_derive_from_config():
    columns = _load_columns_for_table("RCPT_CD")
    assert "FILING_ID" in columns
    assert "TRAN_ID" in columns
    assert "CTRIB_NAML" in columns
    assert "RCPT_DATE" in columns
    assert "AMOUNT" in columns
    assert "FORM_TYPE" in columns


def test_columns_for_expn_derive_from_config():
    columns = _load_columns_for_table("EXPN_CD")
    assert "FILING_ID" in columns
    assert "TRAN_ID" in columns
    assert "PAYEE_NAML" in columns
    assert "EXPN_DATE" in columns
    assert "AMOUNT" in columns
    assert "EXPN_CODE" in columns


def test_columns_for_loan_derive_from_config():
    columns = _load_columns_for_table("LOAN_CD")
    assert "FILING_ID" in columns
    assert "TRAN_ID" in columns
    assert "LNDR_NAML" in columns
    assert "LOAN_DATE1" in columns
    assert "LOAN_AMT1" in columns
    assert "LOAN_RATE" in columns


def test_columns_for_filername_derive_from_config():
    columns = _load_columns_for_table("FILERNAME_CD")
    assert "XREF_FILER_ID" in columns
    assert "NAML" in columns
    assert "FILER_TYPE" in columns
    # Live FILERNAME_CD uses ZIP4; ZIP was a stale config column that broke parsing.
    assert "ZIP4" in columns
    assert "ZIP" not in columns


def test_columns_for_filers_derive_from_config():
    # Live FILERS_CD.TSV contains only FILER_ID; config was updated to match.
    columns = _load_columns_for_table("FILERS_CD")
    assert columns == ("FILER_ID",)


def test_columns_for_unknown_table_raises():
    with pytest.raises(RuntimeError, match="No field mappings found"):
        _load_columns_for_table("NONEXISTENT_TABLE")


def test_coverage_start_year_from_config():
    config = _load_ca_config()
    raw_source = next(ds for ds in config.data_sources if ds.name == "CAL-ACCESS Raw Data Export")
    assert raw_source.coverage.start_year == 1999


def test_coverage_sub_jurisdictions_from_config():
    config = _load_ca_config()
    raw_source = next(ds for ds in config.data_sources if ds.name == "CAL-ACCESS Raw Data Export")
    assert raw_source.coverage.covers_sub_jurisdictions is True
