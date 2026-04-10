from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from domains.property.ingest import durham_source


def test_load_durham_config_reads_bundled_jurisdiction_asset() -> None:
    config = durham_source.load_durham_config()
    jurisdiction = config.get("jurisdiction")
    source = config.get("source")
    assert isinstance(jurisdiction, dict)
    assert isinstance(source, dict)

    assert jurisdiction["slug"] == "states/nc/counties/durham"
    assert jurisdiction["fips"] == "37063"
    assert "FeatureServer/0/query" in str(source["arcgis_query_url"])


def test_load_durham_fixture_records_reads_bundled_fixture() -> None:
    records = durham_source.load_durham_fixture_records()

    assert len(records) > 0
    assert "REID" in records[0]
    assert "PIN" in records[0]


def test_default_bundled_paths_point_to_durham_assets() -> None:
    config_path, fixture_path = durham_source.resolve_bundled_durham_asset_paths()

    assert config_path.name == "config.yaml"
    assert fixture_path.name == "sample_query_response.json"
    assert config_path.parent.name == "durham"
    assert fixture_path.parent.name == "fixtures"
    assert config_path.exists()
    assert fixture_path.exists()


def test_build_durham_source_url_is_reproducible_and_contains_pin() -> None:
    source_url = durham_source.build_durham_source_url("0821123456")

    assert source_url == durham_source.build_durham_source_url("0821123456")
    assert "PIN%20%3D%20%270821123456%27" in source_url
    assert "FeatureServer/0/query" in source_url


def test_build_durham_source_url_rejects_blank_pin() -> None:
    with pytest.raises(ValueError, match="PIN"):
        durham_source.build_durham_source_url("   ")


def test_normalize_durham_raw_record_coerces_identity_and_dates() -> None:
    normalized = durham_source.normalize_durham_raw_record(
        {
            "REID": " 012345 ",
            "PIN": 8212345601,
            "DEED_DATE": 1704067200000,
            "IS_PENDING": "Y",
        }
    )

    assert normalized["reid"] == "012345"
    assert normalized["pin"] == "8212345601"
    assert normalized["deed_date"] == date(2024, 1, 1)
    assert normalized["is_pending"] is True


def test_normalize_durham_raw_record_source_url_contains_pin_from_helper() -> None:
    normalized = durham_source.normalize_durham_raw_record(
        {
            "REID": "012345",
            "PIN": "0821123456",
        }
    )

    assert normalized["source_url"] == durham_source.build_durham_source_url("0821123456")
    assert "0821123456" in str(normalized["source_url"])


def test_normalize_durham_raw_record_coerces_numeric_assessment_fields() -> None:
    normalized = durham_source.normalize_durham_raw_record(
        {
            "REID": "1001",
            "PIN": "0821234567",
            "LAND_VALUE": "120,000.00",
            "IMPROVEMENT_VALUE": "250000",
            "TOTAL_VALUE": 370000,
            "ACREAGE": "0.45",
            "HEATED_AREA": "1890",
        }
    )

    assert normalized["land_assessed_value"] == Decimal("120000.00")
    assert normalized["improvement_assessed_value"] == Decimal("250000")
    assert normalized["total_assessed_value"] == Decimal("370000")
    assert normalized["acreage"] == Decimal("0.45")
    assert normalized["heated_area"] == 1890


@pytest.mark.parametrize(
    ("raw_pending", "expected"),
    [
        (True, True),
        (1, True),
        ("1", True),
        ("yes", True),
        ("N", False),
        (0, False),
        (None, False),
    ],
)
def test_normalize_durham_raw_record_handles_is_pending_flags(raw_pending: object, expected: bool) -> None:
    normalized = durham_source.normalize_durham_raw_record(
        {
            "REID": "1001",
            "PIN": "0821234567",
            "IS_PENDING": raw_pending,
        }
    )

    assert normalized["is_pending"] is expected


def test_load_durham_fixture_records_supports_explicit_path(tmp_path: Path) -> None:
    fixture_path = tmp_path / "sample_query_response.json"
    fixture_path.write_text('{"features":[{"attributes":{"REID":"1","PIN":"2"}}]}', encoding="utf-8")

    records = durham_source.load_durham_fixture_records(fixture_path)

    assert records == [{"REID": "1", "PIN": "2"}]
