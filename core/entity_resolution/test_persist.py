from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from core.entity_resolution.persist import (
    _ENTITY_TABLE_NAMES,
    _entity_table_name,
    log_splink_run_complete,
    log_splink_run_failed,
    log_splink_run_start,
    persist_auto_merge_clusters,
    persist_match_decisions,
)
from core.entity_resolution.test_extract import (
    _expected_donor_identity_id,
    _insert_organization,
    _insert_person,
)

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


def _create_donor_identity(db_conn: psycopg.Connection, *, donor_id: UUID, employer: str) -> None:
    db_conn.execute(
        """
        INSERT INTO core.donor_identity (
            id, canonical_name, contributor_name_raw, contributor_employer, transaction_count
        )
        VALUES (%s, 'DOE, JANE', 'DOE, JANE', %s, 1)
        """,
        (donor_id, employer),
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


def _cluster_component(
    *,
    canonical_entity_id: UUID,
    member_ids: set[UUID],
    min_confidence: float,
) -> dict[str, object]:
    return {
        "canonical_entity_id": canonical_entity_id,
        "member_ids": member_ids,
        "min_confidence": min_confidence,
        "min_decision": "match",
        "links": [],
    }


def _donor_identity_id(*, employer: str, zip_code: str = "277011234") -> UUID:
    return _expected_donor_identity_id(
        contributor_name_raw="DOE, JANE",
        contributor_employer=employer,
        contributor_occupation="ENGINEER",
        contributor_city="DURHAM",
        contributor_state="NC",
        contributor_zip=zip_code,
    )


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


def test_log_splink_run_lifecycle_accepts_donor_identity_entity_type(
    db_conn: psycopg.Connection,
) -> None:
    started_at = datetime(2026, 3, 17, 8, 0, 0, tzinfo=UTC)
    completed_at = datetime(2026, 3, 17, 8, 2, 0, tzinfo=UTC)

    completed_run_id = log_splink_run_start(
        db_conn,
        entity_type="donor_identity",
        splink_version="3.9.8",
        model_config={"model": "donor-v1", "blocking_rules": ["l.zip5 = r.zip5"]},
        started_at=started_at,
    )
    failed_run_id = log_splink_run_start(
        db_conn,
        entity_type="donor_identity",
        splink_version="3.9.8",
        model_config={"model": "donor-v1"},
        started_at=started_at,
    )

    log_splink_run_complete(
        db_conn,
        completed_run_id,
        completed_at=completed_at,
        duration_seconds=120.0,
        counts={
            "input_record_count": 3,
            "pairs_compared": 2,
            "matches_found": 1,
            "auto_merged": 1,
            "probable_matches": 0,
            "possible_matches": 0,
        },
    )
    log_splink_run_failed(
        db_conn,
        failed_run_id,
        completed_at=completed_at,
        duration_seconds=12.5,
        error_message="donor scoring failed",
    )

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT id, entity_type, status, model_config, input_record_count, pairs_compared,
                   matches_found, auto_merged, probable_matches, possible_matches,
                   duration_seconds, error_message
            FROM core.splink_run
            WHERE id IN (%s, %s)
            ORDER BY status
            """,
            (completed_run_id, failed_run_id),
        )
        rows = cursor.fetchall()

    completed_row = next(row for row in rows if row["id"] == completed_run_id)
    failed_row = next(row for row in rows if row["id"] == failed_run_id)
    assert completed_row["entity_type"] == "donor_identity"
    assert completed_row["status"] == "completed"
    assert completed_row["model_config"] == {"model": "donor-v1", "blocking_rules": ["l.zip5 = r.zip5"]}
    assert completed_row["input_record_count"] == 3
    assert completed_row["pairs_compared"] == 2
    assert completed_row["matches_found"] == 1
    assert completed_row["auto_merged"] == 1
    assert completed_row["probable_matches"] == 0
    assert completed_row["possible_matches"] == 0
    assert completed_row["duration_seconds"] == pytest.approx(120.0)
    assert completed_row["error_message"] is None
    assert failed_row["entity_type"] == "donor_identity"
    assert failed_row["status"] == "failed"
    assert failed_row["duration_seconds"] == pytest.approx(12.5)
    assert failed_row["error_message"] == "donor scoring failed"


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
                decided_by="deterministic_fec_candidate_id_match",
            ),
            "matched_rule_names": ["deterministic_fec_candidate_id_match"],
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
    assert deterministic_row["decided_by"] == "deterministic_fec_candidate_id_match"
    assert deterministic_row["match_evidence"]["matched_rule_names"] == ["deterministic_fec_candidate_id_match"]
    assert deterministic_row["match_evidence_is_null"] is False
    assert deterministic_row["match_evidence_type"] == "object"

    probabilistic_rows = [row for row in rows if row["decision_method"] == "probabilistic"]
    assert {row["decided_by"] for row in probabilistic_rows} == {"splink_v1"}
    assert all(row["match_evidence"] is None for row in probabilistic_rows)
    assert all(row["match_evidence_is_null"] is True for row in probabilistic_rows)
    assert all(row["match_evidence_type"] is None for row in probabilistic_rows)


def test_persist_match_decisions_accepts_donor_identity_and_persists_ordered_evidence(
    db_conn: psycopg.Connection,
) -> None:
    donor_a = _donor_identity_id(employer="ACME CORP")
    donor_b = _donor_identity_id(employer="BETA LLC")
    inserted_ids = persist_match_decisions(
        db_conn,
        [
            {
                **_match_pair(
                    donor_b,
                    donor_a,
                    confidence=0.94,
                    decision="probable_match",
                    decided_by="splink_donor_v1",
                ),
                "matched_fields": ["contributor_name_raw", "contributor_zip"],
                "transaction_counts": {"left": 2, "right": 1},
            }
        ],
        "donor_identity",
    )

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT id, entity_type, entity_id_a, entity_id_b, decision, confidence,
                   decided_by, decision_method, match_evidence
            FROM core.match_decision
            WHERE id = %s
            """,
            (inserted_ids[0],),
        )
        row = cursor.fetchone()

    assert row is not None
    assert row["entity_type"] == "donor_identity"
    assert isinstance(row["entity_id_a"], UUID)
    assert isinstance(row["entity_id_b"], UUID)
    assert row["entity_id_a"] == min(donor_a, donor_b)
    assert row["entity_id_b"] == max(donor_a, donor_b)
    assert row["decision"] == "probable_match"
    assert row["confidence"] == pytest.approx(0.94)
    assert row["decided_by"] == "splink_donor_v1"
    assert row["decision_method"] == "probabilistic"
    assert row["match_evidence"] == {
        "matched_fields": ["contributor_name_raw", "contributor_zip"],
        "transaction_counts": {"left": 2, "right": 1},
    }


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
                decided_by="deterministic_fec_candidate_id_match",
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


