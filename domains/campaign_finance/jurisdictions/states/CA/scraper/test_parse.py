from __future__ import annotations

from pathlib import Path

import pytest

from domains.campaign_finance.jurisdictions.states.CA.scraper import (
    INGESTION_TABLE_NAMES,
    _load_columns_for_table,
)
from domains.campaign_finance.jurisdictions.states.CA.scraper.parse import (
    parse_table,
)


def _write_tsv(path: Path, header: str, *rows: str) -> None:
    """Write a tab-delimited TSV file with the given header and data rows."""
    path.write_text("\n".join((header, *rows, "")), encoding="utf-8")


# --- Header validation ---


def test_parse_table_validates_header_against_config_columns(tmp_path: Path):
    """Parser should reject a TSV whose header doesn't match config-derived columns."""
    columns = _load_columns_for_table("RCPT_CD")
    # Corrupt the first column name
    bad_columns = ("WRONG_COL",) + columns[1:]
    header = "\t".join(bad_columns)
    fixture = tmp_path / "RCPT_CD.TSV"
    _write_tsv(fixture, header, "\t".join(["val"] * len(bad_columns)))

    parser = parse_table(fixture, "RCPT_CD")

    with pytest.raises(ValueError, match="[Hh]eader|[Cc]olumn"):
        list(parser)


def test_parse_table_accepts_correct_header(tmp_path: Path):
    columns = _load_columns_for_table("RCPT_CD")
    header = "\t".join(columns)
    row = "\t".join(["val"] * len(columns))
    fixture = tmp_path / "RCPT_CD.TSV"
    _write_tsv(fixture, header, row)

    parser = parse_table(fixture, "RCPT_CD")
    rows = list(parser)

    assert len(rows) == 1
    assert tuple(rows[0].keys()) == columns


def test_parse_table_accepts_live_rcpt_cd_superset_header_and_maps_by_column_name(tmp_path: Path):
    """RCPT_CD live feeds can include extra/reordered columns; parser must map configured subset by name."""
    expected_columns = _load_columns_for_table("RCPT_CD")
    live_header = (
        "FILING_ID",
        "AMEND_ID",
        "LINE_ITEM",
        "REC_TYPE",
        "FORM_TYPE",
        "TRAN_ID",
        "ENTITY_CD",
        "CTRIB_NAML",
        "CTRIB_NAMF",
        "CTRIB_NAMT",
        "CTRIB_NAMS",
        "CTRIB_CITY",
        "CTRIB_ST",
        "CTRIB_ZIP4",
        "CTRIB_EMP",
        "CTRIB_OCC",
        "CTRIB_SELF",
        "TRAN_TYPE",
        "RCPT_DATE",
        "DATE_THRU",
        "AMOUNT",
        "CUM_YTD",
        "CUM_OTH",
        "CTRIB_DSCR",
        "CMTE_ID",
        "TRES_NAML",
        "TRES_NAMF",
        "TRES_NAMT",
        "TRES_NAMS",
        "TRES_CITY",
        "TRES_ST",
        "TRES_ZIP4",
        "INTR_NAML",
        "INTR_NAMF",
        "INTR_NAMT",
        "INTR_NAMS",
        "INTR_CITY",
        "INTR_ST",
        "INTR_ZIP4",
        "INTR_EMP",
        "INTR_OCC",
        "INTR_SELF",
        "CAND_NAML",
        "CAND_NAMF",
        "CAND_NAMT",
        "CAND_NAMS",
        "OFFICE_CD",
        "OFFIC_DSCR",
        "JURIS_CD",
        "JURIS_DSCR",
        "DIST_NO",
        "OFF_S_H_CD",
        "BAL_NAME",
        "BAL_NUM",
        "BAL_JURIS",
        "SUP_OPP_CD",
        "MEMO_CODE",
        "MEMO_REFNO",
        "BAKREF_TID",
        "XREF_SCHNM",
        "XREF_MATCH",
        "INT_RATE",
        "INTR_CMTEID",
    )
    row_by_column = {column: f"value_for_{index}" for index, column in enumerate(live_header)}
    row = "\t".join(row_by_column[column] for column in live_header)
    fixture = tmp_path / "RCPT_CD.TSV"
    _write_tsv(fixture, "\t".join(live_header), row)

    parser = parse_table(fixture, "RCPT_CD")
    rows = list(parser)

    assert len(rows) == 1
    assert tuple(rows[0].keys()) == expected_columns
    for column in expected_columns:
        assert rows[0][column] == row_by_column[column]


