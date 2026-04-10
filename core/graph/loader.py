
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from core.graph import _escape_cypher_literal, _execute_formatted_cypher

# ---------------------------------------------------------------------------
# Transaction-type routing — canonical allowlists
#
# Stage 3 edge loaders must import these constants instead of inlining
# transaction-type string comparisons. The classifier function below is
# the single routing decision point.
# ---------------------------------------------------------------------------

CONTRIBUTION_LIKE_TYPES: frozenset[str] = frozenset(
    {
        "Monetary (Itemized)",
        "Monetary (Non-Itemized)",
        "Monetary",
    }
)

EXPENDITURE_LIKE_TYPES: frozenset[str] = frozenset(
    {
        "Expenditure (Itemized)",
        "Expenditure (Non-Itemized)",
        "Independent Expenditure",
    }
)


def classify_transaction_type(transaction_type: str) -> str | None:
    """Classify a cf.transaction.transaction_type value into a routing bucket."""
    if transaction_type in CONTRIBUTION_LIKE_TYPES:
        return "contribution"
    if transaction_type in EXPENDITURE_LIKE_TYPES:
        return "expenditure"
    return None


@dataclass(frozen=True, slots=True)
class _NodeRef:
    label: str
    node_id: UUID
    canonical_name: str


_TRANSACTION_EDGE_ROWS_QUERY = """
    SELECT
        t.id AS transaction_id,
        t.committee_id,
        c.name AS committee_name,
        t.contributor_person_id,
        p.canonical_name AS contributor_person_name,
        t.contributor_organization_id,
        o.canonical_name AS contributor_organization_name,
        t.amount,
        t.transaction_date,
        t.transaction_type,
        t.filing_id,
        t.source_record_id
    FROM cf.transaction t
    JOIN cf.committee c
      ON c.id = t.committee_id
    LEFT JOIN core.person p
      ON p.id = t.contributor_person_id
    LEFT JOIN core.organization o
      ON o.id = t.contributor_organization_id
    WHERE t.transaction_type = ANY(%s)
      AND t.support_oppose IS NULL
    ORDER BY t.id
    LIMIT %s
"""

_IE_EDGE_ROWS_QUERY = """
    SELECT
        t.id AS transaction_id,
        t.committee_id,
        c.name AS committee_name,
        t.recipient_candidate_id AS candidate_id,
        cand.name AS candidate_name,
        t.support_oppose,
        t.amount,
        t.transaction_date,
        t.transaction_type,
        t.filing_id,
        t.source_record_id
    FROM cf.transaction t
    JOIN cf.committee c
      ON c.id = t.committee_id
    JOIN cf.candidate cand
      ON cand.id = t.recipient_candidate_id
    WHERE t.support_oppose IS NOT NULL
    ORDER BY t.id
    LIMIT %s
"""

_AFFILIATED_EDGE_ROWS_QUERY = """
    SELECT
        link.id,
        link.candidate_id,
        cand.name AS candidate_name,
        link.committee_id,
        cmte.name AS committee_name,
        link.designation,
        link.candidate_election_year,
        link.fec_election_year,
        link.valid_period,
        link.source_record_id
    FROM cf.candidate_committee_link link
    JOIN cf.candidate cand
      ON cand.id = link.candidate_id
    JOIN cf.committee cmte
      ON cmte.id = link.committee_id
    ORDER BY link.id
    LIMIT %s
"""

_FILED_EDGE_ROWS_QUERY = """
    SELECT
        f.id,
        f.filing_fec_id,
        f.committee_id,
        c.name AS committee_name,
        f.receipt_date,
        f.due_date,
        f.accepted_date,
        f.report_type,
        f.source_record_id
    FROM cf.filing f
    JOIN cf.committee c
      ON c.id = f.committee_id
    ORDER BY f.id
    LIMIT %s
"""


def _require_nonnegative_limit(limit: int) -> None:
    if limit < 0:
        raise ValueError("limit must be >= 0")


