from __future__ import annotations

from datetime import date
from uuid import UUID

import psycopg
import pytest
from psycopg.rows import dict_row

from domains.property.graph.loader import (
    load_assessed_at_edges,
    load_located_in_edges,
    load_owns_edges,
    load_property_edges,
    load_zoned_as_edges,
)
from domains.property.ingest.durham_source import load_durham_fixture_records, normalize_durham_raw_records
from domains.property.ingest.loader import (
    ensure_durham_data_source,
    ensure_durham_jurisdiction,
    load_durham_records,
)

pytestmark = pytest.mark.integration


def _fixture_records() -> list[dict[str, object]]:
    return normalize_durham_raw_records(load_durham_fixture_records())


def _ingest_fixture(conn: psycopg.Connection) -> tuple[UUID, UUID]:
    records = _fixture_records()
    data_source_id = ensure_durham_data_source(conn)
    jurisdiction_id = ensure_durham_jurisdiction(conn)
    inserted, skipped, errors = load_durham_records(conn, data_source_id, jurisdiction_id, records)
    assert (inserted, skipped, errors) == (len(records), 0, 0)
    return data_source_id, jurisdiction_id


def _count_node(conn: psycopg.Connection, *, label: str, node_id: str) -> int:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT count(*)
            FROM cypher('civibus', $$
                MATCH (n:%s {id: "%s"})
                RETURN n
            $$) AS (v agtype)
            """
            % (label, str(node_id))
        )
        row = cursor.fetchone()

    assert row is not None
    return int(row[0])


def _count_edge(
    conn: psycopg.Connection,
    *,
    source_label: str,
    source_id: str,
    edge_type: str,
    target_label: str,
    target_id: str,
    source_record_id: UUID,
) -> int:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT count(*)
            FROM cypher('civibus', $$
                MATCH (s:%s {id: "%s"})-[e:%s {source_record_id: "%s"}]->(t:%s {id: "%s"})
                RETURN e
            $$) AS (v agtype)
            """
            % (
                source_label,
                str(source_id),
                edge_type,
                str(source_record_id),
                target_label,
                str(target_id),
            )
        )
        row = cursor.fetchone()

    assert row is not None
    return int(row[0])