def test_persist_auto_merge_clusters_accepts_and_persists_donor_identity_type(
    db_conn: psycopg.Connection,
) -> None:
    canonical_id = _donor_identity_id(employer="ACME CORP")
    member_id = _donor_identity_id(employer="BETA LLC")
    _create_donor_identity(db_conn, donor_id=canonical_id, employer="ACME CORP")
    _create_donor_identity(db_conn, donor_id=member_id, employer="BETA LLC")

    cluster_ids = persist_auto_merge_clusters(
        db_conn,
        [
            _cluster_component(
                canonical_entity_id=canonical_id,
                member_ids={canonical_id, member_id},
                min_confidence=0.97,
            )
        ],
        "donor_identity",
        merged_by="splink_donor_v1",
    )

    assert len(cluster_ids) == 1
    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT entity_type, canonical_entity_id, cluster_confidence, member_count
            FROM core.entity_cluster
            WHERE id = %s
            """,
            (cluster_ids[0],),
        )
        cluster_row = cursor.fetchone()
        cursor.execute(
            """
            SELECT entity_type, entity_id, is_canonical, merged_by, split_at
            FROM core.cluster_member
            WHERE cluster_id = %s
            ORDER BY entity_id
            """,
            (cluster_ids[0],),
        )
        member_rows = cursor.fetchall()
        cursor.execute(
            """
            SELECT dcp.person_id, p.canonical_name, p.er_cluster_id
            FROM core.donor_cluster_person dcp
            JOIN core.person p ON p.id = dcp.person_id
            WHERE dcp.cluster_id = %s
            """,
            (cluster_ids[0],),
        )
        person_mapping_row = cursor.fetchone()

    assert cluster_row == {
        "entity_type": "donor_identity",
        "canonical_entity_id": canonical_id,
        "cluster_confidence": pytest.approx(0.97),
        "member_count": 2,
    }
    assert member_rows == [
        {
            "entity_type": "donor_identity",
            "entity_id": min(canonical_id, member_id),
            "is_canonical": min(canonical_id, member_id) == canonical_id,
            "merged_by": "splink_donor_v1",
            "split_at": None,
        },
        {
            "entity_type": "donor_identity",
            "entity_id": max(canonical_id, member_id),
            "is_canonical": max(canonical_id, member_id) == canonical_id,
            "merged_by": "splink_donor_v1",
            "split_at": None,
        },
    ]
    assert person_mapping_row is not None
    assert person_mapping_row["canonical_name"] == "DOE, JANE"
    assert person_mapping_row["er_cluster_id"] is None


def test_persist_auto_merge_clusters_rerun_preserves_donor_provenance(
    db_conn: psycopg.Connection,
) -> None:
    donor_a = _donor_identity_id(employer="ACME CORP")
    donor_b = _donor_identity_id(employer="BETA LLC")
    _create_donor_identity(db_conn, donor_id=donor_a, employer="ACME CORP")
    _create_donor_identity(db_conn, donor_id=donor_b, employer="BETA LLC")

    data_source_id = _insert_data_source(db_conn, name="donor-cluster-rerun")
    source_a = _insert_source_record(db_conn, data_source_id=data_source_id, source_record_key="donor-a")
    source_b = _insert_source_record(db_conn, data_source_id=data_source_id, source_record_key="donor-b")
    _insert_entity_source(
        db_conn,
        entity_type="donor_identity",
        entity_id=donor_a,
        source_record_id=source_a,
        extraction_role="donor",
    )
    _insert_entity_source(
        db_conn,
        entity_type="donor_identity",
        entity_id=donor_b,
        source_record_id=source_b,
        extraction_role="donor",
    )

    persist_auto_merge_clusters(
        db_conn,
        [_cluster_component(canonical_entity_id=donor_a, member_ids={donor_a, donor_b}, min_confidence=0.97)],
        "donor_identity",
    )
    final_cluster_id = persist_auto_merge_clusters(
        db_conn,
        [_cluster_component(canonical_entity_id=donor_b, member_ids={donor_a, donor_b}, min_confidence=0.99)],
        "donor_identity",
    )[0]

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT id, er_cluster_id, er_confidence
            FROM core.donor_identity
            WHERE id IN (%s, %s)
            ORDER BY id
            """,
            (donor_a, donor_b),
        )
        donor_rows = cursor.fetchall()
        cursor.execute(
            """
            SELECT entity_id, source_record_id, extracted_fields
            FROM core.entity_source
            WHERE entity_type = 'donor_identity'
            ORDER BY source_record_id
            """
        )
        source_rows = cursor.fetchall()

    assert all(row["er_cluster_id"] == final_cluster_id for row in donor_rows)
    assert all(row["er_confidence"] == pytest.approx(0.99) for row in donor_rows)
    source_by_id = {row["source_record_id"]: row for row in source_rows}
    assert source_by_id == {
        source_a: {
            "entity_id": donor_b,
            "source_record_id": source_a,
            "extracted_fields": {"_er_source_entity_ids": [str(donor_a)]},
        },
        source_b: {
            "entity_id": donor_b,
            "source_record_id": source_b,
            "extracted_fields": None,
        },
    }


