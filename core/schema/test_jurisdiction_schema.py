from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import psycopg
import pytest


pytestmark = pytest.mark.integration


def _insert_jurisdiction(
    db_conn: psycopg.Connection,
    *,
    name: str,
    jurisdiction_type: str,
    fips: str | None = None,
    state_fips: str | None = None,
    county_geoid: str | None = None,
    place_geoid: str | None = None,
    parent_id: UUID | None = None,
    state: str | None = None,
) -> UUID:
    return db_conn.execute(
        """
        INSERT INTO core.jurisdiction (
            name,
            jurisdiction_type,
            fips,
            state_fips,
            county_geoid,
            place_geoid,
            parent_id,
            state
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (name, jurisdiction_type, fips, state_fips, county_geoid, place_geoid, parent_id, state),
    ).fetchone()[0]


def _insert_jurisdiction_with_timestamps(
    db_conn: psycopg.Connection,
    *,
    name: str,
    jurisdiction_type: str,
    fips: str | None,
    created_at: datetime,
    updated_at: datetime,
) -> UUID:
    return db_conn.execute(
        """
        INSERT INTO core.jurisdiction (
            name,
            jurisdiction_type,
            fips,
            created_at,
            updated_at
        )
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id
        """,
        (name, jurisdiction_type, fips, created_at, updated_at),
    ).fetchone()[0]


def test_jurisdiction_table_exists(db_conn: psycopg.Connection) -> None:
    table_name = db_conn.execute("SELECT to_regclass('core.jurisdiction')").fetchone()[0]
    assert table_name == "core.jurisdiction"


def test_jurisdiction_state_and_county_insert_with_parent(db_conn: psycopg.Connection) -> None:
    state_id = _insert_jurisdiction(
        db_conn,
        name="North Carolina",
        jurisdiction_type="state",
        fips="37",
        state="NC",
    )
    county_id = _insert_jurisdiction(
        db_conn,
        name="Durham County",
        jurisdiction_type="county",
        fips="37063",
        parent_id=state_id,
        state="NC",
    )

    parent_id = db_conn.execute(
        "SELECT parent_id FROM core.jurisdiction WHERE id = %s",
        (county_id,),
    ).fetchone()[0]

    assert isinstance(state_id, UUID)
    assert isinstance(county_id, UUID)
    assert parent_id == state_id


def test_jurisdiction_rejects_unknown_parent_id(db_conn: psycopg.Connection) -> None:
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        _insert_jurisdiction(
            db_conn,
            name="Durham County",
            jurisdiction_type="county",
            fips="37063",
            parent_id=uuid4(),
            state="NC",
        )


def test_jurisdiction_fips_unique_when_non_null(db_conn: psycopg.Connection) -> None:
    _insert_jurisdiction(db_conn, name="North Carolina", jurisdiction_type="state", fips="37")

    with pytest.raises(psycopg.errors.UniqueViolation):
        _insert_jurisdiction(
            db_conn,
            name="Duplicate NC",
            jurisdiction_type="state",
            fips="37",
        )


@pytest.mark.parametrize(
    ("jurisdiction_type", "field_name", "value"),
    (
        ("state", "state_fips", "37"),
        ("county", "county_geoid", "37063"),
        ("municipality", "place_geoid", "0644000"),
        ("municipality", "county_geoid", "06075"),
    ),
)
def test_jurisdiction_accepts_typed_geography_for_compatible_types(
    db_conn: psycopg.Connection,
    jurisdiction_type: str,
    field_name: str,
    value: str,
) -> None:
    inserted_id = _insert_jurisdiction(
        db_conn,
        name=f"Typed {field_name}",
        jurisdiction_type=jurisdiction_type,
        fips=value,
        **{field_name: value},
    )

    assert isinstance(inserted_id, UUID)


@pytest.mark.parametrize(
    ("jurisdiction_type", "field_name", "value"),
    (
        ("county", "state_fips", "37"),
        ("state", "county_geoid", "37063"),
        ("county", "place_geoid", "0644000"),
        ("state", "state_fips", "٣٧"),
        ("county", "county_geoid", "3706A"),
        ("municipality", "place_geoid", "064400"),
    ),
)
def test_jurisdiction_rejects_invalid_typed_geography_or_type_pairing(
    db_conn: psycopg.Connection,
    jurisdiction_type: str,
    field_name: str,
    value: str,
) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        _insert_jurisdiction(
            db_conn,
            name=f"Invalid {field_name}",
            jurisdiction_type=jurisdiction_type,
            fips=value,
            **{field_name: value},
        )


@pytest.mark.parametrize(
    ("jurisdiction_type", "field_name", "value"),
    (
        ("state", "state_fips", "37"),
        ("county", "county_geoid", "37063"),
        ("municipality", "place_geoid", "0644000"),
    ),
)
def test_jurisdiction_typed_geography_is_unique_when_non_null(
    db_conn: psycopg.Connection,
    jurisdiction_type: str,
    field_name: str,
    value: str,
) -> None:
    _insert_jurisdiction(
        db_conn,
        name=f"First {field_name}",
        jurisdiction_type=jurisdiction_type,
        fips=value,
        **{field_name: value},
    )

    with pytest.raises(psycopg.errors.UniqueViolation):
        _insert_jurisdiction(
            db_conn,
            name=f"Duplicate {field_name}",
            jurisdiction_type=jurisdiction_type,
            fips=f"9{value}",
            **{field_name: value},
        )


def test_jurisdiction_allows_federal_without_fips(db_conn: psycopg.Connection) -> None:
    federal_id = _insert_jurisdiction(
        db_conn,
        name="United States",
        jurisdiction_type="federal",
    )

    assert isinstance(federal_id, UUID)


def test_jurisdiction_rejects_invalid_type(db_conn: psycopg.Connection) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        _insert_jurisdiction(
            db_conn,
            name="Invalid Jurisdiction",
            jurisdiction_type="invalid_kind",
            fips="99999",
        )


def test_jurisdiction_rejects_non_federal_rows_without_fips(db_conn: psycopg.Connection) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        _insert_jurisdiction(
            db_conn,
            name="North Carolina",
            jurisdiction_type="state",
            fips=None,
            state="NC",
        )


def test_jurisdiction_rejects_electoral_division_type_labels(db_conn: psycopg.Connection) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        _insert_jurisdiction(
            db_conn,
            name="North Carolina District 1",
            jurisdiction_type="congressional_district",
            fips="37001",
            state="NC",
        )


def test_jurisdiction_update_changes_updated_at(db_conn: psycopg.Connection) -> None:
    inserted_id = _insert_jurisdiction_with_timestamps(
        db_conn,
        name="North Carolina",
        jurisdiction_type="state",
        fips="37",
        created_at=datetime(2000, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2000, 1, 1, tzinfo=timezone.utc),
    )

    original_updated_at = db_conn.execute(
        "SELECT updated_at FROM core.jurisdiction WHERE id = %s",
        (inserted_id,),
    ).fetchone()[0]

    changed_updated_at = db_conn.execute(
        """
        UPDATE core.jurisdiction
        SET name = %s
        WHERE id = %s
        RETURNING updated_at
        """,
        ("North Carolina Updated", inserted_id),
    ).fetchone()[0]

    assert changed_updated_at > original_updated_at
