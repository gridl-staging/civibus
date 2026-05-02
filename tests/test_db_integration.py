from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import uuid4

import psycopg
import pytest

from core.db import (
    insert_address,
    insert_data_source,
    insert_organization,
    insert_person,
    insert_person_portrait,
    insert_refresh_run,
    insert_source_record,
    select_active_roster_portrait_for_person,
    select_address,
    select_data_source,
    select_organization,
    select_person,
    select_person_portrait,
    select_refresh_run,
    select_source_record,
)
from core.people.enrichment.models import CandidateEnrichmentRecord, CandidateEnrichmentTarget, PortraitBinaryMetadata
from core.people.enrichment.orchestrator import run_cf_candidate_enrichment, run_nc_enrichment
from core.people.enrichment.strategy_shared import evaluate_portrait_binary
from core.types.python.models import (
    Address,
    DataSource,
    Organization,
    Person,
    PersonPortrait,
    RefreshRun,
    SourceRecord,
    compute_record_hash,
)


pytestmark = pytest.mark.integration


def _valid_house_fec_candidate_id() -> str:
    return f"H0NC{uuid4().int % 100000:05d}"


def test_person_round_trip(db_conn: psycopg.Connection) -> None:
    linked_address = Address(raw_address="500 Link St, Durham, NC 27701")
    insert_address(db_conn, linked_address)

    person = Person(
        canonical_name="Jane Doe",
        name_variants=["J. Doe"],
        first_name="Jane",
        middle_name="A",
        last_name="Doe",
        suffix="Jr",
        occupation="Engineer",
        education="NCSU",
        date_of_birth=date(1990, 4, 3),
        year_of_birth=1990,
        identifiers={"fec_id": "P123"},
        primary_address_id=linked_address.id,
        er_cluster_id=uuid4(),
        er_confidence=0.88,
    )

    inserted_id = insert_person(db_conn, person)
    selected = select_person(db_conn, inserted_id)

    assert selected == person
    assert selected is not None
    assert selected.occupation == "Engineer"
    assert selected.education == "NCSU"


def test_person_portrait_insert_dedupes_repeated_source_image_pair(db_conn: psycopg.Connection) -> None:
    person = Person(canonical_name="Portrait Person")
    insert_person(db_conn, person)

    data_source = DataSource(
        domain="campaign_finance",
        jurisdiction="state/NC",
        name="NC Portrait Feed",
        source_url="https://example.gov/portraits",
    )
    insert_data_source(db_conn, data_source)

    source_record = SourceRecord(
        data_source_id=data_source.id,
        source_record_key="portrait-001",
        source_url="https://example.gov/portraits/portrait-001",
        raw_fields={"candidate": "Portrait Person", "portrait": "portrait-001"},
        pull_date=datetime(2026, 4, 25, 13, 0, tzinfo=timezone.utc),
        record_hash=compute_record_hash({"candidate": "Portrait Person", "portrait": "portrait-001"}),
    )
    insert_source_record(db_conn, source_record)

    portrait = PersonPortrait(
        person_id=person.id,
        source_record_id=source_record.id,
        status="active",
        rights_status="public_domain",
        image_hash="7f63cb6d067972c3f34f094bb7e776a8f7f5bf3ce6f5f8a761fd72d4e95f94c4",
        mime_type="image/jpeg",
        width_px=640,
        height_px=480,
        source_image_url="https://images.example.gov/portrait-001.jpg",
        storage_uri="s3://civibus/portraits/portrait-001.jpg",
    )
    first_id = insert_person_portrait(db_conn, portrait)

    repeated_portrait = portrait.model_copy(
        update={
            "id": uuid4(),
            "rights_status": "licensed",
            "width_px": 800,
            "height_px": 600,
            "source_image_url": "https://images.example.gov/portrait-001-copy.jpg",
            "storage_uri": "s3://civibus/portraits/portrait-001-copy.jpg",
        }
    )
    second_id = insert_person_portrait(db_conn, repeated_portrait)

    assert first_id == second_id

    selected = select_person_portrait(db_conn, first_id)
    assert selected is not None
    assert selected.status == "active"
    assert selected.dedup_key == portrait.dedup_key
    assert selected.rights_status == "licensed"
    assert selected.width_px == 800
    assert selected.height_px == 600
    assert selected.source_image_url == "https://images.example.gov/portrait-001-copy.jpg"
    assert selected.storage_uri == "s3://civibus/portraits/portrait-001-copy.jpg"

    with db_conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM core.person_portrait
            WHERE person_id = %s
              AND dedup_key = %s
            """,
            (person.id, portrait.dedup_key),
        )
        portrait_count = cursor.fetchone()[0]
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM core.person_portrait
            WHERE person_id = %s
              AND status = 'active'
            """,
            (person.id,),
        )
        active_count = cursor.fetchone()[0]

    assert portrait_count == 1
    assert active_count == 1


def test_person_portrait_round_trip_accepts_explicit_non_active_statuses(db_conn: psycopg.Connection) -> None:
    person = Person(canonical_name="Small Portrait Person")
    insert_person(db_conn, person)

    data_source = DataSource(
        domain="campaign_finance",
        jurisdiction="state/NC",
        name="NC Portrait QA Feed",
        source_url="https://example.gov/portrait-qa",
    )
    insert_data_source(db_conn, data_source)

    source_record = SourceRecord(
        data_source_id=data_source.id,
        source_record_key="portrait-qa-001",
        source_url="https://example.gov/portrait-qa/001",
        raw_fields={"candidate": "Small Portrait Person", "portrait": "portrait-qa-001"},
        pull_date=datetime(2026, 4, 25, 14, 0, tzinfo=timezone.utc),
        record_hash=compute_record_hash({"candidate": "Small Portrait Person", "portrait": "portrait-qa-001"}),
    )
    insert_source_record(db_conn, source_record)

    portrait = PersonPortrait(
        person_id=person.id,
        source_record_id=source_record.id,
        status="too_small",
        rights_status="unknown",
        image_hash="5e538104ec4d5e8806cb6920e2c69ba70440e9504dcd0e8f2ab0d4e5b95d5f3d",
        mime_type="image/jpeg",
        width_px=120,
        height_px=120,
        source_image_url="https://images.example.gov/portrait-qa-001.jpg",
    )
    portrait_id = insert_person_portrait(db_conn, portrait)

    selected = select_person_portrait(db_conn, portrait_id)

    assert selected is not None
    assert selected.status == "too_small"
    assert selected.width_px == 120
    assert selected.height_px == 120


