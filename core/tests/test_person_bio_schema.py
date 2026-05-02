from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import psycopg
import pytest

from core.db import select_person


pytestmark = pytest.mark.integration


def _insert_person_with_bio_fields(db_conn: psycopg.Connection, person_id: UUID) -> None:
    db_conn.execute(
        """
        INSERT INTO core.person (
            id,
            canonical_name,
            identifiers,
            bio_text,
            bio_source_url,
            bio_license,
            bio_pulled_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (
            person_id,
            "Bio Test Person",
            "{}",
            "Bio text from source",
            "https://example.org/biography",
            "licensed",
            datetime(2026, 4, 30, 12, 34, 56, tzinfo=timezone.utc),
        ),
    )


def test_person_bio_fields_roundtrip_through_select_person(db_conn: psycopg.Connection) -> None:
    person_id = uuid4()
    _insert_person_with_bio_fields(db_conn, person_id)

    selected = select_person(db_conn, person_id)

    assert selected is not None
    assert selected.bio_text == "Bio text from source"
    assert selected.bio_source_url == "https://example.org/biography"
    assert selected.bio_license == "licensed"
    assert selected.bio_pulled_at == datetime(2026, 4, 30, 12, 34, 56, tzinfo=timezone.utc)


def test_person_bio_license_rejects_invalid_values(db_conn: psycopg.Connection) -> None:
    with db_conn.cursor() as cursor:
        cursor.execute("SAVEPOINT invalid_bio_license")
        try:
            with pytest.raises(psycopg.errors.CheckViolation):
                cursor.execute(
                    """
                    INSERT INTO core.person (
                        id,
                        canonical_name,
                        identifiers,
                        bio_license
                    )
                    VALUES (%s, %s, %s, %s)
                    """,
                    (
                        uuid4(),
                        "Invalid Bio License Person",
                        "{}",
                        "copyright_unknown",
                    ),
                )
        finally:
            cursor.execute("ROLLBACK TO SAVEPOINT invalid_bio_license")
            cursor.execute("RELEASE SAVEPOINT invalid_bio_license")
