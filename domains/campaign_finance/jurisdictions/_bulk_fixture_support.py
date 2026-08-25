"""Shared observation, CSV copying, and leak-proof cleanup for loader fixtures.

Single owner of the common support every jurisdiction's bounded-commit specimen needs:
make a per-run fixture CSV copy, read what a *different* database connection committed,
delete every row one fixture wrote, and prove the deletion left nothing behind.

NY, GA, WA, SF, and PA fixtures all write the same row shapes — source records, filings,
transactions, provenance links, and the ``core.person`` / ``core.organization`` /
``core.address`` rows behind them — so they share one implementation here instead of
copies that drift. Only the per-jurisdiction fixture writers stay local, because only
they know which fields carry their source's identities.

Cleanup is scoped to one fixture's own synthetic identities (its source-record keys and
its synthetic committee id), never to a data source or a jurisdiction: every
``ensure_*_data_source`` resolves the canonical production data source, which real rows
and concurrently running fixtures share.
"""

from __future__ import annotations

import csv
from collections import Counter
from collections.abc import Callable, Sequence
from contextlib import ExitStack
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, NamedTuple, Protocol, TypeVar
from uuid import UUID

import psycopg

from core.db import get_connection
from domains.campaign_finance.ingest.filing_loader import generate_synthetic_committee_id

if TYPE_CHECKING:  # pytest is a test-time dependency; this module lives in a shipped package.
    import pytest

# The entity footprint of a fixture that has never been loaded, and the footprint its
# cleanup must restore.
NO_ENTITY_ROWS = {"person": 0, "organization": 0, "address": 0, "committee": 0}

# Entity rows are deleted only when nothing references them any more, so a row the
# fixture merely reused (real jurisdiction provenance, or a concurrently running
# fixture) survives. person and organization are deleted before address: both can
# reference an address through primary_address_id, so the address is only unreferenced
# once they are gone.
_UNREFERENCED_ENTITY_DELETES: dict[str, str] = {
    "person": """
        DELETE FROM core.person p
        WHERE p.id = ANY(%s)
          AND NOT EXISTS (
              SELECT 1 FROM core.entity_source es
              WHERE es.entity_type = 'person' AND es.entity_id = p.id
          )
          AND NOT EXISTS (
              SELECT 1 FROM core.entity_address ea
              WHERE ea.entity_type = 'person' AND ea.entity_id = p.id
          )
    """,
    "organization": """
        DELETE FROM core.organization o
        WHERE o.id = ANY(%s)
          AND NOT EXISTS (
              SELECT 1 FROM core.entity_source es
              WHERE es.entity_type = 'organization' AND es.entity_id = o.id
          )
          AND NOT EXISTS (
              SELECT 1 FROM core.entity_address ea
              WHERE ea.entity_type = 'organization' AND ea.entity_id = o.id
          )
          AND NOT EXISTS (SELECT 1 FROM cf.committee c WHERE c.organization_id = o.id)
    """,
    "address": """
        DELETE FROM core.address a
        WHERE a.id = ANY(%s)
          AND NOT EXISTS (
              SELECT 1 FROM core.entity_source es
              WHERE es.entity_type = 'address' AND es.entity_id = a.id
          )
          AND NOT EXISTS (SELECT 1 FROM core.entity_address ea WHERE ea.address_id = a.id)
          AND NOT EXISTS (SELECT 1 FROM core.person p WHERE p.primary_address_id = a.id)
          AND NOT EXISTS (SELECT 1 FROM core.organization o WHERE o.primary_address_id = a.id)
    """,
}

_FixtureT = TypeVar("_FixtureT", bound="SuffixScopedBulkFixture")


def read_sample_csv(path: Path) -> list[dict[str, str | None]]:
    """Read a fixture CSV into ordered row dicts, preserving its header order."""
    with path.open(encoding="utf-8", newline="") as csv_file:
        return list(csv.DictReader(csv_file))


