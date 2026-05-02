from __future__ import annotations

import inspect
from pathlib import Path
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import psycopg
import pytest

from scripts.register_roster_pilot_sources import register_roster_pilot_sources

from domains.civics.loaders.official_rosters import loader
from domains.civics.loaders.official_rosters._test_fixtures import fixture_path, seed_persons
from domains.civics.loaders.official_rosters.loader import (
    TARGET_RESOLVER_REGISTRY,
    _ResolvedTarget,
    _resolve_durham_city_council_target,
    _resolve_nc_house_target,
)
from domains.civics.loaders.official_rosters.parsers import NormalizedRosterRow


def _durham_row() -> NormalizedRosterRow:
    return NormalizedRosterRow(
        member_name="Leonardo Williams",
        role_label="Mayor",
        district_number=None,
        bio_url="https://www.durhamnc.gov/1329/About-the-Mayor",
        portrait_url=None,
    )


def _nc_house_row(district_number: str) -> NormalizedRosterRow:
    return NormalizedRosterRow(
        member_name="Julia C. Howard",
        role_label=f"State Representative District {district_number}",
        district_number=district_number,
        bio_url="https://www.ncleg.gov/Members/Biography/H/53",
        portrait_url=None,
    )


def _sample_division(source_record_id: UUID) -> loader.ElectoralDivision:
    return loader.ElectoralDivision(
        name="nc_municipal_durham",
        division_type="municipal",
        state="NC",
        source_record_id=source_record_id,
    )


def _sample_office(source_record_id: UUID) -> loader.Office:
    return loader.Office(
        name="durham_nc_mayor",
        office_level="municipal",
        title="Mayor",
        state="NC",
        number_of_seats=1,
        source_record_id=source_record_id,
    )


def test_target_resolver_registry_keys_are_exactly_durham_and_nc_house() -> None:
    assert set(TARGET_RESOLVER_REGISTRY.keys()) == {"durham_city_council", "nc_house"}


@pytest.mark.integration
def test_shared_seed_persons_helper_preserves_existing_fixture_name_contract(
    db_conn: psycopg.Connection,
) -> None:
    seed_persons(
        db_conn,
        ("Julia C. Howard", "Mitchell S. Setzer"),
    )

    with db_conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT canonical_name, first_name, last_name
            FROM core.person
            WHERE canonical_name IN (%s, %s)
            ORDER BY canonical_name
            """,
            ("Julia C. Howard", "Mitchell S. Setzer"),
        )
        rows = cursor.fetchall()

    assert rows == [
        ("Julia C. Howard", "Julia", "Howard"),
        ("Mitchell S. Setzer", "Mitchell", "Setzer"),
    ]


def test_target_resolver_registry_values_resolve_to_existing_functions() -> None:
    assert callable(TARGET_RESOLVER_REGISTRY["durham_city_council"])
    assert callable(TARGET_RESOLVER_REGISTRY["nc_house"])
    assert TARGET_RESOLVER_REGISTRY["durham_city_council"] is _resolve_durham_city_council_target
    assert TARGET_RESOLVER_REGISTRY["nc_house"] is _resolve_nc_house_target

    for resolver in TARGET_RESOLVER_REGISTRY.values():
        signature = inspect.signature(resolver)
        assert list(signature.parameters.keys()) == ["row", "source_record_id"]


def test_resolved_target_raises_when_both_office_and_office_id_are_set() -> None:
    source_record_id = uuid4()

    with pytest.raises(ValueError):
        _ResolvedTarget(
            office=_sample_office(source_record_id),
            office_id=uuid4(),
            electoral_division=_sample_division(source_record_id),
        )


def test_resolved_target_raises_when_neither_office_nor_office_id_is_set() -> None:
    source_record_id = uuid4()

    with pytest.raises(ValueError):
        _ResolvedTarget(
            office=None,
            office_id=None,
            electoral_division=_sample_division(source_record_id),
        )


def test_durham_and_nc_house_resolvers_keep_office_object_path() -> None:
    source_record_id = uuid4()

    durham_target = _resolve_durham_city_council_target(_durham_row(), source_record_id)
    nc_house_target = _resolve_nc_house_target(_nc_house_row("77"), source_record_id)

    assert durham_target is not None
    assert durham_target.office is not None
    assert durham_target.office_id is None

    assert nc_house_target is not None
    assert nc_house_target.office is not None
    assert nc_house_target.office_id is None


def test_registry_doc_office_id_guidance_matches_current_owner_truth() -> None:
    registry_doc = Path(__file__).with_name("REGISTRY.md").read_text(encoding="utf-8")

    # The extension contract must describe only real current owners.
    assert "domains/civics/schema/tables.sql" not in registry_doc
    assert "domains/civics/data/nc_2026_civic_calendar.yaml" not in registry_doc
    assert "[scripts/register_roster_pilot_office_links.py]" not in registry_doc
    assert "no current official-roster Python module exports deterministic office UUID constants" in registry_doc
    assert "Current TARGET_RESOLVER_REGISTRY resolvers return office object targets (office_id=None)" in registry_doc
    assert "Should official-roster loaders expose a dedicated Python module" not in registry_doc


@pytest.mark.integration
def test_harvest_uses_preseeded_office_id_without_upsert_office(
    db_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    register_roster_pilot_sources(db_conn)
    seed_persons(
        db_conn,
        ("Leonardo Williams", "Javiera Caballero", "Monique Holsey-Hyman"),
    )

    seeded_office_id = uuid4()
    with db_conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO civic.office (id, name, office_level, title, state, number_of_seats)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                seeded_office_id,
                f"seeded_durham_office_{seeded_office_id.hex[:12]}",
                "municipal",
                "Mayor",
                "NC",
                1,
            ),
        )

    def _resolver_with_preseeded_office_id(
        row: NormalizedRosterRow,
        source_record_id: UUID,
    ) -> _ResolvedTarget | None:
        return _ResolvedTarget(
            office=None,
            office_id=seeded_office_id,
            electoral_division=_sample_division(source_record_id),
        )

    patched_registry = dict(loader.TARGET_RESOLVER_REGISTRY)
    patched_registry["durham_city_council"] = _resolver_with_preseeded_office_id
    office_upsert_mock = MagicMock(name="upsert_office")
    monkeypatch.setattr(loader, "TARGET_RESOLVER_REGISTRY", patched_registry)
    monkeypatch.setattr(loader, "upsert_office", office_upsert_mock)

    result = loader.harvest_official_roster(
        db_conn,
        source_id="nc_durham_city_council_roster",
        fixture_path=fixture_path("nc_durham_city_council.html"),
        dry_run=False,
        fetch_bytes=lambda url, *, timeout_seconds: None,
    )

    office_upsert_mock.assert_not_called()
    assert result.source_record_id is not None

    with db_conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM civic.officeholding
            WHERE source_record_id = %s
              AND office_id = %s
            """,
            (result.source_record_id, seeded_office_id),
        )
        matching_officeholding_count = cursor.fetchone()[0]

    assert matching_officeholding_count >= 1

    def _typed_fetcher_that_fails_internally(url: str, *, timeout_seconds: float) -> bytes | None:
        del url, timeout_seconds
        raise TypeError("fetcher-internal-type-error")

    with pytest.raises(TypeError, match="fetcher-internal-type-error"):
        loader.harvest_official_roster(
            db_conn,
            source_id="nc_durham_city_council_roster",
            fixture_path=None,
            dry_run=True,
            fetch_bytes=_typed_fetcher_that_fails_internally,
        )
