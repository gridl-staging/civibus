from __future__ import annotations

from datetime import date
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from domains.campaign_finance.jurisdictions.config_schema import load_jurisdiction_config

_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.yaml"


@dataclass(frozen=True, slots=True)
class _GADataSourceBlock:
    name: str
    url: str
    transaction_types: tuple[str, ...]
    field_mapping_keys: tuple[str, ...]
    date_selectors: tuple[str, str] | None
    last_verified_working: date | None
    known_issues: tuple[str, ...]


@lru_cache(maxsize=1)
def _load_ga_data_source_blocks() -> tuple[_GADataSourceBlock, ...]:
    try:
        config = load_jurisdiction_config(_CONFIG_PATH)
    except ValueError as error:
        raise RuntimeError(f"Could not load GA scraper config from {_CONFIG_PATH}: {error}") from error

    return tuple(
        _GADataSourceBlock(
            name=data_source.name,
            url=data_source.url,
            transaction_types=tuple(data_source.coverage.transaction_types),
            field_mapping_keys=tuple(data_source.field_mappings.keys()),
            date_selectors=(
                data_source.date_start_selector,
                data_source.date_end_selector,
            )
            if data_source.date_start_selector and data_source.date_end_selector
            else None,
            last_verified_working=data_source.last_verified_working,
            known_issues=tuple(data_source.known_issues),
        )
        for data_source in config.data_sources
    )


def _find_ga_data_source_block(source_name: str) -> _GADataSourceBlock | None:
    for block in _load_ga_data_source_blocks():
        if block.name == source_name:
            return block
    return None


def _find_ga_data_source_block_by_transaction_type(transaction_type: str) -> _GADataSourceBlock | None:
    matching_blocks = [block for block in _load_ga_data_source_blocks() if transaction_type in block.transaction_types]
    if len(matching_blocks) > 1:
        raise RuntimeError(
            "GA config contains multiple data_sources with transaction type "
            f"{transaction_type!r}; could not pick a unique source"
        )
    if matching_blocks:
        return matching_blocks[0]
    return None


@lru_cache(maxsize=None)
def _load_columns(source_name: str) -> tuple[str, ...]:
    data_source_block = _find_ga_data_source_block(source_name)
    if data_source_block is not None and data_source_block.field_mapping_keys:
        return data_source_block.field_mapping_keys

    raise RuntimeError(f"Could not load GA columns from config.yaml for source {source_name!r}")


@lru_cache(maxsize=None)
def _load_columns_for_transaction_type(transaction_type: str) -> tuple[str, ...]:
    data_source_block = _find_ga_data_source_block_by_transaction_type(transaction_type)
    if data_source_block is not None and data_source_block.field_mapping_keys:
        return data_source_block.field_mapping_keys
    raise RuntimeError(f"Could not load GA columns from config.yaml for transaction type {transaction_type!r}")


@lru_cache(maxsize=None)
def _load_date_selectors_for_transaction_type(transaction_type: str) -> tuple[str, str]:
    data_source_block = _find_ga_data_source_block_by_transaction_type(transaction_type)
    if data_source_block is None:
        raise RuntimeError(
            f"Could not load GA date selectors from config.yaml for transaction type {transaction_type!r}"
        )
    if data_source_block.date_selectors is None:
        raise RuntimeError(
            "Could not load GA date selectors from config.yaml for transaction type "
            f"{transaction_type!r}: expected non-empty date_start_selector/date_end_selector"
        )
    return data_source_block.date_selectors


CONTRIBUTION_COLUMNS = _load_columns_for_transaction_type("contributions")
EXPENDITURE_COLUMNS = _load_columns_for_transaction_type("expenditures")

__all__ = [
    "CONTRIBUTION_COLUMNS",
    "EXPENDITURE_COLUMNS",
    "_find_ga_data_source_block",
    "_find_ga_data_source_block_by_transaction_type",
    "_load_date_selectors_for_transaction_type",
    "_load_ga_data_source_blocks",
]
