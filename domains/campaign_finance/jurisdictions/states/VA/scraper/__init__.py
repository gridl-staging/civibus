"""Virginia campaign finance scraper config helpers.

Loads config.yaml and provides typed accessors for data source blocks,
field mappings, and bulk download URLs. All config access is cached.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from domains.campaign_finance.jurisdictions.config_schema import JurisdictionConfig, load_jurisdiction_config

# config.yaml lives one level above this scraper/ package
_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.yaml"


@dataclass(frozen=True, slots=True)
class _VADataSourceBlock:
    """Frozen snapshot of a single VA data source from config.yaml."""

    name: str
    url: str
    bulk_download_url: str | None
    api_base_url: str | None
    transaction_types: tuple[str, ...]
    field_mapping_keys: tuple[str, ...]
    field_mappings: tuple[tuple[str, str], ...]


def _normalize_data_type(data_type: str) -> str:
    """Lowercase and strip whitespace for consistent lookups."""
    return data_type.strip().lower()


@lru_cache(maxsize=1)
def _load_va_config() -> JurisdictionConfig:
    """Load and cache the VA jurisdiction config from disk."""
    try:
        return load_jurisdiction_config(_CONFIG_PATH)
    except ValueError as error:
        raise RuntimeError(f"Could not load VA scraper config from {_CONFIG_PATH}: {error}") from error


@lru_cache(maxsize=1)
def _load_va_data_source_blocks() -> tuple[_VADataSourceBlock, ...]:
    """Build frozen data source block objects from config.yaml."""
    config = _load_va_config()
    return tuple(
        _VADataSourceBlock(
            name=data_source.name,
            url=data_source.url,
            bulk_download_url=data_source.bulk_download_url,
            api_base_url=data_source.api_base_url,
            transaction_types=tuple(_normalize_data_type(value) for value in data_source.coverage.transaction_types),
            field_mapping_keys=tuple(data_source.field_mappings.keys()),
            field_mappings=tuple(data_source.field_mappings.items()),
        )
        for data_source in config.data_sources
    )


def _load_data_source_for_data_type(data_type: str) -> _VADataSourceBlock:
    """Find the data source block whose transaction_types include the given data_type."""
    normalized_data_type = _normalize_data_type(data_type)

    for data_source in _load_va_data_source_blocks():
        if normalized_data_type in data_source.transaction_types:
            return data_source

    raise ValueError(f"Unsupported VA data type: {data_type}")


@lru_cache(maxsize=None)
def _load_columns_for_data_type(data_type: str) -> tuple[str, ...]:
    """Return the ordered CSV column names for a given data type."""
    data_source = _load_data_source_for_data_type(data_type)
    return data_source.field_mapping_keys


@lru_cache(maxsize=None)
def _load_column_for_semantic_path(data_type: str, semantic_path: str) -> str:
    """Find the CSV column name that maps to a given semantic path.

    Raises RuntimeError if zero or multiple columns match.
    """
    data_source = _load_data_source_for_data_type(data_type)
    matching_columns = [
        column_name for column_name, mapped_path in data_source.field_mappings if mapped_path == semantic_path
    ]

    if not matching_columns:
        raise RuntimeError(f"No VA field mapping found for data type {data_type!r} and semantic path {semantic_path!r}")
    if len(matching_columns) > 1:
        raise RuntimeError(
            f"Multiple VA field mappings found for data type {data_type!r} and semantic path {semantic_path!r}"
        )

    return matching_columns[0]


def _load_bulk_download_url_for_data_type(data_type: str) -> str:
    """Return the bulk download URL template for the given data type.

    The returned URL contains a {year_month} placeholder that must be
    formatted by the caller (e.g. '2026_03').
    """
    data_source = _load_data_source_for_data_type(data_type)
    if data_source.bulk_download_url is None:
        raise RuntimeError(f"VA config missing bulk_download_url for data type {data_type!r}")
    return data_source.bulk_download_url


def _load_data_source_name_for_data_type(data_type: str) -> str:
    """Return the human-readable name from config for a given data type."""
    return _load_data_source_for_data_type(data_type).name


def _load_data_source_url_for_data_type(data_type: str) -> str:
    """Return the portal URL from config for a given data type."""
    return _load_data_source_for_data_type(data_type).url
