"""
Stub summary for mar21_02_tx_pa_state_pipelines/civibus_dev/domains/campaign_finance/jurisdictions/states/PA/scraper/load_support.py.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from uuid import UUID

import psycopg

from core.db import (
    find_organization_by_identifier,
    resolve_organization_by_canonical_name,
    resolve_person_by_name_and_zip,
    upsert_address,
)
from core.types.python.models import (
    Address,
    DataSource,
    Organization,
    Person,
    SourceRecord,
    compute_record_hash,
    utc_now,
)
from domains.campaign_finance.ingest.text_utils import normalize_optional_text
from domains.campaign_finance.jurisdictions.states.load_utils import (
    ensure_data_source,
    link_entity_source_and_optional_mailing_address,
)
from domains.campaign_finance.types.models import Filing

from . import _load_column_for_semantic_path, _load_data_source_for_data_type
from .extract import extract_pa_filing

_PA_DOMAIN = "campaign_finance"
_PA_JURISDICTION = "state/PA"
_PA_SOURCE_FORMAT = "csv"

_PA_CAMPAIGN_ID_PATH_BY_TYPE = {
    "contributions": "pa.campaign_finance_id",
    "expenditures": "pa.campaign_finance_id",
    "debts": "pa.campaign_finance_id",
    "receipts": "pa.campaign_finance_id",
    "filings": "pa.campaignfinance_id",
}
_PA_COUNTERPARTY_NAME_PATH_BY_TYPE = {
    "contributions": "donor.name",
    "expenditures": "payee.name",
    "debts": "lender.name",
    "receipts": "pa.receipt_source_name",
}
_PA_COUNTERPARTY_EMPLOYER_PATH = {"contributions": "donor.employer"}
_PA_COUNTERPARTY_OCCUPATION_PATH = {"contributions": "donor.occupation"}
_PA_TRANSACTION_ROLES_BY_TYPE = {
    "contributions": ("donor", "contributor", "contributor_address"),
    "expenditures": ("payee", "payee", "payee_address"),
    "debts": ("lender", "lender", "lender_address"),
    "receipts": ("source", "source", "source_address"),
}

_normalize_optional_text = normalize_optional_text


def ensure_pa_data_source(conn: psycopg.Connection, data_type: str = "contributions") -> UUID:
    normalized_data_type = data_type.strip().lower()
    data_source_config = _load_data_source_for_data_type(normalized_data_type)
    return ensure_data_source(
        conn,
        DataSource(
            domain=_PA_DOMAIN,
            jurisdiction=_PA_JURISDICTION,
            name=data_source_config.name,
            source_url=data_source_config.url,
            source_format=_PA_SOURCE_FORMAT,
        ),
    )


def _required_pa_text(value: str | None, field_name: str) -> str:
    normalized_value = _normalize_optional_text(value)
    if normalized_value is None:
        raise ValueError(f"PA row is missing {field_name}")
    return normalized_value


def _pa_campaign_finance_id(row: Mapping[str, str | None], *, data_type: str) -> str:
    campaign_id_column = _load_column_for_semantic_path(data_type, _PA_CAMPAIGN_ID_PATH_BY_TYPE[data_type])
    return _required_pa_text(row.get(campaign_id_column), campaign_id_column)


def _pa_source_record_key(row: Mapping[str, str | None], *, data_type: str) -> str:
    campaign_finance_id = _pa_campaign_finance_id(row, data_type=data_type)
    row_hash = compute_record_hash(dict(row))
    return f"PA-{campaign_finance_id}-{data_type}-{row_hash}"


def _pa_transaction_identifier(row: Mapping[str, str | None], *, data_type: str) -> str:
    return _pa_source_record_key(row, data_type=data_type)


def _parse_pa_compact_date(raw_value: str | None) -> date | None:
    normalized_value = _normalize_optional_text(raw_value)
    if normalized_value is None:
        return None
    if len(normalized_value) != 8 or not normalized_value.isdigit():
        raise ValueError(f"PA row has invalid YYYYMMDD date: {raw_value!r}")
    return datetime.strptime(normalized_value, "%Y%m%d").date()


def _parse_pa_submitted_date(raw_value: str | None) -> date | None:
    normalized_value = _normalize_optional_text(raw_value)
    if normalized_value is None:
        return None
    return datetime.strptime(normalized_value, "%Y-%m-%d").date()


def _pa_filing_fec_id(row: Mapping[str, str | None], *, data_type: str) -> str:
    committee_id_column = _load_column_for_semantic_path(data_type, "committee.id")
    submitted_date_column = _load_column_for_semantic_path(data_type, "filing.submitted_date")

    committee_identifier = _required_pa_text(row.get(committee_id_column), committee_id_column)
    submitted_date = _parse_pa_submitted_date(row.get(submitted_date_column))
    if submitted_date is None:
        raise ValueError("PA row is missing SubmittedDate for filing_fec_id generation")

    return f"PA-{committee_identifier}-{submitted_date.year}-{data_type}"


def _pa_filing_fec_id_from_filer_row(
    filer_row: Mapping[str, str | None],
    *,
    data_type: str,
) -> str:
    committee_id_column = _load_column_for_semantic_path("filings", "committee.id")
    submitted_date_column = _load_column_for_semantic_path("filings", "filing.submitted_date")

    committee_identifier = _required_pa_text(filer_row.get(committee_id_column), committee_id_column)
    submitted_date = _parse_pa_submitted_date(filer_row.get(submitted_date_column))
    if submitted_date is None:
        raise ValueError("PA filer row is missing SubmittedDate for filing_fec_id generation")

    return f"PA-{committee_identifier}-{submitted_date.year}-{data_type}"


def _pa_filer_row_amendment_indicator(row: Mapping[str, str | None]) -> str:
    amend_column = _load_column_for_semantic_path("filings", "pa.amend_flag")
    terminate_column = _load_column_for_semantic_path("filings", "pa.terminate_flag")

    amend_value = (_normalize_optional_text(row.get(amend_column)) or "N").upper()
    terminate_value = (_normalize_optional_text(row.get(terminate_column)) or "N").upper()

    if amend_value == "Y":
        return "A"
    if terminate_value == "Y":
        return "T"
    return "N"


def _build_filer_amendment_lookup(filer_rows: Iterable[Mapping[str, str | None]]) -> dict[str, str]:
    campaignfinance_id_column = _load_column_for_semantic_path("filings", "pa.campaignfinance_id")

    lookup: dict[str, str] = {}
    for filer_row in filer_rows:
        campaignfinance_id = _normalize_optional_text(filer_row.get(campaignfinance_id_column))
        if campaignfinance_id is None:
            continue
        lookup[campaignfinance_id] = _pa_filer_row_amendment_indicator(filer_row)

    return lookup


def _build_filer_row_lookup(
    filer_rows: Iterable[Mapping[str, str | None]],
) -> dict[str, dict[str, str | None]]:
    campaignfinance_id_column = _load_column_for_semantic_path("filings", "pa.campaignfinance_id")

    lookup: dict[str, dict[str, str | None]] = {}
    for filer_row in filer_rows:
        campaignfinance_id = _normalize_optional_text(filer_row.get(campaignfinance_id_column))
        if campaignfinance_id is None:
            continue
        lookup[campaignfinance_id] = dict(filer_row)

    return lookup


def _resolve_pa_amendment_indicator(
    row: Mapping[str, str | None],
    *,
    data_type: str,
    filer_lookup: Mapping[str, str],
) -> str | None:
    if data_type == "filings":
        return _pa_filer_row_amendment_indicator(row)

    campaign_id_column = _load_column_for_semantic_path(data_type, _PA_CAMPAIGN_ID_PATH_BY_TYPE[data_type])
    campaign_finance_id = _normalize_optional_text(row.get(campaign_id_column))
    if campaign_finance_id is None:
        return None

    return filer_lookup.get(campaign_finance_id)


def _parse_required_pa_amount(raw_value: str | None, field_name: str) -> Decimal:
    normalized_value = _required_pa_text(raw_value, field_name)
    try:
        return Decimal(normalized_value.replace(",", ""))
    except InvalidOperation as error:
        raise ValueError(f"PA row has invalid {field_name}: {raw_value!r}") from error


def _build_pa_source_record(data_source_id: UUID, row: Mapping[str, str | None], *, data_type: str) -> SourceRecord:
    raw_fields = dict(row)
    return SourceRecord(
        data_source_id=data_source_id,
        source_record_key=_pa_source_record_key(row, data_type=data_type),
        source_url=_load_data_source_for_data_type(data_type).url,
        raw_fields=raw_fields,
        record_hash=compute_record_hash(raw_fields),
        pull_date=utc_now(),
    )


def _load_pa_transaction_entities(
    conn: psycopg.Connection,
    *,
    source_record_id: UUID,
    data_type: str,
    person: Person | None,
    organization: Organization | None,
    address: Address | None,
) -> None:
    person_role, organization_role, address_role = _PA_TRANSACTION_ROLES_BY_TYPE[data_type]

    address_id = None
    if address is not None:
        address_id = upsert_address(conn, address)
        link_entity_source_and_optional_mailing_address(
            conn,
            entity_type="address",
            entity_id=address_id,
            source_record_id=source_record_id,
            extraction_role=address_role,
            address_id=None,
        )

    person_id = resolve_person_by_name_and_zip(conn, person, address)
    if person_id is not None:
        link_entity_source_and_optional_mailing_address(
            conn,
            entity_type="person",
            entity_id=person_id,
            source_record_id=source_record_id,
            extraction_role=person_role,
            address_id=address_id,
        )

    organization_id = resolve_organization_by_canonical_name(conn, organization)
    if organization_id is not None:
        link_entity_source_and_optional_mailing_address(
            conn,
            entity_type="organization",
            entity_id=organization_id,
            source_record_id=source_record_id,
            extraction_role=organization_role,
            address_id=address_id,
        )


def _select_pa_source_record_id(
    conn: psycopg.Connection,
    *,
    data_source_id: UUID,
    source_record_key: str,
) -> UUID | None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT id
            FROM core.source_record
            WHERE data_source_id = %s
              AND source_record_key = %s
              AND superseded_by IS NULL
            LIMIT 1
            """,
            (data_source_id, source_record_key),
        )
        row = cursor.fetchone()
    if row is None:
        return None
    return row[0]


