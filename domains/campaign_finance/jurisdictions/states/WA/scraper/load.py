from __future__ import annotations

import logging
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

import psycopg

from core.db import (
    find_organization_by_identifier,
    resolve_organization_by_canonical_name,
    resolve_person_by_name_and_zip,
    try_insert_source_record,
    upsert_address,
)
from core.types.python.models import (
    Address,
    DataSource,
    Organization,
    Person,
    SourceRecord,
    compute_record_hash,
    utc_now,
)
from domains.campaign_finance.ingest.filing_loader import (
    ensure_state_committee,
    resolve_transaction_counterparty_ids,
    upsert_filing,
    upsert_transaction,
)
from domains.campaign_finance.ingest.text_utils import normalize_optional_text
from domains.campaign_finance.jurisdictions.states.load_utils import (
    LoadResult,
    commit_managed_transaction,
    ensure_data_source,
    ensure_transaction_open,
    link_entity_source_and_optional_mailing_address,
    validated_limit,
)
from domains.campaign_finance.types.models import Filing, Transaction

from . import (
    _load_column_for_semantic_path,
    _load_data_source_name_for_data_type,
    _load_data_source_url_for_data_type,
)
from .ie_record_classes import (
    _WA_EXTRACT_FN,
    _WATransactionDispatch,
    _WATransactionRoles,
    _resolve_wa_ie_record_class,
    _transaction_amount_field,
    _transaction_date_from_row,
    _transaction_type_from_row,
    _wa_effective_dispatch,
    _wa_support_oppose,
)
from .load_support import (
    _parse_required_wa_amount,
    _required_wa_text,
)
from .parse import parse_contributions, parse_expenditures, parse_independent_expenditures, parse_loans
from .relational_utils import (
    WAFilingLookupEntry as _WAFilingLookupEntry,
    WALoadCounts as _WALoadCounts,
    WARelationalOperations,
    WARelationalPassSettings,
    WASourceRecordKeyLedger as _WASourceRecordKeyLedger,
    load_wa_relational_transactions as _run_wa_relational_transactions,
)

LOGGER = logging.getLogger(__name__)

_WA_DOMAIN = "campaign_finance"
_WA_JURISDICTION = "state/WA"
_WA_SOURCE_FORMAT = "csv"

# One commit per this many iterated rows: both WA row loops share the boundary.
_COMMIT_BATCH_ROWS = 1_000
_normalize_optional_text = normalize_optional_text


@dataclass(frozen=True, slots=True)
class _WATransactionEntities:
    person: Person | None
    organization: Organization | None
    committee: Organization
    address: Address | None


_WA_PARSER_FN = {
    "contributions": parse_contributions,
    "expenditures": parse_expenditures,
    "independent_expenditures": parse_independent_expenditures,
    "loans": parse_loans,
}
_WA_COUNTERPARTY_NAME_PATH = {
    "contributions": "donor.name",
    "expenditures": "payee.name",
    "independent_expenditures": "payee.name",
    "loans": "lender.name",
}
_WA_COUNTERPARTY_EMPLOYER_PATH = {"contributions": "donor.employer", "loans": "lender.employer"}


def ensure_wa_data_source(conn: psycopg.Connection, data_type: str = "contributions") -> UUID:
    normalized_data_type = data_type.strip().lower()
    data_source_name = _load_data_source_name_for_data_type(normalized_data_type)

    data_source = DataSource(
        domain=_WA_DOMAIN,
        jurisdiction=_WA_JURISDICTION,
        name=data_source_name,
        source_url=_load_data_source_url_for_data_type(normalized_data_type),
        source_format=_WA_SOURCE_FORMAT,
    )
    return ensure_data_source(conn, data_source)


def _wa_source_record_key(row: Mapping[str, str | None]) -> str:
    return compute_record_hash(dict(row))


def _build_wa_source_record(
    data_source_id: UUID,
    row: Mapping[str, str | None],
    *,
    data_type: str,
) -> SourceRecord:
    raw_fields = dict(row)
    record_hash = compute_record_hash(raw_fields)
    return SourceRecord(
        data_source_id=data_source_id,
        source_record_key=record_hash,
        source_url=_source_record_url(row, data_type=data_type),
        raw_fields=raw_fields,
        record_hash=record_hash,
        pull_date=utc_now(),
    )


