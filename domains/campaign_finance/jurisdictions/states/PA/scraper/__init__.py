"""
Stub summary for mar21_02_tx_pa_state_pipelines/civibus_dev/domains/campaign_finance/jurisdictions/states/PA/scraper/__init__.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from domains.campaign_finance.jurisdictions.config_schema import JurisdictionConfig, load_jurisdiction_config

_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.yaml"
_YEARLY_BULK_DOWNLOAD_EXCEPTION_PREFIX = "yearly_bulk_download_url_exception:"


@dataclass(frozen=True, slots=True)
class _PADataSourceBlock:
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
def _load_pa_config() -> JurisdictionConfig:
    try:
        return load_jurisdiction_config(_CONFIG_PATH)
    except ValueError as error:
        raise RuntimeError(f"Could not load PA scraper config from {_CONFIG_PATH}: {error}") from error


@lru_cache(maxsize=1)
def _load_pa_data_source_blocks() -> tuple[_PADataSourceBlock, ...]:
    config = _load_pa_config()
    return tuple(
        _PADataSourceBlock(
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


def _load_data_source_for_data_type(data_type: str) -> _PADataSourceBlock:
    normalized_data_type = _normalize_data_type(data_type)

    for data_source in _load_pa_data_source_blocks():
        if normalized_data_type in data_source.transaction_types:
            return data_source

    raise ValueError(f"Unsupported PA data type: {data_type}")


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
        raise RuntimeError(f"No PA field mapping found for data type {data_type!r} and semantic path {semantic_path!r}")
    if len(matching_columns) > 1:
        raise RuntimeError(
            f"Multiple PA field mappings found for data type {data_type!r} and semantic path {semantic_path!r}"
        )

    return matching_columns[0]


def _parse_yearly_bulk_download_exception(known_issue: str) -> tuple[int, str] | None:
    if not known_issue.startswith(_YEARLY_BULK_DOWNLOAD_EXCEPTION_PREFIX):
        return None

    payload = known_issue.removeprefix(_YEARLY_BULK_DOWNLOAD_EXCEPTION_PREFIX)
    year_literal, separator, exception_url = payload.partition("=")

    if separator != "=" or not year_literal.isdigit() or not exception_url:
        raise RuntimeError(
            "Invalid PA yearly bulk URL exception format. "
            f"Expected '{_YEARLY_BULK_DOWNLOAD_EXCEPTION_PREFIX}<year>=<url>', got: {known_issue!r}"
        )

    return int(year_literal), exception_url


@lru_cache(maxsize=None)
def _load_bulk_download_url_for_data_type(data_type: str, year: int) -> str:
    data_source = _load_data_source_for_data_type(data_type)
    if data_source.bulk_download_url is None:
        raise RuntimeError(f"PA config missing bulk_download_url for data type {data_type!r}")

    for known_issue in data_source.known_issues:
        parsed_exception = _parse_yearly_bulk_download_exception(known_issue)
        if parsed_exception is None:
            continue

        exception_year, exception_url = parsed_exception
        if year == exception_year:
            return exception_url

    template = data_source.bulk_download_url
    if "{year}" not in template:
        raise RuntimeError(
            f"PA bulk_download_url for data type {data_type!r} must include '{{year}}' placeholder: {template!r}"
        )

    try:
        return template.format(year=year)
    except (IndexError, KeyError, ValueError) as error:
        raise RuntimeError(
            f"PA bulk_download_url for data type {data_type!r} is not a valid year template: {template!r}"
        ) from error
