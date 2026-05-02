"""Unit tests for TIGER geometry loader helpers."""

from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile

import pytest


def _build_tiny_county_shapefile_zip(tmp_path: Path) -> Path:
    """Create a tiny zip that satisfies shapefile member validation."""
    payload_by_extension = {
        "shp": b"fixture-shp",
        "shx": b"fixture-shx",
        "dbf": b"fixture-dbf",
        "prj": b"GEOGCS[\"WGS 84\"]",
    }

    zip_path = tmp_path / "tiny_fixture.zip"
    with ZipFile(zip_path, "w") as zip_file:
        for extension, payload in payload_by_extension.items():
            zip_file.writestr(f"tiny_fixture.{extension}", payload)

    return zip_path


def _tiny_county_geojson_export() -> str:
    return json.dumps(
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [-78.95, 35.86],
                                [-78.73, 35.86],
                                [-78.73, 36.07],
                                [-78.95, 36.07],
                                [-78.95, 35.86],
                            ]
                        ],
                    },
                    "properties": {"STATEFP": "37", "COUNTYFP": "063", "NAME": "Durham"},
                }
            ],
        }
    )


def test_iter_geojson_features_from_fixture_shapefile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from domains.civics.loaders import tiger_geometry

    zip_path = _build_tiny_county_shapefile_zip(tmp_path)
    monkeypatch.setattr(
        tiger_geometry,
        "_run_ogr2ogr_geojson_export",
        lambda _zip_path, **_kwargs: _tiny_county_geojson_export(),
    )
    features = list(tiger_geometry._iter_geojson_features_from_shapefile_zip(zip_path))

    assert len(features) == 1
    assert features[0]["type"] == "Feature"
    assert features[0]["geometry"]["type"] == "Polygon"
    assert features[0]["properties"]["NAME"] == "Durham"


def test_iter_geojson_features_from_shapefile_zip_with_srs_passes_explicit_source_srs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from domains.civics.loaders import tiger_geometry

    zip_path = _build_tiny_county_shapefile_zip(tmp_path)
    captured: dict[str, object] = {}

    def _fake_run_ogr2ogr_geojson_export(
        path: Path,
        *,
        source_srs: str | None,
        target_srs: str,
    ) -> str:
        captured["zip_path"] = path
        captured["source_srs"] = source_srs
        captured["target_srs"] = target_srs
        return _tiny_county_geojson_export()

    monkeypatch.setattr(tiger_geometry, "_run_ogr2ogr_geojson_export", _fake_run_ogr2ogr_geojson_export)

    features = list(
        tiger_geometry._iter_geojson_features_from_shapefile_zip_with_srs(
            zip_path,
            source_srs="EPSG:4269",
        )
    )

    assert captured == {
        "zip_path": zip_path,
        "source_srs": "EPSG:4269",
        "target_srs": "EPSG:4326",
    }
    assert len(features) == 1
    assert features[0]["geometry"]["type"] == "Polygon"