def _source_record_url(row: Mapping[str, str | None], *, data_type: str) -> str:
    try:
        source_url_column = _load_column_for_semantic_path(data_type, "wa.source_url")
    except RuntimeError:
        return _load_data_source_url_for_data_type(data_type)

    source_url = _normalize_optional_text(row.get(source_url_column))
    if source_url is not None:
        return source_url
    return _load_data_source_url_for_data_type(data_type)


def _resolve_wa_committee_id(conn: psycopg.Connection, committee: Organization) -> UUID:
    committee_identifier = _normalize_optional_text(committee.identifiers.get("wa_committee_id"))
    if committee_identifier is not None:
        existing_org_id = find_organization_by_identifier(conn, "wa_committee_id", committee_identifier)
        if existing_org_id is not None:
            return existing_org_id
    return resolve_organization_by_canonical_name(conn, committee)


def _load_wa_transaction_entities(
    conn: psycopg.Connection,
    *,
    source_record_id: UUID,
    entities: _WATransactionEntities,
    roles: _WATransactionRoles,
) -> None:
    address_id = None
    if entities.address is not None:
        address_id = upsert_address(conn, entities.address)
        link_entity_source_and_optional_mailing_address(
            conn,
            entity_type="address",
            entity_id=address_id,
            source_record_id=source_record_id,
            extraction_role=roles.address,
            address_id=None,
        )

    person_id = resolve_person_by_name_and_zip(conn, entities.person, entities.address)
    if person_id is not None:
        link_entity_source_and_optional_mailing_address(
            conn,
            entity_type="person",
            entity_id=person_id,
            source_record_id=source_record_id,
            extraction_role=roles.person,
            address_id=address_id,
        )

    committee_id = _resolve_wa_committee_id(conn, entities.committee)
    link_entity_source_and_optional_mailing_address(
        conn,
        entity_type="organization",
        entity_id=committee_id,
        source_record_id=source_record_id,
        extraction_role=roles.committee,
        address_id=None,
    )

    organization_id = resolve_organization_by_canonical_name(conn, entities.organization)
    if organization_id is not None:
        link_entity_source_and_optional_mailing_address(
            conn,
            entity_type="organization",
            entity_id=organization_id,
            source_record_id=source_record_id,
            extraction_role=roles.organization,
            address_id=address_id,
        )


def _load_wa_transaction_row(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    data_source_id: UUID,
    *,
    data_type: str,
    entities: _WATransactionEntities,
    roles: _WATransactionRoles,
) -> bool:
    source_record_id = try_insert_source_record(conn, _build_wa_source_record(data_source_id, row, data_type=data_type))
    if source_record_id is None:
        return False

    _load_wa_transaction_entities(
        conn,
        source_record_id=source_record_id,
        entities=entities,
        roles=roles,
    )
    return True


def _extract_and_load_wa_row(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    data_source_id: UUID,
    *,
    data_type: str,
) -> bool:
    if data_type not in _WA_EXTRACT_FN:
        raise ValueError(f"Unsupported WA data_type: {data_type}")
    dispatch = _wa_effective_dispatch(data_type, _resolve_wa_ie_record_class(row, data_type))
    person_key, org_key = dispatch.entity_keys
    extracted = dispatch.extract_fn(dict(row))
    return _load_wa_transaction_row(
        conn,
        row,
        data_source_id,
        data_type=data_type,
        entities=_WATransactionEntities(
            person=extracted[person_key],
            organization=extracted[org_key],
            committee=extracted["committee"],
            address=extracted["address"],
        ),
        roles=dispatch.entity_roles,
    )


def load_wa_contribution(conn: psycopg.Connection, row: Mapping[str, str | None], data_source_id: UUID) -> bool:
    return _extract_and_load_wa_row(conn, row, data_source_id, data_type="contributions")


def load_wa_expenditure(conn: psycopg.Connection, row: Mapping[str, str | None], data_source_id: UUID) -> bool:
    return _extract_and_load_wa_row(conn, row, data_source_id, data_type="expenditures")


def load_wa_loan(conn: psycopg.Connection, row: Mapping[str, str | None], data_source_id: UUID) -> bool:
    return _extract_and_load_wa_row(conn, row, data_source_id, data_type="loans")


