"""Integration tests for NCSBE ENRS contest-results loader."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest

from core.db import insert_data_source
from core.types.python.models import DataSource


pytestmark = pytest.mark.integration


_REPO_ROOT = Path(__file__).resolve().parents[3]
_SOURCE_METADATA_PATH = _REPO_ROOT / "domains" / "civics" / "loaders" / "ncsbe_results_sources.yaml"


def _insert_ncsbe_data_source(conn: psycopg.Connection, *, source_id: str) -> UUID:
    data_source = DataSource(
        domain="civics",
        jurisdiction="us/nc",
        name=f"NCSBE ENRS {source_id}",
        source_url=f"https://example.test/{source_id}",
        notes=(
            "{"
            f"\"registry_source_id\": \"{source_id}\""
            "}"
        ),
    )
    insert_data_source(conn, data_source)
    return data_source.id


def _insert_stale_ncsbe_data_source_identity(conn: psycopg.Connection, *, source_id: str) -> UUID:
    data_source = DataSource(
        domain="civics",
        jurisdiction="state/NC",
        name=f"NC SBE ENRS {source_id}",
        source_url=f"https://example.test/stale/{source_id}",
        notes=(
            "{"
            f"\"registry_source_id\": \"{source_id}\""
            "}"
        ),
    )
    insert_data_source(conn, data_source)
    return data_source.id


def _seed_contest(
    conn: psycopg.Connection,
    *,
    contest_id: UUID,
    contest_name: str,
    election_date: str,
    election_type: str,
    number_of_seats: int,
) -> None:
    office_id = uuid4()
    conn.execute(
        """
        INSERT INTO civic.office (id, name, office_level, state, number_of_seats)
        VALUES (%s, %s, 'state', 'NC', 1)
        """,
        (office_id, f"office_{contest_id.hex[:8]}"),
    )
    conn.execute(
        """
        INSERT INTO civic.contest (
            id,
            name,
            election_date,
            election_type,
            office_id,
            number_of_seats
        )
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (contest_id, contest_name, election_date, election_type, office_id, number_of_seats),
    )


def _contest_result_rows(conn: psycopg.Connection, contest_id: UUID) -> list[tuple[str, int, bool]]:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT candidate_name, votes, is_winner
            FROM civic.contest_result
            WHERE contest_id = %s
            ORDER BY votes DESC, candidate_name
            """,
            (contest_id,),
        )
        return cursor.fetchall()


def _contest_result_count_by_source_record(
    conn: psycopg.Connection, source_record_ids: list[UUID]
) -> dict[UUID, int]:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT source_record_id, COUNT(*)::int
            FROM civic.contest_result
            WHERE source_record_id = ANY(%s)
            GROUP BY source_record_id
            """,
            (source_record_ids,),
        )
        rows = cursor.fetchall()
    return {row[0]: row[1] for row in rows}