def test_iter_geojson_features_compatibility_wrapper_delegates_to_shared_seam(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from domains.civics.loaders import tiger_geometry

    zip_path = _build_tiny_county_shapefile_zip(tmp_path)
    expected_features = [{"type": "Feature", "geometry": {"type": "Polygon", "coordinates": []}, "properties": {}}]
    call_details: dict[str, object] = {}

    def _fake_shared_seam(
        path: Path,
        *,
        source_srs: str | None = None,
        target_srs: str = "EPSG:4326",
    ) -> list[dict[str, object]]:
        call_details["zip_path"] = path
        call_details["source_srs"] = source_srs
        call_details["target_srs"] = target_srs
        return expected_features

    monkeypatch.setattr(tiger_geometry, "_iter_geojson_features_from_shapefile_zip_with_srs", _fake_shared_seam)

    features = tiger_geometry._iter_geojson_features_from_shapefile_zip(zip_path)

    assert features == expected_features
    assert call_details == {"zip_path": zip_path, "source_srs": None, "target_srs": "EPSG:4326"}


@pytest.mark.parametrize(
    ("level", "properties", "expected_name", "expected_type", "expected_district", "expected_ocd_id"),
    [
        (
            "state",
            {"STUSPS": "NC", "NAME": "North Carolina", "STATEFP": "37"},
            "nc",
            "statewide",
            None,
            None,
        ),
        (
            "county",
            {"STATEFP": "37", "COUNTYFP": "063", "NAME": "Durham"},
            "nc_county_durham",
            "county",
            None,
            None,
        ),
        (
            "county",
            {"STATEFP": "37", "COUNTYFP": "183", "NAME": "Wake"},
            "nc_county_wake",
            "county",
            None,
            None,
        ),
        (
            "county",
            {"STATEFP": "37", "COUNTYFP": "135", "NAME": "Orange"},
            "nc_county_orange",
            "county",
            None,
            None,
        ),
        (
            "congressional_district",
            {"DISTRICT": "1"},
            "nc_cd_01",
            "congressional_district",
            "01",
            "ocd-division/country:us/state:nc/cd:01",
        ),
        (
            "state_legislative_upper",
            {"DISTRICT": "9"},
            "nc_sldu_09",
            "state_legislative_upper",
            "09",
            "ocd-division/country:us/state:nc/sldu:09",
        ),
        (
            "state_legislative_lower",
            {"DISTRICT": "3"},
            "nc_sldl_03",
            "state_legislative_lower",
            "03",
            "ocd-division/country:us/state:nc/sldl:03",
        ),
        (
            "municipal",
            {"MunicipalName": "Durham", "County": "DURHAM"},
            "nc_municipal_durham",
            "municipal",
            None,
            "ocd-division/country:us/state:nc/place:durham",
        ),
        (
            "school_district",
            {"NAME": "Chapel Hill-Carrboro", "LEA": "681", "COUNTYFP": "135"},
            "nc_school_district_681",
            "school_district",
            "681",
            "ocd-division/country:us/state:nc/school_district:681",
        ),
    ],
)
def test_normalize_tiger_feature(
    level: str,
    properties: dict[str, str],
    expected_name: str,
    expected_type: str,
    expected_district: str | None,
    expected_ocd_id: str | None,
) -> None:
    from domains.civics.loaders.tiger_geometry import _normalize_tiger_feature

    division = _normalize_tiger_feature(
        level=level,
        state="NC",
        feature={"type": "Feature", "properties": properties, "geometry": {"type": "Polygon", "coordinates": []}},
        boundary_year=2024,
    )
    assert division.name == expected_name
    assert division.division_type == expected_type
    assert division.district_number == expected_district
    assert division.ocd_id == expected_ocd_id
    assert division.boundary_year == 2024


def test_discovers_congressional_filename_from_listing_without_hardcoded_congress_number() -> None:
    from domains.civics.loaders.tiger_geometry import _discover_congressional_district_zip_name

    html = """
    <html><body>
    <a href="tl_2024_us_cd118.zip">old</a>
    <a href="tl_2024_us_cd119.zip">current</a>
    </body></html>
    """
    assert _discover_congressional_district_zip_name(html, year=2024, state_fips="37") == "tl_2024_us_cd119.zip"


def test_discovers_state_scoped_congressional_filename_from_listing() -> None:
    from domains.civics.loaders.tiger_geometry import _discover_congressional_district_zip_name

    html = """
    <html><body>
    <a href="tl_2024_01_cd119.zip">alabama</a>
    <a href="tl_2024_37_cd119.zip">north-carolina</a>
    </body></html>
    """
    assert _discover_congressional_district_zip_name(html, year=2024, state_fips="37") == "tl_2024_37_cd119.zip"


def test_loader_argument_parser_accepts_state_level_year() -> None:
    from domains.civics.loaders.tiger_geometry import _build_argument_parser

    args = _build_argument_parser().parse_args(
        ["--state", "NC", "--level", "state_legislative_upper", "--year", "2024"]
    )
    assert args.state == "NC"
    assert args.level == "state_legislative_upper"
    assert args.year == 2024


@pytest.mark.parametrize("level", ["municipal", "school_district"])
def test_loader_argument_parser_accepts_nc_onemap_levels(level: str) -> None:
    from domains.civics.loaders.tiger_geometry import _build_argument_parser

    args = _build_argument_parser().parse_args(["--state", "NC", "--level", level, "--year", "2024"])
    assert args.state == "NC"
    assert args.level == level
    assert args.year == 2024


def test_zip_url_for_level_rejects_unproven_judicial_level_for_nc() -> None:
    from domains.civics.loaders.tiger_geometry import _zip_url_for_level

    with pytest.raises(ValueError, match="Unsupported level=judicial_district"):
        _zip_url_for_level(year=2024, level="judicial_district", state_fips="37")


@pytest.mark.parametrize(
    ("level", "expected_url"),
    [
        (
            "congressional_district",
            "https://dl.ncsbe.gov/ShapeFiles/USCongress/SL%202025-95%20-%20Shapefile.zip",
        ),
        (
            "state_legislative_upper",
            "https://dl.ncsbe.gov/ShapeFiles/LegislativeDistricts/Shapefiles/Senate/SL%202023-146%20Senate%20-%20Shapefile.zip",
        ),
        (
            "state_legislative_lower",
            "https://dl.ncsbe.gov/ShapeFiles/LegislativeDistricts/Shapefiles/House/SL%202023-149%20House%20-%20Shapefile.zip",
        ),
    ],
)
def test_zip_url_for_level_pins_nc_districts_to_stage1_contract_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    level: str,
    expected_url: str,
) -> None:
    from domains.civics.loaders import tiger_geometry

    monkeypatch.setattr(
        tiger_geometry,
        "_download_text",
        lambda _url: pytest.fail("NC contracted district ZIP resolution must not rely on listing discovery"),
    )

    url = tiger_geometry._zip_url_for_level(year=1999, level=level, state_fips="37")
    assert url == expected_url


