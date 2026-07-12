from __future__ import annotations

from pathlib import Path
import zipfile

import pytest

from domains.campaign_finance.ingest import bulk_parser
from domains.campaign_finance.ingest.bulk_parser import (
    CCL_COLUMNS,
    CM_COLUMNS,
    CN_COLUMNS,
    COLUMNS_BY_FILE_TYPE,
    ITCONT_COLUMNS,
    ITPAS2_COLUMNS,
    WEBALL_COLUMNS,
    parse_pipe_delimited,
    read_bulk_file,
)
from domains.campaign_finance.ingest.field_mapper import parse_fec_date


_FIXTURE_DIR = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "bulk"
_ITCONT_STAGE3_MIN_DATE = "2022-01-01"
_ITCONT_STAGE3_ALLOWED_COMMITTEE_IDS = frozenset({"C00100001", "C00100002", "C00100003", "C00100005"})


def _itcont_rows_by_sub_id() -> dict[str, dict[str, str | None]]:
    rows = list(read_bulk_file(_FIXTURE_DIR / "itcont_sample.txt", "itcont"))
    return {row["SUB_ID"]: row for row in rows if row["SUB_ID"] is not None}


@pytest.mark.unit
def test_parse_pipe_delimited_maps_columns_and_converts_empty_to_none() -> None:
    rows = list(
        parse_pipe_delimited(
            [" A |B|| D \n", "\n", "E| F |G|H\r\n"],
            ("col_a", "col_b", "col_c", "col_d"),
        )
    )

    assert rows == [
        {"col_a": "A", "col_b": "B", "col_c": None, "col_d": "D"},
        {"col_a": "E", "col_b": "F", "col_c": "G", "col_d": "H"},
    ]


