
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator
from uuid import UUID

import psycopg

from core.db import resolve_organization_by_canonical_name, try_insert_source_record
from core.types.python.models import (
    DataSource,
    Organization,
    SourceRecord,
    compute_record_hash,
    utc_now,
)
from domains.campaign_finance.ingest.filing_loader import (
    ensure_state_committee,
    upsert_filing,
    upsert_transaction,
)
from domains.campaign_finance.jurisdictions.states.load_utils import (
    LoadResult,
    commit_managed_transaction,
    ensure_data_source,
    ensure_transaction_open,
    validated_limit,
)
from domains.campaign_finance.types.models import Filing, Transaction

from .parse import PHLCampaignFinanceRow, parse_phl_carto_rows

LOGGER = logging.getLogger(__name__)

_PHL_DOMAIN = "campaign_finance"
_PHL_JURISDICTION = "municipality/PHL"
_PHL_SOURCE_FORMAT = "json"

_PHL_CONTRIBUTIONS_DATA_SOURCE_NAME = "PHL Campaign Finance Contributions"
_PHL_EXPENDITURES_DATA_SOURCE_NAME = "PHL Campaign Finance Expenditures"

# The Carto API sits behind the same site URL for both tables; the
# data_source row name is what differentiates contributions from
# expenditures in `core.data_source` (the `(domain, jurisdiction, name)`
# unique key carries the distinction).
_PHL_DATA_SOURCE_URL = "https://www.phila.gov/departments/board-of-ethics/campaign-finance/"


@dataclass(slots=True)
class _PHLLoadCounts:
    inserted: int = 0
    skipped: int = 0
    quarantined: int = 0
    errors: int = 0


def ensure_phl_contributions_data_source(conn: psycopg.Connection) -> UUID:
    """Create or retrieve the PHL contributions data source row."""
    return ensure_data_source(
        conn,
        DataSource(
            domain=_PHL_DOMAIN,
            jurisdiction=_PHL_JURISDICTION,
            name=_PHL_CONTRIBUTIONS_DATA_SOURCE_NAME,
            source_url=_PHL_DATA_SOURCE_URL,
            source_format=_PHL_SOURCE_FORMAT,
        ),
    )


def ensure_phl_expenditures_data_source(conn: psycopg.Connection) -> UUID:
    """Create or retrieve the PHL expenditures data source row."""
    return ensure_data_source(
        conn,
        DataSource(
            domain=_PHL_DOMAIN,
            jurisdiction=_PHL_JURISDICTION,
            name=_PHL_EXPENDITURES_DATA_SOURCE_NAME,
            source_url=_PHL_DATA_SOURCE_URL,
            source_format=_PHL_SOURCE_FORMAT,
        ),
    )


