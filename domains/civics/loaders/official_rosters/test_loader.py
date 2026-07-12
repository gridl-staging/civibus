from __future__ import annotations

import json
import sys
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from scripts.register_roster_pilot_sources import register_roster_pilot_sources

from domains.civics.ingest import upsert_electoral_division, upsert_office, upsert_officeholding
from domains.civics.loaders.official_rosters.loader import harvest_official_roster
from domains.civics.loaders.official_rosters import loader as roster_loader
from domains.civics.loaders.official_rosters.parsers import parse_roster_rows
from domains.civics.types import ElectoralDivision, Office, Officeholding


pytestmark = pytest.mark.integration

_FIXTURE_DIR = Path(__file__).resolve().parents[4] / "tests" / "fixtures" / "roster"
_STAGE2_ARTIFACT_DIR = roster_loader._ROSTER_ARTIFACT_DIR
_MANIFEST_PATH = _STAGE2_ARTIFACT_DIR / "canonical_seat_manifest.json"
_STAGE3_RESOLUTION_EXPECTATIONS_PATH = _STAGE2_ARTIFACT_DIR / "stage3_resolution_subset.json"


def _fixture_path(name: str) -> Path:
    return _FIXTURE_DIR / name


def _manifest_sources() -> dict[str, dict[str, object]]:
    payload = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
    return {source["source_id"]: source for source in payload["sources"]}


def _manifest_artifact_path(source: dict[str, object]) -> Path:
    return Path(__file__).resolve().parents[4] / Path(str(source["artifact_path"]))


def _stage3_resolution_expectations() -> dict[str, list[str]]:
    payload = json.loads(_STAGE3_RESOLUTION_EXPECTATIONS_PATH.read_text(encoding="utf-8"))
    return {str(source_id): [str(name) for name in names] for source_id, names in payload.items()}


def _resolved_expected_name_count(
    connection: psycopg.Connection,
    *,
    source: dict[str, object],
    expected_names: set[str],
) -> int:
    rows = parse_roster_rows(
        body_key=str(source["body_key"]),
        source_url=str(source["source_url"]),
        html=_manifest_artifact_path(source).read_text(encoding="utf-8"),
    )
    return sum(
        1
        for row in rows
        if row.member_name in expected_names and roster_loader._find_existing_person_id(connection, row) is not None
    )


def _manifest_target_cases() -> list[tuple[str, str, str, str, int, str, str]]:
    cases: list[tuple[str, str, str, str, int, str, str]] = []
    office_name_by_body_key = {
        "nc_sheriffs": "nc_county_sheriff",
        "nc_registers_of_deeds": "nc_county_register_of_deeds",
        "nc_county_commissioners": "nc_county_commissioner",
        "nc_soil_water_supervisors": "nc_county_soil_water_supervisor",
        "nc_municipal_council": "nc_municipal_council_member",
        "nc_school_board": "nc_school_board_member",
    }
    for source in _manifest_sources().values():
        body_key = str(source["body_key"])
        if body_key not in office_name_by_body_key:
            continue
        division_name = str(source.get("division_name", "Alamance"))
        cases.append(
            (
                str(source["source_id"]),
                body_key,
                str(source["office_level"]),
                division_name,
                str(source["title"]),
                int(source["number_of_seats"]),
                str(source["division_type"]),
                office_name_by_body_key[body_key],
            )
        )
    return cases


def _select_counts_for_source(connection: psycopg.Connection, source_id: str) -> tuple[int, int, int]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                (SELECT COUNT(*)
                 FROM core.source_record sr
                 JOIN core.data_source ds ON ds.id = sr.data_source_id
                 WHERE ds.notes::jsonb->>'registry_source_id' = %s),
                (SELECT COUNT(*)
                 FROM core.person_portrait pp
                 JOIN core.source_record sr ON sr.id = pp.source_record_id
                 JOIN core.data_source ds ON ds.id = sr.data_source_id
                 WHERE ds.notes::jsonb->>'registry_source_id' = %s),
                (SELECT COUNT(*)
                 FROM civic.officeholding oh
                 JOIN core.source_record sr ON sr.id = oh.source_record_id
                 JOIN core.data_source ds ON ds.id = sr.data_source_id
                 WHERE ds.notes::jsonb->>'registry_source_id' = %s)
            """,
            (source_id, source_id, source_id),
        )
        row = cursor.fetchone()
    assert row is not None
    return row[0], row[1], row[2]


def _seed_people_for_manifest_source_fixture(connection: psycopg.Connection, source: dict[str, object]) -> None:
    source_url = str(source["source_url"])
    body_key = str(source["body_key"])
    html = _manifest_artifact_path(source).read_text(encoding="utf-8")
    rows = parse_roster_rows(body_key=body_key, source_url=source_url, html=html)
    unique_names = sorted({row.member_name for row in rows if row.member_name.strip() != ""})
    with connection.cursor() as cursor:
        for name in unique_names:
            first_name, last_name = roster_loader._split_name(name)
            if first_name is None or last_name is None:
                continue
            cursor.execute(
                """
                INSERT INTO core.person (id, canonical_name, first_name, last_name, identifiers)
                VALUES (gen_random_uuid(), %s, %s, %s, '{}'::jsonb)
                ON CONFLICT DO NOTHING
                """,
                (name, first_name, last_name),
            )


def _seed_persons_for_fixture_rows(connection: psycopg.Connection) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO core.person (id, canonical_name, first_name, last_name, identifiers)
            VALUES
                (gen_random_uuid(), 'Leonardo Williams', 'Leonardo', 'Williams', '{}'::jsonb),
                (gen_random_uuid(), 'Julia C. Howard', 'Julia', 'Howard', '{}'::jsonb),
                (gen_random_uuid(), 'Mitchell S. Setzer', 'Mitchell', 'Setzer', '{}'::jsonb),
                (gen_random_uuid(), 'Becky Carney', 'Becky', 'Carney', '{}'::jsonb),
                (gen_random_uuid(), 'Terry S. Johnson', 'Terry', 'Johnson', '{}'::jsonb),
                (gen_random_uuid(), 'Chad Pennell', 'Chad', 'Pennell', '{}'::jsonb),
                (gen_random_uuid(), 'Shane Glenn', 'Shane', 'Glenn', '{}'::jsonb)
            ON CONFLICT DO NOTHING
            """
        )


