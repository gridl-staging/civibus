from __future__ import annotations

from dataclasses import replace
from datetime import date
from uuid import uuid4

import psycopg
import pytest

from core.types.python.models import Organization
from domains.campaign_finance.jurisdictions.states.WA.scraper import load as wa_load
from domains.campaign_finance.jurisdictions.states.WA.scraper.ie_record_classes import (
    _WA_IE_RECORD_CLASSES,
    _resolve_wa_ie_record_class,
    _transaction_amount_field,
    _transaction_date_from_row,
    _transaction_type_from_row,
    _wa_support_oppose,
)
from domains.campaign_finance.jurisdictions.states.WA.scraper.load import (
    _WAFilingLookupEntry,
    _load_wa_relational_transactions,
)


_C62_ORIGIN = "C6.2 - Itemized Expenditures"
_C63_ORIGIN = "C6.3 - Identified Entities"
_C65_ORIGIN = "C6.5 - Funding Sources"


def _row(**overrides: str | None) -> dict[str, str | None]:
    row = {
        "origin": _C62_ORIGIN,
        "report_type": "Independent Expenditure",
        "expenditure_amount": "500.00",
        "date_expense_obligated": "2025-04-15T00:00:00.000",
        "portion_of_amount": "250.00",
        "report_date": "2025-04-16T00:00:00.000",
        "amount": "100.00",
        "date_received": "2025-04-17T00:00:00.000",
        "for_or_against": "For",
    }
    row.update(overrides)
    return row


@pytest.mark.parametrize(
    ("origin", "expected_key"),
    [
        (_C62_ORIGIN, "C6.2"),
        (_C63_ORIGIN, "C6.3"),
        (_C65_ORIGIN, "C6.5"),
        ("  c6.3 - identified entities  ", "C6.3"),
    ],
)
def test_resolves_ie_record_class_from_origin_prefix(origin: str, expected_key: str) -> None:
    record_class = _resolve_wa_ie_record_class(_row(origin=origin), "independent_expenditures")

    assert record_class is _WA_IE_RECORD_CLASSES[expected_key]


@pytest.mark.parametrize("origin", [None, "", "   ", "IE", "C6.9 - Unknown"])
def test_ie_record_class_requires_known_non_empty_origin(origin: str | None) -> None:
    with pytest.raises(ValueError, match="WA independent expenditure origin"):
        _resolve_wa_ie_record_class(_row(origin=origin), "independent_expenditures")


def test_ie_record_class_is_noop_for_other_data_types() -> None:
    assert _resolve_wa_ie_record_class(_row(origin=None), "contributions") is None


@pytest.mark.parametrize(
    ("origin", "expected_field", "expected_date"),
    [
        (_C62_ORIGIN, "expenditure_amount", date(2025, 4, 15)),
        (_C63_ORIGIN, "portion_of_amount", date(2025, 4, 16)),
        (_C65_ORIGIN, "amount", date(2025, 4, 17)),
    ],
)
def test_ie_record_class_selects_amount_and_date_semantics(
    origin: str,
    expected_field: str,
    expected_date: date,
) -> None:
    record_class = _resolve_wa_ie_record_class(_row(origin=origin), "independent_expenditures")

    assert _transaction_amount_field("independent_expenditures", record_class=record_class) == expected_field
    assert (
        _transaction_date_from_row(_row(origin=origin), "independent_expenditures", record_class=record_class)
        == expected_date
    )


def test_non_ie_amount_and_date_semantics_stay_on_existing_transaction_paths() -> None:
    row = {"amount": "42.00", "receipt_date": "2025-06-01T00:00:00.000"}

    assert _transaction_amount_field("contributions", record_class=None) == "amount"
    assert _transaction_date_from_row(row, "contributions", record_class=None) == date(2025, 6, 1)


def test_c63_enables_support_oppose_and_exact_transaction_type_label() -> None:
    record_class = _resolve_wa_ie_record_class(
        _row(origin=_C63_ORIGIN, for_or_against="Against"), "independent_expenditures"
    )

    assert (
        _wa_support_oppose(
            _row(origin=_C63_ORIGIN, for_or_against="Against"),
            "independent_expenditures",
            record_class=record_class,
        )
        == "O"
    )
    assert (
        _transaction_type_from_row(_row(origin=_C63_ORIGIN), "independent_expenditures", record_class=record_class)
        == _C63_ORIGIN
    )


def test_c62_uses_existing_report_type_and_disables_support_oppose() -> None:
    record_class = _resolve_wa_ie_record_class(
        _row(origin=_C62_ORIGIN, for_or_against="For"), "independent_expenditures"
    )

    assert (
        _transaction_type_from_row(_row(origin=_C62_ORIGIN), "independent_expenditures", record_class=record_class)
        == "Independent Expenditure"
    )
    assert (
        _wa_support_oppose(
            _row(origin=_C62_ORIGIN, for_or_against="For"),
            "independent_expenditures",
            record_class=record_class,
        )
        is None
    )