def test_runtime_contest_result_contract_includes_stage2_columns(db_conn: psycopg.Connection) -> None:
    expected_columns = {
        "candidate_name",
        "party",
        "votes",
        "vote_pct",
        "is_certified",
        "is_winner",
    }
    with db_conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'civic'
              AND table_name = 'contest_result'
            """
        )
        present_columns = {row[0] for row in cursor.fetchall()}

    missing_columns = expected_columns - present_columns
    assert not missing_columns, f"Missing Stage 2 contest_result columns: {sorted(missing_columns)}"


def test_cli_main_passes_non_empty_rows_to_loader(
    monkeypatch: pytest.MonkeyPatch,
    ncsbe_contract_rows_by_file: dict[str, list[dict[str, str]]],
) -> None:
    from domains.civics.loaders import ncsbe_results

    captured_rows: dict[str, list[dict[str, str]]] = {}

    class _StubConn:
        def commit(self) -> None:
            return None

        def rollback(self) -> None:
            return None

        def close(self) -> None:
            return None

    def _stub_load_ncsbe_results(*_args, **kwargs):
        nonlocal captured_rows
        captured_rows = kwargs["raw_rows_by_file"]
        return ncsbe_results.NcsbeResultsLoadSummary(
            source_record_count=0,
            result_row_count=0,
            contest_count=0,
            source_record_ids_by_file={},
        )

    fixture_path = (
        _REPO_ROOT
        / "docs"
        / "research"
        / "artifacts"
        / "2026_04_30_dwo_past_results"
        / "ncsbe"
        / "raw_extracts"
        / "enrs_2024_11_05_general_sample.csv"
    )
    assert fixture_path.name in ncsbe_contract_rows_by_file

    monkeypatch.setattr(ncsbe_results, "get_connection", lambda: _StubConn())
    monkeypatch.setattr(ncsbe_results, "load_ncsbe_results", _stub_load_ncsbe_results)

    exit_code = ncsbe_results.main(["--raw-csv", str(fixture_path)])
    assert exit_code == 0
    assert fixture_path.name in captured_rows
    assert captured_rows[fixture_path.name], "CLI must pass parsed rows into loader execution"


def test_loader_hard_fails_for_unknown_fixture_file(
    db_conn: psycopg.Connection,
    ncsbe_contract_rows_by_file: dict[str, list[dict[str, str]]],
) -> None:
    from domains.civics.loaders.ncsbe_results import load_ncsbe_results

    _insert_ncsbe_data_source(db_conn, source_id="nc_ncsbe_enrs_2024_11_05_general")

    with pytest.raises(ValueError, match="Unknown fixture files"):
        load_ncsbe_results(
            db_conn,
            metadata_path=_SOURCE_METADATA_PATH,
            raw_rows_by_file={
                "unknown_fixture.csv": ncsbe_contract_rows_by_file["enrs_2024_11_05_general_sample.csv"]
            },
            pull_date=datetime(2026, 4, 30, tzinfo=timezone.utc),
        )


def test_loader_hard_fails_when_contest_mapping_is_unresolved(
    db_conn: psycopg.Connection,
    ncsbe_contract_rows_by_file: dict[str, list[dict[str, str]]],
) -> None:
    from domains.civics.loaders.ncsbe_results import load_ncsbe_results

    _insert_ncsbe_data_source(db_conn, source_id="nc_ncsbe_enrs_2024_11_05_general")

    with pytest.raises(ValueError, match="Unresolved contest mapping"):
        load_ncsbe_results(
            db_conn,
            metadata_path=_SOURCE_METADATA_PATH,
            raw_rows_by_file={"enrs_2024_11_05_general_sample.csv": ncsbe_contract_rows_by_file["enrs_2024_11_05_general_sample.csv"]},
            pull_date=datetime(2026, 4, 30, tzinfo=timezone.utc),
        )


def test_deterministic_contest_match_key_and_seat_aware_winner_flags(
    db_conn: psycopg.Connection,
    ncsbe_contract_rows_by_file: dict[str, list[dict[str, str]]],
) -> None:
    from domains.civics.loaders.ncsbe_results import build_contest_match_key, load_ncsbe_results

    us_senate_contest_id = UUID("11111111-1111-4111-8111-111111111111")
    attorney_general_contest_id = UUID("22222222-2222-4222-8222-222222222222")
    governor_contest_id = UUID("33333333-3333-4333-8333-333333333333")

    _seed_contest(
        db_conn,
        contest_id=us_senate_contest_id,
        contest_name="US SENATE",
        election_date="2022-11-08",
        election_type="general",
        number_of_seats=1,
    )
    _seed_contest(
        db_conn,
        contest_id=attorney_general_contest_id,
        contest_name="ATTORNEY GENERAL DEM",
        election_date="2024-03-05",
        election_type="primary",
        number_of_seats=2,
    )
    _seed_contest(
        db_conn,
        contest_id=governor_contest_id,
        contest_name="NC GOVERNOR",
        election_date="2024-11-05",
        election_type="general",
        number_of_seats=1,
    )

    key_a = build_contest_match_key(
        election_date="2022-11-08",
        election_label="General Election",
        jurisdiction_name="Wake",
        contest_name="US SENATE",
        contest_external_id="2001",
    )
    key_b = build_contest_match_key(
        election_date="2022-11-08",
        election_label="general election",
        jurisdiction_name=" wake ",
        contest_name="US SENATE",
        contest_external_id="2001",
    )
    assert key_a == key_b

    _insert_ncsbe_data_source(db_conn, source_id="nc_ncsbe_enrs_2022_11_08_general")
    _insert_ncsbe_data_source(db_conn, source_id="nc_ncsbe_enrs_2024_03_05_primary")
    _insert_ncsbe_data_source(db_conn, source_id="nc_ncsbe_enrs_2024_11_05_general")

    primary_rows_with_loser = list(ncsbe_contract_rows_by_file["enrs_2024_03_05_primary_sample.csv"])
    primary_rows_with_loser.append(
        {
            "election_date": "2024-03-05",
            "election_name": "Primary Election",
            "county": "Wake",
            "contest_name": "ATTORNEY GENERAL DEM",
            "contest_id": "3001",
            "candidate_name": "THIRD PLACE SAMPLE",
            "candidate_party": "DEM",
            "votes": "1024",
            "percent": "0.68",
            "certified": "true",
        }
    )

    load_ncsbe_results(
        db_conn,
        metadata_path=_SOURCE_METADATA_PATH,
        raw_rows_by_file={
            "enrs_2022_11_08_general_sample.csv": ncsbe_contract_rows_by_file["enrs_2022_11_08_general_sample.csv"],
            "enrs_2024_03_05_primary_sample.csv": primary_rows_with_loser,
            "enrs_2024_11_05_general_sample.csv": ncsbe_contract_rows_by_file["enrs_2024_11_05_general_sample.csv"][:2],
        },
        pull_date=datetime(2026, 4, 30, tzinfo=timezone.utc),
    )

    senate_rows = _contest_result_rows(db_conn, us_senate_contest_id)
    assert senate_rows == [
        ("TED BUDD", 361304, True),
        ("CHERI BEASLEY", 312832, False),
    ]

    attorney_rows = _contest_result_rows(db_conn, attorney_general_contest_id)
    assert attorney_rows == [
        ("JEFF JACKSON", 97751, True),
        ("SATANA DEBERRY", 52957, True),
        ("THIRD PLACE SAMPLE", 1024, False),
    ]

    governor_rows = _contest_result_rows(db_conn, governor_contest_id)
    assert governor_rows == [
        ("JOSH STEIN", 452111, True),
        ("MARK ROBINSON", 423112, False),
    ]

    with db_conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT c.id, c.number_of_seats, COUNT(*) FILTER (WHERE cr.is_winner) AS winner_count
            FROM civic.contest_result AS cr
            JOIN civic.contest AS c ON c.id = cr.contest_id
            WHERE c.id = ANY(%s)
            GROUP BY c.id, c.number_of_seats
            ORDER BY c.id
            """,
            ([attorney_general_contest_id, governor_contest_id],),
        )
        winner_rows = cursor.fetchall()
    assert winner_rows == [
        (attorney_general_contest_id, 2, 2),
        (governor_contest_id, 1, 1),
    ]


