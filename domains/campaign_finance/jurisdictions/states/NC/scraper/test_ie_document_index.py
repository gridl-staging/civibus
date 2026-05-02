from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlparse

from domains.campaign_finance.jurisdictions.states.NC.scraper.parse import parse_committee_docs

_IE_DOCUMENT_INDEX_FIXTURE = (
    Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "cfdoclkup_ie_document_index_sample_2026_04_18.csv"
)
_STAGE1_LINKAGE_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "tests"
    / "fixtures"
    / "cfdoclkup_ie_document_index_stage1_linkage_sample_2026_04_24.csv"
)
_EXPECTED_IE_COMMITTEE_NAMES = [
    "GUILFORD-ROCKINGHAM ALLIANCE",
    "NCAAT IN ACTION",
    "AMERICAN CONSERVATIVE FUND",
]


# Fixture compatibility tests (expected GREEN): the IE CSV uses the existing
# 12-column committee-document schema and should parse as-is.
def test_parse_committee_docs_ie_fixture_matches_observed_values() -> None:
    rows = list(parse_committee_docs(_IE_DOCUMENT_INDEX_FIXTURE))

    assert len(rows) == 3
    assert [row["Doc Name"] for row in rows] == [
        "Independent Expenditure Report",
        "Independent Expenditure Report",
        "Independent Expenditure Report",
    ]
    assert [row["Committee Name"] for row in rows] == _EXPECTED_IE_COMMITTEE_NAMES
    assert [row["SBoE ID"] for row in rows] == ["No Id", "No Id", "No Id"]
    assert [row["Year"] for row in rows] == ["2026", "2026", "2026"]
    assert [row["Amend"] for row in rows] == ["Y", "N", "N"]


def test_stage1_linkage_fixture_proves_url_present_and_url_absent_rows_for_raw_fields_contract() -> None:
    rows = list(parse_committee_docs(_STAGE1_LINKAGE_FIXTURE))
    assert len(rows) == 2
    assert rows[0]["Committee Name"] == "GUILFORD-ROCKINGHAM ALLIANCE"
    assert rows[0]["Data"] == "DATA"
    assert rows[1]["Committee Name"] == "CONSERVATION VOTES PAC"
    assert rows[1]["Data"] is None


def test_build_nc_committee_doc_linkage_key_contract_uses_parse_owner_columns() -> None:
    from domains.campaign_finance.jurisdictions.states.NC.scraper.parse import (
        COMMITTEE_DOC_COLUMNS,
        build_nc_committee_doc_linkage_key,
    )

    rows = list(parse_committee_docs(_STAGE1_LINKAGE_FIXTURE))
    with_data_key = build_nc_committee_doc_linkage_key(rows[0])
    without_data_key = build_nc_committee_doc_linkage_key(rows[1])

    # The linkage key intentionally excludes "Doc Type" — see
    # _LINKAGE_KEY_COLUMNS in parse.py for why. So the key length is
    # COMMITTEE_DOC_COLUMNS minus 1.
    assert len(with_data_key) == len(COMMITTEE_DOC_COLUMNS) - 1
    assert len(without_data_key) == len(COMMITTEE_DOC_COLUMNS) - 1
    assert with_data_key != without_data_key


def test_linkage_key_excludes_doc_type_for_cross_endpoint_robustness() -> None:
    """The CFDocLkup CSV reports the real Doc Type per filing (Disclosure
    Report or Informational Report); the CFDocLkup/DocumentResult HTML
    grid does NOT carry a Doc Type column at all (it's hardcoded to
    "Disclosure Report" in _build_document_result_row_for_linkage_key).

    Including "Doc Type" in the linkage key therefore drops every CSV row
    whose Doc Type is "Informational Report" — a real loss observed live
    2026-04-25 (6 of 47 IE candidates were silently un-URL'd, including
    ADVANCE NORTH CAROLINA and AMERICAN CONSERVATIVE FUND).

    Two rows that differ ONLY in Doc Type must produce the same linkage
    key so the URL queue match still works across the two NC SBoE
    endpoints.
    """
    from domains.campaign_finance.jurisdictions.states.NC.scraper.parse import (
        build_nc_committee_doc_linkage_key,
    )

    csv_row_disclosure = {
        "Committee Name": "ADVANCE NORTH CAROLINA",
        "SBoE ID": "No Id",
        "Year": "2026",
        "Doc Type": "Disclosure Report",
        "Doc Name": "Independent Expenditure Report",
        "Amend": "N",
        "Received Image": "",
        "Received Data": "02/24/2026",
        "Start Date": "02/15/2026",
        "End Date": "02/24/2026",
        "Image": "",
        "Data": "DATA",
    }
    csv_row_informational = dict(csv_row_disclosure)
    csv_row_informational["Doc Type"] = "Informational Report"

    key_disclosure = build_nc_committee_doc_linkage_key(csv_row_disclosure)
    key_informational = build_nc_committee_doc_linkage_key(csv_row_informational)

    assert key_disclosure == key_informational, (
        "Linkage key must be Doc-Type-independent so the DocumentResult URL "
        "queue (which hardcodes 'Disclosure Report') matches CSV rows whose "
        "Doc Type is 'Informational Report'."
    )


