"""Contract tests for the Census ZCTA-to-congressional-district relationship file."""

from __future__ import annotations

import csv
import logging
from decimal import Decimal
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
RELATIONSHIP_SAMPLE_PATH = REPO_ROOT / "tests" / "fixtures" / "civics_zcta_district_relationship_sample.txt"
REQUIRED_RELATIONSHIP_COLUMNS = {
    "GEOID_CD119_20",
    "GEOID_ZCTA5_20",
    "AREALAND_PART",
}


class _RecordingCursor:
    def __init__(self) -> None:
        self.executed_sql: list[str] = []
        self.executemany_sql: str | None = None
        self.executemany_parameters: list[tuple[Any, ...]] = []

    def __enter__(self) -> "_RecordingCursor":
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def execute(self, sql: str, parameters: tuple[Any, ...] | None = None) -> None:
        self.executed_sql.append(" ".join(sql.split()))
        if parameters is not None:
            self.executed_sql[-1] += f" {parameters!r}"

    def executemany(self, sql: str, parameters: list[tuple[Any, ...]]) -> None:
        self.executemany_sql = " ".join(sql.split())
        self.executemany_parameters = list(parameters)


class _RecordingConnection:
    def __init__(self) -> None:
        self.cursor_instance = _RecordingCursor()
        self.committed = False
        self.closed = False

    def cursor(self) -> _RecordingCursor:
        return self.cursor_instance

    def commit(self) -> None:
        self.committed = True

    def close(self) -> None:
        self.closed = True


def _import_zcta_district_loader():
    from domains.civics.loaders import zcta_district_loader

    return zcta_district_loader


def _read_relationship_sample_rows() -> list[dict[str, str]]:
    with RELATIONSHIP_SAMPLE_PATH.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="|"))


def test_fixture_preserves_census_cd119_zcta_relationship_header_contract() -> None:
    header_line = RELATIONSHIP_SAMPLE_PATH.read_text(encoding="utf-8-sig").splitlines()[0]
    header_columns = header_line.split("|")

    assert header_line.count("|") == 16
    assert REQUIRED_RELATIONSHIP_COLUMNS.issubset(header_columns)


def test_zcta_dominant_district_selector_known_answer_contract() -> None:
    loader = _import_zcta_district_loader()
    selector = getattr(loader, "select_dominant_zcta_districts")

    selected_by_zcta = selector(iter(_read_relationship_sample_rows()), boundary_year=2022)

    assert selected_by_zcta == {
        "71101": {
            "zcta5": "71101",
            "boundary_year": 2022,
            "state_fips": "22",
            "cd_geoid": "2204",
            "district_number": "04",
            "land_share": Decimal("0.69231"),
        },
        "73301": {
            "zcta5": "73301",
            "boundary_year": 2022,
            "state_fips": "48",
            "cd_geoid": "4804",
            "district_number": "04",
            "land_share": Decimal("0.50000"),
        },
    }


def test_zcta_loader_streams_fixture_and_writes_selected_rows(monkeypatch) -> None:
    loader = _import_zcta_district_loader()
    connection = _RecordingConnection()
    monkeypatch.setattr(loader, "get_connection", lambda: connection)

    loaded_count = loader.load_zcta_districts(source=RELATIONSHIP_SAMPLE_PATH, boundary_year=2022)

    cursor = connection.cursor_instance
    assert loaded_count == 2
    assert cursor.executed_sql == ["DELETE FROM civic.zcta_district WHERE boundary_year = %s (2022,)"]
    assert cursor.executemany_sql == (
        "INSERT INTO civic.zcta_district "
        "( zcta5, boundary_year, state_fips, cd_geoid, district_number, land_share, source_url ) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (zcta5, boundary_year) DO UPDATE SET "
        "state_fips = EXCLUDED.state_fips, cd_geoid = EXCLUDED.cd_geoid, "
        "district_number = EXCLUDED.district_number, land_share = EXCLUDED.land_share, "
        "source_url = EXCLUDED.source_url"
    )
    assert cursor.executemany_parameters == [
        ("71101", 2022, "22", "2204", "04", Decimal("0.69231"), str(RELATIONSHIP_SAMPLE_PATH)),
        ("73301", 2022, "48", "4804", "04", Decimal("0.50000"), str(RELATIONSHIP_SAMPLE_PATH)),
    ]
    assert connection.committed is True
    assert connection.closed is True


