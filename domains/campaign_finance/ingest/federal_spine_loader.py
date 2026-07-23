"""Federal congress-spine loader.

Implements ``load_federal_spine()`` — Stage 3's primary deliverable. Materializes
exactly one ``core.person`` per current federal official (House + Senate +
delegates + President + VP), one current ``civic.officeholding`` per person, and
authoritatively repoints every matching ``cf.candidate.person_id`` by FEC
candidate ID — for ALL FIVE buckets — so member money attaches to the spine
person.

House and Senate rows flow directly into the existing
``load_federal_house_officeholders`` / ``load_federal_senate_officeholders``
owners — NOT forked. Delegate / President / VP each get a small dedicated path
modeled on the same upsert idioms (source_record → person → officeholding).

The convergence UPDATE

    UPDATE cf.candidate
    SET    person_id = %s
    WHERE  fec_candidate_id = ANY(%s)
      AND  (person_id IS NULL OR person_id <> %s)

is idempotent by construction: re-running cannot create duplicates or alter
values once every matching ``cf.candidate`` row already points at the spine
person. ``cf.candidate.updated_at`` is maintained by the existing
``trg_candidate_updated_at`` trigger (``domains/campaign_finance/schema/tables.sql``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from uuid import UUID

import psycopg

from core.db import merge_person_identifiers
from core.db_ingest import find_person_by_identifier
from core.types.python.models import DataSource, ValidDateRange
from domains.civics.types.models import Officeholding
from domains.campaign_finance.ingest.bulk_stage4_loader import LoadResult
from domains.campaign_finance.ingest.congress_legislators_adapter import (
    AdaptedLegislators,
    HistoricalPredecessors,
)
from domains.campaign_finance.ingest.federal_officeholder_loader import (
    OFFICE_US_HOUSE_DELEGATE,
    OFFICE_US_PRESIDENT,
    OFFICE_US_VICE_PRESIDENT,
    _OFFICE_US_HOUSE,
    _resolve_house_division,
    load_federal_house_officeholders,
    load_federal_senate_officeholders,
)
from domains.campaign_finance.ingest.fec_lookup import (
    resolve_federal_officeholder_fec_candidate_ids,
)
from domains.campaign_finance.ingest.officeholder_contact import (
    insert_officeholder_source_record,
    resolve_or_create_person_by_identifier,
    run_officeholder_row,
)
from domains.campaign_finance.jurisdictions.states.load_utils import ensure_data_source
from domains.civics.ingest import upsert_officeholding

LOGGER = logging.getLogger(__name__)


# Mapping from adapter executive-row type strings to canonical office UUIDs.
# Delegate is included here so the same pure helper resolves the third
# "non-chamber" bucket alongside president / vice_president.
OFFICE_BY_EXECUTIVE_TYPE: dict[str, UUID] = {
    "delegate": OFFICE_US_HOUSE_DELEGATE,
    "president": OFFICE_US_PRESIDENT,
    "vice_president": OFFICE_US_VICE_PRESIDENT,
}


@dataclass(slots=True)
class _BucketResult:
    inserted: int = 0
    skipped: int = 0
    errors: int = 0
    converged_candidates: int = 0


@dataclass(slots=True)
class SpineLoadResult:
    """Per-bucket counters returned by :func:`load_federal_spine`."""

    house: _BucketResult = field(default_factory=_BucketResult)
    senate: _BucketResult = field(default_factory=_BucketResult)
    delegate: _BucketResult = field(default_factory=_BucketResult)
    president: _BucketResult = field(default_factory=_BucketResult)
    vice_president: _BucketResult = field(default_factory=_BucketResult)

    @property
    def inserted(self) -> int:
        return sum(bucket.inserted for bucket in self._buckets)

    @property
    def skipped(self) -> int:
        return sum(bucket.skipped for bucket in self._buckets)

    @property
    def quarantined(self) -> int:
        return 0

    @property
    def superseded(self) -> int:
        return 0

    @property
    def errors(self) -> int:
        return sum(bucket.errors for bucket in self._buckets)

    @property
    def converged_candidates(self) -> int:
        return sum(bucket.converged_candidates for bucket in self._buckets)

    @property
    def _buckets(self) -> tuple[_BucketResult, ...]:
        return (self.house, self.senate, self.delegate, self.president, self.vice_president)


# ---------------------------------------------------------------------------
# Data-source provenance for spine ingest
# ---------------------------------------------------------------------------

FEDERAL_SPINE_DATA_SOURCE_NAME = "US Congress Legislators (unitedstates/congress-legislators)"


def ensure_federal_spine_data_source(conn: psycopg.Connection) -> UUID:
    """Return the data_source id used for spine ingest provenance.

    Spine ingest records provenance against a dedicated DataSource so it is
    distinct from the per-chamber House Clerk / Senate XML directories owned by
    ``run_federal_officeholder_refresh``.
    """
    return ensure_data_source(
        conn,
        DataSource(
            domain="campaign_finance",
            jurisdiction="federal/congress",
            name=FEDERAL_SPINE_DATA_SOURCE_NAME,
            source_url="https://github.com/unitedstates/congress-legislators",
        ),
    )


# ---------------------------------------------------------------------------
# Convergence helper
# ---------------------------------------------------------------------------


def _converge_spine_identity(
    conn: psycopg.Connection,
    *,
    person_id: UUID,
    fec_ids: list[str],
    bioguide_id: str | None = None,
    wikidata_id: str | None = None,
    govtrack_id: str | None = None,
) -> int:
    """Enrich identifiers on the spine person and repoint matching cf.candidate rows.

    Returns the number of cf.candidate rows updated by the convergence UPDATE.

    The UPDATE is idempotent: when every matching candidate row already points
    at ``person_id``, no rows are touched. ``cf.candidate.updated_at`` is set by
    the existing ``trg_candidate_updated_at`` trigger so we do not set it here.
    """
    normalized_fec_ids = resolve_federal_officeholder_fec_candidate_ids(
        bioguide_id=bioguide_id,
        upstream_candidate_ids=fec_ids or [],
    )
    identifier_payload: dict[str, Any] = {}
    if normalized_fec_ids:
        identifier_payload["fec_candidate_id"] = normalized_fec_ids[0]
        identifier_payload["fec_candidate_ids"] = normalized_fec_ids
    if wikidata_id:
        identifier_payload["wikidata_id"] = wikidata_id
    if govtrack_id:
        identifier_payload["govtrack_id"] = govtrack_id
    if identifier_payload:
        merge_person_identifiers(conn, person_id=person_id, identifiers=identifier_payload)

    if not normalized_fec_ids:
        return 0

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE cf.candidate
            SET person_id = %s
            WHERE fec_candidate_id = ANY(%s)
              AND (person_id IS NULL OR person_id <> %s)
            """,
            (person_id, normalized_fec_ids, person_id),
        )
        return cur.rowcount or 0


