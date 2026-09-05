"""Import-direction contract for campaign-finance jurisdiction packages.

Audit scope
-----------
This module owns a *static import-direction* classifier for concrete
campaign-finance region packages (for example
``domains.campaign_finance.jurisdictions.states.CA``). It answers exactly one
question about a Python source file: for every import statement it contains,
does that import reach into a concrete region package, and if so, is that
region the importing file's own region or a different one?

Runtime mutation-path ownership is explicitly **out of scope** for this
contract and is not mechanically checkable from an AST. A region adapter that
writes shared campaign-finance schema tables, mutates shared refresh state, or
reaches another region's loader through dynamic dispatch (``importlib``,
``getattr`` on a registry, a subprocess CLI invocation, or a SQL statement) is
invisible here. Do not read a passing import-direction check as evidence that
runtime ownership boundaries hold.

Stage scope
-----------
Stage 1 kept the classifier pure and file-local. Stage 2 reuses it to classify
caller-supplied specimens and to enforce a scan of live tracked Python files.
Concrete region roots come from the canonical discovery owner,
``domains.campaign_finance.jurisdictions.config_schema.discover_jurisdiction_configs``,
so this module carries no ``config.yaml`` glob and no parallel ``_template``
exclusion rule of its own.
"""

from __future__ import annotations

import ast
import subprocess
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent

import pytest

from domains.campaign_finance.jurisdictions.config_schema import discover_jurisdiction_configs


REPO_ROOT = Path(__file__).resolve().parents[2]
JURISDICTIONS_DIR = REPO_ROOT / "domains" / "campaign_finance" / "jurisdictions"
TEMPLATE_CONFIG_PATH = JURISDICTIONS_DIR / "_template" / "config.yaml"
CA_CONFIG_PATH = JURISDICTIONS_DIR / "states" / "CA" / "config.yaml"

JURISDICTIONS_PACKAGE = "domains.campaign_finance.jurisdictions"
STATES_PACKAGE = f"{JURISDICTIONS_PACKAGE}.states"
CITIES_PACKAGE = f"{JURISDICTIONS_PACKAGE}.cities"
CA_PACKAGE = f"{STATES_PACKAGE}.CA"
MN_PACKAGE = f"{STATES_PACKAGE}.MN"
CITIES_LA_PACKAGE = f"{CITIES_PACKAGE}.LA"
STATES_LA_PACKAGE = f"{STATES_PACKAGE}.LA"
REFRESH_REGISTRY_MODULE = f"{JURISDICTIONS_PACKAGE}.refresh_registry"
ImportPolicyEntry = tuple[str, str, str]

SHARED_SEAM_MODULES = (
    f"{JURISDICTIONS_PACKAGE}._test_helpers",
    f"{JURISDICTIONS_PACKAGE}.protected_portal",
    f"{STATES_PACKAGE}.load_utils",
    f"{STATES_PACKAGE}.config_helpers",
)

CA_LOAD_RELATIVE_PATH = Path("domains/campaign_finance/jurisdictions/states/CA/scraper/load.py")
CA_PACKAGE_INIT_RELATIVE_PATH = Path("domains/campaign_finance/jurisdictions/states/CA/scraper/__init__.py")


def _accepted_inbound_imports(
    relative_path: str,
    importing_module: str,
    imported_modules: tuple[str, ...],
) -> frozenset[ImportPolicyEntry]:
    return frozenset((relative_path, importing_module, imported_module) for imported_module in imported_modules)


def _modules(package_root: str, suffixes: str) -> tuple[str, ...]:
    return tuple(f"{package_root}.{suffix}" for suffix in suffixes.split())


def _state_modules(suffixes: str) -> tuple[str, ...]:
    return _modules(STATES_PACKAGE, suffixes)


