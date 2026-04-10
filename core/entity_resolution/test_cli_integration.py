from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from core.entity_resolution.cli import main
from core.entity_resolution.test_extract import _insert_person
from core.entity_resolution.test_persist import (
    _insert_data_source,
    _insert_entity_source,
    _insert_source_record,
)
from core.graph.loader import merge_person_node
from test_support.cross_domain_graph import (
    CrossDomainPossibleMatchFixtureSet,
    assert_cross_domain_possible_match_provenance,
    seed_cross_domain_possible_match_fixture,
)


@dataclass
class _DryRunFixtureSet:
    person_a: UUID
    person_b: UUID
    expected_entity_sources: list[tuple[UUID, UUID]]


class _RollbackOnCloseProxy:
    def __init__(
        self,
        wrapped: psycopg.Connection,
        *,
        savepoint_name: str | None = None,
    ) -> None:
        self._wrapped = wrapped
        self._savepoint_name = savepoint_name

    def close(self) -> None:
        if self._savepoint_name is None:
            self._wrapped.rollback()
            return
        self._wrapped.execute(f"ROLLBACK TO SAVEPOINT {self._savepoint_name}")

    def __getattr__(self, item: str) -> object:
        return getattr(self._wrapped, item)


class _CommitSuppressingProxy:
    def __init__(self, wrapped: psycopg.Connection) -> None:
        self._wrapped = wrapped
        self.commit_calls = 0
        self.close_calls = 0

    def commit(self) -> None:
        self.commit_calls += 1

    def close(self) -> None:
        self.close_calls += 1

    def __getattr__(self, item: str) -> object:
        return getattr(self._wrapped, item)


class _SavepointFailingProxy(_CommitSuppressingProxy):
    def __init__(self, wrapped: psycopg.Connection) -> None:
        super().__init__(wrapped)
        self.rollback_to_savepoint_attempts = 0

    def execute(self, query: str, *args, **kwargs):
        normalized_query = query.strip().upper()
        if normalized_query == "SAVEPOINT SPLINK_RUN_EXECUTE":
            raise RuntimeError("savepoint setup failure")
        if normalized_query == "ROLLBACK TO SAVEPOINT SPLINK_RUN_EXECUTE":
            self.rollback_to_savepoint_attempts += 1
        return self._wrapped.execute(query, *args, **kwargs)


def _assert_dry_run_rollback_state(
    graph_conn: psycopg.Connection,
    *,
    expected_entity_sources: list[tuple[UUID, UUID]],
) -> None:
    assert graph_conn.execute("SELECT count(*) FROM core.match_decision").fetchone()[0] == 0
    assert graph_conn.execute("SELECT count(*) FROM core.entity_cluster").fetchone()[0] == 0
    assert graph_conn.execute("SELECT count(*) FROM core.cluster_member").fetchone()[0] == 0

    person_ids = [entity_id for _, entity_id in expected_entity_sources]
    assert set(
        graph_conn.execute(
            "SELECT id, er_cluster_id, er_confidence FROM core.person WHERE id = ANY(%s)",
            (person_ids,),
        ).fetchall()
    ) == {(person_id, None, None) for person_id in person_ids}
    assert set(
        graph_conn.execute(
            "SELECT source_record_id, entity_id FROM core.entity_source WHERE source_record_id = ANY(%s)",
            ([source_record_id for source_record_id, _ in expected_entity_sources],),
        ).fetchall()
    ) == set(expected_entity_sources)


