from __future__ import annotations

from pathlib import Path

import psycopg
import pytest

from scripts.register_roster_pilot_sources import register_roster_pilot_sources
from domains.civics.loaders.official_rosters import loader as roster_loader


pytestmark = pytest.mark.integration

_FIXTURE_DIR = Path(__file__).resolve().parents[4] / "tests" / "fixtures" / "roster"


def _fixture_path(name: str) -> Path:
    return _FIXTURE_DIR / name


def _active_snapshot_count(connection: psycopg.Connection, source_id: str) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM core.source_record sr
            JOIN core.data_source ds ON ds.id = sr.data_source_id
            WHERE ds.notes::jsonb->>'registry_source_id' = %s
              AND sr.source_record_key = %s
              AND sr.superseded_by IS NULL
            """,
            (source_id, f"official_roster:{source_id}:snapshot"),
        )
        return cursor.fetchone()[0]


def _seed_cli_people(connection: psycopg.Connection) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO core.person (id, canonical_name, first_name, last_name, identifiers)
            VALUES
                (gen_random_uuid(), 'Leonardo Williams', 'Leonardo', 'Williams', '{}'::jsonb),
                (gen_random_uuid(), 'Javiera Caballero', 'Javiera', 'Caballero', '{}'::jsonb),
                (gen_random_uuid(), 'Shanetta Burris', 'Shanetta', 'Burris', '{}'::jsonb),
                (gen_random_uuid(), 'Terry S. Johnson', 'Terry', 'Johnson', '{}'::jsonb),
                (gen_random_uuid(), 'Chad Pennell', 'Chad', 'Pennell', '{}'::jsonb),
                (gen_random_uuid(), 'Shane Glenn', 'Shane', 'Glenn', '{}'::jsonb)
            ON CONFLICT DO NOTHING
            """
        )


def test_cli_missing_fixture_returns_nonzero(capsys: pytest.CaptureFixture[str]) -> None:
    from domains.civics.loaders.official_rosters.cli import main

    exit_code = main(
        [
            "--source-id",
            "nc_durham_city_council_roster",
            "--fixture-path",
            "tests/fixtures/roster/does-not-exist.html",
            "--dry-run",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "Fixture HTML file not found" in captured.err


def test_cli_dry_run_does_not_write(db_conn: psycopg.Connection) -> None:
    from domains.civics.loaders.official_rosters import cli

    register_roster_pilot_sources(db_conn)

    class _NoCommitNoCloseConnection:
        def __init__(self, connection: psycopg.Connection) -> None:
            self._connection = connection

        def commit(self) -> None:
            return None

        def close(self) -> None:
            return None

        def __getattr__(self, name: str) -> object:
            return getattr(self._connection, name)

    before = _active_snapshot_count(db_conn, "nc_durham_city_council_roster")
    cli.get_connection = lambda **_: _NoCommitNoCloseConnection(db_conn)
    exit_code = cli.main(
        [
            "--source-id",
            "nc_durham_city_council_roster",
            "--fixture-path",
            str(_fixture_path("nc_durham_city_council.html")),
            "--dry-run",
        ]
    )
    after = _active_snapshot_count(db_conn, "nc_durham_city_council_roster")

    assert exit_code == 0
    assert before == after


def test_cli_write_mode_is_rerun_safe(db_conn: psycopg.Connection) -> None:
    from domains.civics.loaders.official_rosters import cli

    register_roster_pilot_sources(db_conn)
    _seed_cli_people(db_conn)

    class _NoCloseConnection:
        def __init__(self, connection: psycopg.Connection) -> None:
            self._connection = connection

        def close(self) -> None:
            return None

        def __getattr__(self, name: str) -> object:
            return getattr(self._connection, name)

    cli.get_connection = lambda **_: _NoCloseConnection(db_conn)
    first = cli.main(
        [
            "--source-id",
            "nc_durham_city_council_roster",
            "--fixture-path",
            str(_fixture_path("nc_durham_city_council.html")),
        ]
    )
    second = cli.main(
        [
            "--source-id",
            "nc_durham_city_council_roster",
            "--fixture-path",
            str(_fixture_path("nc_durham_city_council.html")),
        ]
    )

    assert first == 0
    assert second == 0
    assert _active_snapshot_count(db_conn, "nc_durham_city_council_roster") == 1


def test_cli_harvests_nc_sheriffs_source_id(db_conn: psycopg.Connection) -> None:
    from domains.civics.loaders.official_rosters import cli

    register_roster_pilot_sources(db_conn)
    _seed_cli_people(db_conn)

    class _NoCloseConnection:
        def __init__(self, connection: psycopg.Connection) -> None:
            self._connection = connection

        def close(self) -> None:
            return None

        def __getattr__(self, name: str) -> object:
            return getattr(self._connection, name)

    cli.get_connection = lambda **_: _NoCloseConnection(db_conn)
    exit_code = cli.main(
        [
            "--source-id",
            "nc_sheriffs_association_roster",
            "--fixture-path",
            str(_fixture_path("nc_sheriffs_directory.html")),
        ]
    )

    assert exit_code == 0
    assert _active_snapshot_count(db_conn, "nc_sheriffs_association_roster") == 1


def test_cli_source_id_dispatches_to_loader_path(monkeypatch: pytest.MonkeyPatch) -> None:
    from domains.civics.loaders.official_rosters import cli

    class _FakeConnection:
        def transaction(self):  # type: ignore[no-untyped-def]
            class _Ctx:
                def __enter__(self_inner):  # type: ignore[no-untyped-def]
                    return None

                def __exit__(self_inner, exc_type, exc, tb):  # type: ignore[no-untyped-def]
                    return False

            return _Ctx()

        def rollback(self) -> None:
            return None

        def commit(self) -> None:
            return None

        def close(self) -> None:
            return None

    calls: list[tuple[str, str | None, bool, float]] = []

    monkeypatch.setattr(cli, "get_connection", lambda **_: _FakeConnection())
    monkeypatch.setattr(
        cli,
        "harvest_official_roster",
        lambda conn, *, source_id, fixture_path, dry_run, timeout_seconds: calls.append(
            (source_id, str(fixture_path) if fixture_path is not None else None, dry_run, timeout_seconds)
        )
        or roster_loader.OfficialRosterHarvestResult(
            source_id=source_id,
            body_key="nc_school_board",
            member_count=7,
            resolved_member_count=7,
            unresolved_member_count=0,
            officeholding_upserts=7,
            portrait_writes=0,
            source_record_key=f"official_roster:{source_id}:snapshot",
            source_record_id=None,
            source_record_inserted=False,
            dry_run=dry_run,
        ),
    )
    exit_code = cli.main(
        [
            "--source-id",
            "nc_wake_county_commissioners_roster",
            "--fixture-path",
            str(_fixture_path("wake_county_commissioners.html")),
        ]
    )

    assert exit_code == 0
    assert calls == [
        ("nc_wake_county_commissioners_roster", str(_fixture_path("wake_county_commissioners.html")), False, 30.0)
    ]