_DEFAULT_ACCEPTED_INBOUND_IMPORTS: frozenset[ImportPolicyEntry] = frozenset(
    {
        ("core/keel_gate_l6.py", "core.keel_gate_l6", f"{STATES_PACKAGE}.NC.scraper.parse"),
    }
    | _accepted_inbound_imports(
        "domains/campaign_finance/jurisdictions/refresh_registry.py",
        REFRESH_REGISTRY_MODULE,
        _state_modules(
            """
            AL.refresh CA.refresh CO.refresh FL.refresh GA.refresh IL.refresh IN.refresh KY.refresh
            LA.refresh MA.refresh MN.refresh NC.refresh NE.refresh NJ.refresh NY.refresh OR.refresh
            PA.refresh TX.refresh VA.refresh WA.refresh WI.refresh
            """
        )
        + _modules(CITIES_PACKAGE, "LA.refresh NYC.refresh PHL.refresh SF.refresh"),
    )
    | _accepted_inbound_imports(
        "domains/campaign_finance/quality/freshness.py",
        "domains.campaign_finance.quality.freshness",
        _state_modules(
            """
            IL.scraper IL.scraper.download IL.scraper.load IL.scraper.parse IN.scraper
            IN.scraper.download IN.scraper.load_helpers IN.scraper.parse MN.scraper
            MN.scraper.download MN.scraper.load MN.scraper.parse NJ.scraper
            NJ.scraper.download NJ.scraper.load NJ.scraper.parse
            """
        ),
    )
    | _accepted_inbound_imports(
        "domains/campaign_finance/quality/state_closeout.py",
        "domains.campaign_finance.quality.state_closeout",
        _state_modules(
            "CO.scraper.load CO.scraper.parse GA.scraper.load GA.scraper.parse NC.scraper.load NC.scraper.parse"
        ),
    )
    | _accepted_inbound_imports(
        "domains/civics/tests/test_candidacy_committee_coverage_probe.py",
        "domains.civics.tests.test_candidacy_committee_coverage_probe",
        _state_modules("NC.scraper.committee_candidacy_match NC.scraper.load"),
    )
    | _accepted_inbound_imports(
        "tests/e2e/test_ie_pipeline_smoke.py",
        "tests.e2e.test_ie_pipeline_smoke",
        _state_modules(
            "CA.scraper.load CO.scraper.load KY.scraper.load MN.scraper.load NE.scraper.load NY.scraper.load "
            "WA.scraper.load WI.scraper.load"
        ),
    )
    | _accepted_inbound_imports(
        "tests/test_state_sample_ingest_smoke.py",
        "tests.test_state_sample_ingest_smoke",
        _state_modules("CO.scraper.cli GA.scraper.cli NC.scraper.cli"),
    )
)
# Narrow pre-existing debt: this archived NC IE research probe still imports
# the live NC parser to compare captured portal artifacts against current parse
# behavior. Intended owner for reroute/removal:
# `docs/reference/research/artifacts/2026_04_24_nc_ie_amounts/probe.py`.
_ACCEPTED_INBOUND_IMPORT_DEBT: frozenset[ImportPolicyEntry] = frozenset(
    {
        (
            "docs/reference/research/artifacts/2026_04_24_nc_ie_amounts/probe.py",
            "docs.reference.research.artifacts.2026_04_24_nc_ie_amounts.probe",
            f"{STATES_PACKAGE}.NC.scraper.parse",
        )
    }
)


# --------------------------------------------------------------------------
# Classifier
# --------------------------------------------------------------------------

CROSS_REGION_IMPORT = "cross_region"
SAME_REGION_IMPORT = "same_region"
INBOUND_REGION_IMPORT = "inbound_region"
NON_REGION_IMPORT = "non_region"


@dataclass(frozen=True)
class RegionRoot:
    """A concrete jurisdiction package, addressed both as a package and on disk."""

    package_root: str
    filesystem_root: Path


@dataclass(frozen=True)
class ImportClassification:
    """One import statement, classified relative to the concrete region roots."""

    file_path: Path
    line_number: int
    importing_module: str
    imported_module: str
    importing_region_root: str | None
    imported_region_root: str | None
    kind: str


@dataclass(frozen=True)
class AcceptedInboundImportMismatch:
    """Difference between accepted inbound policy keys and live observations."""

    missing_accepted: frozenset[ImportPolicyEntry]
    unexpected_observed: frozenset[ImportPolicyEntry]


def _module_name_for_path(path: Path, naming_root: Path) -> tuple[str, bool]:
    """Return the dotted module name for ``path`` and whether it names a package."""
    relative_parts = list(path.resolve().relative_to(naming_root.resolve()).parts)
    is_package = True
    if relative_parts and relative_parts[-1].endswith(".py"):
        relative_parts[-1] = relative_parts[-1].removesuffix(".py")
        is_package = relative_parts[-1] == "__init__"
        if is_package:
            relative_parts.pop()
    return ".".join(relative_parts), is_package