def test_landed_ie_record_class_labels_are_not_pdc_sort_codes() -> None:
    labels = {
        record_class.transaction_type_label
        for record_class in _WA_IE_RECORD_CLASSES.values()
        if record_class.lands_transaction and record_class.transaction_type_label is not None
    }

    assert labels == {_C63_ORIGIN}
    assert all(not label.startswith(("1", "2")) for label in labels)


@pytest.mark.parametrize("sort_code_type", ["1000", "2001 Something"])
def test_landed_ie_report_type_rejects_pdc_sort_code_prefixes(sort_code_type: str) -> None:
    # C6.2 lands the source report_type verbatim; a value colliding with the 1/2 receipt
    # and disbursement sort-code prefixes must fail loudly instead of corrupting totals.
    record_class = _resolve_wa_ie_record_class(_row(origin=_C62_ORIGIN), "independent_expenditures")

    with pytest.raises(ValueError, match="sort-code"):
        _transaction_type_from_row(
            _row(origin=_C62_ORIGIN, report_type=sort_code_type),
            "independent_expenditures",
            record_class=record_class,
        )


def test_c65_entity_roles_and_keys_match_its_payee_extractor() -> None:
    # C6.5 does not land in this stage but its source-record entities are still linked, so
    # its roles/keys must match the payee-shaped extractor it declares (no unreachable
    # funder roles). Stage 4 owns funder-specific extraction if the accepted skip changes.
    c65 = _WA_IE_RECORD_CLASSES["C6.5"]

    assert c65.extract_fn is _WA_IE_RECORD_CLASSES["C6.2"].extract_fn
    assert c65.entity_keys == ("payee_person", "payee_org")
    assert c65.entity_roles.person == "payee"
    assert c65.entity_roles.organization == "payee"
    assert c65.counterparty_roles == (("payee",), ("payee",))


def test_only_c65_is_a_non_landing_ie_record_class() -> None:
    # Exactly one recognized IE record class does not land a transaction. Pinning the set
    # means flipping any class's lands_transaction requires a deliberate edit here.
    non_landing = {token for token, cls in _WA_IE_RECORD_CLASSES.items() if not cls.lands_transaction}

    assert non_landing == {"C6.5"}


class _FakeTxn:
    def __enter__(self) -> _FakeTxn:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


class _FakeConn:
    class _Info:
        transaction_status = psycopg.pq.TransactionStatus.INTRANS

    info = _Info()

    def transaction(self) -> _FakeTxn:
        return _FakeTxn()


def test_filing_committee_extractor_uses_record_class(monkeypatch: pytest.MonkeyPatch) -> None:
    default_record_class = _WA_IE_RECORD_CLASSES["C6.2"]

    def _extract_with_sentinel_committee(row: dict[str, str | None]) -> dict[str, object]:
        extracted = dict(default_record_class.extract_fn(row))
        extracted["committee"] = Organization(canonical_name="SENTINEL COMMITTEE")
        return extracted

    record_class = replace(default_record_class, extract_fn=_extract_with_sentinel_committee)
    captured_committee: Organization | None = None

    def _capture_committee(conn: object, committee: Organization) -> object:
        nonlocal captured_committee
        captured_committee = committee
        return uuid4()

    monkeypatch.setattr(wa_load, "_resolve_wa_committee_id", _capture_committee)
    monkeypatch.setattr(wa_load, "ensure_state_committee", lambda *args, **kwargs: uuid4())
    monkeypatch.setattr(wa_load, "upsert_filing", lambda *args, **kwargs: uuid4())

    wa_load._upsert_wa_filing(
        _FakeConn(),
        _row(sponsor_id="12345"),
        source_record_id=uuid4(),
        data_type="independent_expenditures",
        filing_lookup={},
        record_class=record_class,
    )

    assert captured_committee is not None
    assert captured_committee.canonical_name == "SENTINEL COMMITTEE"


