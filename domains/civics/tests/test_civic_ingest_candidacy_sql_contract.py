from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from domains.civics.ingest import upsert_candidacy
from domains.civics.types.models import Candidacy


def _execute_call(candidacy: Candidacy) -> tuple[str, tuple[object, ...]]:
    cursor = MagicMock()
    cursor.fetchone.return_value = (uuid4(),)
    connection = MagicMock()
    connection.cursor.return_value.__enter__.return_value = cursor

    upsert_candidacy(connection, candidacy)

    sql, params = cursor.execute.call_args.args
    return sql, params


def test_upsert_candidacy_sql_preserves_unset_stage1_fields_on_conflict() -> None:
    sql, params = _execute_call(Candidacy(person_id=uuid4(), contest_id=uuid4(), party="DEM"))

    assert "is_unexpired_term = CASE WHEN %s THEN EXCLUDED.is_unexpired_term ELSE civic.candidacy.is_unexpired_term END" in sql
    assert "raw_fields = CASE WHEN %s THEN EXCLUDED.raw_fields ELSE civic.candidacy.raw_fields END" in sql
    assert params[13] is False
    assert params[14] is False


def test_upsert_candidacy_sql_updates_when_stage1_fields_are_explicit() -> None:
    sql, params = _execute_call(
        Candidacy(
            person_id=uuid4(),
            contest_id=uuid4(),
            is_unexpired_term=False,
            raw_fields={},
        )
    )

    assert "is_unexpired_term = CASE WHEN %s THEN EXCLUDED.is_unexpired_term ELSE civic.candidacy.is_unexpired_term END" in sql
    assert "raw_fields = CASE WHEN %s THEN EXCLUDED.raw_fields ELSE civic.candidacy.raw_fields END" in sql
    assert params[13] is True
    assert params[14] is True