def discover_region_roots(repo_root: Path) -> tuple[RegionRoot, ...]:
    """Derive concrete region roots from the canonical jurisdiction config discovery owner."""
    region_roots: list[RegionRoot] = []
    for config_path in discover_jurisdiction_configs(repo_root):
        region_directory = config_path.parent
        package_root, _ = _module_name_for_path(region_directory, repo_root)
        region_roots.append(RegionRoot(package_root=package_root, filesystem_root=region_directory))
    return tuple(region_roots)


def _match_region_root(module_name: str, region_roots: tuple[RegionRoot, ...]) -> RegionRoot | None:
    """Match on dotted-path boundaries so ``states.CALIFORNIA`` never matches ``states.CA``."""
    for region_root in region_roots:
        if module_name == region_root.package_root or module_name.startswith(f"{region_root.package_root}."):
            return region_root
    return None


def _resolve_relative_module(node: ast.ImportFrom, importing_module: str, is_package: bool) -> str:
    """Resolve a relative ``ImportFrom`` target against its containing package."""
    base_parts = importing_module.split(".") if importing_module else []
    if not is_package:
        base_parts = base_parts[:-1]

    levels_above_package = node.level - 1
    if levels_above_package > len(base_parts):
        raise ValueError(
            f"relative import on line {node.lineno} of {importing_module or '<root>'} escapes the naming root"
        )
    if levels_above_package:
        base_parts = base_parts[:-levels_above_package]

    if node.module:
        base_parts.extend(node.module.split("."))
    return ".".join(base_parts)


def _imported_modules_for_import(node: ast.Import) -> tuple[str, ...]:
    return tuple(dict.fromkeys(alias.name for alias in node.names))


def _imported_modules_for_import_from(
    node: ast.ImportFrom,
    resolved_module: str,
    region_roots: tuple[RegionRoot, ...],
) -> tuple[str, ...]:
    """Prefer ``<module>.<alias>`` when the alias itself names a concrete region root.

    ``from ...jurisdictions.states import MN`` imports a region through a shared
    package, so the alias — not the shared package — is the meaningful target.
    """
    region_package_roots = {region_root.package_root for region_root in region_roots}
    imported_modules: list[str] = []
    for alias in node.names:
        candidate = f"{resolved_module}.{alias.name}" if resolved_module else alias.name
        imported_modules.append(candidate if candidate in region_package_roots else resolved_module)
    return tuple(dict.fromkeys(module for module in imported_modules if module))


def _classify_kind(importing_region: RegionRoot | None, imported_region: RegionRoot | None) -> str:
    if imported_region is None:
        return NON_REGION_IMPORT
    if importing_region is None:
        return INBOUND_REGION_IMPORT
    if importing_region.package_root == imported_region.package_root:
        return SAME_REGION_IMPORT
    return CROSS_REGION_IMPORT


def classify_source_imports(
    source_path: Path,
    naming_root: Path,
    region_roots: tuple[RegionRoot, ...],
) -> tuple[ImportClassification, ...]:
    """Classify every import in ``source_path`` against the concrete region roots.

    ``naming_root`` is the directory the dotted module name is derived from, so a
    specimen tree and the live repository tree classify identically.
    """
    importing_module, is_package = _module_name_for_path(source_path, naming_root)
    importing_region = _match_region_root(importing_module, region_roots)
    module = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))

    classifications: list[ImportClassification] = []
    for node in ast.walk(module):
        if isinstance(node, ast.Import):
            imported_modules = _imported_modules_for_import(node)
        elif isinstance(node, ast.ImportFrom):
            resolved_module = (
                _resolve_relative_module(node, importing_module, is_package) if node.level else (node.module or "")
            )
            imported_modules = _imported_modules_for_import_from(node, resolved_module, region_roots)
        else:
            continue

        for imported_module in imported_modules:
            imported_region = _match_region_root(imported_module, region_roots)
            classifications.append(
                ImportClassification(
                    file_path=source_path,
                    line_number=node.lineno,
                    importing_module=importing_module,
                    imported_module=imported_module,
                    importing_region_root=None if importing_region is None else importing_region.package_root,
                    imported_region_root=None if imported_region is None else imported_region.package_root,
                    kind=_classify_kind(importing_region, imported_region),
                )
            )
    return tuple(sorted(classifications, key=lambda entry: (entry.line_number, entry.imported_module)))


