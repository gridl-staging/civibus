"""Integration tests for TIGER state/county geometry loader."""

from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import psycopg
import pytest
import shapefile


pytestmark = pytest.mark.integration

_NC_GEOMETRY_EXPECTED_COUNT_BY_LEVEL = {"congressional_district": 14, "state_legislative_upper": 50, "state_legislative_lower": 120, "municipal": 19, "school_district": 4}


def _assert_nc_level_count_and_srid_invariants(
    db_conn: psycopg.Connection,
    *,
    division_type: str,
    boundary_year: int,
    expected_count: int,
) -> None:
    row = db_conn.execute(
        """
        SELECT
            COUNT(*)::int AS total_count,
            COUNT(*) FILTER (WHERE ST_SRID(geometry) = 4326)::int AS srid_4326_count,
            COUNT(*) FILTER (WHERE ST_GeometryType(geometry) = 'ST_MultiPolygon')::int AS multipolygon_count
        FROM civic.electoral_division
        WHERE division_type = %s
          AND state = 'NC'
          AND COALESCE(boundary_year, 0) = %s
        """,
        (division_type, boundary_year),
    ).fetchone()
    assert row == (expected_count, expected_count, expected_count)


def _square_polygon(min_x: float, min_y: float, size: float) -> list[list[list[float]]]:
    return [
        [
            [min_x, min_y],
            [min_x + size, min_y],
            [min_x + size, min_y + size],
            [min_x, min_y + size],
            [min_x, min_y],
        ]
    ]


def _write_state_fixture(path: Path) -> Path:
    writer = shapefile.Writer(str(path), shapeType=shapefile.POLYGON)
    writer.field("STATEFP", "C", size=2)
    writer.field("STUSPS", "C", size=2)
    writer.field("NAME", "C", size=80)

    writer.record("01", "al", "Alabama")
    writer.poly(_square_polygon(-88.0, 30.0, 1.0))

    writer.record("11", "dc", "District of Columbia")
    writer.poly(_square_polygon(-77.2, 38.8, 0.1))

    writer.record("48", "tx", "Texas")
    writer.poly(_square_polygon(-106.7, 25.8, 1.2))

    # Territory that must be filtered out by launch-scope rules.
    writer.record("72", "pr", "Puerto Rico")
    writer.poly(_square_polygon(-67.3, 18.0, 0.3))

    writer.close()
    return path.with_suffix(".shp")


def _write_county_fixture(path: Path) -> Path:
    writer = shapefile.Writer(str(path), shapeType=shapefile.POLYGON)
    writer.field("STATEFP", "C", size=2)
    writer.field("COUNTYFP", "C", size=3)
    writer.field("NAME", "C", size=80)

    writer.record("01", "001", "Autauga County")
    writer.poly(_square_polygon(-86.7, 32.4, 0.1))

    writer.record("48", "453", "Travis County")
    writer.poly(_square_polygon(-98.0, 30.1, 0.1))

    # Territory county that must be filtered out with the territory state.
    writer.record("72", "001", "Adjuntas")
    writer.poly(_square_polygon(-66.8, 18.2, 0.1))

    # Unknown state FIPS should never create orphan county rows.
    writer.record("99", "001", "Imaginary County")
    writer.poly(_square_polygon(-100.0, 20.0, 0.1))

    writer.close()
    return path.with_suffix(".shp")


def _build_tiny_shapefile_zip_bytes() -> bytes:
    payload_by_extension = {
        "shp": b"fixture-shp",
        "shx": b"fixture-shx",
        "dbf": b"fixture-dbf",
        "prj": b"GEOGCS[\"NAD83\"]",
    }
    output = BytesIO()
    with ZipFile(output, "w") as zip_file:
        for extension, payload in payload_by_extension.items():
            zip_file.writestr(f"fixture.{extension}", payload)
    return output.getvalue()


