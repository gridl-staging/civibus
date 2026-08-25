"""Person absorption biography bundle specimens.

Production owner: `core/entity_resolution/person_absorption.py`.
Merge contract: `docs/design/2026_08_21_er_general_merge_design.md`.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from core.db_ingest import insert_entity_address, insert_field_provenance
from core.entity_resolution.persist_clusters_test_support import (
    _absorb_person_cluster,
    _canonical_and_member,
    _canonical_and_two_members,
    _insert_address_row,
    _person_exists,
)
from core.entity_resolution.test_extract import _insert_person
from core.entity_resolution.test_persist import _create_person, _insert_data_source, _insert_source_record

pytestmark = pytest.mark.integration


def _bio_bundle(db_conn: psycopg.Connection, person_id: UUID) -> tuple[object, ...] | None:
    """Read the four columns that this contract moves as one atomic bundle."""
    return db_conn.execute(
        "SELECT bio_text, bio_source_url, bio_license, bio_pulled_at FROM core.person WHERE id = %s",
        (person_id,),
    ).fetchone()


def _seed_absorbed_member_bundle_row(
    db_conn: psycopg.Connection,
    *,
    person_id: UUID,
    bio_values: dict[str, object],
    name_variants: list[str],
    identifiers: Jsonb,
) -> None:
    """Seed one absorbed member with the shared bundle plus its own name/identifier observations."""
    db_conn.execute(
        """
        UPDATE core.person
        SET bio_text = %(bio_text)s,
            bio_source_url = %(bio_source_url)s,
            bio_license = %(bio_license)s,
            bio_pulled_at = %(bio_pulled_at)s,
            year_of_birth = 1980,
            name_variants = %(name_variants)s,
            identifiers = %(identifiers)s
        WHERE id = %(person_id)s
        """,
        {
            **bio_values,
            "name_variants": name_variants,
            "identifiers": identifiers,
            "person_id": person_id,
        },
    )


def _seed_complete_bio_bundle(
    db_conn: psycopg.Connection,
    *,
    person_ids: list[UUID],
    bio_text: str,
    bio_source_url: str,
    bio_pulled_at: datetime,
) -> None:
    """Write a complete, public-domain biography bundle onto every named person."""
    db_conn.execute(
        """
        UPDATE core.person
        SET bio_text = %s, bio_source_url = %s, bio_license = 'public_domain', bio_pulled_at = %s
        WHERE id = ANY(%s)
        """,
        (bio_text, bio_source_url, bio_pulled_at, person_ids),
    )


def test_person_absorption_imports_complete_person_field_bundle_from_three_person_component(
    db_conn: psycopg.Connection,
) -> None:
    canonical_id = uuid4()
    member_one = uuid4()
    member_two = uuid4()
    _insert_person(
        db_conn,
        person_id=canonical_id,
        canonical_name="Jane Canonical",
        first_name="Jane",
        last_name="Canonical",
        date_of_birth=None,
        identifiers={"fec_candidate_id": "H0AA00001"},
    )
    _insert_person(
        db_conn,
        person_id=member_one,
        canonical_name=" Jane Member A ",
        first_name="Jane",
        last_name="Member",
        date_of_birth=date(1980, 5, 5),
        identifiers={},
    )
    _insert_person(
        db_conn,
        person_id=member_two,
        canonical_name="Jane Member B",
        first_name="Jane",
        last_name="Member",
        date_of_birth=date(1980, 5, 5),
        identifiers={},
    )
    bio_pulled_at = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    bio_values = {
        "bio_text": "Served as county commissioner before election.",
        "bio_source_url": "https://bio.example.test/jane",
        "bio_license": "public_domain",
        "bio_pulled_at": bio_pulled_at,
    }
    db_conn.execute(
        """
        UPDATE core.person
        SET name_variants = ARRAY[' Jane C ', 'Jane Canonical', 'JANE OBSERVED', ''],
            identifiers = %s
        WHERE id = %s
        """,
        (Jsonb({"fec_candidate_id": "H0AA00001"}), canonical_id),
    )
    _seed_absorbed_member_bundle_row(
        db_conn,
        person_id=member_one,
        bio_values=bio_values,
        name_variants=["Jane Alias", "", " Jane Alias "],
        identifiers=Jsonb({"fec_candidate_ids": [" H0AA00001 ", "S0NC00002"]}),
    )
    _seed_absorbed_member_bundle_row(
        db_conn,
        person_id=member_two,
        bio_values=bio_values,
        name_variants=["Other Alias", "Jane Alias"],
        identifiers=Jsonb({"fec_candidate_id": " S0NC00002 ", "bioguide_id": "B000001"}),
    )
    data_source_id = _insert_data_source(db_conn, name="field-bundle-source")
    member_one_source = _insert_source_record(db_conn, data_source_id=data_source_id, source_record_key="bundle-one")
    member_two_source = _insert_source_record(db_conn, data_source_id=data_source_id, source_record_key="bundle-two")
    address_source = _insert_source_record(db_conn, data_source_id=data_source_id, source_record_key="bundle-address")
    for source_record_id, person_id in [(member_one_source, member_one), (member_two_source, member_two)]:
        insert_field_provenance(db_conn, "person", person_id, "bio_text", bio_values["bio_text"], source_record_id)
        insert_field_provenance(
            db_conn, "person", person_id, "bio_source_url", bio_values["bio_source_url"], source_record_id
        )
        insert_field_provenance(
            db_conn, "person", person_id, "bio_license", bio_values["bio_license"], source_record_id
        )
        insert_field_provenance(db_conn, "person", person_id, "date_of_birth", "1980-05-05", source_record_id)
        insert_field_provenance(db_conn, "person", person_id, "year_of_birth", "1980", source_record_id)
    primary_address_id = _insert_address_row(db_conn, raw_address="900 Bundle Lane")
    db_conn.execute("UPDATE core.person SET primary_address_id = %s WHERE id = %s", (primary_address_id, member_one))
    entity_address_id = insert_entity_address(
        db_conn, "person", member_one, primary_address_id, address_source, address_role="mailing"
    )

    _absorb_person_cluster(
        db_conn,
        canonical_id=canonical_id,
        member_ids={canonical_id, member_one, member_two},
    )

    assert not _person_exists(db_conn, member_one)
    assert not _person_exists(db_conn, member_two)
    row = db_conn.execute(
        """
        SELECT bio_text, bio_source_url, bio_license, bio_pulled_at, date_of_birth,
               year_of_birth, primary_address_id, name_variants, identifiers
        FROM core.person
        WHERE id = %s
        """,
        (canonical_id,),
    ).fetchone()
    assert row == (
        bio_values["bio_text"],
        bio_values["bio_source_url"],
        bio_values["bio_license"],
        bio_pulled_at,
        date(1980, 5, 5),
        1980,
        primary_address_id,
        ["JANE OBSERVED", "Jane Alias", "Jane C", "Jane Member A", "Jane Member B", "Other Alias"],
        {"bioguide_id": "B000001", "fec_candidate_ids": ["H0AA00001", "S0NC00002"]},
    )
    assert db_conn.execute(
        "SELECT entity_id, source_record_id FROM core.entity_address WHERE id = %s",
        (entity_address_id,),
    ).fetchone() == (canonical_id, address_source), (
        "primary_address_id may fill only when the absorbed address link survives on the canonical person"
    )


def test_person_absorption_does_not_stitch_biography_bundle_across_members(
    db_conn: psycopg.Connection,
) -> None:
    """Biography value/source/license/pulled-at move as ONE atomic bundle.

    No absorbed member below carries a complete bundle. An implementation that fills the four
    fields independently can synthesize a survivor bundle that never existed on any single person.
    The contract is stricter: absent one complete absorbed observation, the canonical bio bundle
    stays NULL even though each individual field has an attributed non-null source somewhere.
    """
    canonical_id, member_one, member_two = _canonical_and_two_members(db_conn, prefix="BioBundleAtomic")
    bio_pulled_at = datetime(2026, 2, 3, 4, 5, 6, tzinfo=UTC)
    db_conn.execute(
        """
        UPDATE core.person
        SET bio_text = %s,
            bio_source_url = %s
        WHERE id = %s
        """,
        ("Served on the county board.", "https://bio.example.test/atomic", member_one),
    )
    db_conn.execute(
        """
        UPDATE core.person
        SET bio_license = %s,
            bio_pulled_at = %s
        WHERE id = %s
        """,
        ("public_domain", bio_pulled_at, member_two),
    )
    data_source_id = _insert_data_source(db_conn, name="bio-bundle-atomic-source")
    member_one_source = _insert_source_record(
        db_conn, data_source_id=data_source_id, source_record_key="bio-bundle-atomic-one"
    )
    member_two_source = _insert_source_record(
        db_conn, data_source_id=data_source_id, source_record_key="bio-bundle-atomic-two"
    )
    insert_field_provenance(db_conn, "person", member_one, "bio_text", "Served on the county board.", member_one_source)
    insert_field_provenance(
        db_conn,
        "person",
        member_one,
        "bio_source_url",
        "https://bio.example.test/atomic",
        member_one_source,
    )
    insert_field_provenance(db_conn, "person", member_two, "bio_license", "public_domain", member_two_source)
    insert_field_provenance(
        db_conn, "person", member_two, "bio_pulled_at", bio_pulled_at.isoformat(), member_two_source
    )

    _absorb_person_cluster(
        db_conn,
        canonical_id=canonical_id,
        member_ids={canonical_id, member_one, member_two},
    )

    assert not _person_exists(db_conn, member_one)
    assert not _person_exists(db_conn, member_two)
    assert _bio_bundle(db_conn, canonical_id) == (None, None, None, None)


def test_person_absorption_skips_biography_bundle_when_provenance_names_another_text(
    db_conn: psycopg.Connection,
) -> None:
    """The biography bundle moves only when its own attribution names the bundle's values."""
    canonical_id, member_id = _canonical_and_member(db_conn, prefix="BioMismatch")
    data_source_id = _insert_data_source(db_conn, name="bio-mismatch-source")
    member_source = _insert_source_record(db_conn, data_source_id=data_source_id, source_record_key="bio-mismatch")
    bio_pulled_at = datetime(2026, 2, 3, 4, 5, 6, tzinfo=UTC)
    _seed_complete_bio_bundle(
        db_conn,
        person_ids=[member_id],
        bio_text="Served two terms on the water board.",
        bio_source_url="https://bio.example.test/mismatch",
        bio_pulled_at=bio_pulled_at,
    )
    # Only `bio_text` disagrees with the stored scalar; the rest of the bundle is attributed.
    insert_field_provenance(db_conn, "person", member_id, "bio_text", "A different biography.", member_source)
    insert_field_provenance(
        db_conn, "person", member_id, "bio_source_url", "https://bio.example.test/mismatch", member_source
    )
    insert_field_provenance(db_conn, "person", member_id, "bio_license", "public_domain", member_source)

    _absorb_person_cluster(db_conn, canonical_id=canonical_id, member_ids={canonical_id, member_id})

    assert not _person_exists(db_conn, member_id)
    assert _bio_bundle(db_conn, canonical_id) == (None, None, None, None), (
        "an unsourced bundle value blocks the whole atomic bundle move"
    )