def _tracked_python_files(repo_root: Path) -> tuple[Path, ...]:
    result = subprocess.run(
        ["git", "ls-files", "*.py"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return tuple(repo_root / relative_path for relative_path in result.stdout.splitlines())


def scan_repository_imports(repo_root: Path = REPO_ROOT) -> tuple[ImportClassification, ...]:
    region_roots = discover_region_roots(repo_root)
    classifications: list[ImportClassification] = []
    for source_path in _tracked_python_files(repo_root):
        classifications.extend(classify_source_imports(source_path, repo_root, region_roots))
    return tuple(classifications)


def _policy_key(classification: ImportClassification, repo_root: Path) -> ImportPolicyEntry:
    return (
        classification.file_path.relative_to(repo_root).as_posix(),
        classification.importing_module,
        classification.imported_module,
    )


def find_import_boundary_policy_violations(
    classifications: tuple[ImportClassification, ...],
    repo_root: Path,
    *,
    accepted_inbound_imports: frozenset[ImportPolicyEntry] = _DEFAULT_ACCEPTED_INBOUND_IMPORTS,
    accepted_inbound_import_debt: frozenset[ImportPolicyEntry] = _ACCEPTED_INBOUND_IMPORT_DEBT,
) -> tuple[ImportClassification, ...]:
    accepted_inbound = accepted_inbound_imports | accepted_inbound_import_debt
    violations = []
    for classification in classifications:
        if classification.kind == CROSS_REGION_IMPORT:
            violations.append(classification)
        elif (
            classification.kind == INBOUND_REGION_IMPORT
            and _policy_key(classification, repo_root) not in accepted_inbound
        ):
            violations.append(classification)
    return tuple(violations)


def find_accepted_inbound_import_mismatch(
    classifications: tuple[ImportClassification, ...],
    repo_root: Path,
) -> AcceptedInboundImportMismatch:
    accepted_inbound = _locality_present_accepted_inbound_imports(repo_root)
    observed_inbound = frozenset(
        _policy_key(classification, repo_root)
        for classification in classifications
        if classification.kind == INBOUND_REGION_IMPORT
    )
    unexpected_observed = frozenset(
        _policy_key(violation, repo_root)
        for violation in find_import_boundary_policy_violations(classifications, repo_root)
        if violation.kind == INBOUND_REGION_IMPORT
    )
    return AcceptedInboundImportMismatch(
        missing_accepted=accepted_inbound - observed_inbound,
        unexpected_observed=unexpected_observed,
    )


def _locality_present_accepted_inbound_imports(repo_root: Path) -> frozenset[ImportPolicyEntry]:
    tracked_relative_paths = frozenset(
        path.relative_to(repo_root).as_posix() for path in _tracked_python_files(repo_root)
    )
    return frozenset(
        entry
        for entry in _DEFAULT_ACCEPTED_INBOUND_IMPORTS | _ACCEPTED_INBOUND_IMPORT_DEBT
        if entry[0] in tracked_relative_paths
    )


def format_import_boundary_policy_violations(
    violations: tuple[ImportClassification, ...],
    repo_root: Path,
) -> str:
    lines: list[str] = []
    for violation in violations:
        relative_path = violation.file_path.relative_to(repo_root).as_posix()
        lines.append(
            f"{violation.kind}: {relative_path}:{violation.line_number} "
            f"importing_module={violation.importing_module} "
            f"imported_module={violation.imported_module} "
            f"importing_region_root={violation.importing_region_root} "
            f"imported_region_root={violation.imported_region_root}"
        )
    return "\n".join(lines)


@pytest.fixture(scope="module")
def region_roots() -> tuple[RegionRoot, ...]:
    return discover_region_roots(REPO_ROOT)


def _classify_specimen(
    naming_root: Path,
    relative_path: Path,
    source: str,
    region_roots: tuple[RegionRoot, ...],
) -> tuple[ImportClassification, ...]:
    """Write a specimen source at ``relative_path`` and classify its imports."""
    specimen_path = naming_root / relative_path
    specimen_path.parent.mkdir(parents=True, exist_ok=True)
    specimen_path.write_text(dedent(source).lstrip(), encoding="utf-8")
    return classify_source_imports(specimen_path, naming_root, region_roots)


def _region_package_roots(region_roots: tuple[RegionRoot, ...]) -> tuple[str, ...]:
    return tuple(root.package_root for root in region_roots)


def _make_classification(
    policy_key: ImportPolicyEntry,
    *,
    line_number: int,
    importing_region_root: str | None,
    imported_region_root: str | None,
    kind: str,
) -> ImportClassification:
    relative_path, importing_module, imported_module = policy_key
    return ImportClassification(
        file_path=REPO_ROOT / relative_path,
        line_number=line_number,
        importing_module=importing_module,
        imported_module=imported_module,
        importing_region_root=importing_region_root,
        imported_region_root=imported_region_root,
        kind=kind,
    )


def _public_locality_repo_root(tmp_path: Path) -> Path:
    if (REPO_ROOT / ".debbie.toml").is_file():
        from tests.test_debbie_post_sync_hook import project_debbie_public_mirror

        return project_debbie_public_mirror(tmp_path).root
    return REPO_ROOT


# --------------------------------------------------------------------------
# Canonical discovery reuse
# --------------------------------------------------------------------------


def test_canonical_discovery_returns_concrete_jurisdiction_configs() -> None:
    config_paths = discover_jurisdiction_configs(REPO_ROOT)

    assert config_paths, "canonical discovery returned no jurisdiction configs"
    assert all(path.name == "config.yaml" for path in config_paths)
    assert all(JURISDICTIONS_DIR in path.parents for path in config_paths)
    assert CA_CONFIG_PATH.resolve() in config_paths


def test_canonical_discovery_excludes_template_scaffolding() -> None:
    config_paths = discover_jurisdiction_configs(REPO_ROOT)

    assert TEMPLATE_CONFIG_PATH.is_file(), "the _template specimen must exist for this exclusion check to bite"
    assert TEMPLATE_CONFIG_PATH.resolve() not in config_paths
    assert not [path for path in config_paths if "_template" in path.parts]


def test_region_roots_carry_package_and_filesystem_roots(region_roots: tuple[RegionRoot, ...]) -> None:
    california = next(root for root in region_roots if root.package_root == CA_PACKAGE)

    assert california.filesystem_root == (JURISDICTIONS_DIR / "states" / "CA").resolve()
    assert california.filesystem_root.is_dir()


def test_region_roots_distinguish_same_code_across_jurisdiction_levels(
    region_roots: tuple[RegionRoot, ...],
) -> None:
    package_roots = _region_package_roots(region_roots)

    assert STATES_LA_PACKAGE in package_roots
    assert CITIES_LA_PACKAGE in package_roots


def test_shared_seams_are_not_region_roots(region_roots: tuple[RegionRoot, ...]) -> None:
    package_roots = _region_package_roots(region_roots)

    assert JURISDICTIONS_PACKAGE not in package_roots
    assert STATES_PACKAGE not in package_roots
    assert CITIES_PACKAGE not in package_roots
    assert f"{JURISDICTIONS_PACKAGE}._template" not in package_roots


def test_refresh_registry_is_the_only_allowed_refresh_adapter_composition_point() -> None:
    registry_path = "domains/campaign_finance/jurisdictions/refresh_registry.py"
    expected_registry_entries = {
        (registry_path, REFRESH_REGISTRY_MODULE, f"{root}.refresh") for root in (STATES_LA_PACKAGE, CITIES_LA_PACKAGE)
    }

    assert expected_registry_entries <= _DEFAULT_ACCEPTED_INBOUND_IMPORTS
    assert not {
        entry
        for entry in _DEFAULT_ACCEPTED_INBOUND_IMPORTS
        if entry[0] == "core/refresh/job_builders.py" and entry[2].endswith(".refresh")
    }


# --------------------------------------------------------------------------
# Import classification
# --------------------------------------------------------------------------


def test_absolute_import_into_another_region_is_cross_region(
    tmp_path: Path,
    region_roots: tuple[RegionRoot, ...],
) -> None:
    classifications = _classify_specimen(
        tmp_path,
        CA_LOAD_RELATIVE_PATH,
        f"""
        import {MN_PACKAGE}.scraper.parse
        """,
        region_roots,
    )

    assert len(classifications) == 1
    classification = classifications[0]
    assert classification.kind == CROSS_REGION_IMPORT
    assert classification.importing_module == f"{CA_PACKAGE}.scraper.load"
    assert classification.imported_module == f"{MN_PACKAGE}.scraper.parse"
    assert classification.importing_region_root == CA_PACKAGE
    assert classification.imported_region_root == MN_PACKAGE
    assert classification.line_number == 1
    assert classification.file_path == tmp_path / CA_LOAD_RELATIVE_PATH


def test_from_import_into_another_region_is_cross_region(
    tmp_path: Path,
    region_roots: tuple[RegionRoot, ...],
) -> None:
    classifications = _classify_specimen(
        tmp_path,
        CA_LOAD_RELATIVE_PATH,
        f"""
        from {MN_PACKAGE}.scraper.parse import parse_contributions
        """,
        region_roots,
    )

    assert len(classifications) == 1
    classification = classifications[0]
    assert classification.kind == CROSS_REGION_IMPORT
    assert classification.imported_module == f"{MN_PACKAGE}.scraper.parse"
    assert classification.imported_region_root == MN_PACKAGE


def test_from_import_of_region_name_off_shared_package_is_cross_region(
    tmp_path: Path,
    region_roots: tuple[RegionRoot, ...],
) -> None:
    classifications = _classify_specimen(
        tmp_path,
        CA_LOAD_RELATIVE_PATH,
        f"""
        from {STATES_PACKAGE} import MN
        """,
        region_roots,
    )

    assert len(classifications) == 1
    classification = classifications[0]
    assert classification.kind == CROSS_REGION_IMPORT
    assert classification.imported_module == MN_PACKAGE
    assert classification.imported_region_root == MN_PACKAGE


def test_relative_import_crossing_region_roots_is_cross_region(
    tmp_path: Path,
    region_roots: tuple[RegionRoot, ...],
) -> None:
    classifications = _classify_specimen(
        tmp_path,
        CA_LOAD_RELATIVE_PATH,
        """
        from ...MN.scraper import parse_contributions
        """,
        region_roots,
    )

    assert len(classifications) == 1
    classification = classifications[0]
    assert classification.kind == CROSS_REGION_IMPORT
    assert classification.importing_region_root == CA_PACKAGE
    assert classification.imported_module == f"{MN_PACKAGE}.scraper"
    assert classification.imported_region_root == MN_PACKAGE


def test_relative_import_from_package_init_resolves_against_the_package(
    tmp_path: Path,
    region_roots: tuple[RegionRoot, ...],
) -> None:
    classifications = _classify_specimen(
        tmp_path,
        CA_PACKAGE_INIT_RELATIVE_PATH,
        """
        from .parse import parse_contributions
        """,
        region_roots,
    )

    assert len(classifications) == 1
    classification = classifications[0]
    assert classification.importing_module == f"{CA_PACKAGE}.scraper"
    assert classification.imported_module == f"{CA_PACKAGE}.scraper.parse"
    assert classification.kind == SAME_REGION_IMPORT


@pytest.mark.parametrize(
    ("source", "expected_imported_module"),
    (
        (f"import {CA_PACKAGE}.scraper.parse", f"{CA_PACKAGE}.scraper.parse"),
        (f"from {CA_PACKAGE}.scraper.parse import parse_contributions", f"{CA_PACKAGE}.scraper.parse"),
        ("from .parse import parse_contributions", f"{CA_PACKAGE}.scraper.parse"),
        ("from ..tests import fixtures", f"{CA_PACKAGE}.tests"),
    ),
)
def test_same_region_imports_stay_allowed(
    tmp_path: Path,
    region_roots: tuple[RegionRoot, ...],
    source: str,
    expected_imported_module: str,
) -> None:
    classifications = _classify_specimen(tmp_path, CA_LOAD_RELATIVE_PATH, source, region_roots)

    assert len(classifications) == 1
    classification = classifications[0]
    assert classification.kind == SAME_REGION_IMPORT
    assert classification.imported_module == expected_imported_module
    assert classification.importing_region_root == CA_PACKAGE
    assert classification.imported_region_root == CA_PACKAGE


@pytest.mark.parametrize("shared_seam_module", SHARED_SEAM_MODULES)
def test_shared_seam_imports_are_not_region_imports(
    tmp_path: Path,
    region_roots: tuple[RegionRoot, ...],
    shared_seam_module: str,
) -> None:
    module_path, _, member = shared_seam_module.rpartition(".")
    classifications = _classify_specimen(
        tmp_path,
        CA_LOAD_RELATIVE_PATH,
        f"""
        import {shared_seam_module}
        from {module_path} import {member}
        """,
        region_roots,
    )

    assert [classification.kind for classification in classifications] == [
        NON_REGION_IMPORT,
        NON_REGION_IMPORT,
    ]
    # `from <package> import <member>` cannot be statically proven to name a
    # submodule, so the shared package itself is the recorded target.
    assert [classification.imported_module for classification in classifications] == [
        shared_seam_module,
        module_path,
    ]
    assert all(classification.imported_region_root is None for classification in classifications)


def test_import_from_shared_seam_into_a_region_is_inbound_not_cross_region(
    tmp_path: Path,
    region_roots: tuple[RegionRoot, ...],
) -> None:
    classifications = _classify_specimen(
        tmp_path,
        Path("domains/campaign_finance/jurisdictions/states/load_utils.py"),
        f"""
        from {CA_PACKAGE}.scraper import load
        """,
        region_roots,
    )

    assert len(classifications) == 1
    classification = classifications[0]
    assert classification.kind == INBOUND_REGION_IMPORT
    assert classification.importing_region_root is None
    assert classification.imported_region_root == CA_PACKAGE


def test_region_root_matching_respects_dotted_path_boundaries(
    tmp_path: Path,
    region_roots: tuple[RegionRoot, ...],
) -> None:
    classifications = _classify_specimen(
        tmp_path,
        CA_LOAD_RELATIVE_PATH,
        f"""
        import {STATES_PACKAGE}.CALIFORNIA.scraper
        """,
        region_roots,
    )

    assert len(classifications) == 1
    assert classifications[0].kind == NON_REGION_IMPORT
    assert classifications[0].imported_region_root is None


def test_classifications_record_file_line_and_nested_imports(
    tmp_path: Path,
    region_roots: tuple[RegionRoot, ...],
) -> None:
    classifications = _classify_specimen(
        tmp_path,
        CA_LOAD_RELATIVE_PATH,
        f"""
        from {STATES_PACKAGE}.load_utils import chunked


        def load_rows() -> None:
            from {MN_PACKAGE}.scraper.load import load_rows as mn_load_rows

            mn_load_rows()
        """,
        region_roots,
    )

    assert [
        (classification.line_number, classification.kind, classification.imported_module)
        for classification in classifications
    ] == [
        (1, NON_REGION_IMPORT, f"{STATES_PACKAGE}.load_utils"),
        (5, CROSS_REGION_IMPORT, f"{MN_PACKAGE}.scraper.load"),
    ]
    assert {classification.file_path for classification in classifications} == {tmp_path / CA_LOAD_RELATIVE_PATH}


def test_multi_alias_from_import_yields_one_classification_per_module(
    tmp_path: Path,
    region_roots: tuple[RegionRoot, ...],
) -> None:
    classifications = _classify_specimen(
        tmp_path,
        CA_LOAD_RELATIVE_PATH,
        f"""
        from {MN_PACKAGE}.scraper.parse import parse_contributions, parse_expenditures
        from {STATES_PACKAGE} import MN, WA
        """,
        region_roots,
    )

    assert [classification.imported_module for classification in classifications] == [
        f"{MN_PACKAGE}.scraper.parse",
        MN_PACKAGE,
        f"{STATES_PACKAGE}.WA",
    ]
    assert all(classification.kind == CROSS_REGION_IMPORT for classification in classifications)


def test_relative_import_escaping_the_naming_root_is_rejected(
    tmp_path: Path,
    region_roots: tuple[RegionRoot, ...],
) -> None:
    with pytest.raises(ValueError, match="escapes the naming root"):
        _classify_specimen(
            tmp_path,
            CA_LOAD_RELATIVE_PATH,
            """
            from ........... import something
            """,
            region_roots,
        )


# --------------------------------------------------------------------------
# Live repository policy
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "classification",
    (
        _make_classification(
            (
                "domains/campaign_finance/jurisdictions/states/CA/scraper/load.py",
                f"{CA_PACKAGE}.scraper.load",
                f"{MN_PACKAGE}.scraper.parse",
            ),
            line_number=12,
            importing_region_root=CA_PACKAGE,
            imported_region_root=MN_PACKAGE,
            kind=CROSS_REGION_IMPORT,
        ),
        _make_classification(
            (
                "domains/campaign_finance/quality/unapproved.py",
                "domains.campaign_finance.quality.unapproved",
                f"{CA_PACKAGE}.scraper.load",
            ),
            line_number=7,
            importing_region_root=None,
            imported_region_root=CA_PACKAGE,
            kind=INBOUND_REGION_IMPORT,
        ),
    ),
)
def test_live_policy_rejects_boundary_violations_with_complete_diagnostic(
    classification: ImportClassification,
) -> None:
    expected_location = f"{classification.file_path.relative_to(REPO_ROOT).as_posix()}:{classification.line_number}"

    violations = find_import_boundary_policy_violations((classification,), REPO_ROOT)
    diagnostic = format_import_boundary_policy_violations(violations, REPO_ROOT)

    assert violations == (classification,)
    for expected_detail in (
        expected_location,
        f"importing_module={classification.importing_module}",
        f"imported_module={classification.imported_module}",
        f"importing_region_root={classification.importing_region_root}",
        f"imported_region_root={classification.imported_region_root}",
    ):
        assert expected_detail in diagnostic


def test_accepted_inbound_reconciliation_rejects_unaccepted_observed_inbound(tmp_path: Path) -> None:
    unaccepted_key = (
        "domains/campaign_finance/quality/unapproved.py",
        "domains.campaign_finance.quality.unapproved",
        f"{CA_PACKAGE}.scraper.load",
    )
    classification = _make_classification(
        unaccepted_key,
        line_number=7,
        importing_region_root=None,
        imported_region_root=CA_PACKAGE,
        kind=INBOUND_REGION_IMPORT,
    )

    mismatch = find_accepted_inbound_import_mismatch((classification,), REPO_ROOT)

    assert unaccepted_key in mismatch.unexpected_observed

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    accepted_untracked_key = next(iter(_ACCEPTED_INBOUND_IMPORT_DEBT))
    accepted_untracked_classification = ImportClassification(
        file_path=tmp_path / accepted_untracked_key[0],
        line_number=1,
        importing_module=accepted_untracked_key[1],
        imported_module=accepted_untracked_key[2],
        importing_region_root=None,
        imported_region_root=f"{STATES_PACKAGE}.NC",
        kind=INBOUND_REGION_IMPORT,
    )

    policy_violations = find_import_boundary_policy_violations((accepted_untracked_classification,), tmp_path)
    accepted_mismatch = find_accepted_inbound_import_mismatch((accepted_untracked_classification,), tmp_path)

    assert policy_violations == ()
    assert accepted_mismatch.unexpected_observed == frozenset()


def test_accepted_inbound_reconciliation_rejects_tracked_stale_debt() -> None:
    classifications = scan_repository_imports(REPO_ROOT)
    observed_accepted_keys = {
        _policy_key(classification, REPO_ROOT)
        for classification in classifications
        if classification.kind == INBOUND_REGION_IMPORT
    } & _DEFAULT_ACCEPTED_INBOUND_IMPORTS
    stale_key = sorted(observed_accepted_keys)[0]

    mismatch = find_accepted_inbound_import_mismatch(
        tuple(
            classification for classification in classifications if _policy_key(classification, REPO_ROOT) != stale_key
        ),
        REPO_ROOT,
    )

    assert stale_key in mismatch.missing_accepted


def test_projected_public_repository_reconciles_absent_untracked_accepted_debt(tmp_path: Path) -> None:
    projected_root = _public_locality_repo_root(tmp_path)
    debt_key = next(iter(_ACCEPTED_INBOUND_IMPORT_DEBT))

    assert not (projected_root / debt_key[0]).exists()

    classifications = scan_repository_imports(projected_root)
    mismatch = find_accepted_inbound_import_mismatch(classifications, projected_root)

    assert mismatch == AcceptedInboundImportMismatch(frozenset(), frozenset())


def test_live_repository_respects_jurisdiction_import_boundary() -> None:
    classifications = scan_repository_imports(REPO_ROOT)
    violations = find_import_boundary_policy_violations(classifications, REPO_ROOT)
    mismatch = find_accepted_inbound_import_mismatch(classifications, REPO_ROOT)

    assert violations == (), format_import_boundary_policy_violations(violations, REPO_ROOT)
    assert mismatch == AcceptedInboundImportMismatch(frozenset(), frozenset())
