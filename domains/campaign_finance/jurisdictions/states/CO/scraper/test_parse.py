from __future__ import annotations

from pathlib import Path

import pytest

from domains.campaign_finance.jurisdictions.config_schema import load_jurisdiction_config
from domains.campaign_finance.jurisdictions.states.CO.scraper.load import _CO_DATA_SOURCE_NAME_BY_TYPE
from domains.campaign_finance.jurisdictions.states.CO.scraper.parse import (
    CONTRIBUTION_COLUMNS,
    EXPENDITURE_COLUMNS,
    parse_co_date,
    parse_contributions,
    parse_expenditures,
    parse_contributor_type,
    is_superseded,
)

_CO_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.yaml"

CONTRIBUTION_HEADER = ",".join(CONTRIBUTION_COLUMNS)
EXPENDITURE_HEADER = ",".join(EXPENDITURE_COLUMNS)
VALID_CONTRIBUTION_ROW = (
    "20155011111,100.00,2025-01-01 00:00:00,Doe,Janet,,,100 Main St,,Denver,CO,80205,,5001,"
    "2025-01-02 00:00:00,Monetary (Itemized),Contribution,Individual,N,Candidate Committee,"
    "People First,Candidate Name,Employer Inc,Engineer,N,N,0,Colorado,"
)
MALFORMED_SHORT_ROW = (
    "20155022222,200.00,2025-01-03 00:00:00,Smith,Alex,,,200 Main St,,Denver,CO,80205,,5002,"
    "2025-01-04 00:00:00,Monetary (Itemized),Contribution,Individual,N,Candidate Committee,"
    "People First,Candidate Name,Employer Inc,Engineer,N,N"
)
MALFORMED_LONG_ROW = (
    "20155022222,200.00,2025-01-03 00:00:00,Smith,Alex,,,200 Main St,,Denver,CO,80205,,5002,"
    "2025-01-04 00:00:00,Monetary (Itemized),Contribution,Individual,N,Candidate Committee,"
    "People First,Candidate Name,Employer Inc,Engineer,N,N,0,Colorado,,unexpected"
)
SENTINEL_LITERAL_ROW = (
    "20155033333,210.00,2025-01-05 00:00:00,Roe,Jamie,,,300 Main St,,Denver,CO,80206,"
    "__CO_TRACER_MISSING_FIELD__,5003,2025-01-06 00:00:00,Monetary (Itemized),Contribution,"
    "Individual,N,Candidate Committee,People First,Candidate Name,Employer Inc,Engineer,N,N,0,"
    "Colorado,__CO_TRACER_EXTRA_FIELDS__"
)
VALID_EXPENDITURE_ROW = (
    "20155044444,125.00,2025-02-01 00:00:00,Roe,Jamie,,,100 Main St,,Denver,CO,80205,Vendor payment,"
    "7001,2025-02-02 00:00:00,Operating Expenditure,Check,Services,N,Candidate Committee,People First,"
    "Candidate Name,,,N,N,0,Colorado"
)
MALFORMED_SHORT_EXPENDITURE_ROW = (
    "20155055555,205.00,2025-02-03 00:00:00,Smith,Alex,,,200 Main St,,Denver,CO,80205,Mailer,"
    "7002,2025-02-04 00:00:00,Operating Expenditure,Electronic Funds Transfer,Services,N,"
    "Candidate Committee,People First,Candidate Name,,,N,N,0"
)
MALFORMED_LONG_EXPENDITURE_ROW = (
    "20155055555,205.00,2025-02-03 00:00:00,Smith,Alex,,,200 Main St,,Denver,CO,80205,Mailer,"
    "7002,2025-02-04 00:00:00,Operating Expenditure,Electronic Funds Transfer,Services,N,"
    "Candidate Committee,People First,Candidate Name,,,N,N,0,Colorado,unexpected"
)


@pytest.fixture
def sample_contributions_path() -> Path:
    return Path(__file__).parent / "test_fixtures" / "sample_contributions.csv"


@pytest.fixture
def sample_expenditures_path() -> Path:
    return Path(__file__).parent / "test_fixtures" / "sample_expenditures.csv"


def _write_fixture(path: Path, *rows: str, header: str) -> None:
    path.write_text("\n".join((header, *rows, "")), encoding="utf-8")


def test_parse_contributions_reads_all_rows_and_normalizes_empty_strings(sample_contributions_path: Path):
    parser = parse_contributions(sample_contributions_path)

    rows = list(parser)

    assert len(rows) == 11
    for row in rows:
        assert tuple(row.keys()) == CONTRIBUTION_COLUMNS

    assert rows[0]["Address2"] is None
    assert rows[0]["Explanation"] is None
    assert rows[1]["FirstName"] is None
    assert rows[1]["MI"] is None
    assert rows[1]["Suffix"] is None