def _seed_authoritative_persons_for_stage2_roster_rows(connection: psycopg.Connection) -> None:
    commissioner_names = {
        "Michelle Burton",
        "Mike Lee",
        "Nida Allam",
        "Stephen Valentine",
        "Wendy Jacobs",
        "Cheryl Stallings",
        "Don Mial",
        "Safiyah Jackson",
        "Shinica Thomas",
        "Susan Evans",
        "Tara Waters",
        "Vickie Adamson",
        "Amy Fowler",
        "Earl McKee",
        "Jamezetta Bedford",
        "Jean Hamilton",
        "Marilyn Carter",
        "Phyllis Portie-Ascott",
        "Sally Greene",
    }
    unique_names = sorted(
        commissioner_names
        | {
            "George Tarkington",
            "Abner Wayne Staples",
            "Don Lee Keaton",
        }
    )
    with connection.cursor() as cursor:
        for name in unique_names:
            first_name, last_name = roster_loader._split_name(name)
            if first_name is None or last_name is None:
                continue
            cursor.execute(
                """
                INSERT INTO core.person (id, canonical_name, first_name, last_name, identifiers)
                VALUES (gen_random_uuid(), %s, %s, %s, '{}'::jsonb)
                ON CONFLICT DO NOTHING
                """,
                (name, first_name, last_name),
            )


def _seed_authoritative_persons_for_stage3_subset(
    connection: psycopg.Connection,
    source_ids: list[str],
) -> None:
    expected_names_by_source_id = _stage3_resolution_expectations()
    unique_names = sorted({name for source_id in source_ids for name in expected_names_by_source_id.get(source_id, [])})
    with connection.cursor() as cursor:
        for name in unique_names:
            first_name, last_name = roster_loader._split_name(name)
            if first_name is None or last_name is None:
                continue
            cursor.execute(
                """
                INSERT INTO core.person (id, canonical_name, first_name, last_name, identifiers)
                VALUES (gen_random_uuid(), %s, %s, %s, '{}'::jsonb)
                ON CONFLICT DO NOTHING
                """,
                (name, first_name, last_name),
            )


def _remove_non_seeded_name_matches_for_stage3_subset(
    connection: psycopg.Connection,
    source_ids: list[str],
) -> None:
    """Keep Stage 3 seeded-resolution assertions deterministic in shared DB test environments."""
    expected_names_by_source_id = _stage3_resolution_expectations()
    globally_expected_names = {
        expected_name for expected_names in expected_names_by_source_id.values() for expected_name in expected_names
    }
    manifest_sources = _manifest_sources()
    removable_names: set[str] = set()
    removable_bio_urls: set[str] = set()
    for source_id in source_ids:
        source = manifest_sources[source_id]
        expected_names = set(expected_names_by_source_id.get(source_id, []))
        rows = parse_roster_rows(
            body_key=str(source["body_key"]),
            source_url=str(source["source_url"]),
            html=_manifest_artifact_path(source).read_text(encoding="utf-8"),
        )
        for row in rows:
            if row.member_name not in expected_names and row.member_name not in globally_expected_names:
                removable_names.add(row.member_name)
            if row.bio_url is not None and row.member_name not in expected_names:
                removable_bio_urls.add(row.bio_url)

    with connection.cursor() as cursor:
        for name in sorted(removable_names):
            cursor.execute(
                """
                UPDATE core.person
                SET first_name = first_name || ' stage3_unmatched',
                    canonical_name = canonical_name || ' [stage3_unmatched]'
                WHERE canonical_name = %s
                """,
                (name,),
            )
        if removable_bio_urls:
            cursor.execute(
                """
                UPDATE core.person
                SET identifiers = identifiers - 'roster_bio_url'
                WHERE identifiers ? 'roster_bio_url'
                  AND identifiers->>'roster_bio_url' = ANY(%s)
                """,
                (sorted(removable_bio_urls),),
            )