def _merge_named_node(conn: psycopg.Connection, label: str, node_id: str | UUID, canonical_name: str) -> None:
    safe_id = _escape_cypher_literal(str(node_id))
    safe_name = _escape_cypher_literal(canonical_name)
    _execute_formatted_cypher(
        conn,
        f"""
            MERGE (n:{label} {{id: "%s"}})
            SET n.canonical_name = "%s"
        """,
        safe_id,
        safe_name,
    )


def merge_person_node(conn: psycopg.Connection, person_id: UUID, canonical_name: str) -> None:
    _merge_named_node(conn, "Person", person_id, canonical_name)


def merge_organization_node(conn: psycopg.Connection, org_id: UUID, canonical_name: str) -> None:
    _merge_named_node(conn, "Organization", org_id, canonical_name)


def merge_committee_node(conn: psycopg.Connection, committee_id: UUID, canonical_name: str) -> None:
    _merge_named_node(conn, "Committee", committee_id, canonical_name)


def merge_candidate_node(conn: psycopg.Connection, candidate_id: UUID, canonical_name: str) -> None:
    _merge_named_node(conn, "Candidate", candidate_id, canonical_name)


def merge_filing_node(conn: psycopg.Connection, filing_id: UUID, canonical_name: str) -> None:
    _merge_named_node(conn, "Filing", filing_id, canonical_name)


# -- Civic domain node merge helpers --


def merge_office_node(conn: psycopg.Connection, node_id: UUID, canonical_name: str) -> None:
    _merge_named_node(conn, "Office", node_id, canonical_name)


def merge_electoral_division_node(conn: psycopg.Connection, node_id: UUID, canonical_name: str) -> None:
    _merge_named_node(conn, "ElectoralDivision", node_id, canonical_name)


def merge_contest_node(conn: psycopg.Connection, node_id: UUID, canonical_name: str) -> None:
    _merge_named_node(conn, "Contest", node_id, canonical_name)


def merge_candidacy_node(conn: psycopg.Connection, node_id: UUID, canonical_name: str) -> None:
    _merge_named_node(conn, "Candidacy", node_id, canonical_name)


def merge_officeholding_node(conn: psycopg.Connection, node_id: UUID, canonical_name: str) -> None:
    _merge_named_node(conn, "Officeholding", node_id, canonical_name)


def _merge_node_ref(conn: psycopg.Connection, node: _NodeRef) -> None:
    merge_node = {
        "Person": merge_person_node,
        "Organization": merge_organization_node,
        "Committee": merge_committee_node,
        "Candidate": merge_candidate_node,
        "Filing": merge_filing_node,
        "Office": merge_office_node,
        "ElectoralDivision": merge_electoral_division_node,
        "Contest": merge_contest_node,
        "Candidacy": merge_candidacy_node,
        "Officeholding": merge_officeholding_node,
    }.get(node.label)
    if merge_node is None:
        raise ValueError(f"Unsupported node label: {node.label}")
    merge_node(conn, node.node_id, node.canonical_name)


def _merge_node_ref_edge(
    conn: psycopg.Connection,
    *,
    source_node: _NodeRef,
    target_node: _NodeRef,
    edge_type: str,
    properties: dict[str, object],
) -> None:
    _merge_node_ref(conn, source_node)
    _merge_node_ref(conn, target_node)
    _merge_cf_edge(
        conn,
        (source_node.label, source_node.node_id),
        (target_node.label, target_node.node_id),
        edge_type,
        properties,
    )


