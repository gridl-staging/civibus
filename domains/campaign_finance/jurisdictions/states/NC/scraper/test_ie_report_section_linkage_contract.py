from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest

from domains.campaign_finance.jurisdictions.states.NC.scraper.parse import parse_committee_docs


def _repo_root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "pyproject.toml").exists():
            return candidate
    raise RuntimeError("Could not locate repo root from test path")


ARTIFACT_ROOT = _repo_root() / "docs" / "research" / "artifacts" / "2026_04_24_nc_ie_amounts" / "local"
DOCUMENT_RESULT_HTML = ARTIFACT_ROOT / "local_document_result_page.html"
REPORT_SECTION_HTML = ARTIFACT_ROOT / "local_report_section_sample.html"
REPORT_DETAIL_HTML = ARTIFACT_ROOT / "local_report_detail_ie_rows_sample.html"
CSV_SAMPLE = ARTIFACT_ROOT / "local_document_result_export.csv"
EXTRACTED_LINKS_JSON = ARTIFACT_ROOT / "extracted_report_section_links.json"

PROBE_PATH = _repo_root() / "docs" / "research" / "artifacts" / "2026_04_24_nc_ie_amounts" / "probe.py"


def _load_probe_module():
    spec = importlib.util.spec_from_file_location("nc_ie_probe_2026_04_24", PROBE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load probe module from {PROBE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.skipif(
    importlib.util.find_spec("playwright") is None,
    reason="NC state acquisition is parked under federal-first v1; playwright belongs to the download extra.",
)
def test_nc_ie_report_section_linkage_contract_from_fixtures() -> None:
    assert DOCUMENT_RESULT_HTML.exists(), f"Missing fixture: {DOCUMENT_RESULT_HTML}"
    assert REPORT_SECTION_HTML.exists(), f"Missing fixture: {REPORT_SECTION_HTML}"
    assert REPORT_DETAIL_HTML.exists(), f"Missing fixture: {REPORT_DETAIL_HTML}"
    assert CSV_SAMPLE.exists(), f"Missing fixture: {CSV_SAMPLE}"
    assert EXTRACTED_LINKS_JSON.exists(), f"Missing fixture: {EXTRACTED_LINKS_JSON}"

    document_result_html = DOCUMENT_RESULT_HTML.read_text(encoding="utf-8")
    report_section_html = REPORT_SECTION_HTML.read_text(encoding="utf-8")
    report_detail_html = REPORT_DETAIL_HTML.read_text(encoding="utf-8")

    # Guard against fixture drift: these are the pages Stage 1 contract depends on.
    assert "gridDocumentResults" in document_result_html
    assert "/CFOrgLkup/ReportSection/" in document_result_html
    assert "Choose one of the following Report Sections" in report_section_html
    assert "Detailed Expenditures" in report_section_html
    assert "Amount of Expenditure" in report_detail_html

    extracted_links_payload = json.loads(EXTRACTED_LINKS_JSON.read_text(encoding="utf-8"))
    extracted_rows = extracted_links_payload["rows"]
    csv_rows = [
        {column: ("" if value is None else value) for column, value in row.items()}
        for row in parse_committee_docs(CSV_SAMPLE)
    ]

    assert len(extracted_rows) == len(csv_rows)
    assert extracted_links_payload["href_extraction_rule"].startswith("For each DocumentResult table row")

    probe_module = _load_probe_module()
    linkage = probe_module.evaluate_csv_to_report_section_linkage(
        csv_rows=csv_rows,
        extracted_rows=extracted_rows,
    )

    assert linkage["row_count_matches"] is True
    assert linkage["csv_row_count"] == len(csv_rows)
    assert linkage["extracted_row_count"] == len(extracted_rows)
    assert linkage["outcome"] in {"bijection", "ambiguous"}

    if linkage["outcome"] == "ambiguous":
        assert linkage["fallback_required"] is True, (
            "Ambiguity detected but fallback is missing: Stage 2 must preserve per-row DATA href at index-load time."
        )
        assert linkage["fallback_requirement"] == "preserve_per_row_data_href_at_index_load_time"
    else:
        assert linkage["fallback_required"] is False
        assert linkage["fallback_requirement"] == "none"