def test_person_absorption_moves_biography_bundle_without_bio_source_url_provenance(
    db_conn: psycopg.Connection,
) -> None:
    """The bundle transfers when its production-recorded fields are attributed.

    `core/people/enrichment/orchestrator.py` never records `bio_source_url` provenance, so gating
    the bundle on that field makes a shipped merge rule dead on live data. Attribution for the
    fields the provenance owner actually writes (`bio_text`, `bio_license`) must be sufficient.
    """
    canonical_id, member_id = _canonical_and_member(db_conn, prefix="BioNoSourceUrl")
    data_source_id = _insert_data_source(db_conn, name="bio-no-source-url")
    member_source = _insert_source_record(db_conn, data_source_id=data_source_id, source_record_key="bio-no-url")
    bio_pulled_at = datetime(2026, 3, 4, 5, 6, 7, tzinfo=UTC)
    bio_text = "Chaired the transit authority for a decade."
    bio_source_url = "https://bio.example.test/no-url-prov"
    _seed_complete_bio_bundle(
        db_conn,
        person_ids=[member_id],
        bio_text=bio_text,
        bio_source_url=bio_source_url,
        bio_pulled_at=bio_pulled_at,
    )
    # Mirror production: attribution exists for bio_text and bio_license, never for bio_source_url.
    insert_field_provenance(db_conn, "person", member_id, "bio_text", bio_text, member_source)
    insert_field_provenance(db_conn, "person", member_id, "bio_license", "public_domain", member_source)

    _absorb_person_cluster(db_conn, canonical_id=canonical_id, member_ids={canonical_id, member_id})

    assert not _person_exists(db_conn, member_id)
    assert _bio_bundle(db_conn, canonical_id) == (bio_text, bio_source_url, "public_domain", bio_pulled_at)


