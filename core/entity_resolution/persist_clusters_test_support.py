"""Shared test support for the `persist_auto_merge_clusters` DB-backed contract.

Owns DB seeding, row builders, and blocker reason slugs for the replacement test modules.
Deliberately named so pytest's `test_*.py` / `*_test.py` collection patterns do not pick
it up: this module defines no specimens and carries no assertions -- every `assert` stays
with the test that owns it.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb

from core.entity_resolution import person_absorption_preflight
from core.entity_resolution.persist import persist_auto_merge_clusters
from core.entity_resolution.test_persist import (
    _create_org,
    _create_person,
    _insert_data_source,
    _insert_entity_source,
    _insert_source_record,
)


_ENTITY_NAME_SUFFIXES = ("Alpha", "Beta", "Gamma", "Delta", "Echo")


_BLOCKER_TWO_ACTIVE_PORTRAITS = person_absorption_preflight._BLOCKER_TWO_ACTIVE_PORTRAITS
_BLOCKER_OVERLAPPING_OFFICEHOLDING = person_absorption_preflight._BLOCKER_OVERLAPPING_OFFICEHOLDING
_BLOCKER_ACTIVE_NON_MATCH_DECISION = person_absorption_preflight._BLOCKER_ACTIVE_NON_MATCH_DECISION
_BLOCKER_MANUAL_CONFIRMED_NON_MATCH = person_absorption_preflight._BLOCKER_MANUAL_CONFIRMED_NON_MATCH
_BLOCKER_CONFLICTING_ANCHOR_SCALAR = person_absorption_preflight._BLOCKER_CONFLICTING_ANCHOR_SCALAR
_BLOCKER_CONFLICTING_IDENTIFIER = person_absorption_preflight._BLOCKER_CONFLICTING_IDENTIFIER
_BLOCKER_CONFLICTING_CONSENSUS_SCALAR = person_absorption_preflight._BLOCKER_CONFLICTING_CONSENSUS_SCALAR
_BLOCKER_DOB_YEAR_MISMATCH = person_absorption_preflight._BLOCKER_DOB_YEAR_MISMATCH


def _create_entity(db_conn: psycopg.Connection, *, entity_type: str, entity_id: UUID, name: str) -> None:
    """Create one clusterable row of the requested entity type.

    The reversible logical-merge contract (unwind, shrink, canonical reassignment, dissolution)
    is exercised against `organization`, because `person` components are now absorbed physically
    and their non-canonical rows do not survive to be restored.
    """
    if entity_type == "person":
        _create_person(db_conn, person_id=entity_id, name=name)
        return
    _create_org(db_conn, organization_id=entity_id, name=name)


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


def _setup_entities_with_individual_sources(
    db_conn: psycopg.Connection,
    *,
    scenario_prefix: str,
    count: int,
    entity_type: str = "person",
) -> tuple[list[UUID], list[UUID]]:
    if count > len(_ENTITY_NAME_SUFFIXES):
        raise ValueError(f"count must be <= {len(_ENTITY_NAME_SUFFIXES)}")

    entity_ids = [uuid4() for _ in range(count)]
    data_source_id = _insert_data_source(db_conn, name=f"{scenario_prefix.lower()}-source")
    source_record_ids = [
        _insert_source_record(
            db_conn,
            data_source_id=data_source_id,
            source_record_key=f"{scenario_prefix.lower()}-{suffix.lower()}",
        )
        for suffix in _ENTITY_NAME_SUFFIXES[:count]
    ]
    for entity_id, suffix, source_record_id in zip(
        entity_ids,
        _ENTITY_NAME_SUFFIXES[:count],
        source_record_ids,
        strict=True,
    ):
        _create_entity(db_conn, entity_type=entity_type, entity_id=entity_id, name=f"{scenario_prefix} {suffix}")
        _insert_entity_source(
            db_conn,
            entity_type=entity_type,
            entity_id=entity_id,
            source_record_id=source_record_id,
            extraction_role="donor",
        )
    return entity_ids, source_record_ids


def _setup_three_entities_with_shared_source(
    db_conn: psycopg.Connection,
    *,
    scenario_prefix: str,
    entity_type: str = "person",
) -> tuple[UUID, UUID, UUID, UUID, UUID, UUID, UUID]:
    entity_a = uuid4()
    entity_b = uuid4()
    entity_c = uuid4()
    for entity_id, suffix in ((entity_a, "Alpha"), (entity_b, "Beta"), (entity_c, "Gamma")):
        _create_entity(db_conn, entity_type=entity_type, entity_id=entity_id, name=f"{scenario_prefix} {suffix}")

    data_source_id = _insert_data_source(db_conn, name=f"{scenario_prefix.lower()}-source")
    source_a = _insert_source_record(
        db_conn, data_source_id=data_source_id, source_record_key=f"{scenario_prefix.lower()}-a"
    )
    source_b = _insert_source_record(
        db_conn, data_source_id=data_source_id, source_record_key=f"{scenario_prefix.lower()}-b"
    )
    source_c = _insert_source_record(
        db_conn, data_source_id=data_source_id, source_record_key=f"{scenario_prefix.lower()}-c"
    )
    source_shared = _insert_source_record(
        db_conn,
        data_source_id=data_source_id,
        source_record_key=f"{scenario_prefix.lower()}-shared",
    )

    for entity_id, source_record_id in (
        (entity_a, source_a),
        (entity_b, source_b),
        (entity_c, source_c),
        (entity_a, source_shared),
        (entity_c, source_shared),
    ):
        _insert_entity_source(
            db_conn,
            entity_type=entity_type,
            entity_id=entity_id,
            source_record_id=source_record_id,
            extraction_role="donor",
        )

    return entity_a, entity_b, entity_c, source_a, source_b, source_c, source_shared


def _manual_tombstone_cluster_fixture(
    db_conn: psycopg.Connection,
    *,
    scenario_prefix: str,
    absorbed_only_source: bool = False,
) -> tuple[UUID, UUID, UUID, UUID]:
    canonical_id = uuid4()
    absorbed_id = uuid4()
    _create_person(db_conn, person_id=canonical_id, name=f"{scenario_prefix} Canonical")
    _create_person(db_conn, person_id=absorbed_id, name=f"{scenario_prefix} Absorbed")

    cluster_id = uuid4()
    db_conn.execute(
        """
        INSERT INTO core.entity_cluster (
            id, entity_type, canonical_entity_id, cluster_confidence, member_count
        )
        VALUES (%s, 'person', %s, 0.99, 2)
        """,
        (cluster_id, canonical_id),
    )
    for entity_id, is_canonical in ((canonical_id, True), (absorbed_id, False)):
        db_conn.execute(
            """
            INSERT INTO core.cluster_member (
                cluster_id, entity_type, entity_id, is_canonical, merged_at, merged_by
            )
            VALUES (%s, 'person', %s, %s, NOW(), 'manual:test')
            """,
            (cluster_id, entity_id, is_canonical),
        )
    db_conn.execute(
        """
        UPDATE core.person
        SET er_cluster_id = %s,
            er_confidence = 0.99
        WHERE id IN (%s, %s)
        """,
        (cluster_id, canonical_id, absorbed_id),
    )

    data_source_id = _insert_data_source(db_conn, name=f"{scenario_prefix.lower()}-tombstone-source")
    source_record_id = _insert_source_record(
        db_conn,
        data_source_id=data_source_id,
        source_record_key=f"{scenario_prefix.lower()}-shared",
    )
    db_conn.execute(
        """
        INSERT INTO core.entity_source (
            entity_type, entity_id, source_record_id, extraction_role, extracted_fields
        )
        VALUES ('person', %s, %s, 'donor', %s)
        """,
        (
            canonical_id,
            source_record_id,
            Jsonb(
                {
                    "_er_source_entity_ids": [
                        str(owner_id)
                        for owner_id in sorted({absorbed_id} if absorbed_only_source else {canonical_id, absorbed_id})
                    ]
                }
            ),
        ),
    )
    db_conn.execute(
        """
        INSERT INTO core.person_absorption (
            absorbed_person_id,
            canonical_person_id,
            cluster_id,
            merged_by,
            absorbed_payload
        )
        VALUES (%s, %s, %s, 'manual:test', %s)
        """,
        (
            absorbed_id,
            canonical_id,
            cluster_id,
            Jsonb({"id": str(absorbed_id), "canonical_name": f"{scenario_prefix} Absorbed"}),
        ),
    )
    db_conn.execute("DELETE FROM core.person WHERE id = %s", (absorbed_id,))
    return canonical_id, absorbed_id, cluster_id, source_record_id


def _absorb_person_cluster(
    db_conn: psycopg.Connection,
    *,
    canonical_id: UUID,
    member_ids: set[UUID],
    min_confidence: float = 0.98,
) -> list[UUID]:
    """Invoke the person merge orchestrator that Stages 2-4 extend into physical absorption."""
    return persist_auto_merge_clusters(
        db_conn,
        [
            _cluster_component(
                canonical_entity_id=canonical_id,
                member_ids=member_ids,
                min_confidence=min_confidence,
            )
        ],
        "person",
    )


def _person_exists(db_conn: psycopg.Connection, person_id: UUID) -> bool:
    row = db_conn.execute("SELECT 1 FROM core.person WHERE id = %s", (person_id,)).fetchone()
    return row is not None


def _canonical_and_member(db_conn: psycopg.Connection, *, prefix: str) -> tuple[UUID, UUID]:
    canonical_id = uuid4()
    member_id = uuid4()
    _create_person(db_conn, person_id=canonical_id, name=f"{prefix} Canonical")
    _create_person(db_conn, person_id=member_id, name=f"{prefix} Member")
    return canonical_id, member_id


def _canonical_and_two_members(db_conn: psycopg.Connection, *, prefix: str) -> tuple[UUID, UUID, UUID]:
    people, _source_records = _setup_entities_with_individual_sources(db_conn, scenario_prefix=prefix, count=3)
    return people[0], people[1], people[2]


# ---- fixture row builders (fixture-scoped IDs only) -------------------------


def _insert_cf_candidate(db_conn: psycopg.Connection, *, person_id: UUID, name: str = "Absorb Cand") -> UUID:
    candidate_id = uuid4()
    # Format ck_candidate_fec_candidate_id_format: ^[HSP][0-9][A-Z0-9]{2}[0-9]{5}$
    fec_candidate_id = f"H{uuid4().int % 10}{uuid4().hex[:2].upper()}{uuid4().int % 100_000:05d}"
    db_conn.execute(
        "INSERT INTO cf.candidate (id, fec_candidate_id, name, office, person_id) VALUES (%s, %s, %s, 'H', %s)",
        (candidate_id, fec_candidate_id, name, person_id),
    )
    return candidate_id


def _insert_cf_transaction(
    db_conn: psycopg.Connection,
    *,
    filing_id: UUID,
    committee_id: UUID,
    contributor_person_id: UUID | None,
    contributor_organization_id: UUID | None = None,
) -> UUID:
    transaction_id = uuid4()
    db_conn.execute(
        """
        INSERT INTO cf.transaction (
            id, filing_id, committee_id, transaction_type, amount,
            contributor_person_id, contributor_organization_id, amendment_indicator
        )
        VALUES (%s, %s, %s, '15', 250.00, %s, %s, 'N')
        """,
        (transaction_id, filing_id, committee_id, contributor_person_id, contributor_organization_id),
    )
    return transaction_id


def _insert_prop_parcel(db_conn: psycopg.Connection) -> UUID:
    parcel_id = uuid4()
    tag = uuid4().hex[:10]
    db_conn.execute(
        """
        INSERT INTO prop.parcel (id, reid, pin, site_address)
        VALUES (%s, %s, %s, %s)
        """,
        (parcel_id, f"REID-{tag}", f"PIN-{tag}", f"{tag} Main St"),
    )
    return parcel_id


def _insert_prop_ownership(
    db_conn: psycopg.Connection,
    *,
    parcel_id: UUID,
    owner_person_id: UUID | None,
    owner_organization_id: UUID | None = None,
) -> UUID:
    ownership_id = uuid4()
    db_conn.execute(
        """
        INSERT INTO prop.ownership (id, parcel_id, owner_name, owner_person_id, owner_organization_id)
        VALUES (%s, %s, 'ABSORB OWNER', %s, %s)
        """,
        (ownership_id, parcel_id, owner_person_id, owner_organization_id),
    )
    return ownership_id


def _insert_person_portrait(
    db_conn: psycopg.Connection,
    *,
    person_id: UUID,
    source_record_id: UUID,
    dedup_key: str,
    status: str = "active",
    image_hash: str = "sha256-portrait",
) -> UUID:
    portrait_id = uuid4()
    db_conn.execute(
        """
        INSERT INTO core.person_portrait (
            id, person_id, source_record_id, status, rights_status, image_hash, dedup_key
        )
        VALUES (%s, %s, %s, %s, 'public_domain', %s, %s)
        """,
        (portrait_id, person_id, source_record_id, status, image_hash, dedup_key),
    )
    return portrait_id


def _insert_donor_cluster_person(db_conn: psycopg.Connection, *, person_id: UUID) -> UUID:
    cluster_id = uuid4()
    db_conn.execute(
        """
        INSERT INTO core.entity_cluster (id, entity_type, canonical_entity_id, cluster_confidence, member_count)
        VALUES (%s, 'donor_identity', %s, 0.99, 1)
        """,
        (cluster_id, uuid4()),
    )
    db_conn.execute(
        "INSERT INTO core.donor_cluster_person (cluster_id, person_id) VALUES (%s, %s)",
        (cluster_id, person_id),
    )
    return cluster_id


def _insert_civic_office(db_conn: psycopg.Connection) -> UUID:
    office_id = uuid4()
    db_conn.execute(
        "INSERT INTO civic.office (id, name, office_level) VALUES (%s, %s, 'federal')",
        (office_id, f"Office {uuid4().hex[:8]}"),
    )
    return office_id


def _insert_civic_contest(db_conn: psycopg.Connection, *, office_id: UUID) -> UUID:
    contest_id = uuid4()
    db_conn.execute(
        """
        INSERT INTO civic.contest (id, name, election_type, office_id)
        VALUES (%s, %s, 'general', %s)
        """,
        (contest_id, f"Contest {uuid4().hex[:8]}", office_id),
    )
    return contest_id


def _insert_civic_candidacy(
    db_conn: psycopg.Connection,
    *,
    person_id: UUID,
    contest_id: UUID,
    party: str | None = None,
    name_on_ballot: str | None = None,
    source_record_id: UUID | None = None,
) -> UUID:
    candidacy_id = uuid4()
    db_conn.execute(
        """
        INSERT INTO civic.candidacy (id, person_id, contest_id, party, name_on_ballot, source_record_id)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (candidacy_id, person_id, contest_id, party, name_on_ballot, source_record_id),
    )
    return candidacy_id


