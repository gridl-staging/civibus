"""OR scraper config helpers."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from domains.campaign_finance.jurisdictions.config_schema import JurisdictionConfig
from domains.campaign_finance.jurisdictions.states.config_helpers import (
    DataSourceBlock,
    build_data_source_blocks,
    load_column_for_semantic_path,
    load_data_source_for_data_type,
    load_state_config,
    load_supported_data_types as load_block_supported_data_types,
)

_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.yaml"


@lru_cache(maxsize=1)
def _load_or_config() -> JurisdictionConfig:
    return load_state_config(_CONFIG_PATH, state_code="OR")


@lru_cache(maxsize=1)
def _load_or_data_source_blocks() -> tuple[DataSourceBlock, ...]:
    return build_data_source_blocks(_load_or_config())


def _load_data_source_for_data_type(data_type: str) -> DataSourceBlock:
    return load_data_source_for_data_type(
        _load_or_data_source_blocks(),
        data_type=data_type,
        state_code="OR",
    )


@lru_cache(maxsize=None)
def _load_columns_for_data_type(data_type: str) -> tuple[str, ...]:
    return _load_data_source_for_data_type(data_type).field_mapping_keys


@lru_cache(maxsize=1)
def load_supported_data_types() -> tuple[str, ...]:
    return load_block_supported_data_types(_load_or_data_source_blocks())


@lru_cache(maxsize=None)
def _load_column_for_semantic_path(data_type: str, semantic_path: str) -> str:
    return load_column_for_semantic_path(
        _load_or_data_source_blocks(),
        data_type=data_type,
        semantic_path=semantic_path,
        state_code="OR",
    )


@lru_cache(maxsize=None)
def _load_api_base_url_for_data_type(data_type: str) -> str:
    data_source = _load_data_source_for_data_type(data_type)
    if data_source.api_base_url is None:
        raise RuntimeError(f"OR config missing api_base_url for data type {data_type!r}")
    return data_source.api_base_url


@lru_cache(maxsize=None)
def _load_data_source_name_for_data_type(data_type: str) -> str:
    return _load_data_source_for_data_type(data_type).name


@lru_cache(maxsize=None)
def _load_data_source_url_for_data_type(data_type: str) -> str:
    return _load_data_source_for_data_type(data_type).url