# --- Tab-delimited parsing ---


def test_parse_table_reads_tab_delimited_rows(tmp_path: Path):
    columns = _load_columns_for_table("EXPN_CD")
    header = "\t".join(columns)
    row1_vals = [f"r1c{i}" for i in range(len(columns))]
    row2_vals = [f"r2c{i}" for i in range(len(columns))]
    fixture = tmp_path / "EXPN_CD.TSV"
    _write_tsv(fixture, header, "\t".join(row1_vals), "\t".join(row2_vals))

    parser = parse_table(fixture, "EXPN_CD")
    rows = list(parser)

    assert len(rows) == 2
    assert rows[0][columns[0]] == "r1c0"
    assert rows[1][columns[0]] == "r2c0"


# --- Empty string normalization ---


def test_parse_table_normalizes_empty_strings_to_none(tmp_path: Path):
    columns = _load_columns_for_table("LOAN_CD")
    header = "\t".join(columns)
    # Row with some empty values
    vals = ["val"] * len(columns)
    vals[2] = ""  # TRAN_ID empty
    vals[5] = ""  # another field empty
    fixture = tmp_path / "LOAN_CD.TSV"
    _write_tsv(fixture, header, "\t".join(vals))

    parser = parse_table(fixture, "LOAN_CD")
    rows = list(parser)

    assert len(rows) == 1
    assert rows[0][columns[2]] is None
    assert rows[0][columns[5]] is None
    assert rows[0][columns[0]] == "val"


# --- Malformed row handling ---


def test_parse_table_skips_short_rows_and_logs_warning(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
):
    columns = _load_columns_for_table("RCPT_CD")
    header = "\t".join(columns)
    good_row = "\t".join(["val"] * len(columns))
    short_row = "\t".join(["val"] * (len(columns) - 3))
    fixture = tmp_path / "RCPT_CD.TSV"
    _write_tsv(fixture, header, good_row, short_row)

    parser = parse_table(fixture, "RCPT_CD")

    with caplog.at_level("WARNING"):
        rows = list(parser)

    assert len(rows) == 1
    assert parser.skipped == 1
    assert "line 3" in caplog.text


def test_parse_table_skips_long_rows_and_logs_warning(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
):
    columns = _load_columns_for_table("RCPT_CD")
    header = "\t".join(columns)
    good_row = "\t".join(["val"] * len(columns))
    long_row = "\t".join(["val"] * (len(columns) + 5))
    fixture = tmp_path / "RCPT_CD.TSV"
    _write_tsv(fixture, header, good_row, long_row)

    parser = parse_table(fixture, "RCPT_CD")

    with caplog.at_level("WARNING"):
        rows = list(parser)

    assert len(rows) == 1
    assert parser.skipped == 1
    assert "line 3" in caplog.text


# --- Parser as iterator with skipped count ---


def test_parser_tracks_skipped_count(tmp_path: Path):
    # Use EXPN_CD (multi-column) so short/long rows are clearly distinguishable
    columns = _load_columns_for_table("EXPN_CD")
    header = "\t".join(columns)
    good = "\t".join(["val"] * len(columns))
    bad1 = "\t".join(["val"] * 1)
    bad2 = "\t".join(["val"] * (len(columns) + 10))
    fixture = tmp_path / "EXPN_CD.TSV"
    _write_tsv(fixture, header, good, bad1, bad2, good)

    parser = parse_table(fixture, "EXPN_CD")
    rows = list(parser)

    assert len(rows) == 2
    assert parser.skipped == 2


# --- All locked tables can be parsed ---


@pytest.mark.parametrize("table_name", INGESTION_TABLE_NAMES)
def test_parse_table_works_for_all_locked_tables(tmp_path: Path, table_name: str):
    """Each locked table should be parseable when given a valid TSV with correct headers."""
    columns = _load_columns_for_table(table_name)
    header = "\t".join(columns)
    row = "\t".join([f"v{i}" for i in range(len(columns))])
    fixture = tmp_path / f"{table_name}.TSV"
    _write_tsv(fixture, header, row)

    parser = parse_table(fixture, table_name)
    rows = list(parser)

    assert len(rows) == 1
    assert tuple(rows[0].keys()) == columns


