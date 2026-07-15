
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen
from uuid import UUID
from zipfile import ZipFile

import psycopg
import shapefile

from core.db import get_connection
from domains.civics.constants import (
    CENSUS_STATE_FIPS_TO_USPS_MAP,
    LAUNCH_SCOPE_STATE_FIPS,
    congressional_boundary_year_for_congress,
)
from domains.civics.ingest import upsert_electoral_division
from domains.civics.types import ElectoralDivision

_TIGER_BASE_URL = "https://www2.census.gov/geo/tiger/TIGER{year}"
_LEVEL_CHOICES = (
    "state",
    "county",
    "congressional_district",
    "state_legislative_upper",
    "state_legislative_lower",
    "municipal",
    "school_district",
)
_LEVEL_TO_DIVISION_TYPE = {
    "state": "statewide",
    "county": "county",
    "congressional_district": "congressional_district",
    "state_legislative_upper": "state_legislative_upper",
    "state_legislative_lower": "state_legislative_lower",
    "municipal": "municipal",
    "school_district": "school_district",
}
_DISTRICT_NAME_SEGMENT_BY_LEVEL = {
    "congressional_district": "cd",
    "state_legislative_upper": "sldu",
    "state_legislative_lower": "sldl",
    "school_district": "school_district",
}
_CD_FILENAME_PATTERN = re.compile(
    r"tl_(?P<year>\d{4})_(?P<scope>us|\d{2})_cd(?P<congress>\d+)\.zip",
    re.IGNORECASE,
)
_CD_FIELD_PATTERN = re.compile(r"CD\d{3}FP", re.IGNORECASE)
_TRANSIENT_HTTP_STATUS_CODES = frozenset({429, 500, 502, 503, 504, 520, 524})
_DOWNLOAD_ATTEMPTS = 3
_DOWNLOAD_TIMEOUT_SECONDS = 60


@dataclass(frozen=True)
class TigerLoadSummary:
    state_count: int
    county_count: int


@dataclass(frozen=True)
class _NcGeometryContractArtifact:
    provider: str
    url: str
    boundary_year: int
    source_srs: str | None = None


_NC_CONTRACT_ARTIFACT_BY_LEVEL = {
    "congressional_district": _NcGeometryContractArtifact(
        provider="ncsbe",
        url="https://dl.ncsbe.gov/ShapeFiles/USCongress/SL%202025-95%20-%20Shapefile.zip",
        boundary_year=2025,
        source_srs="EPSG:32119",
    ),
    "state_legislative_upper": _NcGeometryContractArtifact(
        provider="ncsbe",
        url=(
            "https://dl.ncsbe.gov/ShapeFiles/LegislativeDistricts/Shapefiles/Senate/"
            "SL%202023-146%20Senate%20-%20Shapefile.zip"
        ),
        boundary_year=2023,
        source_srs="EPSG:32119",
    ),
    "state_legislative_lower": _NcGeometryContractArtifact(
        provider="ncsbe",
        url=(
            "https://dl.ncsbe.gov/ShapeFiles/LegislativeDistricts/Shapefiles/House/"
            "SL%202023-149%20House%20-%20Shapefile.zip"
        ),
        boundary_year=2023,
        source_srs="EPSG:32119",
    ),
    "municipal": _NcGeometryContractArtifact(
        provider="nconemap",
        url=(
            "https://services5.arcgis.com/mSDBiLWaIfH92NqI/arcgis/rest/services/"
            "NC_Municipal_Boundary_Pilot_ViewOnly/FeatureServer"
        ),
        boundary_year=2025,
        source_srs="EPSG:2264",
    ),
    "school_district": _NcGeometryContractArtifact(
        provider="nconemap",
        url=("https://services5.arcgis.com/mSDBiLWaIfH92NqI/arcgis/rest/services/LEA_Boundari_NC/FeatureServer"),
        boundary_year=2021,
        source_srs="EPSG:6543",
    ),
}
_NC_COUNTY_SCOPE_NAME_TO_FIPS = {
    "DURHAM": "063",
    "WAKE": "183",
    "ORANGE": "135",
}
_NC_COUNTY_SCOPE_FIPS = frozenset(_NC_COUNTY_SCOPE_NAME_TO_FIPS.values())


