
from __future__ import annotations

from collections.abc import Callable

import psycopg

BOOTSTRAP_CANARIES = (
    "civic.officeholding.date_precision",
    "core.person_er_view",
    "core.organization_er_view",
    "core.match_decision",
    "ag_catalog.ag_graph.civibus",
)


def _column_exists(conn: psycopg.Connection, schema_name: str, table_name: str, column_name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = %s
                  AND table_name = %s
                  AND column_name = %s
            )
            """,
            (schema_name, table_name, column_name),
        )
        row = cur.fetchone()
    return bool(row and row[0])


def _relation_exists(conn: psycopg.Connection, schema_name: str, relation_name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass(%s) IS NOT NULL", (f"{schema_name}.{relation_name}",))
        row = cur.fetchone()
    return bool(row and row[0])


def _graph_exists(conn: psycopg.Connection, graph_name: str) -> bool:
    with conn.cursor() as cur:
        try:
            cur.execute("SELECT 1 FROM ag_catalog.ag_graph WHERE name = %s", (graph_name,))
        except (psycopg.errors.InvalidSchemaName, psycopg.errors.UndefinedTable):
            return False
        return cur.fetchone() is not None


def _stage1_canary_checks() -> tuple[tuple[str, Callable[[psycopg.Connection], bool]], ...]:
    return (
        (
            BOOTSTRAP_CANARIES[0],
            lambda conn: _column_exists(conn, "civic", "officeholding", "date_precision"),
        ),
        (
            BOOTSTRAP_CANARIES[1],
            lambda conn: _relation_exists(conn, "core", "person_er_view"),
        ),
        (
            BOOTSTRAP_CANARIES[2],
            lambda conn: _relation_exists(conn, "core", "organization_er_view"),
        ),
        (
            BOOTSTRAP_CANARIES[3],
            lambda conn: _relation_exists(conn, "core", "match_decision"),
        ),
        (
            BOOTSTRAP_CANARIES[4],
            lambda conn: _graph_exists(conn, "civibus"),
        ),
    )


def _collect_missing_stage1_canaries(conn: psycopg.Connection) -> list[str]:
    canary_checks = _stage1_canary_checks()
    assert tuple(canary_name for canary_name, _ in canary_checks) == BOOTSTRAP_CANARIES
    return [canary_name for canary_name, check_exists in canary_checks if not check_exists(conn)]