def _try_load_row(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    *,
    data_source_id: UUID,
    data_type: str,
    manages_outer_transaction: bool,
) -> bool | None:
    try:
        if manages_outer_transaction:
            ensure_transaction_open(conn)
        with conn.transaction():
            return _extract_and_load_wa_row(conn, row, data_source_id, data_type=data_type)
    except Exception:  # noqa: BLE001
        LOGGER.exception("Failed loading WA %s row", data_type.rstrip("s"))
        return None


def _load_wa_rows(
    conn: psycopg.Connection,
    rows: Iterable[Mapping[str, str | None]],
    *,
    data_source_id: UUID,
    data_type: str,
    limit: int | None,
    key_ledger: _WASourceRecordKeyLedger | None = None,
) -> LoadResult:
    """Load WA source records for ``data_type``, tallying per-row load outcomes.

    When ``key_ledger`` is supplied, every row's source-record key is recorded on it — as
    rejected when this pass errors on the row, as persisted when the row lands by insert or
    by dedupe skip. The two-pass ``_load_wa_with_filings`` uses that ledger to let the
    relational pass skip a row this pass errored on and nothing persisted — so a single
    malformed row (e.g. an unknown IE origin) is counted once, even if a stale source record
    for it survives from an earlier load.
    """
    started_at = time.monotonic()
    counts = _WALoadCounts()
    manages_outer_transaction = conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE

    for index, row in enumerate(rows, start=1):
        if limit is not None and index > limit:
            break
        if not isinstance(row, Mapping):
            raise TypeError(f"Expected mapping row, got {type(row)!r}")

        inserted = _try_load_row(
            conn,
            row,
            data_source_id=data_source_id,
            data_type=data_type,
            manages_outer_transaction=manages_outer_transaction,
        )
        if inserted is None:
            counts.errors += 1
            if key_ledger is not None:
                key_ledger.rejected_attempts[_wa_source_record_key(row)] += 1
        else:
            if inserted:
                counts.inserted += 1
            else:
                counts.skipped += 1
            if key_ledger is not None:
                key_ledger.persisted.add(_wa_source_record_key(row))

        processed_count = counts.inserted + counts.skipped + counts.errors
        if processed_count % _COMMIT_BATCH_ROWS == 0:
            commit_managed_transaction(conn, manages_outer_transaction)

    commit_managed_transaction(conn, manages_outer_transaction)

    return LoadResult(
        inserted=counts.inserted,
        skipped=counts.skipped,
        quarantined=int(getattr(rows, "skipped", 0)),
        superseded=0,
        errors=counts.errors,
        elapsed_seconds=time.monotonic() - started_at,
    )


def _load_wa_file(
    conn: psycopg.Connection,
    file_path: str | Path,
    *,
    data_source_id: UUID,
    data_type: str,
    limit: int | None = None,
    key_ledger: _WASourceRecordKeyLedger | None = None,
) -> LoadResult:
    validated_row_limit = validated_limit(limit)
    parser = _WA_PARSER_FN[data_type](Path(file_path))
    return _load_wa_rows(
        conn,
        parser,
        data_source_id=data_source_id,
        data_type=data_type,
        limit=validated_row_limit,
        key_ledger=key_ledger,
    )


def load_wa_contributions(
    conn: psycopg.Connection, fp: str | Path, *, data_source_id: UUID, limit: int | None = None
) -> LoadResult:
    return _load_wa_file(conn, fp, data_source_id=data_source_id, data_type="contributions", limit=limit)


def load_wa_expenditures(
    conn: psycopg.Connection, fp: str | Path, *, data_source_id: UUID, limit: int | None = None
) -> LoadResult:
    return _load_wa_file(conn, fp, data_source_id=data_source_id, data_type="expenditures", limit=limit)


def load_wa_loans(
    conn: psycopg.Connection, fp: str | Path, *, data_source_id: UUID, limit: int | None = None
) -> LoadResult:
    return _load_wa_file(conn, fp, data_source_id=data_source_id, data_type="loans", limit=limit)