def test_loader_inserts_exact_per_fixture_counts_for_2022_2024_elections(
    db_conn: psycopg.Connection,
    ncsbe_contract_rows_by_file: dict[str, list[dict[str, str]]],
) -> None:
    from domains.civics.loaders.ncsbe_results import load_ncsbe_results

    _seed_contest(
        db_conn,
        contest_id=UUID("44444444-4444-4444-8444-444444444444"),
        contest_name="US SENATE",
        election_date="2022-11-08",
        election_type="general",
        number_of_seats=1,
    )
    _seed_contest(
        db_conn,
        contest_id=UUID("55555555-5555-4555-8555-555555555555"),
        contest_name="ATTORNEY GENERAL DEM",
        election_date="2024-03-05",
        election_type="primary",
        number_of_seats=2,
    )
    _seed_contest(
        db_conn,
        contest_id=UUID("66666666-6666-4666-8666-666666666666"),
        contest_name="NC GOVERNOR",
        election_date="2024-11-05",
        election_type="general",
        number_of_seats=1,
    )
    _seed_contest(
        db_conn,
        contest_id=UUID("77777777-7777-4777-8777-777777777777"),
        contest_name="UNMAPPED SAMPLE CONTEST",
        election_date="2024-11-05",
        election_type="general",
        number_of_seats=1,
    )
    _insert_ncsbe_data_source(db_conn, source_id="nc_ncsbe_enrs_2022_11_08_general")
    _insert_ncsbe_data_source(db_conn, source_id="nc_ncsbe_enrs_2024_03_05_primary")
    _insert_ncsbe_data_source(db_conn, source_id="nc_ncsbe_enrs_2024_11_05_general")

    summary = load_ncsbe_results(
        db_conn,
        metadata_path=_SOURCE_METADATA_PATH,
        raw_rows_by_file={
            "enrs_2022_11_08_general_sample.csv": ncsbe_contract_rows_by_file["enrs_2022_11_08_general_sample.csv"],
            "enrs_2024_03_05_primary_sample.csv": ncsbe_contract_rows_by_file["enrs_2024_03_05_primary_sample.csv"],
            "enrs_2024_11_05_general_sample.csv": ncsbe_contract_rows_by_file["enrs_2024_11_05_general_sample.csv"],
        },
        pull_date=datetime(2026, 4, 30, tzinfo=timezone.utc),
    )

    assert summary.source_record_count == 3
    assert summary.result_row_count == 7
    assert summary.contest_count == 4

    counts_by_source_record = _contest_result_count_by_source_record(
        db_conn,
        list(summary.source_record_ids_by_file.values()),
    )
    assert counts_by_source_record[summary.source_record_ids_by_file["enrs_2022_11_08_general_sample.csv"]] == 2
    assert counts_by_source_record[summary.source_record_ids_by_file["enrs_2024_03_05_primary_sample.csv"]] == 2
    assert counts_by_source_record[summary.source_record_ids_by_file["enrs_2024_11_05_general_sample.csv"]] == 3