def write_csv(path: Path, rows: list[dict[str, str | None]]) -> None:
    """Write rows back out with the first row's header order, blanking None values."""
    with path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=list(rows[0]))
        writer.writeheader()
        for row in rows:
            writer.writerow({key: "" if value is None else value for key, value in row.items()})


class ScopedBulkFixture(Protocol):
    """A bulk fixture that can name every row it wrote."""

    source_record_keys: list[str]

    @property
    def committee_fec_id(self) -> str: ...


class SuffixScopedBulkFixture(ScopedBulkFixture, Protocol):
    """A bulk fixture whose every written identity also carries one per-run token.

    ``run_suffix`` is what makes the entity footprint observable *by identity* rather
    than by provenance link: cleanup deletes the links, so a link-scoped count would
    read zero however many entity rows leaked.
    """

    run_suffix: str


class BulkFixture(NamedTuple):
    """One jurisdiction bulk input and the synthetic identities it writes."""

    input_path: Path
    jurisdiction: str
    run_suffix: str
    committee_native_id: str
    source_record_keys: list[str]

    @property
    def committee_fec_id(self) -> str:
        return generate_synthetic_committee_id(self.jurisdiction, self.committee_native_id)


def bulk_fixture_row_counts(fixture: ScopedBulkFixture) -> tuple[int, int]:
    """Return (source_record_count, transaction_count) from an independent connection.

    Independent because the point of every caller is to see what a *different*
    connection committed; reading through the loader's own connection would report
    uncommitted work as durable.
    """
    observer_conn = get_connection()
    try:
        with observer_conn.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM core.source_record WHERE source_record_key = ANY(%s)",
                (fixture.source_record_keys,),
            )
            source_record_count = cursor.fetchone()[0]
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM cf.transaction
                WHERE source_record_id IN (
                    SELECT id FROM core.source_record WHERE source_record_key = ANY(%s)
                )
                """,
                (fixture.source_record_keys,),
            )
            transaction_count = cursor.fetchone()[0]
        return source_record_count, transaction_count
    finally:
        observer_conn.close()


def bulk_fixture_contributor_person_ids(fixture: ScopedBulkFixture) -> list[UUID | None]:
    """Return contributor person ids for fixture transactions, in source-key order."""
    observer_conn = get_connection()
    try:
        with observer_conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT transaction.contributor_person_id
                FROM unnest(%s::text[]) WITH ORDINALITY AS fixture_key(source_record_key, ordinal)
                JOIN core.source_record AS source_record USING (source_record_key)
                JOIN cf.transaction AS transaction
                  ON transaction.source_record_id = source_record.id
                ORDER BY fixture_key.ordinal
                """,
                (fixture.source_record_keys,),
            )
            return [row[0] for row in cursor.fetchall()]
    finally:
        observer_conn.close()


