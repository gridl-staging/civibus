from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg

from core.db import find_organization_by_identifier, resolve_organization_by_canonical_name
from core.types.python.models import Organization, compute_record_hash
from domains.campaign_finance.ingest.text_utils import normalize_optional_text
from domains.campaign_finance.types.models import AmendmentIndicatorLiteral

from . import _load_column_for_semantic_path
from .extract import (
    INContributionExtraction,
    INExpenditureExtraction,
    extract_in_contribution,
    extract_in_expenditure,
)
from .parse import parse_contributions, parse_expenditures

_SUPPORTED_IN_DATA_TYPES = frozenset(("contributions", "expenditures"))
_IN_COUNTERPARTY_OCCUPATION_PATH = {
    "contributions": "donor.occupation",
    "expenditures": "payee.occupation",
}


@dataclass(frozen=True, slots=True)
class _INDataTypeSpec:
    person_key: str
    organization_key: str
    person_role: str
    organization_role: str
    committee_role: str
    address_role: str
    person_roles: tuple[str, ...]
    organization_roles: tuple[str, ...]
    extract_row: Callable[[dict[str, str | None]], INContributionExtraction | INExpenditureExtraction]
    parse_rows: Callable[[Path], Iterable[Mapping[str, str | None]]]


_IN_DATA_TYPE_SPECS = {
    "contributions": _INDataTypeSpec(
        person_key="donor_person",
        organization_key="donor_org",
        person_role="donor",
        organization_role="contributor",
        committee_role="recipient",
        address_role="contributor_address",
        person_roles=("donor",),
        organization_roles=("contributor",),
        extract_row=extract_in_contribution,
        parse_rows=parse_contributions,
    ),
    "expenditures": _INDataTypeSpec(
        person_key="payee_person",
        organization_key="payee_org",
        person_role="payee",
        organization_role="payee",
        committee_role="payer",
        address_role="payee_address",
        person_roles=("payee",),
        organization_roles=("payee",),
        extract_row=extract_in_expenditure,
        parse_rows=parse_expenditures,
    ),
}


def _in_data_type_spec(data_type: str) -> _INDataTypeSpec:
    try:
        return _IN_DATA_TYPE_SPECS[data_type]
    except KeyError as error:
        raise ValueError(f"Unsupported IN data type: {data_type}") from error


def _in_extract_row(row: Mapping[str, str | None], data_type: str) -> Mapping[str, Any]:
    return _in_data_type_spec(data_type).extract_row(dict(row))


def _resolve_in_committee_organization_id(conn: psycopg.Connection, committee: Organization) -> UUID:
    committee_identifier = normalize_optional_text(committee.identifiers.get("in_committee_id"))
    if committee_identifier is not None:
        existing_org_id = find_organization_by_identifier(conn, "in_committee_id", committee_identifier)
        if existing_org_id is not None:
            return existing_org_id

    resolved_org_id = resolve_organization_by_canonical_name(conn, committee)
    if resolved_org_id is None:
        raise ValueError("IN committee extraction did not produce a resolvable organization")
    return resolved_org_id


def _require_in_supported_data_type(data_type: str) -> None:
    if data_type not in _SUPPORTED_IN_DATA_TYPES:
        raise ValueError(f"Unsupported IN data type: {data_type}")


def _required_in_text(value: str | None, field_name: str) -> str:
    normalized_value = normalize_optional_text(value)
    if normalized_value is None:
        raise ValueError(f"IN row is missing {field_name}")
    return normalized_value


def _parse_in_date(raw_value: str | None) -> date | None:
    normalized_value = normalize_optional_text(raw_value)
    if normalized_value is None:
        return None

    for date_format in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(normalized_value, date_format).date()
        except ValueError:
            continue

    raise ValueError(f"IN row has invalid YYYY-MM-DD HH:MM:SS date: {raw_value!r}")


def _parse_required_in_amount(raw_value: str | None, field_name: str) -> Decimal:
    normalized_value = _required_in_text(raw_value, field_name)
    try:
        return Decimal(normalized_value.replace(",", ""))
    except InvalidOperation as error:
        raise ValueError(f"IN row has invalid {field_name}: {raw_value!r}") from error