def _edge_temporal_property(
    conn: psycopg.Connection,
    *,
    source_label: str,
    source_id: str,
    edge_type: str,
    target_label: str,
    target_id: str,
    source_record_id: UUID,
    temporal_property: str,
) -> str | None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT *
            FROM cypher('civibus', $$
                MATCH (s:%s {id: "%s"})-[e:%s {source_record_id: "%s"}]->(t:%s {id: "%s"})
                RETURN e.%s
            $$) AS (v agtype)
            """
            % (
                source_label,
                str(source_id),
                edge_type,
                str(source_record_id),
                target_label,
                str(target_id),
                temporal_property,
            )
        )
        row = cursor.fetchone()

    assert row is not None
    value = row[0]
    return None if value is None else str(value).strip('"')


def _graph_counts(conn: psycopg.Connection) -> dict[str, int]:
    counts: dict[str, int] = {}
    labels = ("Person", "Organization", "Parcel", "Jurisdiction", "ZoningClass", "Assessment")
    edge_types = ("OWNS", "LOCATED_IN", "ZONED_AS", "ASSESSED_AT")

    with conn.cursor() as cursor:
        for label in labels:
            cursor.execute(
                """
                SELECT count(*)
                FROM cypher('civibus', $$
                    MATCH (n:%s)
                    RETURN n
                $$) AS (v agtype)
                """
                % label
            )
            row = cursor.fetchone()
            assert row is not None
            counts[f"node:{label}"] = int(row[0])

        for edge_type in edge_types:
            cursor.execute(
                """
                SELECT count(*)
                FROM cypher('civibus', $$
                    MATCH ()-[e:%s]->()
                    RETURN e
                $$) AS (v agtype)
                """
                % edge_type
            )
            row = cursor.fetchone()
            assert row is not None
            counts[f"edge:{edge_type}"] = int(row[0])

    return counts


def test_load_owns_edges_merges_owner_and_parcel_nodes_with_source_record_keyed_edges(
    graph_conn: psycopg.Connection,
) -> None:
    data_source_id, _ = _ingest_fixture(graph_conn)

    with graph_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT
                o.owner_person_id,
                o.owner_organization_id,
                o.parcel_id,
                o.source_record_id,
                o.ownership_recorded_at
            FROM prop.ownership o
            JOIN core.source_record sr ON sr.id = o.source_record_id
            WHERE sr.data_source_id = %s
              AND sr.superseded_by IS NULL
              AND (o.owner_person_id IS NOT NULL OR o.owner_organization_id IS NOT NULL)
            ORDER BY o.id
            """,
            (data_source_id,),
        )
        owner_rows = cursor.fetchall()

    assert len(owner_rows) > 0

    loaded = load_owns_edges(graph_conn, limit=100)
    assert loaded == len(owner_rows)

    for row in owner_rows:
        parcel_id = row["parcel_id"]
        source_record_id = row["source_record_id"]
        assert isinstance(parcel_id, UUID)
        assert isinstance(source_record_id, UUID)

        owner_person_id = row["owner_person_id"]
        owner_organization_id = row["owner_organization_id"]
        if isinstance(owner_person_id, UUID):
            source_label = "Person"
            source_id = owner_person_id
        else:
            assert isinstance(owner_organization_id, UUID)
            source_label = "Organization"
            source_id = owner_organization_id

        assert _count_node(graph_conn, label=source_label, node_id=str(source_id)) == 1
        assert _count_node(graph_conn, label="Parcel", node_id=str(parcel_id)) == 1
        assert (
            _count_edge(
                graph_conn,
                source_label=source_label,
                source_id=str(source_id),
                edge_type="OWNS",
                target_label="Parcel",
                target_id=str(parcel_id),
                source_record_id=source_record_id,
            )
            == 1
        )
        temporal_value = _edge_temporal_property(
            graph_conn,
            source_label=source_label,
            source_id=str(source_id),
            edge_type="OWNS",
            target_label="Parcel",
            target_id=str(parcel_id),
            source_record_id=source_record_id,
            temporal_property="ownership_recorded_at",
        )
        expected_temporal_value = row["ownership_recorded_at"]
        if isinstance(expected_temporal_value, date):
            assert temporal_value == expected_temporal_value.isoformat()
        else:
            assert temporal_value is None

    rerun_loaded = load_owns_edges(graph_conn, limit=100)
    assert rerun_loaded == loaded

    for row in owner_rows:
        parcel_id = row["parcel_id"]
        source_record_id = row["source_record_id"]
        assert isinstance(parcel_id, UUID)
        assert isinstance(source_record_id, UUID)
        owner_id = row["owner_person_id"] or row["owner_organization_id"]
        assert isinstance(owner_id, UUID)
        owner_label = "Person" if row["owner_person_id"] is not None else "Organization"
        assert (
            _count_edge(
                graph_conn,
                source_label=owner_label,
                source_id=str(owner_id),
                edge_type="OWNS",
                target_label="Parcel",
                target_id=str(parcel_id),
                source_record_id=source_record_id,
            )
            == 1
        )


