"""Campaign-finance jurisdiction refresh job construction helpers."""

from __future__ import annotations

from collections.abc import Callable
from functools import partial

from core.refresh.runner import RefreshJob
from domains.campaign_finance.jurisdictions.config_schema import JurisdictionConfig


def _data_source_identity(data_source: object) -> tuple[str, str]:
    return data_source.name, data_source.update_frequency


def _find_data_source_for_transaction_type(
    config: JurisdictionConfig,
    *,
    transaction_type: str,
) -> tuple[str, str] | None:
    matching_sources = [
        _data_source_identity(data_source)
        for data_source in config.data_sources
        if transaction_type in data_source.coverage.transaction_types
    ]
    if not matching_sources:
        return None
    if len(matching_sources) > 1:
        raise RuntimeError(
            "Refresh runner expected one data source for "
            f"{config.jurisdiction.code} transaction type {transaction_type!r}, "
            f"found {len(matching_sources)}"
        )
    return matching_sources[0]


def _find_data_source_by_name(config: JurisdictionConfig, *, source_name: str) -> tuple[str, str] | None:
    matching_sources = [
        _data_source_identity(data_source) for data_source in config.data_sources if data_source.name == source_name
    ]
    if not matching_sources:
        return None
    if len(matching_sources) > 1:
        raise RuntimeError(
            "Refresh runner expected one data source for "
            f"{config.jurisdiction.code} source name {source_name!r}, found {len(matching_sources)}"
        )
    return matching_sources[0]


def _build_refresh_job(
    *,
    key: str,
    jurisdiction: str,
    source_name: str,
    cadence: str,
    run_callable: Callable[[], object],
) -> RefreshJob:
    return RefreshJob(
        key=key,
        domain="campaign_finance",
        jurisdiction=jurisdiction,
        cadence=cadence,
        data_source_names=(source_name,),
        run_callable=run_callable,
    )


def _optional_job_list(job: RefreshJob | None) -> list[RefreshJob]:
    return [] if job is None else [job]


def _build_job_for_source(
    *,
    key: str,
    jurisdiction: str,
    source: tuple[str, str] | None,
    run_callable: Callable[[], object],
) -> RefreshJob | None:
    if source is None:
        return None

    source_name, cadence = source
    return _build_refresh_job(
        key=key,
        jurisdiction=jurisdiction,
        source_name=source_name,
        cadence=cadence,
        run_callable=run_callable,
    )


def _build_transaction_jobs(
    config: JurisdictionConfig,
    *,
    jurisdiction: str,
    key_prefix: str,
    data_types: tuple[str, ...],
    build_run_callable: Callable[[str], Callable[[], object]],
) -> list[RefreshJob]:
    jobs: list[RefreshJob] = []
    for data_type in data_types:
        job = _build_job_for_source(
            key=f"{key_prefix}-{data_type}",
            jurisdiction=jurisdiction,
            source=_find_data_source_for_transaction_type(config, transaction_type=data_type),
            run_callable=build_run_callable(data_type),
        )
        if job is not None:
            jobs.append(job)
    return jobs


def _download_refresh_callable(
    refresh_callable: Callable[..., object],
    *,
    data_type: str,
    **refresh_kwargs: object,
) -> Callable[[], object]:
    return partial(refresh_callable, data_type=data_type, download=True, **refresh_kwargs)


def _build_download_transaction_jobs(
    config: JurisdictionConfig,
    *,
    jurisdiction: str,
    key_prefix: str,
    data_types: tuple[str, ...],
    refresh_callable: Callable[..., object],
    **refresh_kwargs: object,
) -> list[RefreshJob]:
    return _build_transaction_jobs(
        config,
        jurisdiction=jurisdiction,
        key_prefix=key_prefix,
        data_types=data_types,
        build_run_callable=lambda data_type: _download_refresh_callable(
            refresh_callable,
            data_type=data_type,
            **refresh_kwargs,
        ),
    )


def _build_download_jobs_for_state(
    config: JurisdictionConfig,
    *,
    jurisdiction: str,
    state_code: str,
    data_types: tuple[str, ...],
    refresh_callable: Callable[..., object],
    **refresh_kwargs: object,
) -> list[RefreshJob]:
    return _build_download_transaction_jobs(
        config,
        jurisdiction=jurisdiction,
        key_prefix=f"state-{state_code.lower()}",
        data_types=data_types,
        refresh_callable=refresh_callable,
        **refresh_kwargs,
    )
