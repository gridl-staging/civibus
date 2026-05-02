from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from domains.campaign_finance.jurisdictions.states.NC.scraper.parse_ie_report_section import (
    NCIEReportRow,
    parse_ie_report_section_html,
)

_FIXTURES_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
_KNOWN_ANSWER_HTML_FIXTURE = _FIXTURES_DIR / "nc_ie_report_section_known_answer.html"
_NON_IE_HTML_FIXTURE = _FIXTURES_DIR / "nc_ie_report_section_non_ie.html"
_KNOWN_ANSWER_TOTAL = Decimal("15000.0000")


def test_parse_html_extracts_expected_row_count_and_type() -> None:
    rows = parse_ie_report_section_html(
        _KNOWN_ANSWER_HTML_FIXTURE.read_text(encoding="utf-8"),
        spender_committee_name="ADVANCE NORTH CAROLINA",
        source_filing_url="https://cf.ncsbe.gov/CFOrgLkup/ReportSection/?RID=229253",
    )

    assert len(rows) == 3
    assert all(isinstance(row, NCIEReportRow) for row in rows)


def test_parse_html_sum_matches_hand_calculated_total_to_the_cent() -> None:
    rows = parse_ie_report_section_html(
        _KNOWN_ANSWER_HTML_FIXTURE.read_text(encoding="utf-8"),
        spender_committee_name="ADVANCE NORTH CAROLINA",
        source_filing_url="https://cf.ncsbe.gov/CFOrgLkup/ReportSection/?RID=229253",
    )

    assert sum(row.amount for row in rows) == _KNOWN_ANSWER_TOTAL


def test_parse_html_preserves_support_or_oppose_raw_before_loader_normalization() -> None:
    rows = parse_ie_report_section_html(
        _KNOWN_ANSWER_HTML_FIXTURE.read_text(encoding="utf-8"),
        spender_committee_name="ADVANCE NORTH CAROLINA",
        source_filing_url="https://cf.ncsbe.gov/CFOrgLkup/ReportSection/?RID=229253",
    )

    assert {row.support_or_oppose_raw for row in rows} == {"Support"}


def test_parse_html_non_ie_report_section_like_markup_returns_empty_list() -> None:
    rows = parse_ie_report_section_html(
        _NON_IE_HTML_FIXTURE.read_text(encoding="utf-8"),
        spender_committee_name="ADVANCE NORTH CAROLINA",
        source_filing_url="https://cf.ncsbe.gov/CFOrgLkup/ReportSection/?RID=229253",
    )

    assert rows == []