def _select_wa_source_record_id(
    conn: psycopg.Connection,
    *,
    data_source_id: UUID,
    source_record_key: str,
) -> UUID | None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT id
            FROM core.source_record
            WHERE data_source_id = %s
              AND source_record_key = %s
            LIMIT 1
            """,
            (data_source_id, source_record_key),
        )
        row = cursor.fetchone()
    if row is None:
        return None
    return row[0]


def _build_wa_filing_fec_id(
    row: Mapping[str, str | None],
    data_type: str,
    *,
    record_class: _WATransactionDispatch | None,
) -> str:
    committee_id_column = _load_column_for_semantic_path(data_type, "committee.id")
    year_column = _load_column_for_semantic_path(data_type, "transaction.year")
    committee_identifier = _required_wa_text(row.get(committee_id_column), committee_id_column)
    filing_year = _normalize_optional_text(row.get(year_column))
    if filing_year is None:
        transaction_date = _transaction_date_from_row(row, data_type, record_class=record_class)
        if transaction_date is None:
            raise ValueError("WA row is missing both transaction year and transaction date")
        filing_year = str(transaction_date.year)
    return f"WA-{committee_identifier}-{filing_year}-{data_type}"


def _resolve_wa_filing_committee_id(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    data_type: str,
    *,
    record_class: _WATransactionDispatch | None,
) -> UUID:
    extracted = _wa_effective_dispatch(data_type, record_class).extract_fn(dict(row))
    committee_organization_id = _resolve_wa_committee_id(conn, extracted["committee"])
    committee_id_column = _load_column_for_semantic_path(data_type, "committee.id")
    native_committee_id = _required_wa_text(row.get(committee_id_column), committee_id_column)
    return ensure_state_committee(
        conn,
        state="WA",
        native_committee_id=native_committee_id,
        organization_id=committee_organization_id,
    )


def _build_wa_filing(
    row: Mapping[str, str | None],
    *,
    committee_id: UUID,
    source_record_id: UUID,
    data_type: str,
    record_class: _WATransactionDispatch | None,
) -> Filing:
    """Build the WA filing a row belongs to, dated independently of its record class.

    ``record_class`` reaches the filing identity only. A filing is keyed by committee and
    year, so rows of different record classes upsert the same filing row and ``upsert_filing``
    COALESCEs a non-null date over the stored one — dating the filing from the row's
    record-class date column would let source row order pick C6.3's ``report_date`` over
    C6.2's ``date_expense_obligated``. The filing date is a filing-level fact, so it uses the
    class-independent date path.
    """
    filing_date = _transaction_date_from_row(row, data_type, record_class=None)
    return Filing(
        filing_fec_id=_build_wa_filing_fec_id(row, data_type, record_class=record_class),
        committee_id=committee_id,
        report_type=data_type,
        amendment_indicator="N",
        filing_name=_normalize_optional_text(row.get(_load_column_for_semantic_path(data_type, "committee.name"))),
        receipt_date=filing_date,
        accepted_date=filing_date,
        source_record_id=source_record_id,
    )


def _upsert_wa_filing(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    *,
    source_record_id: UUID,
    data_type: str,
    filing_lookup: dict[str, _WAFilingLookupEntry],
    record_class: _WATransactionDispatch | None,
) -> _WAFilingLookupEntry:
    filing_fec_id = _build_wa_filing_fec_id(row, data_type, record_class=record_class)
    existing_entry = filing_lookup.get(filing_fec_id)
    committee_id = (
        _resolve_wa_filing_committee_id(conn, row, data_type, record_class=record_class)
        if existing_entry is None
        else existing_entry.committee_id
    )
    filing_source_record_id = source_record_id if existing_entry is None else existing_entry.source_record_id

    filing = _build_wa_filing(
        row,
        committee_id=committee_id,
        source_record_id=filing_source_record_id,
        data_type=data_type,
        record_class=record_class,
    )
    filing_id = upsert_filing(conn, filing)
    if existing_entry is not None and existing_entry.filing_id != filing_id:
        raise ValueError(
            f"WA filing lookup drift for filing_fec_id={filing_fec_id!r}: {existing_entry.filing_id} != {filing_id}"
        )

    entry = _WAFilingLookupEntry(
        filing_id=filing_id,
        committee_id=committee_id,
        source_record_id=filing_source_record_id,
    )
    filing_lookup[filing_fec_id] = entry
    return entry


def _counterparty_name_raw(row: Mapping[str, str | None], data_type: str) -> str | None:
    semantic_path = _WA_COUNTERPARTY_NAME_PATH.get(data_type)
    if semantic_path is None:
        raise ValueError(f"Unsupported WA data_type: {data_type}")
    return _normalize_optional_text(row.get(_load_column_for_semantic_path(data_type, semantic_path)))


def _counterparty_employer(row: Mapping[str, str | None], data_type: str) -> str | None:
    semantic_path = _WA_COUNTERPARTY_EMPLOYER_PATH.get(data_type)
    if semantic_path is None:
        return None
    return _normalize_optional_text(row.get(_load_column_for_semantic_path(data_type, semantic_path)))


def _resolve_wa_transaction_address_id(
    conn: psycopg.Connection,
    *,
    source_record_id: UUID,
    data_type: str,
    record_class: _WATransactionDispatch | None,
) -> UUID | None:
    address_role = _wa_effective_dispatch(data_type, record_class).entity_roles.address
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT entity_id
            FROM core.entity_source
            WHERE source_record_id = %s
              AND entity_type = 'address'
              AND extraction_role = %s
            LIMIT 1
            """,
            (source_record_id, address_role),
        )
        row = cursor.fetchone()
    if row is None:
        return None
    return row[0]