def test_dry_run_is_no_write_and_uses_shared_contract_rows(db_conn: psycopg.Connection) -> None:
    register_roster_pilot_sources(db_conn)

    before = _select_counts_for_source(db_conn, "nc_durham_city_council_roster")

    result = harvest_official_roster(
        db_conn,
        source_id="nc_durham_city_council_roster",
        fixture_path=_fixture_path("nc_durham_city_council.html"),
        dry_run=True,
    )

    after = _select_counts_for_source(db_conn, "nc_durham_city_council_roster")
    assert before == after
    assert result.member_count == 3
    assert result.source_record_inserted is False


def test_write_mode_is_rerun_safe_for_source_snapshot_and_officeholdings(db_conn: psycopg.Connection) -> None:
    canonical_member_count = 3
    register_roster_pilot_sources(db_conn)
    _seed_persons_for_fixture_rows(db_conn)
    before_counts = _select_counts_for_source(db_conn, "nc_general_assembly_house_roster")

    first = harvest_official_roster(
        db_conn,
        source_id="nc_general_assembly_house_roster",
        fixture_path=_fixture_path("nc_general_assembly_house.html"),
        dry_run=False,
        fetch_bytes=lambda url, *, timeout_seconds: None,
    )
    after_first_counts = _select_counts_for_source(db_conn, "nc_general_assembly_house_roster")
    second = harvest_official_roster(
        db_conn,
        source_id="nc_general_assembly_house_roster",
        fixture_path=_fixture_path("nc_general_assembly_house.html"),
        dry_run=False,
        fetch_bytes=lambda url, *, timeout_seconds: None,
    )

    assert first.member_count == 3
    assert first.resolved_member_count == 3
    assert second.source_record_inserted is False
    assert first.source_record_key == "official_roster:nc_general_assembly_house_roster:snapshot"
    assert second.source_record_key == first.source_record_key
    assert first.source_record_id == second.source_record_id

    with db_conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM core.source_record sr
            JOIN core.data_source ds ON ds.id = sr.data_source_id
            WHERE ds.notes::jsonb->>'registry_source_id' = %s
              AND sr.source_record_key = %s
              AND sr.superseded_by IS NULL
            """,
            (
                "nc_general_assembly_house_roster",
                "official_roster:nc_general_assembly_house_roster:snapshot",
            ),
        )
        active_snapshots = cursor.fetchone()[0]

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM civic.officeholding oh
            WHERE oh.source_record_id = %s
            """,
            (first.source_record_id,),
        )
        officeholding_rows = cursor.fetchone()[0]

    after_second_counts = _select_counts_for_source(db_conn, "nc_general_assembly_house_roster")
    if before_counts[0] == 0:
        assert after_first_counts[0] == before_counts[0] + 1
    else:
        assert after_first_counts[0] == before_counts[0]
    assert after_second_counts[0] == after_first_counts[0]
    assert active_snapshots == 1
    assert officeholding_rows == canonical_member_count
    assert after_second_counts[2] == after_first_counts[2]
    assert after_second_counts[1] == before_counts[1]


def test_loader_module_does_not_reference_legacy_bridge_or_scripts() -> None:
    import inspect

    from domains.civics.loaders.official_rosters import loader

    source = inspect.getsource(loader)
    assert "office_roster_link" not in source
    assert "scripts/harvest_roster_pilot_nc.py" not in source
    assert "scripts/register_roster_pilot_office_links.py" not in source


def test_manifest_lookup_helpers_share_single_cached_manifest_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    read_count = 0
    manifest_payload = {
        "sources": [
            {
                "body_key": "nc_municipal_council",
                "division_name": "Chapel Hill",
                "number_of_seats": 8,
                "title": "Town Council Member",
            },
            {
                "body_key": "nc_school_board",
                "division_name": "Durham Public Schools",
                "number_of_seats": 7,
                "title": "School Board Member",
            },
        ]
    }

    def _counted_read_text(_path: Path, *, encoding: str = "utf-8") -> str:
        nonlocal read_count
        read_count += 1
        return json.dumps(manifest_payload)

    monkeypatch.setattr(roster_loader.Path, "read_text", _counted_read_text)
    roster_loader._manifest_division_seats.cache_clear()
    roster_loader._manifest_division_titles.cache_clear()
    if hasattr(roster_loader, "_manifest_sources_payload"):
        roster_loader._manifest_sources_payload.cache_clear()
    if hasattr(roster_loader, "manifest_member_counts_by_source_id"):
        roster_loader.manifest_member_counts_by_source_id.cache_clear()
    if hasattr(roster_loader, "_manifest_division_names"):
        roster_loader._manifest_division_names.cache_clear()

    seats = roster_loader._manifest_division_seats()
    titles = roster_loader._manifest_division_titles()

    assert seats[("nc_municipal_council", "chapel hill")] == 8
    assert titles[("nc_school_board", "durham public schools")] == "School Board Member"
    assert read_count == 1
    roster_loader._manifest_division_seats.cache_clear()
    roster_loader._manifest_division_titles.cache_clear()
    if hasattr(roster_loader, "_manifest_sources_payload"):
        roster_loader._manifest_sources_payload.cache_clear()
    if hasattr(roster_loader, "manifest_member_counts_by_source_id"):
        roster_loader.manifest_member_counts_by_source_id.cache_clear()
    if hasattr(roster_loader, "_manifest_division_names"):
        roster_loader._manifest_division_names.cache_clear()


