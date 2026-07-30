from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from domains.campaign_finance.ingest import filing_loader_bulk

pytestmark = pytest.mark.unit


class _RecordingCursor:
    def __init__(
        self,
        parameter_counts: list[int],
        fetchall_results: list[list[tuple[object, ...]]],
    ) -> None:
        self._parameter_counts = parameter_counts
        self._fetchall_results = fetchall_results
        self._fetchall_result: list[tuple[object, ...]] = []

    def __enter__(self) -> _RecordingCursor:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def execute(self, statement: str, params: list[object]) -> None:
        del statement
        self._parameter_counts.append(len(params))
        if len(params) > 65_535:
            raise RuntimeError("PostgreSQL parameter limit exceeded")
        if self._fetchall_results:
            self._fetchall_result = self._fetchall_results.pop(0)

    def fetchall(self) -> list[tuple[object, ...]]:
        return self._fetchall_result

    def fetchone(self) -> None:
        return None


class _RecordingConnection:
    def __init__(
        self,
        *,
        fetchall_results: list[list[tuple[object, ...]]] | None = None,
    ) -> None:
        self.parameter_counts: list[int] = []
        self._fetchall_results = list(fetchall_results or [])

    def cursor(self) -> _RecordingCursor:
        return _RecordingCursor(self.parameter_counts, self._fetchall_results)


def _filing(index: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        filing_fec_id=f"FILING-{index}",
        committee_id=uuid4(),
        candidate_id=None,
        election_id=None,
        report_type=None,
        amendment_indicator="N",
        filing_name=None,
        coverage_start_date=None,
        coverage_end_date=None,
        due_date=None,
        receipt_date=None,
        accepted_date=None,
        amended_from_filing_id=None,
        source_record_id=None,
    )


def test_upsert_filings_bulk_splits_large_batches_below_parameter_limit() -> None:
    first_filing_id = uuid4()
    last_filing_id = uuid4()
    connection = _RecordingConnection(
        fetchall_results=[
            [(first_filing_id, "FILING-0")],
            [(last_filing_id, "FILING-4369")],
        ],
    )

    filing_ids = filing_loader_bulk.upsert_filings_bulk(
        connection,
        [_filing(index) for index in range(4_370)],
    )

    assert connection.parameter_counts == [65_535, 15]
    assert filing_ids == {
        "FILING-0": first_filing_id,
        "FILING-4369": last_filing_id,
    }


def test_transaction_bulk_upsert_splits_large_batches_below_parameter_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_transaction_id = uuid4()
    last_transaction_id = uuid4()
    filing_id = uuid4()
    expected_results = [
        (first_transaction_id, True, 1, filing_id, "TRANSACTION-1"),
        (last_transaction_id, False, 2, filing_id, "TRANSACTION-2"),
    ]
    connection = _RecordingConnection(
        fetchall_results=[
            [expected_results[0]],
            [expected_results[1]],
        ],
    )
    transactions = [SimpleNamespace(id=uuid4()) for _index in range(2_115)]
    monkeypatch.setattr(filing_loader_bulk, "_transaction_values", lambda transaction: (None,) * 30)

    results = filing_loader_bulk._bulk_upsert_transactions_for_conflict_target(
        connection,
        transactions=transactions,
        conflict_mode="sub_id",
    )

    assert connection.parameter_counts == [65_534, 31]
    assert results == expected_results