def test_organization_round_trip(db_conn: psycopg.Connection) -> None:
    linked_address = Address(raw_address="700 Org Blvd, Durham, NC 27701")
    insert_address(db_conn, linked_address)

    organization = Organization(
        canonical_name="Civibus Action Fund",
        name_variants=["CAF"],
        org_type="pac",
        identifiers={"ein": "12-3456789"},
        registered_state="NC",
        formation_date=date(2011, 2, 5),
        dissolution_date=date(2020, 6, 1),
        primary_address_id=linked_address.id,
        er_cluster_id=uuid4(),
        er_confidence=0.91,
    )

    inserted_id = insert_organization(db_conn, organization)
    selected = select_organization(db_conn, inserted_id)

    assert selected == organization


def test_address_round_trip(db_conn: psycopg.Connection) -> None:
    address = Address(
        raw_address="123 Main St, Durham, NC 27701",
        normalized_address="123 MAIN ST DURHAM NC 27701",
        street_number="123",
        street_name="Main St",
        unit="Apt 4",
        city="Durham",
        state="NC",
        zip5="27701",
        zip4="1234",
        county_fips="37063",
        geometry=None,
        geocode_confidence=0.95,
        geocode_source="census",
        geocoded_at=datetime(2026, 3, 13, 13, 20, tzinfo=timezone.utc),
    )

    inserted_id = insert_address(db_conn, address)
    selected = select_address(db_conn, inserted_id)

    assert selected == address


def test_data_source_round_trip(db_conn: psycopg.Connection) -> None:
    data_source = DataSource(
        domain="campaign_finance",
        jurisdiction="federal/fec",
        name="FEC Schedule A API",
        source_url="https://api.open.fec.gov/v1/schedules/schedule_a/",
        source_format="api",
        license="public_domain",
        update_frequency="continuous",
        last_pull_at=datetime(2026, 3, 13, 22, 30, tzinfo=timezone.utc),
        last_pull_status="success",
        record_count=240_000,
        notes="Primary source",
    )

    inserted_id = insert_data_source(db_conn, data_source)
    selected = select_data_source(db_conn, inserted_id)

    assert selected == data_source


def test_source_record_round_trip(db_conn: psycopg.Connection) -> None:
    data_source = DataSource(
        domain="campaign_finance",
        jurisdiction="federal/fec",
        name="FEC Schedule A API",
        source_url="https://api.open.fec.gov/v1/schedules/schedule_a/",
    )
    insert_data_source(db_conn, data_source)

    source_record = SourceRecord(
        data_source_id=data_source.id,
        source_record_key="A1-20260313-001",
        source_url="https://example.gov/record/A1-20260313-001",
        raw_fields={
            "amount": 2500,
            "contributor": {"name": "Jane Doe", "city": "Durham"},
            "flags": ["amended", "verified"],
        },
        pull_date=datetime(2026, 3, 13, 23, 1, tzinfo=timezone.utc),
        record_hash=compute_record_hash(
            {
                "amount": 2500,
                "contributor": {"name": "Jane Doe", "city": "Durham"},
                "flags": ["amended", "verified"],
            }
        ),
        superseded_by=None,
    )

    inserted_id = insert_source_record(db_conn, source_record)
    selected = select_source_record(db_conn, inserted_id)

    assert selected == source_record


def test_refresh_run_round_trip(db_conn: psycopg.Connection) -> None:
    refresh_run = RefreshRun(
        job_key="state-co-contributions",
        domain="campaign_finance",
        jurisdiction="state/CO",
        data_source_names=["TRACER Bulk Download - Contributions"],
        pull_status="success",
        started_at=datetime(2026, 4, 24, 12, 0, tzinfo=timezone.utc),
        completed_at=datetime(2026, 4, 24, 12, 3, tzinfo=timezone.utc),
        inserted_count=120,
        skipped_count=4,
        quarantined_count=1,
        superseded_count=0,
        error_count=0,
        metadata_updates=1,
        message="Refresh job succeeded",
    )

    inserted_id = insert_refresh_run(db_conn, refresh_run)
    selected = select_refresh_run(db_conn, inserted_id)

    assert selected == refresh_run


def test_minimal_fields_round_trip_for_all_models(db_conn: psycopg.Connection) -> None:
    person = Person(canonical_name="Minimal Person")
    organization = Organization(canonical_name="Minimal Org")
    address = Address(raw_address="1 Minimal St, Durham, NC 27701")
    data_source = DataSource(
        domain="campaign_finance",
        name="Minimal Source",
        source_url="https://example.gov/source/minimal",
    )
    source_record = SourceRecord(
        data_source_id=data_source.id,
        raw_fields={"id": "minimal-1"},
        pull_date=datetime(2026, 3, 13, 0, 0, tzinfo=timezone.utc),
    )

    insert_person(db_conn, person)
    insert_organization(db_conn, organization)
    insert_address(db_conn, address)
    insert_data_source(db_conn, data_source)
    insert_source_record(db_conn, source_record)

    assert select_person(db_conn, person.id) == person
    assert select_organization(db_conn, organization.id) == organization
    assert select_address(db_conn, address.id) == address
    assert select_data_source(db_conn, data_source.id) == data_source
    assert select_source_record(db_conn, source_record.id) == source_record


