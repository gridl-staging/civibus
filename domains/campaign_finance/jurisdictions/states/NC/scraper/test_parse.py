from __future__ import annotations

import csv
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from domains.campaign_finance.jurisdictions.states.NC.scraper.parse import (
    COMMITTEE_DOC_COLUMNS,
    TRANSACTION_COLUMNS,
    classify_transction_type,
    parse_amendment_flag,
    parse_committee_docs,
    parse_nc_amount,
    parse_nc_date,
    parse_transactions,
)

TRANSACTION_HEADER = ",".join(TRANSACTION_COLUMNS)
COMMITTEE_DOC_HEADER = ",".join(COMMITTEE_DOC_COLUMNS)
VALID_TRANSACTION_ROW = (
    ",123 MAIN ST,,RALEIGH,NC,27601,,,Individual,EXAMPLE COMMITTEE,STA-XXXX-C-001,"
    "101 CENTER ST,,RALEIGH,NC,27601,2025 MID YEAR,06/26/2025,Not Available,10.0000,"
    "Check,,,"
)
VALID_COMMITTEE_DOC_ROW = (
    "JASON MERRILL FOR CARRBORO TOWN COUNCIL,001-4L70LV-C-001,2025,Disclosure Report,"
    "Year End Semi-Annual,N,,01/26/2026,07/01/2025,12/31/2025,,DATA"
)
MALFORMED_SHORT_ROW = (
    ",123 MAIN ST,,RALEIGH,NC,27601,,,Individual,EXAMPLE COMMITTEE,STA-XXXX-C-001,"
    "101 CENTER ST,,RALEIGH,NC,27601,2025 MID YEAR,06/26/2025,Not Available,10.0000,"
    "Check,,"
)
MALFORMED_LONG_ROW = f"{VALID_TRANSACTION_ROW},unexpected"
MALFORMED_SHORT_COMMITTEE_DOC_ROW = (
    "JASON MERRILL FOR CARRBORO TOWN COUNCIL,001-4L70LV-C-001,2025,Disclosure Report,"
    "Year End Semi-Annual,N,,01/26/2026,07/01/2025,12/31/2025,"
)
MALFORMED_LONG_COMMITTEE_DOC_ROW = f"{VALID_COMMITTEE_DOC_ROW},unexpected"


@pytest.fixture
def transaction_fixture_path() -> Path:
    return Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "transaction_export_sample.csv"


@pytest.fixture
def committee_document_fixture_path() -> Path:
    return Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "committee_document_export_sample.csv"


def _write_fixture(path: Path, *rows: str, header: str) -> None:
    path.write_text("\n".join((header, *rows, "")), encoding="utf-8")


def _build_transaction_row(date_occured: str) -> dict[str, str]:
    row = {column: "" for column in TRANSACTION_COLUMNS}
    row["Committee Name"] = "EXAMPLE COMMITTEE"
    row["Committee SBoE ID"] = "STA-XXXX-C-001"
    row["Date Occured"] = date_occured
    row["Amount"] = "10.0000"
    row["Form of Payment"] = "Check"
    row["Transction Type"] = "Individual"
    return row


def test_transaction_columns_match_fixture_header_order_and_preserve_typos() -> None:
    assert len(TRANSACTION_COLUMNS) == 24
    assert TRANSACTION_COLUMNS[0] == "Name"
    assert TRANSACTION_COLUMNS[8] == "Transction Type"
    assert TRANSACTION_COLUMNS[17] == "Date Occured"
    assert TRANSACTION_COLUMNS[-1] == "Declaration"