def test_loader_data_source_names_match_config_transaction_types() -> None:
    config = load_jurisdiction_config(_CO_CONFIG_PATH)
    data_source_name_by_type: dict[str, str] = {}
    for data_source in config.data_sources:
        for transaction_type in data_source.coverage.transaction_types:
            data_source_name_by_type[transaction_type] = data_source.name

    assert _CO_DATA_SOURCE_NAME_BY_TYPE["contributions"] == data_source_name_by_type["contributions"]
    assert _CO_DATA_SOURCE_NAME_BY_TYPE["expenditures"] == data_source_name_by_type["expenditures"]


def test_parse_contributions_rejects_unexpected_headers(tmp_path: Path):
    fixture_path = tmp_path / "unexpected-header.csv"
    unexpected_columns = list(CONTRIBUTION_COLUMNS)
    unexpected_columns[1] = "ContributionTotal"
    _write_fixture(
        fixture_path,
        VALID_CONTRIBUTION_ROW,
        header=",".join(unexpected_columns),
    )

    parser = parse_contributions(fixture_path)

    with pytest.raises(ValueError, match="Unexpected contribution CSV header"):
        list(parser)


@pytest.mark.parametrize("malformed_row", [MALFORMED_SHORT_ROW, MALFORMED_LONG_ROW])
def test_parse_contributions_skips_malformed_row_and_logs_warning(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    malformed_row: str,
):
    fixture_path = tmp_path / "malformed.csv"
    _write_fixture(
        fixture_path,
        VALID_CONTRIBUTION_ROW,
        malformed_row,
        header=CONTRIBUTION_HEADER,
    )

    parser = parse_contributions(fixture_path)

    with caplog.at_level("WARNING"):
        rows = list(parser)

    assert len(rows) == 1
    assert parser.skipped == 1
    assert "line 3" in caplog.text


def test_parse_contributions_accepts_literal_sentinel_values(tmp_path: Path):
    fixture_path = tmp_path / "sentinel-values.csv"
    _write_fixture(fixture_path, SENTINEL_LITERAL_ROW, header=CONTRIBUTION_HEADER)

    parser = parse_contributions(fixture_path)
    rows = list(parser)

    assert len(rows) == 1
    assert parser.skipped == 0
    assert rows[0]["Explanation"] == "__CO_TRACER_MISSING_FIELD__"
    assert rows[0]["OccupationComments"] == "__CO_TRACER_EXTRA_FIELDS__"


def test_expenditure_columns_match_expected_header_order() -> None:
    assert len(EXPENDITURE_COLUMNS) == 28
    assert EXPENDITURE_COLUMNS == (
        "CO_ID",
        "ExpenditureAmount",
        "ExpenditureDate",
        "LastName",
        "FirstName",
        "MI",
        "Suffix",
        "Address1",
        "Address2",
        "City",
        "State",
        "Zip",
        "Explanation",
        "RecordID",
        "FiledDate",
        "ExpenditureType",
        "PaymentType",
        "DisbursementType",
        "Electioneering",
        "CommitteeType",
        "CommitteeName",
        "CandidateName",
        "Employer",
        "Occupation",
        "Amended",
        "Amendment",
        "AmendedRecordID",
        "Jurisdiction",
    )


def test_parse_expenditures_reads_all_rows(sample_expenditures_path: Path) -> None:
    parser = parse_expenditures(sample_expenditures_path)

    rows = list(parser)

    assert len(rows) == 5
    for row in rows:
        assert tuple(row.keys()) == EXPENDITURE_COLUMNS


@pytest.mark.parametrize(
    "malformed_row",
    [MALFORMED_SHORT_EXPENDITURE_ROW, MALFORMED_LONG_EXPENDITURE_ROW],
)
def test_parse_expenditures_skips_malformed_rows(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    malformed_row: str,
) -> None:
    fixture_path = tmp_path / "malformed-expenditures.csv"
    _write_fixture(
        fixture_path,
        VALID_EXPENDITURE_ROW,
        malformed_row,
        header=EXPENDITURE_HEADER,
    )

    parser = parse_expenditures(fixture_path)

    with caplog.at_level("WARNING"):
        rows = list(parser)

    assert len(rows) == 1
    assert parser.skipped == 1
    assert "line 3" in caplog.text


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        ({"Amended": "Y", "Amendment": "N"}, True),
        ({"Amended": "N", "Amendment": "N"}, False),
        ({"Amended": "N", "Amendment": "Y"}, False),
    ],
)
def test_is_superseded(row: dict[str, str], expected: bool):
    assert is_superseded(row) is expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "Individual (Member of LLC: HOWES WOLF LLC)",
            ("Individual", "HOWES WOLF LLC"),
        ),
        ("Business", ("Business", None)),
        (None, (None, None)),
    ],
)
def test_parse_contributor_type(raw: str | None, expected: tuple[str | None, str | None]):
    assert parse_contributor_type(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2025-01-01 00:00:00", "2025-01-01"),
        ("", None),
        (None, None),
    ],
)
def test_parse_co_date(raw: str | None, expected: str | None):
    assert parse_co_date(raw) == expected
