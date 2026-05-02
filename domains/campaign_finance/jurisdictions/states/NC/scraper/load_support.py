"""
Stub summary for /Users/stuart/parallel_development/civibus_dev/MAR18_api_graph_routes_and_property_endpoints/civibus_dev/domains/campaign_finance/jurisdictions/states/NC/scraper/load_support.py.
"""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
from uuid import UUID

import psycopg

from core.types.python.models import (
    DataSource,
    SourceRecord,
    compute_record_hash,
    utc_now,
)
from domains.campaign_finance.jurisdictions.config_schema import DataSourceConfig, load_jurisdiction_config
from domains.campaign_finance.jurisdictions.states.load_utils import ensure_data_source

from . import _CONFIG_PATH

_NC_DOMAIN = "campaign_finance"
_NC_JURISDICTION = "state/NC"
NC_TRANSACTION_SOURCE_NAME = "North Carolina SBoE Transaction Search"
NC_COMMITTEE_DOCUMENT_SOURCE_NAME = "North Carolina SBoE Committee/Document Search"
NC_IE_TRANSACTION_TYPE = "independent_expenditures"


@lru_cache(maxsize=1)
def _load_nc_data_source_configs() -> tuple[DataSourceConfig, ...]:
    config = load_jurisdiction_config(_CONFIG_PATH)
    return tuple(config.data_sources)


def _load_nc_data_source_config_by_name(source_name: str) -> DataSourceConfig:
    for data_source in _load_nc_data_source_configs():
        if data_source.name == source_name:
            return data_source
    raise RuntimeError(f"NC config is missing data source {source_name!r}")


def _load_nc_ie_data_source_config() -> DataSourceConfig:
    matches = [
        data_source
        for data_source in _load_nc_data_source_configs()
        if NC_IE_TRANSACTION_TYPE in data_source.coverage.transaction_types
    ]
    if len(matches) != 1:
        raise RuntimeError(
            "NC config must define exactly one IE data source with "
            f"transaction_types containing {NC_IE_TRANSACTION_TYPE!r}; found {len(matches)}"
        )
    return matches[0]


def _build_data_source_from_config(data_source_config: DataSourceConfig) -> DataSource:
    return DataSource(
        domain=_NC_DOMAIN,
        jurisdiction=_NC_JURISDICTION,
        name=data_source_config.name,
        source_url=data_source_config.url,
        source_format="csv",
    )


def build_data_source() -> DataSource:
    return _build_data_source_from_config(_load_nc_data_source_config_by_name(NC_TRANSACTION_SOURCE_NAME))


def build_committee_document_data_source() -> DataSource:
    return _build_data_source_from_config(_load_nc_data_source_config_by_name(NC_COMMITTEE_DOCUMENT_SOURCE_NAME))


def build_ie_document_index_data_source() -> DataSource:
    return _build_data_source_from_config(_load_nc_ie_data_source_config())


def _ensure_nc_data_source(conn: psycopg.Connection, data_source: DataSource) -> UUID:
    return ensure_data_source(conn, data_source)


def ensure_nc_data_source(conn: psycopg.Connection) -> UUID:
    return _ensure_nc_data_source(conn, build_data_source())


def ensure_nc_committee_document_data_source(conn: psycopg.Connection) -> UUID:
    return _ensure_nc_data_source(conn, build_committee_document_data_source())


def ensure_nc_ie_document_index_data_source(conn: psycopg.Connection) -> UUID:
    return _ensure_nc_data_source(conn, build_ie_document_index_data_source())


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


def set_nc_source_record_report_section_url(
    conn: psycopg.Connection,
    *,
    source_record_id: UUID,
    report_section_url: str,
) -> None:
    """Persist additive report-section metadata without changing record identity."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE core.source_record
            SET raw_fields = COALESCE(raw_fields, '{}'::jsonb) || jsonb_build_object('report_section_url', %s::text)
            WHERE id = %s
              AND superseded_by IS NULL
              AND (raw_fields ->> 'report_section_url') IS DISTINCT FROM %s::text
            """,
            (report_section_url, source_record_id, report_section_url),
        )
        if cursor.rowcount > 0:
            return
        cursor.execute(
            """
            SELECT 1
            FROM core.source_record
            WHERE id = %s
              AND superseded_by IS NULL
            LIMIT 1
            """,
            (source_record_id,),
        )
        row = cursor.fetchone()
    if row is None:
        raise RuntimeError(
            f"Cannot persist NC report_section_url because source_record_id={source_record_id} was not found"
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
