"""PA loader test fixtures and the PA-specific observers built on them.

Single owner of the synthetic detail+filings fixture pair every PA committing test
uses. Cleanup and the source-record/transaction observer are not owned here: they are
identical across jurisdictions and belong to `jurisdictions._bulk_fixture_support`,
which PA's tests reach through this module. What stays PA-specific is
the entity footprint read through PA's own extractor, because the `shared_address`
seam below deliberately gives two fixtures one address and so cannot be scoped by a
per-run token.

Every identity the fixture writes — campaign-finance id, filer id and name, donor
name, street address — carries the same per-run suffix. The donor suffix rides in
the parsed surname token, keeping its ``(first_name, last_name, zip5)`` resolver
key run-unique rather than only its canonical name. That keeps the fixture from
ever colliding with real PA data, and keeps two fixtures running concurrently
under xdist from resolving to, and then deleting, each other's rows.
"""

from __future__ import annotations

import csv
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import NamedTuple
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import psycopg

from core.db import get_connection
from domains.campaign_finance.ingest.filing_loader import generate_synthetic_committee_id
from domains.campaign_finance.jurisdictions.states.PA.scraper import _load_column_for_semantic_path
from domains.campaign_finance.jurisdictions.states.PA.scraper.extract import extract_pa_contribution
from domains.campaign_finance.jurisdictions.states.PA.scraper.load import _pa_source_record_key
from domains.campaign_finance.jurisdictions.states.PA.scraper.parse import parse_contributions

_FIXTURE_DIR = Path(__file__).parent / "test_fixtures"
PA_FIXTURE_YEAR = 2025


class PAFixture(NamedTuple):
    """One synthetic PA detail+filings pair and the identities it writes."""

    detail_path: Path
    campaign_finance_id: str
    filer_id: str
    source_record_keys: list[str]

    @property
    def committee_fec_id(self) -> str:
        return generate_synthetic_committee_id("PA", self.filer_id)


class FakeTransactionConnection:
    """Connection double that models psycopg transaction and savepoint semantics.

    Unlike a frozen ``MagicMock`` whose status never changes, this moves
    IDLE -> INTRANS on ``execute`` / ``BEGIN`` and on entering a ``transaction()``
    block, and back to IDLE on ``commit`` / ``rollback``. ``transaction()`` behaves
    like a savepoint: an exception inside it records a savepoint rollback, re-raises,
    and leaves the enclosing transaction open — so a test can tell a per-row
    savepoint rollback apart from a connection-wide one. The ordered call log is the
    only observable surface for loop-owned periodic commit behaviour.
    """

    def __init__(self) -> None:
        self.info = SimpleNamespace(transaction_status=psycopg.pq.TransactionStatus.IDLE)
        self.calls: list[str] = []

    def _open(self) -> None:
        self.info.transaction_status = psycopg.pq.TransactionStatus.INTRANS

    def execute(self, *_args: object, **_kwargs: object) -> MagicMock:
        self.calls.append("execute")
        self._open()
        return MagicMock()

    def commit(self) -> None:
        self.calls.append("commit")
        self.info.transaction_status = psycopg.pq.TransactionStatus.IDLE

    def rollback(self) -> None:
        self.calls.append("rollback")
        self.info.transaction_status = psycopg.pq.TransactionStatus.IDLE

    def close(self) -> None:
        self.calls.append("close")

    @contextmanager
    def transaction(self) -> Iterator[None]:
        self._open()
        self.calls.append("savepoint_enter")
        try:
            yield
        except Exception:
            # Rolling back to a savepoint leaves the enclosing transaction open.
            self.calls.append("savepoint_rollback")
            self._open()
            raise
        self.calls.append("savepoint_release")

    @property
    def commit_count(self) -> int:
        return self.calls.count("commit")


def _read_sample_csv(path: Path) -> list[dict[str, str | None]]:
    with path.open(encoding="utf-8", newline="") as csv_file:
        return list(csv.DictReader(csv_file))


