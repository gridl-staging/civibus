
from __future__ import annotations

from pathlib import Path

import psycopg


FIXTURE_DIR = Path(__file__).resolve().parents[4] / "tests" / "fixtures" / "roster"


def read_fixture(name: str) -> str:
    candidate = (FIXTURE_DIR / Path(name)).resolve()
    fixture_root = FIXTURE_DIR.resolve()
    if candidate != fixture_root and fixture_root not in candidate.parents:
        raise ValueError(f"Fixture path must stay within {fixture_root}")
    return candidate.read_text(encoding="utf-8")


def fixture_path(name: str) -> Path:
    return FIXTURE_DIR / name


def seed_persons(connection: psycopg.Connection, canonical_names: tuple[str, ...]) -> None:
    rows = [
        (
            full_name,
            full_name.split()[0],
            full_name.split()[-1],
        )
        for full_name in canonical_names
    ]
    with connection.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO core.person (id, canonical_name, first_name, last_name, identifiers)
            VALUES
                (gen_random_uuid(), %s, %s, %s, '{}'::jsonb)
            ON CONFLICT DO NOTHING
            """,
            rows,
        )
