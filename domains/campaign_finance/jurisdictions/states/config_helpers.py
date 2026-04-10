
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from domains.campaign_finance.jurisdictions.config_schema import JurisdictionConfig, load_jurisdiction_config


@dataclass(frozen=True, slots=True)
class DataSourceBlock:
    name: str
    url: str
    bulk_download_url: str | None
    api_base_url: str | None
    transaction_types: tuple[str, ...]
    field_mapping_keys: tuple[str, ...]
    field_mappings: tuple[tuple[str, str], ...]
    known_issues: tuple[str, ...]


def normalize_data_type(data_type: str) -> str:
    return data_type.strip().lower()


def load_state_config(config_path: Path, *, state_code: str) -> JurisdictionConfig:
    try:
        return load_jurisdiction_config(config_path)
    except ValueError as error:
        raise RuntimeError(f"Could not load {state_code} scraper config from {config_path}: {error}") from error


def build_data_source_blocks(config: JurisdictionConfig) -> tuple[DataSourceBlock, ...]:
    return tuple(
        DataSourceBlock(
            name=data_source.name,
            url=data_source.url,
            bulk_download_url=data_source.bulk_download_url,
            api_base_url=data_source.api_base_url,
            transaction_types=tuple(normalize_data_type(value) for value in data_source.coverage.transaction_types),
            field_mapping_keys=tuple(data_source.field_mappings.keys()),
            field_mappings=tuple(data_source.field_mappings.items()),
            known_issues=tuple(data_source.known_issues),
        )
        for data_source in config.data_sources
    )


def load_data_source_for_data_type(
    data_source_blocks: tuple[DataSourceBlock, ...],
    *,
    data_type: str,
    state_code: str,
) -> DataSourceBlock:
    normalized_data_type = normalize_data_type(data_type)

    for data_source in data_source_blocks:
        if normalized_data_type in data_source.transaction_types:
            return data_source

    raise ValueError(f"Unsupported {state_code} data type: {data_type}")


def load_supported_data_types(data_source_blocks: tuple[DataSourceBlock, ...]) -> tuple[str, ...]:
    return tuple(data_type for block in data_source_blocks for data_type in block.transaction_types)


def load_column_for_semantic_path(
    data_source_blocks: tuple[DataSourceBlock, ...],
    *,
    data_type: str,
    semantic_path: str,
    state_code: str,
) -> str:
    data_source = load_data_source_for_data_type(
        data_source_blocks,
        data_type=data_type,
        state_code=state_code,
    )
    matching_columns = [
        column_name for column_name, mapped_path in data_source.field_mappings if mapped_path == semantic_path
    ]

    if not matching_columns:
        raise RuntimeError(
            f"No {state_code} field mapping found for data type {data_type!r} and semantic path {semantic_path!r}"
        )
    if len(matching_columns) > 1:
        raise RuntimeError(
            f"Multiple {state_code} field mappings found for data type {data_type!r} and semantic path {semantic_path!r}"
        )

    return matching_columns[0]