def _in_row_value(
    row: Mapping[str, str | None],
    *,
    data_type: str,
    semantic_path: str,
) -> str | None:
    return row.get(_load_column_for_semantic_path(data_type, semantic_path))


def _required_in_row_value(
    row: Mapping[str, str | None],
    *,
    data_type: str,
    semantic_path: str,
) -> str:
    column_name = _load_column_for_semantic_path(data_type, semantic_path)
    return _required_in_text(row.get(column_name), column_name)


def _required_in_amount_from_row(
    row: Mapping[str, str | None],
    *,
    data_type: str,
    semantic_path: str,
) -> Decimal:
    column_name = _load_column_for_semantic_path(data_type, semantic_path)
    return _parse_required_in_amount(row.get(column_name), column_name)


def _in_source_record_key(row: Mapping[str, str | None], *, data_type: str) -> str:
    _require_in_supported_data_type(data_type)
    # Indiana exports do not expose a stable per-row transaction identifier.
    return compute_record_hash(dict(row))


def _in_transaction_identifier(row: Mapping[str, str | None], *, data_type: str) -> str:
    return _in_source_record_key(row, data_type=data_type)


def _in_amendment_indicator(row: Mapping[str, str | None], *, data_type: str) -> AmendmentIndicatorLiteral:
    amended_flag = normalize_optional_text(_in_row_value(row, data_type=data_type, semantic_path="transaction.amended"))
    if amended_flag in {None, "0", "N"}:
        return "N"
    if amended_flag == "1":
        return "A"
    raise ValueError(f"IN row has unknown amended flag: {amended_flag!r}")


def _in_filing_fec_id(row: Mapping[str, str | None], *, data_type: str) -> str:
    filing_identifier = _required_in_row_value(row, data_type=data_type, semantic_path="filing.id")
    transaction_date = _parse_in_date(_in_row_value(row, data_type=data_type, semantic_path="transaction.date"))
    if transaction_date is None:
        raise ValueError("IN row is missing transaction.date for filing_fec_id generation")

    return f"IN-{filing_identifier}-{transaction_date.year}-{data_type}"


def _in_native_committee_id(row: Mapping[str, str | None], *, data_type: str) -> str:
    committee_name = _required_in_row_value(row, data_type=data_type, semantic_path="committee.name").casefold()
    committee_type = normalize_optional_text(_in_row_value(row, data_type=data_type, semantic_path="committee.type"))
    if committee_type is None:
        return committee_name
    return f"{committee_name}::{committee_type.casefold()}"


# Assumed IN IE token: ExpenditureCode == "Independent Expenditure".
# Indiana IED bulk data uses ExpenditureCode for broad categories (Advertising,
# Contributions, etc.). IE filings would use this category code.
_IN_IE_EXPENDITURE_CODES = frozenset({"independent expenditure"})


def _in_is_independent_expenditure(row: Mapping[str, str | None], *, data_type: str) -> bool:
    if data_type != "expenditures":
        return False
    code = normalize_optional_text(_in_row_value(row, data_type=data_type, semantic_path="transaction.code"))
    if code is None:
        return False
    return code.lower() in _IN_IE_EXPENDITURE_CODES


def _in_transaction_type(row: Mapping[str, str | None], *, data_type: str) -> str:
    if _in_is_independent_expenditure(row, data_type=data_type):
        return "Independent Expenditure"
    transaction_type = normalize_optional_text(
        _in_row_value(row, data_type=data_type, semantic_path="transaction.type")
    )
    if transaction_type is not None:
        return transaction_type.lower()
    return data_type.rstrip("s")


def _in_counterparty_occupation(row: Mapping[str, str | None], *, data_type: str) -> str | None:
    semantic_path = _IN_COUNTERPARTY_OCCUPATION_PATH.get(data_type)
    if semantic_path is None:
        return None

    return normalize_optional_text(_in_row_value(row, data_type=data_type, semantic_path=semantic_path))
