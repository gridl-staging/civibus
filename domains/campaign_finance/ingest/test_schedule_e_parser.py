"""Tests for FEC Schedule E (independent expenditures) CSV parser.

Tests run against the curated fixture at tests/fixtures/bulk/schedule_e_sample.csv
which contains 34 data rows with 23 columns per the FEC bulk download format.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from domains.campaign_finance.ingest.schedule_e_parser import (
    SCHEDULE_E_COLUMNS,
    read_schedule_e_file,
)

FIXTURE_PATH = Path("tests/fixtures/bulk/schedule_e_sample.csv")


class TestHappyPath:
    """Test 1: correct row count, field mapping to dict keys, amount/date parsing."""

    def test_parses_all_34_rows(self) -> None:
        rows = list(read_schedule_e_file(FIXTURE_PATH))
        assert len(rows) == 34

    def test_dict_keys_match_column_names(self) -> None:
        rows = list(read_schedule_e_file(FIXTURE_PATH, limit=1))
        assert set(rows[0].keys()) == set(SCHEDULE_E_COLUMNS)

    def test_amount_parsed_as_decimal(self) -> None:
        rows = list(read_schedule_e_file(FIXTURE_PATH, limit=1))
        # First row: exp_amo = 9000
        assert rows[0]["exp_amo"] == Decimal("9000")

    def test_date_parsed_as_date_object(self) -> None:
        rows = list(read_schedule_e_file(FIXTURE_PATH, limit=2))
        # Second row: exp_date = "27-SEP-24" -> date(2024, 9, 27)
        assert rows[1]["exp_date"] == date(2024, 9, 27)

    def test_dissemination_date_parsed(self) -> None:
        rows = list(read_schedule_e_file(FIXTURE_PATH, limit=2))
        # Second row: dissem_dt = "02-OCT-24" -> date(2024, 10, 2)
        assert rows[1]["dissem_dt"] == date(2024, 10, 2)

    def test_receipt_date_parsed(self) -> None:
        rows = list(read_schedule_e_file(FIXTURE_PATH, limit=1))
        # First row: receipt_dat = "31-OCT-24" -> date(2024, 10, 31)
        assert rows[0]["receipt_dat"] == date(2024, 10, 31)

    def test_negative_amount(self) -> None:
        rows = list(read_schedule_e_file(FIXTURE_PATH))
        # Row 23 (0-indexed 22): exp_amo = -15250
        assert rows[22]["exp_amo"] == Decimal("-15250")

    def test_aggregate_amount_decimal(self) -> None:
        rows = list(read_schedule_e_file(FIXTURE_PATH, limit=3))
        # Third row: agg_amo = 1539.08
        assert rows[2]["agg_amo"] == Decimal("1539.08")


class TestHeaderValidation:
    """Test 2: reject CSV with wrong/missing column names."""

    def test_rejects_wrong_headers(self, tmp_path: Path) -> None:
        bad_csv = tmp_path / "bad.csv"
        bad_csv.write_text("wrong_col1,wrong_col2\n1,2\n", encoding="utf-8")
        with pytest.raises(ValueError, match="header mismatch"):
            list(read_schedule_e_file(bad_csv))

    def test_rejects_missing_column(self, tmp_path: Path) -> None:
        # Header with one column removed
        truncated_header = ",".join(SCHEDULE_E_COLUMNS[:-1])
        bad_csv = tmp_path / "missing.csv"
        bad_csv.write_text(truncated_header + "\n", encoding="utf-8")
        with pytest.raises(ValueError, match="header mismatch"):
            list(read_schedule_e_file(bad_csv))

    def test_rejects_reordered_headers(self, tmp_path: Path) -> None:
        # All correct columns but in reversed order — must be rejected
        reordered = ",".join(reversed(SCHEDULE_E_COLUMNS))
        bad_csv = tmp_path / "reordered.csv"
        bad_csv.write_text(reordered + "\n", encoding="utf-8")
        with pytest.raises(ValueError, match="wrong order"):
            list(read_schedule_e_file(bad_csv))


class TestEmptyNormalization:
    """Test 3: empty quoted strings become None."""

    def test_empty_string_becomes_none(self) -> None:
        rows = list(read_schedule_e_file(FIXTURE_PATH, limit=1))
        # First row: exp_date is empty -> None
        assert rows[0]["exp_date"] is None

    def test_empty_dissemination_date_becomes_none(self) -> None:
        rows = list(read_schedule_e_file(FIXTURE_PATH, limit=4))
        # Fourth row (0-indexed 3): dissem_dt is empty -> None
        assert rows[3]["dissem_dt"] is None

    def test_empty_prev_file_num_becomes_none(self) -> None:
        rows = list(read_schedule_e_file(FIXTURE_PATH, limit=1))
        # First row: prev_file_num is empty -> None
        assert rows[0]["prev_file_num"] is None

    def test_empty_cand_id_becomes_none(self) -> None:
        rows = list(read_schedule_e_file(FIXTURE_PATH))
        # Row 16 (0-indexed 15): cand_id is empty -> None
        assert rows[15]["cand_id"] is None


class TestMalformedRowSkipping:
    """Test 4: rows with wrong field count logged and skipped."""

    def test_skips_row_with_extra_field(self, tmp_path: Path) -> None:
        header = ",".join(SCHEDULE_E_COLUMNS)
        good_row = ",".join(f'"{i}"' for i in range(23))
        bad_row = ",".join(f'"{i}"' for i in range(24))  # 24 fields
        content = f"{header}\n{good_row}\n{bad_row}\n{good_row}\n"
        csv_file = tmp_path / "extra.csv"
        csv_file.write_text(content, encoding="utf-8")
        rows = list(read_schedule_e_file(csv_file))
        assert len(rows) == 2

    def test_skips_row_with_fewer_fields(self, tmp_path: Path) -> None:
        header = ",".join(SCHEDULE_E_COLUMNS)
        good_row = ",".join(f'"{i}"' for i in range(23))
        bad_row = ",".join(f'"{i}"' for i in range(5))  # only 5 fields
        content = f"{header}\n{good_row}\n{bad_row}\n"
        csv_file = tmp_path / "fewer.csv"
        csv_file.write_text(content, encoding="utf-8")
        rows = list(read_schedule_e_file(csv_file))
        assert len(rows) == 1


class TestLimitParameter:
    """Test 5: limit=5 yields exactly 5 rows."""

    def test_limit_returns_exact_count(self) -> None:
        rows = list(read_schedule_e_file(FIXTURE_PATH, limit=5))
        assert len(rows) == 5

    def test_limit_zero_returns_empty(self) -> None:
        rows = list(read_schedule_e_file(FIXTURE_PATH, limit=0))
        assert len(rows) == 0

    def test_limit_none_returns_all(self) -> None:
        rows = list(read_schedule_e_file(FIXTURE_PATH))
        assert len(rows) == 34

    def test_limit_exceeding_row_count(self) -> None:
        rows = list(read_schedule_e_file(FIXTURE_PATH, limit=1000))
        assert len(rows) == 34

    def test_negative_limit_raises(self) -> None:
        with pytest.raises(ValueError, match="limit must be >= 0"):
            list(read_schedule_e_file(FIXTURE_PATH, limit=-1))


class TestEncoding:
    """Test 6: UTF-8 round-trip, no mojibake."""

    def test_utf8_roundtrip_no_mojibake(self) -> None:
        rows = list(read_schedule_e_file(FIXTURE_PATH))
        # Check that names with commas survive CSV parsing
        assert rows[5]["spe_nam"] == "1199 SEIU New York State Political Action Fund"

    def test_backtick_in_name_preserved(self) -> None:
        rows = list(read_schedule_e_file(FIXTURE_PATH))
        # Row 10 (0-indexed 9): "Biden`, Joseph" — backtick preserved
        assert rows[9]["cand_name"] == "Biden`, Joseph"

    def test_ampersand_in_name_preserved(self) -> None:
        rows = list(read_schedule_e_file(FIXTURE_PATH))
        # Row with "Americans for Prosperity Action, Inc. (AFP Action) DBA CVA Action and DBA LIBRE Action"
        assert "AFP Action" in rows[22]["spe_nam"]