def _merge_edge_with_source_record_id(
    conn: psycopg.Connection,
    *,
    source: tuple[str, str | UUID],
    target: tuple[str, str | UUID],
    edge_type: str,
    properties: dict[str, object],
) -> None:
    """MERGE an edge keyed by source_record_id and set non-null properties."""
    source_label, source_id = source
    target_label, target_id = target
    source_record_id = properties.get("source_record_id")
    if not isinstance(source_record_id, str):
        return

    safe_source_id = _escape_cypher_literal(str(source_id))
    safe_target_id = _escape_cypher_literal(str(target_id))
    safe_source_record_id = _escape_cypher_literal(source_record_id)

    set_fragments: list[str] = []
    format_args: list[object] = [safe_source_id, safe_target_id, safe_source_record_id]

    for key in sorted(properties):
        if key == "source_record_id":
            continue
        value = properties[key]
        if value is None:
            continue
        if isinstance(value, str):
            set_fragments.append(f'e.{key} = "%s"')
            format_args.append(_escape_cypher_literal(value))
            continue
        if isinstance(value, Decimal):
            set_fragments.append(f"e.{key} = %s")
            format_args.append(float(value))
            continue
        set_fragments.append(f"e.{key} = %s")
        format_args.append(value)

    set_clause = f"\n            SET {', '.join(set_fragments)}" if set_fragments else ""
    _execute_formatted_cypher(
        conn,
        f"""
            MATCH (s:{source_label} {{id: "%s"}}), (t:{target_label} {{id: "%s"}})
            MERGE (s)-[e:{edge_type} {{source_record_id: "%s"}}]->(t){set_clause}
        """,
        *format_args,
    )


def _merge_cf_edge(
    conn: psycopg.Connection,
    source: tuple[str, UUID],
    target: tuple[str, UUID],
    edge_type: str,
    properties: dict[str, object],
) -> None:
    """MERGE a CF edge between two pre-existing nodes with idempotent properties."""
    _merge_edge_with_source_record_id(
        conn,
        source=source,
        target=target,
        edge_type=edge_type,
        properties=properties,
    )


# ---------------------------------------------------------------------------
# Row normalization and lookups
# ---------------------------------------------------------------------------


def _fetch_dict_rows(conn: psycopg.Connection, query: str, params: tuple[object, ...]) -> list[dict[str, object]]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(query, params)
        return list(cursor.fetchall())


def _fetch_transaction_rows(
    conn: psycopg.Connection,
    *,
    limit: int,
    allowed_types: frozenset[str],
) -> list[dict[str, object]]:
    return _fetch_dict_rows(
        conn,
        _TRANSACTION_EDGE_ROWS_QUERY,
        (sorted(allowed_types), limit),
    )


