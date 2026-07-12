from __future__ import annotations

import re
from pathlib import Path

from _test_helpers import (
    assert_ascii_crlf_without_bom,
    assert_files_exist,
    csv_headers,
    extract_named_block,
    extract_source_blocks,
    nested_keys,
    read,
    scalar_value,
    source_block_by_name,
)

REPO_ROOT = Path(__file__).resolve().parents[6]
GA_DIR = REPO_ROOT / "domains" / "campaign_finance" / "jurisdictions" / "states" / "GA"
CONFIG_PATH = GA_DIR / "config.yaml"
README_PATH = GA_DIR / "README.md"
LAWS_PATH = GA_DIR / "laws.md"
SEMANTICS_PATH = GA_DIR / "data_semantics.md"
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
CONTRIBUTION_FIXTURE = FIXTURE_DIR / "contribution_export_sample.xls"
EXPENDITURE_FIXTURE = FIXTURE_DIR / "expenditure_export_sample.xls"


def expenditure_headers() -> list[str]:
    fixture_text = read(EXPENDITURE_FIXTURE)
    first_row_match = re.search(r"<tr[^>]*>(.*?)</tr>", fixture_text, re.DOTALL | re.IGNORECASE)
    if first_row_match is None:
        raise AssertionError("expected HTML row in expenditure fixture")
    return re.findall(r"<td[^>]*>([^<]+)</td>", first_row_match.group(1), re.IGNORECASE)


def laws_notes_block() -> str:
    return extract_named_block(extract_named_block(read(CONFIG_PATH), "laws"), "notes")


def test_stage5_ga_files_exist():
    assert_files_exist(
        CONFIG_PATH,
        README_PATH,
        LAWS_PATH,
        SEMANTICS_PATH,
        CONTRIBUTION_FIXTURE,
        EXPENDITURE_FIXTURE,
    )


def test_data_sources_are_web_portal_only_and_bulk_api_are_explicit_null():
    config_text = read(CONFIG_PATH)
    assert len(extract_source_blocks(config_text)) == 3
    assert config_text.count('format: "web_portal"') == 3
    assert config_text.count("bulk_download_url: null") == 3
    assert config_text.count("api_base_url: null") == 3
    assert config_text.count("auth_required: false") == 3


def test_contribution_field_mappings_match_downloaded_export_headers():
    config_text = read(CONFIG_PATH)
    source_block = source_block_by_name(config_text, "Georgia Campaign Portal — Contributions Search Export")
    assert nested_keys(source_block, "field_mappings") == csv_headers(CONTRIBUTION_FIXTURE)


def test_expenditure_field_mappings_match_downloaded_export_headers():
    config_text = read(CONFIG_PATH)
    source_block = source_block_by_name(config_text, "Georgia Campaign Portal — Expenditures Search Export")
    assert nested_keys(source_block, "field_mappings") == expenditure_headers()


def test_known_issues_document_stateful_export_workflow_and_scrape_only_constraints():
    config_text = read(CONFIG_PATH)
    assert "ASP.NET_SessionId" in config_text
    assert "__VIEWSTATE" in config_text
    assert "__EVENTVALIDATION" in config_text
    assert "returns full matching result sets, not only the visible page" in config_text
    assert "No official bulk download, API, or machine-readable feed was found" in config_text


def test_coverage_regression_uses_observed_year_floor_and_sub_jurisdiction_presence():
    config_text = read(CONFIG_PATH)
    assert config_text.count("start_year: 2000") == 3
    assert config_text.count("covers_sub_jurisdictions: true") == 3
    assert "county" in config_text
    assert "municipal" in config_text


def test_laws_block_has_required_stage5_values():
    config_text = read(CONFIG_PATH)
    assert 'source_url: "https://media.ethics.ga.gov/Commission/pdf/EthicsInGovernmentAct.pdf"' in config_text
    assert "individual_to_candidate: 8400" in config_text
    assert "pac_to_candidate: 8400" in config_text
    assert "corporate_direct: 8400" in config_text
    assert "union_direct: 8400" in config_text
    assert "party_to_candidate: 8400" in config_text
    assert "itemization_threshold: 100" in config_text
    assert 'electronic_filing_required: "required"' in config_text
    assert "public_financing: false" in config_text


def test_laws_doc_cites_statute_commission_limit_notice_and_reporting_schedule():
    laws_text = read(LAWS_PATH)
    assert "https://media.ethics.ga.gov/Commission/pdf/EthicsInGovernmentAct.pdf" in laws_text
    assert "https://ethics.ga.gov/contribution-limits/" in laws_text
    assert "https://ethics.ga.gov/filing-schedule/" in laws_text