def _seed_dry_run_fixture(graph_conn: psycopg.Connection) -> _DryRunFixtureSet:
    person_a = uuid4()
    person_b = uuid4()
    shared_fec_id = "CLI-DRY-RUN-001"

    _insert_person(
        graph_conn,
        person_id=person_a,
        canonical_name="CLI Alpha",
        first_name="CLI",
        last_name="Alpha",
        date_of_birth=None,
        identifiers={"fec_id": shared_fec_id},
    )
    _insert_person(
        graph_conn,
        person_id=person_b,
        canonical_name="CLI Beta",
        first_name="CLI",
        last_name="Beta",
        date_of_birth=None,
        identifiers={"fec_id": shared_fec_id},
    )

    data_source_id = _insert_data_source(graph_conn, name="ER CLI dry-run integration")
    source_record_a = _insert_source_record(
        graph_conn,
        data_source_id=data_source_id,
        source_record_key="cli-dry-run-a",
    )
    source_record_b = _insert_source_record(
        graph_conn,
        data_source_id=data_source_id,
        source_record_key="cli-dry-run-b",
    )
    _insert_entity_source(
        graph_conn,
        entity_type="person",
        entity_id=person_a,
        source_record_id=source_record_a,
        extraction_role="donor",
    )
    _insert_entity_source(
        graph_conn,
        entity_type="person",
        entity_id=person_b,
        source_record_id=source_record_b,
        extraction_role="donor",
    )

    return _DryRunFixtureSet(
        person_a=person_a,
        person_b=person_b,
        expected_entity_sources=[
            (source_record_a, person_a),
            (source_record_b, person_b),
        ],
    )


def _patch_dry_run_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    *,
    graph_conn: psycopg.Connection,
    fixtures: _DryRunFixtureSet,
) -> None:
    savepoint_name = "cli_dry_run_start"
    graph_conn.execute(f"SAVEPOINT {savepoint_name}")

    proxy_connection = _RollbackOnCloseProxy(graph_conn, savepoint_name=savepoint_name)
    monkeypatch.setattr("core.entity_resolution.cli.get_connection", lambda *, post_connect: proxy_connection)
    monkeypatch.setattr("core.entity_resolution.cli._require_splink_runtime_available", lambda *_: None)
    monkeypatch.setattr(
        "core.entity_resolution.cli.extract_rows_for_matching",
        lambda *_: [
            {"id": fixtures.person_a, "canonical_name": "CLI Alpha"},
            {"id": fixtures.person_b, "canonical_name": "CLI Beta"},
        ],
    )
    monkeypatch.setattr(
        "core.entity_resolution.cli.score_entities",
        lambda *_: [
            {
                "entity_id_a": min(fixtures.person_a, fixtures.person_b),
                "entity_id_b": max(fixtures.person_a, fixtures.person_b),
                "confidence": 1.0,
                "decision_method": "deterministic",
                "decided_by": "deterministic_fec_id_match",
            }
        ],
    )


@dataclass
class _PersistedRunFixtureSet:
    auto_merge_person_a: UUID
    auto_merge_person_b: UUID
    auto_merge_person_c: UUID
    auto_merge_person_d: UUID
    source_records_by_person: dict[UUID, UUID]
    jurisdictions_by_person: dict[UUID, str]


def _insert_seed_person(
    graph_conn: psycopg.Connection,
    *,
    person_id: UUID,
    canonical_name: str,
    identifiers: dict[str, str] | None = None,
) -> None:
    first_name, last_name = canonical_name.split()
    _insert_person(
        graph_conn,
        person_id=person_id,
        canonical_name=canonical_name,
        first_name=first_name,
        last_name=last_name,
        date_of_birth=None,
        identifiers=identifiers or {},
    )
    merge_person_node(graph_conn, person_id, canonical_name)


