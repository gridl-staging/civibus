from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_property_domain_stage2_scaffold_layout_and_markers() -> None:
    required_directories = [
        "domains/property/",
        "domains/property/types/",
        "domains/property/normalize/",
        "domains/property/ingest/",
        "domains/property/entity_extractors/",
        "domains/property/jurisdictions/",
        "domains/property/schema/",
        "domains/property/tests/",
    ]

    for rel_path in required_directories:
        assert (REPO_ROOT / rel_path).is_dir(), f"Expected directory missing: {rel_path}"

    required_package_markers = [
        "domains/property/__init__.py",
        "domains/property/types/__init__.py",
        "domains/property/normalize/__init__.py",
        "domains/property/ingest/__init__.py",
        "domains/property/entity_extractors/__init__.py",
        "domains/property/jurisdictions/__init__.py",
    ]

    for rel_path in required_package_markers:
        assert (REPO_ROOT / rel_path).is_file(), f"Expected package marker missing: {rel_path}"

    assert not (REPO_ROOT / "domains/property/schema/__init__.py").exists()


def test_property_domain_stage2_does_not_include_deferred_files() -> None:
    deferred_paths = [
        "domains/property/profile.py",
    ]

    for rel_path in deferred_paths:
        assert not (REPO_ROOT / rel_path).exists(), f"Deferred file must be absent in Stage 2: {rel_path}"
