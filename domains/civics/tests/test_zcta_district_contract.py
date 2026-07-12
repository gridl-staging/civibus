"""Contract tests for the Census ZCTA-to-congressional-district relationship file."""

from __future__ import annotations

import csv
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

    def execute(self, sql: str) -> None:
        self.executed_sql.append(" ".join(sql.split()))

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

    selected_by_zcta = selector(iter(_read_relationship_sample_rows()))

    assert selected_by_zcta == {
        "71101": {
            "zcta5": "71101",
            "state_fips": "22",
            "cd_geoid": "2204",
            "district_number": "04",
            "land_share": Decimal("0.69231"),
        },
        "73301": {
            "zcta5": "73301",
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

    loaded_count = loader.load_zcta_districts(source=RELATIONSHIP_SAMPLE_PATH)

    cursor = connection.cursor_instance
    assert loaded_count == 2
    assert cursor.executed_sql == ["TRUNCATE TABLE civic.zcta_district"]
    assert cursor.executemany_sql == (
        "INSERT INTO civic.zcta_district "
        "( zcta5, state_fips, cd_geoid, district_number, land_share, source_url ) "
        "VALUES (%s, %s, %s, %s, %s, %s)"
    )
    assert cursor.executemany_parameters == [
        ("71101", "22", "2204", "04", Decimal("0.69231"), str(RELATIONSHIP_SAMPLE_PATH)),
        ("73301", "48", "4804", "04", Decimal("0.50000"), str(RELATIONSHIP_SAMPLE_PATH)),
    ]
    assert connection.committed is True
    assert connection.closed is True
