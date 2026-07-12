from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from core import db as core_db
from core.types.python.models import Person


pytestmark = pytest.mark.unit


def test_select_person_omits_bio_columns_when_schema_lacks_them(monkeypatch: pytest.MonkeyPatch) -> None:
    person_id = uuid4()
    captured_columns: tuple[str, ...] | None = None

    def _fake_select_row_by_id(
        _conn: object,
        _table_name: str,
        columns: tuple[str, ...],
        _record_id: object,
    ) -> dict[str, object]:
        nonlocal captured_columns
        captured_columns = columns
        now = datetime(2026, 5, 2, 0, 0, 0, tzinfo=timezone.utc)
        return {
            "id": person_id,
            "canonical_name": "Schema Compat Person",
            "name_variants": [],
            "first_name": "Schema",
            "middle_name": None,
            "last_name": "Compat",
            "suffix": None,
            "occupation": None,
            "education": None,
            "date_of_birth": None,
            "year_of_birth": None,
            "identifiers": {},
            "primary_address_id": None,
            "er_cluster_id": None,
            "er_confidence": None,
            "created_at": now,
            "updated_at": now,
        }

    monkeypatch.setattr(core_db, "_PERSON_HAS_BIO_COLUMNS", None)
    monkeypatch.setattr(core_db, "_person_has_bio_columns", lambda _conn: False)
    monkeypatch.setattr(core_db, "_select_row_by_id", _fake_select_row_by_id)

    selected = core_db.select_person(MagicMock(), person_id)

    assert selected is not None
    assert selected.id == person_id
    assert selected.bio_text is None
    assert selected.bio_source_url is None
    assert selected.bio_license is None
    assert selected.bio_pulled_at is None
    assert captured_columns is not None
    assert "bio_text" not in captured_columns
    assert "bio_source_url" not in captured_columns
    assert "bio_license" not in captured_columns
    assert "bio_pulled_at" not in captured_columns


def test_select_person_drops_non_string_identifier_values_from_typed_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    person_id = uuid4()

    def _fake_select_row_by_id(
        _conn: object,
        _table_name: str,
        _columns: tuple[str, ...],
        _record_id: object,
    ) -> dict[str, object]:
        now = datetime(2026, 6, 5, 0, 0, 0, tzinfo=timezone.utc)
        return {
            "id": person_id,
            "canonical_name": "Federal Person",
            "name_variants": [],
            "first_name": "Federal",
            "middle_name": None,
            "last_name": "Person",
            "suffix": None,
            "occupation": None,
            "education": None,
            "bio_text": None,
            "bio_source_url": None,
            "bio_license": None,
            "bio_pulled_at": None,
            "date_of_birth": None,
            "year_of_birth": None,
            "identifiers": {
                "bioguide_id": "A000382",
                "fec_candidate_id": "S4MD00327",
                "fec_candidate_ids": ["S4MD00327", "S6MD03674"],
            },
            "primary_address_id": None,
            "er_cluster_id": None,
            "er_confidence": None,
            "created_at": now,
            "updated_at": now,
        }

    monkeypatch.setattr(core_db, "_select_row_by_id", _fake_select_row_by_id)

    selected = core_db.select_person(MagicMock(), person_id)

    assert selected is not None
    assert selected.identifiers == {
        "bioguide_id": "A000382",
        "fec_candidate_id": "S4MD00327",
    }


def test_insert_person_omits_bio_columns_when_schema_lacks_them(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_columns: tuple[str, ...] | None = None
    captured_values: tuple[object, ...] | None = None

    def _fake_insert_row(
        _conn: object,
        _table_name: str,
        columns: tuple[str, ...],
        values: tuple[object, ...],
    ) -> None:
        nonlocal captured_columns, captured_values
        captured_columns = columns
        captured_values = values

    monkeypatch.setattr(core_db, "_PERSON_HAS_BIO_COLUMNS", None)
    monkeypatch.setattr(core_db, "_person_has_bio_columns", lambda _conn: False)
    monkeypatch.setattr(core_db, "_insert_row", _fake_insert_row)

    person = Person(
        canonical_name="Insert Schema Compat",
        first_name="Insert",
        last_name="Compat",
        bio_text="Should not be referenced in legacy schema",
        bio_source_url="https://example.org/bio",
        bio_license="licensed",
    )
    inserted_id = core_db.insert_person(MagicMock(), person)

    assert inserted_id == person.id
    assert captured_columns is not None
    assert captured_values is not None
    assert len(captured_columns) == len(captured_values)
    assert "bio_text" not in captured_columns
    assert "bio_source_url" not in captured_columns
    assert "bio_license" not in captured_columns
    assert "bio_pulled_at" not in captured_columns


def test_update_person_bio_fields_skips_bio_sql_when_columns_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    cursor = MagicMock()
    cursor.fetchone.return_value = (None, None)
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor

    monkeypatch.setattr(core_db, "_PERSON_HAS_BIO_COLUMNS", None)
    monkeypatch.setattr(core_db, "_person_has_bio_columns", lambda _conn: False)

    updated_fields = core_db.update_person_bio_fields_if_missing(
        conn,
        person_id=uuid4(),
        occupation="Member",
        education="State University",
        bio_text="Bio text",
        bio_source_url="https://example.org/bio",
        bio_license="licensed",
    )

    assert updated_fields == ("occupation", "education")
    executed_select_sql = cursor.execute.call_args_list[0].args[0]
    executed_update_sql = cursor.execute.call_args_list[1].args[0]
    assert "SELECT occupation, education" in executed_select_sql
    assert "bio_text" not in executed_select_sql
    assert "bio_source_url" not in executed_select_sql
    assert "bio_license" not in executed_select_sql
    assert "bio_text" not in executed_update_sql
    assert "bio_source_url" not in executed_update_sql
    assert "bio_license" not in executed_update_sql
