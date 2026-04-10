from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from core.entity_resolution.persist import (
    log_splink_run_complete,
    log_splink_run_failed,
    log_splink_run_start,
    persist_match_decisions,
)
from core.entity_resolution.test_extract import _insert_organization, _insert_person

pytestmark = pytest.mark.integration


def _insert_data_source(
    db_conn: psycopg.Connection,
    *,
    name: str,
    jurisdiction: str = "federal/fec",
) -> UUID:
    data_source_id = uuid4()
    db_conn.execute(
        """
        INSERT INTO core.data_source (
            id, domain, jurisdiction, name, source_url
        )
        VALUES (%s, 'campaign_finance', %s, %s, 'https://example.test')
        """,
        (data_source_id, jurisdiction, name),
    )
    return data_source_id


def _insert_source_record(
    db_conn: psycopg.Connection,
    *,
    data_source_id: UUID,
    source_record_key: str,
) -> UUID:
    source_record_id = uuid4()
    db_conn.execute(
        """
        INSERT INTO core.source_record (
            id, data_source_id, source_record_key, raw_fields, pull_date
        )
        VALUES (%s, %s, %s, %s, NOW())
        """,
        (source_record_id, data_source_id, source_record_key, Jsonb({"source_record_key": source_record_key})),
    )
    return source_record_id


def _insert_entity_source(
    db_conn: psycopg.Connection,
    *,
    entity_type: str,
    entity_id: UUID,
    source_record_id: UUID,
    extraction_role: str,
) -> UUID:
    entity_source_id = uuid4()
    db_conn.execute(
        """
        INSERT INTO core.entity_source (
            id, entity_type, entity_id, source_record_id, extraction_role
        )
        VALUES (%s, %s, %s, %s, %s)
        """,
        (entity_source_id, entity_type, entity_id, source_record_id, extraction_role),
    )
    return entity_source_id


def _create_person(db_conn: psycopg.Connection, *, person_id: UUID, name: str) -> None:
    _insert_person(
        db_conn,
        person_id=person_id,
        canonical_name=name,
        first_name=name.split()[0],
        last_name=name.split()[-1],
        date_of_birth=None,
        identifiers={},
    )


def _create_org(db_conn: psycopg.Connection, *, organization_id: UUID, name: str) -> None:
    _insert_organization(
        db_conn,
        organization_id=organization_id,
        canonical_name=name,
        registered_state="NC",
        org_type="committee",
        identifiers={},
    )


def _match_pair(
    entity_id_a: UUID,
    entity_id_b: UUID,
    *,
    confidence: float,
    decision: str,
    decision_method: str = "probabilistic",
    decided_by: str = "splink_v1",
) -> dict[str, object]:
    return {
        "entity_id_a": entity_id_a,
        "entity_id_b": entity_id_b,
        "confidence": confidence,
        "decision": decision,
        "decision_method": decision_method,
        "decided_by": decided_by,
    }


def test_log_splink_run_start_inserts_running_row_with_explicit_started_at(
    db_conn: psycopg.Connection,
) -> None:
    started_at = datetime(2026, 3, 16, 6, 30, 0, tzinfo=UTC)
    model_config = {"blocking_rules": ["l.first_name = r.first_name"], "threshold": 0.95}

    run_id = log_splink_run_start(
        db_conn,
        entity_type="person",
        splink_version="3.9.8",
        model_config=model_config,
        started_at=started_at,
    )

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute("SELECT * FROM core.splink_run WHERE id = %s", (run_id,))
        row = cursor.fetchone()

    assert row is not None
    assert row["status"] == "running"
    assert row["entity_type"] == "person"
    assert row["splink_version"] == "3.9.8"
    assert row["model_config"] == model_config
    assert row["started_at"] == started_at
    assert row["completed_at"] is None


def test_log_splink_run_complete_sets_status_timestamps_and_count_fields(
    db_conn: psycopg.Connection,
) -> None:
    started_at = datetime(2026, 3, 16, 7, 0, 0, tzinfo=UTC)
    completed_at = datetime(2026, 3, 16, 7, 1, 5, tzinfo=UTC)
    run_id = log_splink_run_start(
        db_conn,
        entity_type="organization",
        splink_version="3.9.8",
        model_config={"model": "org-v1"},
        started_at=started_at,
    )

    log_splink_run_complete(
        db_conn,
        run_id,
        completed_at=completed_at,
        duration_seconds=65.0,
        counts={
            "input_record_count": 120,
            "pairs_compared": 330,
            "matches_found": 42,
            "auto_merged": 9,
            "probable_matches": 11,
            "possible_matches": 22,
        },
    )

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute("SELECT * FROM core.splink_run WHERE id = %s", (run_id,))
        row = cursor.fetchone()

    assert row is not None
    assert row["status"] == "completed"
    assert row["completed_at"] == completed_at
    assert row["input_record_count"] == 120
    assert row["pairs_compared"] == 330
    assert row["matches_found"] == 42
    assert row["auto_merged"] == 9
    assert row["probable_matches"] == 11
    assert row["possible_matches"] == 22
    assert row["error_message"] is None
    assert row["duration_seconds"] == pytest.approx(65.0)