def test_zcta_selector_keeps_vintages_independent_when_winning_district_changes() -> None:
    loader = _import_zcta_district_loader()
    rows_2022 = [
        {"GEOID_ZCTA5_20": "12345", "GEOID_CD119_20": "3701", "AREALAND_PART": "9", "AREAWATER_PART": "0"},
        {"GEOID_ZCTA5_20": "12345", "GEOID_CD119_20": "3702", "AREALAND_PART": "1", "AREAWATER_PART": "0"},
    ]
    rows_2024 = [
        {"GEOID_ZCTA5_20": "12345", "GEOID_CD119_20": "3701", "AREALAND_PART": "1", "AREAWATER_PART": "0"},
        {"GEOID_ZCTA5_20": "12345", "GEOID_CD119_20": "3702", "AREALAND_PART": "9", "AREAWATER_PART": "0"},
    ]

    assert loader.select_dominant_zcta_districts(rows_2022, boundary_year=2022)["12345"]["cd_geoid"] == "3701"
    selected_2024 = loader.select_dominant_zcta_districts(rows_2024, boundary_year=2024)["12345"]
    assert selected_2024["cd_geoid"] == "3702"
    assert selected_2024["boundary_year"] == 2024


def test_tiger_cd_listing_probe_records_baseline_without_warning(monkeypatch, caplog) -> None:
    loader = _import_zcta_district_loader()
    records: dict[str, str] = {}
    monkeypatch.setattr(loader.tiger_geometry, "_download_text", lambda url: "<a>tl_2024_us_cd119.zip</a>")
    monkeypatch.setattr(loader, "_read_stored_tiger_cd_listing_hash", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        loader,
        "_store_tiger_cd_listing_hash",
        lambda _conn, year, manifest_hash: records.update({str(year): manifest_hash}),
    )

    with caplog.at_level(logging.WARNING):
        result = loader.probe_tiger_congressional_district_listing(object(), year=2024)

    assert result.changed is False
    assert result.previous_hash is None
    assert records["2024"] == result.current_hash
    assert not [record for record in caplog.records if record.levelno >= logging.WARNING]


def test_tiger_cd_listing_probe_same_hash_is_quiet(monkeypatch, caplog) -> None:
    loader = _import_zcta_district_loader()
    monkeypatch.setattr(loader.tiger_geometry, "_download_text", lambda url: "<a>tl_2024_us_cd119.zip</a>")
    current_hash = loader.compute_tiger_cd_listing_hash("<a>tl_2024_us_cd119.zip</a>", year=2024)
    monkeypatch.setattr(loader, "_read_stored_tiger_cd_listing_hash", lambda *_args, **_kwargs: current_hash)
    store = monkeypatch.setattr(loader, "_store_tiger_cd_listing_hash", lambda *_args, **_kwargs: None)

    with caplog.at_level(logging.WARNING):
        result = loader.probe_tiger_congressional_district_listing(object(), year=2024)

    assert store is None
    assert result.changed is False
    assert result.previous_hash == current_hash
    assert not [record for record in caplog.records if record.levelno >= logging.WARNING]


def test_tiger_cd_listing_probe_warns_on_changed_hash(monkeypatch, caplog) -> None:
    loader = _import_zcta_district_loader()
    previous_hash = loader.compute_tiger_cd_listing_hash("<a>tl_2024_us_cd118.zip</a>", year=2024)
    monkeypatch.setattr(loader.tiger_geometry, "_download_text", lambda url: "<a>tl_2024_us_cd119.zip</a>")
    monkeypatch.setattr(loader, "_read_stored_tiger_cd_listing_hash", lambda *_args, **_kwargs: previous_hash)
    monkeypatch.setattr(loader, "_store_tiger_cd_listing_hash", lambda *_args, **_kwargs: None)

    with caplog.at_level(logging.WARNING):
        result = loader.probe_tiger_congressional_district_listing(object(), year=2024)

    assert result.changed is True
    assert result.previous_hash == previous_hash
    assert "TIGER congressional district listing changed" in caplog.text
