from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[5]

from _test_helpers import YAML_KEY_LINE, assert_files_exist, extract_named_block, extract_source_blocks, read  # noqa: E402

TEMPLATE_DIR = REPO_ROOT / "domains" / "campaign_finance" / "jurisdictions" / "_template"
CONFIG_PATH = TEMPLATE_DIR / "config.yaml"
README_PATH = TEMPLATE_DIR / "README.md"
LAWS_PATH = TEMPLATE_DIR / "laws.md"
SEMANTICS_PATH = TEMPLATE_DIR / "data_semantics.md"
SPEC_PATH = REPO_ROOT / "docs" / "reference" / "specs" / "jurisdiction-config.md"


def load_spec_example_text() -> str:
    match = re.search(r"```yaml\n(.*?)\n```", read(SPEC_PATH), re.DOTALL)
    if match is None:
        raise AssertionError(f"expected YAML example block in {SPEC_PATH}")
    return match.group(1)


def assert_block_contains(block: str, required_keys: list[str]) -> None:
    active_keys = {match.group(1) for match in (YAML_KEY_LINE.match(line) for line in block.splitlines()) if match}

    for key in required_keys:
        assert key.removesuffix(":") in active_keys


def assert_data_source_shape(config_text: str) -> None:
    source_blocks = extract_source_blocks(config_text)
    assert len(source_blocks) >= 2

    required_source_keys = [
        "name:",
        "url:",
        "bulk_download_url:",
        "api_base_url:",
        "format:",
        "auth_required:",
        "update_frequency:",
        "coverage:",
        "field_mappings:",
        "scraper:",
        "last_successful_pull:",
        "last_verified_working:",
        "known_issues:",
    ]
    required_coverage_keys = ["start_year:", "covers_sub_jurisdictions:", "office_levels:", "transaction_types:"]
    formats: set[str] = set()

    for source_block in source_blocks:
        assert_block_contains(source_block, required_source_keys)
        coverage_block = extract_named_block(source_block, "coverage")
        assert_block_contains(coverage_block, required_coverage_keys)
        format_match = re.search(r'format:\s*"([^"]+)"', source_block)
        if format_match is not None:
            formats.add(format_match.group(1))

    assert {"csv", "web_portal"} <= formats


def assert_laws_shape(config_text: str) -> None:
    laws_block = extract_named_block(config_text, "laws")
    assert_block_contains(
        laws_block,
        [
            "source_url:",
            "last_verified:",
            "contribution_limits:",
            "itemization_threshold:",
            "reporting:",
            "public_financing:",
            "notes:",
        ],
    )

    contribution_limits_block = extract_named_block(laws_block, "contribution_limits")
    assert_block_contains(
        contribution_limits_block,
        [
            "individual_to_candidate:",
            "pac_to_candidate:",
            "corporate_direct:",
            "union_direct:",
            "party_to_candidate:",
        ],
    )

    reporting_block = extract_named_block(laws_block, "reporting")
    assert_block_contains(reporting_block, ["periods:", "electronic_filing_required:"])
    assert re.search(r"periods:\s*\[[^\]]+\]", reporting_block)
    public_financing_block = extract_named_block(laws_block, "public_financing")
    assert "false" in public_financing_block or "administering_agency" in {
        match.group(1) for match in (YAML_KEY_LINE.match(line) for line in public_financing_block.splitlines()) if match
    }


def assert_reconciled_schema_shape(config_text: str) -> None:
    jurisdiction_block = extract_named_block(config_text, "jurisdiction")
    assert_block_contains(jurisdiction_block, ["name:", "code:", "type:", "fips:", "parent:"])
    assert_data_source_shape(config_text)
    assert_laws_shape(config_text)
    status_block = extract_named_block(config_text, "status")
    assert_block_contains(
        status_block,
        ["discovery:", "scraper:", "normalization:", "entity_resolution:", "last_full_update:"],
    )