def test_data_semantics_documents_export_formats_and_playwright_navigation():
    semantics_text = read(SEMANTICS_PATH)
    assert "StateEthicsReport.csv" in semantics_text
    assert "EthicsReportExport.xls" in semantics_text
    assert "CSV payload with .xls extension in local save paths" in semantics_text
    assert "HTML table payload with .xls attachment metadata" in semantics_text
    assert "page-size table renders 10 rows per page" in semantics_text
    assert "export returns full result set across all pages" in semantics_text
    assert "Playwright" in semantics_text
    assert "single browser context" in semantics_text


def test_readme_documents_verification_date_and_recheck_instructions():
    config_text = read(CONFIG_PATH)
    readme_text = read(README_PATH)
    primary_source_blocks = [
        block for block in extract_source_blocks(config_text) if "Independent Expenditures Search Export" not in block
    ]
    source_verified_values = {
        scalar_value(source_block, "last_verified_working") for source_block in primary_source_blocks
    }
    assert source_verified_values == {"2026-03-26"}
    source_verified = "2026-03-26"
    laws_verified = scalar_value(extract_named_block(config_text, "laws"), "last_verified")

    assert f"Source access and portal workflow verified: {source_verified}" in readme_text
    assert "Independent expenditures surface re-check: 2026-04-29" in readme_text
    assert "HTTP 404" in readme_text
    assert f"Laws research verified: {laws_verified}" in readme_text
    assert "Re-verify by running a one-page contribution search" in readme_text


def test_portal_surface_inventory_documents_all_search_surfaces():
    semantics_text = read(SEMANTICS_PATH)
    expected_surface_rows = [
        "| Search by Contribution | `Campaign_ByContributions.aspx` | Yes (CSV) | Yes |",
        "| Search by Expenditure | `Campaign_ByExpenditures.aspx` | Yes (HTML-table .xls) | Yes |",
        "| View Campaign Report Log | `Campaign_ReportLog.aspx` | No export observed | No |",
        "| Search by Name | `Campaign_ByName.aspx` | No export observed | No |",
        "| Search by Office | `Campaign_ByOffice.aspx` | No export observed | No |",
    ]
    for expected_row in expected_surface_rows:
        assert expected_row in semantics_text
    assert "Only the contribution and expenditure surfaces provide data-export functionality." in semantics_text


def test_export_encoding_and_metadata_rows_documented():
    semantics_text = read(SEMANTICS_PATH)
    assert_ascii_crlf_without_bom(CONTRIBUTION_FIXTURE)
    assert_ascii_crlf_without_bom(EXPENDITURE_FIXTURE)
    assert (
        "Contribution CSV export (`StateEthicsReport.csv`) is ASCII-compatible text with CRLF "
        "line terminators; no BOM or explicit charset header is sent. Parse as UTF-8 "
        "(ASCII superset)."
    ) in semantics_text
    assert (
        "Expenditure export (`EthicsReportExport.xls`) is ASCII-compatible HTML with CRLF "
        "line terminators; no encoding declaration beyond standard ASCII. Parse as UTF-8."
    ) in semantics_text
    assert (
        "Neither export file contains portal-added metadata rows (no title row, no trailing "
        "summary row, no report-generation timestamp row)."
    ) in semantics_text


def test_laws_notes_carry_ambiguity_items():
    notes_text = laws_notes_block()
    assert "21-5-41(k)" in notes_text
    assert "CPI-driven updates" in notes_text
    assert "SB 199 implementation context" in notes_text


def test_reporting_periods_mapping_documented_in_notes():
    notes_text = laws_notes_block()
    assert "Reporting periods are mapped to quarterly + pre-election" in notes_text
    assert "four roughly quarterly CCDR windows" in notes_text
    assert "21-5-34(c)(2)" in notes_text


def test_readme_coverage_includes_loans():
    readme_text = read(README_PATH)
    assert (
        "Transaction coverage includes contributions, loans (via the contribution search "
        "export `Type` field), and expenditures in this stage"
    ) in readme_text


def test_amendment_indicator_hardcoded_n_documented_in_semantics_and_readme():
    semantics_text = read(SEMANTICS_PATH)
    readme_text = read(README_PATH)

    # data_semantics.md must explicitly state the loader hardcodes "N"
    assert "amendment_indicator='N'" in semantics_text
    assert "unconditionally sets" in semantics_text

    # README must mention the amendment_indicator limitation
    assert "amendment_indicator" in readme_text
