"""Red contract tests for FEC Schedule B (operating expenditures / oppexp.txt).

These tests lock the source contract before implementation. They import symbols
that do not yet exist in the codebase — each test is structured so that a missing
symbol produces a targeted failure (ImportError or AttributeError) rather than a
single collection-time crash.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

EXPECTED_COLUMNS = (
    "CMTE_ID",
    "AMNDT_IND",
    "RPT_YR",
    "RPT_TP",
    "IMAGE_NUM",
    "LINE_NUM",
    "FORM_TP_CD",
    "SCHED_TP_CD",
    "NAME",
    "CITY",
    "STATE",
    "ZIP_CODE",
    "TRANSACTION_DT",
    "TRANSACTION_AMT",
    "TRANSACTION_PGI",
    "PURPOSE",
    "CATEGORY",
    "CATEGORY_DESC",
    "MEMO_CD",
    "MEMO_TEXT",
    "ENTITY_TP",
    "SUB_ID",
    "FILE_NUM",
    "TRAN_ID",
    "BACK_REF_TRAN_ID",
)


# ---------------------------------------------------------------------------
# Helpers — lazy imports to keep each test's failure isolated
# ---------------------------------------------------------------------------


def _import_schedule_b_parser():
    from domains.campaign_finance.ingest import schedule_b_parser

    return schedule_b_parser


def _import_bulk_cli():
    from domains.campaign_finance.ingest import bulk_cli

    return bulk_cli


# ---------------------------------------------------------------------------
# Parser symbol contract tests
# ---------------------------------------------------------------------------


class TestScheduleBParserSymbols:
    def test_schedule_b_columns_exists(self):
        parser = _import_schedule_b_parser()
        assert hasattr(parser, "SCHEDULE_B_COLUMNS")

    def test_schedule_b_columns_matches_official_order(self):
        parser = _import_schedule_b_parser()
        assert parser.SCHEDULE_B_COLUMNS == EXPECTED_COLUMNS

    def test_schedule_b_columns_has_25_fields(self):
        parser = _import_schedule_b_parser()
        assert len(parser.SCHEDULE_B_COLUMNS) == 25

    def test_read_schedule_b_file_exists(self):
        parser = _import_schedule_b_parser()
        assert callable(getattr(parser, "read_schedule_b_file", None))

    def test_map_schedule_b_fields_exists(self):
        parser = _import_schedule_b_parser()
        assert callable(getattr(parser, "map_schedule_b_fields", None))


# ---------------------------------------------------------------------------
# URL contract tests
# ---------------------------------------------------------------------------


class TestScheduleBUrl:
    def test_fec_schedule_b_url_2024(self):
        cli = _import_bulk_cli()
        assert cli.fec_schedule_b_url(2024) == ("https://www.fec.gov/files/bulk-downloads/2024/oppexp24.zip")

    def test_fec_schedule_b_url_2026(self):
        cli = _import_bulk_cli()
        assert cli.fec_schedule_b_url(2026) == ("https://www.fec.gov/files/bulk-downloads/2026/oppexp26.zip")


# ---------------------------------------------------------------------------
# Registry contract tests
# ---------------------------------------------------------------------------


class TestScheduleBRegistry:
    def test_schedule_b_in_file_types(self):
        cli = _import_bulk_cli()
        assert "schedule_b" in cli.FILE_TYPES

    def test_schedule_b_loader_spec_requires_cycle(self):
        cli = _import_bulk_cli()
        spec = cli.FILE_TYPE_LOADERS["schedule_b"]
        assert spec.requires_cycle is True

    def test_schedule_b_loader_spec_supports_graph(self):
        cli = _import_bulk_cli()
        spec = cli.FILE_TYPE_LOADERS["schedule_b"]
        assert spec.supports_graph is True


# ---------------------------------------------------------------------------
# Parser contract test — one-row pipe-delimited sample
# ---------------------------------------------------------------------------

SAMPLE_ROW = (
    "|".join(
        [
            "C00401224",  # CMTE_ID
            "N",  # AMNDT_IND
            "2024",  # RPT_YR
            "Q3",  # RPT_TP
            "202410159712345",  # IMAGE_NUM
            "21B",  # LINE_NUM
            "F3X",  # FORM_TP_CD
            "SB",  # SCHED_TP_CD
            "ACME CONSULTING LLC",  # NAME
            "WASHINGTON",  # CITY
            "DC",  # STATE
            "20001",  # ZIP_CODE
            "09152024",  # TRANSACTION_DT
            "5000.00",  # TRANSACTION_AMT
            "G2024",  # TRANSACTION_PGI
            "CONSULTING FEES",  # PURPOSE
            "006",  # CATEGORY
            "OTHER",  # CATEGORY_DESC
            "",  # MEMO_CD (empty)
            " ",  # MEMO_TEXT (whitespace-only)
            "ORG",  # ENTITY_TP
            "4091520241234567890",  # SUB_ID
            "1234567",  # FILE_NUM
            "SB21B.1234",  # TRAN_ID
            "SA11AI.5678",  # BACK_REF_TRAN_ID
        ]
    )
    + "\n"
)


@pytest.fixture()
def sample_oppexp_file(tmp_path):
    """Write SAMPLE_ROW to a temporary oppexp-format file and yield its path."""
    path = tmp_path / "oppexp_sample.txt"
    path.write_text(SAMPLE_ROW, encoding="latin-1")
    return path


class TestScheduleBParserContract:
    def test_read_schedule_b_file_basic_parsing(self, sample_oppexp_file):
        parser = _import_schedule_b_parser()
        rows = list(parser.read_schedule_b_file(sample_oppexp_file))
        assert len(rows) == 1
        row = rows[0]
        assert row["CMTE_ID"] == "C00401224"
        assert row["NAME"] == "ACME CONSULTING LLC"
        assert row["STATE"] == "DC"

    def test_read_schedule_b_file_empty_fields_are_none(self, sample_oppexp_file):
        parser = _import_schedule_b_parser()
        rows = list(parser.read_schedule_b_file(sample_oppexp_file))
        row = rows[0]
        assert row["MEMO_CD"] is None
        assert row["MEMO_TEXT"] is None

    def test_read_schedule_b_file_preserves_field_order(self, sample_oppexp_file):
        parser = _import_schedule_b_parser()
        rows = list(parser.read_schedule_b_file(sample_oppexp_file))
        assert tuple(rows[0].keys()) == EXPECTED_COLUMNS

    def test_map_schedule_b_fields_typed_values(self, sample_oppexp_file):
        parser = _import_schedule_b_parser()
        rows = list(parser.read_schedule_b_file(sample_oppexp_file))
        mapped = parser.map_schedule_b_fields(rows[0])
        assert mapped["transaction_date"].month == 9
        assert mapped["transaction_date"].day == 15
        assert mapped["transaction_date"].year == 2024
        assert mapped["transaction_amount"] == Decimal("5000.00")
        assert mapped["memo_code"] is None
        assert mapped["memo_text"] is None
        assert mapped["entity_type"] == "ORG"
        assert mapped["transaction_identifier"] == "SB21B.1234"
        assert mapped["back_ref_transaction_id"] == "SA11AI.5678"


class TestScheduleBDateParsing:
    def test_mmddyyyy_no_separators(self):
        parser = _import_schedule_b_parser()
        assert parser._parse_schedule_b_date("09152024") == date(2024, 9, 15)

    def test_mm_dd_yyyy_with_slashes(self):
        parser = _import_schedule_b_parser()
        assert parser._parse_schedule_b_date("09/15/2024") == date(2024, 9, 15)

    def test_empty_string_returns_none(self):
        parser = _import_schedule_b_parser()
        assert parser._parse_schedule_b_date("") is None

    def test_none_returns_none(self):
        parser = _import_schedule_b_parser()
        assert parser._parse_schedule_b_date(None) is None

    def test_all_zeros_returns_none(self):
        parser = _import_schedule_b_parser()
        assert parser._parse_schedule_b_date("00000000") is None

    def test_malformed_returns_none(self):
        parser = _import_schedule_b_parser()
        assert parser._parse_schedule_b_date("not-a-date") is None


# ---------------------------------------------------------------------------
# Documentation hygiene — research doc must match code constant
# ---------------------------------------------------------------------------


class TestDocumentationHygiene:
    def test_research_doc_oppexp_fields_match_schedule_b_columns(self):
        bulk_data_doc = (REPO_ROOT / "docs" / "reference" / "research" / "fec-bulk-data.md").read_text(encoding="utf-8")

        in_oppexp_section = False
        doc_fields: list[str] = []
        field_row_pattern = re.compile(r"^\|\s*\d+\s*\|\s*(\w+)\s*\|")

        for line in bulk_data_doc.splitlines():
            if line.startswith("### oppexp.txt"):
                in_oppexp_section = True
                continue
            if in_oppexp_section and line.startswith("### "):
                break
            if in_oppexp_section:
                match = field_row_pattern.match(line)
                if match:
                    doc_fields.append(match.group(1))

        assert len(doc_fields) == 25, f"Expected 25 fields in oppexp.txt doc section, found {len(doc_fields)}"

        parser = _import_schedule_b_parser()
        assert tuple(doc_fields) == parser.SCHEDULE_B_COLUMNS, (
            "oppexp.txt field names in docs/reference/research/fec-bulk-data.md must exactly "
            "match SCHEDULE_B_COLUMNS in schedule_b_parser.py"
        )
