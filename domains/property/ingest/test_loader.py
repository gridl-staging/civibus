from __future__ import annotations

import inspect
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from core.types.python.models import Address, Organization, Person
from domains.property.ingest import durham_source
from domains.property.ingest import loader


def _build_normalized_record(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "reid": "100000001",
        "pin": "0821123456",
        "source_url": durham_source.build_durham_source_url("0821123456"),
        "raw_record": {"REID": "100000001", "PIN": "0821123456"},
        "owner_record": {
            "PROPERTY_OWNER": "SMITH JOHN",
            "OWNER_MAIL_1": "922 LANCASTER ST",
            "OWNER_MAIL_2": "",
            "OWNER_MAIL_3": "",
            "OWNER_MAIL_CITY": "DURHAM",
            "OWNER_MAIL_STATE": "NC",
            "OWNER_MAIL_ZIP": "27701",
        },
        "site_address": "922 LANCASTER ST",
        "property_description": "LOT 1",
        "city": "DURHAM",
        "zoning_class": "RS-8",
        "land_class": "RESIDENTIAL",
        "acreage": Decimal("0.31"),
        "neighborhood": "OLD EAST DURHAM",
        "fire_district": "DURHAM",
        "deed_date": date(2024, 1, 1),
        "deed_book": "1234",
        "deed_page": "567",
        "tax_year": 2024,
        "land_assessed_value": Decimal("120000"),
        "improvement_assessed_value": Decimal("250000"),
        "total_assessed_value": Decimal("370000"),
        "assessed_at": date(2024, 1, 1),
        "heated_area": 1890,
        "exemption_description": None,
        "is_pending": False,
        "owner_name_as_filed": "SMITH JOHN",
        "owner_mail_line1": "922 LANCASTER ST",
        "owner_mail_line2": "",
        "owner_mail_line3": "",
        "owner_mail_city": "DURHAM",
        "owner_mail_state": "NC",
        "owner_mail_zip5": "27701",
    }
    record.update(overrides)
    return record


def test_ensure_durham_data_source_returns_existing_id(monkeypatch: pytest.MonkeyPatch) -> None:
    existing_id = uuid4()
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = (existing_id,)
    try_insert_data_source = MagicMock()
    monkeypatch.setattr(loader, "try_insert_data_source", try_insert_data_source)

    data_source_id = loader.ensure_durham_data_source(conn)

    assert data_source_id == existing_id
    try_insert_data_source.assert_not_called()


def test_ensure_durham_data_source_inserts_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    inserted_id = uuid4()
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = None
    try_insert_data_source = MagicMock(return_value=inserted_id)
    monkeypatch.setattr(loader, "try_insert_data_source", try_insert_data_source)

    data_source_id = loader.ensure_durham_data_source(conn)

    assert data_source_id == inserted_id
    try_insert_data_source.assert_called_once()


def test_build_source_record_uses_reid_and_per_record_source_url() -> None:
    data_source_id = uuid4()
    normalized_record = _build_normalized_record()

    source_record = loader._build_source_record(data_source_id, normalized_record)

    assert source_record.data_source_id == data_source_id
    assert source_record.source_record_key == normalized_record["reid"]
    assert source_record.source_url == durham_source.build_durham_source_url(str(normalized_record["pin"]))
    assert str(normalized_record["pin"]) in str(source_record.source_url)
    assert source_record.raw_fields == normalized_record["raw_record"]


def test_build_source_record_derives_source_url_from_pin_when_normalized_source_url_missing() -> None:
    data_source_id = uuid4()
    normalized_record = _build_normalized_record(source_url=None)

    source_record = loader._build_source_record(data_source_id, normalized_record)

    assert source_record.source_url == durham_source.build_durham_source_url(str(normalized_record["pin"]))


def test_build_source_record_is_deterministic_for_same_fixture_record() -> None:
    data_source_id = uuid4()
    normalized_record = _build_normalized_record()

    first_source_record = loader._build_source_record(data_source_id, normalized_record)
    second_source_record = loader._build_source_record(data_source_id, normalized_record)

    assert first_source_record.source_record_key == second_source_record.source_record_key
    assert first_source_record.source_url == second_source_record.source_url
    assert first_source_record.record_hash == second_source_record.record_hash


def test_build_source_record_rejects_missing_pin() -> None:
    with pytest.raises(ValueError, match="pin"):
        loader._build_source_record(uuid4(), _build_normalized_record(pin="  "))