def _insert_civic_officeholding(
    db_conn: psycopg.Connection,
    *,
    person_id: UUID,
    office_id: UUID,
    start: str,
    end: str | None,
    source_record_id: UUID | None = None,
) -> UUID:
    officeholding_id = uuid4()
    db_conn.execute(
        """
        INSERT INTO civic.officeholding (id, person_id, office_id, valid_period, source_record_id)
        VALUES (%s, %s, %s, daterange(%s, %s, '[)'), %s)
        """,
        (officeholding_id, person_id, office_id, start, end, source_record_id),
    )
    return officeholding_id


def _insert_address_row(db_conn: psycopg.Connection, *, raw_address: str) -> UUID:
    # `idx_address_raw_address_dedup` is a GLOBAL unique index on `raw_address`, so a fixed
    # literal collides with any ambient row carrying the same text and turns a behavior test
    # into a fixture UniqueViolation. Every caller gets a fixture-unique address string.
    address_id = uuid4()
    db_conn.execute(
        "INSERT INTO core.address (id, raw_address) VALUES (%s, %s)",
        (address_id, f"{raw_address} #{uuid4().hex[:8]}"),
    )
    return address_id


def _insert_contact_point(
    db_conn: psycopg.Connection,
    *,
    owner_id: UUID,
    value_raw: str,
    source_record_id: UUID,
    role: str | None = "campaign",
    is_preferred: bool = False,
    contact_type: str = "email",
) -> UUID:
    contact_point_id = uuid4()
    db_conn.execute(
        """
        INSERT INTO core.contact_point (
            id, type, value_raw, role, owner_type, owner_id, source_record_id, is_preferred
        )
        VALUES (%s, %s, %s, %s, 'person', %s, %s, %s)
        """,
        (contact_point_id, contact_type, value_raw, role, owner_id, source_record_id, is_preferred),
    )
    return contact_point_id
