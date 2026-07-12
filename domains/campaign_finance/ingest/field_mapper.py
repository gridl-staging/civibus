"""Field mapping helpers for FEC bulk ingest rows."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation
from math import isfinite


def _normalize_optional_text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    normalized_value = value.strip()
    if not normalized_value:
        return None
    return normalized_value


def _parse_optional_year(value: object) -> int | None:
    normalized_value = _normalize_optional_text(value)
    if normalized_value is None:
        return None
    try:
        return int(normalized_value)
    except ValueError:
        return None


def parse_fec_date(value: str | None) -> str | None:
    normalized_value = _normalize_optional_text(value)
    if normalized_value in {None, "00000000"}:
        return None
    if "/" in normalized_value:
        date_format = "%m/%d/%Y"
    elif len(normalized_value) == 8 and normalized_value.isdigit():
        date_format = "%m%d%Y"
    else:
        return None
    try:
        parsed_date = datetime.strptime(normalized_value, date_format).date()
    except ValueError:
        return None
    return parsed_date.isoformat()


def parse_fec_amount(value: str | None) -> float | None:
    normalized_value = _normalize_optional_text(value)
    if normalized_value is None:
        return None
    try:
        parsed_amount = float(normalized_value)
    except ValueError:
        return None
    if not isfinite(parsed_amount):
        return None
    return parsed_amount


def parse_fec_decimal_amount(value: str | None) -> Decimal | None:
    normalized_value = _normalize_optional_text(value)
    if normalized_value is None:
        return None
    try:
        parsed_amount = Decimal(normalized_value)
    except InvalidOperation:
        return None
    if not parsed_amount.is_finite():
        return None
    return parsed_amount


def _map_base_contribution_fields(row: Mapping[str, str | None]) -> dict[str, object]:
    raw_transaction_date = _normalize_optional_text(row.get("TRANSACTION_DT"))
    parsed_transaction_date = parse_fec_date(raw_transaction_date)
    return {
        "committee_id": _normalize_optional_text(row.get("CMTE_ID")),
        "contributor_name": _normalize_optional_text(row.get("NAME")),
        "entity_type": _normalize_optional_text(row.get("ENTITY_TP")),
        "contributor_state": _normalize_optional_text(row.get("STATE")),
        "contributor_city": _normalize_optional_text(row.get("CITY")),
        "contributor_zip": _normalize_optional_text(row.get("ZIP_CODE")),
        "contributor_employer": _normalize_optional_text(row.get("EMPLOYER")),
        "contributor_occupation": _normalize_optional_text(row.get("OCCUPATION")),
        "contribution_receipt_amount": parse_fec_amount(row.get("TRANSACTION_AMT")),
        "contribution_receipt_date": parsed_transaction_date,
        "contribution_receipt_date_is_reliable": parsed_transaction_date is not None or raw_transaction_date is None,
        "sub_id": _normalize_optional_text(row.get("SUB_ID")),
        "amendment_indicator": _normalize_optional_text(row.get("AMNDT_IND")),
        "report_type": _normalize_optional_text(row.get("RPT_TP")),
        "transaction_type": _normalize_optional_text(row.get("TRANSACTION_TP")),
        "image_number": _normalize_optional_text(row.get("IMAGE_NUM")),
        "file_number": _normalize_optional_text(row.get("FILE_NUM")),
        "memo_code": _normalize_optional_text(row.get("MEMO_CD")),
        "memo_text": _normalize_optional_text(row.get("MEMO_TEXT")),
        "transaction_identifier": _normalize_optional_text(row.get("TRAN_ID")),
        "other_id": _normalize_optional_text(row.get("OTHER_ID")),
    }


def map_contribution_fields(row: Mapping[str, str | None]) -> dict[str, object]:
    mapped_fields = _map_base_contribution_fields(row)
    candidate_fec_id = _normalize_optional_text(row.get("CAND_ID"))
    if candidate_fec_id is not None:
        mapped_fields["candidate_fec_id"] = candidate_fec_id
    return mapped_fields


def map_committee_fields(row: Mapping[str, str | None]) -> dict[str, object]:
    return {
        "fec_committee_id": _normalize_optional_text(row.get("CMTE_ID")),
        "name": _normalize_optional_text(row.get("CMTE_NM")),
        "committee_type": _normalize_optional_text(row.get("CMTE_TP")),
        "committee_designation": _normalize_optional_text(row.get("CMTE_DSGN")),
        "party": _normalize_optional_text(row.get("CMTE_PTY_AFFILIATION")),
        "state": _normalize_optional_text(row.get("CMTE_ST")),
        "city": _normalize_optional_text(row.get("CMTE_CITY")),
        "zip_code": _normalize_optional_text(row.get("CMTE_ZIP")),
        "treasurer_name": _normalize_optional_text(row.get("TRES_NM")),
        "candidate_fec_id": _normalize_optional_text(row.get("CAND_ID")),
        "connected_organization_name": _normalize_optional_text(row.get("CONNECTED_ORG_NM")),
    }


def map_candidate_fields(row: Mapping[str, str | None]) -> dict[str, object]:
    return {
        "fec_candidate_id": _normalize_optional_text(row.get("CAND_ID")),
        "name": _normalize_optional_text(row.get("CAND_NAME")),
        "party": _normalize_optional_text(row.get("CAND_PTY_AFFILIATION")),
        "office": _normalize_optional_text(row.get("CAND_OFFICE")),
        "state": _normalize_optional_text(row.get("CAND_OFFICE_ST")),
        "district": _normalize_optional_text(row.get("CAND_OFFICE_DISTRICT")),
        "incumbent_challenge": _normalize_optional_text(row.get("CAND_ICI")),
        "principal_committee_fec_id": _normalize_optional_text(row.get("CAND_PCC")),
    }


def map_candidate_summary_fields(row: Mapping[str, str | None]) -> dict[str, object]:
    return {
        "fec_candidate_id": _normalize_optional_text(row.get("CAND_ID")),
        "total_receipts": parse_fec_decimal_amount(row.get("TTL_RECEIPTS")),
        "total_disbursements": parse_fec_decimal_amount(row.get("TTL_DISB")),
        "cash_on_hand": parse_fec_decimal_amount(row.get("COH_COP")),
        "summary_coverage_end_date": parse_fec_date(row.get("CVG_END_DT")),
    }


def map_ccl_fields(row: Mapping[str, str | None]) -> dict[str, object]:
    return {
        "candidate_fec_id": _normalize_optional_text(row.get("CAND_ID")),
        "committee_fec_id": _normalize_optional_text(row.get("CMTE_ID")),
        "committee_type": _normalize_optional_text(row.get("CMTE_TP")),
        "designation": _normalize_optional_text(row.get("CMTE_DSGN")),
        "linkage_id": _normalize_optional_text(row.get("LINKAGE_ID")),
        "candidate_election_year": _parse_optional_year(row.get("CAND_ELECTION_YR")),
        "fec_election_year": _parse_optional_year(row.get("FEC_ELECTION_YR")),
    }


__all__ = [
    "parse_fec_date",
    "parse_fec_amount",
    "parse_fec_decimal_amount",
    "map_contribution_fields",
    "map_committee_fields",
    "map_candidate_fields",
    "map_candidate_summary_fields",
    "map_ccl_fields",
]
