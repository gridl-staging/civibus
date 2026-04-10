from __future__ import annotations

import csv
from decimal import Decimal
from pathlib import Path

import pytest

from domains.campaign_finance.jurisdictions.states.GA.scraper import (
    CONTRIBUTION_COLUMNS,
    EXPENDITURE_COLUMNS,
)
from domains.campaign_finance.jurisdictions.states.GA.scraper.parse import (
    _normalize_html_cell,
    infer_entity_type,
    parse_contributions,
    parse_expenditures,
    parse_ga_amount,
    parse_ga_date,
)

REPO_ROOT = Path(__file__).resolve().parents[6]
GA_DIR = REPO_ROOT / "domains" / "campaign_finance" / "jurisdictions" / "states" / "GA"
CONTRIBUTION_FIXTURE_PATH = GA_DIR / "tests" / "fixtures" / "contribution_export_sample.xls"
EXPENDITURE_FIXTURE_PATH = GA_DIR / "tests" / "fixtures" / "expenditure_export_sample.xls"


def _read_fixture_rows() -> list[dict[str, str]]:
    with CONTRIBUTION_FIXTURE_PATH.open("r", encoding="utf-8", newline="") as fixture_file:
        return list(csv.DictReader(fixture_file))


def _write_contribution_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(header)
        writer.writerows(rows)


def _fixture_row_values_in_header_order() -> list[str]:
    fixture_row = _read_fixture_rows()[0]
    return [fixture_row[column] for column in CONTRIBUTION_COLUMNS]


def _write_expenditure_table(path: Path, header: list[str], rows: list[list[str]]) -> None:
    header_cells = "".join(f"<td>{column}</td>" for column in header)
    rendered_rows = "".join(f"<tr>{''.join(f'<td>{value}</td>' for value in row_values)}</tr>" for row_values in rows)
    html_table = f"<table><tr>{header_cells}</tr>{rendered_rows}</table>"
    path.write_text(html_table, encoding="utf-8")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("12/30/2025 12:00:00 AM", "2025-12-30"),
        ("", None),
        ("   ", None),
        (None, None),
    ],
)
def test_parse_ga_date(raw: str | None, expected: str | None) -> None:
    assert parse_ga_date(raw) == expected


def test_parse_ga_date_normalizes_actual_fixture_date_value() -> None:
    fixture_row = _read_fixture_rows()[0]

    assert fixture_row["Date"] == "12/30/2025 12:00:00 AM"
    assert parse_ga_date(fixture_row["Date"]) == "2025-12-30"


def test_parse_ga_date_rejects_non_midnight_timestamp() -> None:
    with pytest.raises(ValueError, match="Invalid GA date value"):
        parse_ga_date("12/30/2025 01:30:00 PM")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("25.0000", Decimal("25.00")),
        ("0.0000", Decimal("0.00")),
        ("", None),
        ("   ", None),
        (None, None),
    ],
)
def test_parse_ga_amount(raw: str | None, expected: Decimal | None) -> None:
    assert parse_ga_amount(raw) == expected


def test_parse_ga_amount_normalizes_fixture_cash_and_in_kind_values() -> None:
    fixture_row = _read_fixture_rows()[0]

    assert parse_ga_amount(fixture_row["Cash_Amount"]) == Decimal("25.00")
    assert parse_ga_amount(fixture_row["In_Kind_Amount"]) == Decimal("0.00")


def test_parse_ga_amount_rejects_non_finite_values() -> None:
    with pytest.raises(ValueError, match="Invalid GA amount value"):
        parse_ga_amount("NaN")


@pytest.mark.parametrize(
    "raw",
    [
        "25.0050",
        "25.0049",
        "25.00000",
        "1E+2",
        "1_000.00",
        "+25.0000",
        "25.00",
    ],
)
def test_parse_ga_amount_rejects_unexpected_precision_or_notation(raw: str) -> None:
    with pytest.raises(ValueError, match="Invalid GA amount value"):
        parse_ga_amount(raw)


@pytest.mark.parametrize(
    ("last_name", "first_name", "expected"),
    [
        ("Doe", "Jane", "person"),
        ("Acme LLC", "", "organization"),
        ("Acme LLC", None, "organization"),
        ("", "", "unknown"),
        ("   ", "   ", "unknown"),
        (None, None, "unknown"),
    ],
)
def test_infer_entity_type(
    last_name: str | None,
    first_name: str | None,
    expected: str,
) -> None:
    assert infer_entity_type(last_name, first_name) == expected