def test_person_bio_fields_round_trip_through_insert_and_select(db_conn: psycopg.Connection) -> None:
    pulled_at = datetime(2026, 4, 30, 12, 34, 56, tzinfo=timezone.utc)
    person = Person(
        canonical_name="Bio Test Person",
        first_name="Bio",
        last_name="Person",
        bio_text="Served three terms in the state legislature.",
        bio_source_url="https://www.ncleg.gov/Members/Biography/H/149",
        bio_license="public_domain",
        bio_pulled_at=pulled_at,
    )

    insert_person(db_conn, person)
    selected = select_person(db_conn, person.id)

    assert selected is not None
    assert selected.bio_text == "Served three terms in the state legislature."
    assert selected.bio_source_url == "https://www.ncleg.gov/Members/Biography/H/149"
    assert selected.bio_license == "public_domain"
    assert selected.bio_pulled_at == pulled_at


def test_data_source_duplicate_domain_jurisdiction_name_raises_unique_violation(db_conn: psycopg.Connection) -> None:
    first_data_source = DataSource(
        domain="campaign_finance",
        jurisdiction="federal/fec",
        name="FEC Schedule A API",
        source_url="https://api.open.fec.gov/v1/schedules/schedule_a/",
    )
    duplicate_data_source = DataSource(
        domain="campaign_finance",
        jurisdiction="federal/fec",
        name="FEC Schedule A API",
        source_url="https://api.open.fec.gov/v1/schedules/schedule_a/",
    )

    insert_data_source(db_conn, first_data_source)

    with pytest.raises(psycopg.errors.UniqueViolation):
        insert_data_source(db_conn, duplicate_data_source)


def test_person_portrait_insert_persists_stage3_metadata_for_rejected_and_active(db_conn: psycopg.Connection) -> None:
    person = Person(canonical_name="QA Contract Person")
    insert_person(db_conn, person)

    data_source = DataSource(
        domain="campaign_finance",
        jurisdiction="state/NC",
        name="NC QA Contract Feed",
        source_url="https://example.gov/qa-contract",
    )
    insert_data_source(db_conn, data_source)

    active_record = SourceRecord(
        data_source_id=data_source.id,
        source_record_key="portrait-qa-active",
        source_url="https://example.gov/qa-contract/active",
        raw_fields={"portrait": "active"},
        pull_date=datetime(2026, 4, 25, 15, 0, tzinfo=timezone.utc),
    )
    rejected_record = SourceRecord(
        data_source_id=data_source.id,
        source_record_key="portrait-qa-rejected",
        source_url="https://example.gov/qa-contract/rejected",
        raw_fields={"portrait": "rejected"},
        pull_date=datetime(2026, 4, 25, 15, 1, tzinfo=timezone.utc),
    )
    insert_source_record(db_conn, active_record)
    insert_source_record(db_conn, rejected_record)

    active_portrait = PersonPortrait(
        person_id=person.id,
        source_record_id=active_record.id,
        status="active",
        rights_status="licensed",
        image_hash="b8f12ea8c9a95d4b4641b03d9fa5a71ad30b44ed6cd4bf793bbe1a5801b986d4",
        mime_type="image/jpeg",
        width_px=900,
        height_px=700,
    )
    rejected_portrait = PersonPortrait(
        person_id=person.id,
        source_record_id=rejected_record.id,
        status="rejected",
        rights_status="restricted",
        image_hash="6da8d7688f09093f4f95357e2f9cd223a198de0f1f2970c72f74ee87f16ec95b",
        mime_type="image/png",
        width_px=64,
        height_px=64,
    )

    active_id = insert_person_portrait(db_conn, active_portrait)
    rejected_id = insert_person_portrait(db_conn, rejected_portrait)

    loaded_active = select_person_portrait(db_conn, active_id)
    loaded_rejected = select_person_portrait(db_conn, rejected_id)

    assert loaded_active is not None
    assert loaded_rejected is not None
    assert loaded_active.status == "active"
    assert loaded_active.rights_status == "licensed"
    assert loaded_active.image_hash == active_portrait.image_hash
    assert loaded_active.mime_type == "image/jpeg"
    assert loaded_active.width_px == 900
    assert loaded_active.height_px == 700

    assert loaded_rejected.status == "rejected"
    assert loaded_rejected.rights_status == "restricted"
    assert loaded_rejected.image_hash == rejected_portrait.image_hash
    assert loaded_rejected.mime_type == "image/png"
    assert loaded_rejected.width_px == 64
    assert loaded_rejected.height_px == 64