def _iter_jsonl_rows(file_path: Path) -> Iterator[dict[str, object]]:
    """Yield one parsed JSON object per line of a JSONL file.

    Tolerant of malformed JSONL: a single bad line (truncated JSON,
    trailing curl bracket, garbage characters) is logged and skipped
    rather than aborting the whole load. Non-dict JSON values (`null`,
    arrays, primitives) are also skipped — only dict rows are yielded.
    """
    with file_path.open("r", encoding="utf-8") as fp:
        for line_number, line in enumerate(fp, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                LOGGER.warning(
                    "Skipping malformed JSONL line %d in %s: %s",
                    line_number,
                    file_path,
                    exc,
                )
                continue
            if isinstance(obj, dict):
                yield obj


def load_phl_source_records(
    conn: psycopg.Connection,
    file_path: str | Path,
    *,
    is_expenditure: bool,
    limit: int | None = None,
) -> LoadResult:
    """Load PHL Carto rows from a JSONL file into `core.source_record`.

    Pass-1 provenance loader. Each unique (data_source_id, record_hash) is
    inserted once; duplicates are counted as `skipped` for idempotency.
    Rows that fail Pydantic validation (missing required fields, malformed
    amount/date) are counted as `quarantined` rather than aborting the
    batch.

    `is_expenditure=True` selects the expenditures data source; False
    selects contributions. Both share the same loader; the parser
    distinguishes donor_/payee_ counterparty columns based on this flag.
    """
    path = Path(file_path)
    row_limit = validated_limit(limit)
    if is_expenditure:
        data_source_id = ensure_phl_expenditures_data_source(conn)
    else:
        data_source_id = ensure_phl_contributions_data_source(conn)
    started_at = time.monotonic()
    counts = _PHLLoadCounts()
    manages_outer = conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE

    raw_rows = _iter_jsonl_rows(path)
    if row_limit is not None:
        raw_rows = _take(raw_rows, row_limit)

    # Stream row-by-row so large pulls (hundreds of thousands of rows)
    # don't require full in-memory materialization before pass-1 writes.
    for raw in raw_rows:
        try:
            parsed = next(
                iter(parse_phl_carto_rows([raw], is_expenditure=is_expenditure))
            )
        except StopIteration:
            counts.skipped += 1
            continue
        except Exception:  # noqa: BLE001 — Pydantic validation surfaces here
            counts.quarantined += 1
            LOGGER.exception("PHL row failed validation; quarantined")
            continue

        record_hash = compute_record_hash(_to_jsonable(raw))
        try:
            if manages_outer:
                ensure_transaction_open(conn)
            with conn.transaction():
                sr = SourceRecord(
                    data_source_id=data_source_id,
                    source_record_key=record_hash,
                    source_url=_PHL_DATA_SOURCE_URL,
                    raw_fields=_to_jsonable(raw),
                    record_hash=record_hash,
                    pull_date=utc_now(),
                )
                sr_id = try_insert_source_record(conn, sr)
                if sr_id is None:
                    counts.skipped += 1
                else:
                    counts.inserted += 1
            commit_managed_transaction(conn, manages_outer)
        except Exception:  # noqa: BLE001
            counts.errors += 1
            LOGGER.exception(
                "Failed inserting PHL source record (transaction_id=%s)",
                parsed.transaction_id,
            )

    commit_managed_transaction(conn, manages_outer)

    return LoadResult(
        inserted=counts.inserted,
        skipped=counts.skipped,
        quarantined=counts.quarantined,
        superseded=0,
        errors=counts.errors,
        elapsed_seconds=time.monotonic() - started_at,
    )


def _to_jsonable(row: dict[str, object]) -> dict[str, object]:
    """Convert a Carto row dict to a JSON-serializable form for hashing.

    Carto JSON already returns primitives, but the JSONL writer used
    `json.dumps(..., default=str)` which means dates land as ISO strings.
    Re-roundtripping through json keeps the hash stable across runs.
    """
    # Lightweight pass: every value that survived JSON encoding is already
    # serializable. Values like Decimal/date never appear in the JSONL file
    # (they were stringified at write time), so a shallow copy suffices.
    return dict(row)


def _take(iterator: Iterator[dict[str, object]], n: int) -> Iterator[dict[str, object]]:
    """Yield the first n items from an iterator."""
    for index, item in enumerate(iterator):
        if index >= n:
            return
        yield item


# ---------------------------------------------------------------------------
# Pass 2 — relational: cf.committee, cf.filing, cf.transaction upserts
# ---------------------------------------------------------------------------


# PA is the canonical state for Philadelphia committees in cf.committee.state.
_PHL_STATE_CODE = "PA"


def _phl_native_committee_id(parsed: PHLCampaignFinanceRow) -> str:
    """Return the canonical native committee identifier for a PHL row.

    Prefers `filer_id` (the Carto-side filer key); falls back to a
    namespaced filer name when the source omits the id (rare but
    observed in pre-2020 historical rows).
    """
    if parsed.filer_id:
        return f"phl-{parsed.filer_id.strip()}"
    if parsed.filer_name:
        return f"phl-name-{parsed.filer_name.strip()}"
    raise ValueError("PHL row has neither filer_id nor filer_name")


def _phl_filing_fec_id(parsed: PHLCampaignFinanceRow) -> str:
    """Build a deterministic filing FEC ID for a PHL row.

    Group transactions under their source `report_id` filing when present
    (one cf.filing per PHL filing report); otherwise fall back to a
    per-(year, native_id) bucket so historical rows lacking report_id
    still aggregate sensibly rather than producing one filing per row.
    """
    native = _phl_native_committee_id(parsed)
    if parsed.report_id:
        return f"PHL-{native}-{parsed.report_id}"
    year = parsed.report_year or parsed.transaction_date.year
    return f"PHL-{native}-{year}"


def _phl_filing(
    parsed: PHLCampaignFinanceRow,
    *,
    committee_id: UUID,
    source_record_id: UUID,
) -> Filing:
    return Filing(
        filing_fec_id=_phl_filing_fec_id(parsed),
        committee_id=committee_id,
        report_type="expenditures" if parsed.is_expenditure else "contributions",
        amendment_indicator="N",
        filing_name=parsed.filer_name or None,
        coverage_start_date=None,
        coverage_end_date=None,
        receipt_date=parsed.transaction_date,
        accepted_date=parsed.transaction_date,
        source_record_id=source_record_id,
    )


def _phl_transaction(
    parsed: PHLCampaignFinanceRow,
    *,
    filing_id: UUID,
    committee_id: UUID,
    source_record_id: UUID,
) -> Transaction:
    return Transaction(
        filing_id=filing_id,
        committee_id=committee_id,
        # PHL Carto's transaction_type vocabulary (e.g. "Monetary Contributions",
        # "In-Kind") is preserved verbatim so downstream consumers can group;
        # IE classification (when needed) lives in a future enrichment pass.
        transaction_type=parsed.transaction_type or (
            "expenditure" if parsed.is_expenditure else "contribution"
        ),
        transaction_identifier=parsed.transaction_id,
        transaction_date=parsed.transaction_date,
        amount=parsed.transaction_amount,
        contributor_name_raw=parsed.counterparty_name,
        contributor_employer=parsed.counterparty_employer,
        contributor_occupation=parsed.counterparty_occupation,
        contributor_city=parsed.counterparty_city,
        contributor_state=parsed.counterparty_state,
        contributor_zip=parsed.counterparty_zip,
        amendment_indicator="N",
        memo_text=parsed.transaction_description,
        source_record_id=source_record_id,
    )


def _ensure_phl_committee(
    conn: psycopg.Connection,
    parsed: PHLCampaignFinanceRow,
) -> UUID:
    """Resolve organization → ensure cf.committee, return committee_id."""
    canonical_name = (parsed.filer_name or "Unknown PHL Filer").strip()
    organization_id = resolve_organization_by_canonical_name(
        conn, Organization(canonical_name=canonical_name)
    )
    if organization_id is None:
        # resolve_organization_by_canonical_name only returns None when its
        # `organization` argument is None; we pass a non-None Organization so
        # the result is always a UUID. The narrowing is a Pyright affordance,
        # not a real runtime branch.
        raise RuntimeError(
            f"Failed to resolve PHL filer organization for canonical_name={canonical_name!r}"
        )
    return ensure_state_committee(
        conn,
        state=_PHL_STATE_CODE,
        native_committee_id=_phl_native_committee_id(parsed),
        organization_id=organization_id,
    )


def load_phl_relational(
    conn: psycopg.Connection,
    file_path: str | Path,
    *,
    is_expenditure: bool,
    limit: int | None = None,
) -> LoadResult:
    """Pass 2 — upsert cf.committee/filing/transaction rows from PHL JSONL.

    Idempotency: cf.committee uses ON CONFLICT (fec_committee_id) DO
    UPDATE; cf.filing uses canonical upsert keyed by filing_fec_id;
    cf.transaction uses upsert keyed by (filing_id, transaction_identifier).
    Re-running over the same JSONL inserts no new rows.

    Each row's pass-1 source_record_id is looked up via record_hash so
    every transaction carries the correct provenance link.
    """
    path = Path(file_path)
    row_limit = validated_limit(limit)
    started_at = time.monotonic()
    counts = _PHLLoadCounts()
    manages_outer = conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE

    raw_rows = _iter_jsonl_rows(path)
    if row_limit is not None:
        raw_rows = _take(raw_rows, row_limit)

    # Cache committee_id by native id within this load (avoids redundant
    # per-row ensure_state_committee work when many rows share a filer).
    committee_cache: dict[str, UUID] = {}
    # Cache filing_id by filing_fec_id so multiple rows from the same
    # PHL report consolidate into one cf.filing row.
    filing_cache: dict[str, UUID] = {}

    for raw in raw_rows:
        parsed_iter = parse_phl_carto_rows([raw], is_expenditure=is_expenditure)
        try:
            parsed = next(iter(parsed_iter))
        except StopIteration:
            counts.skipped += 1
            continue
        except Exception:  # noqa: BLE001 — Pydantic validation surfaces here
            counts.quarantined += 1
            LOGGER.exception("PHL row failed validation; quarantined")
            continue

        record_hash = compute_record_hash(_to_jsonable(raw))
        try:
            if manages_outer:
                ensure_transaction_open(conn)
            with conn.transaction():
                source_record_id = _select_source_record_id_by_hash(
                    conn, record_hash, is_expenditure=is_expenditure
                )
                if source_record_id is None:
                    # No pass-1 row → can't carry provenance; skip rather
                    # than create an orphan filing/transaction.
                    counts.skipped += 1
                    continue

                native_id = _phl_native_committee_id(parsed)
                committee_id = committee_cache.get(native_id)
                if committee_id is None:
                    committee_id = _ensure_phl_committee(conn, parsed)
                    committee_cache[native_id] = committee_id

                filing_fec_id = _phl_filing_fec_id(parsed)
                filing_id = filing_cache.get(filing_fec_id)
                if filing_id is None:
                    filing = _phl_filing(
                        parsed,
                        committee_id=committee_id,
                        source_record_id=source_record_id,
                    )
                    filing_id = upsert_filing(conn, filing)
                    filing_cache[filing_fec_id] = filing_id

                txn = _phl_transaction(
                    parsed,
                    filing_id=filing_id,
                    committee_id=committee_id,
                    source_record_id=source_record_id,
                )
                upsert_transaction(conn, txn)
                counts.inserted += 1
            commit_managed_transaction(conn, manages_outer)
        except Exception:  # noqa: BLE001
            counts.errors += 1
            LOGGER.exception(
                "Failed PHL pass-2 upsert (transaction_id=%s)", parsed.transaction_id
            )

    commit_managed_transaction(conn, manages_outer)

    return LoadResult(
        inserted=counts.inserted,
        skipped=counts.skipped,
        quarantined=counts.quarantined,
        superseded=0,
        errors=counts.errors,
        elapsed_seconds=time.monotonic() - started_at,
    )


def _select_source_record_id_by_hash(
    conn: psycopg.Connection,
    record_hash: str,
    *,
    is_expenditure: bool,
) -> UUID | None:
    """Look up the pass-1 source_record_id for the given (data_source, hash)."""
    if is_expenditure:
        data_source_id = ensure_phl_expenditures_data_source(conn)
    else:
        data_source_id = ensure_phl_contributions_data_source(conn)
    row = conn.execute(
        """
        SELECT id FROM core.source_record
        WHERE data_source_id = %s AND record_hash = %s
        LIMIT 1
        """,
        (data_source_id, record_hash),
    ).fetchone()
    return None if row is None else row[0]