def _seed_persisted_run_fixture(graph_conn: psycopg.Connection) -> _PersistedRunFixtureSet:
    auto_merge_person_a = uuid4()
    auto_merge_person_b = uuid4()
    auto_merge_person_c = uuid4()
    auto_merge_person_d = uuid4()

    _insert_seed_person(
        graph_conn,
        person_id=auto_merge_person_a,
        canonical_name="Run Alpha",
        identifiers={"fec_id": "CLI-RUN-FEC-MATCH"},
    )
    _insert_seed_person(
        graph_conn,
        person_id=auto_merge_person_b,
        canonical_name="Run Beta",
        identifiers={"fec_id": "CLI-RUN-FEC-MATCH"},
    )
    _insert_seed_person(
        graph_conn,
        person_id=auto_merge_person_c,
        canonical_name="Run Gamma",
        identifiers={"voter_reg_id": "CLI-RUN-VOTER-MATCH"},
    )
    _insert_seed_person(
        graph_conn,
        person_id=auto_merge_person_d,
        canonical_name="Run Delta",
        identifiers={"voter_reg_id": "CLI-RUN-VOTER-MATCH"},
    )

    jurisdictions_by_person = {
        auto_merge_person_a: "federal/fec",
        auto_merge_person_b: "federal/fec",
        auto_merge_person_c: "state/CO",
        auto_merge_person_d: "state/GA",
    }
    source_records = _seed_person_source_records_by_jurisdiction(
        graph_conn,
        source_key_prefix="cli-run",
        jurisdictions_by_person=jurisdictions_by_person,
    )
    for person_id, source_record_id in source_records.items():
        _insert_entity_source(
            graph_conn,
            entity_type="person",
            entity_id=person_id,
            source_record_id=source_record_id,
            extraction_role="donor",
        )

    return _PersistedRunFixtureSet(
        auto_merge_person_a=auto_merge_person_a,
        auto_merge_person_b=auto_merge_person_b,
        auto_merge_person_c=auto_merge_person_c,
        auto_merge_person_d=auto_merge_person_d,
        source_records_by_person=source_records,
        jurisdictions_by_person=jurisdictions_by_person,
    )


def _seed_person_source_records_by_jurisdiction(
    graph_conn: psycopg.Connection,
    *,
    source_key_prefix: str,
    jurisdictions_by_person: dict[UUID, str],
) -> dict[UUID, UUID]:
    source_records_by_person: dict[UUID, UUID] = {}
    data_source_id_by_jurisdiction: dict[str, UUID] = {}
    record_count_by_jurisdiction: dict[str, int] = {}

    for person_id, jurisdiction in sorted(jurisdictions_by_person.items(), key=lambda item: str(item[0])):
        if jurisdiction not in data_source_id_by_jurisdiction:
            data_source_id_by_jurisdiction[jurisdiction] = _insert_data_source(
                graph_conn,
                name=f"ER CLI persisted integration ({jurisdiction})",
                jurisdiction=jurisdiction,
            )
            record_count_by_jurisdiction[jurisdiction] = 0

        record_count_by_jurisdiction[jurisdiction] += 1
        source_records_by_person[person_id] = _insert_source_record(
            graph_conn,
            data_source_id=data_source_id_by_jurisdiction[jurisdiction],
            source_record_key=f"{source_key_prefix}-{jurisdiction.replace('/', '-')}-{record_count_by_jurisdiction[jurisdiction]}",
        )

    return source_records_by_person


def _patch_persisted_run_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    *,
    graph_conn: psycopg.Connection,
    fixtures: _PersistedRunFixtureSet,
) -> _CommitSuppressingProxy:
    from core.entity_resolution.extract import extract_rows_for_matching as real_extract_rows_for_matching

    seed_person_ids = {
        fixtures.auto_merge_person_a,
        fixtures.auto_merge_person_b,
        fixtures.auto_merge_person_c,
        fixtures.auto_merge_person_d,
    }

    def _extract_seed_rows(conn: psycopg.Connection, entity_type: str) -> list[dict[str, object]]:
        rows = real_extract_rows_for_matching(conn, entity_type)
        if entity_type != "person":
            return rows
        return [row for row in rows if row["id"] in seed_person_ids]

    proxy_connection = _CommitSuppressingProxy(graph_conn)
    monkeypatch.setattr("core.entity_resolution.cli.get_connection", lambda *, post_connect: proxy_connection)
    monkeypatch.setattr("core.entity_resolution.cli._require_splink_runtime_available", lambda *_: None)
    monkeypatch.setattr("core.entity_resolution.cli.extract_rows_for_matching", _extract_seed_rows)
    monkeypatch.setattr("core.entity_resolution.scoring.extract_rows_for_matching", _extract_seed_rows)
    return proxy_connection


