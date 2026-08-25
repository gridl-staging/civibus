"""Live PostgreSQL proof that scoped connection identity reaches `pg_stat_activity`.

`core.db.connection_identity` only sets a connection parameter; this test is the
known-answer check that PostgreSQL actually records that parameter against the
right backend, and that an untagged connection stays untagged.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import ExitStack, contextmanager

import psycopg
import pytest

from core.db import connection_identity, get_connection

pytestmark = pytest.mark.integration

_PROBE_A_IDENTITY = "refresh:probe-a"
_PROBE_B_IDENTITY = "refresh:probe-b"
_REFRESH_IDENTITY_PREFIX = "refresh:"


@contextmanager
def _tagged_connection(identity: str) -> Iterator[psycopg.Connection]:
    """Open a live connection whose application name is fixed at connect time."""
    with connection_identity(identity):
        connection = get_connection()
    try:
        yield connection
    finally:
        connection.close()


def _backend_pid(connection: psycopg.Connection) -> int:
    row = connection.execute("SELECT pg_backend_pid()").fetchone()
    assert row is not None
    return int(row[0])


def _application_names_by_pid(observer: psycopg.Connection, pids: Sequence[int]) -> dict[int, str]:
    # Scoped to the exact specimen PIDs: unrelated sessions share this database
    # during a parallel test run, so a namespace-wide count would be flaky.
    rows = observer.execute(
        "SELECT pid, application_name FROM pg_stat_activity WHERE pid = ANY(%s)",
        (list(pids),),
    ).fetchall()
    return {int(pid): (application_name or "") for pid, application_name in rows}


def test_connection_identity_tags_each_live_backend_and_leaves_observer_untagged(
    db_conn: psycopg.Connection,
) -> None:
    with ExitStack() as live_connections:
        probe_a = live_connections.enter_context(_tagged_connection(_PROBE_A_IDENTITY))
        probe_b = live_connections.enter_context(_tagged_connection(_PROBE_B_IDENTITY))

        pid_a = _backend_pid(probe_a)
        pid_b = _backend_pid(probe_b)
        observer_pid = _backend_pid(db_conn)
        specimen_pids = (pid_a, pid_b, observer_pid)
        assert len(set(specimen_pids)) == 3, f"expected three distinct backends, got {specimen_pids}"

        application_names_by_pid = _application_names_by_pid(db_conn, specimen_pids)

        assert set(application_names_by_pid) == set(specimen_pids)
        assert application_names_by_pid[pid_a] == _PROBE_A_IDENTITY
        assert application_names_by_pid[pid_b] == _PROBE_B_IDENTITY
        assert not application_names_by_pid[observer_pid].startswith(_REFRESH_IDENTITY_PREFIX)
