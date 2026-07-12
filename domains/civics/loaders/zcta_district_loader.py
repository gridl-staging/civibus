
from __future__ import annotations

import argparse
import csv
from collections.abc import Iterable
from decimal import Decimal, ROUND_HALF_UP
from io import TextIOWrapper
from pathlib import Path
from typing import TextIO
from urllib.request import urlopen

from core.db import get_connection

CENSUS_CD119_ZCTA_RELATIONSHIP_URL = (
    "https://www2.census.gov/geo/docs/maps-data/data/rel2020/cd-sld/tab20_cd11920_zcta520_natl.txt"
)
_LAND_SHARE_PRECISION = Decimal("0.00001")
_ZERO = Decimal("0")


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
        "state_fips": cd_geoid[:2],
        "cd_geoid": cd_geoid,
        "district_number": cd_geoid[2:],
        "land_share": land_share,
    }


def select_dominant_zcta_districts(rows: Iterable[dict[str, str]]) -> dict[str, dict[str, object]]:
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
        zcta5: _selected_row(zcta5=zcta5, winning_candidate=winning_candidate, total_land=total_land_by_zcta[zcta5])
        for zcta5, winning_candidate in winners_by_zcta.items()
    }


def load_zcta_districts(*, source: str | Path = CENSUS_CD119_ZCTA_RELATIONSHIP_URL) -> int:
    """Replace civic.zcta_district with selected rows from one Census relationship source."""
    with _open_relationship_source(source) as handle:
        reader = csv.DictReader(handle, delimiter="|")
        header_names = {name.strip() for name in (reader.fieldnames or [])}
        if {"GEOID_CD119_20", "GEOID_ZCTA5_20", "AREALAND_PART"} - header_names:
            raise ValueError("Census ZCTA relationship file is missing required headers")
        selected_rows = select_dominant_zcta_districts(reader)

    connection = get_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("TRUNCATE TABLE civic.zcta_district")
            cursor.executemany(
                """
                INSERT INTO civic.zcta_district (
                    zcta5,
                    state_fips,
                    cd_geoid,
                    district_number,
                    land_share,
                    source_url
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                [
                    (
                        row["zcta5"],
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load the Census ZCTA5-to-119th-district approximation table")
    parser.add_argument("--source", default=CENSUS_CD119_ZCTA_RELATIONSHIP_URL)
    args = parser.parse_args(argv)
    loaded_count = load_zcta_districts(source=args.source)
    print(f"Loaded {loaded_count} ZCTA district rows from {args.source}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
