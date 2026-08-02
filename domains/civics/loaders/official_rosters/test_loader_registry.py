from __future__ import annotations

import inspect
from pathlib import Path
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import psycopg
import pytest
import yaml

from scripts.register_roster_pilot_sources import register_roster_pilot_sources

from domains.campaign_finance.ingest.federal_officeholder_loader import (
    _DIVISION_US_CONGRESSIONAL_DISTRICTS,
    _DIVISION_US_STATEWIDE,
    _OFFICE_US_HOUSE,
    _OFFICE_US_SENATE,
)
from domains.civics.loaders.official_rosters import loader
from domains.civics.loaders.official_rosters._test_fixtures import fixture_path, seed_persons
from domains.civics.loaders.official_rosters.loader import (
    TARGET_RESOLVER_REGISTRY,
    _ResolvedTarget,
    _resolve_durham_city_council_target,
    _resolve_nc_house_target,
)
from domains.civics.loaders.official_rosters.parsers import NormalizedRosterRow
from domains.civics.loaders.official_rosters.source_registry import list_nc_roster_source_metadata
from domains.civics.tests.statewide_roster_stage5_support import EXPECTED_OFFICEHOLDING_COUNTS_BY_SOURCE

_LAUNCH_SCOPE_ROSTER_SOURCE_IDS = (
    "nc_apex_town_council_roster",
    "nc_carrboro_town_council_roster",
    "nc_cary_town_council_roster",
    "nc_chapel_hill_town_council_roster",
    "nc_chccs_school_board_roster",
    "nc_dps_school_board_roster",
    "nc_durham_city_council_roster",
    "nc_durham_county_commissioners_roster",
    "nc_fuquay_varina_town_council_roster",
    "nc_garner_town_council_roster",
    "nc_general_assembly_house_roster",
    "nc_hillsborough_town_council_roster",
    "nc_holly_springs_town_council_roster",
    "nc_knightdale_town_council_roster",
    "nc_morrisville_town_council_roster",
    "nc_ocs_school_board_roster",
    "nc_orange_county_commissioners_roster",
    "nc_raleigh_city_council_roster",
    "nc_registers_of_deeds_roster",
    "nc_rolesville_town_council_roster",
    "nc_sheriffs_association_roster",
    "nc_soil_water_supervisors_roster",
    "nc_wake_county_commissioners_roster",
    "nc_wake_forest_town_council_roster",
    "nc_wcpss_school_board_roster",
    "nc_wendell_town_council_roster",
    "nc_zebulon_town_council_roster",
)


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


def _us_house_nc_row(district_number: str) -> NormalizedRosterRow:
    return NormalizedRosterRow(
        member_name=f"NC Representative {district_number}",
        role_label=f"United States Representative District {district_number}",
        district_number=district_number,
        bio_url=None,
        portrait_url=None,
    )


