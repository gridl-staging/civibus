"""WA transaction dispatch and independent-expenditure record-class semantics.

This module owns the "given a row, a data_type, and a resolved record class, what are
its amount/date/type/support-oppose semantics" layer for the WA loader. It is a
lower-level sibling of ``load.py``: it imports the config column resolver and the
per-row parse helpers, but never imports ``load.py`` itself, so ``load.py`` can import
these names freely without a cycle.

The independent-expenditure record classes (C6.2/C6.3/C6.5) derive from the
``independent_expenditures`` default dispatch via :func:`dataclasses.replace`, so an IE
class can never declare a role its extractor cannot produce, and the C6.N class token is
stated once — as the dict key — instead of being duplicated in a per-entry field.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date
from typing import Callable

from domains.campaign_finance.ingest.text_utils import normalize_optional_text

from . import _load_column_for_semantic_path
from .extract import (
    extract_wa_contribution,
    extract_wa_expenditure,
    extract_wa_independent_expenditure,
    extract_wa_loan,
)
from .load_support import _normalize_support_oppose, _parse_optional_wa_date

_normalize_optional_text = normalize_optional_text


@dataclass(frozen=True, slots=True)
class _WATransactionRoles:
    person: str
    organization: str
    committee: str
    address: str


@dataclass(frozen=True, slots=True)
class _WATransactionDispatch:
    amount_semantic_path: str
    date_semantic_path: str
    counterparty_roles: tuple[tuple[str, ...], tuple[str, ...]]
    entity_roles: _WATransactionRoles
    extract_fn: Callable[[dict[str, str | None]], Mapping[str, object]]
    entity_keys: tuple[str, str]
    support_oppose_enabled: bool
    transaction_type_label: str | None
    lands_transaction: bool


_WA_ENTITY_ROLES_BY_TYPE = {
    "contributions": _WATransactionRoles(
        person="donor", organization="contributor", committee="recipient", address="contributor_address"
    ),
    "expenditures": _WATransactionRoles(
        person="payee", organization="payee", committee="payer", address="payee_address"
    ),
    "independent_expenditures": _WATransactionRoles(
        person="payee", organization="payee", committee="sponsor", address="payee_address"
    ),
    "loans": _WATransactionRoles(
        person="lender", organization="lender", committee="borrower", address="lender_address"
    ),
}
_WA_COUNTERPARTY_ROLES_BY_TYPE = {
    "contributions": (("donor",), ("contributor",)),
    "expenditures": (("payee",), ("payee",)),
    "independent_expenditures": (("payee",), ("payee",)),
    "loans": (("lender",), ("lender",)),
}
_WA_EXTRACT_FN = {
    "contributions": extract_wa_contribution,
    "expenditures": extract_wa_expenditure,
    "independent_expenditures": extract_wa_independent_expenditure,
    "loans": extract_wa_loan,
}
_WA_ENTITY_KEYS = {
    "contributions": ("donor_person", "donor_org"),
    "expenditures": ("payee_person", "payee_org"),
    "independent_expenditures": ("payee_person", "payee_org"),
    "loans": ("lender_person", "lender_org"),
}

# Per-data-type default dispatch: the effective descriptor for a row when no IE record
# class applies. Roles/keys/extractor and the semantic amount/date paths have a single
# owner in the maps above; IE record classes derive from the IE default via ``replace``
# so they never restate those facts.
_WA_DEFAULT_DISPATCH = {
    data_type: _WATransactionDispatch(
        amount_semantic_path="transaction.amount",
        date_semantic_path="transaction.date",
        counterparty_roles=_WA_COUNTERPARTY_ROLES_BY_TYPE[data_type],
        entity_roles=_WA_ENTITY_ROLES_BY_TYPE[data_type],
        extract_fn=_WA_EXTRACT_FN[data_type],
        entity_keys=_WA_ENTITY_KEYS[data_type],
        support_oppose_enabled=False,
        transaction_type_label=None,
        lands_transaction=True,
    )
    for data_type in _WA_EXTRACT_FN
}

# WA independent-expenditure record classes, keyed by normalized C6 origin token. Each
# inherits the IE default (payee-shaped extractor/roles/keys) and overrides only its
# deltas, so an IE class can never declare roles its extractor cannot produce. C6.5 is
# recognized here but does not land a transaction in this stage; Stage 4 owns its
# land-or-skip outcome and any funder-specific extraction. The dict key is the single
# source of truth for the class token, read by both resolution and callers.
_WA_IE_RECORD_CLASSES = {
    "C6.2": _WA_DEFAULT_DISPATCH["independent_expenditures"],
    "C6.3": replace(
        _WA_DEFAULT_DISPATCH["independent_expenditures"],
        amount_semantic_path="wa.ie.portion_of_amount",
        date_semantic_path="wa.ie.report_date",
        support_oppose_enabled=True,
        transaction_type_label="C6.3 - Identified Entities",
    ),
    "C6.5": replace(
        _WA_DEFAULT_DISPATCH["independent_expenditures"],
        amount_semantic_path="wa.ie.amount",
        date_semantic_path="wa.ie.date_received",
        lands_transaction=False,
    ),
}


def _origin_opens_with_class_token(normalized_origin: str, class_token: str) -> bool:
    """Return whether an origin opens with exactly ``class_token`` as its class token.

    A bare ``startswith`` would route a malformed or future class such as ``C6.25`` or
    ``C6.2.1`` through C6.2's amount/date/type/support semantics. The class token must
    therefore be terminated: the origin either ends there or continues with a separator
    that cannot extend the numbering (anything other than an alphanumeric or a dot).
    """
    if not normalized_origin.startswith(class_token):
        return False
    remainder = normalized_origin[len(class_token) :]
    if not remainder:
        return True
    return not remainder[0].isalnum() and remainder[0] != "."


def _resolve_wa_ie_record_class(row: Mapping[str, str | None], data_type: str) -> _WATransactionDispatch | None:
    """Resolve a row's IE record class from ``wa.origin``, or ``None`` for non-IE types.

    Empty or unknown origins raise loudly: an origin that does not open with exactly one
    known class token is not routable and must not silently fall through to a default.
    """
    if data_type != "independent_expenditures":
        return None

    origin_column = _load_column_for_semantic_path(data_type, "wa.origin")
    origin = _normalize_optional_text(row.get(origin_column))
    if origin is None:
        raise ValueError("WA independent expenditure origin is required for record-class routing")

    normalized_origin = origin.upper()
    for class_token, record_class in _WA_IE_RECORD_CLASSES.items():
        if _origin_opens_with_class_token(normalized_origin, class_token.upper()):
            return record_class

    raise ValueError(f"Unsupported WA independent expenditure origin: {origin!r}")


def _wa_effective_dispatch(
    data_type: str,
    record_class: _WATransactionDispatch | None,
) -> _WATransactionDispatch:
    """Return the authoritative dispatch descriptor for a row.

    ``record_class`` is authoritative: a resolved WA IE record class is used verbatim,
    otherwise the per-data-type default applies. Callers resolve the class once via
    :func:`_resolve_wa_ie_record_class` and thread it through, so this never re-resolves
    from the row.
    """
    if record_class is not None:
        return record_class
    return _WA_DEFAULT_DISPATCH[data_type]


def _guard_wa_ie_transaction_type(data_type: str, transaction_type: str) -> str:
    """Reject IE transaction types colliding with PDC receipt/disbursement sort codes.

    ``total_raised``/``total_spent`` aggregates and the receipt-only partial indexes key
    on a ``1``/``2`` transaction_type prefix, so an IE landing under one would corrupt
    those totals. The observed IE report_type vocabulary never starts with a digit; a
    value that does is a contract violation, surfaced as a per-row error rather than
    silent aggregate corruption.
    """
    if data_type == "independent_expenditures" and transaction_type.startswith(("1", "2")):
        raise ValueError(
            f"WA independent expenditure transaction_type {transaction_type!r} collides with "
            "PDC receipt/disbursement sort-code prefixes (1/2)"
        )
    return transaction_type


def _transaction_amount_field(
    data_type: str,
    *,
    record_class: _WATransactionDispatch | None,
) -> str:
    dispatch = _wa_effective_dispatch(data_type, record_class)
    return _load_column_for_semantic_path(data_type, dispatch.amount_semantic_path)


def _transaction_date_from_row(
    row: Mapping[str, str | None],
    data_type: str,
    *,
    record_class: _WATransactionDispatch | None,
) -> date | None:
    dispatch = _wa_effective_dispatch(data_type, record_class)
    return _parse_optional_wa_date(row.get(_load_column_for_semantic_path(data_type, dispatch.date_semantic_path)))


def _transaction_type_from_row(
    row: Mapping[str, str | None],
    data_type: str,
    *,
    record_class: _WATransactionDispatch | None,
) -> str:
    dispatch = _wa_effective_dispatch(data_type, record_class)
    if dispatch.transaction_type_label is not None:
        return dispatch.transaction_type_label

    candidate_paths = ("transaction.type", "transaction.loan_type", "transaction.receipt_type")
    for semantic_path in candidate_paths:
        try:
            column_name = _load_column_for_semantic_path(data_type, semantic_path)
        except RuntimeError:
            continue
        normalized = _normalize_optional_text(row.get(column_name))
        if normalized is not None:
            return _guard_wa_ie_transaction_type(data_type, normalized)
    if data_type == "independent_expenditures":
        return "Independent Expenditure"
    # Live data sometimes has empty type columns; fall back to singularized data_type
    return data_type.rstrip("s")


def _wa_support_oppose(
    row: Mapping[str, str | None],
    data_type: str,
    *,
    record_class: _WATransactionDispatch | None,
) -> str | None:
    dispatch = _wa_effective_dispatch(data_type, record_class)
    if not dispatch.support_oppose_enabled:
        return None
    column_name = _load_column_for_semantic_path(data_type, "transaction.support_oppose")
    return _normalize_support_oppose(row.get(column_name))
