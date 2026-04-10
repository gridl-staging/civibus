"""MA scraper config helpers — loads field mappings and data source metadata from config.yaml."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from domains.campaign_finance.jurisdictions.config_schema import JurisdictionConfig, load_jurisdiction_config

_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.yaml"


@dataclass(frozen=True, slots=True)
class _MADataSourceBlock:
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
def _load_ma_config() -> JurisdictionConfig:
    try:
        return load_jurisdiction_config(_CONFIG_PATH)
    except ValueError as error:
        raise RuntimeError(f"Could not load MA config from {_CONFIG_PATH}: {error}") from error


@lru_cache(maxsize=1)
def _load_ma_data_source_blocks() -> tuple[_MADataSourceBlock, ...]:
    config = _load_ma_config()
    return tuple(
        _MADataSourceBlock(
            name=ds.name,
            url=ds.url,
            bulk_download_url=ds.bulk_download_url,
            api_base_url=ds.api_base_url,
            transaction_types=tuple(_normalize_data_type(v) for v in ds.coverage.transaction_types),
            field_mapping_keys=tuple(ds.field_mappings.keys()),
            field_mappings=tuple(ds.field_mappings.items()),
        )
        for ds in config.data_sources
    )


def _load_data_source_for_data_type(data_type: str) -> _MADataSourceBlock:
    normalized = _normalize_data_type(data_type)
    for ds in _load_ma_data_source_blocks():
        if normalized in ds.transaction_types:
            return ds
    raise ValueError(f"Unsupported MA data type: {data_type}")


@lru_cache(maxsize=None)
def _load_columns_for_data_type(data_type: str) -> tuple[str, ...]:
    return _load_data_source_for_data_type(data_type).field_mapping_keys


@lru_cache(maxsize=None)
def _load_column_for_semantic_path(data_type: str, semantic_path: str) -> str:
    """Look up the column name for a semantic path."""
    ds = _load_data_source_for_data_type(data_type)
    matches = [col for col, path in ds.field_mappings if path == semantic_path]
    if not matches:
        raise RuntimeError(f"No MA field mapping for {data_type!r} / {semantic_path!r}")
    if len(matches) > 1:
        raise RuntimeError(f"Multiple MA field mappings for {data_type!r} / {semantic_path!r}")
    return matches[0]


def _load_bulk_download_url_template() -> str:
    """Return the URL template with {year} placeholder."""
    ds = _load_ma_data_source_blocks()[0]
    if ds.bulk_download_url is None:
        raise RuntimeError("MA config missing bulk_download_url")
    return ds.bulk_download_url


def _load_data_source_name() -> str:
    return _load_ma_data_source_blocks()[0].name


def _load_data_source_url() -> str:
    return _load_ma_data_source_blocks()[0].url