def _is_nc_scope_county(*, county_name: object | None = None, county_fips: object | None = None) -> bool:
    normalized_name: str | None = None
    if isinstance(county_name, str) and county_name.strip():
        normalized_name = county_name.strip().upper()

    normalized_fips: str | None = None
    if isinstance(county_fips, str) and county_fips.strip():
        normalized_fips = county_fips.strip().zfill(3)

    if normalized_name is not None and normalized_fips is not None:
        return _NC_COUNTY_SCOPE_NAME_TO_FIPS.get(normalized_name) == normalized_fips
    if normalized_name is not None:
        return normalized_name in _NC_COUNTY_SCOPE_NAME_TO_FIPS
    if normalized_fips is not None:
        return normalized_fips in _NC_COUNTY_SCOPE_FIPS
    return False


def _shape_to_geojson_multipolygon(shape: object) -> dict[str, object]:
    geo = shape.__geo_interface__  # type: ignore[union-attr]
    geo_type = geo["type"]
    coordinates = geo["coordinates"]
    if geo_type == "Polygon":
        return {"type": "MultiPolygon", "coordinates": [coordinates]}
    if geo_type == "MultiPolygon":
        return {"type": "MultiPolygon", "coordinates": coordinates}
    raise ValueError(f"Unexpected geometry type: {geo_type}")


def _read_state_records(
    state_shapefile_path: Path,
) -> list[tuple[str, str, str, dict[str, object]]]:
    """Return (statefp, stusps, name, geometry) for launch-scope states."""
    reader = shapefile.Reader(str(state_shapefile_path))
    field_names = [f[0] for f in reader.fields[1:]]
    statefp_idx = field_names.index("STATEFP")
    stusps_idx = field_names.index("STUSPS")
    name_idx = field_names.index("NAME")

    result: list[tuple[str, str, str, dict[str, object]]] = []
    for shape_rec in reader.iterShapeRecords():
        statefp = shape_rec.record[statefp_idx]
        if statefp not in LAUNCH_SCOPE_STATE_FIPS:
            continue
        stusps = shape_rec.record[stusps_idx].upper()
        name = shape_rec.record[name_idx]
        geometry = _shape_to_geojson_multipolygon(shape_rec.shape)
        result.append((statefp, stusps, name, geometry))
    return result


def _read_county_records(
    county_shapefile_path: Path,
    valid_statefps: frozenset[str],
) -> list[tuple[str, str, str, dict[str, object]]]:
    """Return (statefp, countyfp, name, geometry) for counties in valid states."""
    reader = shapefile.Reader(str(county_shapefile_path))
    field_names = [f[0] for f in reader.fields[1:]]
    statefp_idx = field_names.index("STATEFP")
    countyfp_idx = field_names.index("COUNTYFP")
    name_idx = field_names.index("NAME")

    result: list[tuple[str, str, str, dict[str, object]]] = []
    for shape_rec in reader.iterShapeRecords():
        statefp = shape_rec.record[statefp_idx]
        if statefp not in valid_statefps:
            continue
        countyfp = shape_rec.record[countyfp_idx]
        name = shape_rec.record[name_idx]
        geometry = _shape_to_geojson_multipolygon(shape_rec.shape)
        result.append((statefp, countyfp, name, geometry))
    return result


