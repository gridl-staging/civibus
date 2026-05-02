
from __future__ import annotations

from collections.abc import Callable

import psycopg

BOOTSTRAP_CANARIES = (
    "civic.officeholding.date_precision",
    "civic.candidacy.name_on_ballot",
    "civic.candidacy.is_unexpired_term",
    "civic.candidacy.raw_fields",
    "civic.candidacy.committee_id",
    "civic.idx_candidacy_committee_id",
    "civic.idx_candidacy_name_on_ballot",
    "civic.contest_result",
    "civic.uq_contest_result_canonical",
    "civic.trg_contest_result_updated_at",
    "civic.contest_result.candidate_name",
    "civic.contest_result.party",
    "civic.contest_result.votes",
    "civic.contest_result.vote_pct",
    "civic.contest_result.is_certified",
    "core.person.bio_text",
    "core.person.bio_source_url",
    "core.person.bio_license",
    "core.person.bio_pulled_at",
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


def _index_exists(conn: psycopg.Connection, schema_name: str, index_name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM pg_indexes
                WHERE schemaname = %s
                  AND indexname = %s
            )
            """,
            (schema_name, index_name),
        )
        row = cur.fetchone()
    return bool(row and row[0])


def _constraint_exists(conn: psycopg.Connection, schema_name: str, table_name: str, constraint_name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM pg_constraint con
                JOIN pg_class rel ON rel.oid = con.conrelid
                JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
                WHERE nsp.nspname = %s
                  AND rel.relname = %s
                  AND con.conname = %s
            )
            """,
            (schema_name, table_name, constraint_name),
        )
        row = cur.fetchone()
    return bool(row and row[0])


def _trigger_exists(conn: psycopg.Connection, schema_name: str, table_name: str, trigger_name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM pg_trigger t
                JOIN pg_class c ON c.oid = t.tgrelid
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = %s
                  AND c.relname = %s
                  AND t.tgname = %s
                  AND NOT t.tgisinternal
            )
            """,
            (schema_name, table_name, trigger_name),
        )
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
            lambda conn: _column_exists(conn, "civic", "candidacy", "name_on_ballot"),
        ),
        (
            BOOTSTRAP_CANARIES[2],
            lambda conn: _column_exists(conn, "civic", "candidacy", "is_unexpired_term"),
        ),
        (
            BOOTSTRAP_CANARIES[3],
            lambda conn: _column_exists(conn, "civic", "candidacy", "raw_fields"),
        ),
        (
            BOOTSTRAP_CANARIES[4],
            lambda conn: _column_exists(conn, "civic", "candidacy", "committee_id"),
        ),
        (
            BOOTSTRAP_CANARIES[5],
            lambda conn: _index_exists(conn, "civic", "idx_candidacy_committee_id"),
        ),
        (
            BOOTSTRAP_CANARIES[6],
            lambda conn: _index_exists(conn, "civic", "idx_candidacy_name_on_ballot"),
        ),
        (
            BOOTSTRAP_CANARIES[7],
            lambda conn: _relation_exists(conn, "civic", "contest_result"),
        ),
        (
            BOOTSTRAP_CANARIES[8],
            lambda conn: _constraint_exists(conn, "civic", "contest_result", "uq_contest_result_canonical"),
        ),
        (
            BOOTSTRAP_CANARIES[9],
            lambda conn: _trigger_exists(conn, "civic", "contest_result", "trg_contest_result_updated_at"),
        ),
        (
            BOOTSTRAP_CANARIES[10],
            lambda conn: _column_exists(conn, "civic", "contest_result", "candidate_name"),
        ),
        (
            BOOTSTRAP_CANARIES[11],
            lambda conn: _column_exists(conn, "civic", "contest_result", "party"),
        ),
        (
            BOOTSTRAP_CANARIES[12],
            lambda conn: _column_exists(conn, "civic", "contest_result", "votes"),
        ),
        (
            BOOTSTRAP_CANARIES[13],
            lambda conn: _column_exists(conn, "civic", "contest_result", "vote_pct"),
        ),
        (
            BOOTSTRAP_CANARIES[14],
            lambda conn: _column_exists(conn, "civic", "contest_result", "is_certified"),
        ),
        (
            BOOTSTRAP_CANARIES[15],
            lambda conn: _column_exists(conn, "core", "person", "bio_text"),
        ),
        (
            BOOTSTRAP_CANARIES[16],
            lambda conn: _column_exists(conn, "core", "person", "bio_source_url"),
        ),
        (
            BOOTSTRAP_CANARIES[17],
            lambda conn: _column_exists(conn, "core", "person", "bio_license"),
        ),
        (
            BOOTSTRAP_CANARIES[18],
            lambda conn: _column_exists(conn, "core", "person", "bio_pulled_at"),
        ),
        (
            BOOTSTRAP_CANARIES[19],
            lambda conn: _relation_exists(conn, "core", "person_er_view"),
        ),
        (
            BOOTSTRAP_CANARIES[20],
            lambda conn: _relation_exists(conn, "core", "organization_er_view"),
        ),
        (
            BOOTSTRAP_CANARIES[21],
            lambda conn: _relation_exists(conn, "core", "match_decision"),
        ),
        (
            BOOTSTRAP_CANARIES[22],
            lambda conn: _graph_exists(conn, "civibus"),
        ),
    )


def _collect_missing_stage1_canaries(conn: psycopg.Connection) -> list[str]:
    canary_checks = _stage1_canary_checks()
    assert tuple(canary_name for canary_name, _ in canary_checks) == BOOTSTRAP_CANARIES
    return [canary_name for canary_name, check_exists in canary_checks if not check_exists(conn)]
