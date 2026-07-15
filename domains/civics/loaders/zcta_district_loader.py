
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import timezone
from decimal import Decimal, ROUND_HALF_UP
from io import TextIOWrapper
from pathlib import Path
from typing import TextIO
from urllib.request import urlopen

import psycopg

from core.db import get_connection, insert_data_source, insert_source_record, select_active_source_record_by_key
from core.types.python.models import DataSource, SourceRecord, utc_now
from domains.civics.loaders import tiger_geometry

CENSUS_CD119_ZCTA_RELATIONSHIP_URL = (
    "https://www2.census.gov/geo/docs/maps-data/data/rel2020/cd-sld/tab20_cd11920_zcta520_natl.txt"
)
TIGER_CD_LISTING_DATA_SOURCE_NAME = "Census TIGER congressional district listing"
_TIGER_CD_LISTING_SOURCE_RECORD_KEY_PREFIX = "tiger-cd-listing"
_LAND_SHARE_PRECISION = Decimal("0.00001")
_ZERO = Decimal("0")
_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class TigerCdListingProbeResult:
    year: int
    listing_url: str
    current_hash: str
    previous_hash: str | None
    changed: bool


def _open_relationship_source(source: str | Path) -> TextIO:
    if str(source).startswith(("http://", "https://")):
        response = urlopen(str(source), timeout=60)  # noqa: S310
        return TextIOWrapper(response, encoding="utf-8-sig", newline="")
    return Path(source).open("r", encoding="utf-8-sig", newline="")


def _decimal_from_row(row: dict[str, str], field_name: str) -> Decimal:
    return Decimal((row.get(field_name) or "0").strip() or "0")


def _candidate_parts(candidate: dict[str, object]) -> tuple[Decimal, Decimal, str]:
    land_part = candidate["land_part"]
    water_part = candidate["water_part"]
    cd_geoid = candidate["cd_geoid"]
    assert isinstance(land_part, Decimal)
    assert isinstance(water_part, Decimal)
    assert isinstance(cd_geoid, str)
    return (land_part, land_part + water_part, cd_geoid)


def _candidate_is_better(candidate: dict[str, object], current_winner: dict[str, object]) -> bool:
    candidate_land, candidate_total_area, candidate_cd_geoid = _candidate_parts(candidate)
    winner_land, winner_total_area, winner_cd_geoid = _candidate_parts(current_winner)
    return (
        candidate_land > winner_land
        or (candidate_land == winner_land and candidate_total_area > winner_total_area)
        or (
            candidate_land == winner_land
            and candidate_total_area == winner_total_area
            and candidate_cd_geoid < winner_cd_geoid
        )
    )


def _selected_row(
    *,
    zcta5: str,
    winning_candidate: dict[str, object],
    total_land: Decimal,
    boundary_year: int,
) -> dict[str, object]:
    winning_land = winning_candidate["land_part"]
    cd_geoid = winning_candidate["cd_geoid"]
    assert isinstance(winning_land, Decimal)
    assert isinstance(cd_geoid, str)

    land_share = _ZERO
    if total_land > 0:
        land_share = (winning_land / total_land).quantize(_LAND_SHARE_PRECISION, rounding=ROUND_HALF_UP)

    return {
        "zcta5": zcta5,
        "boundary_year": boundary_year,
        "state_fips": cd_geoid[:2],
        "cd_geoid": cd_geoid,
        "district_number": cd_geoid[2:],
        "land_share": land_share,
    }


def select_dominant_zcta_districts(
    rows: Iterable[dict[str, str]],
    *,
    boundary_year: int,
) -> dict[str, dict[str, object]]:
    """Select one dominant 119th congressional district per ZCTA from Census relationship rows."""
    winners_by_zcta: dict[str, dict[str, object]] = {}
    total_land_by_zcta: dict[str, Decimal] = {}

    for row in rows:
        zcta5 = (row.get("GEOID_ZCTA5_20") or "").strip()
        if not zcta5:
            continue

        candidate = {
            "cd_geoid": (row.get("GEOID_CD119_20") or "").strip(),
            "land_part": _decimal_from_row(row, "AREALAND_PART"),
            "water_part": _decimal_from_row(row, "AREAWATER_PART"),
        }
        total_land_by_zcta[zcta5] = total_land_by_zcta.get(zcta5, _ZERO) + candidate["land_part"]

        current_winner = winners_by_zcta.get(zcta5)
        if current_winner is None or _candidate_is_better(candidate, current_winner):
            winners_by_zcta[zcta5] = candidate

    return {
        zcta5: _selected_row(
            zcta5=zcta5,
            winning_candidate=winning_candidate,
            total_land=total_land_by_zcta[zcta5],
            boundary_year=boundary_year,
        )
        for zcta5, winning_candidate in winners_by_zcta.items()
    }