def load_tiger_states_and_counties(
    conn: psycopg.Connection,
    state_shapefile_path: Path,
    county_shapefile_path: Path,
    *,
    vintage: int = 2024,
) -> TigerLoadSummary:
    """Load fixture-driven state and county rows for integration tests."""
    state_records = _read_state_records(state_shapefile_path)

    fips_to_stusps: dict[str, str] = {}
    fips_to_state_id: dict[str, UUID] = {}
    for statefp, stusps, name, geometry in state_records:
        division = ElectoralDivision(
            name=name,
            division_type="statewide",
            state=stusps,
            geometry=geometry,
            boundary_year=vintage,
        )
        row_id = upsert_electoral_division(conn, division)
        fips_to_stusps[statefp] = stusps
        fips_to_state_id[statefp] = row_id

    loaded_fips = frozenset(fips_to_stusps.keys())
    county_records = _read_county_records(county_shapefile_path, loaded_fips)

    county_count = 0
    for statefp, countyfp, name, geometry in county_records:
        division = ElectoralDivision(
            name=name,
            division_type="county",
            state=fips_to_stusps[statefp],
            district_number=countyfp,
            geometry=geometry,
            parent_id=fips_to_state_id[statefp],
            boundary_year=vintage,
        )
        upsert_electoral_division(conn, division)
        county_count += 1

    return TigerLoadSummary(
        state_count=len(state_records),
        county_count=county_count,
    )


