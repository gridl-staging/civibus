from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal, InvalidOperation
from io import StringIO

from bs4 import BeautifulSoup
from pydantic import BaseModel, ConfigDict

from domains.campaign_finance.ingest.text_utils import normalize_optional_text

_DETAIL_EXPORT_SECTION_HEADER = "EXPENDITURES"
_INDEPENDENT_EXPENDITURE_TYPE = "Independent Expenditure"
_REQUIRED_EXPORT_COLUMNS = (
    "Date",
    "Name",
    "City",
    "State",
    "Full Zip",
    "Purpose",
    "Candidate",
    "Office Sought",
    "Declaration",
    "Amount",
    "Expenditure Type Desc",
)


class NCIEReportParseError(ValueError):
    """Raised when an NC IE report-detail export does not match the verified contract."""


class NCIEReportRow(BaseModel):
    """Typed NC IE row parsed from the report-detail CSV export."""

    model_config = ConfigDict(extra="forbid")

    row_index: int
    spender_committee_name: str
    payee_name: str
    target_name: str | None = None
    target_office: str | None = None
    support_or_oppose_raw: str | None = None
    amount: Decimal
    transaction_date: date
    purpose: str | None = None
    payee_city: str | None = None
    payee_state: str | None = None
    payee_zip: str | None = None
    source_filing_url: str
    report_detail_url: str | None = None
    report_export_url: str | None = None


def _require_text(value: str | None, *, field_name: str) -> str:
    normalized_value = normalize_optional_text(value)
    if normalized_value is None:
        raise NCIEReportParseError(f"NC IE report row is missing required {field_name}")
    return normalized_value


def _parse_date(raw_value: str | None) -> date:
    normalized_value = _require_text(raw_value, field_name="Date")
    try:
        month, day, year = normalized_value.split("/")
        return date(int(year), int(month), int(day))
    except ValueError as exc:
        raise NCIEReportParseError(f"Invalid NC IE report date: {raw_value!r}") from exc


def _parse_amount(raw_value: str | None) -> Decimal:
    normalized_value = _require_text(raw_value, field_name="Amount")
    try:
        return Decimal(normalized_value)
    except InvalidOperation as exc:
        raise NCIEReportParseError(f"Invalid NC IE report amount: {raw_value!r}") from exc


def _build_report_row(
    raw_row: dict[str, str | None],
    *,
    row_index: int,
    spender_committee_name: str,
    source_filing_url: str,
    report_detail_url: str | None,
    report_export_url: str | None,
) -> NCIEReportRow:
    """Build one typed row from already-extracted raw field values.

    This seam intentionally does only parsing/typing cleanup. Candidate matching,
    support/oppose normalization, and persistence stay in loader code.
    """
    return NCIEReportRow(
        row_index=row_index,
        spender_committee_name=spender_committee_name,
        payee_name=_require_text(raw_row.get("Name"), field_name="Name"),
        target_name=normalize_optional_text(raw_row.get("Candidate")),
        target_office=normalize_optional_text(raw_row.get("Office Sought")),
        support_or_oppose_raw=normalize_optional_text(raw_row.get("Declaration")),
        amount=_parse_amount(raw_row.get("Amount")),
        transaction_date=_parse_date(raw_row.get("Date")),
        purpose=normalize_optional_text(raw_row.get("Purpose")),
        payee_city=normalize_optional_text(raw_row.get("City")),
        payee_state=normalize_optional_text(raw_row.get("State")),
        payee_zip=normalize_optional_text(raw_row.get("Full Zip")),
        source_filing_url=source_filing_url,
        report_detail_url=report_detail_url,
        report_export_url=report_export_url,
    )


def _normalize_header_rows(csv_text: str) -> str:
    # The export starts with a section label line before the real header row.
    stripped_lines = [line for line in csv_text.splitlines() if line.strip()]
    if not stripped_lines:
        raise NCIEReportParseError("NC IE report export is empty")
    if stripped_lines[0].strip().upper() != _DETAIL_EXPORT_SECTION_HEADER:
        raise NCIEReportParseError(
            "NC IE report export does not start with the EXPENDITURES section header"
        )
    if len(stripped_lines) < 2:
        raise NCIEReportParseError("NC IE report export is missing the CSV header row")
    return "\n".join(stripped_lines[1:])


