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
    parse_pipe_delimited,
    read_bulk_file,
)


_FIXTURE_DIR = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "bulk"


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
    ],
)
def test_read_bulk_file_reads_text_fixtures(file_type: str, fixture_name: str) -> None:
    fixture_path = _FIXTURE_DIR / fixture_name

    rows = list(read_bulk_file(fixture_path, file_type))

    assert len(rows) == 5
    assert tuple(rows[0].keys()) == COLUMNS_BY_FILE_TYPE[file_type]


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
