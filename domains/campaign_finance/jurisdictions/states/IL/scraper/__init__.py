"""Illinois campaign finance scraper config helpers."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from domains.campaign_finance.jurisdictions.config_schema import JurisdictionConfig, load_jurisdiction_config

_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.yaml"


@dataclass(frozen=True, slots=True)
class _ILDataSourceBlock:
    name: str
    url: str
    bulk_download_url: str | None
    api_base_url: str | None
    transaction_types: tuple[str, ...]
    field_mapping_keys: tuple[str, ...]
    field_mappings: tuple[tuple[str, str], ...]
    known_issues: tuple[str, ...]


def _normalize_data_type(data_type: str) -> str:
    return data_type.strip().lower()


@lru_cache(maxsize=1)
def _load_il_config() -> JurisdictionConfig:
    try:
        return load_jurisdiction_config(_CONFIG_PATH)
    except ValueError as error:
        raise RuntimeError(f"Could not load IL scraper config from {_CONFIG_PATH}: {error}") from error


@lru_cache(maxsize=1)
def _load_il_data_source_blocks() -> tuple[_ILDataSourceBlock, ...]:
    config = _load_il_config()
    return tuple(
        _ILDataSourceBlock(
            name=data_source.name,
            url=data_source.url,
            bulk_download_url=data_source.bulk_download_url,
            api_base_url=data_source.api_base_url,
            transaction_types=tuple(_normalize_data_type(value) for value in data_source.coverage.transaction_types),
            field_mapping_keys=tuple(data_source.field_mappings.keys()),
            field_mappings=tuple(data_source.field_mappings.items()),
            known_issues=tuple(data_source.known_issues),
        )
        for data_source in config.data_sources
    )


def _load_data_source_for_data_type(data_type: str) -> _ILDataSourceBlock:
    normalized_data_type = _normalize_data_type(data_type)
    matching_data_source = next(
        (
            data_source
            for data_source in _load_il_data_source_blocks()
            if normalized_data_type in data_source.transaction_types
        ),
        None,
    )
    if matching_data_source is None:
        raise ValueError(f"Unsupported IL data type: {data_type}")
    return matching_data_source


@lru_cache(maxsize=None)
def _load_columns_for_data_type(data_type: str) -> tuple[str, ...]:
    return _load_data_source_for_data_type(data_type).field_mapping_keys


@lru_cache(maxsize=None)
def _load_semantic_path_to_column_map(data_type: str) -> dict[str, str]:
    data_source = _load_data_source_for_data_type(data_type)
    semantic_path_to_column: dict[str, str] = {}

    for column_name, mapped_path in data_source.field_mappings:
        if mapped_path in semantic_path_to_column:
            raise RuntimeError(
                f"Multiple IL field mappings found for data type {data_type!r} and semantic path {mapped_path!r}"
            )
        semantic_path_to_column[mapped_path] = column_name

    return semantic_path_to_column


@lru_cache(maxsize=None)
def _load_column_for_semantic_path(data_type: str, semantic_path: str) -> str:
    semantic_path_to_column = _load_semantic_path_to_column_map(data_type)
    column_name = semantic_path_to_column.get(semantic_path)
    if column_name is None:
        raise RuntimeError(f"No IL field mapping found for data type {data_type!r} and semantic path {semantic_path!r}")
    return column_name


def _load_bulk_download_url_for_data_type(data_type: str) -> str:
    data_source = _load_data_source_for_data_type(data_type)
    if data_source.bulk_download_url is None:
        raise RuntimeError(f"IL config missing bulk_download_url for data type {data_type!r}")
    return data_source.bulk_download_url


def _load_data_source_name_for_data_type(data_type: str) -> str:
    return _load_data_source_for_data_type(data_type).name


def _load_data_source_url_for_data_type(data_type: str) -> str:
    return _load_data_source_for_data_type(data_type).url