def _slugify_name(raw_name: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", raw_name.lower()).strip("_")
    return normalized or "unknown"


def _discover_congressional_district_zip_name(listing_html: str, year: int, state_fips: str) -> str:
    """Discover the current TIGER congressional-district filename from listing HTML."""
    matches: list[tuple[str, int, str]] = []
    for match in _CD_FILENAME_PATTERN.finditer(listing_html):
        candidate_year = int(match.group("year"))
        if candidate_year != year:
            continue
        scope = match.group("scope").lower()
        congress_text = match.group("congress")
        congress = int(congress_text)
        filename = f"tl_{candidate_year}_{scope}_cd{congress_text}.zip"
        matches.append((scope, congress, filename))

    if not matches:
        raise ValueError(f"No congressional district zip found in listing for TIGER {year}")

    state_matches = [candidate for candidate in matches if candidate[0] == state_fips]
    us_matches = [candidate for candidate in matches if candidate[0] == "us"]
    latest_state_match = max(state_matches, key=lambda item: item[1]) if state_matches else None
    latest_us_match = max(us_matches, key=lambda item: item[1]) if us_matches else None

    if latest_state_match is not None and latest_us_match is not None:
        if latest_state_match[1] >= latest_us_match[1]:
            return latest_state_match[2]
        return latest_us_match[2]
    if latest_state_match is not None:
        return latest_state_match[2]
    if latest_us_match is not None:
        return latest_us_match[2]

    raise ValueError(f"No congressional district zip found for state FIPS {state_fips} in TIGER {year} listing")


def _discover_national_congressional_district_zip_names(listing_html: str, year: int) -> list[str]:
    latest_by_scope: dict[str, tuple[int, str]] = {}
    for match in _CD_FILENAME_PATTERN.finditer(listing_html):
        candidate_year = int(match.group("year"))
        if candidate_year != year:
            continue
        scope = match.group("scope").lower()
        congress_text = match.group("congress")
        congress = int(congress_text)
        filename = f"tl_{candidate_year}_{scope}_cd{congress_text}.zip"
        current = latest_by_scope.get(scope)
        if current is None or congress > current[0]:
            latest_by_scope[scope] = (congress, filename)

    us_match = latest_by_scope.get("us")
    if us_match is not None:
        return [us_match[1]]

    state_scoped_inventory = {scope: item for scope, item in latest_by_scope.items() if scope.isdigit()}
    if state_scoped_inventory:
        congress_numbers = {item[0] for item in state_scoped_inventory.values()}
        if len(congress_numbers) != 1:
            raise ValueError(f"State-scoped congressional district inventory mixes Congress numbers in TIGER {year}")
        return [item[1] for scope, item in sorted(state_scoped_inventory.items())]
    raise ValueError(f"No congressional district zip found in listing for TIGER {year}")


def _congress_number_from_cd_zip_url(zip_url: str) -> int:
    filename = Path(zip_url).name
    match = _CD_FILENAME_PATTERN.fullmatch(filename)
    if match is None:
        raise ValueError(f"Could not determine Congress number from congressional district zip URL: {zip_url}")
    return int(match.group("congress"))


def _boundary_year_for_congressional_zip_url(zip_url: str) -> int:
    congress_number = _congress_number_from_cd_zip_url(zip_url)
    return congressional_boundary_year_for_congress(congress_number)


def _download_url(url: str) -> bytes:
    last_error: BaseException | None = None
    for _attempt in range(_DOWNLOAD_ATTEMPTS):
        try:
            with urlopen(url, timeout=_DOWNLOAD_TIMEOUT_SECONDS) as response:  # noqa: S310
                return response.read()
        except HTTPError as error:
            if error.code not in _TRANSIENT_HTTP_STATUS_CODES:
                raise
            last_error = error
        except (ConnectionResetError, TimeoutError, URLError) as error:
            last_error = error
    assert last_error is not None
    raise last_error


def _download_text(url: str) -> str:
    return _download_url(url).decode("utf-8")


def _download_bytes(url: str) -> bytes:
    return _download_url(url)


def _nc_contract_artifact_for_level(level: str) -> _NcGeometryContractArtifact:
    artifact = _NC_CONTRACT_ARTIFACT_BY_LEVEL.get(level)
    if artifact is None:
        raise ValueError(f"Unsupported NC district level={level}")
    return artifact


def _nc_contract_url_for_level(level: str) -> str:
    return _nc_contract_artifact_for_level(level).url


def _boundary_year_for_level(*, year: int, level: str, state_fips: str) -> int:
    if state_fips == "37" and level in _NC_CONTRACT_ARTIFACT_BY_LEVEL:
        return _nc_contract_artifact_for_level(level).boundary_year
    return year


def _zip_url_for_level(*, year: int, level: str, state_fips: str) -> str:
    if level not in _LEVEL_CHOICES:
        raise ValueError(f"Unsupported level={level}")

    if state_fips == "37" and level in _NC_CONTRACT_ARTIFACT_BY_LEVEL:
        return _nc_contract_url_for_level(level)

    base_url = _TIGER_BASE_URL.format(year=year)
    if level == "state":
        return f"{base_url}/STATE/tl_{year}_us_state.zip"
    if level == "county":
        return f"{base_url}/COUNTY/tl_{year}_us_county.zip"
    if level in {"state_legislative_upper", "state_legislative_lower"}:
        raise ValueError(f"Unsupported level={level} for non-NC state_fips={state_fips}")

    listing_url = f"{base_url}/CD/"
    listing_html = _download_text(listing_url)
    zip_name = _discover_congressional_district_zip_name(listing_html, year=year, state_fips=state_fips)
    return f"{listing_url}{zip_name}"


def _zip_urls_for_national_congressional_districts(*, year: int) -> list[str]:
    base_url = _TIGER_BASE_URL.format(year=year)
    listing_url = f"{base_url}/CD/"
    listing_html = _download_text(listing_url)
    zip_names = _discover_national_congressional_district_zip_names(listing_html, year=year)
    return [f"{listing_url}{zip_name}" for zip_name in zip_names]


def _run_ogr2ogr_geojson_export(
    zip_path: Path,
    *,
    source_srs: str | None = None,
    target_srs: str = "EPSG:4326",
) -> str:
    """Extract one shapefile from zip and export it as GeoJSON through ogr2ogr."""
    with tempfile.TemporaryDirectory(prefix="civics_tiger_") as temp_dir:
        temp_path = Path(temp_dir)
        with ZipFile(zip_path) as zip_file:
            zip_file.extractall(temp_path)

        shapefiles = sorted(temp_path.glob("*.shp"))
        if not shapefiles:
            raise ValueError(f"TIGER zip has no .shp members: {zip_path}")

        command = ["ogr2ogr", "-f", "GeoJSON", "-t_srs", target_srs, "/vsistdout/"]
        if source_srs is not None:
            command.extend(["-s_srs", source_srs])
        command.append(str(shapefiles[0]))

        process = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
        )
        return process.stdout


