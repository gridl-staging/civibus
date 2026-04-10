"""Integration tests for Schedule E loader (independent expenditures).

Tests verify the end-to-end ingest path: CSV parsing → entity linking →
amendment normalization → filing/transaction upsert. Each test seeds its
own committee/candidate fixtures and cleans up afterward.

These tests are written before the loader implementation (TDD red phase).
They will fail on import until schedule_e_loader.py exists.
"""

from __future__ import annotations

import csv
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from core.db import get_connection
from domains.campaign_finance.ingest.bulk_loader import ensure_fec_bulk_data_source
from domains.campaign_finance.ingest.schedule_e_loader import load_schedule_e
from domains.campaign_finance.ingest.schedule_e_parser import SCHEDULE_E_COLUMNS
from test_support.schedule_e import SeededCommittee, seed_schedule_e_committee

pytestmark = [pytest.mark.integration, pytest.mark.e2e]


# ---------------------------------------------------------------------------
# Unique ID generators for test isolation
# ---------------------------------------------------------------------------


def _unique_committee_fec_id() -> str:
    """C + 8 digits, unique per call."""
    return f"C{uuid4().int % 100_000_000:08d}"


def _unique_candidate_fec_id(office: str = "H") -> str:
    """[HSP] + 0 + AA + 5 digits — matches FEC regex ^[HSP][0-9][A-Z0-9]{2}[0-9]{5}$."""
    n = uuid4().int % 100_000
    return f"{office}0AA{n:05d}"


def _unique_file_num() -> str:
    return str(uuid4().int % 10_000_000)


def _unique_tran_id() -> str:
    return f"SE.{uuid4().hex[:10]}"


# ---------------------------------------------------------------------------
# CSV fixture helpers
# ---------------------------------------------------------------------------


def _write_schedule_e_csv(tmp_path: Path, rows: list[dict[str, str]]) -> Path:
    """Write a Schedule E CSV with proper header and quoting."""
    csv_path = tmp_path / f"schedule_e_{uuid4().hex[:8]}.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=list(SCHEDULE_E_COLUMNS),
            quoting=csv.QUOTE_ALL,
        )
        writer.writeheader()
        writer.writerows(rows)
    return csv_path


def _make_row(
    *,
    cand_id: str = "",
    cand_name: str = "Test Candidate",
    spe_id: str,
    spe_nam: str = "Test PAC",
    ele_type: str = "G",
    can_office_state: str = "",
    can_office_dis: str = "00",
    can_office: str = "H",
    cand_pty_aff: str = "",
    exp_amo: str = "1000",
    exp_date: str = "15-OCT-24",
    agg_amo: str = "5000",
    sup_opp: str = "S",
    pur: str = "Advertising",
    pay: str = "Ad Agency LLC",
    file_num: str = "",
    amndt_ind: str = "N",
    tran_id: str = "",
    image_num: str = "202410001234567890",
    receipt_dat: str = "16-OCT-24",
    fec_election_yr: str = "2024",
    prev_file_num: str = "",
    dissem_dt: str = "14-OCT-24",
) -> dict[str, str]:
    """Build a Schedule E CSV row dict with sensible defaults."""
    if not file_num:
        file_num = _unique_file_num()
    if not tran_id:
        tran_id = _unique_tran_id()
    return {
        "cand_id": cand_id,
        "cand_name": cand_name,
        "spe_id": spe_id,
        "spe_nam": spe_nam,
        "ele_type": ele_type,
        "can_office_state": can_office_state,
        "can_office_dis": can_office_dis,
        "can_office": can_office,
        "cand_pty_aff": cand_pty_aff,
        "exp_amo": exp_amo,
        "exp_date": exp_date,
        "agg_amo": agg_amo,
        "sup_opp": sup_opp,
        "pur": pur,
        "pay": pay,
        "file_num": file_num,
        "amndt_ind": amndt_ind,
        "tran_id": tran_id,
        "image_num": image_num,
        "receipt_dat": receipt_dat,
        "fec_election_yr": fec_election_yr,
        "prev_file_num": prev_file_num,
        "dissem_dt": dissem_dt,
    }


# ---------------------------------------------------------------------------
# DB seeding helpers
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SeededCandidate:
    id: UUID
    fec_candidate_id: str
    person_id: UUID


def _seed_committee(
    conn: psycopg.Connection,
    fec_id: str,
    name: str = "Test Committee",
) -> SeededCommittee:
    return seed_schedule_e_committee(conn, fec_id, name)


