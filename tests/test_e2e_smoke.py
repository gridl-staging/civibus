from __future__ import annotations

import io
import os
import subprocess
import sys
from contextlib import redirect_stderr

import pytest
from psycopg.rows import dict_row

from core.db import get_connection
from core.graph import age_post_connect, ensure_graph
from domains.campaign_finance.ingest.cli import main
from domains.campaign_finance.ingest.loader import ensure_fec_data_source, load_contribution
from test_support.fec_fixtures import load_fixture_results


pytestmark = pytest.mark.e2e


def _ingest_fixture_contributions(conn):
    """Load fixture contributions through the same loader path as the CLI."""
    ensure_graph(conn)
    with conn.transaction():
        data_source_id = ensure_fec_data_source(conn)
        for record in load_fixture_results():
            load_contribution(conn, data_source_id, record, graph_enabled=True)


def _run_cli_ingest() -> tuple[int, str]:
    captured_stderr = io.StringIO()
    with redirect_stderr(captured_stderr):
        exit_code = main(["--state", "NC", "--cycle", "2024", "--limit", "10"])

    stderr_output = captured_stderr.getvalue()
    if stderr_output:
        print(stderr_output, file=sys.stderr, end="")
    return exit_code, stderr_output


def _is_rate_limited_fetch_failure(exit_code: int, stderr_output: str) -> bool:
    return exit_code != 0 and "FEC fetch failed:" in stderr_output and "HTTP 429" in stderr_output


@pytest.mark.parametrize(
    ("exit_code", "stderr_output", "expected"),
    [
        (1, "FEC fetch failed: Rate limit exceeded (HTTP 429). Slow down requests.\n", True),
        (1, "FEC fetch failed: Forbidden (HTTP 403). Check your API key.\n", False),
        (1, "FEC ingest failed: database unavailable\n", False),
        (0, "", False),
    ],
)
def test_is_rate_limited_fetch_failure(exit_code: int, stderr_output: str, expected: bool) -> None:
    assert _is_rate_limited_fetch_failure(exit_code, stderr_output) is expected


def _ensure_test_postgres_password() -> None:
    os.environ.setdefault("POSTGRES_PASSWORD", "civibus_dev")


@pytest.fixture(scope="module")
def e2e_db():
    """Reset database, run CLI ingest, yield a connection for assertions.

    Falls back to fixture data only when the live FEC API rate-limits the
    request, so the extract -> load -> graph -> query pipeline is still
    validated end-to-end without masking other fetch or ingest failures.
    """
    _ensure_test_postgres_password()
    subprocess.run(["make", "db-reset"], check=True, capture_output=True, env=os.environ.copy())
    exit_code, stderr_output = _run_cli_ingest()

    conn = get_connection(post_connect=age_post_connect)

    if _is_rate_limited_fetch_failure(exit_code, stderr_output):
        print("Live FEC API rate-limited — falling back to fixture data", file=sys.stderr)
        _ingest_fixture_contributions(conn)
    else:
        assert exit_code == 0, f"CLI ingest failed unexpectedly: {stderr_output.strip() or f'exit_code={exit_code}'}"
        ensure_graph(conn)

    conn.commit()
    try:
        yield conn
    finally:
        conn.close()


class TestRelationalCounts:
    def test_source_records_loaded(self, e2e_db):
        with e2e_db.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT count(*) AS n FROM core.source_record")
            assert cur.fetchone()["n"] >= 10

    def test_persons_created(self, e2e_db):
        with e2e_db.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT count(*) AS n FROM core.person")
            assert cur.fetchone()["n"] >= 1

    def test_organizations_created(self, e2e_db):
        with e2e_db.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT count(*) AS n FROM core.organization")
            assert cur.fetchone()["n"] >= 1

    def test_addresses_created(self, e2e_db):
        with e2e_db.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT count(*) AS n FROM core.address")
            assert cur.fetchone()["n"] >= 1

    def test_entity_source_count(self, e2e_db):
        with e2e_db.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT count(*) AS n FROM core.source_record")
            sr_count = cur.fetchone()["n"]
            cur.execute("SELECT count(*) AS n FROM core.entity_source")
            es_count = cur.fetchone()["n"]
        # IND: 3 entity_source rows, ORG: 2 — so 2× is the safe lower bound
        assert es_count >= 2 * sr_count

    def test_entity_addresses_created(self, e2e_db):
        with e2e_db.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT count(*) AS n FROM core.entity_address")
            assert cur.fetchone()["n"] >= 1


class TestProvenanceIntegrity:
    def test_every_person_has_entity_source(self, e2e_db):
        with e2e_db.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT p.id
                FROM core.person p
                WHERE NOT EXISTS (
                    SELECT 1 FROM core.entity_source es
                    WHERE es.entity_type = 'person' AND es.entity_id = p.id
                )
                """
            )
            orphans = cur.fetchall()
        assert len(orphans) == 0, f"Found {len(orphans)} persons without entity_source"


class TestGraphCounts:
    def test_person_nodes_exist(self, e2e_db):
        with e2e_db.cursor() as cur:
            cur.execute(
                """
                SELECT count(*)
                FROM cypher('civibus', $$
                    MATCH (p:Person) RETURN p
                $$) AS (v agtype)
                """
            )
            assert cur.fetchone()[0] >= 1

    def test_organization_nodes_exist(self, e2e_db):
        with e2e_db.cursor() as cur:
            cur.execute(
                """
                SELECT count(*)
                FROM cypher('civibus', $$
                    MATCH (o:Organization) RETURN o
                $$) AS (v agtype)
                """
            )
            assert cur.fetchone()[0] >= 1

    def test_contributed_to_edges_exist(self, e2e_db):
        with e2e_db.cursor() as cur:
            cur.execute(
                """
                SELECT count(*)
                FROM cypher('civibus', $$
                    MATCH ()-[e:CONTRIBUTED_TO]->() RETURN e
                $$) AS (v agtype)
                """
            )
            assert cur.fetchone()[0] >= 1


class TestCteHybridE2E:
    def test_graph_relational_join_returns_results(self, e2e_db):
        with e2e_db.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                WITH graph_donors AS (
                    SELECT person_id::text AS person_id
                    FROM cypher('civibus', $$
                        MATCH (p:Person)-[:CONTRIBUTED_TO]->(o:Organization)
                        RETURN DISTINCT p.id AS person_id
                    $$) AS (person_id agtype)
                )
                SELECT a.state, count(*) AS n
                FROM graph_donors gd
                JOIN core.entity_address ea
                    ON ea.entity_type = 'person'
                    AND ea.entity_id = trim(both '"' from gd.person_id)::uuid
                JOIN core.address a ON a.id = ea.address_id
                WHERE a.state IS NOT NULL
                GROUP BY a.state
                """
            )
            rows = cur.fetchall()
        assert len(rows) >= 1