def _iter_geojson_features_from_shapefile_zip_with_srs(
    zip_path: Path,
    *,
    source_srs: str | None,
    target_srs: str = "EPSG:4326",
) -> list[dict[str, object]]:
    geojson_text = _run_ogr2ogr_geojson_export(
        zip_path,
        source_srs=source_srs,
        target_srs=target_srs,
    )
    geojson_payload = json.loads(geojson_text)
    if geojson_payload.get("type") != "FeatureCollection":
        raise ValueError("ogr2ogr export did not return a GeoJSON FeatureCollection")
    features = geojson_payload.get("features")
    if not isinstance(features, list):
        raise ValueError("GeoJSON FeatureCollection missing features list")
    return [feature for feature in features if isinstance(feature, dict)]


def _iter_geojson_features_from_shapefile_zip(zip_path: Path) -> list[dict[str, object]]:
    return _iter_geojson_features_from_shapefile_zip_with_srs(
        zip_path,
        source_srs=None,
        target_srs="EPSG:4326",
    )


def _download_shapefile_zip_features(
    zip_url: str,
    *,
    source_srs: str | None,
) -> list[dict[str, object]]:
    zip_payload = _download_bytes(zip_url)
    with tempfile.NamedTemporaryFile(prefix="civics_tiger_", suffix=".zip", delete=True) as temp_zip:
        temp_zip.write(zip_payload)
        temp_zip.flush()
        return _iter_geojson_features_from_shapefile_zip_with_srs(
            Path(temp_zip.name),
            source_srs=source_srs,
            target_srs="EPSG:4326",
        )


def _iter_geojson_features_from_arcgis_featureserver(
    feature_server_url: str,
    *,
    result_record_count: int = 2000,
) -> list[dict[str, object]]:
    """Query a FeatureServer layer and return all feature objects as GeoJSON dicts."""
    if result_record_count <= 0:
        raise ValueError("result_record_count must be positive")

    query_base = f"{feature_server_url.rstrip('/')}/0/query"
    result_offset = 0
    features: list[dict[str, object]] = []

    while True:
        query_params = urlencode(
            {
                "where": "1=1",
                "outFields": "*",
                "returnGeometry": "true",
                "outSR": "4326",
                "f": "geojson",
                "resultOffset": str(result_offset),
                "resultRecordCount": str(result_record_count),
            }
        )
        payload = json.loads(_download_text(f"{query_base}?{query_params}"))
        response_features = payload.get("features")
        if not isinstance(response_features, list):
            details = payload.get("error") if isinstance(payload, dict) else payload
            raise ValueError(f"FeatureServer query did not return features list: {details}")

        page_features = [feature for feature in response_features if isinstance(feature, dict)]
        features.extend(page_features)

        if not payload.get("exceededTransferLimit") or len(response_features) < result_record_count:
            break
        result_offset += result_record_count
    return features


def _state_fips_for_code(conn: psycopg.Connection, state: str) -> str:
    row = conn.execute(
        """
        SELECT fips
        FROM core.jurisdiction
        WHERE jurisdiction_type = 'state'
          AND state = %s
        LIMIT 1
        """,
        (state,),
    ).fetchone()
    if row is None or not isinstance(row[0], str) or not row[0]:
        raise ValueError(f"Could not resolve state FIPS for state={state}")
    return row[0]


def _district_number_from_properties(properties: dict[str, object]) -> str:
    district_value = properties.get("DISTRICT")
    if isinstance(district_value, str) and district_value.strip():
        normalized = re.sub(r"[^0-9]", "", district_value.strip())
        if normalized:
            return normalized.zfill(2)

    for key, value in properties.items():
        if _CD_FIELD_PATTERN.fullmatch(key) and isinstance(value, str) and value.strip():
            return value.strip().zfill(2)
    raise ValueError("Missing district number field (expected DISTRICT or CD###FP)")