def _jsonable_raw_row(row: dict[str, Any]) -> dict[str, Any]:
    """Strip non-JSON-safe values (UUIDs, lists) from the row before persisting as raw_fields.

    ``compute_record_hash`` requires every value be a JSON-safe scalar. The
    adapter's delegate row carries ``office_id`` as a UUID (a convenience for
    downstream consumers); the spine loader does not consume that field —
    delegate office is the constant OFFICE_US_HOUSE_DELEGATE.
    """
    safe: dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, UUID):
            safe[key] = str(value)
        elif isinstance(value, list):
            safe[key] = ",".join(str(item) for item in value)
        else:
            safe[key] = value
    return safe


def _row_identity_lookup(
    conn: psycopg.Connection,
    *,
    bioguide_id: str,
    govtrack_id: str | None = None,
    wikidata_id: str | None = None,
) -> UUID | None:
    """Resolve the spine person from any identifier known to be present.

    Bioguide is the primary key for currently-serving members; only the VP-
    without-bioguide path needs the govtrack / wikidata fallbacks.
    """
    if bioguide_id:
        person_id = find_person_by_identifier(conn, "bioguide_id", bioguide_id)
        if person_id is not None:
            return person_id
    if govtrack_id:
        person_id = find_person_by_identifier(conn, "govtrack_id", govtrack_id)
        if person_id is not None:
            return person_id
    if wikidata_id:
        return find_person_by_identifier(conn, "wikidata_id", wikidata_id)
    return None


# ---------------------------------------------------------------------------
# Chamber paths — reuse existing loaders unchanged, then converge.
# ---------------------------------------------------------------------------


def _converge_chamber_rows(
    conn: psycopg.Connection,
    rows: list[dict[str, Any]],
    *,
    bucket: _BucketResult,
) -> None:
    """For each row that the chamber loaders just persisted, run convergence."""
    for row in rows:
        bioguide_id = (row.get("bioguide_id") or "").strip()
        if not bioguide_id:
            continue
        fec_ids = list(row.get("fec_ids") or [])
        person_id = _row_identity_lookup(
            conn,
            bioguide_id=bioguide_id,
            govtrack_id=row.get("govtrack_id"),
            wikidata_id=row.get("wikidata_id"),
        )
        if person_id is None:
            LOGGER.warning(
                "Skipping convergence for %s: spine person not found after chamber load",
                bioguide_id,
            )
            continue
        bucket.converged_candidates += _converge_spine_identity(
            conn,
            person_id=person_id,
            fec_ids=fec_ids,
            bioguide_id=bioguide_id,
            wikidata_id=row.get("wikidata_id"),
            govtrack_id=row.get("govtrack_id"),
        )


