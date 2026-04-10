"""Wisconsin campaign finance scraper config helpers."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from domains.campaign_finance.jurisdictions.config_schema import JurisdictionConfig, load_jurisdiction_config

_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.yaml"


@dataclass(frozen=True, slots=True)
class _WIDataSourceBlock:
    name: str
    url: str
    bulk_download_url: str | None
    api_base_url: str | None
    transaction_types: tuple[str, ...]
    field_mapping_keys: tuple[str, ...]
    field_mappings: tuple[tuple[str, str], ...]


def _normalize_data_type(data_type: str) -> str:
    return data_type.strip().lower()


@lru_cache(maxsize=1)
def _load_wi_config() -> JurisdictionConfig:
    try:
        return load_jurisdiction_config(_CONFIG_PATH)
    except ValueError as error:
        raise RuntimeError(f"Could not load WI scraper config from {_CONFIG_PATH}: {error}") from error


@lru_cache(maxsize=1)
def _load_wi_data_source_blocks() -> tuple[_WIDataSourceBlock, ...]:
    config = _load_wi_config()
    return tuple(
        _WIDataSourceBlock(
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


def _load_data_source_for_data_type(data_type: str) -> _WIDataSourceBlock:
    normalized_data_type = _normalize_data_type(data_type)

    for data_source in _load_wi_data_source_blocks():
        if normalized_data_type in data_source.transaction_types:
            return data_source

    raise ValueError(f"Unsupported WI data type: {data_type}")


@lru_cache(maxsize=None)
def _load_columns_for_data_type(data_type: str) -> tuple[str, ...]:
    data_source = _load_data_source_for_data_type(data_type)
    return data_source.field_mapping_keys


@lru_cache(maxsize=None)
def _load_column_for_semantic_path(data_type: str, semantic_path: str) -> str:
    data_source = _load_data_source_for_data_type(data_type)
    matching_columns = [
        column_name for column_name, mapped_path in data_source.field_mappings if mapped_path == semantic_path
    ]

    if not matching_columns:
        raise RuntimeError(f"No WI field mapping found for data type {data_type!r} and semantic path {semantic_path!r}")
    if len(matching_columns) > 1:
        raise RuntimeError(
            f"Multiple WI field mappings found for data type {data_type!r} and semantic path {semantic_path!r}"
        )

    return matching_columns[0]


def _load_bulk_download_url_for_data_type(data_type: str) -> str:
    data_source = _load_data_source_for_data_type(data_type)
    if data_source.bulk_download_url is None:
        raise RuntimeError(f"WI config missing bulk_download_url for data type {data_type!r}")
    return data_source.bulk_download_url


def _load_data_source_name_for_data_type(data_type: str) -> str:
    return _load_data_source_for_data_type(data_type).name


def _load_data_source_url_for_data_type(data_type: str) -> str:
    return _load_data_source_for_data_type(data_type).url
