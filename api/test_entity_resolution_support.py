from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from core.db import insert_organization, insert_person
from core.types.python.models import Organization, Person

# -- Deterministic IDs for test assertions --

PERSON_CANONICAL_ID = UUID("00000000-0000-0000-0000-000000001101")
PERSON_ALIAS_ID = UUID("00000000-0000-0000-0000-000000001102")
PERSON_SECOND_CLUSTER_ID = UUID("00000000-0000-0000-0000-000000001103")
PERSON_SPLIT_MEMBER_ID = UUID("00000000-0000-0000-0000-000000001104")

ORG_CANONICAL_ID = UUID("00000000-0000-0000-0000-000000001201")
ORG_SECOND_ID = UUID("00000000-0000-0000-0000-000000001202")

CLUSTER_PERSON_TOP_ID = UUID("00000000-0000-0000-0000-000000002101")
CLUSTER_ORG_ID = UUID("00000000-0000-0000-0000-000000002102")
CLUSTER_PERSON_LOW_ID = UUID("00000000-0000-0000-0000-000000002103")
CLUSTER_HISTORICAL_ONLY_ID = UUID("00000000-0000-0000-0000-000000002104")

MATCH_PERSON_ACTIVE_ID = UUID("00000000-0000-0000-0000-000000003101")
MATCH_PERSON_POSSIBLE_ACTIVE_ID = UUID("00000000-0000-0000-0000-000000003102")
MATCH_PERSON_SUPERSEDED_ID = UUID("00000000-0000-0000-0000-000000003103")
MATCH_ORG_NO_MATCH_ID = UUID("00000000-0000-0000-0000-000000003104")

_FIXED_TIMESTAMP = datetime(2026, 3, 18, 12, 0, tzinfo=UTC)
_SPLIT_TIMESTAMP = datetime(2026, 3, 18, 12, 30, tzinfo=UTC)


# -- Seed data types to keep insert helpers under the 6-param hard limit --


@dataclass(frozen=True, slots=True)
class ClusterMemberSeed:
    member_id: UUID
    cluster_id: UUID
    entity_type: str
    entity_id: UUID
    is_canonical: bool
    split_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class MatchDecisionSeed:
    decision_id: UUID
    entity_type: str
    entity_id_a: UUID
    entity_id_b: UUID
    decision: str
    confidence: float
    match_evidence: dict[str, Any]
    superseded_by: UUID | None = None


# -- Insert helpers (each ≤ 6 params: db_conn + seed/kwargs) --


def _insert_cluster(
    db_conn: psycopg.Connection,
    *,
    cluster_id: UUID,
    entity_type: str,
    canonical_entity_id: UUID,
    cluster_confidence: float,
    member_count: int,
) -> None:
    db_conn.execute(
        """
        INSERT INTO core.entity_cluster (
            id, entity_type, canonical_entity_id,
            cluster_confidence, member_count, created_at, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (
            cluster_id,
            entity_type,
            canonical_entity_id,
            cluster_confidence,
            member_count,
            _FIXED_TIMESTAMP,
            _FIXED_TIMESTAMP,
        ),
    )


def _insert_cluster_member(db_conn: psycopg.Connection, seed: ClusterMemberSeed) -> None:
    db_conn.execute(
        """
        INSERT INTO core.cluster_member (
            id, cluster_id, entity_type, entity_id, is_canonical,
            merged_at, merged_by, split_at, split_by, created_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            seed.member_id,
            seed.cluster_id,
            seed.entity_type,
            seed.entity_id,
            seed.is_canonical,
            _FIXED_TIMESTAMP,
            "splink_v1",
            seed.split_at,
            "splink_v1" if seed.split_at is not None else None,
            _FIXED_TIMESTAMP,
        ),
    )


def _insert_match_decision(db_conn: psycopg.Connection, seed: MatchDecisionSeed) -> None:
    db_conn.execute(
        """
        INSERT INTO core.match_decision (
            id, entity_type, entity_id_a, entity_id_b, decision,
            confidence, decided_by, decision_method, match_evidence,
            decided_at, superseded_by, superseded_at, created_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, 'splink_v1', 'probabilistic',
                %s, %s, %s, %s, %s)
        """,
        (
            seed.decision_id,
            seed.entity_type,
            min(seed.entity_id_a, seed.entity_id_b),
            max(seed.entity_id_a, seed.entity_id_b),
            seed.decision,
            seed.confidence,
            Jsonb(seed.match_evidence),
            _FIXED_TIMESTAMP,
            seed.superseded_by,
            _FIXED_TIMESTAMP if seed.superseded_by is not None else None,
            _FIXED_TIMESTAMP,
        ),
    )


# -- Focused seed sub-functions (each well under 60 lines) --


def _seed_entities(db_conn: psycopg.Connection) -> None:
    insert_person(db_conn, Person(id=PERSON_CANONICAL_ID, canonical_name="Jane Canonical"))
    insert_person(db_conn, Person(id=PERSON_ALIAS_ID, canonical_name="J. Canonical"))
    insert_person(db_conn, Person(id=PERSON_SECOND_CLUSTER_ID, canonical_name="Alex Secondary"))
    insert_person(db_conn, Person(id=PERSON_SPLIT_MEMBER_ID, canonical_name="Split Person"))
    insert_organization(db_conn, Organization(id=ORG_CANONICAL_ID, canonical_name="Civibus Action Org"))
    insert_organization(db_conn, Organization(id=ORG_SECOND_ID, canonical_name="Unaffiliated Org"))


