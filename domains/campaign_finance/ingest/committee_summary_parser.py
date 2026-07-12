"""Streaming CSV parser for FEC committee summary bulk files.

Committee summary CSVs are comma-delimited UTF-8 files with a header row. They
are a separate headered format from the pipe-delimited legacy bulk files parsed
by bulk_parser.py.

Returns typed values: dates as datetime.date, amounts as Decimal, empty strings
as None. Candidate and cycle identifiers are passed through as strings so later
loader stages own relationship resolution and cycle dispatch.
"""

from __future__ import annotations

import csv
from collections.abc import Iterator
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import logging
from pathlib import Path
from typing import Any


LOGGER = logging.getLogger(__name__)

COMMITTEE_SUMMARY_COLUMNS: tuple[str, ...] = (
    "Link_Image",
    "CMTE_ID",
    "CMTE_NM",
    "CMTE_TP",
    "CMTE_DSGN",
    "CMTE_FILING_FREQ",
    "CMTE_ST1",
    "CMTE_ST2",
    "CMTE_CITY",
    "CMTE_ST",
    "CMTE_ZIP",
    "TRES_NM",
    "CAND_ID",
    "FEC_ELECTION_YR",
    "INDV_CONTB",
    "PTY_CMTE_CONTB",
    "OTH_CMTE_CONTB",
    "TTL_CONTB",
    "TRANF_FROM_OTHER_AUTH_CMTE",
    "OFFSETS_TO_OP_EXP",
    "OTHER_RECEIPTS",
    "TTL_RECEIPTS",
    "TRANF_TO_OTHER_AUTH_CMTE",
    "OTH_LOAN_REPYMTS",
    "INDV_REF",
    "POL_PTY_CMTE_REF",
    "TTL_CONTB_REF",
    "OTHER_DISB",
    "TTL_DISB",
    "NET_CONTB",
    "NET_OP_EXP",
    "COH_BOP",
    "CVG_START_DT",
    "COH_COP",
    "CVG_END_DT",
    "DEBTS_OWED_BY_CMTE",
    "DEBTS_OWED_TO_CMTE",
    "INDV_ITEM_CONTB",
    "INDV_UNITEM_CONTB",
    "OTH_LOANS",
    "TRANF_FROM_NONFED_ACCT",
    "TRANF_FROM_NONFED_LEVIN",
    "TTL_NONFED_TRANF",
    "LOAN_REPYMTS_RECEIVED",
    "OFFSETS_TO_FNDRSG",
    "OFFSETS_TO_LEGAL_ACCTG",
    "FED_CAND_CONTB_REF",
    "TTL_FED_RECEIPTS",
    "SHARED_FED_OP_EXP",
    "SHARED_NONFED_OP_EXP",
    "OTHER_FED_OP_EXP",
    "TTL_OP_EXP",
    "FED_CAND_CMTE_CONTB",
    "INDT_EXP",
    "COORD_EXP_BY_PTY_CMTE",
    "LOANS_MADE",
    "SHARED_FED_ACTVY_FED_SHR",
    "SHARED_FED_ACTVY_NONFED",
    "NON_ALLOC_FED_ELECT_ACTVY",
    "TTL_FED_ELECT_ACTVY",
    "TTL_FED_DISB",
    "CAND_CNTB",
    "CAND_LOAN",
    "TTL_LOANS",
    "OP_EXP",
    "CAND_LOAN_REPYMNT",
    "TTL_LOAN_REPYMTS",
    "OTH_CMTE_REF",
    "TTL_OFFSETS_TO_OP_EXP",
    "EXEMPT_LEGAL_ACCTG_DISB",
    "FNDRSG_DISB",
    "ITEM_REF_REB_RET",
    "SUBTTL_REF_REB_RET",
    "UNITEM_REF_REB_RET",
    "ITEM_OTHER_REF_REB_RET",
    "UNITEM_OTHER_REF_REB_RET",
    "SUBTTL_OTHER_REF_REB_RET",
    "ITEM_OTHER_INCOME",
    "UNITEM_OTHER_INCOME",
    "EXP_PRIOR_YRS_SUBJECT_LIM",
    "EXP_SUBJECT_LIMITS",
    "FED_FUNDS",
    "ITEM_CONVN_EXP_DISB",
    "ITEM_OTHER_DISB",
    "SUBTTL_CONVN_EXP_DISB",
    "TTL_EXP_SUBJECT_LIMITS",
    "UNITEM_CONVN_EXP_DISB",
    "UNITEM_OTHER_DISB",
    "TTL_COMMUNICATION_COST",
    "COH_BOY",
    "COH_COY",
    "ORG_TP",
)