def _state_code_from_properties(properties: dict[str, object]) -> str:
    stusps = properties.get("STUSPS")
    if isinstance(stusps, str) and stusps.strip():
        return stusps.strip().upper()

    statefp = properties.get("STATEFP")
    if isinstance(statefp, str) and statefp.strip():
        state_code = CENSUS_STATE_FIPS_TO_USPS_MAP.get(statefp.strip().zfill(2))
        if state_code is not None:
            return state_code
    raise ValueError("TIGER congressional district feature missing recognized STUSPS or STATEFP")


def _school_district_number_from_properties(properties: dict[str, object]) -> str:
    lea_value = properties.get("LEA")
    if isinstance(lea_value, str) and lea_value.strip():
        digits = re.sub(r"[^0-9]", "", lea_value)
        if digits:
            return digits.zfill(3)
    raise ValueError("Missing school district LEA value")


def _municipal_name_from_properties(properties: dict[str, object]) -> str:
    municipal_name = properties.get("MunicipalName")
    if isinstance(municipal_name, str) and municipal_name.strip():
        return municipal_name.strip()
    raise ValueError("Municipal feature missing MunicipalName")


def _ocd_id_for_level(*, level: str, state_lower: str, district_number: str) -> str | None:
    segment = _DISTRICT_NAME_SEGMENT_BY_LEVEL.get(level)
    if segment is None:
        return None
    return f"ocd-division/country:us/state:{state_lower}/{segment}:{district_number}"


def _normalize_tiger_feature(
    *,
    level: str,
    state: str,
    feature: dict[str, object],
    boundary_year: int,
) -> ElectoralDivision:
    properties = feature.get("properties")
    geometry = feature.get("geometry")
    if not isinstance(properties, dict):
        raise ValueError("TIGER feature properties must be an object")
    if not isinstance(geometry, dict):
        raise ValueError("TIGER feature geometry must be an object")

    state_lower = state.lower()
    ocd_id: str | None = None
    if level == "state":
        name = state_lower
        district_number = None
    elif level == "county":
        county_name = str(properties.get("NAME", "")).strip()
        if not county_name:
            raise ValueError("County feature missing NAME")
        name = f"{state_lower}_county_{_slugify_name(county_name)}"
        district_number = None
    elif level == "municipal":
        municipal_name = _municipal_name_from_properties(properties)
        municipality_slug = _slugify_name(municipal_name)
        name = f"{state_lower}_municipal_{municipality_slug}"
        district_number = None
        ocd_id = f"ocd-division/country:us/state:{state_lower}/place:{municipality_slug}"
    elif level == "school_district":
        district_number = _school_district_number_from_properties(properties)
        name = f"{state_lower}_school_district_{district_number}"
        ocd_id = _ocd_id_for_level(level=level, state_lower=state_lower, district_number=district_number)
    else:
        district_number = _district_number_from_properties(properties)
        name_segment = _DISTRICT_NAME_SEGMENT_BY_LEVEL[level]
        name = f"{state_lower}_{name_segment}_{district_number}"
        ocd_id = _ocd_id_for_level(level=level, state_lower=state_lower, district_number=district_number)

    return ElectoralDivision(
        name=name,
        division_type=_LEVEL_TO_DIVISION_TYPE[level],
        state=state,
        district_number=district_number,
        ocd_id=ocd_id,
        boundary_year=boundary_year,
        geometry=geometry,
    )


def _as_multipolygon_geometry(geometry: dict[str, object]) -> dict[str, object]:
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if geometry_type == "MultiPolygon" and isinstance(coordinates, list):
        return {"type": "MultiPolygon", "coordinates": coordinates}
    if geometry_type == "Polygon" and isinstance(coordinates, list):
        return {"type": "MultiPolygon", "coordinates": [coordinates]}
    raise ValueError(f"Unsupported geometry type for municipal merge: {geometry_type}")


