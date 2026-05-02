"""
Stub summary for /Users/stuart/parallel_development/civibus_dev/MAR18_api_graph_routes_and_property_endpoints/civibus_dev/domains/campaign_finance/ingest/loader.py.
"""

from __future__ import annotations

from uuid import UUID

import psycopg

from core.db import (
    find_organization_by_identifier,
    find_person_by_name_and_zip,
    insert_entity_address,
    insert_entity_source,
    insert_organization,
    insert_person,
    try_insert_data_source,
    try_insert_source_record,
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
from core.graph.loader import create_contributed_to_edge, merge_organization_node, merge_person_node
from domains.campaign_finance.entity_extractors.extract import extract_contribution

_FEC_DATA_SOURCE_DOMAIN = "campaign_finance"
_FEC_DATA_SOURCE_JURISDICTION = "federal/fec"
_FEC_DATA_SOURCE_NAME = "FEC Schedule A API"
_FEC_SCHEDULE_A_URL = "https://api.open.fec.gov/v1/schedules/schedule_a/"


def _select_fec_data_source_id(conn: psycopg.Connection) -> UUID | None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT id
            FROM core.data_source
            WHERE domain = %s
              AND jurisdiction = %s
              AND name = %s
            LIMIT 1
            """,
            (_FEC_DATA_SOURCE_DOMAIN, _FEC_DATA_SOURCE_JURISDICTION, _FEC_DATA_SOURCE_NAME),
        )
        row = cursor.fetchone()

    if row is None:
        return None
    return row[0]


def _build_source_record(data_source_id: UUID, contribution: dict[str, object]) -> SourceRecord:
    source_record_key = contribution.get("sub_id")
    source_url = contribution.get("pdf_url")
    return SourceRecord(
        data_source_id=data_source_id,
        source_record_key=source_record_key if isinstance(source_record_key, str) else None,
        source_url=source_url if isinstance(source_url, str) else None,
        raw_fields=contribution,
        pull_date=utc_now(),
        record_hash=compute_record_hash(contribution),
    )


def _resolve_person_id(
    conn: psycopg.Connection,
    person: Person | None,
    address: Address | None,
) -> UUID | None:
    if person is None:
        return None

    zip5 = address.zip5 if address is not None else None
    existing_person_id = None
    if person.last_name and person.first_name:
        existing_person_id = find_person_by_name_and_zip(conn, person.last_name, person.first_name, zip5)
    if existing_person_id is not None:
        return existing_person_id
    return insert_person(conn, person)


def _resolve_organization_id(conn: psycopg.Connection, organization: Organization) -> UUID:
    committee_id = organization.identifiers.get("fec_committee_id")
    if committee_id:
        existing_org_id = find_organization_by_identifier(conn, "fec_committee_id", committee_id)
        if existing_org_id is not None:
            return existing_org_id
    return insert_organization(conn, organization)


def load_contribution(
    conn: psycopg.Connection,
    data_source_id: UUID,
    contribution: dict[str, object],
    *,
    graph_enabled: bool = False,
) -> bool:
    source_record = _build_source_record(data_source_id, contribution)
    source_record_id = try_insert_source_record(conn, source_record)
    if source_record_id is None:
        return False

    extracted = extract_contribution(contribution)
    extracted_address = extracted["address"]
    extracted_person = extracted["person"]
    extracted_organization = extracted["organization"]

    address_id = None
    if extracted_address is not None:
        address_id = upsert_address(conn, extracted_address)
        insert_entity_source(conn, "address", address_id, source_record_id, "contributor_address")

    person_id = _resolve_person_id(conn, extracted_person, extracted_address)
    if person_id is not None:
        insert_entity_source(conn, "person", person_id, source_record_id, "donor")
        if address_id is not None:
            insert_entity_address(conn, "person", person_id, address_id, source_record_id, "mailing")

    organization_id = _resolve_organization_id(conn, extracted_organization)
    insert_entity_source(conn, "organization", organization_id, source_record_id, "recipient")
    if address_id is not None:
        insert_entity_address(conn, "organization", organization_id, address_id, source_record_id, "mailing")

    if graph_enabled:
        if person_id is not None and extracted_person is not None:
            merge_person_node(conn, person_id, extracted_person.canonical_name)
        merge_organization_node(conn, organization_id, extracted_organization.canonical_name)
        amount = contribution.get("contribution_receipt_amount", 0.0)
        date = contribution.get("contribution_receipt_date", "")
        create_contributed_to_edge(
            conn, person_id, organization_id, float(amount or 0), str(date or ""), source_record_id
        )

    return True


def ensure_fec_data_source(conn: psycopg.Connection) -> UUID:
    existing_id = _select_fec_data_source_id(conn)
    if existing_id is not None:
        return existing_id

    data_source = DataSource(
        domain=_FEC_DATA_SOURCE_DOMAIN,
        jurisdiction=_FEC_DATA_SOURCE_JURISDICTION,
        name=_FEC_DATA_SOURCE_NAME,
        source_url=_FEC_SCHEDULE_A_URL,
        source_format="api",
        license="public_domain",
        update_frequency="continuous",
    )
    inserted_id = try_insert_data_source(conn, data_source)
    if inserted_id is not None:
        return inserted_id

    existing_id = _select_fec_data_source_id(conn)
    if existing_id is not None:
        return existing_id

    raise RuntimeError("FEC data source insert reported a conflict, but the existing row could not be selected")