_DATE_COLUMNS = frozenset({"CVG_START_DT", "CVG_END_DT"})
_NON_AMOUNT_COLUMNS = (
    frozenset(
        {
            "Link_Image",
            "CMTE_ID",
            "CMTE_NM",
            "CMTE_TP",
            "CMTE_DSGN",
            "CMTE_FILING_FREQ",
            "CMTE_ST1",
            "CMTE_ST2",
            "CMTE_CITY",
            "CMTE_ST",
            "CMTE_ZIP",
            "TRES_NM",
            "CAND_ID",
            "FEC_ELECTION_YR",
            "ORG_TP",
        }
    )
    | _DATE_COLUMNS
)
_AMOUNT_COLUMNS = frozenset(column for column in COMMITTEE_SUMMARY_COLUMNS if column not in _NON_AMOUNT_COLUMNS)


class CommitteeSummaryCellCoercionError(ValueError):
    """Raised when a non-empty typed committee-summary cell cannot be parsed."""

    def __init__(self, column: str, raw_value: str) -> None:
        super().__init__(f"{column}={raw_value!r}")
        self.column = column
        self.raw_value = raw_value


def _parse_fec_yyyymmdd(raw: str) -> date:
    if len(raw) != 8 or not raw.isdigit():
        raise CommitteeSummaryCellCoercionError("date", raw)
    try:
        return datetime.strptime(raw, "%Y%m%d").date()
    except ValueError:
        raise CommitteeSummaryCellCoercionError("date", raw) from None


def _parse_amount(raw: str) -> Decimal:
    try:
        value = Decimal(raw)
    except InvalidOperation:
        raise CommitteeSummaryCellCoercionError("amount", raw) from None
    if not value.is_finite():
        raise CommitteeSummaryCellCoercionError("amount", raw)
    return value


def _coerce_non_empty_cell(key: str, value: str) -> str | date | Decimal:
    try:
        if key in _DATE_COLUMNS:
            return _parse_fec_yyyymmdd(value)
        if key in _AMOUNT_COLUMNS:
            return _parse_amount(value)
    except CommitteeSummaryCellCoercionError as exc:
        raise CommitteeSummaryCellCoercionError(key, exc.raw_value) from None
    return value


def _normalize_row(raw_row: dict[str, str]) -> dict[str, Any]:
    typed: dict[str, Any] = {}
    for key, value in raw_row.items():
        stripped = value.strip() if value else ""
        if not stripped:
            typed[key] = None
        else:
            typed[key] = _coerce_non_empty_cell(key, stripped)
    return typed


def _validate_header(actual: tuple[str, ...]) -> None:
    if actual == COMMITTEE_SUMMARY_COLUMNS:
        return

    actual_set = set(actual)
    expected_set = set(COMMITTEE_SUMMARY_COLUMNS)
    order_note = ", columns present but in wrong order" if actual_set == expected_set else ""
    raise ValueError(
        f"Committee summary CSV header mismatch: "
        f"missing={expected_set - actual_set}, "
        f"extra={actual_set - expected_set}" + order_note
    )


def read_committee_summary_file(
    path: str | Path,
    limit: int | None = None,
) -> Iterator[dict[str, Any]]:
    """Stream-parse a FEC committee summary CSV file."""
    if limit is not None and limit < 0:
        raise ValueError("limit must be >= 0")
    if limit == 0:
        return

    file_path = Path(path)
    expected_count = len(COMMITTEE_SUMMARY_COLUMNS)
    yielded = 0

    with file_path.open("r", encoding="utf-8", newline="") as csvfile:
        reader = csv.DictReader(csvfile)
        _validate_header(tuple(reader.fieldnames) if reader.fieldnames else ())

        for line_number, raw_row in enumerate(reader, start=2):
            if None in raw_row:
                LOGGER.warning(
                    "Skipping row %d: too many fields (%d extra)",
                    line_number,
                    len(raw_row[None]),  # type: ignore[arg-type]
                )
                continue
            if any(value is None for value in raw_row.values()):
                present = sum(1 for value in raw_row.values() if value is not None)
                LOGGER.warning(
                    "Skipping row %d: expected %d fields, got %d",
                    line_number,
                    expected_count,
                    present,
                )
                continue

            try:
                yield _normalize_row(raw_row)
            except CommitteeSummaryCellCoercionError as exc:
                LOGGER.warning(
                    "Skipping row %d: invalid committee summary cell %s",
                    line_number,
                    exc,
                )
                continue
            yielded += 1
            if limit is not None and yielded >= limit:
                return
