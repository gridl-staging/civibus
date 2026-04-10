"""
Stub summary for /Users/stuart/parallel_development/civibus_dev/MAR18_api_graph_routes_and_property_endpoints/civibus_dev/domains/campaign_finance/jurisdictions/states/NC/scraper/load_support.py.
"""

from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

import psycopg

from core.types.python.models import (
    DataSource,
    SourceRecord,
    compute_record_hash,
    utc_now,
)
from domains.campaign_finance.jurisdictions.states.load_utils import ensure_data_source

_NC_DOMAIN = "campaign_finance"
_NC_JURISDICTION = "state/NC"
_NC_TRANSACTION_SOURCE_NAME = "North Carolina SBoE Transaction Search"
_NC_TRANSACTION_SOURCE_URL = "https://cf.ncsbe.gov/CFTxnLkup/"
_NC_COMMITTEE_DOCUMENT_SOURCE_NAME = "North Carolina SBoE Committee/Document Search"
_NC_COMMITTEE_DOCUMENT_SOURCE_URL = "https://cf.ncsbe.gov/CFOrgLkup/"


def build_data_source() -> DataSource:
    return DataSource(
        domain=_NC_DOMAIN,
        jurisdiction=_NC_JURISDICTION,
        name=_NC_TRANSACTION_SOURCE_NAME,
        source_url=_NC_TRANSACTION_SOURCE_URL,
        source_format="csv",
    )


def build_committee_document_data_source() -> DataSource:
    return DataSource(
        domain=_NC_DOMAIN,
        jurisdiction=_NC_JURISDICTION,
        name=_NC_COMMITTEE_DOCUMENT_SOURCE_NAME,
        source_url=_NC_COMMITTEE_DOCUMENT_SOURCE_URL,
        source_format="csv",
    )


def _ensure_nc_data_source(conn: psycopg.Connection, data_source: DataSource) -> UUID:
    return ensure_data_source(conn, data_source)


def ensure_nc_data_source(conn: psycopg.Connection) -> UUID:
    return _ensure_nc_data_source(conn, build_data_source())


def ensure_nc_committee_document_data_source(conn: psycopg.Connection) -> UUID:
    return _ensure_nc_data_source(conn, build_committee_document_data_source())


def build_nc_source_record(data_source_id: UUID, row: Mapping[str, str | None]) -> SourceRecord:
    raw_fields = dict(row)
    record_hash = compute_record_hash(raw_fields)

    return SourceRecord(
        data_source_id=data_source_id,
        source_record_key=record_hash,
        raw_fields=raw_fields,
        pull_date=utc_now(),
        record_hash=record_hash,
    )


def select_nc_source_record_id(
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