def _patch_cross_domain_possible_match_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    *,
    graph_conn: psycopg.Connection,
    fixtures: CrossDomainPossibleMatchFixtureSet,
) -> _CommitSuppressingProxy:
    from core.entity_resolution.extract import extract_rows_for_matching as real_extract_rows_for_matching

    seed_person_ids = {
        fixtures.campaign_person_id,
        fixtures.property_person_id,
    }

    def _extract_seed_rows(conn: psycopg.Connection, entity_type: str) -> list[dict[str, object]]:
        rows = real_extract_rows_for_matching(conn, entity_type)
        if entity_type != "person":
            return rows
        return [row for row in rows if row["id"] in seed_person_ids]

    scored_pair_id_a, scored_pair_id_b = sorted((fixtures.campaign_person_id, fixtures.property_person_id))
    proxy_connection = _CommitSuppressingProxy(graph_conn)
    monkeypatch.setattr("core.entity_resolution.cli.get_connection", lambda *, post_connect: proxy_connection)
    monkeypatch.setattr("core.entity_resolution.cli._require_splink_runtime_available", lambda *_: None)
    monkeypatch.setattr("core.entity_resolution.cli.extract_rows_for_matching", _extract_seed_rows)
    monkeypatch.setattr("core.entity_resolution.scoring.extract_rows_for_matching", _extract_seed_rows)
    monkeypatch.setattr(
        "core.entity_resolution.cli.score_entities",
        lambda *_: [
            {
                "entity_id_a": scored_pair_id_a,
                "entity_id_b": scored_pair_id_b,
                "confidence": 0.65,
                "decision_method": "probabilistic",
                "decided_by": "splink_v1",
            }
        ],
    )
    return proxy_connection


def _count_person_edge(
    graph_conn: psycopg.Connection,
    *,
    edge_label: str,
    entity_id_a: UUID,
    entity_id_b: UUID,
) -> int:
    pair_id_a, pair_id_b = sorted((entity_id_a, entity_id_b))
    with graph_conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT count(*)
            FROM cypher('civibus', $$
                MATCH (a:Person {id: "%s"})-[e:%s]->(b:Person {id: "%s"})
                RETURN e
            $$) AS (v agtype)
            """
            % (pair_id_a, edge_label, pair_id_b)
        )
        return cursor.fetchone()[0]


def _assert_persisted_run_active_matches(
    graph_conn: psycopg.Connection,
    *,
    fixtures: _PersistedRunFixtureSet,
) -> None:
    with graph_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT entity_id_a, entity_id_b, decision, decision_method, decided_by, match_evidence
            FROM core.active_matches
            WHERE entity_type = 'person'
            ORDER BY entity_id_a, entity_id_b
            """
        )
        active_matches = cursor.fetchall()
    assert len(active_matches) == 2
    assert {row["decision"] for row in active_matches} == {"match"}
    expected_pairs = {
        tuple(sorted((fixtures.auto_merge_person_a, fixtures.auto_merge_person_b))),
        tuple(sorted((fixtures.auto_merge_person_c, fixtures.auto_merge_person_d))),
    }
    assert {(row["entity_id_a"], row["entity_id_b"]) for row in active_matches} == expected_pairs
    assert {row["decision_method"] for row in active_matches} == {"deterministic"}
    assert {row["decided_by"] for row in active_matches} == {
        "deterministic_fec_id_match",
        "deterministic_voter_reg_match",
    }
    assert {tuple(row["match_evidence"]["matched_rule_names"]) for row in active_matches} == {
        ("deterministic_fec_id_match",),
        ("deterministic_voter_reg_match",),
    }