def uncommented_active_yaml_fields(text: str) -> list[str]:
    missing_comments: list[str] = []
    field_mappings_indent: int | None = None

    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue

        indent = len(line) - len(line.lstrip(" "))
        if field_mappings_indent is not None and indent <= field_mappings_indent:
            field_mappings_indent = None

        match = YAML_KEY_LINE.match(line)
        if match is None:
            continue

        key = match.group(1)
        if field_mappings_indent is not None and indent > field_mappings_indent:
            continue
        if key == "field_mappings":
            field_mappings_indent = indent

        if "#" not in line:
            missing_comments.append(line.strip())

    return missing_comments


def test_config_and_source_sections_exist():
    assert_files_exist(CONFIG_PATH, README_PATH, LAWS_PATH, SEMANTICS_PATH)


def test_config_includes_reconciled_fields():
    assert_reconciled_schema_shape(read(CONFIG_PATH))


def test_laws_shape_requires_live_public_financing_field():
    text = read(CONFIG_PATH).replace("  public_financing: false # live default in template\n", "")

    try:
        assert_laws_shape(text)
    except AssertionError:
        return

    raise AssertionError("expected commented public_financing example to not satisfy live laws contract")


def test_config_field_schema_not_present_and_field_mappings_used():
    text = read(CONFIG_PATH)

    assert "field_schema:" not in text
    assert all("field_mappings:" in source_block for source_block in extract_source_blocks(text))
    assert "field_schema -> field_mappings" in text


def test_template_uses_two_data_source_formats():
    formats = set(re.findall(r'format:\s*"([^"]+)"', read(CONFIG_PATH)))
    assert {"csv", "web_portal"} <= formats


def test_config_includes_reconciled_enum_comments():
    text = read(CONFIG_PATH)
    assert "federal | state | county | municipality" in text
    assert "csv | api | web_portal | pdf | pipe_delimited" in text
    assert "continuous | daily | weekly | monthly | quarterly | annual" in text
    assert "pending | in_progress | complete | working | partial | broken | unknown" in text


def test_template_documents_every_active_schema_field_inline():
    missing_comments = uncommented_active_yaml_fields(read(CONFIG_PATH))
    assert not missing_comments, f"missing inline comment guidance: {missing_comments}"


def test_laws_doc_has_required_sections():
    text = read(LAWS_PATH)
    required_sections = [
        "## Authoritative source",
        "## Contribution limits table",
        "## Itemization threshold",
        "## Reporting periods and deadlines",
        "## Expected filing obligations / completeness cues",
        "## Prohibitions",
        "## Public financing",
        "## Known ambiguities / recent changes",
        "## Office-level or election-type variation",
    ]
    for section in required_sections:
        assert section in text


def test_readme_has_required_sections():
    text = read(README_PATH)
    required_sections = [
        "## Acquisition pattern",
        "## Preliminary online research",
        "## Interactive exploration / contract discovery",
        "## Jurisdiction overview",
        "## Data sources summary",
        "## Coverage notes",
        "## Known data quality issues",
        "## Last verified date",
        "## Current lifecycle status",
        "## Evidence artifacts",
        "## Update instructions",
    ]
    for section in required_sections:
        assert section in text


def test_data_semantics_has_required_sections_and_portal_navigation():
    text = read(SEMANTICS_PATH)
    required_sections = [
        "## Acquisition contract summary",
        "## Date fields",
        "## Name formats",
        "## Employer/occupation",
        "## Address format",
        "## Committee IDs",
        "## Amendment handling",
        "## Missing/null conventions",
        "## Interactive Exploration / Contract Discovery",
    ]
    for section in required_sections:
        assert section in text


def test_data_source_nullability_is_explicit():
    text = read(CONFIG_PATH)
    assert "api_base_url: null" in text
    assert "bulk_download_url: null" in text
    assert "last_successful_pull: null" in text
    assert "last_verified_working: null" in text
    assert "party_to_candidate: null" in text
    # The config must document the omit-vs-null resolution (case/punctuation flexible)
    assert "omit" in text.lower() and "not applicable" in text.lower()


def test_spec_example_matches_reconciled_template_shape():
    assert_reconciled_schema_shape(load_spec_example_text())