def test_manual_override_schema_accepts_donor_identity_entity_type(
    db_conn: psycopg.Connection,
) -> None:
    donor_a, donor_b = sorted(
        [
            _donor_identity_id(employer="ACME CORP"),
            _donor_identity_id(employer="BETA LLC"),
        ]
    )
    override_id = uuid4()

    db_conn.execute(
        """
        INSERT INTO core.manual_override (
            id,
            entity_type,
            entity_id_a,
            entity_id_b,
            override_decision,
            reason,
            decided_by
        )
        VALUES (%s, 'donor_identity', %s, %s, 'confirmed_match', 'same donor tuple', 'test:audit')
        """,
        (override_id, donor_a, donor_b),
    )

    row = db_conn.execute(
        """
        SELECT entity_type, entity_id_a, entity_id_b, override_decision, reason, decided_by
        FROM core.manual_override
        WHERE id = %s
        """,
        (override_id,),
    ).fetchone()

    assert row == (
        "donor_identity",
        donor_a,
        donor_b,
        "confirmed_match",
        "same donor tuple",
        "test:audit",
    )


def test_persist_entity_table_name_accepts_donor_identity_and_lists_supported_types() -> None:
    assert "donor_identity" in _ENTITY_TABLE_NAMES
    assert _entity_table_name("donor_identity") == _ENTITY_TABLE_NAMES["donor_identity"]

    with pytest.raises(
        ValueError,
        match="entity_type must be one of 'donor_identity', 'organization', or 'person', got 'committee'",
    ):
        _entity_table_name("committee")
