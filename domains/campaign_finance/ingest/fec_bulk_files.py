from __future__ import annotations

import os
from pathlib import Path
from collections.abc import Callable
from urllib.request import urlretrieve


FEC_BULK_DOWNLOAD_BASE = "https://www.fec.gov/files/bulk-downloads"

FEC_DATA_ROOT_ENV_VAR = "CIVIBUS_FEC_DATA_ROOT"

# ingest -> campaign_finance -> domains -> repo root. NB: two levels up is the
# `domains` package, which would silently resolve archives to `<repo>/domains/data`.
_REPO_ROOT = Path(__file__).resolve().parents[3]
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


def fec_bulk_data_root(data_root: Path) -> Path:
    return data_root / "fec" / "bulk"


class FecDataRootMissingError(RuntimeError):
    """Raised when no usable FEC bulk archive root can be resolved."""


def resolve_fec_data_root(*, repo_root: Path | None = None) -> Path:
    """Resolve the `data/` root holding FEC bulk archives.

    Returns the **`data/` root** — the parent of `fec/` — because
    `fec_bulk_data_cache_path` appends `fec/bulk` itself. `CIVIBUS_FEC_DATA_ROOT`
    must therefore be set to `.../data`, not `.../data/fec`; the variable name
    invites the wrong value.

    Resolution order is the environment variable, then `<repo_root>/data`. The
    chosen root is only returned when `fec/bulk` exists beneath it: `.gitignore`
    excludes `data/`, so a git worktree has no archives at all and a lane that
    assumed otherwise would fail later with an unrelated error.

    `repo_root` exists so tests can build the fallback branch in a tmp dir instead
    of depending on where the suite happens to run.
    """
    configured = os.environ.get(FEC_DATA_ROOT_ENV_VAR)
    if configured:
        data_root = Path(configured)
        source = f"{FEC_DATA_ROOT_ENV_VAR}={configured}"
    else:
        data_root = (repo_root if repo_root is not None else _REPO_ROOT) / "data"
        source = f"{FEC_DATA_ROOT_ENV_VAR} unset; fell back to <repo_root>/data"

    archive_root = fec_bulk_data_root(data_root)
    if not archive_root.is_dir():
        raise FecDataRootMissingError(
            f"No FEC bulk archives at {archive_root} ({source}). "
            f"Set {FEC_DATA_ROOT_ENV_VAR} to the data/ root that contains fec/bulk "
            f"— note that git worktrees never carry archives, because .gitignore excludes data/."
        )
    return data_root


def fec_bulk_data_cache_path(data_root: Path, *, cycle: int, file_type: str) -> Path:
    cycle_suffix = str(cycle)[-2:]
    if file_type == "schedule_e":
        filename = f"independent_expenditure_{cycle}.csv"
    elif file_type == "schedule_b":
        filename = f"oppexp{cycle_suffix}.zip"
    else:
        filename = f"{file_type}{cycle_suffix}.zip"
    return fec_bulk_data_root(data_root) / str(cycle) / filename


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