def _write_csv(path: Path, rows: list[dict[str, str | None]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=list(rows[0]))
        writer.writeheader()
        for row in rows:
            writer.writerow({key: "" if value is None else value for key, value in row.items()})


def write_pa_fixture_pair(
    tmp_path: Path,
    *,
    row_count: int = 1,
    shared_address: str | None = None,
) -> PAFixture:
    """Write a detail+filings CSV pair whose every identity is unique per run.

    `_resolve_pa_filings_path` derives the sibling filings CSV by replacing the
    ``contributions`` segment, so the two stems must match, and
    `_require_pa_filer_row` needs the filings row's campaign-finance id to match
    the detail row's.

    All ``row_count`` detail rows share this fixture's single per-run
    ``CampaignFinanceID`` so the one filings row still satisfies the filer join
    and amendment lookup, but each detail row carries the run suffix and row index
    in its parsed donor surname. This makes both the person resolver key and the
    whole-row hash — and therefore its ``source_record_key`` — unique. That is what
    lets a bulk fixture cross ``load._COMMIT_BATCH_ROWS`` while still being cleaned
    up by its own scoped keys. Pass a row count just above that boundary to exercise
    periodic commits.

    ``shared_address`` overrides the per-run-unique donor street with a caller-
    supplied value. Two independent fixtures (distinct run suffix in the parsed
    donor surname, so distinct resolver keys and committee/filer/donor identities)
    built with the same ``shared_address`` and the sample row's city/state/zip
    extract to one identical ``raw_address`` and therefore resolve to a single
    ``core.address`` row — the seam later blocking tests reuse to assert address
    sharing.
    """
    if row_count < 1:
        raise ValueError(f"row_count must be >= 1, got {row_count}")

    run_suffix = uuid4().hex[:12]
    campaign_finance_id = f"90{run_suffix}"
    filer_id = f"STAGE6TEST{run_suffix}"
    filer_name = f"Stage6 Bounded Commit Test Committee {run_suffix}"
    detail_path = tmp_path / f"pa_bounded_{run_suffix}_contributions.csv"
    filings_path = tmp_path / f"pa_bounded_{run_suffix}_filings.csv"

    name_column = _load_column_for_semantic_path("contributions", "donor.name")
    street_column = _load_column_for_semantic_path("contributions", "donor.address.street1")
    street_value = shared_address if shared_address is not None else f"{run_suffix} Test Street"

    base_row = _read_sample_csv(_FIXTURE_DIR / "sample_contributions.csv")[0]
    detail_rows: list[dict[str, str | None]] = []
    for index in range(row_count):
        detail_row = dict(base_row)
        detail_row["CampaignFinanceID"] = campaign_finance_id
        detail_row["FilerID"] = filer_id
        # The run suffix and row index share the parsed surname token, keeping both
        # the resolver key and source_record_key unique for every fixture row.
        detail_row[name_column] = f"José Café Donor {run_suffix}_{index}"
        detail_row[street_column] = street_value
        detail_rows.append(detail_row)
    _write_csv(detail_path, detail_rows)

    filings_row = _read_sample_csv(_FIXTURE_DIR / "sample_filings.csv")[0]
    filings_row["CampaignfinanceID"] = campaign_finance_id
    filings_row["FILERID"] = filer_id
    filings_row["FILERNAME"] = filer_name
    _write_csv(filings_path, [filings_row])

    rows = list(parse_contributions(detail_path, year=PA_FIXTURE_YEAR))
    source_record_keys = [_pa_source_record_key(row, data_type="contributions") for row in rows]
    return PAFixture(
        detail_path=detail_path,
        campaign_finance_id=campaign_finance_id,
        filer_id=filer_id,
        source_record_keys=source_record_keys,
    )


def _fixture_entity_identity(fixture: PAFixture) -> tuple[list[str], list[str], list[str]]:
    """Return the (person names, organization names, raw addresses) the fixture extracts.

    Reuses the loader's own extractor so this cannot drift from what a load writes.
    """
    rows = parse_contributions(fixture.detail_path, year=PA_FIXTURE_YEAR)
    extracted = [extract_pa_contribution(dict(row)) for row in rows]
    person_names = [row["donor_person"].canonical_name for row in extracted if row["donor_person"] is not None]
    organization_names = [row["donor_org"].canonical_name for row in extracted if row["donor_org"] is not None]
    raw_addresses = [row["address"].raw_address for row in extracted if row["address"] is not None]
    return person_names, organization_names, raw_addresses


def fixture_person_zip_keys(
    fixture: PAFixture,
) -> list[tuple[str | None, str | None, str | None]]:
    """Return each fixture row's extractor-derived person resolver key."""
    rows = parse_contributions(fixture.detail_path, year=PA_FIXTURE_YEAR)
    extracted = [extract_pa_contribution(dict(row)) for row in rows]
    return [
        (
            row["donor_person"].first_name if row["donor_person"] is not None else None,
            row["donor_person"].last_name if row["donor_person"] is not None else None,
            row["address"].zip5 if row["address"] is not None else None,
        )
        for row in extracted
    ]


def fixture_entity_row_counts(fixture: PAFixture) -> dict[str, int]:
    """Count entity rows carrying the fixture's identity, from an independent connection.

    Counted by identity rather than by provenance link: cleanup deletes the links,
    so a link-scoped count would read zero however many entity rows leaked.
    """
    person_names, organization_names, raw_addresses = _fixture_entity_identity(fixture)
    observer_conn = get_connection()
    try:
        with observer_conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM core.person WHERE canonical_name = ANY(%s)", (person_names,))
            person_count = cursor.fetchone()[0]
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM core.organization
                WHERE canonical_name = ANY(%s) OR identifiers ->> 'pa_filer_id' = %s
                """,
                (organization_names, fixture.filer_id),
            )
            organization_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM core.address WHERE raw_address = ANY(%s)", (raw_addresses,))
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


def fixture_address_ids(fixture: PAFixture) -> list[UUID]:
    """Return the distinct `core.address` ids linked to this fixture's loaded rows.

    The address identity is still checked against the extractor-derived
    `raw_address` (the same value `upsert_address` dedupes on), but the lookup is
    scoped through this fixture's `core.source_record` provenance. That means an
    unloaded fixture sharing another fixture's address reads as absent instead of
    inheriting the globally matching `core.address` row.
    """
    _, _, raw_addresses = _fixture_entity_identity(fixture)
    observer_conn = get_connection()
    try:
        with observer_conn.cursor() as cursor:
            cursor.execute(
                """
                WITH fixture_source_records AS (
                    SELECT id
                    FROM core.source_record
                    WHERE source_record_key = ANY(%s)
                ),
                fixture_address_ids AS (
                    SELECT es.entity_id AS address_id
                    FROM core.entity_source es
                    JOIN fixture_source_records sr ON sr.id = es.source_record_id
                    WHERE es.entity_type = 'address'
                    UNION
                    SELECT ea.address_id
                    FROM core.entity_address ea
                    JOIN fixture_source_records sr ON sr.id = ea.source_record_id
                )
                SELECT DISTINCT a.id
                FROM core.address a
                JOIN fixture_address_ids fai ON fai.address_id = a.id
                WHERE a.raw_address = ANY(%s)
                """,
                (fixture.source_record_keys, raw_addresses),
            )
            return [row[0] for row in cursor.fetchall()]
    finally:
        observer_conn.close()


class BackendActivity(NamedTuple):
    """One backend's `pg_stat_activity` row plus who is blocking it, if anyone."""

    pid: int
    state: str | None
    wait_event_type: str | None
    wait_event: str | None
    query: str | None
    blocking_pids: list[int]


def observe_backend_activity(backend_pid: int) -> BackendActivity | None:
    """Read `pg_stat_activity` + `pg_blocking_pids()` for a backend from its own connection.

    Opens an independent `get_connection()` so it can observe a backend that is
    itself mid-transaction (a self-observing connection would only ever report its
    own in-flight `SELECT`). Returns ``None`` when no such backend exists — an
    honest "unknown", never a synthesised healthy row.
    """
    observer_conn = get_connection()
    try:
        with observer_conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT state, wait_event_type, wait_event, query, pg_blocking_pids(pid)
                FROM pg_stat_activity
                WHERE pid = %s
                """,
                (backend_pid,),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        state, wait_event_type, wait_event, query, blocking_pids = row
        return BackendActivity(
            pid=backend_pid,
            state=state,
            wait_event_type=wait_event_type,
            wait_event=wait_event,
            query=query,
            blocking_pids=list(blocking_pids or []),
        )
    finally:
        observer_conn.close()


def wait_until(
    predicate: Callable[[], bool],
    *,
    timeout_seconds: float,
    poll_interval_seconds: float = 0.02,
    description: str = "condition",
) -> None:
    """Poll ``predicate`` until it is exactly ``True``; raise on timeout or indeterminacy.

    A bounded-wait guard that must never default to healthy: it raises
    ``TimeoutError`` if ``timeout_seconds`` elapses with the predicate still
    ``False``, and ``TypeError`` if the predicate returns anything other than a
    bool (indeterminate state), rather than treating either as success. Any
    exception the predicate raises propagates unchanged — an errored probe is not
    a passing one.
    """
    if timeout_seconds < 0:
        raise ValueError(f"timeout_seconds must be >= 0, got {timeout_seconds}")

    deadline = time.monotonic() + timeout_seconds
    while True:
        result = predicate()
        if result is True:
            return
        if result is not False:
            raise TypeError(
                f"wait_until predicate for {description!r} returned indeterminate "
                f"{result!r}; a bounded-wait guard requires an explicit bool"
            )
        if time.monotonic() >= deadline:
            raise TimeoutError(f"Timed out after {timeout_seconds}s waiting for {description}")
        time.sleep(poll_interval_seconds)
