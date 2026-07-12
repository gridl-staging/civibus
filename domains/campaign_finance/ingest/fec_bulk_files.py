
from __future__ import annotations

from pathlib import Path
from collections.abc import Callable
from urllib.request import urlretrieve


FEC_BULK_DOWNLOAD_BASE = "https://www.fec.gov/files/bulk-downloads"
FEC_BULK_URL_SLUGS: dict[str, str] = {
    "cm": "cm",
    "cn": "cn",
    "ccl": "ccl",
    "itcont": "indiv",
    "itpas2": "pas2",
    "weball": "weball",
    "schedule_e": "independent_expenditure",
}


def fec_baseline_url(cycle: int, file_type: str) -> str:
    if file_type not in {"cm", "cn", "ccl", "itcont", "itpas2"}:
        raise ValueError(f"Unknown FEC file type: {file_type}")
    slug = FEC_BULK_URL_SLUGS[file_type]
    yy = str(cycle)[-2:]
    return f"{FEC_BULK_DOWNLOAD_BASE}/{cycle}/{slug}{yy}.zip"


def fec_schedule_b_url(cycle: int) -> str:
    yy = str(cycle)[-2:]
    return f"{FEC_BULK_DOWNLOAD_BASE}/{cycle}/oppexp{yy}.zip"


def fec_weball_url(cycle: int) -> str:
    yy = str(cycle)[-2:]
    return f"{FEC_BULK_DOWNLOAD_BASE}/{cycle}/weball{yy}.zip"


def fec_schedule_e_url(cycle: int) -> str:
    filename = f"independent_expenditure_{cycle}.csv"
    return f"{FEC_BULK_DOWNLOAD_BASE}/{cycle}/{filename}"


def fec_committee_summary_url(cycle: int) -> str:
    filename = f"committee_summary_{cycle}.csv"
    return f"{FEC_BULK_DOWNLOAD_BASE}/{cycle}/{filename}"


def fec_baseline_urls(cycle: int, file_order: tuple[str, ...]) -> dict[str, str]:
    return {file_type: fec_baseline_url(cycle, file_type) for file_type in file_order}


def fec_bulk_cache_path(repo_root: Path, *, cycle: int, file_type: str) -> Path:
    return fec_bulk_data_cache_path(repo_root / "data", cycle=cycle, file_type=file_type)


def fec_bulk_data_cache_path(data_root: Path, *, cycle: int, file_type: str) -> Path:
    cycle_suffix = str(cycle)[-2:]
    if file_type == "schedule_e":
        filename = f"independent_expenditure_{cycle}.csv"
    elif file_type == "schedule_b":
        filename = f"oppexp{cycle_suffix}.zip"
    else:
        filename = f"{file_type}{cycle_suffix}.zip"
    return data_root / "fec" / "bulk" / str(cycle) / filename


def download_fec_bulk_file_to_cache(
    repo_root: Path,
    *,
    cycle: int,
    file_type: str,
    data_root: Path | None = None,
    downloader: Callable[[str, Path], object] = urlretrieve,
) -> Path:
    if file_type not in {*FEC_BULK_URL_SLUGS.keys(), "schedule_b"}:
        raise ValueError(f"Unknown FEC file type: {file_type}")

    cache_path = (
        fec_bulk_data_cache_path(data_root, cycle=cycle, file_type=file_type)
        if data_root is not None
        else fec_bulk_cache_path(repo_root, cycle=cycle, file_type=file_type)
    )
    if cache_path.is_file() and cache_path.stat().st_size > 0:
        return cache_path

    if file_type == "schedule_b":
        url = fec_schedule_b_url(cycle)
    elif file_type == "schedule_e":
        url = fec_schedule_e_url(cycle)
    elif file_type == "weball":
        url = fec_weball_url(cycle)
    else:
        url = fec_baseline_url(cycle, file_type)

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    partial_path = cache_path.with_suffix(f"{cache_path.suffix}.part")
    partial_path.unlink(missing_ok=True)
    downloader(url, partial_path)
    partial_path.replace(cache_path)
    return cache_path