def test_relational_pass_isolates_a_single_bad_origin_row(monkeypatch: pytest.MonkeyPatch) -> None:
    landed: list[str | None] = []

    def _fake_source_id(conn: object, *, data_source_id: object, source_record_key: str) -> object:
        return uuid4()

    def _fake_upsert_filing(conn: object, row: dict, **kwargs: object) -> _WAFilingLookupEntry:
        return _WAFilingLookupEntry(filing_id=uuid4(), committee_id=uuid4(), source_record_id=uuid4())

    def _fake_upsert_transaction(conn: object, row: dict, **kwargs: object) -> None:
        landed.append(row["origin"])

    monkeypatch.setattr(wa_load, "_select_wa_source_record_id", _fake_source_id)
    monkeypatch.setattr(wa_load, "_upsert_wa_filing", _fake_upsert_filing)
    monkeypatch.setattr(wa_load, "_upsert_wa_transaction_with_filing", _fake_upsert_transaction)
    monkeypatch.setattr(wa_load, "commit_managed_transaction", lambda conn, manages: None)

    rows = [
        _row(origin=_C62_ORIGIN),
        _row(origin="IE"),  # unknown origin: raises inside the per-row try
        _row(origin=_C65_ORIGIN),  # recognized but does not land this stage
        _row(origin=_C63_ORIGIN),
    ]

    counts = _load_wa_relational_transactions(
        _FakeConn(),
        rows,
        data_source_id=uuid4(),
        data_type="independent_expenditures",
        limit=None,
    )

    assert counts.errors == 1
    # The single C6.5 row is recognized but non-landing: counted as a skip, never an error.
    assert counts.skipped == 1
    assert landed == [_C62_ORIGIN, _C63_ORIGIN]


@pytest.mark.parametrize(
    "origin",
    [
        "C6.25 - Future Itemization",
        "C6.30 - Future Identification",
        "C6.55 - Future Funding",
        "C6.2.1 - Subclass",
        "C6.3X - Malformed",
    ],
)
def test_ie_record_class_rejects_origins_that_only_share_a_class_prefix(origin: str) -> None:
    # A future or malformed class that merely starts with a known class token must not
    # inherit that class's amount/date/type/support semantics; it is an unknown origin.
    with pytest.raises(ValueError, match="Unsupported WA independent expenditure origin"):
        _resolve_wa_ie_record_class(_row(origin=origin), "independent_expenditures")


class _FakeSourceRecordStore:
    """Minimal stand-in for the source_records table keyed by record hash."""

    def __init__(self) -> None:
        self.record_ids: dict[str, object] = {}

    def insert(self, conn: object, source_record: object) -> object | None:
        key = source_record.source_record_key
        if key in self.record_ids:
            return None
        self.record_ids[key] = uuid4()
        return self.record_ids[key]

    def select(self, conn: object, *, data_source_id: object, source_record_key: str) -> object | None:
        return self.record_ids.get(source_record_key)


def test_with_filings_counts_one_bad_origin_row_once(monkeypatch: pytest.MonkeyPatch) -> None:
    # The two-pass loader resolves the IE record class in both passes. One malformed row
    # must still fail loudly, but the public LoadResult may report it only once.
    landed: list[str | None] = []
    store = _FakeSourceRecordStore()
    rows = [
        _row(origin=_C62_ORIGIN),
        _row(origin="IE"),  # unknown origin: raises in the source-record pass
        _row(origin=_C65_ORIGIN),  # recognized but does not land a transaction this stage
        _row(origin=_C63_ORIGIN),
    ]

    def _fake_upsert_filing(conn: object, row: dict, **kwargs: object) -> _WAFilingLookupEntry:
        return _WAFilingLookupEntry(filing_id=uuid4(), committee_id=uuid4(), source_record_id=uuid4())

    monkeypatch.setitem(wa_load._WA_PARSER_FN, "independent_expenditures", lambda path: list(rows))
    monkeypatch.setattr(wa_load, "ensure_wa_data_source", lambda conn, data_type="contributions": uuid4())
    monkeypatch.setattr(wa_load, "try_insert_source_record", store.insert)
    monkeypatch.setattr(wa_load, "_load_wa_transaction_entities", lambda *args, **kwargs: None)
    monkeypatch.setattr(wa_load, "_select_wa_source_record_id", store.select)
    monkeypatch.setattr(wa_load, "_upsert_wa_filing", _fake_upsert_filing)
    monkeypatch.setattr(
        wa_load,
        "_upsert_wa_transaction_with_filing",
        lambda conn, row, **kwargs: landed.append(row["origin"]),
    )
    monkeypatch.setattr(wa_load, "commit_managed_transaction", lambda conn, manages: None)

    result = wa_load._load_wa_with_filings(_FakeConn(), "unused.csv", data_type="independent_expenditures")

    assert result.errors == 1
    assert result.inserted == 3
    assert landed == [_C62_ORIGIN, _C63_ORIGIN]