# --- Error for unknown table ---


def test_parse_table_raises_for_unknown_table(tmp_path: Path):
    fixture = tmp_path / "FAKE.TSV"
    fixture.write_text("COL1\tCOL2\nval1\tval2\n")

    with pytest.raises(RuntimeError, match="No field mappings found"):
        parse_table(fixture, "NONEXISTENT_TABLE")


# --- Live FILERS_CD header regression ---


def test_filers_cd_parses_live_single_column_header(tmp_path: Path):
    """Live FILERS_CD.TSV has only FILER_ID; config must match.

    The live CAL-ACCESS dbwebexport.zip FILERS_CD.TSV header contains only
    'FILER_ID', not the 4-column header the config originally declared.
    This test ensures the parser accepts the live header without ValueError.
    """
    columns = _load_columns_for_table("FILERS_CD")
    # After the config fix, FILERS_CD should only declare FILER_ID
    assert columns == ("FILER_ID",), f"Expected FILERS_CD to have only FILER_ID, got {columns}"

    header = "FILER_ID"
    row = "C12345"
    fixture = tmp_path / "FILERS_CD.TSV"
    _write_tsv(fixture, header, row)

    parser = parse_table(fixture, "FILERS_CD")
    rows = list(parser)

    assert len(rows) == 1
    assert rows[0]["FILER_ID"] == "C12345"
    assert parser.skipped == 0


# --- Year filter tests (MM/DD/YYYY date format) ---


def test_parse_table_with_year_from_filters_old_rows(tmp_path: Path):
    """Rows with transaction date before year_from should be filtered out."""
    columns = _load_columns_for_table("RCPT_CD")
    header = "\t".join(columns)
    # RCPT_DATE is the date column for RCPT_CD (MM/DD/YYYY format)
    rcpt_date_index = columns.index("RCPT_DATE")

    def _make_row(date_value: str) -> str:
        vals = ["val"] * len(columns)
        vals[rcpt_date_index] = date_value
        return "\t".join(vals)

    fixture = tmp_path / "RCPT_CD.TSV"
    _write_tsv(
        fixture,
        header,
        _make_row("01/15/2020"),  # before 2022 — should be filtered
        _make_row("12/31/2021"),  # before 2022 — should be filtered
        _make_row("01/01/2022"),  # exactly 2022 — should be kept
        _make_row("06/15/2024"),  # after 2022 — should be kept
    )

    parser = parse_table(fixture, "RCPT_CD", year_from=2022)
    rows = list(parser)

    assert len(rows) == 2
    assert rows[0]["RCPT_DATE"] == "01/01/2022"
    assert rows[1]["RCPT_DATE"] == "06/15/2024"
    assert parser.filtered == 2


def test_parse_table_with_year_from_passes_none_dates(tmp_path: Path):
    """Rows with empty/None date values should pass through (loader handles them)."""
    columns = _load_columns_for_table("EXPN_CD")
    header = "\t".join(columns)
    expn_date_index = columns.index("EXPN_DATE")

    def _make_row(date_value: str) -> str:
        vals = ["val"] * len(columns)
        vals[expn_date_index] = date_value
        return "\t".join(vals)

    fixture = tmp_path / "EXPN_CD.TSV"
    _write_tsv(
        fixture,
        header,
        _make_row(""),  # empty date — should pass through
        _make_row("03/15/2023"),  # after 2022 — should be kept
        _make_row("11/01/2019"),  # before 2022 — should be filtered
    )

    parser = parse_table(fixture, "EXPN_CD", year_from=2022)
    rows = list(parser)

    assert len(rows) == 2  # empty date + 2023 row
    assert rows[0]["EXPN_DATE"] is None  # empty -> None normalization
    assert rows[1]["EXPN_DATE"] == "03/15/2023"
    assert parser.filtered == 1


