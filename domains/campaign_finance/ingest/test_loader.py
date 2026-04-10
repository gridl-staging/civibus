from __future__ import annotations

from uuid import uuid4
from unittest.mock import MagicMock

import pytest

from core.types.python.models import Address, Organization, Person, compute_record_hash
from domains.campaign_finance.ingest import loader


def _build_contribution(**overrides: object) -> dict[str, object]:
    contribution: dict[str, object] = {
        "sub_id": "4072820251212123890",
        "pdf_url": "https://docquery.fec.gov/cgi-bin/fecimg/?202507289764269530",
        "entity_type": "IND",
        "contributor_first_name": "ALICE",
        "contributor_last_name": "JONES",
        "committee_id": "C00123456",
        "committee_name": "TEST PAC",
    }
    contribution.update(overrides)
    return contribution


def test_load_contribution_persists_entities_and_links(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = MagicMock()
    data_source_id = uuid4()
    source_record_id = uuid4()
    person_id = uuid4()
    organization_id = uuid4()
    address_id = uuid4()

    contribution = _build_contribution()
    extracted_person = Person(
        canonical_name="Alice Jones",
        first_name="ALICE",
        last_name="JONES",
        identifiers={"employer": "ACME"},
    )
    extracted_organization = Organization(
        canonical_name="TEST PAC",
        identifiers={"fec_committee_id": "C00123456"},
    )
    extracted_address = Address(
        raw_address="123 MAIN ST, DURHAM, NC 27701",
        city="DURHAM",
        state="NC",
        zip5="27701",
    )

    try_insert_source_record = MagicMock(return_value=source_record_id)
    extract_contribution = MagicMock(
        return_value={
            "person": extracted_person,
            "organization": extracted_organization,
            "address": extracted_address,
        }
    )
    upsert_address = MagicMock(return_value=address_id)
    find_person = MagicMock(return_value=None)
    insert_person = MagicMock(return_value=person_id)
    find_organization = MagicMock(return_value=None)
    insert_organization = MagicMock(return_value=organization_id)
    insert_entity_source = MagicMock()
    insert_entity_address = MagicMock()

    monkeypatch.setattr(loader, "try_insert_source_record", try_insert_source_record)
    monkeypatch.setattr(loader, "extract_contribution", extract_contribution)
    monkeypatch.setattr(loader, "upsert_address", upsert_address)
    monkeypatch.setattr(loader, "find_person_by_name_and_zip", find_person)
    monkeypatch.setattr(loader, "insert_person", insert_person)
    monkeypatch.setattr(loader, "find_organization_by_identifier", find_organization)
    monkeypatch.setattr(loader, "insert_organization", insert_organization)
    monkeypatch.setattr(loader, "insert_entity_source", insert_entity_source)
    monkeypatch.setattr(loader, "insert_entity_address", insert_entity_address)

    loaded = loader.load_contribution(conn, data_source_id, contribution)

    assert loaded is True
    try_insert_source_record.assert_called_once()
    source_record = try_insert_source_record.call_args.args[1]
    assert source_record.data_source_id == data_source_id
    assert source_record.source_record_key == contribution["sub_id"]
    assert source_record.record_hash == compute_record_hash(contribution)
    assert source_record.raw_fields == contribution

    extract_contribution.assert_called_once_with(contribution)
    upsert_address.assert_called_once_with(conn, extracted_address)
    find_person.assert_called_once_with(conn, "JONES", "ALICE", "27701")
    insert_person.assert_called_once_with(conn, extracted_person)
    find_organization.assert_called_once_with(conn, "fec_committee_id", "C00123456")
    insert_organization.assert_called_once_with(conn, extracted_organization)

    insert_entity_source.assert_any_call(conn, "person", person_id, source_record_id, "donor")
    insert_entity_source.assert_any_call(conn, "organization", organization_id, source_record_id, "recipient")
    insert_entity_source.assert_any_call(conn, "address", address_id, source_record_id, "contributor_address")

    insert_entity_address.assert_any_call(conn, "person", person_id, address_id, source_record_id, "mailing")
    insert_entity_address.assert_any_call(
        conn, "organization", organization_id, address_id, source_record_id, "mailing"
    )


def test_load_contribution_returns_early_when_source_record_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = MagicMock()
    contribution = _build_contribution()

    try_insert_source_record = MagicMock(return_value=None)
    extract_contribution = MagicMock()
    upsert_address = MagicMock()
    insert_person = MagicMock()
    insert_organization = MagicMock()
    insert_entity_source = MagicMock()
    insert_entity_address = MagicMock()

    monkeypatch.setattr(loader, "try_insert_source_record", try_insert_source_record)
    monkeypatch.setattr(loader, "extract_contribution", extract_contribution)
    monkeypatch.setattr(loader, "upsert_address", upsert_address)
    monkeypatch.setattr(loader, "insert_person", insert_person)
    monkeypatch.setattr(loader, "insert_organization", insert_organization)
    monkeypatch.setattr(loader, "insert_entity_source", insert_entity_source)
    monkeypatch.setattr(loader, "insert_entity_address", insert_entity_address)

    loaded = loader.load_contribution(conn, uuid4(), contribution)

    assert loaded is False
    extract_contribution.assert_not_called()
    upsert_address.assert_not_called()
    insert_person.assert_not_called()
    insert_organization.assert_not_called()
    insert_entity_source.assert_not_called()
    insert_entity_address.assert_not_called()


def test_ensure_fec_data_source_returns_existing_id(monkeypatch: pytest.MonkeyPatch) -> None:
    existing_id = uuid4()
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = (existing_id,)
    try_insert_data_source = MagicMock()
    monkeypatch.setattr(loader, "try_insert_data_source", try_insert_data_source)

    data_source_id = loader.ensure_fec_data_source(conn)

    assert data_source_id == existing_id
    try_insert_data_source.assert_not_called()


def test_ensure_fec_data_source_inserts_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    inserted_id = uuid4()
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = None
    try_insert_data_source = MagicMock(return_value=inserted_id)
    monkeypatch.setattr(loader, "try_insert_data_source", try_insert_data_source)

    data_source_id = loader.ensure_fec_data_source(conn)

    assert data_source_id == inserted_id
    try_insert_data_source.assert_called_once()


def test_ensure_fec_data_source_selects_existing_id_after_insert_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing_id = uuid4()
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchone.side_effect = [None, (existing_id,)]
    try_insert_data_source = MagicMock(return_value=None)
    monkeypatch.setattr(loader, "try_insert_data_source", try_insert_data_source)

    data_source_id = loader.ensure_fec_data_source(conn)

    assert data_source_id == existing_id
    try_insert_data_source.assert_called_once()
