from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import psycopg

from domains.campaign_finance.jurisdictions.states.IL.scraper import load
from domains.campaign_finance.jurisdictions.states.IL.scraper.load import LoadResult


class _FakeTransactionContext:
    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class _FakeConnection:
    def __init__(self) -> None:
        self.info = SimpleNamespace(transaction_status=psycopg.pq.TransactionStatus.IDLE)
        self.commit = MagicMock()
        self.rollback = MagicMock()

    def transaction(self) -> _FakeTransactionContext:
        return _FakeTransactionContext()


def test_parse_il_bool_accepts_true_false_strings() -> None:
    assert load._parse_il_bool("True") is True
    assert load._parse_il_bool("False") is False
    assert load._parse_il_bool(None) is None


def test_il_transaction_type_uses_d2_part_codes() -> None:
    assert load._il_transaction_type({"D2Part": "1A"}, data_type="contributions") == "contribution"
    assert load._il_transaction_type({"D2Part": "2A"}, data_type="contributions") == "transfer_in"
    assert load._il_transaction_type({"D2Part": "9"}, data_type="expenditures") == "independent_expenditure"


def test_load_il_contributions_skips_archived_rows_and_counts_inserted(
    monkeypatch,
) -> None:
    connection = _FakeConnection()
    source_record_id = uuid4()

    monkeypatch.setattr(load, "ensure_il_data_source", MagicMock(return_value=uuid4()))
    monkeypatch.setattr(load, "parse_contributions", MagicMock(return_value=iter([])))
    monkeypatch.setattr(load, "ensure_transaction_open", MagicMock())
    monkeypatch.setattr(
        load,
        "_il_data_type_spec",
        MagicMock(
            return_value=SimpleNamespace(
                person_roles=("donor",),
                organization_roles=("contributor",),
                archived_path="il.archived",
                extract_row=MagicMock(return_value={"committee": MagicMock()}),
                parse_rows=MagicMock(
                    return_value=iter(
                        [
                            {"ID": "100", "D2Part": "1A", "Archived": "False"},
                            {"ID": "101", "D2Part": "2A", "Archived": "True"},
                        ]
                    )
                ),
            )
        ),
    )
    monkeypatch.setattr(load, "_build_il_source_record", MagicMock())
    monkeypatch.setattr(load, "try_insert_source_record", MagicMock(return_value=source_record_id))
    monkeypatch.setattr(load, "_load_il_entities", MagicMock(return_value=(uuid4(), None)))
    monkeypatch.setattr(load, "_upsert_il_filing", MagicMock(return_value=uuid4()))
    monkeypatch.setattr(load, "_upsert_il_transaction", MagicMock())

    result = load.load_il_contributions_with_filings(connection, "/tmp/sample.txt")

    assert isinstance(result, LoadResult)
    assert result.inserted == 1
    assert result.superseded == 1
    assert result.quarantined == 0
