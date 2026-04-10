from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

from test_support.schedule_e import (
    SeededCommittee,
    extract_schedule_e_committees,
    seed_schedule_e_committee,
)


def test_extract_schedule_e_committees_uses_fixture_rows_and_limit() -> None:
    fixture_path = Path(__file__).resolve().parent / "fixtures" / "bulk" / "schedule_e_sample.csv"

    assert extract_schedule_e_committees(fixture_path, limit=5) == [
        ("C00866517", "Go America PAC"),
        ("C00877886", "1000 Women Strong PAC"),
        ("C90022559", "1199 SEIU New York State Political Action Fund"),
    ]


def test_seed_schedule_e_committee_serializes_identifiers_json_safely() -> None:
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = None
    committee_fec_id = 'C00"12345'

    seed_schedule_e_committee(conn, committee_fec_id, "Quoted Committee")

    organization_insert_params = next(
        call.args[1] for call in cursor.execute.call_args_list if "INSERT INTO core.organization" in call.args[0]
    )
    identifiers_json = organization_insert_params[2]
    assert identifiers_json == json.dumps({"fec_committee_id": committee_fec_id})
    assert json.loads(identifiers_json)["fec_committee_id"] == committee_fec_id


def test_seed_schedule_e_committee_reuses_existing_committee_without_inserting() -> None:
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    committee_id = uuid4()
    organization_id = uuid4()
    cursor.fetchone.return_value = (committee_id, organization_id)

    seeded = seed_schedule_e_committee(conn, "C00866517", "Go America PAC")

    assert seeded == SeededCommittee(
        id=committee_id,
        fec_committee_id="C00866517",
        organization_id=organization_id,
    )
    assert cursor.execute.call_count == 1
    select_statement, select_params = cursor.execute.call_args_list[0].args
    assert "SELECT id, organization_id FROM cf.committee" in select_statement
    assert select_params == ("C00866517",)
    conn.commit.assert_not_called()
