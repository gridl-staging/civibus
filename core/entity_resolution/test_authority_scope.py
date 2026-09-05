from __future__ import annotations

from uuid import uuid4

import psycopg

from core.db import insert_data_source, insert_entity_source, insert_organization, insert_person, insert_source_record
from core.entity_resolution.extract import extract_organizations_for_matching, extract_persons_for_matching
from core.entity_resolution.scoring import _authority_pair_is_permitted, run_deterministic_rules
from core.types.python.models import DataSource, Organization, Person, SourceRecord, compute_record_hash, utc_now


def _source(
    conn: psycopg.Connection,
    *,
    authority_type: str,
    authority_code: str,
    label: str,
) -> tuple[DataSource, SourceRecord]:
    source = DataSource(
        domain="campaign_finance",
        jurisdiction=f"{authority_type}/{authority_code}",
        filing_authority_type=authority_type,
        filing_authority_code=authority_code,
        name=f"ER authority fixture {label} {uuid4()}",
        source_url=f"https://example.test/{label}",
    )
    insert_data_source(conn, source)
    raw_fields = {"label": label}
    record = SourceRecord(
        data_source_id=source.id,
        source_record_key=f"record-{label}-{uuid4()}",
        raw_fields=raw_fields,
        pull_date=utc_now(),
        record_hash=compute_record_hash(raw_fields),
    )
    insert_source_record(conn, record)
    return source, record


def test_probabilistic_authority_guard_refuses_disjoint_campaign_scopes() -> None:
    assert _authority_pair_is_permitted(
        {"filing_authority_scopes": ["state:WA"]},
        {"filing_authority_scopes": ["state:WA", "municipality:SEA"]},
    )
    assert not _authority_pair_is_permitted(
        {"filing_authority_scopes": ["state:WA"]},
        {"filing_authority_scopes": ["municipality:SEA"]},
    )
    assert _authority_pair_is_permitted({}, {"filing_authority_scopes": ["state:WA"]})


def test_deterministic_identifier_rules_match_within_authority_but_not_across_it(
    db_conn: psycopg.Connection,
) -> None:
    _, state_record_a = _source(db_conn, authority_type="state", authority_code="WA", label="state-a")
    _, state_record_b = _source(db_conn, authority_type="state", authority_code="WA", label="state-b")
    _, city_record = _source(
        db_conn,
        authority_type="municipality",
        authority_code="SEA",
        label="city",
    )

    people = [
        Person(canonical_name=f"Authority Candidate {label}", identifiers={"fec_candidate_id": "H1WA00042"})
        for label in ("State A", "State B", "City")
    ]
    organizations = [
        Organization(canonical_name=f"Authority Committee {label}", identifiers={"fec_committee_id": "C00000042"})
        for label in ("State A", "State B", "City")
    ]
    records = (state_record_a, state_record_b, city_record)
    for person, organization, record in zip(people, organizations, records, strict=True):
        insert_person(db_conn, person)
        insert_organization(db_conn, organization)
        insert_entity_source(db_conn, "person", person.id, record.id, "candidate")
        insert_entity_source(db_conn, "organization", organization.id, record.id, "committee")

    person_pairs = {
        frozenset((pair["entity_id_a"], pair["entity_id_b"])) for pair in run_deterministic_rules(db_conn, "person")
    }
    organization_pairs = {
        frozenset((pair["entity_id_a"], pair["entity_id_b"]))
        for pair in run_deterministic_rules(db_conn, "organization")
    }

    assert frozenset((people[0].id, people[1].id)) in person_pairs
    assert frozenset((organizations[0].id, organizations[1].id)) in organization_pairs
    for state_index in (0, 1):
        assert frozenset((people[state_index].id, people[2].id)) not in person_pairs
        assert frozenset((organizations[state_index].id, organizations[2].id)) not in organization_pairs

    person_scopes = {
        row["id"]: set(row["filing_authority_scopes"])
        for row in extract_persons_for_matching(db_conn)
        if row["id"] in {person.id for person in people}
    }
    organization_scopes = {
        row["id"]: set(row["filing_authority_scopes"])
        for row in extract_organizations_for_matching(db_conn)
        if row["id"] in {organization.id for organization in organizations}
    }
    assert person_scopes[people[0].id] == {"state:WA"}
    assert person_scopes[people[2].id] == {"municipality:SEA"}
    assert organization_scopes[organizations[0].id] == {"state:WA"}
    assert organization_scopes[organizations[2].id] == {"municipality:SEA"}
