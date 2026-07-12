"""Tests for the FEC committee summary CSV parser."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from domains.campaign_finance.ingest.committee_summary_parser import (
    COMMITTEE_SUMMARY_COLUMNS,
    read_committee_summary_file,
)


FIXTURE_PATH = Path("tests/fixtures/bulk/committee_summary_2024.csv")


def _committee_summary_csv_row(overrides: dict[str, str] | None = None) -> str:
    values = [""] * len(COMMITTEE_SUMMARY_COLUMNS)
    values[COMMITTEE_SUMMARY_COLUMNS.index("CMTE_ID")] = "C00999999"
    values[COMMITTEE_SUMMARY_COLUMNS.index("CMTE_NM")] = "TEST COMMITTEE"
    values[COMMITTEE_SUMMARY_COLUMNS.index("FEC_ELECTION_YR")] = "2024"
    values[COMMITTEE_SUMMARY_COLUMNS.index("CVG_START_DT")] = "20240101"
    values[COMMITTEE_SUMMARY_COLUMNS.index("CVG_END_DT")] = "20241231"
    values[COMMITTEE_SUMMARY_COLUMNS.index("TTL_CONTB")] = "12.34"
    for column, value in (overrides or {}).items():
        values[COMMITTEE_SUMMARY_COLUMNS.index(column)] = value
    return ",".join(f'"{value}"' for value in values)


def _write_committee_summary_csv(path: Path, rows: list[str]) -> None:
    path.write_text(
        ",".join(COMMITTEE_SUMMARY_COLUMNS) + "\n" + "\n".join(rows) + "\n",
        encoding="utf-8",
    )


def test_parses_exact_values_from_real_header_fixture() -> None:
    rows = list(read_committee_summary_file(FIXTURE_PATH, limit=1))

    assert rows == [
        {
            "Link_Image": "https://www.fec.gov/data/committee/C00879676/?cycle=2024",
            "CMTE_ID": "C00879676",
            "CMTE_NM": "AMERICAN FREEDOM COALITION PAC",
            "CMTE_TP": "O",
            "CMTE_DSGN": "U",
            "CMTE_FILING_FREQ": "T",
            "CMTE_ST1": "1021 NORTH MARKET PLAZA",
            "CMTE_ST2": "STE 107",
            "CMTE_CITY": "PUEBLO WEST",
            "CMTE_ST": "CO",
            "CMTE_ZIP": "81007",
            "TRES_NM": "MCCAULEY, MIKE",
            "CAND_ID": None,
            "FEC_ELECTION_YR": "2024",
            "INDV_CONTB": Decimal("0"),
            "PTY_CMTE_CONTB": Decimal("0"),
            "OTH_CMTE_CONTB": Decimal("20000"),
            "TTL_CONTB": Decimal("20000"),
            "TRANF_FROM_OTHER_AUTH_CMTE": Decimal("0"),
            "OFFSETS_TO_OP_EXP": Decimal("0"),
            "OTHER_RECEIPTS": Decimal("0"),
            "TTL_RECEIPTS": Decimal("20000"),
            "TRANF_TO_OTHER_AUTH_CMTE": Decimal("0"),
            "OTH_LOAN_REPYMTS": Decimal("0"),
            "INDV_REF": Decimal("0"),
            "POL_PTY_CMTE_REF": Decimal("0"),
            "TTL_CONTB_REF": Decimal("0"),
            "OTHER_DISB": Decimal("0"),
            "TTL_DISB": Decimal("20000"),
            "NET_CONTB": Decimal("20000"),
            "NET_OP_EXP": Decimal("1500"),
            "COH_BOP": Decimal("0"),
            "CVG_START_DT": date(2024, 4, 1),
            "COH_COP": Decimal("0"),
            "CVG_END_DT": date(2024, 11, 25),
            "DEBTS_OWED_BY_CMTE": Decimal("0"),
            "DEBTS_OWED_TO_CMTE": Decimal("0"),
            "INDV_ITEM_CONTB": Decimal("0"),
            "INDV_UNITEM_CONTB": Decimal("0"),
            "OTH_LOANS": None,
            "TRANF_FROM_NONFED_ACCT": Decimal("0"),
            "TRANF_FROM_NONFED_LEVIN": Decimal("0"),
            "TTL_NONFED_TRANF": Decimal("0"),
            "LOAN_REPYMTS_RECEIVED": Decimal("0"),
            "OFFSETS_TO_FNDRSG": None,
            "OFFSETS_TO_LEGAL_ACCTG": None,
            "FED_CAND_CONTB_REF": Decimal("0"),
            "TTL_FED_RECEIPTS": Decimal("20000"),
            "SHARED_FED_OP_EXP": Decimal("0"),
            "SHARED_NONFED_OP_EXP": Decimal("0"),
            "OTHER_FED_OP_EXP": Decimal("1500"),
            "TTL_OP_EXP": Decimal("1500"),
            "FED_CAND_CMTE_CONTB": Decimal("0"),
            "INDT_EXP": Decimal("18500"),
            "COORD_EXP_BY_PTY_CMTE": Decimal("0"),
            "LOANS_MADE": Decimal("0"),
            "SHARED_FED_ACTVY_FED_SHR": Decimal("0"),
            "SHARED_FED_ACTVY_NONFED": Decimal("0"),
            "NON_ALLOC_FED_ELECT_ACTVY": Decimal("0"),
            "TTL_FED_ELECT_ACTVY": Decimal("0"),
            "TTL_FED_DISB": Decimal("20000"),
            "CAND_CNTB": None,
            "CAND_LOAN": None,
            "TTL_LOANS": Decimal("0"),
            "OP_EXP": None,
            "CAND_LOAN_REPYMNT": None,
            "TTL_LOAN_REPYMTS": None,
            "OTH_CMTE_REF": Decimal("0"),
            "TTL_OFFSETS_TO_OP_EXP": None,
            "EXEMPT_LEGAL_ACCTG_DISB": None,
            "FNDRSG_DISB": None,
            "ITEM_REF_REB_RET": None,
            "SUBTTL_REF_REB_RET": None,
            "UNITEM_REF_REB_RET": None,
            "ITEM_OTHER_REF_REB_RET": None,
            "UNITEM_OTHER_REF_REB_RET": None,
            "SUBTTL_OTHER_REF_REB_RET": None,
            "ITEM_OTHER_INCOME": None,
            "UNITEM_OTHER_INCOME": None,
            "EXP_PRIOR_YRS_SUBJECT_LIM": None,
            "EXP_SUBJECT_LIMITS": None,
            "FED_FUNDS": None,
            "ITEM_CONVN_EXP_DISB": None,
            "ITEM_OTHER_DISB": None,
            "SUBTTL_CONVN_EXP_DISB": None,
            "TTL_EXP_SUBJECT_LIMITS": None,
            "UNITEM_CONVN_EXP_DISB": None,
            "UNITEM_OTHER_DISB": None,
            "TTL_COMMUNICATION_COST": None,
            "COH_BOY": None,
            "COH_COY": None,
            "ORG_TP": None,
        }
    ]


def test_rejects_wrong_header_names(tmp_path: Path) -> None:
    bad_csv = tmp_path / "bad.csv"
    bad_csv.write_text("wrong_col1,wrong_col2\n1,2\n", encoding="utf-8")

    with pytest.raises(ValueError, match="header mismatch"):
        list(read_committee_summary_file(bad_csv))


def test_rejects_reordered_headers(tmp_path: Path) -> None:
    bad_csv = tmp_path / "reordered.csv"
    bad_csv.write_text(",".join(reversed(COMMITTEE_SUMMARY_COLUMNS)) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="wrong order"):
        list(read_committee_summary_file(bad_csv))


def test_empty_strings_normalize_to_none() -> None:
    rows = list(read_committee_summary_file(FIXTURE_PATH, limit=2))

    assert rows[0]["CAND_ID"] is None
    assert rows[0]["OTH_LOANS"] is None
    assert rows[1]["CMTE_ST2"] is None


def test_malformed_rows_are_skipped(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("WARNING")
    header = ",".join(COMMITTEE_SUMMARY_COLUMNS)
    good_row = _committee_summary_csv_row()
    extra_field_row = ",".join(f'"{index}"' for index in range(len(COMMITTEE_SUMMARY_COLUMNS) + 1))
    missing_field_row = ",".join(f'"{index}"' for index in range(len(COMMITTEE_SUMMARY_COLUMNS) - 1))
    csv_file = tmp_path / "malformed.csv"
    csv_file.write_text(
        f"{header}\n{good_row}\n{extra_field_row}\n{missing_field_row}\n{good_row}\n",
        encoding="utf-8",
    )

    rows = list(read_committee_summary_file(csv_file))

    assert len(rows) == 2
    assert "Skipping row 3" in caplog.text
    assert "Skipping row 4" in caplog.text


def test_utf8_text_is_preserved(tmp_path: Path) -> None:
    header = ",".join(COMMITTEE_SUMMARY_COLUMNS)
    values = [""] * len(COMMITTEE_SUMMARY_COLUMNS)
    values[COMMITTEE_SUMMARY_COLUMNS.index("CMTE_ID")] = "C00999999"
    values[COMMITTEE_SUMMARY_COLUMNS.index("CMTE_NM")] = "GARCIA Y NIÑOS PAC"
    values[COMMITTEE_SUMMARY_COLUMNS.index("FEC_ELECTION_YR")] = "2024"
    csv_file = tmp_path / "utf8.csv"
    csv_file.write_text(header + "\n" + ",".join(f'"{value}"' for value in values) + "\n", encoding="utf-8")

    rows = list(read_committee_summary_file(csv_file))

    assert rows[0]["CMTE_NM"] == "GARCIA Y NIÑOS PAC"


def test_limit_counts_yielded_valid_rows_after_skipping_malformed_rows(tmp_path: Path) -> None:
    header = ",".join(COMMITTEE_SUMMARY_COLUMNS)
    good_row = _committee_summary_csv_row()
    extra_field_row = ",".join(f'"{index}"' for index in range(len(COMMITTEE_SUMMARY_COLUMNS) + 1))
    csv_file = tmp_path / "limit.csv"
    csv_file.write_text(
        f"{header}\n{good_row}\n{extra_field_row}\n{good_row}\n{good_row}\n",
        encoding="utf-8",
    )

    rows = list(read_committee_summary_file(csv_file, limit=2))

    assert len(rows) == 2
    assert rows[0]["CMTE_ID"] == "C00999999"
    assert rows[1]["CMTE_ID"] == "C00999999"


def test_invalid_non_empty_amount_cell_skips_row(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("WARNING")
    csv_file = tmp_path / "invalid_amount.csv"
    _write_committee_summary_csv(
        csv_file,
        [
            _committee_summary_csv_row({"CMTE_ID": "C00000001", "TTL_CONTB": "not-a-number"}),
            _committee_summary_csv_row({"CMTE_ID": "C00000002", "TTL_CONTB": "15.50"}),
        ],
    )

    rows = list(read_committee_summary_file(csv_file))

    assert [row["CMTE_ID"] for row in rows] == ["C00000002"]
    assert rows[0]["TTL_CONTB"] == Decimal("15.50")
    assert "Skipping row 2" in caplog.text
    assert "TTL_CONTB" in caplog.text
    assert "not-a-number" in caplog.text


@pytest.mark.parametrize("bad_amount", ["NaN", "sNaN", "Infinity"])
def test_non_finite_amount_cell_skips_row(bad_amount: str, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("WARNING")
    csv_file = tmp_path / "non_finite_amount.csv"
    _write_committee_summary_csv(
        csv_file,
        [
            _committee_summary_csv_row({"CMTE_ID": "C00000001", "TTL_CONTB": bad_amount}),
            _committee_summary_csv_row({"CMTE_ID": "C00000002", "TTL_CONTB": "15.50"}),
        ],
    )

    rows = list(read_committee_summary_file(csv_file))

    assert [row["CMTE_ID"] for row in rows] == ["C00000002"]
    assert rows[0]["TTL_CONTB"] == Decimal("15.50")
    assert "Skipping row 2" in caplog.text
    assert "TTL_CONTB" in caplog.text
    assert bad_amount in caplog.text


def test_invalid_non_empty_date_cell_skips_row(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("WARNING")
    csv_file = tmp_path / "invalid_date.csv"
    _write_committee_summary_csv(
        csv_file,
        [
            _committee_summary_csv_row({"CMTE_ID": "C00000001", "CVG_START_DT": "20241301"}),
            _committee_summary_csv_row({"CMTE_ID": "C00000002", "CVG_START_DT": "20240101"}),
        ],
    )

    rows = list(read_committee_summary_file(csv_file))

    assert [row["CMTE_ID"] for row in rows] == ["C00000002"]
    assert rows[0]["CVG_START_DT"] == date(2024, 1, 1)
    assert "Skipping row 2" in caplog.text
    assert "CVG_START_DT" in caplog.text
    assert "20241301" in caplog.text


def test_short_yyyymmdd_date_cell_skips_row(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("WARNING")
    csv_file = tmp_path / "short_date.csv"
    _write_committee_summary_csv(
        csv_file,
        [
            _committee_summary_csv_row({"CMTE_ID": "C00000001", "CVG_START_DT": "2024011"}),
            _committee_summary_csv_row({"CMTE_ID": "C00000002", "CVG_START_DT": "20240101"}),
        ],
    )

    rows = list(read_committee_summary_file(csv_file))

    assert [row["CMTE_ID"] for row in rows] == ["C00000002"]
    assert rows[0]["CVG_START_DT"] == date(2024, 1, 1)
    assert "Skipping row 2" in caplog.text
    assert "CVG_START_DT" in caplog.text
    assert "2024011" in caplog.text


def test_limit_zero_returns_empty() -> None:
    assert list(read_committee_summary_file(FIXTURE_PATH, limit=0)) == []


def test_negative_limit_raises() -> None:
    with pytest.raises(ValueError, match="limit must be >= 0"):
        list(read_committee_summary_file(FIXTURE_PATH, limit=-1))