def test_transaction_columns_round_trip_with_fixture_header(transaction_fixture_path: Path) -> None:
    with transaction_fixture_path.open("r", encoding="utf-8", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        fieldnames = tuple(reader.fieldnames or ())

    assert fieldnames == TRANSACTION_COLUMNS


def test_committee_doc_columns_match_fixture_header_order() -> None:
    assert len(COMMITTEE_DOC_COLUMNS) == 12
    assert COMMITTEE_DOC_COLUMNS[0] == "Committee Name"
    assert COMMITTEE_DOC_COLUMNS[5] == "Amend"
    assert COMMITTEE_DOC_COLUMNS[-1] == "Data"


def test_committee_doc_columns_round_trip_with_fixture_header(
    committee_document_fixture_path: Path,
) -> None:
    with committee_document_fixture_path.open("r", encoding="utf-8", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        fieldnames = tuple(reader.fieldnames or ())

    assert fieldnames == COMMITTEE_DOC_COLUMNS


def test_parse_transactions_reads_fixture_rows_and_normalizes_blanks(transaction_fixture_path: Path) -> None:
    parser = parse_transactions(transaction_fixture_path)

    rows = list(parser)

    assert len(rows) == 5
    for row in rows:
        assert tuple(row.keys()) == TRANSACTION_COLUMNS

    assert rows[0]["Name"] is None
    assert rows[1]["Name"] is None
    assert rows[2]["Name"] is None
    assert rows[3]["Name"] is None
    assert rows[4]["Name"].startswith("\tNORTH CAROLINA FARM BUREAU")
    assert rows[0]["Street Line 2"] is None
    assert rows[0]["Profession/Job Title"] is None
    assert rows[0]["Employer's Name/Specific Field"] is None


def test_parse_transactions_filters_pre_year_from_rows_and_tracks_filtered_count(tmp_path: Path) -> None:
    fixture_path = tmp_path / "year-filter.csv"
    with fixture_path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=list(TRANSACTION_COLUMNS))
        writer.writeheader()
        writer.writerow(_build_transaction_row("12/31/2021"))
        writer.writerow(_build_transaction_row("01/01/2022"))
        writer.writerow(_build_transaction_row("06/26/2025"))

    parser = parse_transactions(fixture_path, year_from=2022)
    rows = list(parser)

    assert len(rows) == 2
    assert [row["Date Occured"] for row in rows] == ["01/01/2022", "06/26/2025"]
    assert parser.filtered == 1
    assert parser.skipped == 0


def test_parse_transactions_without_explicit_year_from_uses_default_five_year_window(tmp_path: Path) -> None:
    fixture_path = tmp_path / "default-year-filter.csv"
    current_year = datetime.now(timezone.utc).year
    default_year_from = current_year - 4
    with fixture_path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=list(TRANSACTION_COLUMNS))
        writer.writeheader()
        writer.writerow(_build_transaction_row(f"01/01/{default_year_from - 1}"))
        writer.writerow(_build_transaction_row(f"01/01/{default_year_from}"))

    parser = parse_transactions(fixture_path, year_from=None)
    rows = list(parser)

    assert len(rows) == 1
    assert rows[0]["Date Occured"] == f"01/01/{default_year_from}"
    assert parser.filtered == 1


def test_parse_committee_docs_reads_fixture_rows_and_normalizes_blanks(
    committee_document_fixture_path: Path,
) -> None:
    parser = parse_committee_docs(committee_document_fixture_path)

    rows = list(parser)

    assert len(rows) == 8
    for row in rows:
        assert tuple(row.keys()) == COMMITTEE_DOC_COLUMNS
        assert row["Received Image"] is None
        assert row["Image"] is None
        assert row["Data"] == "DATA"


def test_parse_transactions_rejects_unexpected_header(tmp_path: Path) -> None:
    fixture_path = tmp_path / "unexpected-header.csv"
    mismatched_columns = list(TRANSACTION_COLUMNS)
    mismatched_columns[19] = "Total"
    _write_fixture(fixture_path, VALID_TRANSACTION_ROW, header=",".join(mismatched_columns))

    parser = parse_transactions(fixture_path)

    with pytest.raises(ValueError, match="Unexpected transaction CSV header"):
        list(parser)


def test_parse_committee_docs_rejects_unexpected_header(tmp_path: Path) -> None:
    fixture_path = tmp_path / "unexpected-committee-doc-header.csv"
    mismatched_columns = list(COMMITTEE_DOC_COLUMNS)
    mismatched_columns[5] = "Amendment"
    _write_fixture(fixture_path, VALID_COMMITTEE_DOC_ROW, header=",".join(mismatched_columns))

    parser = parse_committee_docs(fixture_path)

    with pytest.raises(ValueError, match="Unexpected committee_document CSV header"):
        list(parser)