def _seed_clusters(db_conn: psycopg.Connection) -> None:
    for cluster_id, entity_type, canonical_id, confidence, count in [
        (CLUSTER_PERSON_TOP_ID, "person", PERSON_CANONICAL_ID, 0.95, 3),
        (CLUSTER_ORG_ID, "organization", ORG_CANONICAL_ID, 0.90, 1),
        (CLUSTER_PERSON_LOW_ID, "person", PERSON_SECOND_CLUSTER_ID, 0.80, 1),
        (CLUSTER_HISTORICAL_ONLY_ID, "person", PERSON_SPLIT_MEMBER_ID, 0.99, 1),
    ]:
        _insert_cluster(
            db_conn,
            cluster_id=cluster_id,
            entity_type=entity_type,
            canonical_entity_id=canonical_id,
            cluster_confidence=confidence,
            member_count=count,
        )


def _seed_cluster_members(db_conn: psycopg.Connection) -> None:
    members = [
        ClusterMemberSeed(
            UUID("00000000-0000-0000-0000-000000004101"), CLUSTER_PERSON_TOP_ID, "person", PERSON_CANONICAL_ID, True
        ),
        ClusterMemberSeed(
            UUID("00000000-0000-0000-0000-000000004102"), CLUSTER_PERSON_TOP_ID, "person", PERSON_ALIAS_ID, False
        ),
        ClusterMemberSeed(
            UUID("00000000-0000-0000-0000-000000004103"),
            CLUSTER_PERSON_TOP_ID,
            "person",
            PERSON_SPLIT_MEMBER_ID,
            False,
            _SPLIT_TIMESTAMP,
        ),
        ClusterMemberSeed(
            UUID("00000000-0000-0000-0000-000000004104"), CLUSTER_ORG_ID, "organization", ORG_CANONICAL_ID, True
        ),
        ClusterMemberSeed(
            UUID("00000000-0000-0000-0000-000000004105"),
            CLUSTER_PERSON_LOW_ID,
            "person",
            PERSON_SECOND_CLUSTER_ID,
            True,
        ),
        ClusterMemberSeed(
            UUID("00000000-0000-0000-0000-000000004106"),
            CLUSTER_HISTORICAL_ONLY_ID,
            "person",
            PERSON_SPLIT_MEMBER_ID,
            True,
            _SPLIT_TIMESTAMP,
        ),
    ]
    for member in members:
        _insert_cluster_member(db_conn, member)


def _seed_match_decisions(db_conn: psycopg.Connection) -> None:
    decisions = [
        MatchDecisionSeed(
            MATCH_PERSON_ACTIVE_ID,
            "person",
            PERSON_CANONICAL_ID,
            PERSON_ALIAS_ID,
            "match",
            0.97,
            {"name_similarity": 0.98},
        ),
        MatchDecisionSeed(
            MATCH_PERSON_POSSIBLE_ACTIVE_ID,
            "person",
            PERSON_CANONICAL_ID,
            PERSON_SECOND_CLUSTER_ID,
            "possible_match",
            0.71,
            {"name_similarity": 0.73},
        ),
        MatchDecisionSeed(
            MATCH_PERSON_SUPERSEDED_ID,
            "person",
            PERSON_CANONICAL_ID,
            PERSON_SECOND_CLUSTER_ID,
            "probable_match",
            0.88,
            {"name_similarity": 0.89},
            MATCH_PERSON_POSSIBLE_ACTIVE_ID,
        ),
        MatchDecisionSeed(
            MATCH_ORG_NO_MATCH_ID,
            "organization",
            ORG_CANONICAL_ID,
            ORG_SECOND_ID,
            "no_match",
            0.14,
            {"name_similarity": 0.12},
        ),
    ]
    for decision in decisions:
        _insert_match_decision(db_conn, decision)


# -- Public entry point --


def seed_er_read_fixture(db_conn: psycopg.Connection) -> dict[str, UUID]:
    """Seed all ER read-fixture data and return deterministic IDs for assertions."""
    # ER read tests assert exact counts and ordering, so start from an empty active ER state.
    db_conn.execute("DELETE FROM core.match_decision")
    db_conn.execute("DELETE FROM core.cluster_member")
    db_conn.execute("DELETE FROM core.entity_cluster")

    _seed_entities(db_conn)
    _seed_clusters(db_conn)
    _seed_cluster_members(db_conn)
    _seed_match_decisions(db_conn)

    return {
        "cluster_person_top_id": CLUSTER_PERSON_TOP_ID,
        "cluster_org_id": CLUSTER_ORG_ID,
        "cluster_person_low_id": CLUSTER_PERSON_LOW_ID,
        "person_canonical_id": PERSON_CANONICAL_ID,
        "person_alias_id": PERSON_ALIAS_ID,
        "person_split_member_id": PERSON_SPLIT_MEMBER_ID,
        "org_canonical_id": ORG_CANONICAL_ID,
    }