def _district_geojson_feature_collection(*, district_count: int) -> str:
    features: list[dict[str, object]] = []
    for district in range(1, district_count + 1):
        offset = district * 0.01
        polygon = [
            [
                [-80.0 + offset, 35.0 + offset],
                [-79.9 + offset, 35.0 + offset],
                [-79.9 + offset, 35.1 + offset],
                [-80.0 + offset, 35.1 + offset],
                [-80.0 + offset, 35.0 + offset],
            ]
        ]
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": polygon},
                "properties": {"DISTRICT": str(district)},
            }
        )
    return json.dumps({"type": "FeatureCollection", "features": features})


def _municipal_geojson_feature_collection_with_mixed_statewide_rows() -> str:
    """Build NC OneMap-like municipal features with D/W/O + out-of-scope counties."""
    features: list[dict[str, object]] = []
    offset_index = 0

    def _append_feature(*, county: str, municipal_name: str | None) -> None:
        nonlocal offset_index
        offset = offset_index * 0.005
        offset_index += 1
        properties: dict[str, object] = {
            "County": county,
            "MunicipalName": municipal_name,
        }
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [-82.0 + offset, 35.0 + offset],
                            [-81.9 + offset, 35.0 + offset],
                            [-81.9 + offset, 35.1 + offset],
                            [-82.0 + offset, 35.1 + offset],
                            [-82.0 + offset, 35.0 + offset],
                        ]
                    ],
                },
                "properties": properties,
            }
        )

    # Durham County = 6 raw rows (5 named, 1 null).
    for municipal_name in ["CHAPEL HILL", "DURHAM", "MORRISVILLE", "RALEIGH", None, "CARY"]:
        _append_feature(county="DURHAM", municipal_name=municipal_name)

    # Orange County = 9 raw rows.
    for municipal_name in [
        "CARRBORO",
        "CARRBORO",
        "CHAPEL HILL",
        "CHAPEL HILL",
        "DURHAM",
        "HILLSBOROUGH",
        "HILLSBOROUGH",
        "MEBANE",
        "MEBANE",
    ]:
        _append_feature(county="ORANGE", municipal_name=municipal_name)

    # Wake County = 31 raw rows.
    for municipal_name in [
        "CLAYTON",
        "ANGIER",
        "ANGIER",
        "APEX",
        "APEX",
        "CARY",
        "CARY",
        "DURHAM",
        "FUQUAY-VARINA",
        "FUQUAY-VARINA",
        "GARNER",
        "GARNER",
        "HOLLY SPRINGS",
        "HOLLY SPRINGS",
        "KNIGHTDALE",
        "KNIGHTDALE",
        "MORRISVILLE",
        "MORRISVILLE",
        "RALEIGH",
        "RALEIGH",
        "ROLESVILLE",
        "ROLESVILLE",
        "WAKE FOREST",
        "WAKE FOREST",
        "WENDELL",
        "WENDELL",
        "ZEBULON",
        "ZEBULON",
        "",
        None,
        None,
    ]:
        _append_feature(county="WAKE", municipal_name=municipal_name)

    # Out-of-scope county rows must be filtered out.
    _append_feature(county="MECKLENBURG", municipal_name="CHARLOTTE")
    _append_feature(county="BUNCOMBE", municipal_name="ASHEVILLE")

    return json.dumps({"type": "FeatureCollection", "features": features})


def _school_district_geojson_feature_collection_with_mixed_statewide_rows() -> str:
    """Build LEA-like features with D/W/O + one out-of-scope county."""
    features: list[dict[str, object]] = []
    rows = [
        ("063", "Durham", "320"),
        ("135", "Orange", "680"),
        ("135", "Chapel Hill-Carrboro", "681"),
        ("183", "Wake", "920"),
        ("119", "Mecklenburg", "600"),
    ]
    for index, (countyfp, name, lea) in enumerate(rows):
        offset = index * 0.01
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [-80.5 + offset, 34.8 + offset],
                            [-80.4 + offset, 34.8 + offset],
                            [-80.4 + offset, 34.9 + offset],
                            [-80.5 + offset, 34.9 + offset],
                            [-80.5 + offset, 34.8 + offset],
                        ]
                    ],
                },
                "properties": {"STATEFP": "37", "COUNTYFP": countyfp, "NAME": name, "LEA": lea},
            }
        )
    return json.dumps({"type": "FeatureCollection", "features": features})


