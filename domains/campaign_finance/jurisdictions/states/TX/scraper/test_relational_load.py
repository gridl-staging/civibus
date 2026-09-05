"""Contract for Texas's delegation to the shared relational loop.

Texas-owned policy only: the exact arguments Texas supplies to
`load_utils.load_relational_rows_without_savepoints`, the behavior of each
callback and hook it passes, `limit` application, result mapping, its filing
cache policy, and its typed exception identities. Batch/terminal commit
cadence, batch accounting, lost-success arithmetic, fatal-type passthrough,
and the caller-owned raise are owned by
`domains/campaign_finance/jurisdictions/states/test_load_utils.py` and must not
be restated here.
"""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import psycopg
import pytest

from domains.campaign_finance.jurisdictions.states.TX.scraper import load as tx_load_module
from domains.campaign_finance.jurisdictions.states.TX.scraper.load import _tx_source_record_key
from domains.campaign_finance.jurisdictions.states.TX.scraper.load_test_support import (
    parsed_contributions,
    parsed_expenditures,
    parsed_loans,
)


def _capture_tx_relational_delegation(
    monkeypatch: pytest.MonkeyPatch,
    *,
    conn: MagicMock,
    rows: list[dict[str, str | None]],
    data_source_id: object,
    data_type: str = "contributions",
    limit: int | None = None,
    result: object | None = None,
) -> tuple[object, MagicMock, object, list[dict[str, str | None]]]:
    if result is None:
        result = SimpleNamespace(inserted=11, skipped=13, errors=17)
    materialized_rows: list[dict[str, str | None]] = []

    def _shared_loop(_conn: object, delegated_rows: object, **_kwargs: object) -> object:
        materialized_rows.extend(list(delegated_rows))
        return result

    shared_loop = MagicMock(side_effect=_shared_loop)
    monkeypatch.setattr(tx_load_module, "load_relational_rows_without_savepoints", shared_loop)

    counts = tx_load_module._load_tx_relational_transactions(
        conn,
        rows,
        data_source_id=data_source_id,
        data_type=data_type,
        limit=limit,
    )
    return counts, shared_loop, result, materialized_rows


def test_load_tx_relational_transactions_delegates_once_with_tx_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = MagicMock()
    _, shared_loop, _, materialized_rows = _capture_tx_relational_delegation(
        monkeypatch,
        conn=conn,
        rows=[{"row": "0"}],
        data_source_id=uuid4(),
    )

    assert materialized_rows == [{"row": "0"}]
    shared_loop.assert_called_once()
    args, kwargs = shared_loop.call_args
    assert len(args) == 2
    assert args[0] is conn
    assert set(kwargs) == {
        "batch_size",
        "caller_owned_rollback_error",
        "fatal_exceptions",
        "label",
        "link_row",
        "on_db_error_recovery",
        "on_managed_commit_reset",
        "resolve_source_record_id",
        "source_record_key_for_row",
    }
    assert kwargs["batch_size"] == 1_000
    assert kwargs["fatal_exceptions"] == (tx_load_module.TXFilingLookupDrift,)
    for callback_name in (
        "source_record_key_for_row",
        "resolve_source_record_id",
        "link_row",
        "on_db_error_recovery",
        "caller_owned_rollback_error",
    ):
        assert callable(kwargs[callback_name])

    # The shared loop calls this factory with a `failed_row=` keyword
    # (`states/test_load_utils.py::test_shared_relational_loop_raises_caller_owned_rollback_error_without_managed_commits`),
    # so Texas's factory must accept that exact call shape and mint a fresh
    # exception per call rather than handing back a shared singleton.
    first_rollback_error = kwargs["caller_owned_rollback_error"](failed_row={"row": "0"})
    second_rollback_error = kwargs["caller_owned_rollback_error"](failed_row={"row": "0"})
    assert isinstance(first_rollback_error, tx_load_module.TXCallerTransactionRolledBack)
    assert isinstance(second_rollback_error, tx_load_module.TXCallerTransactionRolledBack)
    assert first_rollback_error is not second_rollback_error
    assert "caller-owned" in str(first_rollback_error)
    assert "rolled back" in str(first_rollback_error)