def _record_chamber_bucket(result: LoadResult, bucket: _BucketResult) -> None:
    bucket.inserted += result.inserted
    bucket.skipped += result.skipped
    bucket.errors += result.errors


# ---------------------------------------------------------------------------
# Delegate / executive paths — small, mirror the chamber loader idioms.
# ---------------------------------------------------------------------------


def _load_delegate_row(
    conn: psycopg.Connection,
    row: dict[str, Any],
    *,
    data_source_id: UUID,
    bucket: _BucketResult,
) -> None:
    """Insert one delegate as person + congressional-district officeholding."""

    def _process_row() -> None:
        bioguide_id = (row.get("bioguide_id") or "").strip()
        if not bioguide_id:
            # Without a bioguide we cannot anchor identity; skip.
            bucket.skipped += 1
            return
        first_name = (row.get("first_name") or "").strip()
        last_name = (row.get("last_name") or "").strip()
        state = (row.get("state") or "").strip()
        district = (row.get("district") or "").strip()

        source_record_id = insert_officeholder_source_record(
            conn,
            data_source_id=data_source_id,
            source_record_key=f"delegate:{bioguide_id}",
            raw_row=_jsonable_raw_row(row),
        )
        row_inserted = source_record_id is not None
        person_id = resolve_or_create_person_by_identifier(
            conn,
            identifier_key="bioguide_id",
            identifier_value=bioguide_id,
            first_name=first_name,
            last_name=last_name,
            source_record_id=source_record_id,
        )
        division_id = _resolve_house_division(conn, state, district) if state and district else None
        upsert_officeholding(
            conn,
            Officeholding(
                person_id=person_id,
                office_id=OFFICE_US_HOUSE_DELEGATE,
                electoral_division_id=division_id,
                holder_status="elected",
                valid_period=ValidDateRange(),
                date_precision="year",
                source_record_id=source_record_id,
            ),
        )

        fec_ids = list(row.get("fec_ids") or [])
        if fec_ids:
            bucket.converged_candidates += _converge_spine_identity(
                conn,
                person_id=person_id,
                fec_ids=fec_ids,
                bioguide_id=bioguide_id,
                wikidata_id=row.get("wikidata_id"),
                govtrack_id=row.get("govtrack_id"),
            )

        if row_inserted:
            bucket.inserted += 1
        else:
            bucket.skipped += 1

    if not run_officeholder_row(
        conn,
        logger=LOGGER,
        failure_message="Error ingesting federal delegate row: %s",
        raw_row=row,
        operation=_process_row,
    ):
        bucket.errors += 1