def test_load_tiger_states_and_counties_is_idempotent_with_canonical_rows(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    from domains.civics.loaders.tiger_geometry import load_tiger_states_and_counties

    state_path = _write_state_fixture(tmp_path / "state_fixture")
    county_path = _write_county_fixture(tmp_path / "county_fixture")

    first = load_tiger_states_and_counties(
        db_conn,
        state_shapefile_path=state_path,
        county_shapefile_path=county_path,
        vintage=2024,
    )
    second = load_tiger_states_and_counties(
        db_conn,
        state_shapefile_path=state_path,
        county_shapefile_path=county_path,
        vintage=2024,
    )

    assert first.state_count == second.state_count == 3
    assert first.county_count == second.county_count == 2

    rows = db_conn.execute(
        """
        SELECT
            division_type,
            name,
            state,
            district_number,
            boundary_year,
            parent_id,
            ST_SRID(geometry) AS srid,
            ST_GeometryType(geometry) AS geometry_type
        FROM civic.electoral_division
        WHERE
            (division_type = 'statewide' AND state IN ('AL', 'DC', 'TX')) OR
            (division_type = 'county' AND state IN ('AL', 'TX'))
        ORDER BY division_type, state, name
        """
    ).fetchall()

    assert len(rows) == 5

    state_rows = [row for row in rows if row[0] == "statewide"]
    county_rows = [row for row in rows if row[0] == "county"]

    assert {(row[1], row[2], row[4]) for row in state_rows} == {
        ("Alabama", "AL", 2024),
        ("District of Columbia", "DC", 2024),
        ("Texas", "TX", 2024),
    }
    assert all(row[3] is None for row in state_rows)
    assert all(row[5] is None for row in state_rows)

    county_identity = {(row[1], row[2], row[3], row[4]) for row in county_rows}
    assert county_identity == {
        ("Autauga County", "AL", "001", 2024),
        ("Travis County", "TX", "453", 2024),
    }

    state_id_rows = db_conn.execute(
        """
        SELECT state, id
        FROM civic.electoral_division
        WHERE division_type = 'statewide' AND state IN ('AL', 'DC', 'TX')
        """
    ).fetchall()
    state_ids = {row[0]: row[1] for row in state_id_rows}

    for county_row in county_rows:
        state_code = county_row[2]
        parent_id = county_row[5]
        srid = county_row[6]
        geometry_type = county_row[7]
        assert state_code in state_ids
        assert parent_id == state_ids[state_code]
        assert srid == 4326
        assert geometry_type == "ST_MultiPolygon"

    skipped_rows = db_conn.execute(
        """
        SELECT COUNT(1)::int
        FROM civic.electoral_division
        WHERE state IN ('PR') OR name IN ('Adjuntas', 'Imaginary County')
        """
    ).fetchone()
    assert skipped_rows == (0,)


def test_load_tiger_geometry_uses_generalized_shapefile_seam_and_preserves_upsert_idempotency(
    db_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from domains.civics.loaders import tiger_geometry

    zip_payload = _build_tiny_shapefile_zip_bytes()
    seam_calls: list[tuple[str | None, str]] = []

    def _fake_ogr2ogr_export(
        _zip_path: Path,
        *,
        source_srs: str | None,
        target_srs: str,
    ) -> str:
        seam_calls.append((source_srs, target_srs))
        return """
        {
          "type": "FeatureCollection",
          "features": [
            {
              "type": "Feature",
              "geometry": {
                "type": "Polygon",
                "coordinates": [[[-78.95, 35.86], [-78.73, 35.86], [-78.73, 36.07], [-78.95, 36.07], [-78.95, 35.86]]]
              },
              "properties": {"STATEFP": "37", "COUNTYFP": "063", "NAME": "Durham"}
            },
            {
              "type": "Feature",
              "geometry": {
                "type": "Polygon",
                "coordinates": [[[-78.85, 35.90], [-78.50, 35.90], [-78.50, 36.10], [-78.85, 36.10], [-78.85, 35.90]]]
              },
              "properties": {"STATEFP": "37", "COUNTYFP": "183", "NAME": "Wake"}
            },
            {
              "type": "Feature",
              "geometry": {
                "type": "Polygon",
                "coordinates": [[[-79.25, 35.80], [-78.90, 35.80], [-78.90, 36.10], [-79.25, 36.10], [-79.25, 35.80]]]
              },
              "properties": {"STATEFP": "37", "COUNTYFP": "135", "NAME": "Orange"}
            },
            {
              "type": "Feature",
              "geometry": {
                "type": "Polygon",
                "coordinates": [[[-81.10, 35.10], [-80.60, 35.10], [-80.60, 35.50], [-81.10, 35.50], [-81.10, 35.10]]]
              },
              "properties": {"STATEFP": "37", "COUNTYFP": "119", "NAME": "Mecklenburg"}
            }
          ]
        }
        """

    monkeypatch.setattr(tiger_geometry, "_state_fips_for_code", lambda _conn, _state: "37")
    monkeypatch.setattr(tiger_geometry, "_zip_url_for_level", lambda **_kwargs: "https://example.test/fixture.zip")
    monkeypatch.setattr(tiger_geometry, "_download_bytes", lambda _url: zip_payload)
    monkeypatch.setattr(tiger_geometry, "_run_ogr2ogr_geojson_export", _fake_ogr2ogr_export)

    first_upsert_count = tiger_geometry.load_tiger_geometry(db_conn, state="NC", level="county", year=2024)
    second_upsert_count = tiger_geometry.load_tiger_geometry(db_conn, state="NC", level="county", year=2024)

    assert first_upsert_count == 3
    assert second_upsert_count == 3
    assert seam_calls == [(None, "EPSG:4326"), (None, "EPSG:4326")]

    canonical_rows = db_conn.execute(
        """
        SELECT name, boundary_year
        FROM civic.electoral_division
        WHERE division_type = 'county'
          AND state = 'NC'
          AND COALESCE(boundary_year, 0) = 2024
        ORDER BY name
        """
    ).fetchall()
    assert canonical_rows == [
        ("nc_county_durham", 2024),
        ("nc_county_orange", 2024),
        ("nc_county_wake", 2024),
    ]

    row = db_conn.execute(
        """
        SELECT id, parent_id, ST_GeometryType(geometry), ST_SRID(geometry)
        FROM civic.electoral_division
        WHERE division_type = 'county'
          AND state = 'NC'
          AND name = 'nc_county_durham'
          AND COALESCE(boundary_year, 0) = 2024
        """
    ).fetchone()
    assert row is not None
    row_id, parent_id, geometry_type, srid = row
    assert row_id is not None
    assert parent_id is None
    assert geometry_type == "ST_MultiPolygon"
    assert srid == 4326

    rerun = db_conn.execute(
        """
        SELECT COUNT(*)::int, COUNT(DISTINCT id)::int
        FROM civic.electoral_division
        WHERE division_type = 'county'
          AND state = 'NC'
          AND name = 'nc_county_durham'
          AND COALESCE(boundary_year, 0) = 2024
        """
    ).fetchone()
    assert rerun == (1, 1)

    # -- Parent-link preservation: set a parent_id, rerun loader (which sends
    # parent_id=None via _normalize_tiger_feature), then assert COALESCE keeps it.
    fake_parent_id = db_conn.execute(
        """
        INSERT INTO civic.electoral_division (
            name, division_type, state, boundary_year
        )
        VALUES ('nc_parent_stub', 'statewide', 'NC', 2024)
        ON CONFLICT (division_type, COALESCE(state, ''), name, COALESCE(boundary_year, 0))
        DO UPDATE SET updated_at = NOW()
        RETURNING id
        """
    ).fetchone()[0]

    db_conn.execute(
        "UPDATE civic.electoral_division SET parent_id = %s WHERE id = %s",
        (fake_parent_id, row_id),
    )

    third_upsert_count = tiger_geometry.load_tiger_geometry(db_conn, state="NC", level="county", year=2024)
    assert third_upsert_count == 3

    preserved = db_conn.execute(
        """
        SELECT parent_id
        FROM civic.electoral_division
        WHERE id = %s
        """,
        (row_id,),
    ).fetchone()
    assert preserved is not None
    assert preserved[0] == fake_parent_id

    rerun_all = db_conn.execute(
        """
        SELECT COUNT(*)::int, COUNT(DISTINCT id)::int
        FROM civic.electoral_division
        WHERE division_type = 'county'
          AND state = 'NC'
          AND COALESCE(boundary_year, 0) = 2024
        """
    ).fetchone()
    assert rerun_all == (3, 3)


@pytest.mark.parametrize(
    ("level", "division_type", "expected_count", "ocd_segment", "expected_boundary_year"),
    [
        ("congressional_district", "congressional_district", _NC_GEOMETRY_EXPECTED_COUNT_BY_LEVEL["congressional_district"], "cd", 2025),
        ("state_legislative_upper", "state_legislative_upper", _NC_GEOMETRY_EXPECTED_COUNT_BY_LEVEL["state_legislative_upper"], "sldu", 2023),
        ("state_legislative_lower", "state_legislative_lower", _NC_GEOMETRY_EXPECTED_COUNT_BY_LEVEL["state_legislative_lower"], "sldl", 2023),
    ],
)
def test_load_tiger_geometry_nc_district_chambers_preserve_counts_and_ocd_contract(
    db_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
    level: str,
    division_type: str,
    expected_count: int,
    ocd_segment: str,
    expected_boundary_year: int,
) -> None:
    from domains.civics.loaders import tiger_geometry

    zip_payload = _build_tiny_shapefile_zip_bytes()
    seam_calls: list[tuple[str | None, str]] = []
    active_level: dict[str, str] = {"value": ""}
    geojson_by_level = {
        "congressional_district": _district_geojson_feature_collection(district_count=14),
        "state_legislative_upper": _district_geojson_feature_collection(district_count=50),
        "state_legislative_lower": _district_geojson_feature_collection(district_count=120),
    }

    def _fake_zip_url_for_level(*, year: int, level: str, state_fips: str) -> str:
        assert year == 2024
        assert state_fips == "37"
        return f"https://example.test/{level}.zip"

    def _fake_download_bytes(url: str) -> bytes:
        active_level["value"] = Path(url).stem
        return zip_payload

    def _fake_ogr2ogr_export(
        _zip_path: Path,
        *,
        source_srs: str | None,
        target_srs: str,
    ) -> str:
        seam_calls.append((source_srs, target_srs))
        return geojson_by_level[active_level["value"]]

    monkeypatch.setattr(tiger_geometry, "_state_fips_for_code", lambda _conn, _state: "37")
    monkeypatch.setattr(tiger_geometry, "_zip_url_for_level", _fake_zip_url_for_level)
    monkeypatch.setattr(tiger_geometry, "_download_bytes", _fake_download_bytes)
    monkeypatch.setattr(tiger_geometry, "_run_ogr2ogr_geojson_export", _fake_ogr2ogr_export)

    first_upsert_count = tiger_geometry.load_tiger_geometry(db_conn, state="NC", level=level, year=2024)
    second_upsert_count = tiger_geometry.load_tiger_geometry(db_conn, state="NC", level=level, year=2024)

    assert first_upsert_count == expected_count
    assert second_upsert_count == expected_count
    assert seam_calls == [("EPSG:32119", "EPSG:4326"), ("EPSG:32119", "EPSG:4326")]

    rows = db_conn.execute(
        """
        SELECT
            name,
            district_number,
            ocd_id,
            ST_SRID(geometry) AS srid,
            ST_GeometryType(geometry) AS geometry_type
        FROM civic.electoral_division
        WHERE division_type = %s
          AND state = 'NC'
          AND COALESCE(boundary_year, 0) = %s
        ORDER BY district_number::int
        """,
        (division_type, expected_boundary_year),
    ).fetchall()

    assert len(rows) == expected_count
    assert all(row[3] == 4326 for row in rows)
    assert all(row[4] == "ST_MultiPolygon" for row in rows)

    expected_district_numbers = {f"{district:02d}" for district in range(1, expected_count + 1)}
    actual_district_numbers = {row[1] for row in rows}
    assert actual_district_numbers == expected_district_numbers

    expected_ocd_ids = {
        f"ocd-division/country:us/state:nc/{ocd_segment}:{district:02d}" for district in range(1, expected_count + 1)
    }
    actual_ocd_ids = {row[2] for row in rows}
    assert actual_ocd_ids == expected_ocd_ids
    _assert_nc_level_count_and_srid_invariants(
        db_conn,
        division_type=division_type,
        boundary_year=expected_boundary_year,
        expected_count=_NC_GEOMETRY_EXPECTED_COUNT_BY_LEVEL[level],
    )

    rerun = db_conn.execute(
        """
        SELECT COUNT(*)::int, COUNT(DISTINCT id)::int
        FROM civic.electoral_division
        WHERE division_type = %s
          AND state = 'NC'
          AND COALESCE(boundary_year, 0) = %s
        """,
        (division_type, expected_boundary_year),
    ).fetchone()
    assert rerun == (expected_count, expected_count)


@pytest.mark.parametrize(
    ("level", "division_type", "expected_boundary_year"),
    [
        ("congressional_district", "congressional_district", 2025),
        ("state_legislative_upper", "state_legislative_upper", 2023),
        ("state_legislative_lower", "state_legislative_lower", 2023),
    ],
)
def test_load_tiger_geometry_nc_districts_persist_contracted_boundary_year(
    db_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
    level: str,
    division_type: str,
    expected_boundary_year: int,
) -> None:
    from domains.civics.loaders import tiger_geometry

    zip_payload = _build_tiny_shapefile_zip_bytes()
    district_geojson = _district_geojson_feature_collection(district_count=1)

    monkeypatch.setattr(tiger_geometry, "_state_fips_for_code", lambda _conn, _state: "37")
    monkeypatch.setattr(tiger_geometry, "_download_bytes", lambda _url: zip_payload)
    monkeypatch.setattr(tiger_geometry, "_run_ogr2ogr_geojson_export", lambda *_args, **_kwargs: district_geojson)

    upserted_count = tiger_geometry.load_tiger_geometry(db_conn, state="NC", level=level, year=1999)

    assert upserted_count == 1
    boundary_year_row = db_conn.execute(
        """
        SELECT boundary_year
        FROM civic.electoral_division
        WHERE division_type = %s
          AND state = 'NC'
          AND district_number = '01'
        """,
        (division_type,),
    ).fetchone()
    assert boundary_year_row == (expected_boundary_year,)


@pytest.mark.parametrize(
    (
        "level",
        "division_type",
        "expected_upsert_count",
        "expected_row_count",
        "expected_boundary_year",
        "identity_name",
        "identity_ocd_id",
    ),
    [
        ("municipal", "municipal", _NC_GEOMETRY_EXPECTED_COUNT_BY_LEVEL["municipal"], 19, 2025, "nc_municipal_durham", "ocd-division/country:us/state:nc/place:durham"),
        ("school_district", "school_district", _NC_GEOMETRY_EXPECTED_COUNT_BY_LEVEL["school_district"], 4, 2021, "nc_school_district_681", "ocd-division/country:us/state:nc/school_district:681"),
    ],
)
def test_load_tiger_geometry_nc_onemap_levels_filter_dw_o_and_preserve_contract_identities(
    db_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
    level: str,
    division_type: str,
    expected_upsert_count: int,
    expected_row_count: int,
    expected_boundary_year: int,
    identity_name: str,
    identity_ocd_id: str,
) -> None:
    from domains.civics.loaders import tiger_geometry

    seam_calls: list[str] = []
    geojson_by_level = {
        "municipal": _municipal_geojson_feature_collection_with_mixed_statewide_rows(),
        "school_district": _school_district_geojson_feature_collection_with_mixed_statewide_rows(),
    }

    def _fake_zip_url_for_level(*, year: int, level: str, state_fips: str) -> str:
        assert year == 2024
        assert state_fips == "37"
        return f"https://example.test/{level}.zip"

    def _fake_arcgis_feature_iterator(url: str) -> list[dict[str, object]]:
        seam_calls.append(url)
        level_key = Path(url).stem
        payload = json.loads(geojson_by_level[level_key])
        features = payload.get("features")
        assert isinstance(features, list)
        return features

    monkeypatch.setattr(tiger_geometry, "_state_fips_for_code", lambda _conn, _state: "37")
    monkeypatch.setattr(tiger_geometry, "_zip_url_for_level", _fake_zip_url_for_level)
    monkeypatch.setattr(
        tiger_geometry,
        "_iter_geojson_features_from_arcgis_featureserver",
        _fake_arcgis_feature_iterator,
    )

    first_upsert_count = tiger_geometry.load_tiger_geometry(db_conn, state="NC", level=level, year=2024)
    second_upsert_count = tiger_geometry.load_tiger_geometry(db_conn, state="NC", level=level, year=2024)

    assert first_upsert_count == expected_upsert_count
    assert second_upsert_count == expected_upsert_count
    assert seam_calls == [
        f"https://example.test/{level}.zip",
        f"https://example.test/{level}.zip",
    ]

    rows = db_conn.execute(
        """
        SELECT
            name,
            ocd_id,
            boundary_year,
            ST_SRID(geometry) AS srid,
            ST_GeometryType(geometry) AS geometry_type
        FROM civic.electoral_division
        WHERE division_type = %s
          AND state = 'NC'
          AND COALESCE(boundary_year, 0) = %s
        ORDER BY name
        """,
        (division_type, expected_boundary_year),
    ).fetchall()

    assert len(rows) == expected_row_count
    assert all(row[3] == 4326 for row in rows)
    assert all(row[4] == "ST_MultiPolygon" for row in rows)

    identity = next((row for row in rows if row[0] == identity_name), None)
    assert identity is not None
    assert identity[1] == identity_ocd_id
    _assert_nc_level_count_and_srid_invariants(
        db_conn,
        division_type=division_type,
        boundary_year=expected_boundary_year,
        expected_count=_NC_GEOMETRY_EXPECTED_COUNT_BY_LEVEL[level],
    )
    if level == "municipal":
        merged_geometry_parts = db_conn.execute(
            """
            SELECT ST_NumGeometries(geometry)
            FROM civic.electoral_division
            WHERE division_type = 'municipal'
              AND state = 'NC'
              AND name = 'nc_municipal_durham'
              AND COALESCE(boundary_year, 0) = 2025
            """
        ).fetchone()
        assert merged_geometry_parts == (3,)

    outside_rows = db_conn.execute(
        """
        SELECT COUNT(*)::int
        FROM civic.electoral_division
        WHERE division_type = %s
          AND state = 'NC'
          AND COALESCE(boundary_year, 0) = %s
          AND (
            name ILIKE '%%charlotte%%'
            OR name ILIKE '%%asheville%%'
            OR name ILIKE '%%mecklenburg%%'
          )
        """,
        (division_type, expected_boundary_year),
    ).fetchone()
    assert outside_rows == (0,)

    rerun = db_conn.execute(
        """
        SELECT COUNT(*)::int, COUNT(DISTINCT id)::int
        FROM civic.electoral_division
        WHERE division_type = %s
          AND state = 'NC'
          AND COALESCE(boundary_year, 0) = %s
        """,
        (division_type, expected_boundary_year),
    ).fetchone()
    assert rerun == (expected_row_count, expected_row_count)
