
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from domains.campaign_finance.jurisdictions.config_schema import JurisdictionConfig, load_jurisdiction_config

_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.yaml"
_TRANSACTIONS_DATA_TYPE = "transactions"


@dataclass(frozen=True, slots=True)
class _SFDataSourceBlock:
    name: str
    url: str
    bulk_download_url: str | None
    api_base_url: str | None
    transaction_types: tuple[str, ...]
    field_mapping_keys: tuple[str, ...]


def _normalize_data_type(data_type: str) -> str:
    normalized_data_type = data_type.strip().lower()
    return (
        _TRANSACTIONS_DATA_TYPE
        if normalized_data_type in {"contributions", "expenditures", "loans", "independent_expenditures"}
        else normalized_data_type
    )


@lru_cache(maxsize=1)
def _load_sf_config() -> JurisdictionConfig:
    try:
        return load_jurisdiction_config(_CONFIG_PATH)
    except ValueError as error:
        raise RuntimeError(f"Could not load SF scraper config from {_CONFIG_PATH}: {error}") from error


@lru_cache(maxsize=1)
def _load_sf_data_source_blocks() -> tuple[_SFDataSourceBlock, ...]:
    config = _load_sf_config()
    return tuple(
        _SFDataSourceBlock(
            name=data_source.name,
            url=data_source.url,
            bulk_download_url=data_source.bulk_download_url,
            api_base_url=data_source.api_base_url,
            transaction_types=tuple(
                {
                    _normalize_data_type(transaction_type)
                    for transaction_type in data_source.coverage.transaction_types + [_TRANSACTIONS_DATA_TYPE]
                }
            ),
            field_mapping_keys=tuple(data_source.field_mappings.keys()),
        )
        for data_source in config.data_sources
    )


def _load_data_source_for_data_type(data_type: str) -> _SFDataSourceBlock:
    normalized_data_type = _normalize_data_type(data_type)

    for data_source in _load_sf_data_source_blocks():
        if normalized_data_type in data_source.transaction_types:
            return data_source

    raise ValueError(f"Unsupported SF data type: {data_type}")


@lru_cache(maxsize=None)
def _load_columns_for_data_type(data_type: str) -> tuple[str, ...]:
    return _load_data_source_for_data_type(data_type).field_mapping_keys


@lru_cache(maxsize=None)
def _load_bulk_download_url_for_data_type(data_type: str) -> str:
    data_source = _load_data_source_for_data_type(data_type)
    if data_source.bulk_download_url is not None:
        return data_source.bulk_download_url
    raise RuntimeError(f"SF config missing bulk_download_url for data type {data_type!r}")