def test_reported_member_count_raises_on_registers_manifest_miss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = roster_loader.RosterSourceDefinition(
        data_source_id=uuid4(),
        source_id="nc_registers_of_deeds_roster",
        source_name="NC Registers of Deeds",
        source_url="https://example.org/registers",
        body_key="nc_registers_of_deeds",
    )
    monkeypatch.setattr(
        roster_loader,
        "manifest_member_counts_by_source_id",
        lambda: {},
    )
    monkeypatch.setattr(
        roster_loader,
        "_manifest_launch_scope_source_ids",
        lambda: {"nc_registers_of_deeds_roster"},
    )

    with pytest.raises(
        ValueError,
        match="Missing manifest member_count for registers-of-deeds source_id=nc_registers_of_deeds_roster",
    ):
        roster_loader._reported_member_count(source=source, parsed_row_count=0)


def test_reported_member_count_uses_manifest_for_launch_scope_body_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = roster_loader.RosterSourceDefinition(
        data_source_id=uuid4(),
        source_id="nc_durham_county_commissioners_roster",
        source_name="Durham County Commissioners",
        source_url="https://example.org/commissioners",
        body_key="nc_county_commissioners",
    )
    monkeypatch.setattr(
        roster_loader,
        "manifest_member_counts_by_source_id",
        lambda: {"nc_durham_county_commissioners_roster": 5},
    )
    monkeypatch.setattr(
        roster_loader,
        "_manifest_launch_scope_source_ids",
        lambda: {"nc_durham_county_commissioners_roster"},
    )

    assert roster_loader._reported_member_count(source=source, parsed_row_count=2) == 5


def test_reported_member_count_uses_parsed_count_for_non_launch_source_with_launch_body_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = roster_loader.RosterSourceDefinition(
        data_source_id=uuid4(),
        source_id="nc_county_commissioners_future_rollout_roster",
        source_name="Future Commissioners Roster",
        source_url="https://example.org/future-commissioners",
        body_key="nc_county_commissioners",
    )
    monkeypatch.setattr(
        roster_loader,
        "_manifest_launch_scope_source_ids",
        lambda: {"nc_durham_county_commissioners_roster"},
    )
    monkeypatch.setattr(
        roster_loader,
        "manifest_member_counts_by_source_id",
        lambda: {"nc_durham_county_commissioners_roster": 5},
    )

    assert roster_loader._reported_member_count(source=source, parsed_row_count=3) == 3


def test_harvest_dry_run_uses_manifest_member_count_for_launch_scope_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = roster_loader.RosterSourceDefinition(
        data_source_id=uuid4(),
        source_id="nc_durham_county_commissioners_roster",
        source_name="Durham County Commissioners",
        source_url="https://example.org/commissioners",
        body_key="nc_county_commissioners",
    )
    parsed_rows = [
        roster_loader.NormalizedRosterRow(
            member_name="Resolved Member",
            role_label="County Commissioner",
            district_number="Durham",
            bio_url=None,
            portrait_url=None,
        ),
        roster_loader.NormalizedRosterRow(
            member_name="Unresolved Member",
            role_label="County Commissioner",
            district_number="Durham",
            bio_url=None,
            portrait_url=None,
        ),
    ]
    resolved_person_id = uuid4()

    monkeypatch.setattr(roster_loader, "_select_roster_source_definition", lambda conn, *, source_id: source)
    monkeypatch.setattr(roster_loader, "_fixture_or_live_html", lambda *_args, **_kwargs: "<html></html>")
    monkeypatch.setattr(roster_loader, "parse_roster_rows", lambda **_kwargs: parsed_rows)
    monkeypatch.setattr(
        roster_loader,
        "manifest_member_counts_by_source_id",
        lambda: {"nc_durham_county_commissioners_roster": 5},
    )
    monkeypatch.setattr(
        roster_loader,
        "_manifest_launch_scope_source_ids",
        lambda: {"nc_durham_county_commissioners_roster"},
    )

    def _find_existing_person_id(_conn: object, row: roster_loader.NormalizedRosterRow) -> object | None:
        if row.member_name == "Resolved Member":
            return resolved_person_id
        return None

    monkeypatch.setattr(roster_loader, "_find_existing_person_id", _find_existing_person_id)

    result = roster_loader.harvest_official_roster(
        object(),  # dry-run path never uses connection cursor methods
        source_id="nc_durham_county_commissioners_roster",
        dry_run=True,
    )

    assert result.member_count == 5
    assert result.resolved_member_count == 1
    assert result.unresolved_member_count == 4
    assert result.officeholding_upserts == 0


