"""Federal FEC races loader.

Owns the federal race-spine build: it reads already-loaded FEC ``cn`` candidate
source records (produced by the ``federal-fec-masters`` refresh job), populates the
missing ``civic.election`` rows keyed by the general-election date, and links each
contest/candidacy to that election. FEC candidate-to-civic mapping (office
resolution, district resolution, person reuse, contest/candidacy upsert) is NOT
re-implemented here — it is reused from
``domains.campaign_finance.ingest.fec_canonical_loader`` so there is a single owner.

The election date comes from the OpenFEC ``/election-dates/`` endpoint via
``FecClient.fetch_election_dates`` when a matching general-election row is present,
falling back to the deterministic first-Tuesday-after-first-Monday date otherwise.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Sequence
from datetime import date
from typing import Protocol
from uuid import UUID

import psycopg

from core.db import try_insert_data_source
from core.db_ingest import try_insert_source_record
from core.types.python.models import (
    DataSource,
    SourceRecord,
    compute_record_hash,
    utc_now,
)
from domains.campaign_finance.ingest.bulk_stage4_loader import LoadResult
from core.db_ingest import find_person_by_identifier
from domains.campaign_finance.ingest.fec_canonical_loader import (
    federal_general_election_date,
    ingest_candidate_civic_rows,
    resolve_candidate_division,
    validate_candidate_row,
)
from domains.campaign_finance.ingest.fec_client import FecApiError
from domains.campaign_finance.ingest.text_utils import normalize_optional_text
from domains.civics.ingest import upsert_election
from domains.civics.types.models import Election

LOGGER = logging.getLogger(__name__)

FEDERAL_FEC_RACES_DATA_SOURCE_NAME = "FEC Federal Races"
_FEDERAL_FEC_RACES_DATA_SOURCE_DOMAIN = "civics"
_FEDERAL_FEC_RACES_DATA_SOURCE_JURISDICTION = "federal/fec"
_FEDERAL_FEC_RACES_DATA_SOURCE_URL = "https://api.open.fec.gov/v1/election-dates/"

# OpenFEC ``election_type_id`` value for a general election.
_GENERAL_ELECTION_TYPE_ID = "G"


class ElectionDatesClient(Protocol):
    """Structural contract for the FEC election-dates dependency the loader needs."""

    def fetch_election_dates(
        self,
        *,
        office: str | None = ...,
        state: str | None = ...,
        district: str | None = ...,
        election_year: int | None = ...,
        per_page: int = ...,
        limit: int | None = ...,
    ) -> list[dict]: ...


def _select_races_data_source_id(conn: psycopg.Connection) -> UUID | None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT id
            FROM core.data_source
            WHERE domain = %s
              AND jurisdiction = %s
              AND name = %s
            LIMIT 1
            """,
            (
                _FEDERAL_FEC_RACES_DATA_SOURCE_DOMAIN,
                _FEDERAL_FEC_RACES_DATA_SOURCE_JURISDICTION,
                FEDERAL_FEC_RACES_DATA_SOURCE_NAME,
            ),
        )
        row = cursor.fetchone()
    return None if row is None else row[0]


def ensure_federal_fec_races_data_source(conn: psycopg.Connection) -> UUID:
    """Return the federal-races provenance data source id, creating it when absent.

    Concurrency-safe: uses ``try_insert_data_source`` (ON CONFLICT DO NOTHING) so
    two concurrent refresh workers cannot both race past the initial existence
    check and abort on the unique ``core.data_source(domain, jurisdiction, name)``
    key. When the conflict path fires, the winner's id is re-selected instead.
    """
    existing_id = _select_races_data_source_id(conn)
    if existing_id is not None:
        return existing_id

    data_source = DataSource(
        domain=_FEDERAL_FEC_RACES_DATA_SOURCE_DOMAIN,
        jurisdiction=_FEDERAL_FEC_RACES_DATA_SOURCE_JURISDICTION,
        name=FEDERAL_FEC_RACES_DATA_SOURCE_NAME,
        source_url=_FEDERAL_FEC_RACES_DATA_SOURCE_URL,
        source_format="json",
        license="public_domain",
        update_frequency="weekly",
    )
    inserted_id = try_insert_data_source(conn, data_source)
    if inserted_id is not None:
        return inserted_id

    winner_id = _select_races_data_source_id(conn)
    if winner_id is not None:
        return winner_id

    raise RuntimeError(
        f"{FEDERAL_FEC_RACES_DATA_SOURCE_NAME} insert reported a conflict, but the existing row could not be selected"
    )


