"""Civics-local pytest fixtures for NCSBE results parser red tests."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[3]
_NCSBE_ARTIFACTS_DIR = (
    _REPO_ROOT / "docs" / "reference" / "research" / "artifacts" / "2026_04_30_dwo_past_results" / "ncsbe"
)
_RAW_EXTRACTS_DIR = _NCSBE_ARTIFACTS_DIR / "raw_extracts"


@pytest.fixture(scope="session")
def ncsbe_raw_extract_paths() -> list[Path]:
    paths = sorted(_RAW_EXTRACTS_DIR.glob("enrs_*_sample.csv"))
    assert len(paths) == 4, "Stage 1 contract requires exactly four fixed-election ENRS fixture files"
    return paths


@pytest.fixture(scope="session")
def ncsbe_contract_rows_by_file(ncsbe_raw_extract_paths: list[Path]) -> dict[str, list[dict[str, str]]]:
    rows_by_file: dict[str, list[dict[str, str]]] = {}
    for csv_path in ncsbe_raw_extract_paths:
        with csv_path.open("r", encoding="utf-8", newline="") as handle:
            rows_by_file[csv_path.name] = list(csv.DictReader(handle))
    assert rows_by_file, "Expected at least one NCSBE contract fixture file"
    return rows_by_file
