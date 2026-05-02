"""Derive coverage registry rows from jurisdiction configs and merge into the canonical registry."""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable

from core.refresh.runner import _CADENCE_INTERVALS, _SUPPORTED_STATE_CODES
from domains.campaign_finance.jurisdictions.config_schema import (
    JurisdictionConfig,
    discover_jurisdiction_configs,
    load_jurisdiction_config,
)

from .registry import DEFAULT_REGISTRY_PATH, CoverageRegistry, CoverageRegistryRow, load_registry, write_registry

_DEFAULT_JURISDICTIONS_ROOT = Path(__file__).resolve().parents[1] / "jurisdictions"
_PRESERVED_REGISTRY_FIELDS = (
    "tier",
    "best_update_frequency",
    "evidence_summary",
    "operational_reason",
    "next_action",
    "evidence_date",
    "ie_coverage_available",
)


def _best_update_frequency(config: JurisdictionConfig) -> str:
    def cadence_interval(cadence: str) -> timedelta:
        return _CADENCE_INTERVALS[cadence]

    cadences = [source.update_frequency for source in config.data_sources]
    return min(cadences, key=cadence_interval)


def _best_last_verified_working(config: JurisdictionConfig) -> date | None:
    last_verified_dates = [
        source.last_verified_working for source in config.data_sources if source.last_verified_working
    ]
    if not last_verified_dates:
        return None
    return max(last_verified_dates)


def _derive_state_registry_row(
    config: JurisdictionConfig,
    *,
    runner_supported_state_codes: set[str],
) -> CoverageRegistryRow:
    """Build a single registry row from a state jurisdiction config."""
    source_names = [source.name for source in config.data_sources]
    return CoverageRegistryRow(
        jurisdiction_code=config.jurisdiction.code,
        name=config.jurisdiction.name,
        jurisdiction_type=config.jurisdiction.type,
        best_update_frequency=_best_update_frequency(config),
        best_last_verified_working=_best_last_verified_working(config),
        covers_sub_jurisdictions=any(source.coverage.covers_sub_jurisdictions for source in config.data_sources),
        source_count=len(source_names),
        source_names=source_names,
        runner_wired=config.jurisdiction.code in runner_supported_state_codes,
        tier=None,
        evidence_summary=None,
        operational_reason=None,
        next_action=None,
        evidence_date=None,
    )


def derive_state_registry_rows(
    jurisdictions_root: Path | None = None,
    *,
    supported_state_codes: Iterable[str] = _SUPPORTED_STATE_CODES,
) -> list[CoverageRegistryRow]:
    """Discover all state configs and return sorted registry rows."""
    resolved_root = jurisdictions_root or _DEFAULT_JURISDICTIONS_ROOT
    runner_supported_state_codes = set(supported_state_codes)

    rows: list[CoverageRegistryRow] = []
    for config_path in discover_jurisdiction_configs(resolved_root):
        config = load_jurisdiction_config(config_path)
        if config.jurisdiction.type != "state":
            continue
        rows.append(
            _derive_state_registry_row(
                config,
                runner_supported_state_codes=runner_supported_state_codes,
            )
        )

    return sorted(rows, key=lambda row: row.jurisdiction_code)


def build_fec_registry_row() -> CoverageRegistryRow:
    """Return the hard-coded FEC federal registry row."""
    return CoverageRegistryRow(
        jurisdiction_code="FEC",
        name="Federal Election Commission",
        jurisdiction_type="federal",
        best_update_frequency="continuous",
        best_last_verified_working=None,
        covers_sub_jurisdictions=False,
        source_count=3,
        source_names=["FEC Schedule A API", "FEC Bulk Data", "FEC Schedule E/IE"],
        runner_wired=True,
        tier=None,
        evidence_summary=None,
        operational_reason=None,
        next_action=None,
        evidence_date=None,
    )


def build_seed_registry() -> CoverageRegistry:
    state_rows = derive_state_registry_rows()
    return CoverageRegistry(rows=[build_fec_registry_row(), *state_rows])


def _merge_seeded_row(existing_row: CoverageRegistryRow, seeded_row: CoverageRegistryRow) -> CoverageRegistryRow:
    if existing_row.jurisdiction_type != seeded_row.jurisdiction_type:
        return seeded_row

    return seeded_row.model_copy(
        update={field_name: getattr(existing_row, field_name) for field_name in _PRESERVED_REGISTRY_FIELDS}
    )


def merge_seed_registry(
    existing_registry: CoverageRegistry,
    seeded_registry: CoverageRegistry,
) -> CoverageRegistry:
    """Merge seeded rows into an existing registry, preserving curated tier/evidence fields."""
    seeded_rows_by_code = {row.jurisdiction_code: row for row in seeded_registry.rows}
    merged_rows: list[CoverageRegistryRow] = []

    for existing_row in existing_registry.rows:
        seeded_row = seeded_rows_by_code.pop(existing_row.jurisdiction_code, None)
        if seeded_row is None:
            merged_rows.append(existing_row)
            continue
        merged_rows.append(_merge_seeded_row(existing_row, seeded_row))

    for jurisdiction_code in sorted(seeded_rows_by_code):
        merged_rows.append(seeded_rows_by_code[jurisdiction_code])

    return CoverageRegistry(rows=merged_rows)


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Seed campaign-finance coverage registry from configs and runner wiring"
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=DEFAULT_REGISTRY_PATH,
        help="Output path for coverage registry JSON",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_argument_parser().parse_args(argv)
    try:
        seeded_registry = build_seed_registry()
        if args.path.exists():
            registry = merge_seed_registry(load_registry(args.path), seeded_registry)
        else:
            registry = seeded_registry
        output_path = write_registry(args.path, registry)
    except (OSError, ValueError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    print(f"Wrote coverage registry: {output_path} (rows={len(registry.rows)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
