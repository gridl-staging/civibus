"""
Stub summary for mar22_03_fec_schedule_e_independent_expenditures/civibus_dev/core/graph/loader_test_support.py.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
import re
from uuid import UUID, uuid4

from psycopg.rows import dict_row

from core.db import insert_data_source, insert_organization, insert_person, insert_source_record
from core.types.python.models import DataSource, Organization, Person, SourceRecord, compute_record_hash, utc_now

_CYPHER_IDENTIFIER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_EDGE_PROJECTION_RE = re.compile(r"^e\.[A-Za-z][A-Za-z0-9_]*$")
_EDGE_ALIAS_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]* agtype$")
_VALID_DATERANGE_BOUNDS = frozenset({"[]", "[)", "(]", "()"})


def _require_cypher_identifier(value: str, *, field_name: str) -> str:
    if not _CYPHER_IDENTIFIER_RE.fullmatch(value):
        raise ValueError(f"Invalid Cypher identifier for {field_name}: {value!r}")
    return value


def _require_edge_projection(value: str) -> str:
    projection_parts = [part.strip() for part in value.split(",")]
    if not projection_parts or any(not _EDGE_PROJECTION_RE.fullmatch(part) for part in projection_parts):
        raise ValueError(f"Invalid edge projection: {value!r}")
    return ", ".join(projection_parts)


def _require_edge_aliases(value: str, *, expected_count: int) -> str:
    alias_parts = [part.strip() for part in value.split(",")]
    if len(alias_parts) != expected_count or any(not _EDGE_ALIAS_RE.fullmatch(part) for part in alias_parts):
        raise ValueError(f"Invalid edge aliases: {value!r}")
    return ", ".join(alias_parts)


def _normalize_valid_period_bounds(bounds: str) -> str:
    if bounds not in _VALID_DATERANGE_BOUNDS:
        raise ValueError(f"valid_period_bounds must be one of {_VALID_DATERANGE_BOUNDS}, got {bounds!r}")
    return bounds


def count_edge(conn, *, source_label: str, source_id: UUID, edge_type: str, target_label: str, target_id: UUID) -> int:
    safe_source_label = _require_cypher_identifier(source_label, field_name="source_label")
    safe_edge_type = _require_cypher_identifier(edge_type, field_name="edge_type")
    safe_target_label = _require_cypher_identifier(target_label, field_name="target_label")
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT count(*)
            FROM cypher('civibus', $$
                MATCH (s:%s {id: "%s"})-[e:%s]->(t:%s {id: "%s"})
                RETURN e
            $$) AS (v agtype)
            """
            % (safe_source_label, source_id, safe_edge_type, safe_target_label, target_id)
        )
        return cur.fetchone()[0]