@pytest.mark.parametrize(
    ("data_type", "expected_label"),
    [
        ("contributions", "TX contribution filing link"),
        ("expenditures", "TX expenditure filing link"),
        ("loans", "TX loan filing link"),
    ],
)
def test_load_tx_relational_transactions_formats_shared_loop_label(
    monkeypatch: pytest.MonkeyPatch,
    data_type: str,
    expected_label: str,
) -> None:
    _, shared_loop, _, _ = _capture_tx_relational_delegation(
        monkeypatch,
        conn=MagicMock(),
        rows=[{"row": "0"}],
        data_source_id=uuid4(),
        data_type=data_type,
    )

    assert shared_loop.call_args.kwargs["label"] == expected_label


@pytest.mark.parametrize(
    ("data_type", "row_factory"),
    [
        ("contributions", parsed_contributions),
        ("expenditures", parsed_expenditures),
        ("loans", parsed_loans),
    ],
)
@pytest.mark.parametrize("transaction_linked", [True, False])
def test_load_tx_relational_transactions_callbacks_preserve_tx_context(
    monkeypatch: pytest.MonkeyPatch,
    data_type: str,
    row_factory: Callable[[], list[dict[str, str | None]]],
    transaction_linked: bool,
) -> None:
    conn = MagicMock()
    data_source_id = uuid4()
    source_record_id = uuid4()
    row = row_factory()[0]
    expected_source_record_key = _tx_source_record_key(row, data_type=data_type)
    filing_entry = tx_load_module._TXFilingLookupEntry(uuid4(), uuid4(), uuid4())
    tx_source_record_key = MagicMock(return_value=expected_source_record_key)
    select_source_record_id = MagicMock(return_value=source_record_id)
    upsert_filing = MagicMock(return_value=filing_entry)
    upsert_transaction = MagicMock(return_value=transaction_linked)
    monkeypatch.setattr(tx_load_module, "_tx_source_record_key", tx_source_record_key)
    monkeypatch.setattr(tx_load_module, "_select_tx_source_record_id", select_source_record_id)
    monkeypatch.setattr(tx_load_module, "_upsert_tx_filing", upsert_filing)
    monkeypatch.setattr(tx_load_module, "_upsert_tx_transaction_with_filing", upsert_transaction)

    _, shared_loop, _, _ = _capture_tx_relational_delegation(
        monkeypatch,
        conn=conn,
        rows=[row],
        data_source_id=data_source_id,
        data_type=data_type,
    )
    callbacks = shared_loop.call_args.kwargs

    source_record_key = callbacks["source_record_key_for_row"](row)
    assert source_record_key == expected_source_record_key
    tx_source_record_key.assert_called_once_with(row, data_type=data_type)
    assert callbacks["resolve_source_record_id"](conn, source_record_key) == source_record_id
    select_source_record_id.assert_called_once_with(
        conn,
        data_source_id=data_source_id,
        source_record_key=source_record_key,
    )

    assert callbacks["link_row"](conn, row, source_record_id) is transaction_linked
    upsert_filing.assert_called_once()
    filing_args, filing_kwargs = upsert_filing.call_args
    assert filing_args == (conn, row)
    assert filing_kwargs["source_record_id"] == source_record_id
    assert filing_kwargs["data_type"] == data_type
    assert filing_kwargs["filing_lookup"] == {}
    upsert_transaction.assert_called_once_with(
        conn,
        row,
        filing_id=filing_entry.filing_id,
        committee_id=filing_entry.committee_id,
        source_record_id=source_record_id,
        data_type=data_type,
    )