def test_person_portrait_dedup_identity_matches_same_binary_hash_upsert(db_conn: psycopg.Connection) -> None:
    person = Person(canonical_name="Deterministic Hash Person")
    insert_person(db_conn, person)

    data_source = DataSource(
        domain="campaign_finance",
        jurisdiction="state/NC",
        name="NC Deterministic Hash Feed",
        source_url="https://example.gov/hash-contract",
    )
    insert_data_source(db_conn, data_source)

    source_record = SourceRecord(
        data_source_id=data_source.id,
        source_record_key="portrait-hash-001",
        source_url="https://example.gov/hash-contract/portrait-hash-001",
        raw_fields={"portrait": "hash-001"},
        pull_date=datetime(2026, 4, 25, 16, 0, tzinfo=timezone.utc),
    )
    insert_source_record(db_conn, source_record)

    binary_image = (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR"
        b"\x00\x00\x02\x00\x00\x00\x02\x00\x08\x02\x00\x00\x00"
        b"\xf4x\xd4\xfa"
        b"\x00\x00\x00\x0cIDAT\x08\xd7c\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00\x18\xdd\x8d\xb1"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    first_status, first_metadata = evaluate_portrait_binary(
        binary_image,
        source_image_url="https://images.example.gov/hash-source.png",
    )
    second_status, second_metadata = evaluate_portrait_binary(
        binary_image,
        source_image_url="https://images.example.gov/hash-source.png",
    )
    assert first_status == "active"
    assert second_status == "active"
    assert first_metadata is not None
    assert second_metadata is not None
    assert first_metadata.image_hash == second_metadata.image_hash

    first_insert = PersonPortrait(
        person_id=person.id,
        source_record_id=source_record.id,
        status="active",
        image_hash=first_metadata.image_hash,
        mime_type=first_metadata.mime_type,
        width_px=first_metadata.width_px,
        height_px=first_metadata.height_px,
        rights_status="public_domain",
    )
    second_insert = first_insert.model_copy(
        update={
            "id": uuid4(),
            "mime_type": "image/jpeg",
            "width_px": 256,
            "height_px": 256,
            "rights_status": "licensed",
        }
    )

    first_id = insert_person_portrait(db_conn, first_insert)
    second_id = insert_person_portrait(db_conn, second_insert)

    assert first_id == second_id
    loaded = select_person_portrait(db_conn, first_id)
    assert loaded is not None
    assert loaded.image_hash == first_metadata.image_hash
    assert loaded.mime_type == "image/jpeg"
    assert loaded.width_px == 256
    assert loaded.height_px == 256
    assert loaded.rights_status == "licensed"


def test_person_portrait_upsert_keeps_takedown_requested_for_same_hash_redist_url(
    db_conn: psycopg.Connection,
) -> None:
    person = Person(canonical_name="Takedown Preservation Person")
    insert_person(db_conn, person)

    data_source = DataSource(
        domain="campaign_finance",
        jurisdiction="state/NC",
        name="NC Takedown Preservation Feed",
        source_url="https://example.gov/takedown-preservation",
    )
    insert_data_source(db_conn, data_source)

    first_record = SourceRecord(
        data_source_id=data_source.id,
        source_record_key="portrait-preserve-001",
        source_url="https://example.gov/takedown-preservation/portrait-preserve-001",
        raw_fields={"portrait": "preserve-001"},
        pull_date=datetime(2026, 4, 28, 10, 0, tzinfo=timezone.utc),
    )
    second_record = SourceRecord(
        data_source_id=data_source.id,
        source_record_key="portrait-preserve-002",
        source_url="https://example.gov/takedown-preservation/portrait-preserve-002",
        raw_fields={"portrait": "preserve-002"},
        pull_date=datetime(2026, 4, 28, 10, 1, tzinfo=timezone.utc),
    )
    insert_source_record(db_conn, first_record)
    insert_source_record(db_conn, second_record)

    first_id = insert_person_portrait(
        db_conn,
        PersonPortrait(
            person_id=person.id,
            source_record_id=first_record.id,
            status="takedown_requested",
            rights_status="restricted",
            image_hash="1" * 64,
            mime_type="image/jpeg",
            width_px=640,
            height_px=480,
            source_image_url="https://images.example.org/takedown-a.jpg",
            storage_uri="s3://civibus/portraits/takedown-a.jpg",
        ),
    )

    second_id = insert_person_portrait(
        db_conn,
        PersonPortrait(
            person_id=person.id,
            source_record_id=second_record.id,
            status="active",
            rights_status="public_domain",
            image_hash="1" * 64,
            mime_type="image/png",
            width_px=800,
            height_px=600,
            source_image_url="https://images.example.org/takedown-b.jpg",
            storage_uri="s3://civibus/portraits/takedown-b.jpg",
        ),
    )

    assert second_id == first_id
    loaded = select_person_portrait(db_conn, first_id)
    assert loaded is not None
    assert loaded.status == "takedown_requested"
    assert loaded.source_record_id == first_record.id
    assert loaded.source_image_url == "https://images.example.org/takedown-a.jpg"
    assert loaded.rights_status == "restricted"

    with db_conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM core.person_portrait
            WHERE person_id = %s
              AND status = 'active'
            """,
            (person.id,),
        )
        active_portrait_count = cursor.fetchone()[0]
    assert active_portrait_count == 0


def test_person_portrait_active_unique_index_blocks_second_active_for_same_person(db_conn: psycopg.Connection) -> None:
    person = Person(canonical_name="Active Uniqueness Person")
    insert_person(db_conn, person)

    data_source = DataSource(
        domain="campaign_finance",
        jurisdiction="state/NC",
        name="NC Active Uniqueness Feed",
        source_url="https://example.gov/active-uniqueness",
    )
    insert_data_source(db_conn, data_source)

    first_record = SourceRecord(
        data_source_id=data_source.id,
        source_record_key="portrait-active-001",
        source_url="https://example.gov/active-uniqueness/portrait-active-001",
        raw_fields={"portrait": "active-001"},
        pull_date=datetime(2026, 4, 25, 17, 0, tzinfo=timezone.utc),
    )
    second_record = SourceRecord(
        data_source_id=data_source.id,
        source_record_key="portrait-active-002",
        source_url="https://example.gov/active-uniqueness/portrait-active-002",
        raw_fields={"portrait": "active-002"},
        pull_date=datetime(2026, 4, 25, 17, 1, tzinfo=timezone.utc),
    )
    insert_source_record(db_conn, first_record)
    insert_source_record(db_conn, second_record)

    first_active = PersonPortrait(
        person_id=person.id,
        source_record_id=first_record.id,
        status="active",
        image_hash="8acef65311e8ecca5fb4e40dcf5a4bcf7f155ef0350f4df1540f08cf9dc69011",
        rights_status="public_domain",
    )
    second_active = PersonPortrait(
        person_id=person.id,
        source_record_id=second_record.id,
        status="active",
        image_hash="dd8f8d48f28ef386311e65d2fce38f62d83ea72caebf0fa2f2f5a97d95071be7",
        rights_status="public_domain",
    )

    insert_person_portrait(db_conn, first_active)
    with pytest.raises(psycopg.errors.UniqueViolation):
        insert_person_portrait(db_conn, second_active)


def test_run_cf_candidate_enrichment_rerun_with_bootstrapped_source_records_keeps_single_active_portrait(
    db_conn: psycopg.Connection,
) -> None:
    person = Person(canonical_name=f"CF Candidate Portrait Rerun Person {uuid4()}")
    insert_person(db_conn, person)
    db_conn.execute(
        """
        INSERT INTO cf.candidate (id, fec_candidate_id, name, person_id, office, state)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (
            uuid4(),
            _valid_house_fec_candidate_id(),
            f"CF Candidate Portrait Rerun {uuid4()}",
            person.id,
            "H",
            "NC",
        ),
    )

    first_summary = run_cf_candidate_enrichment(
        db_conn,
        chain=_IntegrationFakeChain(
            CandidateEnrichmentRecord(
                portrait_image_url="https://images.example.org/cf-candidate-rerun-a.jpg",
                portrait_metadata=PortraitBinaryMetadata(
                    image_hash="c" * 64,
                    mime_type="image/jpeg",
                    width_px=720,
                    height_px=480,
                    source_image_url="https://images.example.org/cf-candidate-rerun-a.jpg",
                ),
            )
        ),
        state="NC",
    )
    second_summary = run_cf_candidate_enrichment(
        db_conn,
        chain=_IntegrationFakeChain(
            CandidateEnrichmentRecord(
                portrait_image_url="https://images.example.org/cf-candidate-rerun-b.jpg",
                portrait_metadata=PortraitBinaryMetadata(
                    image_hash="c" * 64,
                    mime_type="image/png",
                    width_px=960,
                    height_px=640,
                    source_image_url="https://images.example.org/cf-candidate-rerun-b.jpg",
                ),
            )
        ),
        state="NC",
    )

    first_source_record_id = first_summary["source_record_id"]
    second_source_record_id = second_summary["source_record_id"]
    assert first_source_record_id is not None
    assert second_source_record_id is not None
    assert first_source_record_id != second_source_record_id

    with db_conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM core.person_portrait
            WHERE person_id = %s
              AND status = 'active'
            """,
            (person.id,),
        )
        active_count = cursor.fetchone()[0]
        cursor.execute(
            """
            SELECT source_record_id, mime_type, width_px, height_px, source_image_url
            FROM core.person_portrait
            WHERE person_id = %s
            """,
            (person.id,),
        )
        portrait_row = cursor.fetchone()

    assert active_count == 1
    assert portrait_row is not None
    assert portrait_row[0] == second_source_record_id
    assert portrait_row[1] == "image/png"
    assert portrait_row[2] == 960
    assert portrait_row[3] == 640
    assert portrait_row[4] == "https://images.example.org/cf-candidate-rerun-b.jpg"

    assert select_source_record(db_conn, first_source_record_id) is not None
    assert select_source_record(db_conn, second_source_record_id) is not None


class _IntegrationFakeChain:
    def __init__(self, record: CandidateEnrichmentRecord) -> None:
        self._record = record
        self.calls: list[CandidateEnrichmentTarget] = []

    def enrich(self, target: CandidateEnrichmentTarget) -> CandidateEnrichmentRecord:
        self.calls.append(target)
        return self._record


def test_run_nc_enrichment_is_idempotent_for_portrait_provenance_and_bio_fill_only(
    db_conn: psycopg.Connection,
) -> None:
    person = Person(canonical_name=f"NC Runner Person {uuid4()}")
    insert_person(db_conn, person)

    office_id = db_conn.execute(
        """
        INSERT INTO civic.office (name, office_level, state)
        VALUES (%s, 'state', 'NC')
        RETURNING id
        """,
        (f"NC Runner Office {uuid4()}",),
    ).fetchone()[0]
    contest_id = db_conn.execute(
        """
        INSERT INTO civic.contest (name, election_type, election_date, office_id, is_partisan)
        VALUES (%s, 'general', DATE '2026-11-03', %s, TRUE)
        RETURNING id
        """,
        (f"NC Runner Contest {uuid4()}", office_id),
    ).fetchone()[0]
    db_conn.execute(
        """
        INSERT INTO civic.candidacy (person_id, contest_id)
        VALUES (%s, %s)
        """,
        (person.id, contest_id),
    )

    data_source = DataSource(
        domain="campaign_finance",
        jurisdiction="state/NC",
        name=f"NC Enrichment Test Source {uuid4()}",
        source_url="https://example.org/enrichment",
    )
    insert_data_source(db_conn, data_source)
    source_record = SourceRecord(
        data_source_id=data_source.id,
        source_record_key=f"enrichment-{uuid4()}",
        source_url="https://example.org/enrichment/record",
        raw_fields={"record_type": "enrichment"},
        pull_date=datetime(2026, 4, 25, 18, 0, tzinfo=timezone.utc),
        record_hash=compute_record_hash({"record_type": "enrichment"}),
    )
    insert_source_record(db_conn, source_record)

    initial_chain = _IntegrationFakeChain(
        CandidateEnrichmentRecord(
            occupation="Teacher",
            education="NCSU",
            portrait_image_url="https://images.example.org/nc-runner.jpg",
            portrait_metadata=PortraitBinaryMetadata(
                image_hash="b" * 64,
                mime_type="image/jpeg",
                width_px=900,
                height_px=600,
                source_image_url="https://images.example.org/nc-runner.jpg",
            ),
            field_provenance={"occupation": "wikidata", "education": "wikidata"},
        )
    )
    rerun_chain = _IntegrationFakeChain(
        CandidateEnrichmentRecord(
            occupation="Attorney",
            education="Duke University",
            portrait_image_url="https://images.example.org/nc-runner-updated.jpg",
            portrait_metadata=PortraitBinaryMetadata(
                image_hash="b" * 64,
                mime_type="image/jpeg",
                width_px=1024,
                height_px=768,
                source_image_url="https://images.example.org/nc-runner-updated.jpg",
            ),
            field_provenance={"occupation": "ballotpedia", "education": "ballotpedia"},
        )
    )

    first_summary = run_nc_enrichment(
        db_conn,
        chain=initial_chain,
        source_record_id=source_record.id,
        state="NC",
        cycle=2026,
    )
    second_summary = run_nc_enrichment(
        db_conn,
        chain=rerun_chain,
        source_record_id=source_record.id,
        state="NC",
        cycle=2026,
    )

    assert first_summary["processed"] == 1
    assert second_summary["processed"] == 1
    assert len(initial_chain.calls) == 1
    assert len(rerun_chain.calls) == 1

    refreshed_person = select_person(db_conn, person.id)
    assert refreshed_person is not None
    assert refreshed_person.occupation == "Teacher"
    assert refreshed_person.education == "NCSU"

    with db_conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM core.person_portrait
            WHERE person_id = %s
              AND status = 'active'
            """,
            (person.id,),
        )
        active_portrait_count = cursor.fetchone()[0]
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM core.field_provenance
            WHERE entity_type = 'person'
              AND entity_id = %s
              AND is_current = TRUE
              AND field_name IN ('occupation', 'education')
            """,
            (person.id,),
        )
        current_bio_provenance_count = cursor.fetchone()[0]

    assert active_portrait_count == 1
    assert current_bio_provenance_count == 2


def test_run_cf_candidate_enrichment_is_idempotent_for_portrait_provenance_and_bio_fill_only(
    db_conn: psycopg.Connection,
) -> None:
    person = Person(canonical_name=f"CF Candidate Runner Person {uuid4()}")
    insert_person(db_conn, person)
    db_conn.execute(
        """
        INSERT INTO cf.candidate (id, fec_candidate_id, name, person_id, office, state)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (
            uuid4(),
            _valid_house_fec_candidate_id(),
            f"CF Candidate Runner {uuid4()}",
            person.id,
            "H",
            "NC",
        ),
    )

    first_summary = run_cf_candidate_enrichment(
        db_conn,
        chain=_IntegrationFakeChain(
            CandidateEnrichmentRecord(
                occupation="Teacher",
                education="NCSU",
                portrait_image_url="https://images.example.org/cf-candidate-runner.jpg",
                portrait_metadata=PortraitBinaryMetadata(
                    image_hash="b" * 64,
                    mime_type="image/jpeg",
                    width_px=900,
                    height_px=600,
                    source_image_url="https://images.example.org/cf-candidate-runner.jpg",
                ),
            )
        ),
        state="NC",
    )
    second_summary = run_cf_candidate_enrichment(
        db_conn,
        chain=_IntegrationFakeChain(
            CandidateEnrichmentRecord(
                occupation="Attorney",
                education="Duke University",
                portrait_image_url="https://images.example.org/cf-candidate-runner-updated.jpg",
                portrait_metadata=PortraitBinaryMetadata(
                    image_hash="b" * 64,
                    mime_type="image/jpeg",
                    width_px=1024,
                    height_px=768,
                    source_image_url="https://images.example.org/cf-candidate-runner-updated.jpg",
                ),
            )
        ),
        state="NC",
    )

    assert first_summary["processed"] == 1
    assert second_summary["processed"] == 1
    assert first_summary["source_record_id"] != second_summary["source_record_id"]

    refreshed_person = select_person(db_conn, person.id)
    assert refreshed_person is not None
    assert refreshed_person.occupation == "Teacher"
    assert refreshed_person.education == "NCSU"

    with db_conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM core.person_portrait
            WHERE person_id = %s
              AND status = 'active'
            """,
            (person.id,),
        )
        active_portrait_count = cursor.fetchone()[0]
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM core.field_provenance
            WHERE entity_type = 'person'
              AND entity_id = %s
              AND is_current = TRUE
              AND field_name IN ('occupation', 'education')
            """,
            (person.id,),
        )
        current_bio_provenance_count = cursor.fetchone()[0]

    assert active_portrait_count == 1
    assert current_bio_provenance_count == 2