def test_harvest_dry_run_clamps_unresolved_count_when_resolved_exceeds_manifest_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = roster_loader.RosterSourceDefinition(
        data_source_id=uuid4(),
        source_id="nc_durham_county_commissioners_roster",
        source_name="Durham County Commissioners",
        source_url="https://example.org/commissioners",
        body_key="nc_county_commissioners",
    )
    parsed_rows = [
        roster_loader.NormalizedRosterRow(
            member_name="Resolved Member A",
            role_label="County Commissioner",
            district_number="Durham",
            bio_url=None,
            portrait_url=None,
        ),
        roster_loader.NormalizedRosterRow(
            member_name="Resolved Member B",
            role_label="County Commissioner",
            district_number="Durham",
            bio_url=None,
            portrait_url=None,
        ),
    ]

    monkeypatch.setattr(roster_loader, "_select_roster_source_definition", lambda conn, *, source_id: source)
    monkeypatch.setattr(roster_loader, "_fixture_or_live_html", lambda *_args, **_kwargs: "<html></html>")
    monkeypatch.setattr(roster_loader, "parse_roster_rows", lambda **_kwargs: parsed_rows)
    monkeypatch.setattr(
        roster_loader,
        "_manifest_launch_scope_source_ids",
        lambda: {"nc_durham_county_commissioners_roster"},
    )
    monkeypatch.setattr(
        roster_loader,
        "manifest_member_counts_by_source_id",
        lambda: {"nc_durham_county_commissioners_roster": 1},
    )
    monkeypatch.setattr(roster_loader, "_find_existing_person_id", lambda _conn, _row: uuid4())

    result = roster_loader.harvest_official_roster(
        object(),
        source_id="nc_durham_county_commissioners_roster",
        dry_run=True,
    )

    assert result.member_count == 1
    assert result.resolved_member_count == 2
    assert result.unresolved_member_count == 0


