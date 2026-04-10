"""Validate coverage registry JSON against the schema and cross-layer linkage rules."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .registry import (
    DEFAULT_REGISTRY_PATH,
    CoverageRegistry,
    CoverageRegistryRow,
    collect_duplicate_jurisdiction_codes,
    format_validation_errors,
    load_registry_json,
)


@dataclass(frozen=True)
class _RowValidationResult:
    index: int
    row: CoverageRegistryRow | None
    error: str | None


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate campaign-finance coverage registry")
    parser.add_argument(
        "--path",
        type=Path,
        default=DEFAULT_REGISTRY_PATH,
        help="Path to the coverage registry JSON file",
    )
    return parser


def _load_raw_payload(path: Path) -> dict[str, Any]:
    resolved_path = path.resolve()
    raw_payload = load_registry_json(resolved_path)
    if not isinstance(raw_payload, dict):
        raise ValueError(f"Registry JSON root must be an object: {resolved_path}")
    return raw_payload


def _extract_rows(raw_payload: dict[str, Any]) -> list[Any]:
    if "rows" not in raw_payload:
        raise ValueError("Registry JSON must include required key 'rows'")

    rows = raw_payload["rows"]
    if not isinstance(rows, list):
        raise ValueError("Registry JSON key 'rows' must contain a list")

    return rows


def _validate_rows(raw_rows: list[Any]) -> list[_RowValidationResult]:
    results: list[_RowValidationResult] = []
    for index, raw_row in enumerate(raw_rows):
        try:
            row = CoverageRegistryRow.model_validate(raw_row)
            results.append(_RowValidationResult(index=index, row=row, error=None))
        except ValidationError as error:
            results.append(_RowValidationResult(index=index, row=None, error=format_validation_errors(error)))
    return results


def _loaded_rows(results: list[_RowValidationResult]) -> list[CoverageRegistryRow]:
    return [result.row for result in results if result.row is not None]


def _validate_cross_layer_linkage(rows: list[CoverageRegistryRow]) -> list[str]:
    """Check municipality parent references exist and decision fields are consistent."""
    errors: list[str] = []
    code_to_row = {row.jurisdiction_code: row for row in rows}

    for row in rows:
        if row.parent_jurisdiction_code is None:
            continue

        # Parent must exist in the registry
        parent = code_to_row.get(row.parent_jurisdiction_code)
        if parent is None:
            errors.append(
                f"row '{row.jurisdiction_code}': orphan parent_jurisdiction_code "
                f"'{row.parent_jurisdiction_code}' not found in registry"
            )
            continue

        # covered_by_parent requires parent covers_sub_jurisdictions=true
        if row.municipal_audit_decision == "covered_by_parent" and not parent.covers_sub_jurisdictions:
            errors.append(
                f"row '{row.jurisdiction_code}': municipal_audit_decision is "
                f"'covered_by_parent' but parent '{parent.jurisdiction_code}' "
                f"has covers_sub_jurisdictions=false"
            )

    return errors


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: validate registry JSON and print per-row results."""
    args = _build_argument_parser().parse_args(argv)

    failed = 0
    warnings = 0
    try:
        raw_payload = _load_raw_payload(args.path)
        row_payloads = _extract_rows(raw_payload)
    except ValueError as error:
        print(f"FAIL: {error}")
        print("Validation summary: checked=0 passed=0 failed=1 warnings=0")
        return 1

    unknown_top_level_fields = sorted(set(raw_payload.keys()) - {"rows"})
    if unknown_top_level_fields:
        failed += 1
        joined_unknown_fields = ", ".join(unknown_top_level_fields)
        print(f"FAIL: Unknown top-level registry field(s): {joined_unknown_fields}")

    validation_results = _validate_rows(row_payloads)
    for result in validation_results:
        if result.row is None:
            failed += 1
            print(f"FAIL: row[{result.index}] -> {result.error}")
            continue
        print(f"PASS: row[{result.index}] jurisdiction_code={result.row.jurisdiction_code}")

    valid_rows = _loaded_rows(validation_results)

    duplicate_codes = collect_duplicate_jurisdiction_codes(valid_rows)
    for jurisdiction_code, row_indexes in sorted(duplicate_codes.items()):
        failed += 1
        joined_indexes = ", ".join(str(index) for index in row_indexes)
        print(f"FAIL: Duplicate jurisdiction code '{jurisdiction_code}' found at rows [{joined_indexes}]")

    # Cross-layer linkage checks (municipality parent references + decision consistency)
    cross_layer_errors = _validate_cross_layer_linkage(valid_rows)
    for error_msg in cross_layer_errors:
        failed += 1
        print(f"FAIL: {error_msg}")

    if failed == 0:
        try:
            CoverageRegistry.model_validate(raw_payload)
        except ValidationError as error:
            failed += 1
            print(f"FAIL: Registry-level validation error -> {format_validation_errors(error)}")

    checked = len(row_payloads)
    passed = checked - sum(1 for result in validation_results if result.row is None)
    print(f"Validation summary: checked={checked} passed={passed} failed={failed} warnings={warnings}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