def _merge_municipal_divisions(divisions: list[ElectoralDivision]) -> list[ElectoralDivision]:
    merged_by_name: dict[str, ElectoralDivision] = {}
    for division in divisions:
        if division.division_type != "municipal":
            raise ValueError("Municipal merge received non-municipal division")
        normalized_geometry = _as_multipolygon_geometry(division.geometry)
        current = merged_by_name.get(division.name)
        if current is None:
            merged_by_name[division.name] = division.model_copy(update={"geometry": normalized_geometry})
            continue
        current_geometry = _as_multipolygon_geometry(current.geometry)
        merged_coordinates = list(current_geometry["coordinates"])
        merged_coordinates.extend(normalized_geometry["coordinates"])
        merged_by_name[division.name] = current.model_copy(
            update={"geometry": {"type": "MultiPolygon", "coordinates": merged_coordinates}}
        )
    return list(merged_by_name.values())


def _feature_matches_state(*, level: str, state: str, state_fips: str, properties: dict[str, object]) -> bool:
    if state == "NC" and level == "county":
        if properties.get("STATEFP") != state_fips:
            return False
        return _is_nc_scope_county(
            county_name=properties.get("NAME"),
            county_fips=properties.get("COUNTYFP"),
        )

    if state == "NC" and level == "municipal":
        county_name = properties.get("County")
        municipal_name = properties.get("MunicipalName")
        return (
            _is_nc_scope_county(county_name=county_name)
            and isinstance(municipal_name, str)
            and bool(municipal_name.strip())
        )

    if state == "NC" and level == "school_district":
        return _is_nc_scope_county(county_fips=properties.get("COUNTYFP"))

    if state == "NC" and level in _NC_CONTRACT_ARTIFACT_BY_LEVEL:
        statefp = properties.get("STATEFP")
        if statefp is None:
            return True
        return statefp == state_fips

    if level == "state":
        stusps = properties.get("STUSPS")
        if isinstance(stusps, str) and stusps.upper() == state:
            return True
    return properties.get("STATEFP") == state_fips


def _upsert_divisions(conn: psycopg.Connection, divisions: list[ElectoralDivision]) -> int:
    upserted_count = 0
    for division in divisions:
        upsert_electoral_division(conn, division)
        upserted_count += 1
    return upserted_count


def _without_timeless_ocd_id(division: ElectoralDivision) -> ElectoralDivision:
    return division.model_copy(update={"ocd_id": None})


def load_tiger_geometry(conn: psycopg.Connection, *, state: str, level: str, year: int) -> int:
    """Load TIGER polygons for one (state, level, year) target."""
    if level not in _LEVEL_CHOICES:
        raise ValueError(f"Unsupported level={level}")

    state_code = state.upper()
    state_fips = _state_fips_for_code(conn, state_code)
    zip_url = _zip_url_for_level(year=year, level=level, state_fips=state_fips)
    nc_contract_artifact: _NcGeometryContractArtifact | None = None
    if state_fips == "37" and level in _NC_CONTRACT_ARTIFACT_BY_LEVEL:
        nc_contract_artifact = _nc_contract_artifact_for_level(level)

    boundary_year = _boundary_year_for_level(year=year, level=level, state_fips=state_fips)
    if level == "congressional_district" and nc_contract_artifact is None:
        boundary_year = _boundary_year_for_congressional_zip_url(zip_url)

    if nc_contract_artifact is not None and nc_contract_artifact.provider == "nconemap":
        features = _iter_geojson_features_from_arcgis_featureserver(zip_url)
    else:
        source_srs = nc_contract_artifact.source_srs if nc_contract_artifact is not None else None
        features = _download_shapefile_zip_features(zip_url, source_srs=source_srs)

    parsed_divisions: list[ElectoralDivision] = []
    for feature in features:
        properties = feature.get("properties")
        if not isinstance(properties, dict):
            continue
        if not _feature_matches_state(level=level, state=state_code, state_fips=state_fips, properties=properties):
            continue
        division = _normalize_tiger_feature(
            level=level,
            state=state_code,
            feature=feature,
            boundary_year=boundary_year,
        )
        parsed_divisions.append(division)

    divisions_to_upsert = (
        _merge_municipal_divisions(parsed_divisions)
        if state_code == "NC" and level == "municipal"
        else parsed_divisions
    )

    return _upsert_divisions(conn, divisions_to_upsert)