def _seed_candidate(
    conn: psycopg.Connection,
    fec_id: str,
    name: str = "Test Candidate",
    office: str | None = None,
) -> SeededCandidate:
    """Insert a minimal candidate + person into the test DB."""
    # Derive office from first char of FEC ID
    if office is None:
        office = fec_id[0]  # H, S, or P
    person_id = uuid4()
    candidate_id = uuid4()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO core.person (id, canonical_name, identifiers) VALUES (%s, %s, %s::jsonb)",
            (person_id, name, f'{{"fec_candidate_id": "{fec_id}"}}'),
        )
        cur.execute(
            "INSERT INTO cf.candidate (id, fec_candidate_id, name, person_id, office) VALUES (%s, %s, %s, %s, %s)",
            (candidate_id, fec_id, name, person_id, office),
        )
    conn.commit()
    return SeededCandidate(id=candidate_id, fec_candidate_id=fec_id, person_id=person_id)


# ---------------------------------------------------------------------------
# Cleanup helpers
# ---------------------------------------------------------------------------


def _cleanup_schedule_e_test_data(
    conn: psycopg.Connection,
    committee_fec_ids: list[str],
    candidate_fec_ids: list[str],
    file_nums: list[str],
) -> None:
    """Remove all test-seeded rows. Order respects FK constraints."""
    with conn.cursor() as cur:
        # Delete transactions via their filings
        if file_nums:
            cur.execute(
                """
                DELETE FROM cf.transaction
                WHERE filing_id IN (
                    SELECT id FROM cf.filing WHERE filing_fec_id = ANY(%s)
                )
                """,
                (file_nums,),
            )
            cur.execute(
                "DELETE FROM cf.filing WHERE filing_fec_id = ANY(%s)",
                (file_nums,),
            )
        # Delete source records created by the loader
        if committee_fec_ids:
            cur.execute(
                """
                DELETE FROM core.source_record
                WHERE source_record_key LIKE 'schedule_e:%%'
                  AND source_record_key LIKE ANY(
                      SELECT '%%' || fec_committee_id || '%%'
                      FROM cf.committee WHERE fec_committee_id = ANY(%s)
                  )
                """,
                (committee_fec_ids,),
            )
        # Delete seeded candidates and persons
        if candidate_fec_ids:
            cur.execute(
                "DELETE FROM cf.candidate WHERE fec_candidate_id = ANY(%s)",
                (candidate_fec_ids,),
            )
            cur.execute(
                "DELETE FROM core.person WHERE identifiers ->> 'fec_candidate_id' = ANY(%s)",
                (candidate_fec_ids,),
            )
        # Delete seeded committees and organizations
        if committee_fec_ids:
            cur.execute(
                "DELETE FROM cf.committee WHERE fec_committee_id = ANY(%s)",
                (committee_fec_ids,),
            )
            cur.execute(
                "DELETE FROM core.organization WHERE identifiers ->> 'fec_committee_id' = ANY(%s)",
                (committee_fec_ids,),
            )
    conn.commit()


# ---------------------------------------------------------------------------
# Query helpers for assertions
# ---------------------------------------------------------------------------


def _select_filing_by_fec_id(conn: psycopg.Connection, filing_fec_id: str) -> dict | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT * FROM cf.filing WHERE filing_fec_id = %s LIMIT 1",
            (filing_fec_id,),
        )
        return cur.fetchone()


