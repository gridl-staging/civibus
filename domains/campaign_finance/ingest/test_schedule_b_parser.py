"""Focused unit tests for schedule_b_parser.py.

Tests cover: 5-year date filter, memo code preservation, back_ref normalization,
limit parameter, malformed date handling, and negative amounts.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import patch

from domains.campaign_finance.ingest.schedule_b_parser import (
    SCHEDULE_B_COLUMNS,
    _parse_schedule_b_amount,
    _parse_schedule_b_date,
    map_schedule_b_fields,
    read_schedule_b_file,
)


def _make_row(overrides: dict[str, str] | None = None) -> str:
    """Build a pipe-delimited oppexp row string with sensible defaults."""
    defaults = {
        "CMTE_ID": "C00000001",
        "AMNDT_IND": "N",
        "RPT_YR": "2024",
        "RPT_TP": "Q3",
        "IMAGE_NUM": "202410159712345",
        "LINE_NUM": "21B",
        "FORM_TP_CD": "F3X",
        "SCHED_TP_CD": "SB",
        "NAME": "TEST VENDOR",
        "CITY": "ANYTOWN",
        "STATE": "VA",
        "ZIP_CODE": "22030",
        "TRANSACTION_DT": "06152024",
        "TRANSACTION_AMT": "1000.00",
        "TRANSACTION_PGI": "G2024",
        "PURPOSE": "SUPPLIES",
        "CATEGORY": "006",
        "CATEGORY_DESC": "OTHER",
        "MEMO_CD": "",
        "MEMO_TEXT": "",
        "ENTITY_TP": "ORG",
        "SUB_ID": "1234567890",
        "FILE_NUM": "1234567",
        "TRAN_ID": "SB21B.0001",
        "BACK_REF_TRAN_ID": "",
    }
    if overrides:
        defaults.update(overrides)
    return "|".join(defaults[col] for col in SCHEDULE_B_COLUMNS) + "\n"


def _write_rows(tmp_path, rows: list[str], filename: str = "oppexp.txt") -> str:
    """Write rows to a temp file and return its path."""
    path = tmp_path / filename
    path.write_text("".join(rows), encoding="latin-1")
    return str(path)


class TestFiveYearDateFilter:
    """Rows with provably-old transaction dates are excluded; recent/empty pass through."""

    @patch("domains.campaign_finance.ingest.schedule_b_parser._cutoff_date")
    def test_old_rows_excluded(self, mock_cutoff, tmp_path):
        mock_cutoff.return_value = date(2022, 1, 1)
        old_row = _make_row({"TRANSACTION_DT": "01152020"})
        recent_row = _make_row({"TRANSACTION_DT": "06152024"})
        path = _write_rows(tmp_path, [old_row, recent_row])

        result = list(read_schedule_b_file(path))
        assert len(result) == 1
        assert result[0]["TRANSACTION_DT"] == "06152024"

    @patch("domains.campaign_finance.ingest.schedule_b_parser._cutoff_date")
    def test_empty_date_passes_through(self, mock_cutoff, tmp_path):
        mock_cutoff.return_value = date(2022, 1, 1)
        row = _make_row({"TRANSACTION_DT": ""})
        path = _write_rows(tmp_path, [row])

        result = list(read_schedule_b_file(path))
        assert len(result) == 1

    @patch("domains.campaign_finance.ingest.schedule_b_parser._cutoff_date")
    def test_malformed_date_passes_through(self, mock_cutoff, tmp_path):
        mock_cutoff.return_value = date(2022, 1, 1)
        row = _make_row({"TRANSACTION_DT": "NOTADATE"})
        path = _write_rows(tmp_path, [row])

        result = list(read_schedule_b_file(path))
        assert len(result) == 1

    @patch("domains.campaign_finance.ingest.schedule_b_parser._cutoff_date")
    def test_uses_shared_date_helper(self, mock_cutoff, tmp_path):
        """Verify read_schedule_b_file and map_schedule_b_fields share _parse_schedule_b_date."""
        mock_cutoff.return_value = date(2022, 1, 1)
        row_text = _make_row({"TRANSACTION_DT": "03252024"})
        path = _write_rows(tmp_path, [row_text])

        rows = list(read_schedule_b_file(path))
        assert len(rows) == 1
        mapped = map_schedule_b_fields(rows[0])
        assert mapped["transaction_date"] == date(2024, 3, 25)


class TestMemoCdPreservation:
    """MEMO_CD='X' rows must not be filtered out."""

    @patch("domains.campaign_finance.ingest.schedule_b_parser._cutoff_date")
    def test_memo_x_rows_preserved(self, mock_cutoff, tmp_path):
        mock_cutoff.return_value = date(2022, 1, 1)
        row = _make_row({"MEMO_CD": "X", "TRANSACTION_DT": "06152024"})
        path = _write_rows(tmp_path, [row])

        result = list(read_schedule_b_file(path))
        assert len(result) == 1
        assert result[0]["MEMO_CD"] == "X"


class TestBackRefNormalization:
    """Empty BACK_REF_TRAN_ID → None in mapped output."""

    def test_empty_back_ref_is_none(self, tmp_path):
        row = _make_row({"BACK_REF_TRAN_ID": ""})
        path = _write_rows(tmp_path, [row])

        rows = list(read_schedule_b_file(path))
        mapped = map_schedule_b_fields(rows[0])
        assert mapped["back_ref_transaction_id"] is None

    def test_populated_back_ref_preserved(self, tmp_path):
        row = _make_row({"BACK_REF_TRAN_ID": "SA11AI.5678"})
        path = _write_rows(tmp_path, [row])

        rows = list(read_schedule_b_file(path))
        mapped = map_schedule_b_fields(rows[0])
        assert mapped["back_ref_transaction_id"] == "SA11AI.5678"


class TestLimitParameter:
    """The limit parameter caps the number of returned rows."""

    def test_limit_caps_rows(self, tmp_path):
        rows = [_make_row({"TRAN_ID": f"SB.{i}"}) for i in range(10)]
        path = _write_rows(tmp_path, rows)

        result = list(read_schedule_b_file(path, limit=3))
        assert len(result) == 3

    def test_limit_none_returns_all(self, tmp_path):
        rows = [_make_row({"TRAN_ID": f"SB.{i}"}) for i in range(5)]
        path = _write_rows(tmp_path, rows)

        result = list(read_schedule_b_file(path))
        assert len(result) == 5


class TestMalformedDate:
    """Malformed TRANSACTION_DT → None in mapped output, not a crash."""

    def test_malformed_date_maps_to_none(self, tmp_path):
        row = _make_row({"TRANSACTION_DT": "99XX2024"})
        path = _write_rows(tmp_path, [row])

        rows = list(read_schedule_b_file(path))
        mapped = map_schedule_b_fields(rows[0])
        assert mapped["transaction_date"] is None

    def test_zeroed_date_maps_to_none(self):
        assert _parse_schedule_b_date("00000000") is None

    def test_empty_date_maps_to_none(self):
        assert _parse_schedule_b_date("") is None
        assert _parse_schedule_b_date(None) is None


class TestNegativeAmount:
    """Negative TRANSACTION_AMT → negative Decimal."""

    def test_negative_amount(self):
        assert _parse_schedule_b_amount("-1500.50") == Decimal("-1500.50")

    def test_negative_amount_in_mapped_output(self, tmp_path):
        row = _make_row({"TRANSACTION_AMT": "-2500.00"})
        path = _write_rows(tmp_path, [row])

        rows = list(read_schedule_b_file(path))
        mapped = map_schedule_b_fields(rows[0])
        assert mapped["transaction_amount"] == Decimal("-2500.00")

    def test_empty_amount_maps_to_none(self):
        assert _parse_schedule_b_amount("") is None
        assert _parse_schedule_b_amount(None) is None