def _require_pa_filer_row(
    row: Mapping[str, str | None],
    *,
    data_type: str,
    filer_row_lookup: Mapping[str, Mapping[str, str | None]],
) -> Mapping[str, str | None]:
    campaign_finance_id = _pa_campaign_finance_id(row, data_type=data_type)
    filer_row = filer_row_lookup.get(campaign_finance_id)
    if filer_row is None:
        raise ValueError(f"PA detail row has no matching filer row for CampaignFinanceID={campaign_finance_id!r}")
    return filer_row


def _resolve_pa_committee_organization_id(conn: psycopg.Connection, committee: Organization) -> UUID:
    committee_identifier = _normalize_optional_text(committee.identifiers.get("pa_filer_id"))
    if committee_identifier is not None:
        existing_org_id = find_organization_by_identifier(conn, "pa_filer_id", committee_identifier)
        if existing_org_id is not None:
            return existing_org_id

    resolved_org_id = resolve_organization_by_canonical_name(conn, committee)
    if resolved_org_id is None:
        raise ValueError("PA committee extraction did not produce a resolvable organization")
    return resolved_org_id


def _build_pa_filing(
    filer_row: Mapping[str, str | None],
    *,
    filing_fec_id: str,
    committee_id: UUID,
    source_record_id: UUID,
    data_type: str,
    amendment_indicator: str,
) -> Filing:
    submitted_date_column = _load_column_for_semantic_path("filings", "filing.submitted_date")
    submitted_date = _parse_pa_submitted_date(filer_row.get(submitted_date_column))
    committee_name = _normalize_optional_text(extract_pa_filing(dict(filer_row))["committee"].canonical_name)

    return Filing(
        filing_fec_id=filing_fec_id,
        committee_id=committee_id,
        report_type=data_type,
        amendment_indicator=amendment_indicator,
        filing_name=committee_name,
        receipt_date=submitted_date,
        accepted_date=submitted_date,
        source_record_id=source_record_id,
    )