@pytest.mark.unit
def test_parse_pipe_delimited_trailing_pipe_and_invalid_row_logs_warning(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("WARNING")

    rows = list(
        parse_pipe_delimited(
            ["one|two|three|\n", "too|short\n"],
            ("a", "b", "c"),
        )
    )

    assert rows == [{"a": "one", "b": "two", "c": "three"}]
    assert "Skipping row 2" in caplog.text


@pytest.mark.unit
@pytest.mark.parametrize(
    ("file_type", "fixture_name"),
    [
        ("itcont", "itcont_sample.txt"),
        ("itpas2", "itpas2_sample.txt"),
        ("cm", "cm_sample.txt"),
        ("cn", "cn_sample.txt"),
        ("ccl", "ccl_sample.txt"),
        ("weball", "weball_sample.txt"),
    ],
)
def test_read_bulk_file_reads_text_fixtures(file_type: str, fixture_name: str) -> None:
    fixture_path = _FIXTURE_DIR / fixture_name

    rows = list(read_bulk_file(fixture_path, file_type))

    expected_row_count = 6 if file_type == "itcont" else 5
    assert len(rows) == expected_row_count
    assert tuple(rows[0].keys()) == COLUMNS_BY_FILE_TYPE[file_type]


@pytest.mark.unit
def test_read_bulk_file_itcont_stage3_filter_fixture_contract_rows() -> None:
    rows_by_sub_id = _itcont_rows_by_sub_id()

    assert set(rows_by_sub_id) == {
        "900000000000001",
        "900000000000002",
        "900000000000003",
        "900000000000004",
        "900000000000005",
        "900000000000006",
    }

    assert rows_by_sub_id["900000000000001"]["ENTITY_TP"] == "IND"
    assert rows_by_sub_id["900000000000001"]["MEMO_CD"] is None
    assert rows_by_sub_id["900000000000001"]["ZIP_CODE"] == "331010001"
    assert rows_by_sub_id["900000000000002"]["ENTITY_TP"] == "IND"
    assert rows_by_sub_id["900000000000002"]["MEMO_CD"] == "X"
    assert rows_by_sub_id["900000000000003"]["ENTITY_TP"] == "COM"
    assert rows_by_sub_id["900000000000003"]["OTHER_ID"] == "C00100004"
    assert rows_by_sub_id["900000000000005"]["TRANSACTION_TP"] == "22Y"
    assert rows_by_sub_id["900000000000005"]["TRANSACTION_AMT"] == "-45.00"
    assert rows_by_sub_id["900000000000006"]["TRANSACTION_DT"] == "12312021"


@pytest.mark.unit
def test_stage3_fixture_inclusion_mask_expected_sub_ids_by_committee_and_date() -> None:
    rows = list(read_bulk_file(_FIXTURE_DIR / "itcont_sample.txt", "itcont"))

    included_sub_ids = [
        row["SUB_ID"]
        for row in rows
        if row["CMTE_ID"] in _ITCONT_STAGE3_ALLOWED_COMMITTEE_IDS
        and (transaction_date := parse_fec_date(row["TRANSACTION_DT"])) is not None
        and transaction_date >= _ITCONT_STAGE3_MIN_DATE
    ]

    assert included_sub_ids == [
        "900000000000001",
        "900000000000002",
        "900000000000003",
        "900000000000005",
    ]


@pytest.mark.unit
def test_read_bulk_file_reads_matching_member_from_zip(tmp_path: Path) -> None:
    fixture_path = _FIXTURE_DIR / "itcont_sample.txt"
    zip_path = tmp_path / "indiv24.zip"

    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.write(fixture_path, arcname="itcont_sample.txt")

    text_rows = list(read_bulk_file(fixture_path, "itcont"))
    zip_rows = list(read_bulk_file(zip_path, "itcont"))

    assert zip_rows == text_rows


@pytest.mark.unit
@pytest.mark.parametrize("fixture_name", ["itcont_sample.txt", "indiv24.zip"])
def test_read_bulk_file_skips_persisted_source_row_cursor(tmp_path: Path, fixture_name: str) -> None:
    fixture_path = _FIXTURE_DIR / "itcont_sample.txt"
    input_path = fixture_path
    if fixture_name.endswith(".zip"):
        input_path = tmp_path / fixture_name
        with zipfile.ZipFile(input_path, "w") as archive:
            archive.write(fixture_path, arcname="nested/itcont_sample.txt")

    all_rows = list(read_bulk_file(input_path, "itcont"))
    resumed_rows = list(read_bulk_file(input_path, "itcont", next_source_row_number=3))

    assert [row["SUB_ID"] for row in resumed_rows] == [row["SUB_ID"] for row in all_rows[3:]]
    assert resumed_rows[0]["SUB_ID"] == "900000000000004"
    assert {row["SUB_ID"] for row in resumed_rows}.isdisjoint({row["SUB_ID"] for row in all_rows[:3]})


@pytest.mark.unit
def test_read_bulk_file_respects_limit_and_handles_latin1_name() -> None:
    fixture_path = _FIXTURE_DIR / "itcont_sample.txt"

    limited_rows = list(read_bulk_file(fixture_path, "itcont", limit=2))
    all_rows = list(read_bulk_file(fixture_path, "itcont"))

    assert len(limited_rows) == 2
    assert any((row["NAME"] or "").startswith("GARCÍA") for row in all_rows)


@pytest.mark.unit
def test_read_bulk_file_zero_limit_short_circuits_parser(monkeypatch: pytest.MonkeyPatch) -> None:
    fixture_path = _FIXTURE_DIR / "itcont_sample.txt"

    def _fail_if_called(*args: object, **kwargs: object) -> list[dict[str, str | None]]:
        raise AssertionError("parse_pipe_delimited should not be called for limit=0")

    monkeypatch.setattr(bulk_parser, "parse_pipe_delimited", _fail_if_called)

    rows = list(read_bulk_file(fixture_path, "itcont", limit=0))

    assert rows == []


@pytest.mark.unit
def test_column_count_constants_match_expected_fec_layout() -> None:
    assert len(ITCONT_COLUMNS) == 21
    assert len(ITPAS2_COLUMNS) == 22
    assert len(CM_COLUMNS) == 15
    assert len(CN_COLUMNS) == 15
    assert len(CCL_COLUMNS) == 7
    assert len(WEBALL_COLUMNS) == 30


@pytest.mark.unit
def test_weball_columns_map_official_summary_positions() -> None:
    row = next(read_bulk_file(_FIXTURE_DIR / "weball_sample.txt", "weball"))

    assert tuple(row.keys()) == WEBALL_COLUMNS
    assert WEBALL_COLUMNS[0] == "CAND_ID"
    assert WEBALL_COLUMNS[5] == "TTL_RECEIPTS"
    assert WEBALL_COLUMNS[7] == "TTL_DISB"
    assert WEBALL_COLUMNS[10] == "COH_COP"
    assert WEBALL_COLUMNS[27] == "CVG_END_DT"
    assert row["CAND_ID"] == "H0NC01001"
    assert row["TTL_RECEIPTS"] == "12345.67"
    assert row["TTL_DISB"] == "8910.11"
    assert row["COH_COP"] == "3535.56"
    assert row["CVG_END_DT"] == "12/31/2024"