def _select_transactions_by_filing_fec_id(
    conn: psycopg.Connection,
    filing_fec_id: str,
) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT t.*
            FROM cf.transaction t
            JOIN cf.filing f ON f.id = t.filing_id
            WHERE f.filing_fec_id = %s
            ORDER BY t.transaction_identifier
            """,
            (filing_fec_id,),
        )
        return cur.fetchall()


def _count_transactions_for_committee(conn: psycopg.Connection, committee_id: UUID) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM cf.transaction WHERE committee_id = %s",
            (committee_id,),
        )
        return cur.fetchone()[0]


def _count_source_records_like(conn: psycopg.Connection, pattern: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM core.source_record WHERE source_record_key LIKE %s",
            (pattern,),
        )
        return cur.fetchone()[0]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_conn() -> Iterator[psycopg.Connection]:
    """Single connection for the test, closed on teardown."""
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def data_source_id(db_conn: psycopg.Connection) -> UUID:
    """Ensure the FEC bulk data source row exists and return its ID."""
    ds_id = ensure_fec_bulk_data_source(db_conn)
    db_conn.commit()
    return ds_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestScheduleESourceRecords:
    """Source record creation via provenance tracking."""

    def test_basic_ingest_creates_source_records(
        self,
        db_conn: psycopg.Connection,
        data_source_id: UUID,
        tmp_path: Path,
    ) -> None:
        committee = _seed_committee(db_conn, _unique_committee_fec_id(), "Source Record PAC")
        candidate = _seed_candidate(db_conn, _unique_candidate_fec_id("H"), "Source Record Candidate")
        file_num = _unique_file_num()
        tran_id = _unique_tran_id()
        rows = [
            _make_row(
                spe_id=committee.fec_committee_id,
                cand_id=candidate.fec_candidate_id,
                file_num=file_num,
                tran_id=tran_id,
            ),
        ]
        csv_path = _write_schedule_e_csv(tmp_path, rows)

        try:
            result = load_schedule_e(
                db_conn,
                csv_path,
                cycle=2024,
                data_source_id=data_source_id,
                batch_size=100,
            )
            assert result.inserted == 1
            assert result.errors == 0

            # Verify a source record was created
            filing = _select_filing_by_fec_id(db_conn, file_num)
            assert filing is not None
            assert filing["source_record_id"] is not None
        finally:
            _cleanup_schedule_e_test_data(
                db_conn,
                [committee.fec_committee_id],
                [candidate.fec_candidate_id],
                [file_num],
            )


class TestScheduleESupportOppose:
    """support_oppose field is populated from sup_opp column."""

    def test_support_value(
        self,
        db_conn: psycopg.Connection,
        data_source_id: UUID,
        tmp_path: Path,
    ) -> None:
        committee = _seed_committee(db_conn, _unique_committee_fec_id(), "Support PAC")
        candidate = _seed_candidate(db_conn, _unique_candidate_fec_id("H"), "Supported Candidate")
        file_num = _unique_file_num()
        rows = [
            _make_row(
                spe_id=committee.fec_committee_id,
                cand_id=candidate.fec_candidate_id,
                file_num=file_num,
                sup_opp="S",
            ),
        ]
        csv_path = _write_schedule_e_csv(tmp_path, rows)

        try:
            load_schedule_e(
                db_conn,
                csv_path,
                cycle=2024,
                data_source_id=data_source_id,
                batch_size=100,
            )
            txns = _select_transactions_by_filing_fec_id(db_conn, file_num)
            assert len(txns) == 1
            assert txns[0]["support_oppose"] == "S"
        finally:
            _cleanup_schedule_e_test_data(
                db_conn,
                [committee.fec_committee_id],
                [candidate.fec_candidate_id],
                [file_num],
            )

    def test_oppose_value(
        self,
        db_conn: psycopg.Connection,
        data_source_id: UUID,
        tmp_path: Path,
    ) -> None:
        committee = _seed_committee(db_conn, _unique_committee_fec_id(), "Oppose PAC")
        candidate = _seed_candidate(db_conn, _unique_candidate_fec_id("H"), "Opposed Candidate")
        file_num = _unique_file_num()
        rows = [
            _make_row(
                spe_id=committee.fec_committee_id,
                cand_id=candidate.fec_candidate_id,
                file_num=file_num,
                sup_opp="O",
            ),
        ]
        csv_path = _write_schedule_e_csv(tmp_path, rows)

        try:
            load_schedule_e(
                db_conn,
                csv_path,
                cycle=2024,
                data_source_id=data_source_id,
                batch_size=100,
            )
            txns = _select_transactions_by_filing_fec_id(db_conn, file_num)
            assert len(txns) == 1
            assert txns[0]["support_oppose"] == "O"
        finally:
            _cleanup_schedule_e_test_data(
                db_conn,
                [committee.fec_committee_id],
                [candidate.fec_candidate_id],
                [file_num],
            )

    def test_empty_sup_opp_stored_as_null(
        self,
        db_conn: psycopg.Connection,
        data_source_id: UUID,
        tmp_path: Path,
    ) -> None:
        committee = _seed_committee(db_conn, _unique_committee_fec_id(), "Neutral PAC")
        candidate = _seed_candidate(db_conn, _unique_candidate_fec_id("P"), "Neutral Candidate")
        file_num = _unique_file_num()
        rows = [
            _make_row(
                spe_id=committee.fec_committee_id,
                cand_id=candidate.fec_candidate_id,
                can_office="P",
                file_num=file_num,
                sup_opp="",
            ),
        ]
        csv_path = _write_schedule_e_csv(tmp_path, rows)

        try:
            load_schedule_e(
                db_conn,
                csv_path,
                cycle=2024,
                data_source_id=data_source_id,
                batch_size=100,
            )
            txns = _select_transactions_by_filing_fec_id(db_conn, file_num)
            assert len(txns) == 1
            assert txns[0]["support_oppose"] is None
        finally:
            _cleanup_schedule_e_test_data(
                db_conn,
                [committee.fec_committee_id],
                [candidate.fec_candidate_id],
                [file_num],
            )


class TestScheduleEEntityLinking:
    """Committee and candidate linking via FEC IDs."""

    def test_committee_linked_via_spe_id(
        self,
        db_conn: psycopg.Connection,
        data_source_id: UUID,
        tmp_path: Path,
    ) -> None:
        committee = _seed_committee(db_conn, _unique_committee_fec_id(), "Linked PAC")
        candidate = _seed_candidate(db_conn, _unique_candidate_fec_id("S"), "Linked Candidate")
        file_num = _unique_file_num()
        rows = [
            _make_row(
                spe_id=committee.fec_committee_id,
                cand_id=candidate.fec_candidate_id,
                can_office="S",
                file_num=file_num,
            ),
        ]
        csv_path = _write_schedule_e_csv(tmp_path, rows)

        try:
            load_schedule_e(
                db_conn,
                csv_path,
                cycle=2024,
                data_source_id=data_source_id,
                batch_size=100,
            )
            # Filing's committee_id should match the seeded committee
            filing = _select_filing_by_fec_id(db_conn, file_num)
            assert filing is not None
            assert filing["committee_id"] == committee.id

            # Transaction's committee_id should also match
            txns = _select_transactions_by_filing_fec_id(db_conn, file_num)
            assert len(txns) == 1
            assert txns[0]["committee_id"] == committee.id
        finally:
            _cleanup_schedule_e_test_data(
                db_conn,
                [committee.fec_committee_id],
                [candidate.fec_candidate_id],
                [file_num],
            )

    def test_candidate_linked_via_cand_id(
        self,
        db_conn: psycopg.Connection,
        data_source_id: UUID,
        tmp_path: Path,
    ) -> None:
        committee = _seed_committee(db_conn, _unique_committee_fec_id(), "Cand Link PAC")
        candidate = _seed_candidate(db_conn, _unique_candidate_fec_id("H"), "Cand Link Target")
        file_num = _unique_file_num()
        rows = [
            _make_row(
                spe_id=committee.fec_committee_id,
                cand_id=candidate.fec_candidate_id,
                file_num=file_num,
            ),
        ]
        csv_path = _write_schedule_e_csv(tmp_path, rows)

        try:
            load_schedule_e(
                db_conn,
                csv_path,
                cycle=2024,
                data_source_id=data_source_id,
                batch_size=100,
            )
            txns = _select_transactions_by_filing_fec_id(db_conn, file_num)
            assert len(txns) == 1
            assert txns[0]["recipient_candidate_id"] == candidate.id
        finally:
            _cleanup_schedule_e_test_data(
                db_conn,
                [committee.fec_committee_id],
                [candidate.fec_candidate_id],
                [file_num],
            )

    def test_missing_candidate_tolerance(
        self,
        db_conn: psycopg.Connection,
        data_source_id: UUID,
        tmp_path: Path,
    ) -> None:
        """Row with empty cand_id should still be ingested with recipient_candidate_id=None."""
        committee = _seed_committee(db_conn, _unique_committee_fec_id(), "No Cand PAC")
        file_num = _unique_file_num()
        rows = [
            _make_row(
                spe_id=committee.fec_committee_id,
                cand_id="",
                cand_name="Unknown",
                file_num=file_num,
            ),
        ]
        csv_path = _write_schedule_e_csv(tmp_path, rows)

        try:
            result = load_schedule_e(
                db_conn,
                csv_path,
                cycle=2024,
                data_source_id=data_source_id,
                batch_size=100,
            )
            assert result.inserted == 1
            assert result.errors == 0

            txns = _select_transactions_by_filing_fec_id(db_conn, file_num)
            assert len(txns) == 1
            assert txns[0]["recipient_candidate_id"] is None
        finally:
            _cleanup_schedule_e_test_data(
                db_conn,
                [committee.fec_committee_id],
                [],
                [file_num],
            )

    def test_unresolvable_candidate_still_ingests(
        self,
        db_conn: psycopg.Connection,
        data_source_id: UUID,
        tmp_path: Path,
    ) -> None:
        """Row with a cand_id not in cf.candidate should still be ingested."""
        committee = _seed_committee(db_conn, _unique_committee_fec_id(), "Unresolved Cand PAC")
        nonexistent_cand_id = _unique_candidate_fec_id("H")
        file_num = _unique_file_num()
        rows = [
            _make_row(
                spe_id=committee.fec_committee_id,
                cand_id=nonexistent_cand_id,
                file_num=file_num,
            ),
        ]
        csv_path = _write_schedule_e_csv(tmp_path, rows)

        try:
            result = load_schedule_e(
                db_conn,
                csv_path,
                cycle=2024,
                data_source_id=data_source_id,
                batch_size=100,
            )
            # Row should be ingested (candidate is optional)
            assert result.inserted == 1
            assert result.errors == 0

            txns = _select_transactions_by_filing_fec_id(db_conn, file_num)
            assert len(txns) == 1
            assert txns[0]["recipient_candidate_id"] is None
        finally:
            _cleanup_schedule_e_test_data(
                db_conn,
                [committee.fec_committee_id],
                [],
                [file_num],
            )

    def test_missing_committee_skips_row(
        self,
        db_conn: psycopg.Connection,
        data_source_id: UUID,
        tmp_path: Path,
    ) -> None:
        """Row whose spe_id has no matching cf.committee row should be skipped."""
        nonexistent_committee_id = _unique_committee_fec_id()
        file_num = _unique_file_num()
        rows = [
            _make_row(
                spe_id=nonexistent_committee_id,
                cand_id="",
                file_num=file_num,
            ),
        ]
        csv_path = _write_schedule_e_csv(tmp_path, rows)

        try:
            result = load_schedule_e(
                db_conn,
                csv_path,
                cycle=2024,
                data_source_id=data_source_id,
                batch_size=100,
            )
            # Row should be skipped (committee is required)
            assert result.inserted == 0
            assert result.errors == 1 or result.skipped == 1

            # No filing or transaction should exist
            filing = _select_filing_by_fec_id(db_conn, file_num)
            assert filing is None
        finally:
            _cleanup_schedule_e_test_data(db_conn, [], [], [file_num])


class TestScheduleEAmendmentNormalization:
    """Amendment indicator normalization: A1-A4 → A, empty → N."""

    def test_amndt_ind_n_passthrough(
        self,
        db_conn: psycopg.Connection,
        data_source_id: UUID,
        tmp_path: Path,
    ) -> None:
        committee = _seed_committee(db_conn, _unique_committee_fec_id(), "N Amndt PAC")
        file_num = _unique_file_num()
        rows = [
            _make_row(
                spe_id=committee.fec_committee_id,
                file_num=file_num,
                amndt_ind="N",
            ),
        ]
        csv_path = _write_schedule_e_csv(tmp_path, rows)

        try:
            load_schedule_e(
                db_conn,
                csv_path,
                cycle=2024,
                data_source_id=data_source_id,
                batch_size=100,
            )
            filing = _select_filing_by_fec_id(db_conn, file_num)
            assert filing is not None
            assert filing["amendment_indicator"] == "N"

            txns = _select_transactions_by_filing_fec_id(db_conn, file_num)
            assert len(txns) == 1
            assert txns[0]["amendment_indicator"] == "N"
        finally:
            _cleanup_schedule_e_test_data(
                db_conn,
                [committee.fec_committee_id],
                [],
                [file_num],
            )

    def test_amndt_ind_a1_normalized_to_a(
        self,
        db_conn: psycopg.Connection,
        data_source_id: UUID,
        tmp_path: Path,
    ) -> None:
        committee = _seed_committee(db_conn, _unique_committee_fec_id(), "A1 Amndt PAC")
        # Need a prev_file_num for a valid amendment
        orig_file_num = _unique_file_num()
        amend_file_num = _unique_file_num()
        rows = [
            _make_row(
                spe_id=committee.fec_committee_id,
                file_num=amend_file_num,
                amndt_ind="A1",
                prev_file_num=orig_file_num,
            ),
        ]
        csv_path = _write_schedule_e_csv(tmp_path, rows)

        try:
            load_schedule_e(
                db_conn,
                csv_path,
                cycle=2024,
                data_source_id=data_source_id,
                batch_size=100,
            )
            filing = _select_filing_by_fec_id(db_conn, amend_file_num)
            assert filing is not None
            assert filing["amendment_indicator"] == "A"

            txns = _select_transactions_by_filing_fec_id(db_conn, amend_file_num)
            assert len(txns) == 1
            assert txns[0]["amendment_indicator"] == "A"
        finally:
            _cleanup_schedule_e_test_data(
                db_conn,
                [committee.fec_committee_id],
                [],
                [orig_file_num, amend_file_num],
            )

    def test_amndt_ind_a4_normalized_to_a(
        self,
        db_conn: psycopg.Connection,
        data_source_id: UUID,
        tmp_path: Path,
    ) -> None:
        committee = _seed_committee(db_conn, _unique_committee_fec_id(), "A4 Amndt PAC")
        orig_file_num = _unique_file_num()
        amend_file_num = _unique_file_num()
        rows = [
            _make_row(
                spe_id=committee.fec_committee_id,
                file_num=amend_file_num,
                amndt_ind="A4",
                prev_file_num=orig_file_num,
            ),
        ]
        csv_path = _write_schedule_e_csv(tmp_path, rows)

        try:
            load_schedule_e(
                db_conn,
                csv_path,
                cycle=2024,
                data_source_id=data_source_id,
                batch_size=100,
            )
            filing = _select_filing_by_fec_id(db_conn, amend_file_num)
            assert filing is not None
            assert filing["amendment_indicator"] == "A"
        finally:
            _cleanup_schedule_e_test_data(
                db_conn,
                [committee.fec_committee_id],
                [],
                [orig_file_num, amend_file_num],
            )

    def test_amndt_ind_empty_normalized_to_n(
        self,
        db_conn: psycopg.Connection,
        data_source_id: UUID,
        tmp_path: Path,
    ) -> None:
        committee = _seed_committee(db_conn, _unique_committee_fec_id(), "Empty Amndt PAC")
        file_num = _unique_file_num()
        rows = [
            _make_row(
                spe_id=committee.fec_committee_id,
                file_num=file_num,
                amndt_ind="",
            ),
        ]
        csv_path = _write_schedule_e_csv(tmp_path, rows)

        try:
            load_schedule_e(
                db_conn,
                csv_path,
                cycle=2024,
                data_source_id=data_source_id,
                batch_size=100,
            )
            filing = _select_filing_by_fec_id(db_conn, file_num)
            assert filing is not None
            assert filing["amendment_indicator"] == "N"

            txns = _select_transactions_by_filing_fec_id(db_conn, file_num)
            assert len(txns) == 1
            assert txns[0]["amendment_indicator"] == "N"
        finally:
            _cleanup_schedule_e_test_data(
                db_conn,
                [committee.fec_committee_id],
                [],
                [file_num],
            )


class TestScheduleEFilingUpsert:
    """Filing upsert and prev_file_num supersession."""

    def test_filing_upsert_with_prev_file_num(
        self,
        db_conn: psycopg.Connection,
        data_source_id: UUID,
        tmp_path: Path,
    ) -> None:
        """An amendment filing with prev_file_num should link to the original filing."""
        committee = _seed_committee(db_conn, _unique_committee_fec_id(), "Supersession PAC")
        orig_file_num = _unique_file_num()
        amend_file_num = _unique_file_num()

        # First ingest the original filing
        original_rows = [
            _make_row(
                spe_id=committee.fec_committee_id,
                file_num=orig_file_num,
                amndt_ind="N",
            ),
        ]
        csv_1 = _write_schedule_e_csv(tmp_path, original_rows)
        load_schedule_e(
            db_conn,
            csv_1,
            cycle=2024,
            data_source_id=data_source_id,
            batch_size=100,
        )

        # Then ingest the amendment
        amendment_rows = [
            _make_row(
                spe_id=committee.fec_committee_id,
                file_num=amend_file_num,
                amndt_ind="A1",
                prev_file_num=orig_file_num,
            ),
        ]
        csv_2 = _write_schedule_e_csv(tmp_path, amendment_rows)

        try:
            load_schedule_e(
                db_conn,
                csv_2,
                cycle=2024,
                data_source_id=data_source_id,
                batch_size=100,
            )
            orig_filing = _select_filing_by_fec_id(db_conn, orig_file_num)
            amend_filing = _select_filing_by_fec_id(db_conn, amend_file_num)
            assert orig_filing is not None
            assert amend_filing is not None
            assert amend_filing["amendment_indicator"] == "A"
            # The amendment should reference the original filing
            assert amend_filing["amended_from_filing_id"] == orig_filing["id"]
        finally:
            _cleanup_schedule_e_test_data(
                db_conn,
                [committee.fec_committee_id],
                [],
                [orig_file_num, amend_file_num],
            )


class TestScheduleETransactionFields:
    """Transaction-level field population: dissemination_date, aggregate_amount."""

    def test_dissemination_date_populated(
        self,
        db_conn: psycopg.Connection,
        data_source_id: UUID,
        tmp_path: Path,
    ) -> None:
        committee = _seed_committee(db_conn, _unique_committee_fec_id(), "Dissem Date PAC")
        file_num = _unique_file_num()
        rows = [
            _make_row(
                spe_id=committee.fec_committee_id,
                file_num=file_num,
                dissem_dt="14-OCT-24",
            ),
        ]
        csv_path = _write_schedule_e_csv(tmp_path, rows)

        try:
            load_schedule_e(
                db_conn,
                csv_path,
                cycle=2024,
                data_source_id=data_source_id,
                batch_size=100,
            )
            txns = _select_transactions_by_filing_fec_id(db_conn, file_num)
            assert len(txns) == 1
            assert txns[0]["dissemination_date"] == date(2024, 10, 14)
        finally:
            _cleanup_schedule_e_test_data(
                db_conn,
                [committee.fec_committee_id],
                [],
                [file_num],
            )

    def test_empty_dissemination_date_is_null(
        self,
        db_conn: psycopg.Connection,
        data_source_id: UUID,
        tmp_path: Path,
    ) -> None:
        committee = _seed_committee(db_conn, _unique_committee_fec_id(), "No Dissem PAC")
        file_num = _unique_file_num()
        rows = [
            _make_row(
                spe_id=committee.fec_committee_id,
                file_num=file_num,
                dissem_dt="",
            ),
        ]
        csv_path = _write_schedule_e_csv(tmp_path, rows)

        try:
            load_schedule_e(
                db_conn,
                csv_path,
                cycle=2024,
                data_source_id=data_source_id,
                batch_size=100,
            )
            txns = _select_transactions_by_filing_fec_id(db_conn, file_num)
            assert len(txns) == 1
            assert txns[0]["dissemination_date"] is None
        finally:
            _cleanup_schedule_e_test_data(
                db_conn,
                [committee.fec_committee_id],
                [],
                [file_num],
            )

    def test_aggregate_amount_populated(
        self,
        db_conn: psycopg.Connection,
        data_source_id: UUID,
        tmp_path: Path,
    ) -> None:
        committee = _seed_committee(db_conn, _unique_committee_fec_id(), "Agg Amount PAC")
        file_num = _unique_file_num()
        rows = [
            _make_row(
                spe_id=committee.fec_committee_id,
                file_num=file_num,
                agg_amo="12345.67",
            ),
        ]
        csv_path = _write_schedule_e_csv(tmp_path, rows)

        try:
            load_schedule_e(
                db_conn,
                csv_path,
                cycle=2024,
                data_source_id=data_source_id,
                batch_size=100,
            )
            txns = _select_transactions_by_filing_fec_id(db_conn, file_num)
            assert len(txns) == 1
            assert txns[0]["aggregate_amount"] == Decimal("12345.67")
        finally:
            _cleanup_schedule_e_test_data(
                db_conn,
                [committee.fec_committee_id],
                [],
                [file_num],
            )

    def test_transaction_type_is_independent_expenditure(
        self,
        db_conn: psycopg.Connection,
        data_source_id: UUID,
        tmp_path: Path,
    ) -> None:
        committee = _seed_committee(db_conn, _unique_committee_fec_id(), "TxnType PAC")
        file_num = _unique_file_num()
        rows = [
            _make_row(
                spe_id=committee.fec_committee_id,
                file_num=file_num,
            ),
        ]
        csv_path = _write_schedule_e_csv(tmp_path, rows)

        try:
            load_schedule_e(
                db_conn,
                csv_path,
                cycle=2024,
                data_source_id=data_source_id,
                batch_size=100,
            )
            txns = _select_transactions_by_filing_fec_id(db_conn, file_num)
            assert len(txns) == 1
            assert txns[0]["transaction_type"] == "Independent Expenditure"
        finally:
            _cleanup_schedule_e_test_data(
                db_conn,
                [committee.fec_committee_id],
                [],
                [file_num],
            )

    def test_expenditure_amount_and_date(
        self,
        db_conn: psycopg.Connection,
        data_source_id: UUID,
        tmp_path: Path,
    ) -> None:
        committee = _seed_committee(db_conn, _unique_committee_fec_id(), "Exp PAC")
        file_num = _unique_file_num()
        rows = [
            _make_row(
                spe_id=committee.fec_committee_id,
                file_num=file_num,
                exp_amo="9876.54",
                exp_date="27-SEP-24",
            ),
        ]
        csv_path = _write_schedule_e_csv(tmp_path, rows)

        try:
            load_schedule_e(
                db_conn,
                csv_path,
                cycle=2024,
                data_source_id=data_source_id,
                batch_size=100,
            )
            txns = _select_transactions_by_filing_fec_id(db_conn, file_num)
            assert len(txns) == 1
            assert txns[0]["amount"] == Decimal("9876.54")
            assert txns[0]["transaction_date"] == date(2024, 9, 27)
        finally:
            _cleanup_schedule_e_test_data(
                db_conn,
                [committee.fec_committee_id],
                [],
                [file_num],
            )

    def test_negative_amount_preserved(
        self,
        db_conn: psycopg.Connection,
        data_source_id: UUID,
        tmp_path: Path,
    ) -> None:
        """Negative amounts (refunds/corrections) should be stored as-is."""
        committee = _seed_committee(db_conn, _unique_committee_fec_id(), "Refund PAC")
        file_num = _unique_file_num()
        rows = [
            _make_row(
                spe_id=committee.fec_committee_id,
                file_num=file_num,
                exp_amo="-15250",
            ),
        ]
        csv_path = _write_schedule_e_csv(tmp_path, rows)

        try:
            load_schedule_e(
                db_conn,
                csv_path,
                cycle=2024,
                data_source_id=data_source_id,
                batch_size=100,
            )
            txns = _select_transactions_by_filing_fec_id(db_conn, file_num)
            assert len(txns) == 1
            assert txns[0]["amount"] == Decimal("-15250")
        finally:
            _cleanup_schedule_e_test_data(
                db_conn,
                [committee.fec_committee_id],
                [],
                [file_num],
            )


class TestScheduleEIdempotency:
    """Idempotent re-ingest: running the same file twice produces no duplicates."""

    def test_idempotent_reingest(
        self,
        db_conn: psycopg.Connection,
        data_source_id: UUID,
        tmp_path: Path,
    ) -> None:
        committee = _seed_committee(db_conn, _unique_committee_fec_id(), "Idempotent PAC")
        candidate = _seed_candidate(db_conn, _unique_candidate_fec_id("H"), "Idempotent Candidate")
        file_num = _unique_file_num()
        tran_id = _unique_tran_id()
        rows = [
            _make_row(
                spe_id=committee.fec_committee_id,
                cand_id=candidate.fec_candidate_id,
                file_num=file_num,
                tran_id=tran_id,
            ),
        ]
        csv_path = _write_schedule_e_csv(tmp_path, rows)

        try:
            result_1 = load_schedule_e(
                db_conn,
                csv_path,
                cycle=2024,
                data_source_id=data_source_id,
                batch_size=100,
            )
            assert result_1.inserted == 1

            # Second ingest of the same file
            result_2 = load_schedule_e(
                db_conn,
                csv_path,
                cycle=2024,
                data_source_id=data_source_id,
                batch_size=100,
            )
            # Should be skipped (already ingested)
            assert result_2.inserted == 0
            assert result_2.skipped >= 1

            # Still only one transaction in the DB
            txns = _select_transactions_by_filing_fec_id(db_conn, file_num)
            assert len(txns) == 1
        finally:
            _cleanup_schedule_e_test_data(
                db_conn,
                [committee.fec_committee_id],
                [candidate.fec_candidate_id],
                [file_num],
            )


class TestScheduleELimitHandling:
    """The limit parameter restricts how many rows are processed."""

    def test_limit_restricts_row_count(
        self,
        db_conn: psycopg.Connection,
        data_source_id: UUID,
        tmp_path: Path,
    ) -> None:
        committee = _seed_committee(db_conn, _unique_committee_fec_id(), "Limit PAC")
        file_num_1 = _unique_file_num()
        file_num_2 = _unique_file_num()
        file_num_3 = _unique_file_num()
        rows = [
            _make_row(spe_id=committee.fec_committee_id, file_num=file_num_1),
            _make_row(spe_id=committee.fec_committee_id, file_num=file_num_2),
            _make_row(spe_id=committee.fec_committee_id, file_num=file_num_3),
        ]
        csv_path = _write_schedule_e_csv(tmp_path, rows)

        try:
            result = load_schedule_e(
                db_conn,
                csv_path,
                cycle=2024,
                data_source_id=data_source_id,
                batch_size=100,
                limit=2,
            )
            # Only 2 of 3 rows should be processed
            assert result.inserted == 2

            # Verify only 2 filings exist
            count = _count_transactions_for_committee(db_conn, committee.id)
            assert count == 2
        finally:
            _cleanup_schedule_e_test_data(
                db_conn,
                [committee.fec_committee_id],
                [],
                [file_num_1, file_num_2, file_num_3],
            )

    def test_limit_none_processes_all_rows(
        self,
        db_conn: psycopg.Connection,
        data_source_id: UUID,
        tmp_path: Path,
    ) -> None:
        committee = _seed_committee(db_conn, _unique_committee_fec_id(), "No Limit PAC")
        file_nums = [_unique_file_num() for _ in range(4)]
        rows = [_make_row(spe_id=committee.fec_committee_id, file_num=fn) for fn in file_nums]
        csv_path = _write_schedule_e_csv(tmp_path, rows)

        try:
            result = load_schedule_e(
                db_conn,
                csv_path,
                cycle=2024,
                data_source_id=data_source_id,
                batch_size=100,
                limit=None,
            )
            assert result.inserted == 4
        finally:
            _cleanup_schedule_e_test_data(
                db_conn,
                [committee.fec_committee_id],
                [],
                file_nums,
            )