def _serialize_date(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _serialize_valid_period(valid_period: object) -> str | None:
    if valid_period is None:
        return None
    if isinstance(valid_period, str):
        return valid_period

    lower_value = getattr(valid_period, "lower", None)
    upper_value = getattr(valid_period, "upper", None)
    bounds = getattr(valid_period, "bounds", "[)")

    if not isinstance(bounds, str) or len(bounds) != 2:
        bounds = "[)"

    lower_text = "-infinity" if lower_value is None else _serialize_date(lower_value)
    upper_text = "infinity" if upper_value is None else _serialize_date(upper_value)
    return f"{bounds[0]}{lower_text},{upper_text}{bounds[1]}"


def _normalize_transaction_edge_properties(row: dict[str, object]) -> dict[str, object] | None:
    source_record_id = row.get("source_record_id")
    filing_id = row.get("filing_id")
    if not isinstance(source_record_id, UUID) or not isinstance(filing_id, UUID):
        return None

    amount_value = row.get("amount")
    normalized_amount: float | None = None if amount_value is None else float(amount_value)

    return {
        "amount": normalized_amount,
        "transaction_date": _serialize_date(row.get("transaction_date")),
        "transaction_type": row.get("transaction_type"),
        "filing_id": str(filing_id),
        "source_record_id": str(source_record_id),
    }


def _normalize_affiliated_edge_properties(row: dict[str, object]) -> dict[str, object] | None:
    source_record_id = row.get("source_record_id")
    if not isinstance(source_record_id, UUID):
        return None

    return {
        "designation": row.get("designation"),
        "candidate_election_year": row.get("candidate_election_year"),
        "fec_election_year": row.get("fec_election_year"),
        "valid_period": _serialize_valid_period(row.get("valid_period")),
        "source_record_id": str(source_record_id),
    }


def _normalize_filed_edge_properties(row: dict[str, object]) -> dict[str, object] | None:
    source_record_id = row.get("source_record_id")
    if not isinstance(source_record_id, UUID):
        return None

    return {
        "receipt_date": _serialize_date(row.get("receipt_date")),
        "due_date": _serialize_date(row.get("due_date")),
        "accepted_date": _serialize_date(row.get("accepted_date")),
        "report_type": row.get("report_type"),
        "source_record_id": str(source_record_id),
    }


def _resolve_entity_source_counterparties(
    conn: psycopg.Connection,
    *,
    source_record_ids: list[UUID],
    roles: tuple[str, ...],
) -> dict[UUID, _NodeRef | None]:
    if not source_record_ids:
        return {}

    results: dict[UUID, list[_NodeRef]] = {source_record_id: [] for source_record_id in source_record_ids}
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT
                es.source_record_id,
                es.entity_type,
                es.entity_id,
                CASE
                    WHEN es.entity_type = 'person' THEN p.canonical_name
                    ELSE o.canonical_name
                END AS canonical_name
            FROM core.entity_source es
            LEFT JOIN core.person p
              ON es.entity_type = 'person'
             AND p.id = es.entity_id
            LEFT JOIN core.organization o
              ON es.entity_type = 'organization'
             AND o.id = es.entity_id
            WHERE es.source_record_id = ANY(%s)
              AND es.extraction_role = ANY(%s)
              AND es.entity_type IN ('person', 'organization')
            ORDER BY es.source_record_id, es.created_at, es.id
            """,
            (source_record_ids, list(roles)),
        )
        rows = cursor.fetchall()

    for row in rows:
        source_record_id = row["source_record_id"]
        entity_type = row["entity_type"]
        entity_id = row["entity_id"]
        canonical_name = row["canonical_name"]

        if not isinstance(source_record_id, UUID):
            continue
        if not isinstance(entity_id, UUID):
            continue
        if not isinstance(canonical_name, str):
            continue

        label = "Person" if entity_type == "person" else "Organization"
        if source_record_id in results:
            results[source_record_id].append(_NodeRef(label=label, node_id=entity_id, canonical_name=canonical_name))

    return {source_record_id: nodes[0] if len(nodes) == 1 else None for source_record_id, nodes in results.items()}


def _counterparty_node_from_row(
    row: dict[str, object],
    *,
    fallback_counterparty_by_source_record_id: dict[UUID, _NodeRef | None],
) -> _NodeRef | None:
    person_id = row.get("contributor_person_id")
    person_name = row.get("contributor_person_name")
    if isinstance(person_id, UUID) and isinstance(person_name, str):
        return _NodeRef(label="Person", node_id=person_id, canonical_name=person_name)

    organization_id = row.get("contributor_organization_id")
    organization_name = row.get("contributor_organization_name")
    if isinstance(organization_id, UUID) and isinstance(organization_name, str):
        return _NodeRef(label="Organization", node_id=organization_id, canonical_name=organization_name)

    source_record_id = row.get("source_record_id")
    if not isinstance(source_record_id, UUID):
        return None
    return fallback_counterparty_by_source_record_id.get(source_record_id)


def _source_record_ids_needing_fallback(
    rows: list[dict[str, object]],
    *,
    route_name: str,
) -> list[UUID]:
    source_record_ids: list[UUID] = []
    for row in rows:
        transaction_type = row.get("transaction_type")
        if not isinstance(transaction_type, str):
            continue
        if classify_transaction_type(transaction_type) != route_name:
            continue
        if row.get("contributor_person_id") is not None or row.get("contributor_organization_id") is not None:
            continue
        source_record_id = row.get("source_record_id")
        if isinstance(source_record_id, UUID):
            source_record_ids.append(source_record_id)
    return source_record_ids


def _row_matches_route(row: dict[str, object], route_name: str) -> bool:
    transaction_type = row.get("transaction_type")
    return isinstance(transaction_type, str) and classify_transaction_type(transaction_type) == route_name


def _node_ref_from_row(
    row: dict[str, object],
    *,
    node_id_key: str,
    canonical_name_key: str,
    label: str,
) -> _NodeRef | None:
    node_id = row.get(node_id_key)
    canonical_name = row.get(canonical_name_key)
    if not isinstance(node_id, UUID) or not isinstance(canonical_name, str):
        return None
    return _NodeRef(label=label, node_id=node_id, canonical_name=canonical_name)


def _contributed_to_nodes_from_row(
    row: dict[str, object],
    *,
    fallback_counterparty_by_source_record_id: dict[UUID, _NodeRef | None],
) -> tuple[_NodeRef, _NodeRef] | None:
    counterparty = _counterparty_node_from_row(
        row,
        fallback_counterparty_by_source_record_id=fallback_counterparty_by_source_record_id,
    )
    committee = _node_ref_from_row(
        row, node_id_key="committee_id", canonical_name_key="committee_name", label="Committee"
    )
    if counterparty is None or committee is None:
        return None
    return counterparty, committee


def _spent_on_nodes_from_row(
    row: dict[str, object],
    *,
    fallback_counterparty_by_source_record_id: dict[UUID, _NodeRef | None],
) -> tuple[_NodeRef, _NodeRef] | None:
    committee = _node_ref_from_row(
        row, node_id_key="committee_id", canonical_name_key="committee_name", label="Committee"
    )
    counterparty = _counterparty_node_from_row(
        row,
        fallback_counterparty_by_source_record_id=fallback_counterparty_by_source_record_id,
    )
    if committee is None or counterparty is None:
        return None
    return committee, counterparty


def _load_transaction_edges(
    conn: psycopg.Connection,
    *,
    limit: int,
    allowed_types: frozenset[str],
    route_name: str,
    fallback_roles: tuple[str, ...],
    edge_type: str,
    node_pair_from_row: Callable[..., tuple[_NodeRef, _NodeRef] | None],
) -> int:
    rows = _fetch_transaction_rows(conn, limit=limit, allowed_types=allowed_types)
    fallback_map = _resolve_entity_source_counterparties(
        conn,
        source_record_ids=_source_record_ids_needing_fallback(rows, route_name=route_name),
        roles=fallback_roles,
    )

    edge_count = 0
    for row in rows:
        if not _row_matches_route(row, route_name):
            continue

        node_pair = node_pair_from_row(
            row,
            fallback_counterparty_by_source_record_id=fallback_map,
        )
        properties = _normalize_transaction_edge_properties(row)
        if node_pair is None or properties is None:
            continue

        source_node, target_node = node_pair
        _merge_node_ref_edge(
            conn,
            source_node=source_node,
            target_node=target_node,
            edge_type=edge_type,
            properties=properties,
        )
        edge_count += 1

    return edge_count


# ---------------------------------------------------------------------------
# Stage 3 public loaders
# ---------------------------------------------------------------------------


def load_contributed_to_edges(conn: psycopg.Connection, *, limit: int) -> int:
    _require_nonnegative_limit(limit)

    return _load_transaction_edges(
        conn,
        limit=limit,
        allowed_types=CONTRIBUTION_LIKE_TYPES,
        route_name="contribution",
        fallback_roles=("donor", "contributor"),
        edge_type="CONTRIBUTED_TO",
        node_pair_from_row=_contributed_to_nodes_from_row,
    )


def load_spent_on_edges(conn: psycopg.Connection, *, limit: int) -> int:
    _require_nonnegative_limit(limit)

    return _load_transaction_edges(
        conn,
        limit=limit,
        allowed_types=EXPENDITURE_LIKE_TYPES,
        route_name="expenditure",
        fallback_roles=("payee",),
        edge_type="SPENT_ON",
        node_pair_from_row=_spent_on_nodes_from_row,
    )


def load_ie_edges(conn: psycopg.Connection, *, limit: int) -> int:
    _require_nonnegative_limit(limit)

    rows = _fetch_dict_rows(conn, _IE_EDGE_ROWS_QUERY, (limit,))
    edge_count = 0

    for row in rows:
        committee = _node_ref_from_row(
            row,
            node_id_key="committee_id",
            canonical_name_key="committee_name",
            label="Committee",
        )
        candidate = _node_ref_from_row(
            row,
            node_id_key="candidate_id",
            canonical_name_key="candidate_name",
            label="Candidate",
        )
        properties = _normalize_transaction_edge_properties(row)

        support_oppose = row.get("support_oppose")
        if support_oppose == "S":
            edge_type = "SUPPORTS"
        elif support_oppose == "O":
            edge_type = "OPPOSES"
        else:
            continue

        if committee is None or candidate is None or properties is None:
            continue

        _merge_node_ref_edge(
            conn,
            source_node=committee,
            target_node=candidate,
            edge_type=edge_type,
            properties=properties,
        )
        edge_count += 1

    return edge_count


def load_affiliated_with_edges(conn: psycopg.Connection, *, limit: int) -> int:
    _require_nonnegative_limit(limit)

    rows = _fetch_dict_rows(conn, _AFFILIATED_EDGE_ROWS_QUERY, (limit,))
    edge_count = 0

    for row in rows:
        candidate = _node_ref_from_row(
            row,
            node_id_key="candidate_id",
            canonical_name_key="candidate_name",
            label="Candidate",
        )
        committee = _node_ref_from_row(
            row,
            node_id_key="committee_id",
            canonical_name_key="committee_name",
            label="Committee",
        )
        properties = _normalize_affiliated_edge_properties(row)

        if candidate is None or committee is None or properties is None:
            continue

        _merge_node_ref_edge(
            conn,
            source_node=candidate,
            target_node=committee,
            edge_type="AFFILIATED_WITH",
            properties=properties,
        )
        edge_count += 1

    return edge_count


def load_filed_edges(conn: psycopg.Connection, *, limit: int) -> int:
    _require_nonnegative_limit(limit)

    rows = _fetch_dict_rows(conn, _FILED_EDGE_ROWS_QUERY, (limit,))
    edge_count = 0

    for row in rows:
        committee = _node_ref_from_row(
            row,
            node_id_key="committee_id",
            canonical_name_key="committee_name",
            label="Committee",
        )
        filing = _node_ref_from_row(
            row,
            node_id_key="id",
            canonical_name_key="filing_fec_id",
            label="Filing",
        )
        properties = _normalize_filed_edge_properties(row)

        if committee is None or filing is None or properties is None:
            continue

        _merge_node_ref_edge(
            conn,
            source_node=committee,
            target_node=filing,
            edge_type="FILED",
            properties=properties,
        )
        edge_count += 1

    return edge_count


# ---------------------------------------------------------------------------
# Legacy edge helper — isolated for Stage 4 replacement
# ---------------------------------------------------------------------------


def create_contributed_to_edge(
    conn: psycopg.Connection,
    person_id: UUID | None,
    org_id: UUID,
    amount: float,
    transaction_date: str,
    source_record_id: UUID,
) -> None:
    if person_id is None:
        return

    safe_pid = _escape_cypher_literal(str(person_id))
    safe_oid = _escape_cypher_literal(str(org_id))
    safe_transaction_date = _escape_cypher_literal(transaction_date)
    safe_srid = _escape_cypher_literal(str(source_record_id))
    _execute_formatted_cypher(
        conn,
        """
            MATCH (p:Person {id: "%s"}), (o:Organization {id: "%s"})
            CREATE (p)-[:CONTRIBUTED_TO {amount: %s, transaction_date: "%s", source_record_id: "%s"}]->(o)
        """,
        safe_pid,
        safe_oid,
        amount,
        safe_transaction_date,
        safe_srid,
    )