def test_infer_entity_type_uses_fixture_row_without_mutating_inputs() -> None:
    fixture_row = _read_fixture_rows()[0]
    last_name = fixture_row["LastName"]
    first_name = fixture_row["FirstName"]

    assert infer_entity_type(last_name, first_name) == "organization"
    assert last_name == "Waycross Bank & Trust"
    assert first_name == ""


def test_parse_contributions_parses_fixture_and_applies_ga_helper_normalization() -> None:
    parsed_rows = list(parse_contributions(CONTRIBUTION_FIXTURE_PATH))

    assert len(parsed_rows) == 1
    parsed_row = parsed_rows[0]
    assert tuple(parsed_row.keys()) == CONTRIBUTION_COLUMNS
    assert parsed_row["PAC"] is None
    assert parsed_row["Occupation"] is None
    assert parsed_row["Employer"] is None
    assert parsed_row["Date"] == "2025-12-30"
    assert parsed_row["Cash_Amount"] == Decimal("25.00")
    assert parsed_row["In_Kind_Amount"] == Decimal("0.00")
    assert parsed_row["Type"] == "Monetary"
    # Fixture is lowercase full-name state, while semantics doc says postal normalization.
    # Stage 2 parser preserves raw state; State->postal normalization belongs to Stage 4 extract.
    assert parsed_row["State"] == "georgia"


def test_parse_contributions_rejects_bad_contribution_header(tmp_path: Path) -> None:
    fixture_row = _fixture_row_values_in_header_order()
    bad_header = list(CONTRIBUTION_COLUMNS)
    bad_header[1] = "TransactionType"
    fixture_path = tmp_path / "bad-header.csv"
    _write_contribution_csv(fixture_path, bad_header, [fixture_row])

    with pytest.raises(ValueError, match="Unexpected contribution CSV header"):
        list(parse_contributions(fixture_path))


@pytest.mark.parametrize(
    "row_values",
    [
        _fixture_row_values_in_header_order()[:-1],
        [*_fixture_row_values_in_header_order(), "unexpected-column"],
    ],
)
def test_parse_contributions_rejects_short_or_long_rows(row_values: list[str], tmp_path: Path) -> None:
    fixture_path = tmp_path / "malformed-shape.csv"
    _write_contribution_csv(fixture_path, list(CONTRIBUTION_COLUMNS), [row_values])

    with pytest.raises(ValueError, match=r"Malformed contribution CSV row at line 2"):
        list(parse_contributions(fixture_path))


def test_parse_contributions_keeps_literal_sentinel_like_strings_as_data(tmp_path: Path) -> None:
    row_values = _fixture_row_values_in_header_order()
    employer_index = list(CONTRIBUTION_COLUMNS).index("Employer")
    description_index = list(CONTRIBUTION_COLUMNS).index("In_Kind_Description")
    row_values[employer_index] = "__GA_MISSING_FIELD__"
    row_values[description_index] = "__GA_EXTRA_FIELDS__"
    fixture_path = tmp_path / "literal-sentinel-values.csv"
    _write_contribution_csv(fixture_path, list(CONTRIBUTION_COLUMNS), [row_values])

    parsed_row = list(parse_contributions(fixture_path))[0]

    assert parsed_row["Employer"] == "__GA_MISSING_FIELD__"
    assert parsed_row["In_Kind_Description"] == "__GA_EXTRA_FIELDS__"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("&nbsp;", None),
        (" \t&nbsp;\n", None),
        ("  \t\n  ", None),
        ("  Waycross&nbsp;Bank &amp; Trust  ", "Waycross Bank & Trust"),
        ("A&nbsp;&nbsp;B", "A  B"),
    ],
)
def test_normalize_html_cell_handles_nbsp_whitespace_and_entities(
    raw: str,
    expected: str | None,
) -> None:
    assert _normalize_html_cell(raw) == expected


def test_parse_expenditures_maps_fixture_nbsp_cells_to_none() -> None:
    parsed_rows = list(parse_expenditures(EXPENDITURE_FIXTURE_PATH))

    assert parsed_rows[0]["FirstName"] is None
    assert parsed_rows[0]["Occupation_or_Employer"] is None
    assert parsed_rows[0]["Candidate_Suffix"] is None


def test_parse_expenditures_reads_xls_payload_as_html_text_not_csv_or_workbook(tmp_path: Path) -> None:
    row_values = ["fixture-value" for _ in EXPENDITURE_COLUMNS]
    paid_index = list(EXPENDITURE_COLUMNS).index("Paid")
    other_index = list(EXPENDITURE_COLUMNS).index("Other")
    date_index = list(EXPENDITURE_COLUMNS).index("Date")
    row_values[paid_index] = "1.0000"
    row_values[other_index] = "0.0000"
    row_values[date_index] = "1/2/2025 12:00:00 AM"

    fixture_path = tmp_path / "EthicsReportExport.xls"
    _write_expenditure_table(fixture_path, list(EXPENDITURE_COLUMNS), [row_values])

    parsed_rows = list(parse_expenditures(fixture_path))

    assert len(parsed_rows) == 1
    assert parsed_rows[0]["FilerID"] == "fixture-value"
    assert parsed_rows[0]["Date"] == "2025-01-02"