def _us_senate_nc_row(member_name: str) -> NormalizedRosterRow:
    return NormalizedRosterRow(
        member_name=member_name,
        role_label="United States Senator",
        district_number="Class 2",
        bio_url=None,
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


def _launch_scope_roster_bootstrap_by_source_id() -> dict[str, dict[str, object]]:
    sources_payload = yaml.safe_load((Path(__file__).resolve().parents[4] / "sources.yaml").read_text(encoding="utf-8"))
    jurisdictions = sources_payload.get("jurisdictions", [])
    nc_jurisdiction = next(
        jurisdiction
        for jurisdiction in jurisdictions
        if isinstance(jurisdiction, dict) and jurisdiction.get("scope") == "NC"
    )

    roster_bootstrap_by_source_id: dict[str, dict[str, object]] = {}
    for source in nc_jurisdiction.get("sources", []):
        if not isinstance(source, dict):
            continue
        source_id = source.get("source_id")
        roster_bootstrap = source.get("roster_bootstrap")
        if not isinstance(source_id, str) or not isinstance(roster_bootstrap, dict):
            continue
        roster_bootstrap_by_source_id[source_id] = roster_bootstrap

    return roster_bootstrap_by_source_id


def test_target_resolver_registry_keys_cover_stage2_reachable_body_keys() -> None:
    expected_body_keys = {
        "durham_city_council",
        "nc_house",
        "us_house_nc",
        "us_senate_nc_class_ii",
        "us_senate_nc_class_iii",
        "nc_senate",
        "nc_gov",
        "nc_lt_gov",
        "nc_attorney_general",
        "nc_sec_of_state",
        "nc_treasurer",
        "nc_auditor",
        "nc_supt_pub_instr",
        "nc_ag_commissioner",
        "nc_ins_commissioner",
        "nc_labor_commissioner",
        "nc_supreme_court",
        "nc_court_of_appeals",
    }

    assert set(EXPECTED_OFFICEHOLDING_COUNTS_BY_SOURCE) < expected_body_keys
    assert set(TARGET_RESOLVER_REGISTRY) == expected_body_keys


def test_sources_yaml_launch_scope_roster_bootstrap_includes_required_metadata_fields() -> None:
    roster_bootstrap_by_source_id = _launch_scope_roster_bootstrap_by_source_id()

    assert set(roster_bootstrap_by_source_id) == set(_LAUNCH_SCOPE_ROSTER_SOURCE_IDS)
    for source_id in _LAUNCH_SCOPE_ROSTER_SOURCE_IDS:
        roster_bootstrap = roster_bootstrap_by_source_id[source_id]
        for field_name in ("body_key", "source_url", "cadence", "jurisdiction"):
            field_value = roster_bootstrap.get(field_name)
            assert isinstance(field_value, str)
            assert field_value.strip() != ""
        assert roster_bootstrap["jurisdiction"] == "state/NC"


def test_list_nc_roster_source_metadata_matches_launch_scope_sources_yaml_contract() -> None:
    roster_bootstrap_by_source_id = _launch_scope_roster_bootstrap_by_source_id()
    metadata_by_source_id = {metadata.source_id: metadata for metadata in list_nc_roster_source_metadata()}

    assert set(metadata_by_source_id) == set(_LAUNCH_SCOPE_ROSTER_SOURCE_IDS)
    for source_id in _LAUNCH_SCOPE_ROSTER_SOURCE_IDS:
        metadata = metadata_by_source_id[source_id]
        roster_bootstrap = roster_bootstrap_by_source_id[source_id]
        assert metadata.body_key == roster_bootstrap["body_key"]
        assert metadata.source_url == roster_bootstrap["source_url"]
        assert metadata.cadence == roster_bootstrap["cadence"]
        assert metadata.jurisdiction == roster_bootstrap["jurisdiction"]


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


def test_statewide_resolver_registry_is_built_from_one_declarative_specification() -> None:
    assert loader._STATEWIDE_OFFICE_SPEC_BY_BODY_KEY == {
        "nc_gov": ("nc_governor", "state", "Governor", 1),
        "nc_lt_gov": ("nc_lieutenant_governor", "state", "Lieutenant Governor", 1),
        "nc_attorney_general": ("nc_attorney_general", "state", "Attorney General", 1),
        "nc_sec_of_state": ("nc_secretary_of_state", "state", "Secretary of State", 1),
        "nc_treasurer": ("nc_treasurer", "state", "State Treasurer", 1),
        "nc_auditor": ("nc_auditor", "state", "State Auditor", 1),
        "nc_supt_pub_instr": (
            "nc_superintendent_public_instruction",
            "state",
            "State Superintendent of Public Instruction",
            1,
        ),
        "nc_ag_commissioner": ("nc_agriculture_commissioner", "state", "Commissioner of Agriculture", 1),
        "nc_ins_commissioner": ("nc_insurance_commissioner", "state", "Commissioner of Insurance", 1),
        "nc_labor_commissioner": ("nc_labor_commissioner", "state", "Commissioner of Labor", 1),
        "nc_supreme_court": ("nc_supreme_court_justice", "state", "Justice", 7),
        "nc_court_of_appeals": ("nc_court_of_appeals_judge", "state", "Judge", 15),
    }


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


def test_federal_resolvers_reuse_canonical_federal_office_and_division_chain() -> None:
    source_record_id = uuid4()

    house_target = loader._resolve_target(
        "us_house_nc",
        NormalizedRosterRow(
            member_name="Donald Davis",
            role_label="United States Representative District 1",
            district_number="1",
            bio_url=None,
            portrait_url=None,
        ),
        source_record_id,
    )
    senate_target = loader._resolve_target(
        "us_senate_nc_class_ii",
        NormalizedRosterRow(
            member_name="Thom Tillis",
            role_label="United States Senator",
            district_number="Class 2",
            bio_url="https://tillis.senate.gov",
            portrait_url=None,
        ),
        source_record_id,
    )

    assert house_target is not None
    assert house_target.office is None
    assert house_target.office_id == _OFFICE_US_HOUSE
    assert house_target.electoral_division.name == "nc_cd_01"
    assert house_target.electoral_division.division_type == "congressional_district"
    assert house_target.electoral_division.state == "NC"
    assert house_target.electoral_division.district_number == "01"
    assert house_target.electoral_division.parent_id == _DIVISION_US_CONGRESSIONAL_DISTRICTS

    assert senate_target is not None
    assert senate_target.office is None
    assert senate_target.office_id == _OFFICE_US_SENATE
    assert senate_target.electoral_division.name == "nc"
    assert senate_target.electoral_division.division_type == "statewide"
    assert senate_target.electoral_division.state == "NC"
    assert senate_target.electoral_division.district_number is None
    assert senate_target.electoral_division.parent_id == _DIVISION_US_STATEWIDE


def test_canonical_federal_targets_declare_nc_scoped_seat_limits() -> None:
    # The canonical federal offices hold 435/100 national seats, but an NC roster
    # source may only ever fill the NC slice of them.
    assert loader._ROSTER_SOURCE_SEAT_LIMIT_BY_BODY_KEY["us_house_nc"] == 14
    assert loader._ROSTER_SOURCE_SEAT_LIMIT_BY_BODY_KEY["us_senate_nc_class_ii"] == 1
    assert loader._ROSTER_SOURCE_SEAT_LIMIT_BY_BODY_KEY["us_senate_nc_class_iii"] == 1


def test_us_house_nc_capacity_gate_accepts_the_full_fourteen_district_delegation() -> None:
    loader._validate_roster_target_capacity(
        "us_house_nc",
        [_us_house_nc_row(str(district_number)) for district_number in range(1, 15)],
    )


def test_us_house_nc_capacity_gate_rejects_more_districts_than_nc_holds() -> None:
    with pytest.raises(
        ValueError,
        match=r"us_house_nc roster resolved 15 districts for an office with 14 seats",
    ):
        loader._validate_roster_target_capacity(
            "us_house_nc",
            [_us_house_nc_row(str(district_number)) for district_number in range(1, 16)],
        )


def test_us_house_nc_capacity_gate_rejects_duplicate_district_rows() -> None:
    rows = [_us_house_nc_row(str(district_number)) for district_number in range(1, 14)]
    rows.append(_us_house_nc_row("3"))

    with pytest.raises(
        ValueError,
        match=r"us_house_nc roster has multiple current members for districts: 03",
    ):
        loader._validate_roster_target_capacity("us_house_nc", rows)


@pytest.mark.parametrize("body_key", ["us_senate_nc_class_ii", "us_senate_nc_class_iii"])
def test_us_senate_nc_class_capacity_gate_accepts_exactly_one_current_holder(body_key: str) -> None:
    loader._validate_roster_target_capacity(body_key, [_us_senate_nc_row("Thom Tillis")])


@pytest.mark.parametrize("body_key", ["us_senate_nc_class_ii", "us_senate_nc_class_iii"])
def test_us_senate_nc_class_capacity_gate_rejects_two_current_holders(body_key: str) -> None:
    with pytest.raises(
        ValueError,
        match=rf"{body_key} roster resolved 2 current holders for a source seat limit of 1",
    ):
        loader._validate_roster_target_capacity(
            body_key,
            [_us_senate_nc_row("Thom Tillis"), _us_senate_nc_row("Ted Budd")],
        )


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