def test_run_cf_candidate_enrichment_bootstraps_data_source_and_source_record_without_fixture_uuid(
    db_conn: psycopg.Connection,
) -> None:
    person = Person(canonical_name=f"CF Candidate Bootstrap Person {uuid4()}")
    insert_person(db_conn, person)
    db_conn.execute(
        """
        INSERT INTO cf.candidate (id, fec_candidate_id, name, person_id, office, state)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (
            uuid4(),
            _valid_house_fec_candidate_id(),
            f"CF Candidate Bootstrap {uuid4()}",
            person.id,
            "H",
            "NC",
        ),
    )

    first_summary = run_cf_candidate_enrichment(
        db_conn,
        chain=_IntegrationFakeChain(
            CandidateEnrichmentRecord(
                occupation="Engineer",
                portrait_image_url="https://images.example.org/bootstrap-first.jpg",
                portrait_metadata=PortraitBinaryMetadata(
                    image_hash="d" * 64,
                    mime_type="image/jpeg",
                    width_px=800,
                    height_px=600,
                    source_image_url="https://images.example.org/bootstrap-first.jpg",
                ),
            )
        ),
        state="NC",
    )
    second_summary = run_cf_candidate_enrichment(
        db_conn,
        chain=_IntegrationFakeChain(
            CandidateEnrichmentRecord(
                occupation="Engineer",
                portrait_image_url="https://images.example.org/bootstrap-second.jpg",
                portrait_metadata=PortraitBinaryMetadata(
                    image_hash="d" * 64,
                    mime_type="image/jpeg",
                    width_px=900,
                    height_px=700,
                    source_image_url="https://images.example.org/bootstrap-second.jpg",
                ),
            )
        ),
        state="NC",
    )

    first_data_source_id = first_summary["data_source_id"]
    second_data_source_id = second_summary["data_source_id"]
    first_source_record_id = first_summary["source_record_id"]
    second_source_record_id = second_summary["source_record_id"]

    assert first_data_source_id is not None
    assert second_data_source_id is not None
    assert first_data_source_id == second_data_source_id
    assert first_source_record_id is not None
    assert second_source_record_id is not None
    assert first_source_record_id != second_source_record_id

    selected_data_source = select_data_source(db_conn, first_data_source_id)
    selected_first_source_record = select_source_record(db_conn, first_source_record_id)
    selected_second_source_record = select_source_record(db_conn, second_source_record_id)
    assert selected_data_source is not None
    assert selected_first_source_record is not None
    assert selected_second_source_record is not None
    assert selected_data_source.source_url == "https://civibus.shareborough.com/provenance/people-enrichment"
    assert selected_first_source_record.source_url is None
    assert selected_second_source_record.source_url is None
    assert selected_first_source_record.data_source_id == first_data_source_id
    assert selected_second_source_record.data_source_id == second_data_source_id
    assert selected_first_source_record.source_record_key == selected_second_source_record.source_record_key

    with db_conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*), COUNT(*) FILTER (WHERE superseded_by IS NULL)
            FROM core.source_record
            WHERE data_source_id = %s
              AND source_record_key = %s
            """,
            (first_data_source_id, selected_first_source_record.source_record_key),
        )
        source_record_count, active_source_record_count = cursor.fetchone()

    assert source_record_count == 2
    assert active_source_record_count == 1