def test_parse_table_with_year_from_handles_unparseable_dates(tmp_path: Path):
    """Rows with malformed dates should pass through (not silently dropped)."""
    columns = _load_columns_for_table("RCPT_CD")
    header = "\t".join(columns)
    rcpt_date_index = columns.index("RCPT_DATE")

    def _make_row(date_value: str) -> str:
        vals = ["val"] * len(columns)
        vals[rcpt_date_index] = date_value
        return "\t".join(vals)

    fixture = tmp_path / "RCPT_CD.TSV"
    _write_tsv(
        fixture,
        header,
        _make_row("not-a-date"),  # unparseable — should pass through
        _make_row("01/15/2024"),  # after 2022 — should be kept
    )

    parser = parse_table(fixture, "RCPT_CD", year_from=2022)
    rows = list(parser)

    assert len(rows) == 2
    assert parser.filtered == 0


def test_parse_table_with_year_from_filters_loan_cd(tmp_path: Path):
    """LOAN_CD uses LOAN_DATE1 as the date column; year filter should work."""
    columns = _load_columns_for_table("LOAN_CD")
    header = "\t".join(columns)
    loan_date_index = columns.index("LOAN_DATE1")

    def _make_row(date_value: str) -> str:
        vals = ["val"] * len(columns)
        vals[loan_date_index] = date_value
        return "\t".join(vals)

    fixture = tmp_path / "LOAN_CD.TSV"
    _write_tsv(
        fixture,
        header,
        _make_row("05/20/2018"),  # before 2022 — filtered
        _make_row("09/01/2025"),  # after 2022 — kept
    )

    parser = parse_table(fixture, "LOAN_CD", year_from=2022)
    rows = list(parser)

    assert len(rows) == 1
    assert rows[0]["LOAN_DATE1"] == "09/01/2025"
    assert parser.filtered == 1


def test_parse_table_without_year_from_returns_all_rows(tmp_path: Path):
    """Without year_from, all rows should be returned (backward compatible)."""
    columns = _load_columns_for_table("RCPT_CD")
    header = "\t".join(columns)
    rcpt_date_index = columns.index("RCPT_DATE")

    def _make_row(date_value: str) -> str:
        vals = ["val"] * len(columns)
        vals[rcpt_date_index] = date_value
        return "\t".join(vals)

    fixture = tmp_path / "RCPT_CD.TSV"
    _write_tsv(
        fixture,
        header,
        _make_row("01/15/1999"),
        _make_row("06/15/2024"),
    )

    parser = parse_table(fixture, "RCPT_CD")
    rows = list(parser)

    assert len(rows) == 2
    assert parser.filtered == 0


def test_parse_table_year_from_with_non_transaction_table_ignores_filter(tmp_path: Path):
    """Non-transaction tables (like CVR_CAMPAIGN_DISCLOSURE_CD) have no transaction.date
    mapping, so year_from should be silently ignored (no date_column to filter on)."""
    columns = _load_columns_for_table("CVR_CAMPAIGN_DISCLOSURE_CD")
    header = "\t".join(columns)
    row = "\t".join(["val"] * len(columns))
    fixture = tmp_path / "CVR_CAMPAIGN_DISCLOSURE_CD.TSV"
    _write_tsv(fixture, header, row)

    # year_from on a non-transaction table: should not error, just return all rows
    parser = parse_table(fixture, "CVR_CAMPAIGN_DISCLOSURE_CD", year_from=2022)
    rows = list(parser)

    assert len(rows) == 1
    assert parser.filtered == 0


def test_filername_cd_parses_live_zip4_header_and_rejects_legacy_zip(tmp_path: Path):
    """Live FILERNAME_CD uses ZIP4; parser must not regress to stale ZIP header."""
    columns = _load_columns_for_table("FILERNAME_CD")
    assert "ZIP4" in columns
    assert "ZIP" not in columns

    live_header = (
        "XREF_FILER_ID",
        "FILER_TYPE",
        "NAML",
        "NAMF",
        "NAMT",
        "NAMS",
        "CITY",
        "ST",
        "ZIP4",
        "EFFECT_DT",
        "EXTRA_COL_FROM_LIVE_EXPORT",
    )
    row_by_column = {column: f"value_{index}" for index, column in enumerate(live_header)}
    fixture = tmp_path / "FILERNAME_CD.TSV"
    _write_tsv(
        fixture,
        "\t".join(live_header),
        "\t".join(row_by_column[column] for column in live_header),
    )

    parser = parse_table(fixture, "FILERNAME_CD")
    rows = list(parser)

    assert len(rows) == 1
    assert tuple(rows[0].keys()) == columns
    assert rows[0]["ZIP4"] == row_by_column["ZIP4"]