def _assert_persisted_run_cluster_state(
    graph_conn: psycopg.Connection,
    *,
    fixtures: _PersistedRunFixtureSet,
) -> None:
    cluster_rows = graph_conn.execute(
        """
        SELECT id, cluster_confidence, member_count
        FROM core.entity_cluster
        ORDER BY id
        """
    ).fetchall()
    assert len(cluster_rows) == 2
    cluster_ids = [row[0] for row in cluster_rows]
    for _, cluster_confidence, _ in cluster_rows:
        assert cluster_confidence == pytest.approx(1.0)
    assert {row[2] for row in cluster_rows} == {2}

    cluster_members = graph_conn.execute(
        """
        SELECT cluster_id, entity_id, is_canonical
        FROM core.cluster_member
        WHERE cluster_id = ANY(%s)
          AND split_at IS NULL
        ORDER BY cluster_id, entity_id
        """,
        (cluster_ids,),
    ).fetchall()
    assert len(cluster_members) == 4
    member_ids_by_cluster: dict[UUID, set[UUID]] = {}
    canonical_count_by_cluster: dict[UUID, int] = {}
    for cluster_id, entity_id, is_canonical in cluster_members:
        member_ids_by_cluster.setdefault(cluster_id, set()).add(entity_id)
        canonical_count_by_cluster[cluster_id] = canonical_count_by_cluster.get(cluster_id, 0) + int(is_canonical)
    assert all(canonical_count == 1 for canonical_count in canonical_count_by_cluster.values())
    assert {frozenset(member_ids) for member_ids in member_ids_by_cluster.values()} == {
        frozenset({fixtures.auto_merge_person_a, fixtures.auto_merge_person_b}),
        frozenset({fixtures.auto_merge_person_c, fixtures.auto_merge_person_d}),
    }

    with graph_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT id, er_cluster_id
            FROM core.person
            WHERE id = ANY(%s)
            ORDER BY id
            """,
            (
                [
                    fixtures.auto_merge_person_a,
                    fixtures.auto_merge_person_b,
                    fixtures.auto_merge_person_c,
                    fixtures.auto_merge_person_d,
                ],
            ),
        )
        person_rows = cursor.fetchall()
    assigned_cluster_ids = {row["id"]: row["er_cluster_id"] for row in person_rows}
    assert all(cluster_id is not None for cluster_id in assigned_cluster_ids.values())
    assert assigned_cluster_ids[fixtures.auto_merge_person_a] == assigned_cluster_ids[fixtures.auto_merge_person_b]
    assert assigned_cluster_ids[fixtures.auto_merge_person_c] == assigned_cluster_ids[fixtures.auto_merge_person_d]
    assert assigned_cluster_ids[fixtures.auto_merge_person_a] != assigned_cluster_ids[fixtures.auto_merge_person_c]


def _assert_persisted_run_relinked_sources(
    graph_conn: psycopg.Connection,
    *,
    fixtures: _PersistedRunFixtureSet,
) -> None:
    source_records = fixtures.source_records_by_person
    expected_source_records = [
        source_records[fixtures.auto_merge_person_a],
        source_records[fixtures.auto_merge_person_b],
        source_records[fixtures.auto_merge_person_c],
        source_records[fixtures.auto_merge_person_d],
    ]
    relinked_entity_sources = graph_conn.execute(
        """
        SELECT source_record_id, entity_id
        FROM core.entity_source
        WHERE source_record_id = ANY(%s)
        ORDER BY source_record_id
        """,
        (expected_source_records,),
    ).fetchall()
    relinked_by_source_record = dict(relinked_entity_sources)
    pair_one_owner_ids = {
        relinked_by_source_record[source_records[fixtures.auto_merge_person_a]],
        relinked_by_source_record[source_records[fixtures.auto_merge_person_b]],
    }
    pair_two_owner_ids = {
        relinked_by_source_record[source_records[fixtures.auto_merge_person_c]],
        relinked_by_source_record[source_records[fixtures.auto_merge_person_d]],
    }
    assert len(pair_one_owner_ids) == 1
    assert len(pair_two_owner_ids) == 1
    assert pair_one_owner_ids.pop() in {fixtures.auto_merge_person_a, fixtures.auto_merge_person_b}
    assert pair_two_owner_ids.pop() in {fixtures.auto_merge_person_c, fixtures.auto_merge_person_d}


def _assert_persisted_run_graph_and_audit_state(
    graph_conn: psycopg.Connection,
    *,
    fixtures: _PersistedRunFixtureSet,
) -> None:
    assert (
        _count_person_edge(
            graph_conn,
            edge_label="SAME_AS",
            entity_id_a=fixtures.auto_merge_person_a,
            entity_id_b=fixtures.auto_merge_person_b,
        )
        == 0
    )
    assert (
        _count_person_edge(
            graph_conn,
            edge_label="SAME_AS",
            entity_id_a=fixtures.auto_merge_person_c,
            entity_id_b=fixtures.auto_merge_person_d,
        )
        == 0
    )

    with graph_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT status, input_record_count, pairs_compared, matches_found, auto_merged, probable_matches, possible_matches
            FROM core.splink_run
            WHERE entity_type = 'person'
            ORDER BY started_at DESC
            LIMIT 1
            """
        )
        run_row = cursor.fetchone()
    assert run_row is not None
    assert run_row["status"] == "completed"
    assert run_row["input_record_count"] == 4
    assert run_row["pairs_compared"] == 2
    assert run_row["matches_found"] == 2
    assert run_row["auto_merged"] == 2
    assert run_row["probable_matches"] == 0
    assert run_row["possible_matches"] == 0