def _pa_counterparty_name_raw(row: Mapping[str, str | None], *, data_type: str) -> str | None:
    semantic_path = _PA_COUNTERPARTY_NAME_PATH_BY_TYPE[data_type]
    column_name = _load_column_for_semantic_path(data_type, semantic_path)
    return _normalize_optional_text(row.get(column_name))


def _pa_counterparty_employer(row: Mapping[str, str | None], *, data_type: str) -> str | None:
    semantic_path = _PA_COUNTERPARTY_EMPLOYER_PATH.get(data_type)
    if semantic_path is None:
        return None

    column_name = _load_column_for_semantic_path(data_type, semantic_path)
    return _normalize_optional_text(row.get(column_name))


def _pa_counterparty_occupation(row: Mapping[str, str | None], *, data_type: str) -> str | None:
    semantic_path = _PA_COUNTERPARTY_OCCUPATION_PATH.get(data_type)
    if semantic_path is None:
        return None

    column_name = _load_column_for_semantic_path(data_type, semantic_path)
    return _normalize_optional_text(row.get(column_name))


def _pa_transaction_type(data_type: str) -> str:
    return data_type.rstrip("s")


def _pa_transaction_date(row: Mapping[str, str | None], *, data_type: str) -> date | None:
    transaction_date_column = _load_column_for_semantic_path(data_type, "transaction.date")
    return _parse_pa_compact_date(row.get(transaction_date_column))


def _resolve_pa_transaction_address_id(
    conn: psycopg.Connection,
    *,
    source_record_id: UUID,
    data_type: str,
) -> UUID | None:
    address_role = _PA_TRANSACTION_ROLES_BY_TYPE[data_type][2]

    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT entity_id
            FROM core.entity_source
            WHERE source_record_id = %s
              AND entity_type = 'address'
              AND extraction_role = %s
            LIMIT 1
            """,
            (source_record_id, address_role),
        )
        row = cursor.fetchone()

    if row is None:
        return None
    return row[0]