def _load_executive_row(
    conn: psycopg.Connection,
    row: dict[str, Any],
    *,
    office_type: str,
    data_source_id: UUID,
    bucket: _BucketResult,
) -> None:
    """Insert one executive (president or vp) as person + nationwide officeholding."""
    office_id = OFFICE_BY_EXECUTIVE_TYPE[office_type]
    source_record_key_prefix = "president" if office_type == "president" else "vp"

    def _process_row() -> None:
        bioguide_id = (row.get("bioguide_id") or "").strip()
        govtrack_id = (row.get("govtrack_id") or "").strip() or None
        wikidata_id = (row.get("wikidata_id") or "").strip() or None
        first_name = (row.get("first_name") or "").strip()
        last_name = (row.get("last_name") or "").strip()

        # Identity anchor: bioguide preferred; for the VP-without-bioguide
        # path, fall back to govtrack_id then wikidata_id.
        identifier_key: str
        identifier_value: str
        if bioguide_id:
            identifier_key = "bioguide_id"
            identifier_value = bioguide_id
        elif govtrack_id:
            identifier_key = "govtrack_id"
            identifier_value = govtrack_id
        elif wikidata_id:
            identifier_key = "wikidata_id"
            identifier_value = wikidata_id
        else:
            bucket.skipped += 1
            return

        source_record_id = insert_officeholder_source_record(
            conn,
            data_source_id=data_source_id,
            source_record_key=f"{source_record_key_prefix}:{identifier_value}",
            raw_row=_jsonable_raw_row(row),
        )
        row_inserted = source_record_id is not None
        person_id = resolve_or_create_person_by_identifier(
            conn,
            identifier_key=identifier_key,
            identifier_value=identifier_value,
            first_name=first_name,
            last_name=last_name,
            source_record_id=source_record_id,
        )
        upsert_officeholding(
            conn,
            Officeholding(
                person_id=person_id,
                office_id=office_id,
                electoral_division_id=None,
                holder_status="elected",
                valid_period=ValidDateRange(),
                date_precision="year",
                source_record_id=source_record_id,
            ),
        )

        fec_ids = list(row.get("fec_ids") or [])
        if fec_ids or wikidata_id or govtrack_id:
            bucket.converged_candidates += _converge_spine_identity(
                conn,
                person_id=person_id,
                fec_ids=fec_ids,
                bioguide_id=bioguide_id,
                wikidata_id=wikidata_id,
                govtrack_id=govtrack_id,
            )

        if row_inserted:
            bucket.inserted += 1
        else:
            bucket.skipped += 1

    if not run_officeholder_row(
        conn,
        logger=LOGGER,
        failure_message=f"Error ingesting federal {office_type} row: %s",
        raw_row=row,
        operation=_process_row,
    ):
        bucket.errors += 1


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def load_federal_spine(
    conn: psycopg.Connection,
    adapted: AdaptedLegislators,
    *,
    data_source_id: UUID,
) -> SpineLoadResult:
    """Materialize the federal officeholder spine and converge cf.candidate money.

    Parameters
    ----------
    conn:
        Open psycopg connection. The caller controls commit boundaries; this
        function does not commit on its own.
    adapted:
        Bucketed rows from :func:`adapt_legislators_yaml`.
    data_source_id:
        Provenance handle returned by :func:`ensure_federal_spine_data_source`.
    """
    result = SpineLoadResult()

    house_result = load_federal_house_officeholders(conn, adapted.house_rows, data_source_id=data_source_id)
    _record_chamber_bucket(house_result, result.house)
    _converge_chamber_rows(conn, adapted.house_rows, bucket=result.house)

    senate_result = load_federal_senate_officeholders(conn, adapted.senate_rows, data_source_id=data_source_id)
    _record_chamber_bucket(senate_result, result.senate)
    _converge_chamber_rows(conn, adapted.senate_rows, bucket=result.senate)

    for delegate_row in adapted.delegate_rows:
        _load_delegate_row(
            conn,
            delegate_row,
            data_source_id=data_source_id,
            bucket=result.delegate,
        )

    for president_row in adapted.president_rows:
        _load_executive_row(
            conn,
            president_row,
            office_type="president",
            data_source_id=data_source_id,
            bucket=result.president,
        )

    for vp_row in adapted.vp_rows:
        _load_executive_row(
            conn,
            vp_row,
            office_type="vice_president",
            data_source_id=data_source_id,
            bucket=result.vice_president,
        )

    return result


def load_vacancy_predecessors(
    conn: psycopg.Connection,
    predecessors: HistoricalPredecessors,
    *,
    data_source_id: UUID,
) -> int:
    """Create closed officeholding records for vacant House seats.

    Returns the number of predecessor officeholdings upserted.
    """
    count = 0
    for pred in predecessors.house_predecessors:
        if not pred.bioguide_id:
            continue
        source_record_id = insert_officeholder_source_record(
            conn,
            data_source_id=data_source_id,
            source_record_key=f"vacancy-predecessor:{pred.bioguide_id}",
            raw_row={
                "bioguide_id": pred.bioguide_id,
                "first_name": pred.first_name,
                "last_name": pred.last_name,
                "state": pred.state,
                "district": pred.district,
                "party": pred.party,
                "term_end": pred.term_end,
            },
        )
        person_id = resolve_or_create_person_by_identifier(
            conn,
            identifier_key="bioguide_id",
            identifier_value=pred.bioguide_id,
            first_name=pred.first_name,
            last_name=pred.last_name,
            source_record_id=source_record_id,
        )
        division_id = _resolve_house_division(conn, pred.state, pred.district)
        end_date = date.fromisoformat(pred.term_end)
        upsert_officeholding(
            conn,
            Officeholding(
                person_id=person_id,
                office_id=_OFFICE_US_HOUSE,
                electoral_division_id=division_id,
                holder_status="former",
                valid_period=ValidDateRange(end_date=end_date),
                date_precision="day",
                source_record_id=source_record_id,
            ),
        )
        if pred.fec_ids:
            _converge_spine_identity(
                conn,
                person_id=person_id,
                fec_ids=pred.fec_ids,
                wikidata_id=pred.wikidata_id or None,
                govtrack_id=pred.govtrack_id or None,
            )
        count += 1
        LOGGER.info(
            "Vacancy predecessor: %s %s (%s-%s), term ended %s",
            pred.first_name,
            pred.last_name,
            pred.state,
            pred.district,
            pred.term_end,
        )
    return count


__all__ = [
    "FEDERAL_SPINE_DATA_SOURCE_NAME",
    "OFFICE_BY_EXECUTIVE_TYPE",
    "SpineLoadResult",
    "_BucketResult",
    "ensure_federal_spine_data_source",
    "load_federal_spine",
    "load_vacancy_predecessors",
]