def test_load_durham_record_short_circuits_duplicate_source_record(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = MagicMock()
    normalized_record = _build_normalized_record()
    data_source_id = uuid4()

    try_insert_source_record = MagicMock(return_value=None)
    extract_owner = MagicMock()
    persist_record = MagicMock()
    incoming_source_record = loader._build_source_record(data_source_id, normalized_record)
    monkeypatch.setattr(loader, "try_insert_source_record", try_insert_source_record)
    monkeypatch.setattr(
        loader,
        "_select_active_source_record",
        MagicMock(
            return_value=loader._ActiveSourceRecord(
                id=uuid4(),
                source_url=incoming_source_record.source_url,
                record_hash=incoming_source_record.record_hash,
            )
        ),
    )
    monkeypatch.setattr(loader, "extract_owner", extract_owner)
    monkeypatch.setattr(loader, "_persist_durham_property_record", persist_record)

    loaded = loader.load_durham_record(conn, data_source_id, uuid4(), normalized_record)

    assert loaded is False
    extract_owner.assert_not_called()
    persist_record.assert_not_called()


def test_load_durham_record_uses_stage4_owner_extractor(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = MagicMock()
    source_record_id = uuid4()
    normalized_record = _build_normalized_record()
    owner_extraction = {
        "person": Person(canonical_name="Smith John", identifiers={"owner_name_as_filed": "SMITH JOHN"}),
        "organization": None,
        "persons": [Person(canonical_name="Smith John", identifiers={"owner_name_as_filed": "SMITH JOHN"})],
        "address": Address(raw_address="922 LANCASTER ST, DURHAM, NC 27701", city="DURHAM", state="NC", zip5="27701"),
    }

    try_insert_source_record = MagicMock(return_value=source_record_id)
    extract_owner = MagicMock(return_value=owner_extraction)
    persist_record = MagicMock()
    monkeypatch.setattr(loader, "try_insert_source_record", try_insert_source_record)
    monkeypatch.setattr(loader, "extract_owner", extract_owner)
    monkeypatch.setattr(loader, "_persist_durham_property_record", persist_record)

    loaded = loader.load_durham_record(conn, uuid4(), uuid4(), normalized_record)

    assert loaded is True
    extract_owner.assert_called_once_with(normalized_record["owner_record"])
    persist_record.assert_called_once()
    source_record = try_insert_source_record.call_args.args[1]
    assert source_record.source_record_key == "100000001"
    assert source_record.source_url == durham_source.build_durham_source_url("0821123456")


def test_load_durham_record_passes_owner_extraction_to_persistence(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = MagicMock()
    data_source_id = uuid4()
    jurisdiction_id = uuid4()
    source_record_id = uuid4()
    normalized_record = _build_normalized_record()
    owner_extraction = {
        "person": None,
        "organization": Organization(
            canonical_name="Duke University", identifiers={"owner_name_as_filed": "DUKE UNIVERSITY"}
        ),
        "persons": [],
        "address": None,
    }

    monkeypatch.setattr(loader, "try_insert_source_record", MagicMock(return_value=source_record_id))
    monkeypatch.setattr(loader, "extract_owner", MagicMock(return_value=owner_extraction))
    persist_record = MagicMock()
    monkeypatch.setattr(loader, "_persist_durham_property_record", persist_record)

    loaded = loader.load_durham_record(conn, data_source_id, jurisdiction_id, normalized_record)

    assert loaded is True
    persist_record.assert_called_once_with(
        conn=conn,
        normalized_record=normalized_record,
        owner_extraction=owner_extraction,
        source_record_id=source_record_id,
        jurisdiction_id=jurisdiction_id,
    )


def test_load_durham_records_raises_record_errors_without_savepoints(monkeypatch: pytest.MonkeyPatch) -> None:
    load_durham_record = MagicMock(side_effect=[True, RuntimeError("boom")])
    monkeypatch.setattr(loader, "load_durham_record", load_durham_record)

    with pytest.raises(RuntimeError, match="boom"):
        loader.load_durham_records(
            MagicMock(),
            uuid4(),
            uuid4(),
            [_build_normalized_record(reid="1"), _build_normalized_record(reid="2")],
        )

    assert load_durham_record.call_count == 2


def test_insert_ownership_row_signature_stays_within_parameter_limit() -> None:
    signature = inspect.signature(loader._insert_ownership_row)
    non_connection_parameters = [name for name in signature.parameters if name != "conn"]
    assert len(non_connection_parameters) <= 6


def test_loader_reuses_durham_source_coercion_helpers() -> None:
    assert loader._required_nested_text is durham_source._required_nested_text
    assert loader._required_text is durham_source._required_text
    assert loader._optional_text is durham_source._optional_text
    assert loader._optional_decimal is durham_source._optional_decimal
    assert loader._optional_int is durham_source._optional_int
    assert loader._optional_date is durham_source._optional_date