def _caller_visible_source_record_count(conn: psycopg.Connection, fixture: ScopedBulkFixture) -> int:
    """Count the fixture's source records as the *caller's own* connection sees them.

    The opposite of ``bulk_fixture_row_counts``: this reads through the same connection the
    loader wrote on, so it reports rows the caller's still-open transaction wrote but has
    not committed. That difference is the whole point of the caller-owned proof.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) FROM core.source_record WHERE source_record_key = ANY(%s)",
            (fixture.source_record_keys,),
        )
        return cursor.fetchone()[0]


def assert_loader_arm_is_caller_owned(
    fixture: ScopedBulkFixture,
    db_conn: psycopg.Connection,
    *,
    expected_source_records: int,
    run_loader: Callable[[], object],
) -> None:
    """Prove a loader writes into the caller's open transaction and commits nothing itself.

    When the caller hands the loader a connection that is already INTRANS, the loader must
    observe that it does not manage the outer transaction and leave every write uncommitted:
    the caller connection can see the fixture's source records, but no independent connection
    can while that transaction is open, and rolling the caller transaction back erases them.

    This is the invariant every jurisdiction's ``load_*_with_filings`` entry point must hold
    for a caller-supplied transaction; Stages 2-4 reuse this helper.
    """
    assert db_conn.info.transaction_status == psycopg.pq.TransactionStatus.INTRANS
    run_loader()
    assert _caller_visible_source_record_count(db_conn, fixture) == expected_source_records
    assert bulk_fixture_row_counts(fixture)[0] == 0
    db_conn.rollback()
    assert bulk_fixture_row_counts(fixture)[0] == 0


def bulk_fixture_entity_row_counts(fixture: SuffixScopedBulkFixture) -> dict[str, int]:
    """Count the entity rows carrying this fixture's run suffix, independently observed.

    Matched on the suffix rather than on a canonicalised name so the count cannot drift
    when a loader normalises names differently: the suffix is an opaque hex token that
    survives every normalisation the extractors apply. ``ILIKE`` because a canonical
    name may be case-folded.

    A fixture that has never been loaded reads zero on every key, so a specimen can use
    the same call as its pre-load baseline and as its post-cleanup leak check.
    """
    suffix_pattern = f"%{fixture.run_suffix}%"
    observer_conn = get_connection()
    try:
        with observer_conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM core.person WHERE canonical_name ILIKE %s", (suffix_pattern,))
            person_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM core.organization WHERE canonical_name ILIKE %s", (suffix_pattern,))
            organization_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM core.address WHERE raw_address ILIKE %s", (suffix_pattern,))
            address_count = cursor.fetchone()[0]
            cursor.execute(
                "SELECT COUNT(*) FROM cf.committee WHERE fec_committee_id = %s",
                (fixture.committee_fec_id,),
            )
            committee_count = cursor.fetchone()[0]
        return {
            "person": person_count,
            "organization": organization_count,
            "address": address_count,
            "committee": committee_count,
        }
    finally:
        observer_conn.close()


def _capture_fixture_entity_ids(
    cursor: psycopg.Cursor,
    source_record_ids: list[UUID],
) -> dict[str, list[UUID]]:
    """Read the entity ids the fixture linked, before the links themselves are deleted."""
    captured = _empty_entity_capture()
    cursor.execute(
        "SELECT entity_type, entity_id FROM core.entity_source WHERE source_record_id = ANY(%s)",
        (source_record_ids,),
    )
    for entity_type, entity_id in cursor.fetchall():
        if entity_type in captured:
            captured[entity_type].append(entity_id)

    cursor.execute(
        "SELECT address_id FROM core.entity_address WHERE source_record_id = ANY(%s)",
        (source_record_ids,),
    )
    captured["address"].extend(row[0] for row in cursor.fetchall())
    return captured


def _empty_entity_capture() -> dict[str, list[UUID]]:
    return {entity_type: [] for entity_type in _UNREFERENCED_ENTITY_DELETES}


def _delete_source_record_scoped_rows(cursor: psycopg.Cursor, source_record_ids: list[UUID]) -> None:
    """Delete every row a fixture's source records own, in reference order."""
    # cf.transaction references cf.filing, so delete transactions first.
    cursor.execute("DELETE FROM cf.transaction WHERE source_record_id = ANY(%s)", (source_record_ids,))
    cursor.execute("DELETE FROM cf.filing WHERE source_record_id = ANY(%s)", (source_record_ids,))
    cursor.execute("DELETE FROM core.entity_address WHERE source_record_id = ANY(%s)", (source_record_ids,))
    cursor.execute("DELETE FROM core.entity_source WHERE source_record_id = ANY(%s)", (source_record_ids,))