def iter_cn_source_records(conn: psycopg.Connection, cn_data_source_id: UUID) -> Iterator[dict[str, object]]:
    """Yield the raw ``cn`` candidate-master fields for a FEC bulk data source.

    Reads the active (non-superseded) ``cn:`` keyed source records produced by the
    ``federal-fec-masters`` job, so the races loader consumes existing FEC data
    rather than re-parsing bulk files.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT raw_fields
            FROM core.source_record
            WHERE data_source_id = %s
              AND source_record_key LIKE 'cn:%%'
              AND superseded_by IS NULL
            ORDER BY source_record_key
            """,
            (cn_data_source_id,),
        )
        for (raw_fields,) in cursor.fetchall():
            yield raw_fields


def _resolve_general_election_date(payload: Sequence[dict], year: int) -> date:
    """Resolve the regular November general-election date for ``year``.

    Prefers the OpenFEC general-election (``G``) entry for the year but chooses the
    *regular* November general over an earlier special general: a payload date equal
    to the computed federal general date wins, otherwise the latest ``G`` date for
    the year (specials for vacated seats fall earlier in the cycle). Falls back to
    the deterministic computed date when the payload has no usable general entry.
    """
    computed_election_date = federal_general_election_date(year)
    general_election_dates: list[date] = []
    for entry in payload:
        if str(entry.get("election_type_id", "")).upper() != _GENERAL_ELECTION_TYPE_ID:
            continue
        raw_election_date = entry.get("election_date")
        if not raw_election_date:
            continue
        try:
            parsed_election_date = date.fromisoformat(str(raw_election_date))
        except ValueError:
            continue
        if parsed_election_date.year == year:
            general_election_dates.append(parsed_election_date)

    if not general_election_dates:
        return computed_election_date
    if computed_election_date in general_election_dates:
        return computed_election_date
    return max(general_election_dates)


def _prior_resolved_election_date(
    conn: psycopg.Connection,
    *,
    races_data_source_id: UUID,
    source_record_key: str,
) -> date | None:
    """Return the ``resolved_election_date`` of the active races source record, if any.

    Read before superseding so we know the election date a prior run bound this
    candidate-year to. ``None`` when there is no prior run or the stored value is
    absent/unparseable.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT raw_fields ->> 'resolved_election_date'
            FROM core.source_record
            WHERE data_source_id = %s
              AND source_record_key = %s
              AND superseded_by IS NULL
            """,
            (races_data_source_id, source_record_key),
        )
        row = cursor.fetchone()
    if row is None or row[0] is None:
        return None
    try:
        return date.fromisoformat(row[0])
    except ValueError:
        return None


def _delete_superseded_race_chain(
    conn: psycopg.Connection,
    *,
    person_id: UUID,
    office_id: UUID,
    electoral_division_id: UUID | None,
    old_election_date: date,
) -> None:
    """Drop this candidate's stale race rows left at a prior election date.

    ``civic.election``/``civic.contest`` are keyed by ``election_date``, so a rerun
    that resolves a different general-election date lands the candidate on a fresh
    contest/election via the natural-key upserts while the old-date rows remain. We
    let those upserts converge the new chain (they are the single owner of the
    coarse election, which is globally unique per date, so a manual date move would
    collide) and here we remove the orphaned old-date chain instead.

    The old contest is garbage-collected only once its last candidacy leaves, and
    the old election only once its last contest leaves, so contests/elections shared
    by other candidates in the same seat/cycle survive until genuinely empty.

    Whenever a civic row is removed its ``core.entity_source`` provenance links are
    removed in the same step so no source record points at a deleted entity id.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, election_id
            FROM civic.contest
            WHERE office_id = %s
              AND electoral_division_id IS NOT DISTINCT FROM %s
              AND election_date = %s
              AND election_type = 'general'
            """,
            (office_id, electoral_division_id, old_election_date),
        )
        old_contest = cursor.fetchone()
        if old_contest is None:
            return
        old_contest_id, old_election_id = old_contest

        cursor.execute(
            "DELETE FROM civic.candidacy WHERE person_id = %s AND contest_id = %s RETURNING id",
            (person_id, old_contest_id),
        )
        _delete_entity_source_links(cursor, "candidacy", [row[0] for row in cursor.fetchall()])

        cursor.execute(
            "SELECT 1 FROM civic.candidacy WHERE contest_id = %s LIMIT 1",
            (old_contest_id,),
        )
        if cursor.fetchone() is not None:
            return
        cursor.execute("DELETE FROM civic.contest WHERE id = %s", (old_contest_id,))
        _delete_entity_source_links(cursor, "contest", [old_contest_id])

        if old_election_id is None:
            return
        cursor.execute(
            "SELECT 1 FROM civic.contest WHERE election_id = %s LIMIT 1",
            (old_election_id,),
        )
        if cursor.fetchone() is None:
            cursor.execute("DELETE FROM civic.election WHERE id = %s", (old_election_id,))
            _delete_entity_source_links(cursor, "election", [old_election_id])