def _validate_header(fieldnames: list[str] | None) -> tuple[str, ...]:
    observed_columns = tuple(fieldnames or ())
    missing_columns = [column for column in _REQUIRED_EXPORT_COLUMNS if column not in observed_columns]
    if missing_columns:
        raise NCIEReportParseError(
            "NC IE report export is missing required columns: "
            + ", ".join(missing_columns)
        )
    return observed_columns


def _extract_table_rows_from_html(html_text: str) -> list[dict[str, str | None]]:
    soup = BeautifulSoup(html_text, "html.parser")
    extracted_rows: list[dict[str, str | None]] = []

    for table in soup.find_all("table"):
        header_cells = table.select("thead tr th")
        if not header_cells:
            first_row = table.find("tr")
            header_cells = first_row.find_all("th") if first_row is not None else []
        if not header_cells:
            continue

        headers = [normalize_optional_text(cell.get_text(" ", strip=True)) for cell in header_cells]
        if any(header is None for header in headers):
            continue

        body_rows = table.select("tbody tr")
        if not body_rows:
            body_rows = table.find_all("tr")[1:]

        for body_row in body_rows:
            value_cells = body_row.find_all("td")
            if len(value_cells) != len(headers):
                continue

            row_values = [normalize_optional_text(cell.get_text(" ", strip=True)) for cell in value_cells]
            extracted_rows.append(dict(zip(headers, row_values, strict=True)))

    return extracted_rows


def parse_ie_report_section_html(
    html_text: str,
    *,
    spender_committee_name: str,
    source_filing_url: str,
    report_detail_url: str | None = None,
    report_export_url: str | None = None,
) -> list[NCIEReportRow]:
    """Parse NC ReportSection-like HTML tables into typed IE rows.

    The parser only extracts and types values. It intentionally does not do
    support/oppose normalization, candidate matching, or DB writes.
    """
    parsed_rows: list[NCIEReportRow] = []

    for raw_row in _extract_table_rows_from_html(html_text):
        if normalize_optional_text(raw_row.get("Expenditure Type Desc")) != _INDEPENDENT_EXPENDITURE_TYPE:
            continue

        parsed_rows.append(
            _build_report_row(
                raw_row,
                row_index=len(parsed_rows),
                spender_committee_name=spender_committee_name,
                source_filing_url=source_filing_url,
                report_detail_url=report_detail_url,
                report_export_url=report_export_url,
            )
        )

    return parsed_rows


def parse_ie_report_section_csv(
    csv_text: str,
    *,
    spender_committee_name: str,
    source_filing_url: str,
    report_detail_url: str | None = None,
    report_export_url: str | None = None,
) -> list[NCIEReportRow]:
    """Parse the machine-readable EXP detail export discovered from an NC ReportSection page.

    The HTML detail page is only a JavaScript shell. The verified stable row contract lives in
    the per-report CSV export linked from that page, so the parser anchors to the export.
    """
    normalized_csv = _normalize_header_rows(csv_text)
    reader = csv.DictReader(StringIO(normalized_csv))
    _validate_header(reader.fieldnames)

    parsed_rows: list[NCIEReportRow] = []
    for raw_row in reader:
        expenditure_type = _require_text(
            raw_row.get("Expenditure Type Desc"),
            field_name="Expenditure Type Desc",
        )
        if expenditure_type != _INDEPENDENT_EXPENDITURE_TYPE:
            raise NCIEReportParseError(
                "NC IE report export contained a non-independent-expenditure row: "
                f"{expenditure_type!r}"
            )

        parsed_rows.append(
            _build_report_row(
                raw_row,
                row_index=len(parsed_rows),
                spender_committee_name=spender_committee_name,
                source_filing_url=source_filing_url,
                report_detail_url=report_detail_url,
                report_export_url=report_export_url,
            )
        )

    if not parsed_rows:
        raise NCIEReportParseError("NC IE report export contained zero expenditure rows")
    return parsed_rows