def test_run_cf_candidate_enrichment_limit_run_uses_partial_provenance_without_superseding_full_run(
    db_conn: psycopg.Connection,
) -> None:
    first_person = Person(canonical_name=f"CF Candidate Partial Provenance A {uuid4()}")
    second_person = Person(canonical_name=f"CF Candidate Partial Provenance B {uuid4()}")
    insert_person(db_conn, first_person)
    insert_person(db_conn, second_person)
    db_conn.execute(
        """
        INSERT INTO cf.candidate (id, fec_candidate_id, name, person_id, office, state)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (
            uuid4(),
            _valid_house_fec_candidate_id(),
            f"CF Candidate Partial A {uuid4()}",
            first_person.id,
            "H",
            "NC",
        ),
    )
    db_conn.execute(
        """
        INSERT INTO cf.candidate (id, fec_candidate_id, name, person_id, office, state)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (
            uuid4(),
            _valid_house_fec_candidate_id(),
            f"CF Candidate Partial B {uuid4()}",
            second_person.id,
            "H",
            "NC",
        ),
    )

    full_run_summary = run_cf_candidate_enrichment(
        db_conn,
        chain=_IntegrationFakeChain(CandidateEnrichmentRecord(occupation="Engineer")),
        state="NC",
    )
    limited_run_summary = run_cf_candidate_enrichment(
        db_conn,
        chain=_IntegrationFakeChain(CandidateEnrichmentRecord(occupation="Attorney")),
        state="NC",
        limit=1,
    )

    full_run_source_record_id = full_run_summary["source_record_id"]
    limited_run_source_record_id = limited_run_summary["source_record_id"]
    full_run_data_source_id = full_run_summary["data_source_id"]
    assert full_run_source_record_id is not None
    assert limited_run_source_record_id is not None
    assert full_run_data_source_id is not None

    full_run_source_record = select_source_record(db_conn, full_run_source_record_id)
    limited_run_source_record = select_source_record(db_conn, limited_run_source_record_id)
    assert full_run_source_record is not None
    assert limited_run_source_record is not None

    assert full_run_summary["selected"] == 2
    assert limited_run_summary["selected"] == 1
    assert full_run_source_record.source_record_key == "people-enrichment:cf-candidate:NC:all"
    assert limited_run_source_record.source_record_key == "people-enrichment:cf-candidate:NC:all:limit-1"
    assert full_run_source_record.superseded_by is None
    assert limited_run_source_record.superseded_by is None
    assert limited_run_source_record.raw_fields["run_scope"] == "partial"
    assert limited_run_source_record.raw_fields["effective_limit"] == 1

    with db_conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*), COUNT(*) FILTER (WHERE superseded_by IS NULL)
            FROM core.source_record
            WHERE data_source_id = %s
              AND source_record_key = %s
            """,
            (full_run_data_source_id, "people-enrichment:cf-candidate:NC:all"),
        )
        full_key_count, full_key_active_count = cursor.fetchone()
        cursor.execute(
            """
            SELECT COUNT(*), COUNT(*) FILTER (WHERE superseded_by IS NULL)
            FROM core.source_record
            WHERE data_source_id = %s
              AND source_record_key = %s
            """,
            (full_run_data_source_id, "people-enrichment:cf-candidate:NC:all:limit-1"),
        )
        limited_key_count, limited_key_active_count = cursor.fetchone()

    assert full_key_count == 1
    assert full_key_active_count == 1
    assert limited_key_count == 1
    assert limited_key_active_count == 1


def test_run_cf_candidate_enrichment_blocks_reingest_for_takedown_requested_source_image(
    db_conn: psycopg.Connection,
) -> None:
    person = Person(canonical_name=f"CF Candidate Takedown Person {uuid4()}")
    insert_person(db_conn, person)
    db_conn.execute(
        """
        INSERT INTO cf.candidate (id, fec_candidate_id, name, person_id, office, state)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (
            uuid4(),
            _valid_house_fec_candidate_id(),
            f"CF Candidate Takedown {uuid4()}",
            person.id,
            "H",
            "NC",
        ),
    )

    data_source = DataSource(
        domain="campaign_finance",
        jurisdiction="state/NC",
        name=f"CF Candidate Takedown Source {uuid4()}",
        source_url="https://example.org/cf-candidate-enrichment",
    )
    insert_data_source(db_conn, data_source)
    source_record = SourceRecord(
        data_source_id=data_source.id,
        source_record_key=f"cf-candidate-takedown-{uuid4()}",
        source_url="https://example.org/cf-candidate-enrichment/record",
        raw_fields={"record_type": "cf_candidate_enrichment"},
        pull_date=datetime(2026, 4, 27, 18, 0, tzinfo=timezone.utc),
        record_hash=compute_record_hash({"record_type": "cf_candidate_enrichment"}),
    )
    insert_source_record(db_conn, source_record)
    insert_person_portrait(
        db_conn,
        PersonPortrait(
            person_id=person.id,
            source_record_id=source_record.id,
            status="takedown_requested",
            rights_status="restricted",
            image_hash="f" * 64,
            mime_type="image/jpeg",
            width_px=640,
            height_px=480,
            source_image_url="https://images.example.org/cf-candidate-takedown.jpg",
        ),
    )

    summary = run_cf_candidate_enrichment(
        db_conn,
        chain=_IntegrationFakeChain(
            CandidateEnrichmentRecord(
                portrait_image_url="https://images.example.org/cf-candidate-takedown.jpg",
                portrait_metadata=PortraitBinaryMetadata(
                    image_hash="e" * 64,
                    mime_type="image/jpeg",
                    width_px=1024,
                    height_px=768,
                    source_image_url="https://images.example.org/cf-candidate-takedown.jpg",
                ),
            )
        ),
        source_record_id=source_record.id,
        state="NC",
    )

    with db_conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM core.person_portrait
            WHERE person_id = %s
              AND status = 'active'
            """,
            (person.id,),
        )
        active_portrait_count = cursor.fetchone()[0]
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM core.person_portrait
            WHERE person_id = %s
              AND status = 'takedown_requested'
              AND source_image_url = %s
            """,
            (person.id, "https://images.example.org/cf-candidate-takedown.jpg"),
        )
        takedown_row_count = cursor.fetchone()[0]

    assert summary["processed"] == 1
    assert summary["portrait_writes"] == 0
    assert active_portrait_count == 0
    assert takedown_row_count == 1


