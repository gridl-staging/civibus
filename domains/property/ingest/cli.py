"""
Stub summary for MAR18_cross_domain_er_and_property_graph/civibus_dev/domains/property/ingest/cli.py.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import psycopg

from core.db import get_connection
from domains.property.ingest.durham_source import (
    load_durham_config,
    load_durham_fixture_records,
    normalize_durham_raw_records,
    resolve_bundled_durham_asset_paths,
)
from domains.property.ingest.loader import ensure_durham_data_source, ensure_durham_jurisdiction, load_durham_records


def default_durham_ingest_paths() -> tuple[Path, Path]:
    return resolve_bundled_durham_asset_paths()


def _build_argument_parser() -> argparse.ArgumentParser:
    default_config_path, default_fixture_path = default_durham_ingest_paths()
    parser = argparse.ArgumentParser(description="Load Durham sample property records into Civibus")
    parser.add_argument(
        "--config-path",
        type=Path,
        default=default_config_path,
        help="Path to Durham config.yaml (default: bundled jurisdiction asset)",
    )
    parser.add_argument(
        "--fixture-path",
        type=Path,
        default=default_fixture_path,
        help="Path to ArcGIS sample fixture JSON (default: bundled Durham sample fixture)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_argument_parser().parse_args(argv)
    connection: psycopg.Connection | None = None

    try:
        config = load_durham_config(args.config_path)
        raw_records = load_durham_fixture_records(args.fixture_path)
        normalized_records = normalize_durham_raw_records(raw_records)

        connection = get_connection()
        with connection.transaction():
            data_source_id = ensure_durham_data_source(connection, config)
            jurisdiction_id = ensure_durham_jurisdiction(connection, config)
            loaded_count, skipped_count, error_count = load_durham_records(
                connection,
                data_source_id,
                jurisdiction_id,
                normalized_records,
                per_record_savepoints=True,
            )
        connection.commit()
    except Exception as error:  # noqa: BLE001
        print(f"Durham ingest failed: {error}", file=sys.stderr)
        return 1
    finally:
        if connection is not None:
            connection.close()

    summary = f"loaded={loaded_count} skipped={skipped_count} errors={error_count} fetched={len(normalized_records)}"
    if error_count > 0:
        print(f"Durham ingest completed with record errors: {summary}", file=sys.stderr)
        return 1

    print(f"Durham ingest complete: {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
