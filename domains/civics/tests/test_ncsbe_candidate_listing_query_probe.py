"""Unit contracts for candidate-listing SQL query classification."""

from __future__ import annotations

import pytest
from psycopg.sql import Identifier, SQL

from domains.civics.tests.ncsbe_candidate_listing_query_probe import (
    CountingConnection,
    capture_rollback_isolation_counts,
)


class _CountResult:
    def __init__(self, count: int) -> None:
        self._count = count

    def fetchone(self) -> tuple[int]:
        return (self._count,)


class _RollbackAwareConnection:
    def __init__(self) -> None:
        self.rollback_calls = 0

    def execute(self, query: str) -> _CountResult:
        measured_transaction = self.rollback_calls == 0
        if "FROM civic.candidacy" in query:
            return _CountResult(7 if measured_transaction else 0)
        if "FROM core.source_record" in query:
            return _CountResult(10 if measured_transaction else 0)
        raise AssertionError(f"Unexpected query: {query}")

    def rollback(self) -> None:
        self.rollback_calls += 1


def test_composed_person_insert_is_classified_as_person_write() -> None:
    counting_connection = CountingConnection(None)
    statement = SQL("INSERT INTO core.{table} (id) VALUES (%s)").format(table=Identifier("person"))

    counting_connection._record(statement)

    assert counting_connection.families["person_write"] == 1
    assert counting_connection.families["unknown"] == 0


@pytest.mark.parametrize(
    ("statement", "expected_family"),
    [
        ("INSERT INTO core.entity_source (entity_type) VALUES (%s)", "entity_source_write"),
        ("SELECT pg_advisory_xact_lock(hashtext(%s), hashtext(%s))", "source_record_lock"),
        ("INSERT INTO core.data_source (id) VALUES (%s)", "data_source_write"),
        ("SELECT EXISTS (SELECT 1 FROM information_schema.columns)", "schema_lookup"),
        (
            "UPDATE civic.contest AS legacy SET name = %s WHERE NOT EXISTS (SELECT 1 FROM civic.contest AS existing)",
            "contest_write",
        ),
    ],
)
def test_known_supporting_queries_have_named_families(statement: str, expected_family: str) -> None:
    counting_connection = CountingConnection(None)

    counting_connection._record(statement)

    assert counting_connection.families[expected_family] == 1
    assert counting_connection.families["unknown"] == 0


def test_capture_rollback_isolation_counts_separates_measured_rows_from_residue() -> None:
    connection = _RollbackAwareConnection()

    counts = capture_rollback_isolation_counts(connection)

    assert counts == {
        "measured_transaction_counts": {
            "candidate_listing_candidacies": 7,
            "candidate_listing_source_records": 10,
        },
        "post_rollback_counts": {
            "candidate_listing_candidacies": 0,
            "candidate_listing_source_records": 0,
        },
    }
    assert connection.rollback_calls == 2
