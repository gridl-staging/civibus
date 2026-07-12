from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from domains.civics import ingest
from domains.civics.types.models import Office


pytestmark = pytest.mark.unit


def test_upsert_office_legacy_schema_omits_electoral_division_column(monkeypatch: pytest.MonkeyPatch) -> None:
    row_id = uuid4()
    cursor = MagicMock()
    cursor.fetchone.side_effect = [
        (False,),  # schema probe: electoral_division_id column missing on civic.office
        (row_id,),  # insert/upsert RETURNING id
    ]
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor

    monkeypatch.setattr(ingest, "_OFFICE_HAS_ELECTORAL_DIVISION_COLUMN", None)

    office = Office(
        name="nc_general_assembly_house",
        office_level="state",
        state="NC",
        title="Representative",
        electoral_division_id=uuid4(),
    )
    inserted_id = ingest.upsert_office(conn, office)

    assert inserted_id == row_id
    assert len(cursor.execute.call_args_list) == 2

    schema_probe_sql = cursor.execute.call_args_list[0].args[0]
    fallback_insert_sql = cursor.execute.call_args_list[1].args[0]
    fallback_insert_params = cursor.execute.call_args_list[1].args[1]

    assert "information_schema.columns" in schema_probe_sql
    assert "electoral_division_id" not in fallback_insert_sql
    assert office.electoral_division_id not in fallback_insert_params
