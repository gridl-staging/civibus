"""
Stub summary for MAR18_api_graph_routes_and_property_endpoints/civibus_dev/domains/campaign_finance/validate_configs.py.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from domains.campaign_finance.jurisdictions.config_schema import (
    JurisdictionConfig,
    discover_jurisdiction_configs,
    load_jurisdiction_config,
)


_DEFAULT_JURISDICTIONS_ROOT = Path(__file__).resolve().parent / "jurisdictions"


@dataclass(frozen=True)
class _ValidationResult:
    path: Path
    config: JurisdictionConfig | None
    error: str | None

    @property
    def is_valid(self) -> bool:
        return self.config is not None


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate campaign-finance jurisdiction configs")
    parser.add_argument(
        "--path",
        type=Path,
        help="Validate a single configuration file instead of discovering all configs",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print parsed config summary for each valid config",
    )
    return parser


def _resolve_paths(config_path: Path | None) -> list[Path]:
    if config_path is not None:
        return [config_path.resolve()]
    discovered_paths = discover_jurisdiction_configs(_DEFAULT_JURISDICTIONS_ROOT)
    return sorted(discovered_paths)


def _validate_config_path(config_path: Path) -> _ValidationResult:
    resolved_path = config_path.resolve()
    try:
        return _ValidationResult(path=resolved_path, config=load_jurisdiction_config(config_path), error=None)
    except ValueError as error:
        return _ValidationResult(path=resolved_path, config=None, error=str(error))


def _loaded_configs(results: list[_ValidationResult]) -> list[tuple[Path, JurisdictionConfig]]:
    loaded_configs: list[tuple[Path, JurisdictionConfig]] = []
    for result in results:
        if result.config is None:
            continue
        loaded_configs.append((result.path, result.config))
    return loaded_configs


def _format_config_summary(config: JurisdictionConfig) -> str:
    source_names = [source.name for source in config.data_sources]
    return (
        f"code={config.jurisdiction.code} type={config.jurisdiction.type} "
        f"parent={config.jurisdiction.parent} source_count={len(config.data_sources)} "
        f"source_names={', '.join(source_names)}"
    )


def _collect_duplicate_codes(results: list[_ValidationResult]) -> list[str]:
    code_to_paths = defaultdict(list)
    for path, config in _loaded_configs(results):
        code_to_paths[config.jurisdiction.code].append(path)

    warnings: list[str] = []
    for jurisdiction_code, config_paths in sorted(code_to_paths.items()):
        if len(config_paths) <= 1:
            continue
        sorted_paths = ", ".join(str(path) for path in sorted(config_paths))
        warnings.append(f"Duplicate jurisdiction code '{jurisdiction_code}' in: {sorted_paths}")
    return warnings


def _collect_dangling_parent_warnings(results: list[_ValidationResult]) -> list[str]:
    loaded_configs = _loaded_configs(results)
    known_codes = {config.jurisdiction.code for _, config in loaded_configs}

    warnings: list[str] = []
    for path, config in sorted(loaded_configs, key=lambda item: str(item[0])):
        parent = config.jurisdiction.parent
        if parent is not None and parent not in known_codes:
            warnings.append(f"Missing parent '{parent}' referenced by {path}")
    return warnings


def _collect_duplicate_url_warnings(results: list[_ValidationResult]) -> list[str]:
    url_to_paths_and_sources: dict[str, list[tuple[Path, list[str]]]] = defaultdict(list)
    for path, config in _loaded_configs(results):
        urls = defaultdict(list)
        for source in config.data_sources:
            urls[source.url].append(source.name)

        for url, source_names in urls.items():
            url_to_paths_and_sources[url].append((path, source_names))

    warnings: list[str] = []
    for url, path_and_sources in sorted(url_to_paths_and_sources.items()):
        duplicate_source_count = sum(len(source_names) for _, source_names in path_and_sources)
        if duplicate_source_count <= 1:
            continue

        path_parts = []
        for path, source_names in sorted(path_and_sources, key=lambda item: str(item[0])):
            names = ", ".join(sorted(source_names))
            path_parts.append(f"{path} (sources: {names})")
        warnings.append(f"Duplicate data source URL '{url}' in: {'; '.join(path_parts)}")
    return warnings


def main(argv: list[str] | None = None) -> int:
    parsed_argv = argv if argv is not None else []
    args = _build_argument_parser().parse_args(parsed_argv)

    config_paths = _resolve_paths(args.path)
    validation_results = [_validate_config_path(config_path) for config_path in config_paths]

    total_checked = 0
    passed = 0
    failed = 0

    for result in validation_results:
        total_checked += 1
        if result.config is None:
            failed += 1
            print(f"FAIL: {result.path} -> {result.error}")
            continue

        passed += 1
        print(f"PASS: {result.path}")
        if args.verbose:
            print(f"  {_format_config_summary(result.config)}")

    warning_lines: list[str] = []
    warning_lines.extend(_collect_duplicate_codes(validation_results))
    warning_lines.extend(_collect_dangling_parent_warnings(validation_results))
    warning_lines.extend(_collect_duplicate_url_warnings(validation_results))

    for warning in warning_lines:
        print(f"WARNING: {warning}")

    print(f"Validation summary: checked={total_checked} passed={passed} failed={failed} warnings={len(warning_lines)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
