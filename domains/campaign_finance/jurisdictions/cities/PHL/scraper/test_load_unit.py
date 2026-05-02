"""Fast unit tests for PHL pass-1 loader behavior."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import psycopg

from domains.campaign_finance.jurisdictions.cities.PHL.scraper.load import (
    load_phl_source_records,
)


def _fake_source_row(transaction_id: str) -> dict[str, object]:
    return {
        "transaction_id": transaction_id,
        "transaction_amount": 100,
        "transaction_date": "2026-04-01",
        "filer_name": "Sample Filer",
        "donor_name": "Sample Donor",
    }


def test_load_phl_source_records_streams_inserts_before_input_exhaustion(
    monkeypatch,
) -> None:
    """Regression: pass-1 must stream rows into DB instead of buffering all rows.

    If the loader fully materializes a large JSONL payload first, high-volume
    runs (PHL contributions) can exceed host memory before pass-1 writes begin.
    This test pins streaming behavior by asserting that at least one insert
    happens before the input iterator is exhausted.
    """
    events: list[str] = []
    source_rows = [
        _fake_source_row("TXN-1"),
        _fake_source_row("TXN-2"),
        _fake_source_row("TXN-3"),
    ]

    def fake_iter_jsonl_rows(_path: Path):
        for row in source_rows:
            events.append(f"yield:{row['transaction_id']}")
            yield row
        events.append("rows_exhausted")

    def fake_parse_rows(raw_rows, *, is_expenditure: bool):
        assert is_expenditure is False
        for raw in raw_rows:
            yield SimpleNamespace(transaction_id=str(raw["transaction_id"]))

    def fake_try_insert_source_record(_conn, _source_record):
        events.append("insert")
        return uuid4()

    conn = MagicMock()
    conn.info.transaction_status = psycopg.pq.TransactionStatus.IDLE
    conn.transaction.return_value.__enter__.return_value = None
    conn.transaction.return_value.__exit__.return_value = False

    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.cities.PHL.scraper.load._iter_jsonl_rows",
        fake_iter_jsonl_rows,
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.cities.PHL.scraper.load.parse_phl_carto_rows",
        fake_parse_rows,
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.cities.PHL.scraper.load.ensure_phl_contributions_data_source",
        lambda _conn: UUID("11111111-1111-1111-1111-111111111111"),
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.cities.PHL.scraper.load.try_insert_source_record",
        fake_try_insert_source_record,
    )

    result = load_phl_source_records(
        conn,
        Path("/tmp/ignored.jsonl"),
        is_expenditure=False,
    )

    first_insert_index = events.index("insert")
    rows_exhausted_index = events.index("rows_exhausted")
    assert first_insert_index < rows_exhausted_index, (
        "pass-1 inserts must start before the input stream is fully exhausted"
    )
    assert result.inserted == 3
    assert result.skipped == 0
    assert result.errors == 0