def test_parse_expenditures_rejects_missing_header_row(tmp_path: Path) -> None:
    fixture_path = tmp_path / "missing-header.xls"
    fixture_path.write_text("<table></table>", encoding="utf-8")

    with pytest.raises(ValueError, match="Missing expenditure HTML header row"):
        list(parse_expenditures(fixture_path))


def test_parse_expenditures_rejects_unexpected_header_values(tmp_path: Path) -> None:
    bad_header = list(EXPENDITURE_COLUMNS)
    bad_header[1] = "TransactionKey"
    row_values = ["value" for _ in EXPENDITURE_COLUMNS]
    row_values[list(EXPENDITURE_COLUMNS).index("Date")] = "1/2/2025 12:00:00 AM"
    row_values[list(EXPENDITURE_COLUMNS).index("Paid")] = "1.0000"
    row_values[list(EXPENDITURE_COLUMNS).index("Other")] = "0.0000"

    fixture_path = tmp_path / "bad-header.xls"
    _write_expenditure_table(fixture_path, bad_header, [row_values])

    with pytest.raises(ValueError, match="Unexpected expenditure HTML header"):
        list(parse_expenditures(fixture_path))


def test_parse_expenditures_parses_td_header_fixture_and_applies_ga_helpers() -> None:
    parsed_rows = list(parse_expenditures(EXPENDITURE_FIXTURE_PATH))

    assert len(parsed_rows) == 4
    first_row = parsed_rows[0]
    # Fixture uses <td> header cells (not <th>), so header extraction must support table-data cells.
    assert tuple(first_row.keys()) == EXPENDITURE_COLUMNS
    assert first_row["Date"] == "2025-01-29"
    assert first_row["Paid"] == Decimal("5.00")
    assert first_row["Other"] == Decimal("0.00")
    assert first_row["FirstName"] is None
    assert first_row["Occupation_or_Employer"] is None
    assert first_row["Candidate_Suffix"] is None
    assert first_row["State"] == "GA"
    assert first_row["Type"] == "Expenditure"
    assert [(row["Key"], row["Ref"]) for row in parsed_rows].count(("2", "2")) == 2


@pytest.mark.parametrize(
    "row_values",
    [
        ["value" for _ in range(len(EXPENDITURE_COLUMNS) - 1)],
        ["value" for _ in range(len(EXPENDITURE_COLUMNS) + 1)],
    ],
)
def test_parse_expenditures_rejects_short_or_long_rows(row_values: list[str], tmp_path: Path) -> None:
    row_values[list(EXPENDITURE_COLUMNS).index("Date")] = "1/2/2025 12:00:00 AM"
    row_values[list(EXPENDITURE_COLUMNS).index("Paid")] = "1.0000"
    row_values[list(EXPENDITURE_COLUMNS).index("Other")] = "0.0000"

    fixture_path = tmp_path / "malformed-shape.xls"
    _write_expenditure_table(fixture_path, list(EXPENDITURE_COLUMNS), [row_values])

    with pytest.raises(ValueError, match="Malformed expenditure HTML row at index 1"):
        list(parse_expenditures(fixture_path))


def test_parse_expenditures_keeps_literal_marker_like_strings_as_data(tmp_path: Path) -> None:
    row_values = ["value" for _ in EXPENDITURE_COLUMNS]
    row_values[list(EXPENDITURE_COLUMNS).index("Date")] = "1/2/2025 12:00:00 AM"
    row_values[list(EXPENDITURE_COLUMNS).index("Paid")] = "1.0000"
    row_values[list(EXPENDITURE_COLUMNS).index("Other")] = "0.0000"
    row_values[list(EXPENDITURE_COLUMNS).index("Occupation_or_Employer")] = "__GA_MISSING_FIELD__"
    row_values[list(EXPENDITURE_COLUMNS).index("FirstName")] = "&amp;nbsp;"

    fixture_path = tmp_path / "literal-marker-values.xls"
    _write_expenditure_table(fixture_path, list(EXPENDITURE_COLUMNS), [row_values])

    parsed_row = list(parse_expenditures(fixture_path))[0]

    assert parsed_row["Occupation_or_Employer"] == "__GA_MISSING_FIELD__"
    assert parsed_row["FirstName"] == "&nbsp;"