def load_zcta_districts(*, source: str | Path = CENSUS_CD119_ZCTA_RELATIONSHIP_URL, boundary_year: int) -> int:
    """Replace one civic.zcta_district boundary vintage from one Census relationship source."""
    with _open_relationship_source(source) as handle:
        reader = csv.DictReader(handle, delimiter="|")
        header_names = {name.strip() for name in (reader.fieldnames or [])}
        if {"GEOID_CD119_20", "GEOID_ZCTA5_20", "AREALAND_PART"} - header_names:
            raise ValueError("Census ZCTA relationship file is missing required headers")
        selected_rows = select_dominant_zcta_districts(reader, boundary_year=boundary_year)

    connection = get_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM civic.zcta_district WHERE boundary_year = %s", (boundary_year,))
            cursor.executemany(
                """
                INSERT INTO civic.zcta_district (
                    zcta5,
                    boundary_year,
                    state_fips,
                    cd_geoid,
                    district_number,
                    land_share,
                    source_url
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (zcta5, boundary_year) DO UPDATE SET
                    state_fips = EXCLUDED.state_fips,
                    cd_geoid = EXCLUDED.cd_geoid,
                    district_number = EXCLUDED.district_number,
                    land_share = EXCLUDED.land_share,
                    source_url = EXCLUDED.source_url
                """,
                [
                    (
                        row["zcta5"],
                        row["boundary_year"],
                        row["state_fips"],
                        row["cd_geoid"],
                        row["district_number"],
                        row["land_share"],
                        str(source),
                    )
                    for row in selected_rows.values()
                ],
            )
        connection.commit()
        return len(selected_rows)
    finally:
        connection.close()


def _tiger_cd_listing_url(year: int) -> str:
    return f"https://www2.census.gov/geo/tiger/TIGER{year}/CD/"


def compute_tiger_cd_listing_hash(listing_html: str, *, year: int) -> str:
    zip_names = tiger_geometry._discover_national_congressional_district_zip_names(listing_html, year)
    payload = json.dumps({"year": year, "zip_names": sorted(zip_names)}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _ensure_tiger_cd_listing_data_source(conn: psycopg.Connection) -> object:
    data_source = DataSource(
        domain="civics",
        jurisdiction="federal/geometry",
        name=TIGER_CD_LISTING_DATA_SOURCE_NAME,
        source_url="https://www2.census.gov/geo/tiger/",
        source_format="html",
        update_frequency="weekly",
        notes="Directory listing hash probe for TIGER congressional district boundary artifacts.",
    )
    row = conn.execute(
        """
        SELECT id
        FROM core.data_source
        WHERE domain = %s
          AND jurisdiction = %s
          AND name = %s
        """,
        (data_source.domain, data_source.jurisdiction, data_source.name),
    ).fetchone()
    if row is not None:
        return row[0]
    insert_data_source(conn, data_source)
    return data_source.id


def _source_record_key_for_tiger_cd_listing(year: int) -> str:
    return f"{_TIGER_CD_LISTING_SOURCE_RECORD_KEY_PREFIX}-{year}"


def _read_stored_tiger_cd_listing_hash(conn: psycopg.Connection, *, year: int) -> str | None:
    data_source_id = _ensure_tiger_cd_listing_data_source(conn)
    source_record = select_active_source_record_by_key(
        conn,
        data_source_id=data_source_id,
        source_record_key=_source_record_key_for_tiger_cd_listing(year),
    )
    return None if source_record is None else source_record.record_hash


def _store_tiger_cd_listing_hash(conn: psycopg.Connection, year: int, manifest_hash: str) -> None:
    data_source_id = _ensure_tiger_cd_listing_data_source(conn)
    source_record_key = _source_record_key_for_tiger_cd_listing(year)
    active_record = select_active_source_record_by_key(
        conn,
        data_source_id=data_source_id,
        source_record_key=source_record_key,
    )
    source_record = SourceRecord(
        data_source_id=data_source_id,
        source_record_key=source_record_key,
        source_url=_tiger_cd_listing_url(year),
        raw_fields={"boundary_year": year, "listing_hash": manifest_hash},
        pull_date=utc_now().astimezone(timezone.utc),
        record_hash=manifest_hash,
    )
    if active_record is not None:
        conn.execute(
            "UPDATE core.source_record SET superseded_by = %s WHERE id = %s",
            (source_record.id, active_record.id),
        )
    insert_source_record(conn, source_record)


def probe_tiger_congressional_district_listing(
    conn: psycopg.Connection,
    *,
    year: int = 2024,
) -> TigerCdListingProbeResult:
    listing_url = _tiger_cd_listing_url(year)
    listing_html = tiger_geometry._download_text(listing_url)
    current_hash = compute_tiger_cd_listing_hash(listing_html, year=year)
    previous_hash = _read_stored_tiger_cd_listing_hash(conn, year=year)
    changed = previous_hash is not None and previous_hash != current_hash
    if previous_hash is None or changed:
        _store_tiger_cd_listing_hash(conn, year, current_hash)
    if changed:
        _LOGGER.warning(
            "TIGER congressional district listing changed for year %s: previous=%s current=%s",
            year,
            previous_hash,
            current_hash,
        )
    return TigerCdListingProbeResult(
        year=year,
        listing_url=listing_url,
        current_hash=current_hash,
        previous_hash=previous_hash,
        changed=changed,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load the Census ZCTA5-to-119th-district approximation table")
    parser.add_argument("--source", default=CENSUS_CD119_ZCTA_RELATIONSHIP_URL)
    parser.add_argument("--boundary-year", type=int, required=True)
    args = parser.parse_args(argv)
    loaded_count = load_zcta_districts(source=args.source, boundary_year=args.boundary_year)
    print(f"Loaded {loaded_count} ZCTA district rows from {args.source} for boundary year {args.boundary_year}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