def test_loader_rerun_is_idempotent_on_uq_contest_result_canonical(
    db_conn: psycopg.Connection,
    ncsbe_contract_rows_by_file: dict[str, list[dict[str, str]]],
) -> None:
    from domains.civics.loaders.ncsbe_results import load_ncsbe_results

    governor_contest_id = UUID("33333333-3333-4333-8333-333333333333")
    _seed_contest(
        db_conn,
        contest_id=governor_contest_id,
        contest_name="NC GOVERNOR",
        election_date="2024-11-05",
        election_type="general",
        number_of_seats=1,
    )
    _insert_ncsbe_data_source(db_conn, source_id="nc_ncsbe_enrs_2024_11_05_general")

    first = load_ncsbe_results(
        db_conn,
        metadata_path=_SOURCE_METADATA_PATH,
        raw_rows_by_file={"enrs_2024_11_05_general_sample.csv": ncsbe_contract_rows_by_file["enrs_2024_11_05_general_sample.csv"][:2]},
        pull_date=datetime(2026, 4, 30, tzinfo=timezone.utc),
    )
    second = load_ncsbe_results(
        db_conn,
        metadata_path=_SOURCE_METADATA_PATH,
        raw_rows_by_file={"enrs_2024_11_05_general_sample.csv": ncsbe_contract_rows_by_file["enrs_2024_11_05_general_sample.csv"][:2]},
        pull_date=datetime(2026, 4, 30, tzinfo=timezone.utc),
    )

    assert first.result_row_count == second.result_row_count == 2

    with db_conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM civic.contest_result
            WHERE contest_id = %s
            """,
            (governor_contest_id,),
        )
        assert cursor.fetchone()[0] == 2


def test_loader_replaces_stale_data_source_identity_before_source_record_insert(
    db_conn: psycopg.Connection,
    ncsbe_contract_rows_by_file: dict[str, list[dict[str, str]]],
) -> None:
    from domains.civics.loaders.ncsbe_results import load_ncsbe_results

    source_id = "nc_ncsbe_enrs_2024_11_05_general"
    stale_data_source_id = _insert_stale_ncsbe_data_source_identity(db_conn, source_id=source_id)
    _insert_ncsbe_data_source(db_conn, source_id=source_id)

    governor_contest_id = UUID("44444444-4444-4444-8444-444444444444")
    _seed_contest(
        db_conn,
        contest_id=governor_contest_id,
        contest_name="NC GOVERNOR",
        election_date="2024-11-05",
        election_type="general",
        number_of_seats=1,
    )

    summary = load_ncsbe_results(
        db_conn,
        metadata_path=_SOURCE_METADATA_PATH,
        raw_rows_by_file={"enrs_2024_11_05_general_sample.csv": ncsbe_contract_rows_by_file["enrs_2024_11_05_general_sample.csv"][:2]},
        pull_date=datetime(2026, 4, 30, tzinfo=timezone.utc),
    )

    with db_conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT id
            FROM core.data_source
            WHERE domain = %s
              AND jurisdiction = %s
              AND name = %s
            """,
            (
                "civics",
                "us/nc",
                f"NCSBE ENRS {source_id}",
            ),
        )
        canonical_row = cursor.fetchone()
    assert canonical_row is not None
    canonical_data_source_id = canonical_row[0]

    assert summary.source_record_ids_by_file["enrs_2024_11_05_general_sample.csv"] is not None
    assert canonical_data_source_id != stale_data_source_id

    with db_conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT data_source_id
            FROM core.source_record
            WHERE id = %s
            """,
            (summary.source_record_ids_by_file["enrs_2024_11_05_general_sample.csv"],),
        )
        assert cursor.fetchone()[0] == canonical_data_source_id
