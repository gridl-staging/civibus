"""
Stub summary for /Users/stuart/parallel_development/civibus_dev/MAR18_api_graph_routes_and_property_endpoints/civibus_dev/domains/campaign_finance/ingest/bulk_stage4_loader.py.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
import logging
from pathlib import Path
from typing import Literal
from uuid import UUID

import psycopg

from domains.campaign_finance.ingest.bulk_parser import read_bulk_file
from domains.campaign_finance.ingest.bulk_transaction_loader import (
    build_filing_from_contribution,
    build_transaction_from_contribution,
    resolve_source_record_id,
)
from domains.campaign_finance.ingest.fec_lookup import find_committee_id_by_fec_id
from domains.campaign_finance.ingest.field_mapper import map_contribution_fields
from domains.campaign_finance.ingest.filing_loader import upsert_filing, upsert_transaction
from domains.campaign_finance.ingest.loader import load_contribution
from domains.campaign_finance.ingest.text_utils import normalize_optional_text

LOGGER = logging.getLogger(__name__)

_STAGE4_ROW_SAVEPOINT = "stage4_row"
_LEGACY_STAGE4_OPTION_KEYS = frozenset({"batch_size", "limit", "graph_enabled", "with_transactions"})


@dataclass(slots=True)
class LoadResult:
    inserted: int = 0
    skipped: int = 0
    quarantined: int = 0
    superseded: int = 0
    errors: int = 0


@dataclass(frozen=True, slots=True)
class Stage4LoadOptions:
    batch_size: int = 1000
    limit: int | None = None
    graph_enabled: bool = False
    with_transactions: bool = False


@dataclass(frozen=True, slots=True)
class Stage4LoadRequest:
    file_type: Literal["itcont", "itpas2"]
    path: str | Path
    data_source_id: UUID
    options: Stage4LoadOptions = field(default_factory=Stage4LoadOptions)


def _validate_batch_size(batch_size: int) -> None:
    if batch_size <= 0:
        raise ValueError("batch_size must be greater than zero")


def _commit_batch(conn: psycopg.Connection, processed_since_commit: int, batch_size: int) -> int:
    if processed_since_commit >= batch_size:
        conn.commit()
        return 0
    return processed_since_commit


def _commit_final_batch(conn: psycopg.Connection, processed_since_commit: int) -> None:
    if processed_since_commit > 0:
        conn.commit()


_normalize_optional_text = normalize_optional_text


def _resolve_stage4_options(
    options: Stage4LoadOptions | None,
    legacy_kwargs: dict[str, object],
) -> Stage4LoadOptions:
    unexpected_keys = set(legacy_kwargs) - _LEGACY_STAGE4_OPTION_KEYS
    if unexpected_keys:
        unexpected_key_list = ", ".join(sorted(unexpected_keys))
        raise TypeError(f"Unexpected Stage 4 loader options: {unexpected_key_list}")

    if options is not None and legacy_kwargs:
        raise TypeError("Use either options=Stage4LoadOptions(...) or legacy Stage 4 kwargs, not both")

    if options is not None:
        return options

    return Stage4LoadOptions(
        batch_size=int(legacy_kwargs.get("batch_size", 1000)),
        limit=legacy_kwargs.get("limit"),
        graph_enabled=bool(legacy_kwargs.get("graph_enabled", False)),
        with_transactions=bool(legacy_kwargs.get("with_transactions", False)),
    )


def _build_stage4_request(
    *,
    file_type: Literal["itcont", "itpas2"],
    path: str | Path,
    data_source_id: UUID,
    options: Stage4LoadOptions | None,
    legacy_kwargs: dict[str, object],
) -> Stage4LoadRequest:
    return Stage4LoadRequest(
        file_type=file_type,
        path=path,
        data_source_id=data_source_id,
        options=_resolve_stage4_options(options, legacy_kwargs),
    )


def _load_stage4_row_with_savepoint(
    conn: psycopg.Connection,
    *,
    request: Stage4LoadRequest,
    source_record_key: str,
    contribution_record: dict[str, object],
) -> tuple[bool, bool]:
    with conn.cursor() as cursor:
        cursor.execute(f"SAVEPOINT {_STAGE4_ROW_SAVEPOINT}")
        try:
            inserted = load_contribution(
                conn,
                request.data_source_id,
                contribution_record,
                graph_enabled=request.options.graph_enabled,
            )
            relational_inserted = False
            if request.options.with_transactions:
                relational_inserted = _load_stage4_relational_row(
                    conn,
                    data_source_id=request.data_source_id,
                    source_record_key=source_record_key,
                    contribution_record=contribution_record,
                )
        except Exception:
            cursor.execute(f"ROLLBACK TO SAVEPOINT {_STAGE4_ROW_SAVEPOINT}")
            cursor.execute(f"RELEASE SAVEPOINT {_STAGE4_ROW_SAVEPOINT}")
            raise
        cursor.execute(f"RELEASE SAVEPOINT {_STAGE4_ROW_SAVEPOINT}")
    return inserted, relational_inserted


def _load_stage4_relational_row(
    conn: psycopg.Connection,
    *,
    data_source_id: UUID,
    source_record_key: str,
    contribution_record: dict[str, object],
) -> bool:
    source_record_id = resolve_source_record_id(conn, data_source_id, source_record_key)
    if source_record_id is None:
        raise RuntimeError(
            f"source_record_id missing for data_source_id={data_source_id} source_record_key={source_record_key}"
        )

    filing = build_filing_from_contribution(
        conn,
        contribution_record,
        source_record_id=source_record_id,
    )
    filing_id = upsert_filing(conn, filing)

    transaction = build_transaction_from_contribution(
        conn,
        contribution_record,
        filing_id=filing_id,
        committee_id=filing.committee_id,
        source_record_id=source_record_id,
    )
    upsert_transaction(conn, transaction)
    return True


def _log_stage4_progress(file_type: str, processed_rows: int, load_result: LoadResult) -> None:
    if processed_rows % 10000 == 0:
        LOGGER.info(
            "Processed %s %s rows (inserted=%s skipped=%s errors=%s)",
            processed_rows,
            file_type,
            load_result.inserted,
            load_result.skipped,
            load_result.errors,
        )


def _load_stage4_contributions(
    conn: psycopg.Connection,
    *,
    request: Stage4LoadRequest,
) -> LoadResult:
    _validate_batch_size(request.options.batch_size)

    load_result = LoadResult()
    processed_rows = 0
    processed_since_commit = 0

    raw_rows: Iterable[dict[str, str | None]] = read_bulk_file(
        request.path,
        request.file_type,
        limit=request.options.limit,
    )
    for raw_row in raw_rows:
        processed_rows += 1
        processed_since_commit += 1

        contribution_record = map_contribution_fields(raw_row)

        source_record_key = _normalize_optional_text(contribution_record.get("sub_id"))
        committee_fec_id = _normalize_optional_text(contribution_record.get("committee_id"))
        if source_record_key is None or committee_fec_id is None:
            load_result.errors += 1
            LOGGER.warning(
                "Skipping %s row with missing SUB_ID or CMTE_ID: %s",
                request.file_type,
                dict(raw_row),
            )
            _log_stage4_progress(request.file_type, processed_rows, load_result)
            processed_since_commit = _commit_batch(conn, processed_since_commit, request.options.batch_size)
            continue

        contribution_record["sub_id"] = source_record_key
        contribution_record["committee_id"] = committee_fec_id

        if find_committee_id_by_fec_id(conn, committee_fec_id) is None:
            load_result.errors += 1
            LOGGER.warning(
                "Skipping %s row with unresolved CMTE_ID=%s sub_id=%s; load committees before Stage 4",
                request.file_type,
                committee_fec_id,
                source_record_key,
            )
            _log_stage4_progress(request.file_type, processed_rows, load_result)
            processed_since_commit = _commit_batch(conn, processed_since_commit, request.options.batch_size)
            continue

        try:
            row_outcome = _load_stage4_row_with_savepoint(
                conn,
                request=request,
                source_record_key=source_record_key,
                contribution_record=contribution_record,
            )
        except Exception:
            load_result.errors += 1
            LOGGER.warning(
                "Skipping %s row due to row-level load failure sub_id=%s cmte_id=%s",
                request.file_type,
                source_record_key,
                committee_fec_id,
                exc_info=True,
            )
        else:
            provenance_inserted, relational_inserted = row_outcome
            if provenance_inserted or (request.options.with_transactions and relational_inserted):
                load_result.inserted += 1
            else:
                load_result.skipped += 1

        _log_stage4_progress(request.file_type, processed_rows, load_result)
        processed_since_commit = _commit_batch(conn, processed_since_commit, request.options.batch_size)

    if processed_rows > 0:
        conn.commit()
    return load_result


def load_contributions(
    conn: psycopg.Connection,
    path: str | Path,
    *,
    data_source_id: UUID,
    options: Stage4LoadOptions | None = None,
    **legacy_kwargs: object,
) -> LoadResult:
    return _load_stage4_contributions(
        conn,
        request=_build_stage4_request(
            file_type="itcont",
            path=path,
            data_source_id=data_source_id,
            options=options,
            legacy_kwargs=legacy_kwargs,
        ),
    )


def load_committee_transactions(
    conn: psycopg.Connection,
    path: str | Path,
    *,
    data_source_id: UUID,
    options: Stage4LoadOptions | None = None,
    **legacy_kwargs: object,
) -> LoadResult:
    return _load_stage4_contributions(
        conn,
        request=_build_stage4_request(
            file_type="itpas2",
            path=path,
            data_source_id=data_source_id,
            options=options,
            legacy_kwargs=legacy_kwargs,
        ),
    )


__all__ = [
    "LoadResult",
    "Stage4LoadOptions",
    "Stage4LoadRequest",
    "_commit_batch",
    "_commit_final_batch",
    "_load_stage4_contributions",
    "_load_stage4_relational_row",
    "_validate_batch_size",
    "load_committee_transactions",
    "load_contributions",
]