def test_remaining_property_loaders_create_declared_edges_and_skip_missing_relational_inputs(
    graph_conn: psycopg.Connection,
) -> None:
    data_source_id, jurisdiction_id = _ingest_fixture(graph_conn)

    with graph_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT id
            FROM core.source_record
            WHERE data_source_id = %s
              AND superseded_by IS NULL
            ORDER BY source_record_key
            LIMIT 1
            """,
            (data_source_id,),
        )
        source_record_row = cursor.fetchone()

    assert source_record_row is not None
    skip_source_record_id = source_record_row["id"]
    assert isinstance(skip_source_record_id, UUID)

    skip_located_parcel_id = UUID("00000000-0000-0000-0000-000000000111")
    skip_zoned_parcel_id = UUID("00000000-0000-0000-0000-000000000222")
    skip_assessed_parcel_id = UUID("00000000-0000-0000-0000-000000000333")
    skip_assessment_id = UUID("00000000-0000-0000-0000-000000000444")
    skip_blank_zoned_parcel_id = UUID("00000000-0000-0000-0000-000000000555")

    graph_conn.execute(
        """
        INSERT INTO prop.parcel (id, reid, pin, site_address, zoning_class, jurisdiction_id, source_record_id)
        VALUES (%s, 'skip-located-reid', 'skip-located-pin', 'Skip Located', 'RS-8', NULL, %s)
        """,
        (skip_located_parcel_id, skip_source_record_id),
    )
    graph_conn.execute(
        """
        INSERT INTO prop.parcel (id, reid, pin, site_address, zoning_class, jurisdiction_id, source_record_id)
        VALUES (%s, 'skip-zoned-reid', 'skip-zoned-pin', 'Skip Zoned', NULL, %s, %s)
        """,
        (skip_zoned_parcel_id, jurisdiction_id, skip_source_record_id),
    )
    graph_conn.execute(
        """
        INSERT INTO prop.parcel (id, reid, pin, site_address, zoning_class, jurisdiction_id, source_record_id)
        VALUES (%s, 'skip-assessed-reid', 'skip-assessed-pin', 'Skip Assessed', 'OI', %s, %s)
        """,
        (skip_assessed_parcel_id, jurisdiction_id, skip_source_record_id),
    )
    graph_conn.execute(
        """
        INSERT INTO prop.parcel (id, reid, pin, site_address, zoning_class, jurisdiction_id, source_record_id)
        VALUES (%s, 'skip-blank-zoned-reid', 'skip-blank-zoned-pin', 'Skip Blank Zoned', '   ', %s, %s)
        """,
        (skip_blank_zoned_parcel_id, jurisdiction_id, skip_source_record_id),
    )
    graph_conn.execute(
        """
        INSERT INTO prop.assessment (id, parcel_id, tax_year, assessed_at, source_record_id)
        VALUES (%s, %s, 2025, DATE '2025-01-01', NULL)
        """,
        (skip_assessment_id, skip_assessed_parcel_id),
    )

    with graph_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT
                p.id AS parcel_id,
                p.reid AS parcel_reid,
                p.jurisdiction_id,
                j.name AS jurisdiction_name,
                p.deed_date AS effective_at,
                p.source_record_id
            FROM prop.parcel p
            JOIN core.jurisdiction j
              ON j.id = p.jurisdiction_id
            WHERE p.source_record_id IS NOT NULL
            ORDER BY p.id
            """
        )
        located_rows = cursor.fetchall()

        cursor.execute(
            """
            SELECT
                p.id AS parcel_id,
                p.reid AS parcel_reid,
                NULLIF(BTRIM(p.zoning_class), '') AS zoning_class,
                p.deed_date AS zoned_at,
                p.source_record_id
            FROM prop.parcel p
            WHERE NULLIF(BTRIM(p.zoning_class), '') IS NOT NULL
              AND p.source_record_id IS NOT NULL
            ORDER BY p.id
            """
        )
        zoned_rows = cursor.fetchall()

        cursor.execute(
            """
            SELECT
                p.id AS parcel_id,
                p.reid AS parcel_reid,
                a.id AS assessment_id,
                a.tax_year,
                a.assessed_at,
                a.source_record_id
            FROM prop.assessment a
            JOIN prop.parcel p
              ON p.id = a.parcel_id
            WHERE a.source_record_id IS NOT NULL
            ORDER BY a.id
            """
        )
        assessed_rows = cursor.fetchall()

    loaded_located = load_located_in_edges(graph_conn, limit=100)
    loaded_zoned = load_zoned_as_edges(graph_conn, limit=100)
    loaded_assessed = load_assessed_at_edges(graph_conn, limit=100)

    assert loaded_located == len(located_rows)
    assert loaded_zoned == len(zoned_rows)
    assert loaded_assessed == len(assessed_rows)

    for row in located_rows:
        parcel_id = row["parcel_id"]
        jurisdiction_id = row["jurisdiction_id"]
        source_record_id = row["source_record_id"]
        assert isinstance(parcel_id, UUID)
        assert isinstance(jurisdiction_id, UUID)
        assert isinstance(source_record_id, UUID)
        assert _count_node(graph_conn, label="Parcel", node_id=str(parcel_id)) == 1
        assert _count_node(graph_conn, label="Jurisdiction", node_id=str(jurisdiction_id)) == 1
        assert (
            _count_edge(
                graph_conn,
                source_label="Parcel",
                source_id=str(parcel_id),
                edge_type="LOCATED_IN",
                target_label="Jurisdiction",
                target_id=str(jurisdiction_id),
                source_record_id=source_record_id,
            )
            == 1
        )
        temporal_value = _edge_temporal_property(
            graph_conn,
            source_label="Parcel",
            source_id=str(parcel_id),
            edge_type="LOCATED_IN",
            target_label="Jurisdiction",
            target_id=str(jurisdiction_id),
            source_record_id=source_record_id,
            temporal_property="effective_at",
        )
        expected_temporal_value = row["effective_at"]
        if isinstance(expected_temporal_value, date):
            assert temporal_value == expected_temporal_value.isoformat()
        else:
            assert temporal_value is None

    for row in zoned_rows:
        parcel_id = row["parcel_id"]
        zoning_class = row["zoning_class"]
        source_record_id = row["source_record_id"]
        assert isinstance(parcel_id, UUID)
        assert isinstance(zoning_class, str)
        assert isinstance(source_record_id, UUID)
        assert _count_node(graph_conn, label="Parcel", node_id=str(parcel_id)) == 1
        assert _count_node(graph_conn, label="ZoningClass", node_id=zoning_class) == 1
        assert (
            _count_edge(
                graph_conn,
                source_label="Parcel",
                source_id=str(parcel_id),
                edge_type="ZONED_AS",
                target_label="ZoningClass",
                target_id=zoning_class,
                source_record_id=source_record_id,
            )
            == 1
        )
        temporal_value = _edge_temporal_property(
            graph_conn,
            source_label="Parcel",
            source_id=str(parcel_id),
            edge_type="ZONED_AS",
            target_label="ZoningClass",
            target_id=zoning_class,
            source_record_id=source_record_id,
            temporal_property="zoned_at",
        )
        expected_temporal_value = row["zoned_at"]
        if isinstance(expected_temporal_value, date):
            assert temporal_value == expected_temporal_value.isoformat()
        else:
            assert temporal_value is None

    for row in assessed_rows:
        parcel_id = row["parcel_id"]
        assessment_id = row["assessment_id"]
        source_record_id = row["source_record_id"]
        assert isinstance(parcel_id, UUID)
        assert isinstance(assessment_id, UUID)
        assert isinstance(source_record_id, UUID)
        assert _count_node(graph_conn, label="Parcel", node_id=str(parcel_id)) == 1
        assert _count_node(graph_conn, label="Assessment", node_id=str(assessment_id)) == 1
        assert (
            _count_edge(
                graph_conn,
                source_label="Parcel",
                source_id=str(parcel_id),
                edge_type="ASSESSED_AT",
                target_label="Assessment",
                target_id=str(assessment_id),
                source_record_id=source_record_id,
            )
            == 1
        )
        temporal_value = _edge_temporal_property(
            graph_conn,
            source_label="Parcel",
            source_id=str(parcel_id),
            edge_type="ASSESSED_AT",
            target_label="Assessment",
            target_id=str(assessment_id),
            source_record_id=source_record_id,
            temporal_property="assessed_at",
        )
        expected_temporal_value = row["assessed_at"]
        if isinstance(expected_temporal_value, date):
            assert temporal_value == expected_temporal_value.isoformat()
        else:
            assert temporal_value is None

    assert (
        _count_edge(
            graph_conn,
            source_label="Parcel",
            source_id=str(skip_located_parcel_id),
            edge_type="LOCATED_IN",
            target_label="Jurisdiction",
            target_id=str(jurisdiction_id),
            source_record_id=skip_source_record_id,
        )
        == 0
    )

    with graph_conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT count(*)
            FROM cypher('civibus', $$
                MATCH (p:Parcel {id: "%s"})-[e:ZONED_AS]->(:ZoningClass)
                RETURN e
            $$) AS (v agtype)
            """
            % str(skip_zoned_parcel_id)
        )
        zoned_row = cursor.fetchone()

        cursor.execute(
            """
            SELECT count(*)
            FROM cypher('civibus', $$
                MATCH (p:Parcel {id: "%s"})-[e:ZONED_AS]->(:ZoningClass)
                RETURN e
            $$) AS (v agtype)
            """
            % str(skip_blank_zoned_parcel_id)
        )
        blank_zoned_row = cursor.fetchone()

        cursor.execute(
            """
            SELECT count(*)
            FROM cypher('civibus', $$
                MATCH (p:Parcel {id: "%s"})-[e:ASSESSED_AT]->(a:Assessment {id: "%s"})
                RETURN e
            $$) AS (v agtype)
            """
            % (str(skip_assessed_parcel_id), str(skip_assessment_id))
        )
        assessed_row = cursor.fetchone()

    assert zoned_row is not None
    assert blank_zoned_row is not None
    assert assessed_row is not None
    assert int(zoned_row[0]) == 0
    assert int(blank_zoned_row[0]) == 0
    assert int(assessed_row[0]) == 0
    assert _count_node(graph_conn, label="ZoningClass", node_id="") == 0

    rerun_located = load_located_in_edges(graph_conn, limit=100)
    rerun_zoned = load_zoned_as_edges(graph_conn, limit=100)
    rerun_assessed = load_assessed_at_edges(graph_conn, limit=100)
    assert rerun_located == loaded_located
    assert rerun_zoned == loaded_zoned
    assert rerun_assessed == loaded_assessed


def test_load_property_edges_runs_loaders_in_stable_order_and_is_idempotent(
    graph_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ingest_fixture(graph_conn)

    call_order: list[str] = []
    import domains.property.graph.loader as property_loader

    original_owns = property_loader.load_owns_edges
    original_located = property_loader.load_located_in_edges
    original_zoned = property_loader.load_zoned_as_edges
    original_assessed = property_loader.load_assessed_at_edges

    def owns_wrapper(conn: psycopg.Connection, *, limit: int) -> int:
        call_order.append("load_owns_edges")
        return original_owns(conn, limit=limit)

    def located_wrapper(conn: psycopg.Connection, *, limit: int) -> int:
        call_order.append("load_located_in_edges")
        return original_located(conn, limit=limit)

    def zoned_wrapper(conn: psycopg.Connection, *, limit: int) -> int:
        call_order.append("load_zoned_as_edges")
        return original_zoned(conn, limit=limit)

    def assessed_wrapper(conn: psycopg.Connection, *, limit: int) -> int:
        call_order.append("load_assessed_at_edges")
        return original_assessed(conn, limit=limit)

    monkeypatch.setattr(property_loader, "load_owns_edges", owns_wrapper)
    monkeypatch.setattr(property_loader, "load_located_in_edges", located_wrapper)
    monkeypatch.setattr(property_loader, "load_zoned_as_edges", zoned_wrapper)
    monkeypatch.setattr(property_loader, "load_assessed_at_edges", assessed_wrapper)

    first_total = load_property_edges(graph_conn, limit=100)
    first_snapshot = _graph_counts(graph_conn)
    second_total = load_property_edges(graph_conn, limit=100)
    second_snapshot = _graph_counts(graph_conn)

    assert first_total > 0
    assert second_total == first_total
    assert first_snapshot == second_snapshot
    assert call_order == [
        "load_owns_edges",
        "load_located_in_edges",
        "load_zoned_as_edges",
        "load_assessed_at_edges",
        "load_owns_edges",
        "load_located_in_edges",
        "load_zoned_as_edges",
        "load_assessed_at_edges",
    ]
