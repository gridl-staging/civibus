"""
Stub summary for /Users/stuart/parallel_development/civibus_dev/MAR18_cross_domain_er_and_property_graph/civibus_dev/domains/property/ingest/durham_source.py.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

import yaml

NormalizedDurhamRecord = dict[str, object]

_DURHAM_ASSET_DIR = Path(__file__).resolve().parents[1] / "jurisdictions" / "durham"
_DEFAULT_CONFIG_PATH = _DURHAM_ASSET_DIR / "config.yaml"

_TRUTHY_PENDING_VALUES = frozenset({"1", "Y", "YES", "TRUE", "T"})


def _escape_arcgis_where_literal(value: str) -> str:
    """Escape a string literal for ArcGIS/SQL where clauses."""
    return value.replace("'", "''")


def resolve_bundled_durham_asset_paths() -> tuple[Path, Path]:
    config = load_durham_config(_DEFAULT_CONFIG_PATH)
    fixture_relative_path = _required_nested_text(config, "fixture", "relative_path")
    fixture_path = (_DEFAULT_CONFIG_PATH.parent / fixture_relative_path).resolve()
    return _DEFAULT_CONFIG_PATH.resolve(), fixture_path


def load_durham_config(config_path: Path | None = None) -> dict[str, object]:
    path = (config_path or _DEFAULT_CONFIG_PATH).resolve()
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Durham config must be a mapping: {path}")

    _required_nested_text(payload, "jurisdiction", "slug")
    _required_nested_text(payload, "jurisdiction", "fips")
    _required_nested_text(payload, "source", "name")
    _required_nested_text(payload, "source", "arcgis_query_url")
    _required_nested_text(payload, "fixture", "relative_path")
    return payload


@lru_cache(maxsize=1)
def _load_default_durham_config() -> dict[str, object]:
    return load_durham_config(_DEFAULT_CONFIG_PATH)


def load_durham_fixture_records(fixture_path: Path | None = None) -> list[dict[str, object]]:
    if fixture_path is None:
        _, resolved_fixture_path = resolve_bundled_durham_asset_paths()
    else:
        resolved_fixture_path = fixture_path.resolve()

    payload = json.loads(resolved_fixture_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Durham fixture must deserialize to a mapping: {resolved_fixture_path}")

    raw_features = payload.get("features")
    if not isinstance(raw_features, list):
        raise ValueError(f"Durham fixture must contain a features array: {resolved_fixture_path}")

    records: list[dict[str, object]] = []
    for index, feature in enumerate(raw_features):
        if not isinstance(feature, Mapping):
            raise ValueError(f"Durham fixture feature[{index}] must be a mapping")
        attributes = feature.get("attributes")
        if not isinstance(attributes, Mapping):
            raise ValueError(f"Durham fixture feature[{index}] must include an attributes mapping")
        records.append(_json_compatible_dict(attributes))

    return records


def build_durham_source_url(pin: str, *, config: Mapping[str, object] | None = None) -> str:
    normalized_pin = _required_text(pin, field_name="PIN")
    config_payload = config if config is not None else _load_default_durham_config()
    query_url = _required_nested_text(config_payload, "source", "arcgis_query_url")
    # ArcGIS decodes the where clause before evaluating it, so quote characters
    # in the PIN must be escaped before URL encoding to avoid query injection.
    escaped_pin = _escape_arcgis_where_literal(normalized_pin)
    where_clause = quote(f"PIN = '{escaped_pin}'", safe="")
    return f"{query_url}?where={where_clause}&outFields=*&f=pjson"


def normalize_durham_raw_records(raw_records: Sequence[Mapping[str, object]]) -> list[NormalizedDurhamRecord]:
    return [normalize_durham_raw_record(raw_record) for raw_record in raw_records]


def normalize_durham_raw_record(raw_record: Mapping[str, object]) -> NormalizedDurhamRecord:
    raw_fields = _json_compatible_dict(raw_record)
    reid = _required_text(raw_fields.get("REID"), field_name="REID")
    pin = _required_text(raw_fields.get("PIN"), field_name="PIN")
    owner_name_as_filed = _optional_text(raw_fields.get("PROPERTY_OWNER"))
    owner_mail_fields = _normalized_owner_mail_fields(raw_fields)

    return {
        "reid": reid,
        "pin": pin,
        "source_url": build_durham_source_url(pin),
        "raw_record": raw_fields,
        "owner_record": _build_owner_record(owner_name_as_filed, owner_mail_fields),
        "site_address": _optional_text(raw_fields.get("LOCATION_ADDR")),
        "property_description": _optional_text(raw_fields.get("PROPERTY_DESCRIPTION")),
        "city": _optional_text(raw_fields.get("CITY")),
        "zoning_class": _optional_text(raw_fields.get("ZONING")),
        "land_class": _optional_text(raw_fields.get("LAND_CLASS")),
        "acreage": _optional_decimal(raw_fields.get("ACREAGE")),
        "neighborhood": _optional_text(raw_fields.get("NEIGHBORHOOD")),
        "fire_district": _optional_text(raw_fields.get("FIRE_DISTRICT")),
        "deed_date": _optional_date(raw_fields.get("DEED_DATE")),
        "deed_book": _optional_text(raw_fields.get("DEED_BOOK")),
        "deed_page": _optional_text(raw_fields.get("DEED_PAGE")),
        "tax_year": _optional_int(raw_fields.get("TAX_YEAR")),
        "land_assessed_value": _optional_decimal(raw_fields.get("LAND_VALUE")),
        "improvement_assessed_value": _optional_decimal(raw_fields.get("IMPROVEMENT_VALUE")),
        "total_assessed_value": _optional_decimal(raw_fields.get("TOTAL_VALUE")),
        "assessed_at": _optional_date(raw_fields.get("ASSESSED_AT")),
        "heated_area": _optional_int(raw_fields.get("HEATED_AREA")),
        "exemption_description": _optional_text(raw_fields.get("EXEMPTION_DESC")),
        "is_pending": _coerce_pending(raw_fields.get("IS_PENDING")),
        "owner_name_as_filed": owner_name_as_filed,
        **owner_mail_fields,
    }


def _normalized_owner_mail_fields(raw_fields: Mapping[str, object]) -> dict[str, str | None]:
    owner_mail_state = _optional_text(raw_fields.get("OWNER_MAIL_STATE"))
    return {
        "owner_mail_line1": _optional_text(raw_fields.get("OWNER_MAIL_1")),
        "owner_mail_line2": _optional_text(raw_fields.get("OWNER_MAIL_2")),
        "owner_mail_line3": _optional_text(raw_fields.get("OWNER_MAIL_3")),
        "owner_mail_city": _optional_text(raw_fields.get("OWNER_MAIL_CITY")),
        "owner_mail_state": owner_mail_state.upper() if owner_mail_state is not None else None,
        "owner_mail_zip5": _zip5_or_none(raw_fields.get("OWNER_MAIL_ZIP")),
    }


def _build_owner_record(
    owner_name_as_filed: str | None, owner_mail_fields: Mapping[str, str | None]
) -> dict[str, str | None]:
    return {
        "PROPERTY_OWNER": owner_name_as_filed,
        "OWNER_MAIL_1": owner_mail_fields["owner_mail_line1"],
        "OWNER_MAIL_2": owner_mail_fields["owner_mail_line2"],
        "OWNER_MAIL_3": owner_mail_fields["owner_mail_line3"],
        "OWNER_MAIL_CITY": owner_mail_fields["owner_mail_city"],
        "OWNER_MAIL_STATE": owner_mail_fields["owner_mail_state"],
        "OWNER_MAIL_ZIP": owner_mail_fields["owner_mail_zip5"],
    }


def _required_nested_text(payload: Mapping[str, object], *path: str) -> str:
    current: object = payload
    for key in path:
        if not isinstance(current, Mapping):
            joined = ".".join(path)
            raise ValueError(f"Expected mapping while reading Durham config path '{joined}'")
        current = current.get(key)
    return _required_text(current, field_name=".".join(path))


def _required_text(value: object, *, field_name: str) -> str:
    normalized = _optional_text(value)
    if normalized is None:
        raise ValueError(f"{field_name} must be present and non-empty")
    return normalized


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        return None
    return normalized


def _optional_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return Decimal(int(value))
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        normalized = stripped.replace(",", "").replace("$", "")
        try:
            return Decimal(normalized)
        except InvalidOperation as error:
            raise ValueError(f"Could not parse decimal value from {value!r}") from error

    raise ValueError(f"Unsupported numeric value type: {type(value).__name__}")


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, Decimal):
        return int(value)
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        return int(stripped.replace(",", ""))
    raise ValueError(f"Unsupported integer value type: {type(value).__name__}")


def _optional_date(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        if stripped.isdigit():
            return _epoch_millis_to_date(int(stripped))
        try:
            return date.fromisoformat(stripped[:10])
        except ValueError as error:
            raise ValueError(f"Unsupported date text value: {value!r}") from error
    if isinstance(value, (int, float, Decimal)):
        return _epoch_millis_to_date(int(value))

    raise ValueError(f"Unsupported date value type: {type(value).__name__}")


def _epoch_millis_to_date(value: int) -> date:
    if value == 0:
        return date(1970, 1, 1)
    timestamp_seconds = value / 1000 if abs(value) > 10_000_000_000 else value
    return datetime.fromtimestamp(timestamp_seconds, tz=timezone.utc).date()


def _zip5_or_none(value: object) -> str | None:
    text = _optional_text(value)
    if text is None:
        return None
    digits = "".join(char for char in text if char.isdigit())
    if len(digits) < 5:
        return None
    return digits[:5]


def _coerce_pending(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, Decimal)):
        return bool(int(value))
    normalized = _optional_text(value)
    if normalized is None:
        return False
    return normalized.upper() in _TRUTHY_PENDING_VALUES


def _json_compatible_dict(values: Mapping[str, object]) -> dict[str, object]:
    return {str(key): _json_compatible_value(value) for key, value in values.items()}


def _json_compatible_value(value: object) -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, list):
        return [_json_compatible_value(item) for item in value]
    if isinstance(value, Mapping):
        return _json_compatible_dict({str(key): nested for key, nested in value.items()})
    return str(value)