# IE contract red tests (expected RED): these imports fail until Stage 3
# adds IE-specific parser/download contract helpers.
def test_classify_ie_filing_contract_true_for_ie_doc_name() -> None:
    from domains.campaign_finance.jurisdictions.states.NC.scraper.parse import classify_ie_filing

    row = list(parse_committee_docs(_IE_DOCUMENT_INDEX_FIXTURE))[0]
    assert classify_ie_filing(row) is True


def test_classify_ie_filing_contract_false_for_regular_committee_doc_names() -> None:
    from domains.campaign_finance.jurisdictions.states.NC.scraper.parse import classify_ie_filing

    assert classify_ie_filing({"Doc Name": "Year End Semi-Annual"}) is False
    assert classify_ie_filing({"Doc Name": "Mid Year Semi-Annual"}) is False


def test_ie_report_codes_and_export_url_contract() -> None:
    from domains.campaign_finance.jurisdictions.states.NC.scraper.download import (
        IE_REPORT_CODES,
        build_ie_export_url,
    )

    assert IE_REPORT_CODES == frozenset({"IRIEX", "IRCIX", "RPIER"})

    url = build_ie_export_url(2026)
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    reports_param = query["reports"][0]
    quoted_codes = [code.strip().strip("'") for code in reports_param.split(",")]

    assert parsed.scheme == "https"
    assert parsed.netloc == "cf.ncsbe.gov"
    assert parsed.path == "/CFDocLkup/ExportSearchResults/"
    assert query["year"] == ["2026"]
    assert reports_param == "'IRIEX', 'IRCIX', 'RPIER'"
    assert len(quoted_codes) == 3
    assert set(quoted_codes) == IE_REPORT_CODES


def test_is_within_ie_year_window_contract() -> None:
    from domains.campaign_finance.jurisdictions.states.NC.scraper.parse import is_within_ie_year_window

    row = list(parse_committee_docs(_IE_DOCUMENT_INDEX_FIXTURE))[0]
    assert is_within_ie_year_window({**row, "Year": "2020"}, current_year=2026) is False
    assert is_within_ie_year_window({**row, "Year": "2022"}, current_year=2026) is True
    assert is_within_ie_year_window({**row, "Year": "2023"}, current_year=2026) is True
    assert is_within_ie_year_window({**row, "Year": "2024"}, current_year=2026) is True
    assert is_within_ie_year_window({**row, "Year": "2025"}, current_year=2026) is True
    assert is_within_ie_year_window({**row, "Year": "2026"}, current_year=2026) is True


def test_build_ie_document_index_data_source_uses_config_identity_contract() -> None:
    from domains.campaign_finance.jurisdictions.config_schema import load_jurisdiction_config
    from domains.campaign_finance.jurisdictions.states.NC.scraper import _CONFIG_PATH as _NC_CONFIG_PATH
    from domains.campaign_finance.jurisdictions.states.NC.scraper.load_support import (
        build_ie_document_index_data_source,
    )

    config = load_jurisdiction_config(_NC_CONFIG_PATH)
    ie_sources = [
        source for source in config.data_sources if "independent_expenditures" in source.coverage.transaction_types
    ]
    assert len(ie_sources) == 1

    data_source = build_ie_document_index_data_source()
    assert data_source.domain == "campaign_finance"
    assert data_source.jurisdiction == "state/NC"
    assert data_source.name == ie_sources[0].name
    assert data_source.source_url == ie_sources[0].url
    assert data_source.source_format == "csv"