def test_harvest_rejects_fixture_paths_outside_allowed_roster_roots(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    register_roster_pilot_sources(db_conn)
    rogue_fixture = tmp_path / "rogue_fixture.html"
    rogue_fixture.write_text("<html></html>", encoding="utf-8")

    with pytest.raises(
        ValueError,
        match="Fixture HTML path must stay within tests/fixtures/roster or docs/reference/research/artifacts/2026_04_29_dwo_county_muni",
    ):
        harvest_official_roster(
            db_conn,
            source_id="nc_durham_city_council_roster",
            fixture_path=rogue_fixture,
            dry_run=True,
        )


def test_registers_zero_row_rerun_prunes_stale_snapshot_officeholdings(
    db_conn: psycopg.Connection,
) -> None:
    register_roster_pilot_sources(db_conn)
    with db_conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO core.person (id, canonical_name, first_name, last_name, identifiers)
            VALUES (gen_random_uuid(), 'Stale Register Holder', 'Stale', 'Holder', '{}'::jsonb)
            RETURNING id
            """
        )
        person_id = cursor.fetchone()[0]

    first = harvest_official_roster(
        db_conn,
        source_id="nc_registers_of_deeds_roster",
        fixture_path=_fixture_path("nc_registers_of_deeds_directory.html"),
        dry_run=False,
        fetch_bytes=lambda url, *, timeout_seconds: None,
    )
    assert first.source_record_id is not None

    office_id = upsert_office(
        db_conn,
        Office(
            name="nc_county_register_of_deeds",
            office_level="county",
            title="Register of Deeds",
            state="NC",
            number_of_seats=1,
            source_record_id=first.source_record_id,
        ),
    )
    division_id = upsert_electoral_division(
        db_conn,
        ElectoralDivision(
            name="nc_county_test_register_county",
            division_type="county",
            state="NC",
            district_number="Test Register County",
            source_record_id=first.source_record_id,
        ),
    )
    stale_officeholding_id = upsert_officeholding(
        db_conn,
        Officeholding(
            person_id=person_id,
            office_id=office_id,
            electoral_division_id=division_id,
            holder_status="elected",
            source_record_id=first.source_record_id,
        ),
    )
    with db_conn.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) FROM civic.officeholding WHERE source_record_id = %s",
            (first.source_record_id,),
        )
        assert cursor.fetchone()[0] == 1

    second = harvest_official_roster(
        db_conn,
        source_id="nc_registers_of_deeds_roster",
        fixture_path=_fixture_path("nc_registers_of_deeds_directory.html"),
        dry_run=False,
        fetch_bytes=lambda url, *, timeout_seconds: None,
    )
    assert second.source_record_id == first.source_record_id
    assert second.resolved_member_count == 0

    with db_conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM civic.officeholding
            WHERE source_record_id = %s
            """,
            (first.source_record_id,),
        )
        after_rerun_count = cursor.fetchone()[0]
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM core.entity_source
            WHERE entity_type = 'officeholding'
              AND entity_id = %s
            """,
            (stale_officeholding_id,),
        )
        stale_links = cursor.fetchone()[0]
    assert after_rerun_count == 0
    assert stale_links == 0


@pytest.mark.parametrize(
    (
        "source_id",
        "body_key",
        "office_level",
        "district_number",
        "expected_title",
        "expected_seats",
        "expected_division_type",
        "expected_office_name",
    ),
    _manifest_target_cases(),
)
def test_resolve_target_maps_stage2_county_families_to_office_contract(
    source_id: str,
    body_key: str,
    office_level: str,
    district_number: str,
    expected_title: str,
    expected_seats: int,
    expected_division_type: str,
    expected_office_name: str,
) -> None:
    source_record_id = uuid4()
    role_label = expected_title
    if body_key == "nc_municipal_council":
        role_label = "Mayor Pro Tem"
    if body_key == "nc_school_board":
        role_label = "School Board Member District 1"
    row = roster_loader.NormalizedRosterRow(
        member_name="Placeholder Member",
        role_label=role_label,
        district_number=district_number,
        bio_url="https://example.org/member",
        portrait_url=None,
    )

    resolved = roster_loader._resolve_target(body_key, row, source_record_id)

    assert resolved is not None
    assert source_id.startswith("nc_")
    assert resolved.office.office_level == office_level
    assert resolved.office.name == expected_office_name
    assert resolved.office.title == expected_title
    assert resolved.office.number_of_seats == expected_seats
    assert resolved.electoral_division.division_type == expected_division_type
    if expected_division_type == "county":
        assert resolved.electoral_division.name == f"nc_county_{district_number.lower()}"
    if expected_division_type == "municipal":
        assert resolved.electoral_division.name == f"nc_municipal_{district_number.lower().replace(' ', '_')}"
    if expected_division_type == "school_district":
        assert resolved.electoral_division.name == f"nc_school_district_{district_number.lower().replace(' ', '_')}"
    assert resolved.electoral_division.state == "NC"


def test_stage2_harvest_dry_run_member_counts_match_manifest(db_conn: psycopg.Connection) -> None:
    register_roster_pilot_sources(db_conn)
    _seed_authoritative_persons_for_stage2_roster_rows(db_conn)
    manifest_sources = _manifest_sources()
    expected_resolution = {
        "nc_registers_of_deeds_roster": (0, 100),
        "nc_durham_county_commissioners_roster": (5, 0),
        "nc_wake_county_commissioners_roster": (7, 0),
        "nc_orange_county_commissioners_roster": (7, 0),
        "nc_soil_water_supervisors_roster": (3, 489),
    }

    for source_id, (expected_resolved, expected_unresolved) in expected_resolution.items():
        source = manifest_sources[source_id]
        result = harvest_official_roster(
            db_conn,
            source_id=source_id,
            fixture_path=_manifest_artifact_path(source),
            dry_run=True,
        )

        assert result.member_count == int(source["member_count"])
        assert result.resolved_member_count == expected_resolved
        assert result.unresolved_member_count == expected_unresolved
        assert result.officeholding_upserts == 0


def test_stage3_harvest_dry_run_member_counts_match_manifest_and_seeded_subset_resolution(
    db_conn: psycopg.Connection,
) -> None:
    register_roster_pilot_sources(db_conn)
    manifest_sources = _manifest_sources()
    stage3_source_ids = sorted(
        source_id
        for source_id, source in manifest_sources.items()
        if str(source["body_key"]) in {"durham_city_council", "nc_municipal_council", "nc_school_board"}
    )
    expected_names_by_source_id = _stage3_resolution_expectations()
    for source_id in stage3_source_ids:
        source = manifest_sources[source_id]
        result = harvest_official_roster(
            db_conn,
            source_id=source_id,
            fixture_path=_manifest_artifact_path(source),
            dry_run=True,
        )
        assert result.member_count == int(source["member_count"])
        assert result.officeholding_upserts == 0

    seeded_source_ids = sorted(expected_names_by_source_id)
    _seed_authoritative_persons_for_stage3_subset(db_conn, seeded_source_ids)
    _remove_non_seeded_name_matches_for_stage3_subset(db_conn, seeded_source_ids)

    for source_id in seeded_source_ids:
        source = manifest_sources[source_id]
        expected_resolved = len(expected_names_by_source_id[source_id])
        result = harvest_official_roster(
            db_conn,
            source_id=source_id,
            fixture_path=_manifest_artifact_path(source),
            dry_run=True,
        )

        assert result.member_count == int(source["member_count"])
        assert result.resolved_member_count == expected_resolved
        resolved_expected_names = _resolved_expected_name_count(
            db_conn,
            source=source,
            expected_names=set(expected_names_by_source_id[source_id]),
        )
        assert resolved_expected_names == expected_resolved
        assert result.unresolved_member_count == result.member_count - result.resolved_member_count
        assert result.officeholding_upserts == 0


def test_stage3_helper_ignores_cross_source_expected_name_collisions_and_strips_identifier_matches(
    db_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = sys.modules[__name__]
    source_ids = ["source_a", "source_b"]
    monkeypatch.setattr(
        module,
        "_stage3_resolution_expectations",
        lambda: {"source_a": ["Alex Stone"], "source_b": []},
    )
    monkeypatch.setattr(
        module,
        "_manifest_sources",
        lambda: {
            "source_a": {"body_key": "nc_municipal_council", "source_url": "https://example.org/a"},
            "source_b": {"body_key": "nc_municipal_council", "source_url": "https://example.org/b"},
        },
    )
    monkeypatch.setattr(module, "_manifest_artifact_path", lambda _source: _fixture_path("nc_durham_city_council.html"))

    fake_rows = {
        "https://example.org/a": [
            roster_loader.NormalizedRosterRow(
                member_name="Alex Stone",
                role_label="Council Member",
                district_number="Test A",
                bio_url="https://example.org/alex-seeded",
                portrait_url=None,
            )
        ],
        "https://example.org/b": [
            roster_loader.NormalizedRosterRow(
                member_name="Alex Stone",
                role_label="Council Member",
                district_number="Test B",
                bio_url="https://example.org/alex-ambient",
                portrait_url=None,
            ),
            roster_loader.NormalizedRosterRow(
                member_name="Jordan Vale",
                role_label="Council Member",
                district_number="Test B",
                bio_url="https://example.org/jordan-ambient",
                portrait_url=None,
            ),
        ],
    }

    monkeypatch.setattr(
        module,
        "parse_roster_rows",
        lambda *, body_key, source_url, html: fake_rows[source_url],
    )

    with db_conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO core.person (id, canonical_name, first_name, last_name, identifiers)
            VALUES
                (gen_random_uuid(), 'Alex Stone', 'Alex', 'Stone', %s::jsonb),
                (gen_random_uuid(), 'Jordan Vale', 'Jordan', 'Vale', %s::jsonb)
            """,
            (
                json.dumps({"roster_bio_url": "https://example.org/alex-ambient"}),
                json.dumps({"roster_bio_url": "https://example.org/jordan-ambient"}),
            ),
        )

    _remove_non_seeded_name_matches_for_stage3_subset(db_conn, source_ids)

    with db_conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT canonical_name, first_name, identifiers ? 'roster_bio_url'
            FROM core.person
            WHERE canonical_name LIKE 'Alex Stone%%' OR canonical_name LIKE 'Jordan Vale%%'
            ORDER BY canonical_name
            """
        )
        rows = cursor.fetchall()

    by_name = {row[0]: (row[1], row[2]) for row in rows}
    assert by_name["Alex Stone"] == ("Alex", False)
    assert by_name["Jordan Vale [stage3_unmatched]"] == ("Jordan stage3_unmatched", False)


def test_same_snapshot_rerun_keeps_existing_officeholdings_when_one_row_unresolved(
    db_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    register_roster_pilot_sources(db_conn)
    _seed_persons_for_fixture_rows(db_conn)

    first = roster_loader.harvest_official_roster(
        db_conn,
        source_id="nc_general_assembly_house_roster",
        fixture_path=_fixture_path("nc_general_assembly_house.html"),
        dry_run=False,
        fetch_bytes=lambda url, *, timeout_seconds: None,
    )
    assert first.source_record_id is not None

    with db_conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM civic.officeholding
            WHERE source_record_id = %s
            """,
            (first.source_record_id,),
        )
        before_rerun_count = cursor.fetchone()[0]
    assert before_rerun_count == 3

    original_resolver = roster_loader._resolve_person_id

    def _resolve_with_one_temporary_gap(
        connection: psycopg.Connection,
        row: roster_loader.NormalizedRosterRow,
    ) -> object:
        if row.member_name == "Becky Carney":
            return None
        return original_resolver(connection, row)

    monkeypatch.setattr(roster_loader, "_resolve_person_id", _resolve_with_one_temporary_gap)

    second = roster_loader.harvest_official_roster(
        db_conn,
        source_id="nc_general_assembly_house_roster",
        fixture_path=_fixture_path("nc_general_assembly_house.html"),
        dry_run=False,
        fetch_bytes=lambda url, *, timeout_seconds: None,
    )

    assert second.source_record_id == first.source_record_id
    assert second.resolved_member_count == 2
    with db_conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM civic.officeholding
            WHERE source_record_id = %s
            """,
            (first.source_record_id,),
        )
        after_rerun_count = cursor.fetchone()[0]

    assert after_rerun_count == before_rerun_count


@pytest.mark.parametrize(
    "source_id",
    [
        "nc_durham_county_commissioners_roster",
        "nc_apex_town_council_roster",
        "nc_wcpss_school_board_roster",
    ],
)
def test_write_mode_manifest_sources_are_idempotent_with_exact_counts(
    db_conn: psycopg.Connection,
    source_id: str,
) -> None:
    register_roster_pilot_sources(db_conn)
    source = _manifest_sources()[source_id]
    _seed_people_for_manifest_source_fixture(db_conn, source)
    expected_member_count = int(source["member_count"])
    expected_source_record_key = f"official_roster:{source_id}:snapshot"

    first = harvest_official_roster(
        db_conn,
        source_id=source_id,
        fixture_path=_manifest_artifact_path(source),
        dry_run=False,
        fetch_bytes=lambda url, *, timeout_seconds: None,
    )
    second = harvest_official_roster(
        db_conn,
        source_id=source_id,
        fixture_path=_manifest_artifact_path(source),
        dry_run=False,
        fetch_bytes=lambda url, *, timeout_seconds: None,
    )

    assert first.member_count == expected_member_count
    assert first.resolved_member_count == expected_member_count
    assert first.unresolved_member_count == 0
    assert second.member_count == expected_member_count
    assert second.resolved_member_count == expected_member_count
    assert second.unresolved_member_count == 0
    assert first.source_record_key == expected_source_record_key
    assert second.source_record_key == expected_source_record_key
    assert first.source_record_id == second.source_record_id
    assert second.source_record_inserted is False
    assert first.source_record_id is not None

    with db_conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM core.source_record sr
            JOIN core.data_source ds ON ds.id = sr.data_source_id
            WHERE ds.notes::jsonb->>'registry_source_id' = %s
              AND sr.source_record_key = %s
              AND sr.superseded_by IS NULL
            """,
            (source_id, expected_source_record_key),
        )
        active_snapshots = cursor.fetchone()[0]
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM civic.office
            WHERE source_record_id = %s
            """,
            (first.source_record_id,),
        )
        office_rows = cursor.fetchone()[0]
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM civic.officeholding
            WHERE source_record_id = %s
            """,
            (first.source_record_id,),
        )
        officeholding_rows = cursor.fetchone()[0]

    assert active_snapshots == 1
    assert office_rows == 1
    assert officeholding_rows == expected_member_count