def _upsert_wa_transaction_with_filing(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    *,
    filing_id: UUID,
    committee_id: UUID,
    source_record_id: UUID,
    data_type: str,
    record_class: _WATransactionDispatch | None,
) -> None:
    """Upsert a WA transaction through its record-class-aware dispatch.

    The dispatch extractor is the router's authoritative output and cannot diverge from
    the resolved record class. Recomputing this pure, cheap extraction keeps the filing
    and transaction paths independent; caching its payload is intentionally unnecessary.
    """
    dispatch = _wa_effective_dispatch(data_type, record_class)
    person_roles, organization_roles = dispatch.counterparty_roles
    contributor_person_id, contributor_organization_id = resolve_transaction_counterparty_ids(
        conn,
        source_record_id=source_record_id,
        person_roles=person_roles,
        organization_roles=organization_roles,
    )
    contributor_address_id = _resolve_wa_transaction_address_id(
        conn,
        source_record_id=source_record_id,
        data_type=data_type,
        record_class=record_class,
    )

    counterparty_addr = dispatch.extract_fn(dict(row))["address"]
    contributor_state = counterparty_addr.state if counterparty_addr is not None else None
    contributor_city = counterparty_addr.city if counterparty_addr is not None else None
    contributor_zip = counterparty_addr.zip5 if counterparty_addr is not None else None

    amount_field = _transaction_amount_field(data_type, record_class=record_class)
    upsert_transaction(
        conn,
        Transaction(
            filing_id=filing_id,
            committee_id=committee_id,
            transaction_type=_transaction_type_from_row(row, data_type, record_class=record_class),
            transaction_identifier=_wa_source_record_key(row),
            transaction_date=_transaction_date_from_row(row, data_type, record_class=record_class),
            amount=_parse_required_wa_amount(row.get(amount_field), amount_field),
            contributor_name_raw=_counterparty_name_raw(row, data_type),
            contributor_employer=_counterparty_employer(row, data_type),
            contributor_city=contributor_city,
            contributor_state=contributor_state,
            contributor_zip=contributor_zip,
            contributor_person_id=contributor_person_id,
            contributor_organization_id=contributor_organization_id,
            contributor_address_id=contributor_address_id,
            recipient_committee_id=committee_id,
            amendment_indicator="N",
            source_record_id=source_record_id,
            support_oppose=_wa_support_oppose(row, data_type, record_class=record_class),
        ),
    )


def _evict_rolled_back_filing(
    filing_lookup: dict[str, _WAFilingLookupEntry],
    row: Mapping[str, str | None],
    data_type: str,
    record_class: _WATransactionDispatch | None,
) -> None:
    """Drop a rolled-back filing's cache entry so a later good row re-upserts it.

    The failing row may not have a computable filing_fec_id (e.g. an unknown origin that
    raised before any filing was built), in which case there is nothing cached to evict.
    """
    try:
        filing_fec_id = _build_wa_filing_fec_id(row, data_type, record_class=record_class)
    except Exception:  # noqa: BLE001
        return
    filing_lookup.pop(filing_fec_id, None)


