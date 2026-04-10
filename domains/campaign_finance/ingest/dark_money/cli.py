
from __future__ import annotations

import argparse
from contextlib import contextmanager
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from typing import Iterator

from core.db import get_connection
from domains.campaign_finance.ingest.bulk_stage4_loader import LoadResult
from domains.campaign_finance.ingest.dark_money.download import download_irs_527_full_data, extract_irs_527_txt
from domains.campaign_finance.ingest.dark_money.loader import ensure_irs_527_data_source, load_irs_527_records


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="IRS 527 dark-money downloader and ingest CLI")
    subcommands = parser.add_subparsers(dest="mode", required=True)

    download_parser = subcommands.add_parser("download", help="Download IRS 527 ZIP and extract FullDataFile.txt")
    download_parser.add_argument(
        "--dest-dir",
        type=Path,
        default=Path("data/irs_527"),
        help="Destination directory for downloaded and extracted files",
    )

    ingest_parser = subcommands.add_parser("ingest", help="Ingest IRS 527 FullDataFile.txt or ZIP")
    ingest_parser.add_argument("--path", type=Path, required=True, help="Path to FullDataFile.txt or ZIP archive")
    ingest_parser.add_argument("--batch-size", type=int, default=1000, help="Commit interval (default: 1000)")
    ingest_parser.add_argument("--limit", type=int, help="Optional row limit")

    return parser


@contextmanager
def _resolve_ingest_txt_path(path: Path) -> Iterator[Path]:
    if path.suffix.lower() == ".zip":
        with TemporaryDirectory(prefix="irs_527_") as temp_dir:
            yield extract_irs_527_txt(path, Path(temp_dir))
        return
    yield path


def run_download(*, dest_dir: Path) -> Path:
    archive_path = download_irs_527_full_data(dest_dir)
    return extract_irs_527_txt(archive_path, archive_path.parent)


def run_ingest(
    *,
    path: Path,
    batch_size: int = 1000,
    limit: int | None = None,
) -> LoadResult:
    connection = get_connection()
    try:
        with _resolve_ingest_txt_path(path) as txt_path:
            data_source_id = ensure_irs_527_data_source(connection)
            connection.commit()
            result = load_irs_527_records(
                connection,
                txt_path,
                data_source_id=data_source_id,
                batch_size=batch_size,
                limit=limit,
            )
            connection.commit()
            return result
    finally:
        connection.close()


def main(argv: list[str] | None = None) -> int:
    parser = build_argument_parser()
    args = parser.parse_args(argv)

    try:
        if args.mode == "download":
            txt_path = run_download(dest_dir=args.dest_dir)
            print(f"IRS 527 download complete: extracted {txt_path}")
            return 0

        result = run_ingest(path=args.path, batch_size=args.batch_size, limit=args.limit)
        print(f"IRS 527 ingest complete: inserted={result.inserted} skipped={result.skipped} errors={result.errors}")
        return 0
    except Exception as error:  # noqa: BLE001
        print(f"IRS 527 pipeline failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