def test_with_filings_counts_bad_origin_once_even_with_preexisting_source_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A stale source record for the malformed row (persisted by a pre-router load) makes the
    # relational pass's lookup succeed, so it cannot rely on "no source record" to avoid a
    # second count. The row it rejected in the source-record pass must still be skipped here,
    # so the public LoadResult reports the bad row exactly once.
    landed: list[str | None] = []
    store = _FakeSourceRecordStore()
    bad_row = _row(origin="IE")
    # Seed a stale source record for the bad row, as an earlier all-origins-accepted load left.
    store.record_ids[wa_load._wa_source_record_key(bad_row)] = uuid4()
    rows = [
        _row(origin=_C62_ORIGIN),
        bad_row,  # unknown origin: raises in the source-record pass, but its record pre-exists
        _row(origin=_C63_ORIGIN),
    ]

    def _fake_upsert_filing(conn: object, row: dict, **kwargs: object) -> _WAFilingLookupEntry:
        return _WAFilingLookupEntry(filing_id=uuid4(), committee_id=uuid4(), source_record_id=uuid4())

    monkeypatch.setitem(wa_load._WA_PARSER_FN, "independent_expenditures", lambda path: list(rows))
    monkeypatch.setattr(wa_load, "ensure_wa_data_source", lambda conn, data_type="contributions": uuid4())
    monkeypatch.setattr(wa_load, "try_insert_source_record", store.insert)
    monkeypatch.setattr(wa_load, "_load_wa_transaction_entities", lambda *args, **kwargs: None)
    monkeypatch.setattr(wa_load, "_select_wa_source_record_id", store.select)
    monkeypatch.setattr(wa_load, "_upsert_wa_filing", _fake_upsert_filing)
    monkeypatch.setattr(
        wa_load,
        "_upsert_wa_transaction_with_filing",
        lambda conn, row, **kwargs: landed.append(row["origin"]),
    )
    monkeypatch.setattr(wa_load, "commit_managed_transaction", lambda conn, manages: None)

    result = wa_load._load_wa_with_filings(_FakeConn(), "unused.csv", data_type="independent_expenditures")

    assert result.errors == 1
    assert result.inserted == 2
    assert landed == [_C62_ORIGIN, _C63_ORIGIN]


def test_with_filings_links_duplicate_key_row_when_multiple_attempts_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A non-deterministic failure (a transient DB error, not bad content) rejects attempts
    # on a source_record_key while a byte-identical duplicate row persists that same key
    # cleanly. The rejected key must not suppress the relational pass for content that did
    # land, and failed attempts must not be reported for content that ultimately persisted.
    landed: list[str | None] = []
    store = _FakeSourceRecordStore()
    duplicate_row = _row(origin=_C62_ORIGIN)
    duplicate_key = wa_load._wa_source_record_key(duplicate_row)
    rows = [duplicate_row, dict(duplicate_row), dict(duplicate_row)]
    failed_attempts = 0

    def _insert_failing_twice(conn: object, source_record: object) -> object | None:
        nonlocal failed_attempts
        # Content-driven failure cannot reproduce this: the key is the content hash, so a
        # failure keyed on content rejects every copy. Fail only the first two attempts.
        if source_record.source_record_key == duplicate_key and failed_attempts < 2:
            failed_attempts += 1
            raise psycopg.OperationalError("transient failure before eventual success")
        return store.insert(conn, source_record)

    def _fake_upsert_filing(conn: object, row: dict, **kwargs: object) -> _WAFilingLookupEntry:
        return _WAFilingLookupEntry(filing_id=uuid4(), committee_id=uuid4(), source_record_id=uuid4())

    monkeypatch.setitem(wa_load._WA_PARSER_FN, "independent_expenditures", lambda path: list(rows))
    monkeypatch.setattr(wa_load, "ensure_wa_data_source", lambda conn, data_type="contributions": uuid4())
    monkeypatch.setattr(wa_load, "try_insert_source_record", _insert_failing_twice)
    monkeypatch.setattr(wa_load, "_load_wa_transaction_entities", lambda *args, **kwargs: None)
    monkeypatch.setattr(wa_load, "_select_wa_source_record_id", store.select)
    monkeypatch.setattr(wa_load, "_upsert_wa_filing", _fake_upsert_filing)
    monkeypatch.setattr(
        wa_load,
        "_upsert_wa_transaction_with_filing",
        lambda conn, row, **kwargs: landed.append(row["origin"]),
    )
    monkeypatch.setattr(wa_load, "commit_managed_transaction", lambda conn, manages: None)

    result = wa_load._load_wa_with_filings(_FakeConn(), "unused.csv", data_type="independent_expenditures")

    # All copies of the persisted key link; repeats are idempotent re-links, not drops.
    assert landed == [_C62_ORIGIN, _C62_ORIGIN, _C62_ORIGIN]
    assert result.inserted == 1
    assert result.errors == 0
    # The two reconciled attempts stay accounted for as dedupe skips, so every row read by
    # the source-record pass lands in exactly one bucket.
    assert result.skipped == 2
    assert result.inserted + result.skipped + result.errors == len(rows)