def _load_wa_relational_transactions(
    conn: psycopg.Connection,
    rows: Iterable[Mapping[str, str | None]],
    *,
    data_source_id: UUID,
    data_type: str,
    limit: int | None,
    key_ledger: _WASourceRecordKeyLedger | None = None,
) -> _WALoadCounts:
    """Delegate WA's relational pass while keeping its row operations patchable here.

    :func:`~.relational_utils.load_wa_relational_transactions` owns the loop, the commit
    boundary, and what the returned counts mean.
    """
    return _run_wa_relational_transactions(
        conn,
        rows,
        settings=WARelationalPassSettings(
            data_source_id=data_source_id,
            data_type=data_type,
            limit=limit,
            commit_batch_rows=_COMMIT_BATCH_ROWS,
            key_ledger=key_ledger,
            operations=WARelationalOperations(
                source_record_key=_wa_source_record_key,
                select_source_record_id=_select_wa_source_record_id,
                upsert_filing=_upsert_wa_filing,
                upsert_transaction=_upsert_wa_transaction_with_filing,
                evict_rolled_back_filing=_evict_rolled_back_filing,
            ),
        ),
    )


def _load_wa_with_filings(
    conn: psycopg.Connection,
    file_path: str | Path,
    *,
    data_type: str,
    limit: int | None = None,
) -> LoadResult:
    """Run the source-record pass then the relational pass, folding both into one result.

    The relational pass's ``errors`` and ``skipped`` counts are folded into the
    ``LoadResult`` the source-record pass produced;
    :func:`~.relational_utils.load_wa_relational_transactions` owns what those two counts
    mean. Conflating both skip causes into one field is
    intentional — it keeps the decision's "a skip is never an error" invariant without
    adding a cross-loader field to the shared ``LoadResult``.
    """
    validated_row_limit = validated_limit(limit)
    # Sample ownership before ensure_wa_data_source runs SQL and implicitly opens a
    # transaction, then commit the data-source row so the connection is IDLE again. Both
    # passes below sample ownership on entry, so a lookup left open here would make them
    # believe an outer caller owns the transaction and silently skip every periodic
    # commit — leaving the boundary in place but dead.
    manages_outer_transaction = conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE
    data_source_id = ensure_wa_data_source(conn, data_type=data_type)
    commit_managed_transaction(conn, manages_outer_transaction)
    key_ledger = _WASourceRecordKeyLedger()
    load_result = _load_wa_file(
        conn,
        file_path,
        data_source_id=data_source_id,
        data_type=data_type,
        limit=validated_row_limit,
        key_ledger=key_ledger,
    )
    # A key the source-record pass both rejected and persisted lost nothing: attempts may
    # have failed non-deterministically, but a byte-identical duplicate row confirmed the
    # content persisted, so those attempt errors are spurious and every copy links below.
    # The attempts move to ``skipped`` rather than disappearing: their content was already
    # persisted by the copy that landed, which is what a dedupe skip means, and rebucketing
    # keeps inserted + skipped + errors equal to the rows the source-record pass read.
    spurious_attempt_errors = key_ledger.rejected_attempts_for_persisted_keys()
    load_result.errors -= spurious_attempt_errors
    load_result.skipped += spurious_attempt_errors
    relational_counts = _load_wa_relational_transactions(
        conn,
        _WA_PARSER_FN[data_type](Path(file_path)),
        data_source_id=data_source_id,
        data_type=data_type,
        limit=validated_row_limit,
        key_ledger=key_ledger,
    )
    load_result.errors += relational_counts.errors
    load_result.skipped += relational_counts.skipped
    return load_result


def load_wa_contributions_with_filings(
    conn: psycopg.Connection, fp: str | Path, *, limit: int | None = None
) -> LoadResult:
    return _load_wa_with_filings(conn, fp, data_type="contributions", limit=limit)


def load_wa_expenditures_with_filings(
    conn: psycopg.Connection, fp: str | Path, *, limit: int | None = None
) -> LoadResult:
    return _load_wa_with_filings(conn, fp, data_type="expenditures", limit=limit)


def load_wa_independent_expenditures_with_filings(
    conn: psycopg.Connection, fp: str | Path, *, limit: int | None = None
) -> LoadResult:
    return _load_wa_with_filings(conn, fp, data_type="independent_expenditures", limit=limit)


def load_wa_loans_with_filings(conn: psycopg.Connection, fp: str | Path, *, limit: int | None = None) -> LoadResult:
    return _load_wa_with_filings(conn, fp, data_type="loans", limit=limit)