@pytest.mark.parametrize(
    ("level", "expected_url", "expected_boundary_year"),
    [
        (
            "municipal",
            "https://services5.arcgis.com/mSDBiLWaIfH92NqI/arcgis/rest/services/NC_Municipal_Boundary_Pilot_ViewOnly/FeatureServer",
            2025,
        ),
        (
            "school_district",
            "https://services5.arcgis.com/mSDBiLWaIfH92NqI/arcgis/rest/services/LEA_Boundari_NC/FeatureServer",
            2021,
        ),
    ],
)
def test_nc_onemap_levels_pin_contract_metadata(
    monkeypatch: pytest.MonkeyPatch,
    level: str,
    expected_url: str,
    expected_boundary_year: int,
) -> None:
    from domains.civics.loaders import tiger_geometry

    monkeypatch.setattr(
        tiger_geometry,
        "_download_text",
        lambda _url: pytest.fail("NC OneMap contract resolution must not rely on TIGER listing discovery"),
    )

    url = tiger_geometry._zip_url_for_level(year=1999, level=level, state_fips="37")
    boundary_year = tiger_geometry._boundary_year_for_level(year=1999, level=level, state_fips="37")

    assert url == expected_url
    assert boundary_year == expected_boundary_year


@pytest.mark.parametrize(
    ("level", "properties", "expected_matches"),
    [
        ("county", {"STATEFP": "37", "COUNTYFP": "063", "NAME": "Durham"}, True),
        ("county", {"STATEFP": "37", "COUNTYFP": "183", "NAME": "Wake"}, True),
        ("county", {"STATEFP": "37", "COUNTYFP": "119", "NAME": "Mecklenburg"}, False),
        ("county", {"STATEFP": "51", "COUNTYFP": "063", "NAME": "Durham"}, False),
        ("municipal", {"County": "DURHAM", "MunicipalName": "Durham"}, True),
        ("municipal", {"County": "DURHAM", "MunicipalName": None}, False),
        ("municipal", {"County": "MECKLENBURG", "MunicipalName": "Charlotte"}, False),
        ("school_district", {"COUNTYFP": "135", "LEA": "681", "NAME": "Chapel Hill-Carrboro"}, True),
        ("school_district", {"COUNTYFP": "119", "LEA": "600", "NAME": "Mecklenburg"}, False),
    ],
)
def test_feature_matches_state_applies_dw_o_county_scope_for_nc_onemap_levels(
    level: str,
    properties: dict[str, object],
    expected_matches: bool,
) -> None:
    from domains.civics.loaders.tiger_geometry import _feature_matches_state

    assert (
        _feature_matches_state(level=level, state="NC", state_fips="37", properties=properties)
        is expected_matches
    )