def edge_properties(
    conn,
    *,
    edge_type: str,
    source_record_id: UUID,
    projection: str,
    aliases: str,
) -> dict[str, str | None]:
    safe_edge_type = _require_cypher_identifier(edge_type, field_name="edge_type")
    safe_projection = _require_edge_projection(projection)
    safe_aliases = _require_edge_aliases(aliases, expected_count=len([part for part in safe_projection.split(",")]))
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT * FROM cypher('civibus', $$
                MATCH ()-[e:%s {source_record_id: "%s"}]->()
                RETURN %s
            $$) AS (%s)
            """
            % (safe_edge_type, source_record_id, safe_projection, safe_aliases)
        )
        row = cur.fetchone()

    assert row is not None
    result: dict[str, str | None] = {}
    for key, value in row.items():
        result[key] = None if value is None else str(value).strip('"')
    return result


def seed_data_source(conn, *, label: str) -> UUID:
    data_source = DataSource(
        domain="campaign_finance",
        jurisdiction="test/stage3",
        name=f"Graph Loader Test {label} {uuid4()}",
        source_url="https://example.test/graph-loader",
        source_format="csv",
    )
    insert_data_source(conn, data_source)
    return data_source.id


def seed_source_record(conn, *, data_source_id: UUID, key: str) -> UUID:
    raw_fields = {"source_record_key": key}
    source_record = SourceRecord(
        data_source_id=data_source_id,
        source_record_key=key,
        raw_fields=raw_fields,
        pull_date=utc_now(),
        record_hash=compute_record_hash(raw_fields),
    )
    return insert_source_record(conn, source_record)


def seed_person(conn, *, name: str) -> UUID:
    person = Person(
        canonical_name=name,
        first_name=name.split()[0],
        last_name=name.split()[-1],
    )
    return insert_person(conn, person)


def seed_org(conn, *, name: str, identifiers: dict[str, str] | None = None) -> UUID:
    organization = Organization(canonical_name=name, identifiers=identifiers or {})
    return insert_organization(conn, organization)


def seed_committee(conn, *, name: str, organization_id: UUID | None = None) -> UUID:
    committee_id = uuid4()
    fec_committee_id = f"C{committee_id.int % 100_000_000:08d}"
    conn.execute(
        """
        INSERT INTO cf.committee (id, fec_committee_id, name, organization_id, state)
        VALUES (%s, %s, %s, %s, 'NC')
        """,
        (committee_id, fec_committee_id, name, organization_id),
    )
    return committee_id


def seed_candidate(conn, *, name: str) -> UUID:
    candidate_id = uuid4()
    fec_candidate_id = f"H{candidate_id.int % 10}NC{candidate_id.int % 100000:05d}"
    conn.execute(
        """
        INSERT INTO cf.candidate (id, fec_candidate_id, name, office, state, district)
        VALUES (%s, %s, %s, 'H', 'NC', '01')
        """,
        (candidate_id, fec_candidate_id, name),
    )
    return candidate_id


def seed_filing(
    conn,
    *,
    committee_id: UUID,
    source_record_id: UUID,
    filing_fec_id: str | None = None,
    report_type: str | None = None,
    receipt_date: date | None = None,
    due_date: date | None = None,
    accepted_date: date | None = None,
) -> UUID:
    filing_id = uuid4()
    conn.execute(
        """
        INSERT INTO cf.filing (
            id, filing_fec_id, committee_id, amendment_indicator, source_record_id,
            report_type, receipt_date, due_date, accepted_date
        )
        VALUES (%s, %s, %s, 'N', %s, %s, %s, %s, %s)
        """,
        (
            filing_id,
            filing_fec_id or f"FEC-{filing_id.hex[:12]}",
            committee_id,
            source_record_id,
            report_type,
            receipt_date,
            due_date,
            accepted_date,
        ),
    )
    return filing_id


def seed_transaction(
    conn,
    *,
    transaction_id: UUID | None = None,
    filing_id: UUID,
    committee_id: UUID,
    source_record_id: UUID,
    transaction_type: str,
    amount: Decimal,
    transaction_date: date,
    contributor_person_id: UUID | None = None,
    contributor_organization_id: UUID | None = None,
    recipient_candidate_id: UUID | None = None,
    support_oppose: str | None = None,
    transaction_identifier: str | None = None,
) -> UUID:
    transaction_id = transaction_id or uuid4()
    conn.execute(
        """
        INSERT INTO cf.transaction (
            id, filing_id, committee_id, transaction_type, amount, transaction_date,
            contributor_person_id, contributor_organization_id,
            recipient_candidate_id, support_oppose,
            transaction_identifier, amendment_indicator, source_record_id
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'N', %s)
        """,
        (
            transaction_id,
            filing_id,
            committee_id,
            transaction_type,
            amount,
            transaction_date,
            contributor_person_id,
            contributor_organization_id,
            recipient_candidate_id,
            support_oppose,
            transaction_identifier or f"txn-{transaction_id.hex}",
            source_record_id,
        ),
    )
    return transaction_id


def seed_entity_source(
    conn,
    *,
    entity_type: str,
    entity_id: UUID,
    source_record_id: UUID,
    extraction_role: str,
) -> None:
    conn.execute(
        """
        INSERT INTO core.entity_source (id, entity_type, entity_id, source_record_id, extraction_role)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (uuid4(), entity_type, entity_id, source_record_id, extraction_role),
    )


def seed_candidate_committee_link(
    conn,
    *,
    candidate_id: UUID,
    committee_id: UUID,
    source_record_id: UUID,
    designation: str,
    candidate_election_year: int,
    fec_election_year: int,
    valid_period_start: date | None,
    valid_period_end: date | None,
    valid_period_bounds: str = "[)",
) -> UUID:
    link_id = uuid4()
    normalized_bounds = _normalize_valid_period_bounds(valid_period_bounds)
    conn.execute(
        """
        INSERT INTO cf.candidate_committee_link (
            id, candidate_id, committee_id, designation,
            candidate_election_year, fec_election_year,
            valid_period, source_record_id
        )
        VALUES (%s, %s, %s, %s, %s, %s, daterange(%s, %s, %s), %s)
        """,
        (
            link_id,
            candidate_id,
            committee_id,
            designation,
            candidate_election_year,
            fec_election_year,
            valid_period_start,
            valid_period_end,
            normalized_bounds,
            source_record_id,
        ),
    )
    return link_id