def _delete_entity_source_links(
    cursor: psycopg.Cursor,
    entity_type: str,
    entity_ids: Sequence[UUID],
) -> None:
    """Remove ``core.entity_source`` rows for civic entities just deleted.

    A deleted candidacy/contest/election leaves its provenance links dangling at an
    entity id that no longer exists; drop them so source-record lookups never resolve
    to a pruned entity.
    """
    if not entity_ids:
        return
    cursor.execute(
        "DELETE FROM core.entity_source WHERE entity_type = %s AND entity_id = ANY(%s)",
        (entity_type, list(entity_ids)),
    )


class _ElectionDateResolver:
    """Fetch and cache the OpenFEC election-date payload per election year.

    Federal general-election dates are nationally uniform, so the payload is keyed
    by year alone rather than per seat — this bounds the live API calls to one per
    distinct election year instead of one per (office, state, district). A rate
    limit or transport failure falls back to the deterministic computed date rather
    than aborting the whole federal load.
    """

    def __init__(self, election_client: ElectionDatesClient) -> None:
        self._election_client = election_client
        self._payload_cache: dict[int, list[dict]] = {}

    def payload_for(self, *, year: int) -> list[dict]:
        if year not in self._payload_cache:
            try:
                self._payload_cache[year] = self._election_client.fetch_election_dates(
                    election_year=year,
                )
            except FecApiError as error:
                LOGGER.warning(
                    "election-dates fetch failed for %s; using computed general date: %s",
                    year,
                    error,
                )
                self._payload_cache[year] = []
        return self._payload_cache[year]


def load_federal_fec_races(
    conn: psycopg.Connection,
    *,
    races_data_source_id: UUID,
    cn_data_source_id: UUID,
    election_client: ElectionDatesClient,
    min_election_year: int,
    batch_size: int = 1000,
) -> LoadResult:
    """Load recent federal races from existing FEC ``cn`` source data.

    For each active ``cn`` candidate record with ``candidate_election_year`` at or
    after ``min_election_year``, this populates the ``civic.election`` row for that
    general-election date and reuses the canonical FEC candidate-to-civic mapping to
    upsert the person, electoral division, contest (linked to the election), and
    candidacy. ``candidate_status`` from the Stage 1 mapper output is preserved in
    ``civic.candidacy.status``. Work is committed every ``batch_size`` inserted rows
    so a failure late in a bulk federal run does not discard all prior progress.
    """
    if batch_size <= 0:
        raise ValueError("batch_size must be greater than zero")

    result = LoadResult()
    date_resolver = _ElectionDateResolver(election_client)
    processed_since_commit = 0

    for raw_row in iter_cn_source_records(conn, cn_data_source_id):
        validated = validate_candidate_row(raw_row)
        if validated is None:
            result.errors += 1
            continue
        if validated.election_year < min_election_year:
            continue

        payload = date_resolver.payload_for(year=validated.election_year)
        election_date = _resolve_general_election_date(payload, validated.election_year)

        source_record_key = f"fec_races:{validated.fec_candidate_id}:{validated.election_year}"
        prior_election_date = _prior_resolved_election_date(
            conn,
            races_data_source_id=races_data_source_id,
            source_record_key=source_record_key,
        )
        raw_fields: dict[str, object] = {
            **raw_row,
            "resolved_election_date": election_date.isoformat(),
            "election_dates": payload,
        }
        source_record_id = try_insert_source_record(
            conn,
            SourceRecord(
                data_source_id=races_data_source_id,
                source_record_key=source_record_key,
                raw_fields=raw_fields,
                pull_date=utc_now(),
                record_hash=compute_record_hash(raw_fields),
            ),
        )
        if source_record_id is None:
            result.skipped += 1
            continue

        # upsert_election records the election entity_source link internally.
        election_id = upsert_election(
            conn,
            Election(
                jurisdiction_scope="federal",
                election_date=election_date,
                election_type="general",
                source_record_id=source_record_id,
            ),
        )

        candidate_status = normalize_optional_text(validated.mapped.get("candidate_status"))
        ingest_candidate_civic_rows(
            conn,
            validated,
            source_record_id,
            election_id=election_id,
            election_date=election_date,
            candidacy_status=candidate_status,
        )

        # A rerun that resolved a different date leaves the candidate's prior
        # election-dated chain orphaned; the upserts above converged the new chain,
        # so drop the stale old-date rows instead of duplicating the race spine.
        if prior_election_date is not None and prior_election_date != election_date:
            person_id = find_person_by_identifier(conn, "fec_candidate_id", validated.fec_candidate_id)
            if person_id is not None:
                _delete_superseded_race_chain(
                    conn,
                    person_id=person_id,
                    office_id=validated.office_id,
                    electoral_division_id=resolve_candidate_division(conn, validated),
                    old_election_date=prior_election_date,
                )

        result.inserted += 1
        processed_since_commit += 1
        if processed_since_commit >= batch_size:
            conn.commit()
            processed_since_commit = 0

    if processed_since_commit > 0:
        conn.commit()
    return result