def test_person_absorption_moves_biography_bundle_attributed_on_a_later_member(
    db_conn: psycopg.Connection,
) -> None:
    """Bundle attribution is a component-level question, exactly as consensus fills treat it.

    Two absorbed members carry the byte-identical complete bundle and only the higher-id one
    carries `core.field_provenance` for it. Consulting the lowest-id complete row alone would drop
    a fully sourced biography during an irreversible merge.
    """
    canonical_id = uuid4()
    unattributed_id, attributed_id = sorted([uuid4(), uuid4()])
    _create_person(db_conn, person_id=canonical_id, name="BioAttribution Canonical")
    _create_person(db_conn, person_id=unattributed_id, name="BioAttribution Unattributed")
    _create_person(db_conn, person_id=attributed_id, name="BioAttribution Attributed")
    bio_pulled_at = datetime(2026, 3, 4, 5, 6, 7, tzinfo=UTC)
    bio_text = "Chaired the transit authority for two terms."
    bio_source_url = "https://bio.example.test/later-member"
    _seed_complete_bio_bundle(
        db_conn,
        person_ids=[unattributed_id, attributed_id],
        bio_text=bio_text,
        bio_source_url=bio_source_url,
        bio_pulled_at=bio_pulled_at,
    )
    data_source_id = _insert_data_source(db_conn, name="bio-later-member-source")
    attributed_source = _insert_source_record(
        db_conn, data_source_id=data_source_id, source_record_key="bio-later-member"
    )
    insert_field_provenance(db_conn, "person", attributed_id, "bio_text", bio_text, attributed_source)
    insert_field_provenance(db_conn, "person", attributed_id, "bio_license", "public_domain", attributed_source)

    _absorb_person_cluster(
        db_conn,
        canonical_id=canonical_id,
        member_ids={canonical_id, unattributed_id, attributed_id},
    )

    assert not _person_exists(db_conn, unattributed_id)
    assert not _person_exists(db_conn, attributed_id)
    assert _bio_bundle(db_conn, canonical_id) == (bio_text, bio_source_url, "public_domain", bio_pulled_at), (
        "an identical bundle attributed on any complete absorbed row authorises the move"
    )
