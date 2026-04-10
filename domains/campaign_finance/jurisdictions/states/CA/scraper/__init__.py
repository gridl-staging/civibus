from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from domains.campaign_finance.jurisdictions.config_schema import load_jurisdiction_config

_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.yaml"

_RAW_DATA_SOURCE_NAME = "CAL-ACCESS Raw Data Export"


@dataclass(frozen=True, slots=True)
class _CADataSourceBlock:
    name: str
    url: str
    bulk_download_url: str | None
    transaction_types: tuple[str, ...]
    field_mapping_keys: tuple[str, ...]
    field_mappings: tuple[tuple[str, str], ...]


@lru_cache(maxsize=1)
def _load_ca_config():
    """Load and cache the CA jurisdiction config via Pydantic."""
    try:
        return load_jurisdiction_config(_CONFIG_PATH)
    except ValueError as error:
        raise RuntimeError(f"Could not load CA scraper config from {_CONFIG_PATH}: {error}") from error


@lru_cache(maxsize=1)
def _load_ca_data_source_blocks() -> tuple[_CADataSourceBlock, ...]:
    config = _load_ca_config()
    return tuple(
        _CADataSourceBlock(
            name=ds.name,
            url=ds.url,
            bulk_download_url=ds.bulk_download_url,
            transaction_types=tuple(ds.coverage.transaction_types),
            field_mapping_keys=tuple(ds.field_mappings.keys()),
            field_mappings=tuple(ds.field_mappings.items()),
        )
        for ds in config.data_sources
    )


def _find_ca_data_source_block(source_name: str) -> _CADataSourceBlock | None:
    for block in _load_ca_data_source_blocks():
        if block.name == source_name:
            return block
    return None


def _get_raw_data_source() -> _CADataSourceBlock:
    block = _find_ca_data_source_block(_RAW_DATA_SOURCE_NAME)
    if block is None:
        raise RuntimeError(f"CA config missing required data source: {_RAW_DATA_SOURCE_NAME!r}")
    return block


@lru_cache(maxsize=1)
def _load_ingestion_table_names() -> tuple[str, ...]:
    """Derive the locked Stage 2 table set from config field mapping prefixes."""
    raw_source = _get_raw_data_source()
    table_names: dict[str, None] = {}
    for field_mapping_key in raw_source.field_mapping_keys:
        if "." not in field_mapping_key:
            raise RuntimeError(f"Invalid CA field mapping key {field_mapping_key!r}; expected TABLE.COLUMN format")
        table_name, _ = field_mapping_key.split(".", maxsplit=1)
        table_names.setdefault(table_name, None)

    if not table_names:
        raise RuntimeError("CA raw data source has no field mappings to derive ingestion tables")
    return tuple(table_names.keys())


# Locked Stage 2 ingestion tables and members derived from config.yaml (single source of truth)
INGESTION_TABLE_NAMES: tuple[str, ...] = _load_ingestion_table_names()
INGESTION_MEMBERS: tuple[str, ...] = tuple(f"CalAccess/DATA/{table_name}.TSV" for table_name in INGESTION_TABLE_NAMES)


@lru_cache(maxsize=None)
def _load_columns_for_table(table_name: str) -> tuple[str, ...]:
    """Return the ordered field mapping keys for a specific CA table.

    Field mappings in config.yaml use the format TABLE_NAME.COLUMN_NAME.
    This extracts only columns belonging to the given table.
    """
    raw_source = _get_raw_data_source()
    prefix = f"{table_name}."
    columns = tuple(key.removeprefix(prefix) for key in raw_source.field_mapping_keys if key.startswith(prefix))
    if not columns:
        raise RuntimeError(f"No field mappings found for CA table {table_name!r} in config.yaml")
    return columns


@lru_cache(maxsize=None)
def _load_column_for_semantic_path(table_name: str, semantic_path: str) -> str:
    """Resolve a CA table column name by semantic path from config.yaml."""
    raw_source = _get_raw_data_source()
    prefix = f"{table_name}."
    matching_columns = [
        mapping_key.removeprefix(prefix)
        for mapping_key, mapped_semantic_path in raw_source.field_mappings
        if mapping_key.startswith(prefix) and mapped_semantic_path == semantic_path
    ]
    if not matching_columns:
        raise RuntimeError(f"No CA field mapping found for table {table_name!r} and semantic path {semantic_path!r}")
    if len(matching_columns) > 1:
        raise RuntimeError(
            "Multiple CA field mappings found for table "
            f"{table_name!r} and semantic path {semantic_path!r}: {matching_columns!r}"
        )
    return matching_columns[0]
