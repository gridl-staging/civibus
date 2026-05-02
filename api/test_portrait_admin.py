from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from api.deps import get_db
from api.main import create_app
from core.db import insert_data_source, insert_person, insert_person_portrait, insert_source_record
from core.types.python.models import DataSource, Person, PersonPortrait, SourceRecord


pytestmark = pytest.mark.integration


def _build_admin_api_client(monkeypatch: pytest.MonkeyPatch, connection: psycopg.Connection) -> TestClient:
    monkeypatch.setenv("CIVIBUS_ENV", "production")
    monkeypatch.setenv("CIVIBUS_API_KEYS", "portrait-public-key")
    monkeypatch.setenv("CIVIBUS_ADMIN_API_KEYS", "portrait-admin-key")
    monkeypatch.setenv("CIVIBUS_RATE_LIMIT_REQUESTS", "20")
    monkeypatch.setenv("CIVIBUS_RATE_LIMIT_WINDOW_SECONDS", "60")

    app = create_app()

    def _get_db_override():
        yield connection

    app.dependency_overrides[get_db] = _get_db_override
    return TestClient(app)


def test_portrait_takedown_endpoint_requires_admin_sets_status_and_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
    db_conn: psycopg.Connection,
) -> None:
    person = Person(canonical_name=f"Admin Portrait Subject {uuid4()}")
    insert_person(db_conn, person)
    data_source = DataSource(
        domain="campaign_finance",
        jurisdiction="state/NC",
        name=f"Admin Portrait Source {uuid4()}",
        source_url="https://example.org/admin-portrait/source",
    )
    insert_data_source(db_conn, data_source)
    source_record = SourceRecord(
        data_source_id=data_source.id,
        source_record_key=f"admin-portrait-{uuid4()}",
        source_url="https://example.org/admin-portrait/record",
        raw_fields={"fixture": "portrait-admin-route"},
        pull_date=datetime(2026, 4, 27, 12, 0, tzinfo=timezone.utc),
    )
    insert_source_record(db_conn, source_record)
    portrait = PersonPortrait(
        person_id=person.id,
        source_record_id=source_record.id,
        status="active",
        rights_status="licensed",
        image_hash="c" * 64,
        source_image_url="https://images.example.org/admin-portrait.jpg",
    )
    portrait_id = insert_person_portrait(db_conn, portrait)

    client = _build_admin_api_client(monkeypatch, db_conn)
    with client:
        non_admin_response = client.post(
            f"/v1/admin/portraits/{portrait_id}/takedown",
            headers={"X-API-Key": "portrait-public-key"},
        )
        assert non_admin_response.status_code == 401

        admin_response = client.post(
            f"/v1/admin/portraits/{portrait_id}/takedown",
            headers={"X-API-Key": "portrait-admin-key"},
        )
        assert admin_response.status_code == 200
        assert set(admin_response.json().keys()) == {"id", "status"}
        assert admin_response.json()["id"] == str(portrait_id)
        assert admin_response.json()["status"] == "takedown_requested"

        repeated_admin_response = client.post(
            f"/v1/admin/portraits/{portrait_id}/takedown",
            headers={"X-API-Key": "portrait-admin-key"},
        )
        assert repeated_admin_response.status_code == 200
        assert set(repeated_admin_response.json().keys()) == {"id", "status"}
        assert repeated_admin_response.json()["id"] == str(portrait_id)
        assert repeated_admin_response.json()["status"] == "takedown_requested"