def test_log_splink_run_failed_sets_failed_status_error_message_and_duration(
    db_conn: psycopg.Connection,
) -> None:
    started_at = datetime(2026, 3, 16, 7, 5, 0, tzinfo=UTC)
    completed_at = datetime(2026, 3, 16, 7, 5, 7, tzinfo=UTC)
    run_id = log_splink_run_start(
        db_conn,
        entity_type="person",
        splink_version="3.9.8",
        model_config={"model": "person-v1"},
        started_at=started_at,
    )

    log_splink_run_failed(
        db_conn,
        run_id,
        completed_at=completed_at,
        duration_seconds=7.0,
        error_message="scoring exploded",
    )

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute("SELECT * FROM core.splink_run WHERE id = %s", (run_id,))
        row = cursor.fetchone()

    assert row is not None
    assert row["status"] == "failed"
    assert row["completed_at"] == completed_at
    assert row["duration_seconds"] == pytest.approx(7.0)
    assert row["error_message"] == "scoring exploded"
    assert row["input_record_count"] is None
    assert row["pairs_compared"] is None
    assert row["matches_found"] is None
    assert row["auto_merged"] is None
    assert row["probable_matches"] is None
    assert row["possible_matches"] is None


def test_persist_match_decisions_canonicalizes_pairs_and_persists_metadata_and_evidence(
    db_conn: psycopg.Connection,
) -> None:
    a, b, c, d, e = uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
    for person_id, name in [(a, "Alpha One"), (b, "Beta Two"), (c, "Gamma Three"), (d, "Delta Four"), (e, "Echo Five")]:
        _create_person(db_conn, person_id=person_id, name=name)

    classified_pairs = [
        {
            **_match_pair(
                b,
                a,
                confidence=1.0,
                decision="match",
                decision_method="deterministic",
                decided_by="deterministic_fec_id_match",
            ),
            "matched_rule_names": ["deterministic_fec_id_match"],
        },
        _match_pair(c, a, confidence=0.86, decision="probable_match"),
        _match_pair(d, a, confidence=0.64, decision="possible_match"),
        _match_pair(e, a, confidence=0.20, decision="no_match"),
    ]

    persist_match_decisions(db_conn, classified_pairs, "person")

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT
                entity_id_a,
                entity_id_b,
                decision,
                confidence,
                decision_method,
                decided_by,
                match_evidence,
                match_evidence IS NULL AS match_evidence_is_null,
                jsonb_typeof(match_evidence) AS match_evidence_type
            FROM core.match_decision
            WHERE entity_type = 'person'
            ORDER BY entity_id_a, entity_id_b
            """
        )
        rows = cursor.fetchall()

    assert len(rows) == 4
    for row in rows:
        assert row["entity_id_a"] < row["entity_id_b"]

    decisions = {(row["entity_id_a"], row["entity_id_b"]): row["decision"] for row in rows}
    assert decisions[min(a, b), max(a, b)] == "match"
    assert decisions[min(a, c), max(a, c)] == "probable_match"
    assert decisions[min(a, d), max(a, d)] == "possible_match"
    assert decisions[min(a, e), max(a, e)] == "no_match"

    deterministic_row = next(row for row in rows if row["decision_method"] == "deterministic")
    assert deterministic_row["decided_by"] == "deterministic_fec_id_match"
    assert deterministic_row["match_evidence"]["matched_rule_names"] == ["deterministic_fec_id_match"]
    assert deterministic_row["match_evidence_is_null"] is False
    assert deterministic_row["match_evidence_type"] == "object"

    probabilistic_rows = [row for row in rows if row["decision_method"] == "probabilistic"]
    assert {row["decided_by"] for row in probabilistic_rows} == {"splink_v1"}
    assert all(row["match_evidence"] is None for row in probabilistic_rows)
    assert all(row["match_evidence_is_null"] is True for row in probabilistic_rows)
    assert all(row["match_evidence_type"] is None for row in probabilistic_rows)


def test_persist_match_decisions_supersedes_existing_active_decision_on_rerun(
    db_conn: psycopg.Connection,
) -> None:
    a, b = uuid4(), uuid4()
    _create_person(db_conn, person_id=a, name="Supersede Alpha")
    _create_person(db_conn, person_id=b, name="Supersede Beta")

    persist_match_decisions(
        db_conn,
        [
            _match_pair(
                a,
                b,
                confidence=0.61,
                decision="possible_match",
                decision_method="probabilistic",
                decided_by="splink_v1",
            )
        ],
        "person",
    )
    persist_match_decisions(
        db_conn,
        [
            _match_pair(
                b,
                a,
                confidence=0.99,
                decision="match",
                decision_method="deterministic",
                decided_by="deterministic_fec_id_match",
            )
        ],
        "person",
    )

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT id, decision, confidence, superseded_by, superseded_at
            FROM core.match_decision
            WHERE entity_type = 'person'
              AND entity_id_a = %s
              AND entity_id_b = %s
            """,
            (min(a, b), max(a, b)),
        )
        rows = cursor.fetchall()

    assert len(rows) == 2
    old_row = next(row for row in rows if row["superseded_by"] is not None)
    new_row = next(row for row in rows if row["superseded_by"] is None)
    assert old_row["decision"] == "possible_match"
    assert old_row["superseded_by"] == new_row["id"]
    assert old_row["superseded_at"] is not None
    assert new_row["decision"] == "match"
    assert new_row["superseded_by"] is None

    active_row = db_conn.execute(
        """
        SELECT id, decision
        FROM core.active_matches
        WHERE entity_type = 'person'
          AND entity_id_a = %s
          AND entity_id_b = %s
        """,
        (min(a, b), max(a, b)),
    ).fetchone()
    assert active_row is not None
    assert active_row[0] == new_row["id"]
    assert active_row[1] == "match"