def test_load_tx_relational_transactions_limits_rows_before_delegating(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = MagicMock()
    data_source_id = uuid4()
    rows = [{"row": "0"}, {"row": "1"}, {"row": "2"}]

    _, _, _, limited_rows = _capture_tx_relational_delegation(
        monkeypatch,
        conn=conn,
        rows=rows,
        data_source_id=data_source_id,
        limit=1,
    )
    assert limited_rows == rows[:1]

    _, _, _, unlimited_rows = _capture_tx_relational_delegation(
        monkeypatch,
        conn=conn,
        rows=rows,
        data_source_id=data_source_id,
        limit=None,
    )
    assert unlimited_rows == rows

    invalid_limit_loop = MagicMock()
    monkeypatch.setattr(tx_load_module, "load_relational_rows_without_savepoints", invalid_limit_loop)
    with pytest.raises(ValueError, match="greater than or equal to 0"):
        tx_load_module._load_tx_relational_transactions(
            conn,
            rows,
            data_source_id=data_source_id,
            data_type="contributions",
            limit=-1,
        )
    invalid_limit_loop.assert_not_called()


def test_load_tx_relational_transactions_returns_shared_loop_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared_result = SimpleNamespace(inserted=11, skipped=13, errors=17)

    counts, _, _, _ = _capture_tx_relational_delegation(
        monkeypatch,
        conn=MagicMock(),
        rows=[{"row": "0"}],
        data_source_id=uuid4(),
        result=shared_result,
    )

    assert isinstance(counts, tx_load_module._TXRelationalLoadCounts)
    assert counts is not shared_result
    assert (counts.inserted, counts.skipped, counts.errors) == (11, 13, 17)


def test_load_tx_relational_transactions_does_not_drive_transaction_mechanics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = MagicMock()
    conn.info.transaction_status = psycopg.pq.TransactionStatus.IDLE
    try_row_without_savepoint = MagicMock()
    commit_managed_transaction = MagicMock()
    monkeypatch.setattr(tx_load_module, "try_row_without_savepoint", try_row_without_savepoint)
    monkeypatch.setattr(tx_load_module, "commit_managed_transaction", commit_managed_transaction)

    _capture_tx_relational_delegation(
        monkeypatch,
        conn=conn,
        rows=[{"row": "0"}],
        data_source_id=uuid4(),
    )

    try_row_without_savepoint.assert_not_called()
    commit_managed_transaction.assert_not_called()
    conn.commit.assert_not_called()
    conn.rollback.assert_not_called()
    conn.transaction.assert_not_called()


def test_upsert_tx_filing_raises_typed_lookup_drift_and_refreshes_agreeing_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = MagicMock()
    row = {"row": "0"}
    filing_fec_id = "TX-CANDIDATE-FILING"
    cached_entry = tx_load_module._TXFilingLookupEntry(uuid4(), uuid4(), uuid4())
    returned_filing_id = uuid4()
    filing_lookup = {filing_fec_id: cached_entry}
    monkeypatch.setattr(tx_load_module, "_tx_filing_fec_id", lambda *_args, **_kwargs: filing_fec_id)
    monkeypatch.setattr(tx_load_module, "_build_tx_filing", MagicMock(return_value=object()))
    monkeypatch.setattr(tx_load_module, "upsert_filing", MagicMock(return_value=returned_filing_id))

    assert issubclass(tx_load_module.TXFilingLookupDrift, ValueError)
    with pytest.raises(tx_load_module.TXFilingLookupDrift) as raised:
        tx_load_module._upsert_tx_filing(
            conn,
            row,
            source_record_id=uuid4(),
            data_type="contributions",
            filing_lookup=filing_lookup,
        )

    assert type(raised.value) is tx_load_module.TXFilingLookupDrift
    assert str(cached_entry.filing_id) in str(raised.value)
    assert str(returned_filing_id) in str(raised.value)
    assert filing_lookup[filing_fec_id] is cached_entry

    monkeypatch.setattr(tx_load_module, "upsert_filing", MagicMock(return_value=cached_entry.filing_id))
    agreeing_entry = tx_load_module._upsert_tx_filing(
        conn,
        row,
        source_record_id=uuid4(),
        data_type="contributions",
        filing_lookup=filing_lookup,
    )

    assert agreeing_entry == cached_entry
    assert agreeing_entry is filing_lookup[filing_fec_id]


def test_restore_tx_filing_lookup_entry_after_ordinary_non_db_error() -> None:
    prior_entry = tx_load_module._TXFilingLookupEntry(uuid4(), uuid4(), uuid4())
    unrelated_entry = tx_load_module._TXFilingLookupEntry(uuid4(), uuid4(), uuid4())
    attempted_entry = tx_load_module._TXFilingLookupEntry(uuid4(), uuid4(), uuid4())
    filing_lookup = {"attempted": prior_entry, "unrelated": unrelated_entry}

    cached_entry = filing_lookup.get("attempted")
    filing_lookup["attempted"] = attempted_entry
    tx_load_module._restore_tx_filing_lookup_entry(
        filing_lookup,
        filing_fec_id="attempted",
        cached_entry=cached_entry,
    )

    assert filing_lookup["attempted"] is prior_entry
    assert filing_lookup["unrelated"] is unrelated_entry

    filing_lookup = {"attempted": attempted_entry, "unrelated": unrelated_entry}
    tx_load_module._restore_tx_filing_lookup_entry(
        filing_lookup,
        filing_fec_id="attempted",
        cached_entry=None,
    )
    assert filing_lookup == {"unrelated": unrelated_entry}


def _two_tx_relational_rows() -> list[dict[str, str | None]]:
    return [dict(row) for row in parsed_contributions()[:2]]


def test_load_tx_relational_transactions_reraises_filing_lookup_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = MagicMock()
    conn.info.transaction_status = psycopg.pq.TransactionStatus.IDLE
    drift = tx_load_module.TXFilingLookupDrift("TX filing lookup drift")
    upsert_filing = MagicMock(side_effect=drift)
    upsert_transaction = MagicMock()
    monkeypatch.setattr(tx_load_module, "_select_tx_source_record_id", MagicMock(return_value=uuid4()))
    monkeypatch.setattr(tx_load_module, "_upsert_tx_filing", upsert_filing)
    monkeypatch.setattr(tx_load_module, "_upsert_tx_transaction_with_filing", upsert_transaction)

    with pytest.raises(tx_load_module.TXFilingLookupDrift) as raised:
        tx_load_module._load_tx_relational_transactions(
            conn,
            _two_tx_relational_rows(),
            data_source_id=uuid4(),
            data_type="contributions",
            limit=None,
        )

    assert raised.value is drift
    assert upsert_filing.call_count == 1
    upsert_transaction.assert_not_called()
    conn.transaction.assert_not_called()


def test_load_tx_relational_transactions_raises_after_caller_owned_db_rollback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = MagicMock()
    conn.info.transaction_status = psycopg.pq.TransactionStatus.INTRANS
    filing_entry = tx_load_module._TXFilingLookupEntry(uuid4(), uuid4(), uuid4())
    upsert_transaction = MagicMock(side_effect=psycopg.errors.UniqueViolation("duplicate transaction"))
    monkeypatch.setattr(tx_load_module, "_select_tx_source_record_id", MagicMock(return_value=uuid4()))
    monkeypatch.setattr(tx_load_module, "_upsert_tx_filing", MagicMock(return_value=filing_entry))
    monkeypatch.setattr(tx_load_module, "_upsert_tx_transaction_with_filing", upsert_transaction)

    with pytest.raises(tx_load_module.TXCallerTransactionRolledBack):
        tx_load_module._load_tx_relational_transactions(
            conn,
            _two_tx_relational_rows(),
            data_source_id=uuid4(),
            data_type="contributions",
            limit=None,
        )

    assert upsert_transaction.call_count == 1
    conn.commit.assert_not_called()
    conn.transaction.assert_not_called()


def _capture_tx_filing_cache_hooks(
    monkeypatch: pytest.MonkeyPatch,
    *,
    conn: MagicMock,
    row: dict[str, str | None],
    entries: dict[str, object],
    filing_fec_id: str,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    """Capture the seam callbacks together with the live filing cache they close over.

    `_upsert_tx_filing` is stubbed to seed `entries` into whichever cache dict Texas
    hands it and to record that dict, so a specimen can drive the captured `link_row`
    once and then inspect exactly the cache the hooks operate on. `_tx_filing_fec_id`
    is pinned to `filing_fec_id` so these cache-policy specimens do not depend on the
    row's field shape. Callers may re-monkeypatch `_upsert_tx_filing` /
    `_upsert_tx_transaction_with_filing` after capture to change what a later
    `link_row` call does.
    """
    monkeypatch.setattr(tx_load_module, "_tx_filing_fec_id", lambda *_args, **_kwargs: filing_fec_id)
    cache_refs: list[dict[str, object]] = []

    def _seed_filing_cache(*_args: object, filing_lookup: dict[str, object], **_kwargs: object) -> object:
        filing_lookup.update(entries)
        cache_refs.append(filing_lookup)
        return next(iter(entries.values()))

    monkeypatch.setattr(tx_load_module, "_upsert_tx_filing", _seed_filing_cache)
    monkeypatch.setattr(tx_load_module, "_upsert_tx_transaction_with_filing", MagicMock(return_value=True))
    _, shared_loop, _, _ = _capture_tx_relational_delegation(
        monkeypatch,
        conn=conn,
        rows=[row],
        data_source_id=uuid4(),
    )
    return shared_loop.call_args.kwargs, cache_refs


def test_load_tx_relational_transactions_clears_whole_filing_cache_after_db_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = MagicMock()
    row = {"row": "0"}
    entries = {
        "filing-a": tx_load_module._TXFilingLookupEntry(uuid4(), uuid4(), uuid4()),
        "filing-b": tx_load_module._TXFilingLookupEntry(uuid4(), uuid4(), uuid4()),
    }

    callbacks, cache_refs = _capture_tx_filing_cache_hooks(
        monkeypatch,
        conn=conn,
        row=row,
        entries=entries,
        filing_fec_id="filing-a",
    )

    callbacks["link_row"](conn, row, uuid4())
    assert cache_refs[0] == entries
    callbacks["on_db_error_recovery"](conn, failed_row=row)
    assert cache_refs[0] == {}


def test_load_tx_relational_transactions_keeps_filing_cache_after_managed_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = MagicMock()
    row = {"row": "0"}
    entry = tx_load_module._TXFilingLookupEntry(uuid4(), uuid4(), uuid4())

    callbacks, cache_refs = _capture_tx_filing_cache_hooks(
        monkeypatch,
        conn=conn,
        row=row,
        entries={"filing-a": entry},
        filing_fec_id="filing-a",
    )

    callbacks["link_row"](conn, row, uuid4())
    assert cache_refs[0] == {"filing-a": entry}
    managed_commit_reset = callbacks["on_managed_commit_reset"]
    if managed_commit_reset is not None:
        managed_commit_reset(processed_count=1_000, reason="batch_boundary")
    assert cache_refs[0] == {"filing-a": entry}


@pytest.mark.parametrize("attempted_was_cached", [True, False])
def test_load_tx_relational_transactions_restores_attempted_filing_after_ordinary_row_error(
    monkeypatch: pytest.MonkeyPatch,
    attempted_was_cached: bool,
) -> None:
    """An ordinary non-database row error restores only the attempted filing key.

    The shared loop exposes no ordinary-error hook, so once Texas delegates this rule
    can only live inside its own `link_row`. Clearing the whole cache here would apply
    the database-rollback rule to a row that rolled nothing back; leaving the attempted
    entry in place would let a later row reuse a filing that was never written.
    """
    conn = MagicMock()
    row = {"row": "0"}
    prior_entry = tx_load_module._TXFilingLookupEntry(uuid4(), uuid4(), uuid4())
    unrelated_entry = tx_load_module._TXFilingLookupEntry(uuid4(), uuid4(), uuid4())
    attempted_entry = tx_load_module._TXFilingLookupEntry(uuid4(), uuid4(), uuid4())

    seeded: dict[str, object] = {"unrelated": unrelated_entry}
    if attempted_was_cached:
        seeded["attempted"] = prior_entry

    callbacks, cache_refs = _capture_tx_filing_cache_hooks(
        monkeypatch,
        conn=conn,
        row=row,
        entries=seeded,
        filing_fec_id="attempted",
    )
    callbacks["link_row"](conn, row, uuid4())
    assert cache_refs[0] == seeded

    def _overwrite_attempted_filing(*_args: object, filing_lookup: dict[str, object], **_kwargs: object) -> object:
        filing_lookup["attempted"] = attempted_entry
        return attempted_entry

    ordinary_error = ValueError("ordinary row validation failed")
    monkeypatch.setattr(tx_load_module, "_upsert_tx_filing", _overwrite_attempted_filing)
    monkeypatch.setattr(
        tx_load_module,
        "_upsert_tx_transaction_with_filing",
        MagicMock(side_effect=ordinary_error),
    )

    with pytest.raises(ValueError) as raised:
        callbacks["link_row"](conn, row, uuid4())

    assert raised.value is ordinary_error
    assert cache_refs[0] == seeded
    assert cache_refs[0]["unrelated"] is unrelated_entry
    if attempted_was_cached:
        assert cache_refs[0]["attempted"] is prior_entry
    else:
        assert "attempted" not in cache_refs[0]
