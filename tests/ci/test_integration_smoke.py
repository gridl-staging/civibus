"""AGE-backed integration smoke test for merge-time CI validation."""

from __future__ import annotations

import pytest

from core.graph import GRAPH_NAME


@pytest.mark.integration
def test_graph_conn_exposes_civibus_graph_with_cypher_support(graph_conn) -> None:
    with graph_conn.cursor() as cur:
        cur.execute("SELECT 1 FROM ag_catalog.ag_graph WHERE name = %s", (GRAPH_NAME,))
        assert cur.fetchone() is not None
        cur.execute(f"SELECT * FROM cypher('{GRAPH_NAME}', $$ RETURN 1 $$) AS (v agtype)")
        assert cur.fetchone() is not None