def load_national_congressional_district_geometry(conn: psycopg.Connection, *, year: int) -> int:
    """Load national TIGER congressional district polygons for one TIGER artifact year."""
    level = "congressional_district"
    divisions: list[ElectoralDivision] = []
    for zip_url in _zip_urls_for_national_congressional_districts(year=year):
        boundary_year = _boundary_year_for_congressional_zip_url(zip_url)
        features = _download_shapefile_zip_features(zip_url, source_srs=None)
        for feature in features:
            properties = feature.get("properties")
            if not isinstance(properties, dict):
                continue
            state_code = _state_code_from_properties(properties)
            division = _normalize_tiger_feature(
                level=level,
                state=state_code,
                feature=feature,
                boundary_year=boundary_year,
            )
            divisions.append(_without_timeless_ocd_id(division))
    return _upsert_divisions(conn, divisions)


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Load TIGER geometry rows into civic.electoral_division")
    parser.add_argument(
        "--national-congressional-districts",
        action="store_true",
        help="Load the national TIGER congressional-district artifact for --year",
    )
    parser.add_argument("--state", help="Two-letter state code, e.g. NC")
    parser.add_argument(
        "--level",
        choices=_LEVEL_CHOICES,
        help="Geometry level to load: state, county, or congressional_district",
    )
    parser.add_argument("--year", required=True, type=int, help="TIGER boundary year (e.g. 2024)")
    return parser


def _validate_load_args(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    if args.national_congressional_districts:
        if args.state is not None or args.level is not None:
            parser.error("--national-congressional-districts cannot be combined with --state or --level")
        return
    if args.state is None or args.level is None:
        parser.error("--state and --level are required unless --national-congressional-districts is set")


def main(argv: list[str] | None = None) -> int:
    if argv is None and {"--state-shapefile", "--county-shapefile"} & set(sys.argv[1:]):
        parser = argparse.ArgumentParser(description="Load TIGER state/county geometry")
        parser.add_argument("--state-shapefile", type=Path, required=True)
        parser.add_argument("--county-shapefile", type=Path, required=True)
        parser.add_argument("--vintage", type=int, default=2024)
        args = parser.parse_args()

        conn = get_connection()
        try:
            with conn.transaction():
                summary = load_tiger_states_and_counties(
                    conn,
                    state_shapefile_path=args.state_shapefile,
                    county_shapefile_path=args.county_shapefile,
                    vintage=args.vintage,
                )
            conn.commit()
            print(f"Loaded {summary.state_count} states, {summary.county_count} counties")
        finally:
            conn.close()
        return 0

    parser = _build_argument_parser()
    args = parser.parse_args(argv)
    _validate_load_args(args, parser)
    conn: psycopg.Connection | None = None
    try:
        conn = get_connection()
        with conn.transaction():
            if args.national_congressional_districts:
                upserted = load_national_congressional_district_geometry(conn, year=args.year)
            else:
                upserted = load_tiger_geometry(conn, state=args.state, level=args.level, year=args.year)
    except Exception as exc:  # noqa: BLE001
        print(f"TIGER geometry load failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if conn is not None:
            conn.close()

    if args.national_congressional_districts:
        print(
            f"TIGER geometry load complete: scope=national level=congressional_district year={args.year} rows={upserted}"
        )
    else:
        print(
            f"TIGER geometry load complete: state={args.state.upper()} level={args.level} year={args.year} rows={upserted}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