@pytest.mark.parametrize("malformed_row", [MALFORMED_SHORT_ROW, MALFORMED_LONG_ROW])
def test_parse_transactions_skips_malformed_rows(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    malformed_row: str,
) -> None:
    fixture_path = tmp_path / "malformed.csv"
    _write_fixture(fixture_path, VALID_TRANSACTION_ROW, malformed_row, header=TRANSACTION_HEADER)

    parser = parse_transactions(fixture_path)

    with caplog.at_level("WARNING"):
        rows = list(parser)

    assert len(rows) == 1
    assert parser.skipped == 1
    assert "line 3" in caplog.text


@pytest.mark.parametrize(
    "malformed_row",
    [MALFORMED_SHORT_COMMITTEE_DOC_ROW, MALFORMED_LONG_COMMITTEE_DOC_ROW],
)
def test_parse_committee_docs_skips_malformed_rows(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    malformed_row: str,
) -> None:
    fixture_path = tmp_path / "malformed-committee-doc.csv"
    _write_fixture(
        fixture_path,
        VALID_COMMITTEE_DOC_ROW,
        malformed_row,
        header=COMMITTEE_DOC_HEADER,
    )

    parser = parse_committee_docs(fixture_path)

    with caplog.at_level("WARNING"):
        rows = list(parser)

    assert len(rows) == 1
    assert parser.skipped == 1
    assert "line 3" in caplog.text


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("06/26/2025", "2025-06-26"),
        ("05/01/2025", "2025-05-01"),
        (None, None),
        ("", None),
        ("  ", None),
    ],
)
def test_parse_nc_date(raw: str | None, expected: str | None) -> None:
    assert parse_nc_date(raw) == expected


def test_parse_nc_date_raises_on_invalid_non_empty_input() -> None:
    with pytest.raises(ValueError, match="Invalid NC date"):
        parse_nc_date("2025-06-26")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("01/26/2026", "2026-01-26"),
        ("07/27/2025", "2025-07-27"),
        ("07/01/2025", "2025-07-01"),
        ("01/01/2025", "2025-01-01"),
        ("12/31/2025", "2025-12-31"),
        ("06/30/2025", "2025-06-30"),
    ],
)
def test_parse_nc_date_accepts_committee_document_dates(raw: str, expected: str) -> None:
    assert parse_nc_date(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("10.0000", Decimal("10.0000")),
        ("300.0000", Decimal("300.0000")),
        ("-50.0000", Decimal("-50.0000")),
        (None, None),
        ("", None),
        ("  ", None),
    ],
)
def test_parse_nc_amount(raw: str | None, expected: Decimal | None) -> None:
    assert parse_nc_amount(raw) == expected


def test_parse_nc_amount_raises_on_invalid_non_empty_input() -> None:
    with pytest.raises(ValueError, match="Invalid NC amount"):
        parse_nc_amount("abc")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Individual", "person"),
        ("Non-Party Comm", "organization"),
        ("Business/Group/Org", "organization"),
        (None, None),
        ("", None),
        ("  ", None),
    ],
)
def test_classify_transction_type(raw: str | None, expected: str | None) -> None:
    assert classify_transction_type(raw) == expected


def test_classify_transction_type_returns_unknown_for_unrecognized_value() -> None:
    assert classify_transction_type("Unknown Type") == "unknown"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Y", True),
        (" N ", False),
        (None, None),
        ("", None),
        ("  ", None),
    ],
)
def test_parse_amendment_flag(raw: str | None, expected: bool | None) -> None:
    assert parse_amendment_flag(raw) is expected


def test_parse_amendment_flag_raises_on_unknown_value() -> None:
    with pytest.raises(ValueError, match="Unknown NC amendment flag"):
        parse_amendment_flag("Maybe")