def _delete_fixture_committee(cursor: psycopg.Cursor, committee_fec_id: str) -> list[UUID]:
    """Delete the fixture's synthetic committee, returning its organization id if any.

    The committee organization is only ever *resolved* by the loaders, never linked
    through ``core.entity_source``, so it is reachable from the fixture's own synthetic
    committee identity alone and is handed back to the unreferenced-entity pass.

    A committee's filings and transactions can outlive the source record that created
    them when a later row reuses the cached filing, so they are cleared by committee
    identity as well as by source record.
    """
    cursor.execute("SELECT id, organization_id FROM cf.committee WHERE fec_committee_id = %s", (committee_fec_id,))
    row = cursor.fetchone()
    if row is None:
        return []

    committee_id, organization_id = row
    cursor.execute(
        "DELETE FROM cf.transaction WHERE committee_id = %s OR recipient_committee_id = %s",
        (committee_id, committee_id),
    )
    cursor.execute("DELETE FROM cf.filing WHERE committee_id = %s", (committee_id,))
    cursor.execute("DELETE FROM cf.committee WHERE id = %s", (committee_id,))
    return [] if organization_id is None else [organization_id]


def cleanup_scoped_fixture_rows(
    source_record_keys: Sequence[str],
    committee_fec_ids: Sequence[str],
) -> None:
    """Delete fixture rows by synthetic identity through the one cleanup primitive.

    Provenance links are not the whole footprint: a load also creates ``core.person``,
    ``core.organization``, ``core.address``, and ``cf.committee`` rows. Those are
    captured from the links before the links are removed, then deleted only when
    nothing else references them, so a row the fixture merely reused is left alone.

    Runs on its own connection so it remains usable while a caller-side transaction is
    open. This is the primitive for multi-committee fixtures; ``cleanup_bulk_fixture``
    is its ``ScopedBulkFixture`` adapter.
    """
    keys = list(source_record_keys)
    cleanup_conn = get_connection()
    try:
        with cleanup_conn.cursor() as cursor:
            cursor.execute(
                "SELECT id FROM core.source_record WHERE source_record_key = ANY(%s)",
                (keys,),
            )
            source_record_ids = [row[0] for row in cursor.fetchall()]
            captured = _empty_entity_capture()
            if source_record_ids:
                captured = _capture_fixture_entity_ids(cursor, source_record_ids)
                _delete_source_record_scoped_rows(cursor, source_record_ids)

            for committee_fec_id in committee_fec_ids:
                captured["organization"].extend(_delete_fixture_committee(cursor, committee_fec_id))
            for entity_type, delete_statement in _UNREFERENCED_ENTITY_DELETES.items():
                if captured[entity_type]:
                    cursor.execute(delete_statement, (captured[entity_type],))

            cursor.execute("DELETE FROM core.source_record WHERE source_record_key = ANY(%s)", (keys,))
        cleanup_conn.commit()
    finally:
        cleanup_conn.close()


def cleanup_bulk_fixture(fixture: ScopedBulkFixture) -> None:
    """Adapt one ``ScopedBulkFixture`` to the shared cleanup primitive.

    Safe to call before seeding as well as in cleanup, so a killed run cannot wedge the
    next one. Multi-committee callers use ``cleanup_scoped_fixture_rows`` directly.
    """
    cleanup_scoped_fixture_rows(fixture.source_record_keys, (fixture.committee_fec_id,))


def assert_bulk_fixture_left_no_entity_rows(fixture: SuffixScopedBulkFixture) -> None:
    """Fail if any row carrying this fixture's run suffix outlived its cleanup."""
    remaining = bulk_fixture_entity_row_counts(fixture)
    assert remaining == NO_ENTITY_ROWS, (
        f"bulk fixture {fixture.run_suffix} leaked rows into the database after cleanup: {remaining}"
    )