def test_existing_person_matched_by_name_gets_identifiers_persisted(
    db_conn: psycopg.Connection,
) -> None:
    """Resolved roster matches must still persist enrichment identifiers."""
    register_roster_pilot_sources(db_conn)

    with db_conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO core.person (id, canonical_name, first_name, last_name, identifiers)
            VALUES (gen_random_uuid(), 'Julia C. Howard', 'Julia', 'Howard', '{}'::jsonb)
            ON CONFLICT DO NOTHING
            RETURNING id
            """
        )
        row = cursor.fetchone()
        assert row is not None, "seed insert must return id"
        person_id = row[0]

    result = harvest_official_roster(
        db_conn,
        source_id="nc_general_assembly_house_roster",
        fixture_path=_fixture_path("nc_general_assembly_house.html"),
        dry_run=False,
        fetch_bytes=lambda url, *, timeout_seconds: None,
    )

    assert result.resolved_member_count >= 1

    with db_conn.cursor() as cursor:
        cursor.execute(
            "SELECT identifiers FROM core.person WHERE id = %s",
            (person_id,),
        )
        identifiers = cursor.fetchone()[0]

    assert identifiers.get("roster_bio_url") is not None, (
        f"Expected roster_bio_url in identifiers for pre-existing person, got: {identifiers}"
    )
    assert identifiers.get("ncleg_member_code") is not None, (
        f"Expected ncleg_member_code in identifiers for pre-existing person, got: {identifiers}"
    )


def test_find_existing_person_id_reuses_ncleg_member_code_for_sampled_house_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = parse_roster_rows(
        body_key="nc_house",
        source_url="https://www.ncleg.gov/Members/MemberList/H",
        html=_fixture_path("nc_general_assembly_house.html").read_text(encoding="utf-8"),
    )
    sampled_rows = rows[:3]
    resolved_ids = {
        "H/53": "person-for-h53",
        "H/149": "person-for-h149",
        "H/322": "person-for-h322",
    }

    lookup_calls: list[tuple[str, str]] = []

    def _fake_find_person_by_identifier(_conn: object, key: str, value: str):
        lookup_calls.append((key, value))
        if key == "ncleg_member_code":
            return resolved_ids.get(value)
        return None

    monkeypatch.setattr(roster_loader, "find_person_by_identifier", _fake_find_person_by_identifier)
    monkeypatch.setattr(roster_loader, "find_person_by_name_and_zip", lambda *_args, **_kwargs: None)

    found = [roster_loader._find_existing_person_id(object(), row) for row in sampled_rows]

    assert found == ["person-for-h53", "person-for-h149", "person-for-h322"]
    assert ("ncleg_member_code", "H/53") in lookup_calls
    assert ("ncleg_member_code", "H/149") in lookup_calls
    assert ("ncleg_member_code", "H/322") in lookup_calls