def _assert_persisted_run_output(output: str) -> None:
    assert "Entity resolution run summary (person)" in output
    assert "auto_merge_clusters: 2" in output
    assert "review_components: 0" in output
    assert "age_edges_materialized: 0" in output


@pytest.mark.integration
def test_main_run_dry_run_rolls_back_persisted_rows(
    graph_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixtures = _seed_dry_run_fixture(graph_conn)
    _patch_dry_run_dependencies(
        monkeypatch,
        graph_conn=graph_conn,
        fixtures=fixtures,
    )

    exit_code = main(["--entity-type", "person", "--action", "run", "--dry-run"])

    assert exit_code == 0
    _assert_dry_run_rollback_state(
        graph_conn,
        expected_entity_sources=fixtures.expected_entity_sources,
    )


@pytest.mark.integration
def test_main_run_persists_match_cluster_graph_and_run_audit_rows(
    graph_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fixtures = _seed_persisted_run_fixture(graph_conn)
    proxy_connection = _patch_persisted_run_dependencies(
        monkeypatch,
        graph_conn=graph_conn,
        fixtures=fixtures,
    )

    exit_code = main(["--entity-type", "person", "--action", "run"])

    assert exit_code == 0
    assert proxy_connection.commit_calls == 1
    assert proxy_connection.close_calls == 1

    _assert_persisted_run_active_matches(graph_conn, fixtures=fixtures)
    _assert_persisted_run_cluster_state(
        graph_conn,
        fixtures=fixtures,
    )
    _assert_persisted_run_relinked_sources(
        graph_conn,
        fixtures=fixtures,
    )
    _assert_persisted_run_graph_and_audit_state(
        graph_conn,
        fixtures=fixtures,
    )
    _assert_persisted_run_output(capsys.readouterr().out)


@pytest.mark.integration
def test_main_run_failure_persists_failed_run_audit_without_er_side_effects(
    graph_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    proxy_connection = _CommitSuppressingProxy(graph_conn)
    person_a = uuid4()
    person_b = uuid4()

    _insert_seed_person(
        graph_conn,
        person_id=person_a,
        canonical_name="Failed Alpha",
    )
    _insert_seed_person(
        graph_conn,
        person_id=person_b,
        canonical_name="Failed Beta",
    )

    monkeypatch.setattr("core.entity_resolution.cli.get_connection", lambda *, post_connect: proxy_connection)
    monkeypatch.setattr("core.entity_resolution.cli._require_splink_runtime_available", lambda *_: None)
    monkeypatch.setattr(
        "core.entity_resolution.cli.extract_rows_for_matching",
        lambda *_: [
            {"id": person_a, "canonical_name": "Failed Alpha"},
            {"id": person_b, "canonical_name": "Failed Beta"},
        ],
    )
    monkeypatch.setattr(
        "core.entity_resolution.cli.score_entities",
        lambda *_: (_ for _ in ()).throw(RuntimeError("integration scoring failure")),
    )

    exit_code = main(["--entity-type", "person", "--action", "run"])

    assert exit_code == 1
    assert proxy_connection.commit_calls == 1
    assert proxy_connection.close_calls == 1
    assert graph_conn.execute("SELECT count(*) FROM core.match_decision").fetchone()[0] == 0
    assert graph_conn.execute("SELECT count(*) FROM core.entity_cluster").fetchone()[0] == 0
    assert graph_conn.execute("SELECT count(*) FROM core.cluster_member").fetchone()[0] == 0

    with graph_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT status, error_message, completed_at, duration_seconds
            FROM core.splink_run
            WHERE entity_type = 'person'
            ORDER BY started_at DESC
            LIMIT 1
            """
        )
        run_row = cursor.fetchone()

    assert run_row is not None
    assert run_row["status"] == "failed"
    assert run_row["error_message"] == "integration scoring failure"
    assert run_row["completed_at"] is not None
    assert run_row["duration_seconds"] >= 0.0
    assert "Entity resolution CLI failed: integration scoring failure" in capsys.readouterr().err


@pytest.mark.integration
def test_main_run_savepoint_setup_failure_preserves_failed_run_audit(
    graph_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    proxy_connection = _SavepointFailingProxy(graph_conn)
    person_a = uuid4()
    person_b = uuid4()

    _insert_seed_person(
        graph_conn,
        person_id=person_a,
        canonical_name="Savepoint Alpha",
    )
    _insert_seed_person(
        graph_conn,
        person_id=person_b,
        canonical_name="Savepoint Beta",
    )

    monkeypatch.setattr("core.entity_resolution.cli.get_connection", lambda *, post_connect: proxy_connection)
    monkeypatch.setattr("core.entity_resolution.cli._require_splink_runtime_available", lambda *_: None)
    monkeypatch.setattr(
        "core.entity_resolution.cli.extract_rows_for_matching",
        lambda *_: (_ for _ in ()).throw(AssertionError("dispatch should not run when savepoint setup fails")),
    )

    exit_code = main(["--entity-type", "person", "--action", "run"])

    assert exit_code == 1
    assert proxy_connection.commit_calls == 1
    assert proxy_connection.close_calls == 1
    assert proxy_connection.rollback_to_savepoint_attempts == 0

    with graph_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT status, error_message, completed_at, duration_seconds
            FROM core.splink_run
            WHERE entity_type = 'person'
            ORDER BY started_at DESC
            LIMIT 1
            """
        )
        run_row = cursor.fetchone()

    assert run_row is not None
    assert run_row["status"] == "failed"
    assert run_row["error_message"] == "savepoint setup failure"
    assert run_row["completed_at"] is not None
    assert run_row["duration_seconds"] >= 0.0
    assert "Entity resolution CLI failed: savepoint setup failure" in capsys.readouterr().err


@pytest.mark.integration
def test_main_run_cross_domain_possible_match_materializes_age_edge_and_provenance(
    graph_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixtures = seed_cross_domain_possible_match_fixture(graph_conn)
    proxy_connection = _patch_cross_domain_possible_match_dependencies(
        monkeypatch,
        graph_conn=graph_conn,
        fixtures=fixtures,
    )
    pair_id_a, pair_id_b = sorted((fixtures.campaign_person_id, fixtures.property_person_id))

    exit_code = main(["--entity-type", "person", "--action", "run"])

    assert exit_code == 0
    assert proxy_connection.commit_calls == 1
    assert proxy_connection.close_calls == 1
    assert (
        _count_person_edge(
            graph_conn,
            edge_label="POSSIBLE_MATCH",
            entity_id_a=fixtures.campaign_person_id,
            entity_id_b=fixtures.property_person_id,
        )
        == 1
    )
    assert (
        _count_person_edge(
            graph_conn,
            edge_label="SAME_AS",
            entity_id_a=fixtures.campaign_person_id,
            entity_id_b=fixtures.property_person_id,
        )
        == 0
    )
    assert (
        graph_conn.execute(
            """
            SELECT count(*)
            FROM cypher('civibus', $$
                MATCH (:Person)-[e:POSSIBLE_MATCH]->(:Person)
                RETURN e
            $$) AS (v agtype)
            """
        ).fetchone()[0]
        == 1
    )

    with graph_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT entity_id_a, entity_id_b, decision, decision_method, decided_by
            FROM core.active_matches
            WHERE entity_type = 'person'
              AND entity_id_a = %s
              AND entity_id_b = %s
            """,
            (pair_id_a, pair_id_b),
        )
        active_match = cursor.fetchone()

    assert active_match == {
        "entity_id_a": pair_id_a,
        "entity_id_b": pair_id_b,
        "decision": "possible_match",
        "decision_method": "probabilistic",
        "decided_by": "splink_v1",
    }
    assert_cross_domain_possible_match_provenance(graph_conn, fixtures=fixtures)