def register_bulk_fixture_cleanup(resources: ExitStack, fixture: SuffixScopedBulkFixture) -> None:
    """Clean the fixture up when the stack unwinds, then prove the cleanup left nothing.

    Registered leak-check first so the stack's LIFO unwind runs the cleanup and *then*
    the check. Both run on a red run and a green one alike, so a cleanup that stops
    deleting the entity rows a load creates turns the specimen red instead of silently
    growing the shared database.
    """
    resources.callback(assert_bulk_fixture_left_no_entity_rows, fixture)
    resources.callback(cleanup_bulk_fixture, fixture)


class BulkFixtureInterruption(BaseException):
    """A process-style interrupt for bounded-commit specimens.

    Deliberately not an ``Exception``: every loader wraps its per-row work in
    ``except Exception``, so an ``Exception`` subclass would be swallowed and counted as
    a row error instead of tearing the load down mid-loop the way a killed process does.
    """


def seed_bulk_fixture(
    resources: ExitStack,
    db_conn: psycopg.Connection,
    fixture: SuffixScopedBulkFixture,
    *,
    expected_unique_source_record_keys: int,
) -> None:
    """Register the fixture's cleanup and leak check, then prove it starts absent.

    Registration happens before the load runs, so neither a red nor a green run can leak
    committed rows when an assertion fires part-way through. ``db_conn`` yields with
    BEGIN already executed; rolling it back is what lets the loader observe IDLE and own
    its own commits — without that, nothing commits and the specimen proves nothing.
    """
    register_bulk_fixture_cleanup(resources, fixture)
    db_conn.rollback()
    cleanup_bulk_fixture(fixture)
    assert bulk_fixture_row_counts(fixture) == (0, 0)
    assert bulk_fixture_entity_row_counts(fixture) == NO_ENTITY_ROWS
    assert len(set(fixture.source_record_keys)) == expected_unique_source_record_keys


def seed_written_bulk_fixture(
    resources: ExitStack,
    db_conn: psycopg.Connection,
    write_fixture: Callable[[], _FixtureT],
    *,
    row_count: int,
) -> _FixtureT:
    """Write a jurisdiction-local bulk fixture and hand it to the shared seeding contract."""
    fixture = write_fixture()
    seed_bulk_fixture(resources, db_conn, fixture, expected_unique_source_record_keys=row_count)
    return fixture


def install_write_interrupt(
    monkeypatch: pytest.MonkeyPatch,
    loader_module: ModuleType,
    attribute: str,
    *,
    raise_after_writes: int,
) -> Counter[str]:
    """Interrupt ``loader_module.attribute`` after ``raise_after_writes`` real calls.

    Injected at the loader's own write call rather than at the loop, so every earlier row
    performs its real database write and the durable count reflects real work. The
    returned counter reports how many times the call was reached, which is what tells a
    specimen the interrupt landed on the row it intended.
    """
    real_write = getattr(loader_module, attribute)
    write_counts: Counter[str] = Counter()

    def _interrupting_write(*args: object, **kwargs: object) -> object:
        write_counts["writes"] += 1
        if write_counts["writes"] > raise_after_writes:
            raise BulkFixtureInterruption(f"{loader_module.__name__}.{attribute} batch interruption")
        return real_write(*args, **kwargs)

    monkeypatch.setattr(loader_module, attribute, _interrupting_write)
    return write_counts


def suppress_first_writes(
    monkeypatch: pytest.MonkeyPatch,
    loader_module: ModuleType,
    attribute: str,
    *,
    suppress_first: int,
    replacement_result: object = None,
) -> Counter[str]:
    """Replace the first calls to one loader write, then delegate subsequent calls."""
    if suppress_first < 0:
        raise ValueError("suppress_first must be non-negative")

    real_write = getattr(loader_module, attribute)
    attempts: Counter[str] = Counter()

    def _suppressing_write(*args: object, **kwargs: object) -> object:
        attempts["attempts"] += 1
        if attempts["attempts"] <= suppress_first:
            return replacement_result
        return real_write(*args, **kwargs)

    monkeypatch.setattr(loader_module, attribute, _suppressing_write)
    return attempts
