
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from math import isfinite
from re import fullmatch
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def validate_optional_confidence(value: float | None, field_name: str) -> float | None:
    if value is None:
        return None

    if not isfinite(value) or value < 0 or value > 1:
        raise ValueError(f"{field_name} must be between 0 and 1")

    return value


def validate_optional_state_code(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None

    if fullmatch(r"[A-Z]{2}", value) is None:
        raise ValueError(f"{field_name} must be a two-letter uppercase state code")

    return value


def validate_optional_fixed_digit_string(
    value: str | None,
    expected_length: int,
    field_name: str,
) -> str | None:
    validated_value = validate_optional_digit_string(value, field_name=field_name)
    if validated_value is None:
        return None

    if len(validated_value) != expected_length:
        raise ValueError(f"{field_name} must be a {expected_length}-digit numeric string")

    return validated_value


def validate_optional_digit_string(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None

    if fullmatch(r"[0-9]+", value) is None:
        raise ValueError(f"{field_name} must contain only digits")

    return value


def validate_string_dictionary(value: object, field_name: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be a dictionary of string keys and values")

    validated_dictionary: dict[str, str] = {}
    for key, dictionary_value in value.items():
        if not isinstance(key, str) or not isinstance(dictionary_value, str):
            raise ValueError(f"{field_name} must be a dictionary of string keys and values")
        validated_dictionary[key] = dictionary_value

    return validated_dictionary


def validate_json_value(value: object, field_name: str) -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value

    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError(f"{field_name} must contain only finite JSON numbers")

        return value

    if isinstance(value, list):
        return [validate_json_value(item, field_name=f"{field_name}[{index}]") for index, item in enumerate(value)]

    if isinstance(value, dict):
        return validate_json_dictionary(value, field_name=field_name)

    raise ValueError(f"{field_name} contains unsupported JSON value type {type(value).__name__}")


def validate_json_dictionary(value: object, field_name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be a dictionary with JSON-compatible values")

    validated_dictionary: dict[str, object] = {}
    for key, dictionary_value in value.items():
        if not isinstance(key, str):
            raise ValueError(f"{field_name} must use string keys")

        validated_dictionary[key] = validate_json_value(dictionary_value, field_name=f"{field_name}.{key}")

    return validated_dictionary


def validate_temporal_range(start: date | None, end: date | None) -> None:
    """Validate that a half-open date range [start, end) is non-empty when both bounds are set."""
    if start is not None and end is not None and start >= end:
        raise ValueError("valid_start must be before valid_end")


DatePrecisionLiteral = Literal["day", "month", "quarter", "year", "approximate"]
RefreshPullStatus = Literal["crashed", "empty", "degraded", "success"]


class ValidDateRange(BaseModel):
    """Half-open date range representation: [start_date, end_date)."""

    model_config = ConfigDict(extra="forbid")

    start_date: date | None = None
    end_date: date | None = None

    @model_validator(mode="after")
    def _validate_non_empty_period(self) -> ValidDateRange:
        if self.start_date is not None and self.end_date is not None:
            if self.start_date >= self.end_date:
                raise ValueError("valid_period must be non-empty")
        return self


def compute_record_hash(raw_fields: dict[str, object]) -> str:
    validated_raw_fields = validate_json_dictionary(raw_fields, field_name="raw_fields")
    canonical_json = json.dumps(validated_raw_fields, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


class Person(BaseModel):

    id: UUID = Field(default_factory=uuid4)
    canonical_name: str
    name_variants: list[str] = Field(default_factory=list)
    first_name: str | None = None
    middle_name: str | None = None
    last_name: str | None = None
    suffix: str | None = None
    occupation: str | None = None
    education: str | None = None
    bio_text: str | None = None
    bio_source_url: str | None = None
    bio_license: PortraitRightsStatus | None = None
    bio_pulled_at: datetime | None = None
    date_of_birth: date | None = None
    year_of_birth: int | None = None
    identifiers: dict[str, str] = Field(default_factory=dict)
    primary_address_id: UUID | None = None
    er_cluster_id: UUID | None = None
    er_confidence: float | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("er_confidence")
    @classmethod
    def validate_er_confidence(cls, value: float | None) -> float | None:
        return validate_optional_confidence(value, field_name="er_confidence")

    @field_validator("identifiers", mode="before")
    @classmethod
    def validate_identifiers(cls, value: object) -> dict[str, str]:
        return validate_string_dictionary(value, field_name="identifiers")


class Organization(BaseModel):

    id: UUID = Field(default_factory=uuid4)
    canonical_name: str
    name_variants: list[str] = Field(default_factory=list)
    org_type: str | None = None
    identifiers: dict[str, str] = Field(default_factory=dict)
    registered_state: str | None = None
    formation_date: date | None = None
    dissolution_date: date | None = None
    primary_address_id: UUID | None = None
    er_cluster_id: UUID | None = None
    er_confidence: float | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("registered_state")
    @classmethod
    def validate_registered_state(cls, value: str | None) -> str | None:
        return validate_optional_state_code(value, field_name="registered_state")

    @field_validator("er_confidence")
    @classmethod
    def validate_er_confidence(cls, value: float | None) -> float | None:
        return validate_optional_confidence(value, field_name="er_confidence")

    @field_validator("identifiers", mode="before")
    @classmethod
    def validate_identifiers(cls, value: object) -> dict[str, str]:
        return validate_string_dictionary(value, field_name="identifiers")


class Address(BaseModel):

    id: UUID = Field(default_factory=uuid4)
    raw_address: str
    normalized_address: str | None = None
    street_number: str | None = None
    street_name: str | None = None
    unit: str | None = None
    city: str | None = None
    state: str | None = None
    zip5: str | None = None
    zip4: str | None = None
    county_fips: str | None = None
    geometry: tuple[float, float] | None = None
    geocode_confidence: float | None = None
    geocode_source: str | None = None
    geocoded_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("state")
    @classmethod
    def validate_state(cls, value: str | None) -> str | None:
        return validate_optional_state_code(value, field_name="state")

    @field_validator("zip5")
    @classmethod
    def validate_zip5(cls, value: str | None) -> str | None:
        return validate_optional_fixed_digit_string(value, expected_length=5, field_name="zip5")

    @field_validator("zip4")
    @classmethod
    def validate_zip4(cls, value: str | None) -> str | None:
        return validate_optional_fixed_digit_string(value, expected_length=4, field_name="zip4")

    @field_validator("county_fips")
    @classmethod
    def validate_county_fips(cls, value: str | None) -> str | None:
        return validate_optional_fixed_digit_string(value, expected_length=5, field_name="county_fips")

    @field_validator("geocode_confidence")
    @classmethod
    def validate_geocode_confidence(cls, value: float | None) -> float | None:
        return validate_optional_confidence(value, field_name="geocode_confidence")

    @field_validator("geometry")
    @classmethod
    def validate_geometry_is_none_for_stage_two(cls, value: tuple[float, float] | None) -> tuple[float, float] | None:
        if value is not None:
            raise ValueError("geometry must be None until geocoding is introduced")

        return value


class Jurisdiction(BaseModel):

    id: UUID = Field(default_factory=uuid4)
    name: str
    jurisdiction_type: Literal[
        "federal",
        "state",
        "county",
        "municipality",
        "school_district",
        "special_district",
    ]
    fips: str | None = None
    parent_id: UUID | None = None
    state: str | None = None
    geometry: None = None
    population: int | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("fips")
    @classmethod
    def validate_fips(cls, value: str | None) -> str | None:
        return validate_optional_digit_string(value, field_name="fips")

    @field_validator("state")
    @classmethod
    def validate_state(cls, value: str | None) -> str | None:
        return validate_optional_state_code(value, field_name="state")


class DataSource(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    domain: str
    jurisdiction: str | None = None
    name: str
    source_url: str
    source_format: str | None = None
    license: str | None = None
    update_frequency: str | None = None
    last_pull_at: datetime | None = None
    last_pull_status: str | None = None
    record_count: int | None = None
    notes: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class SourceRecord(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    data_source_id: UUID
    source_record_key: str | None = None
    source_url: str | None = None
    raw_fields: dict[str, object]
    pull_date: datetime
    record_hash: str | None = None
    superseded_by: UUID | None = None
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("raw_fields", mode="before")
    @classmethod
    def validate_raw_fields(cls, value: object) -> dict[str, object]:
        return validate_json_dictionary(value, field_name="raw_fields")


PortraitStatus = Literal[
    "active",
    "not_found",
    "too_small",
    "face_too_small",
    "takedown_requested",
    "superseded",
    "rejected",
]
PortraitRightsStatus = Literal["public_domain", "licensed", "restricted", "unknown"]


class PersonPortrait(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    person_id: UUID
    source_record_id: UUID
    status: PortraitStatus = "active"
    rights_status: PortraitRightsStatus = "unknown"
    image_hash: str
    dedup_key: str | None = None
    mime_type: str | None = None
    width_px: int | None = None
    height_px: int | None = None
    source_image_url: str | None = None
    storage_uri: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("image_hash")
    @classmethod
    def validate_image_hash(cls, value: str) -> str:
        normalized_hash = value.strip().lower()
        if fullmatch(r"[0-9a-f]{64}", normalized_hash) is None:
            raise ValueError("image_hash must be a lowercase 64-character hex SHA-256 string")
        return normalized_hash

    @field_validator("width_px", "height_px")
    @classmethod
    def validate_positive_dimensions(cls, value: int | None) -> int | None:
        if value is not None and value <= 0:
            raise ValueError("portrait dimensions must be positive when provided")
        return value

    @model_validator(mode="after")
    def ensure_dedup_key(self) -> PersonPortrait:
        if self.dedup_key is None:
            raw_key = self.image_hash
            self.dedup_key = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
        return self


class RefreshRun(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    job_key: str
    domain: str
    jurisdiction: str
    data_source_names: list[str] = Field(default_factory=list)
    pull_status: RefreshPullStatus
    started_at: datetime
    completed_at: datetime
    inserted_count: int = 0
    skipped_count: int = 0
    quarantined_count: int = 0
    superseded_count: int = 0
    error_count: int = 0
    metadata_updates: int = 0
    message: str
    error: str | None = None
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator(
        "inserted_count",
        "skipped_count",
        "quarantined_count",
        "superseded_count",
        "error_count",
        "metadata_updates",
    )
    @classmethod
    def validate_non_negative_counts(cls, value: int) -> int:
        if value < 0:
            raise ValueError("refresh-run counts must be non-negative")
        return value


CONTACT_POINT_OWNER_TYPES = Literal[
    "person",
    "organization",
    "office",
    "officeholding",
    "candidacy",
]


class ContactPoint(BaseModel):
    """Domain-agnostic communication primitive: email, phone, web URL, etc.

    Reusable across civic, corporate, nonprofit, and future domains.
    ADR 0008 classifies this as a core shared type (like Address).
    """

    id: UUID = Field(default_factory=uuid4)
    type: str
    value_raw: str
    value_normalized: str | None = None
    role: str | None = None
    owner_type: CONTACT_POINT_OWNER_TYPES
    owner_id: UUID
    source_record_id: UUID | None = None
    last_verified_at: datetime | None = None
    is_preferred: bool = False
    valid_period: ValidDateRange = Field(default_factory=ValidDateRange)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("value_raw")
    @classmethod
    def validate_value_raw_non_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("value_raw must be non-empty")
        return value