def test_select_active_roster_portrait_for_person_prefers_roster_sourced_active_row(
    db_conn: psycopg.Connection,
) -> None:
    person = Person(canonical_name=f"Roster Portrait Person {uuid4()}")
    insert_person(db_conn, person)

    legacy_civics_source = DataSource(
        domain="civics",
        jurisdiction="state/NC",
        name=f"Legacy civics portrait source {uuid4()}",
        source_url="https://example.org/legacy-civics",
        notes="legacy plain-text notes",
    )
    roster_source = DataSource(
        domain="civics",
        jurisdiction="state/NC",
        name=f"Roster portrait source {uuid4()}",
        source_url="https://example.org/roster",
        notes='{"roster_source": true}',
    )
    insert_data_source(db_conn, legacy_civics_source)
    insert_data_source(db_conn, roster_source)

    legacy_civics_record = SourceRecord(
        data_source_id=legacy_civics_source.id,
        source_record_key=f"legacy-civics-{uuid4()}",
        source_url="https://example.org/legacy-civics/record",
        raw_fields={"record_type": "legacy_civics_portrait"},
        pull_date=datetime(2026, 4, 29, 1, 0, tzinfo=timezone.utc),
        record_hash=compute_record_hash({"record_type": "legacy_civics_portrait"}),
    )
    roster_record = SourceRecord(
        data_source_id=roster_source.id,
        source_record_key=f"roster-{uuid4()}",
        source_url="https://example.org/roster/record",
        raw_fields={"record_type": "roster_portrait"},
        pull_date=datetime(2026, 4, 29, 1, 5, tzinfo=timezone.utc),
        record_hash=compute_record_hash({"record_type": "roster_portrait"}),
    )
    insert_source_record(db_conn, legacy_civics_record)
    insert_source_record(db_conn, roster_record)

    insert_person_portrait(
        db_conn,
        PersonPortrait(
            person_id=person.id,
            source_record_id=legacy_civics_record.id,
            status="superseded",
            rights_status="licensed",
            image_hash="1" * 64,
            mime_type="image/jpeg",
            width_px=320,
            height_px=240,
            source_image_url="https://example.org/legacy-civics.jpg",
        ),
    )
    roster_portrait_id = insert_person_portrait(
        db_conn,
        PersonPortrait(
            person_id=person.id,
            source_record_id=roster_record.id,
            status="active",
            rights_status="licensed",
            image_hash="2" * 64,
            mime_type="image/jpeg",
            width_px=640,
            height_px=480,
            source_image_url="https://example.org/roster.jpg",
        ),
    )

    selected = select_active_roster_portrait_for_person(db_conn, person_id=person.id)

    assert selected is not None
    assert selected.id == roster_portrait_id
    assert selected.source_image_url == "https://example.org/roster.jpg"
