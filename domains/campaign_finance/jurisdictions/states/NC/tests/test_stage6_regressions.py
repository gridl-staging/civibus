from __future__ import annotations

from pathlib import Path

from _test_helpers import (
    assert_ascii_crlf_without_bom,
    assert_files_exist,
    csv_headers,
    extract_named_block,
    nested_keys,
    read,
    scalar_value,
    shared_data_source_scalar,
    source_block_by_name,
)
from test_office_class_fixture_inventory import _in_scope_rows
from test_office_universe_inventory import EVIDENCE_TOKEN_BY_FIXTURE_SLUG

REPO_ROOT = Path(__file__).resolve().parents[6]
NC_DIR = REPO_ROOT / "domains" / "campaign_finance" / "jurisdictions" / "states" / "NC"
CONFIG_PATH = NC_DIR / "config.yaml"
README_PATH = NC_DIR / "README.md"
LAWS_PATH = NC_DIR / "laws.md"
SEMANTICS_PATH = NC_DIR / "data_semantics.md"
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
TRANSACTION_EXPORT_FIXTURE = FIXTURE_DIR / "transaction_export_sample.csv"
COMMITTEE_DOC_EXPORT_FIXTURE = FIXTURE_DIR / "committee_document_export_sample.csv"
TRANSACTION_SOURCE_NAME = "North Carolina SBoE Transaction Search"
COMMITTEE_DOC_SOURCE_NAME = "North Carolina SBoE Committee/Document Search"


EXPECTED_COVERAGE_EXAMPLES = [
    "ADAMS FOR NC HOUSE",
    "GALE ADCOCK FOR NC SENATE",
    "JOHN ADCOCK FOR COUNTY COMMISSIONER",
    "JASON MERRILL FOR CARRBORO TOWN COUNCIL",
    "RICHARD N ADAMS FOR DIST CT JUDGE",
]


def assert_statewide_source_coverage_contract(source_block: str) -> None:
    coverage_block = extract_named_block(source_block, "coverage")

    assert 'format: "web_portal"' in source_block
    assert "bulk_download_url: null" in source_block
    assert "api_base_url: null" in source_block
    assert "auth_required: false" in source_block
    assert "covers_sub_jurisdictions: true" in coverage_block
    assert "- state_house" in coverage_block
    assert "- state_senate" in coverage_block
    assert "- county" in coverage_block
    assert "- municipal" in coverage_block
    assert "- judicial" in coverage_block
    assert "- contributions" in coverage_block
    assert "- expenditures" in coverage_block
    assert "- loans" in coverage_block


def test_stage6_nc_files_and_fixtures_exist():
    assert_files_exist(
        CONFIG_PATH,
        README_PATH,
        LAWS_PATH,
        SEMANTICS_PATH,
        TRANSACTION_EXPORT_FIXTURE,
        COMMITTEE_DOC_EXPORT_FIXTURE,
    )


def test_transaction_source_is_query_driven_web_portal_without_bulk_or_api_contract():
    config_text = read(CONFIG_PATH)
    source_block = source_block_by_name(config_text, TRANSACTION_SOURCE_NAME)

    assert_statewide_source_coverage_contract(source_block)
    assert "No official bulk-download file or public API endpoint was found" in source_block


def test_field_mappings_keys_match_observed_transaction_csv_headers():
    source_block = source_block_by_name(read(CONFIG_PATH), TRANSACTION_SOURCE_NAME)
    assert nested_keys(source_block, "field_mappings") == csv_headers(TRANSACTION_EXPORT_FIXTURE)


def test_statewide_package_declares_sub_jurisdiction_coverage_and_target_office_levels():
    source_block = source_block_by_name(read(CONFIG_PATH), TRANSACTION_SOURCE_NAME)
    assert_statewide_source_coverage_contract(source_block)


def test_docs_lock_coverage_examples_used_to_prove_all_in_scope_office_classes():
    readme_text = read(README_PATH)
    semantics_text = read(SEMANTICS_PATH)

    for expected_example in EXPECTED_COVERAGE_EXAMPLES:
        assert expected_example in readme_text
        assert expected_example in semantics_text


def test_semantics_documents_search_workflows_paging_and_export_endpoints():
    semantics_text = read(SEMANTICS_PATH)

    assert "/CFTxnLkup/TxnSearchResults/" in semantics_text
    assert "/CFTxnLkup/GetPagedResults?page={page}&pageSize={page_size}" in semantics_text
    assert "pageSize: 500" in semantics_text
    assert "/CFTxnLkup/ExportResults/" in semantics_text
    assert "/CFOrgLkup/CommitteeGeneralResult/" in semantics_text
    assert "/CFOrgLkup/DocumentGeneralResult/?SID={SBoEID}&OGID={OrgGroupID}" in semantics_text
    assert "/CFOrgLkup/ExportSearchResults/?OGID={OrgGroupID}&Title={title}&Type=DocGen" in semantics_text


def test_semantics_documents_stable_identifier_join_between_transaction_and_document_views():
    semantics_text = read(SEMANTICS_PATH)

    assert "Committee SBoE ID" in semantics_text
    assert "SBoE ID" in semantics_text
    assert "cross-view stable identifier" in semantics_text


def test_laws_structured_values_match_stage6_statutory_findings():
    config_text = read(CONFIG_PATH)

    assert (
        'source_url: "https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_163/GS_163-278.13.html"'
        in config_text
    )
    assert "individual_to_candidate: 6800" in config_text
    assert "pac_to_candidate: 6800" in config_text
    assert 'corporate_direct: "prohibited"' in config_text
    assert 'union_direct: "prohibited"' in config_text
    assert 'party_to_candidate: "unlimited"' in config_text
    assert "itemization_threshold: 50" in config_text
    assert 'electronic_filing_required: "required"' in config_text
    assert "public_financing: false" in config_text


def test_laws_doc_cites_statutes_and_board_guidance_for_limits_thresholds_and_efiling():
    laws_text = read(LAWS_PATH)

    assert (
        "https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_163/GS_163-278.13.html" in laws_text
    )
    assert (
        "https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_163/GS_163-278.11.html" in laws_text
    )
    assert "https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_163/GS_163-278.9.html" in laws_text
    assert (
        "https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_163/GS_163-278.15.html" in laws_text
    )
    assert "https://www.ncsbe.gov/campaign-finance/campaign-finance-reporting-software" in laws_text


def test_readme_records_last_verified_date_and_reverification_steps():
    config_text = read(CONFIG_PATH)
    readme_text = read(README_PATH)
    source_verified = shared_data_source_scalar(config_text, "last_verified_working")
    laws_verified = scalar_value(extract_named_block(config_text, "laws"), "last_verified")

    assert f"Source access and workflow verified: {source_verified}" in readme_text
    assert f"Laws research verified: {laws_verified}" in readme_text
    assert "Re-verify by running a transaction search" in readme_text
    assert "Re-run committee/document evidence checks" in readme_text


def test_committee_doc_field_mappings_keys_match_observed_csv_headers():
    source_block = source_block_by_name(read(CONFIG_PATH), COMMITTEE_DOC_SOURCE_NAME)
    assert nested_keys(source_block, "field_mappings") == csv_headers(COMMITTEE_DOC_EXPORT_FIXTURE)


def test_committee_doc_source_preserves_statewide_coverage_and_per_committee_export_constraints():
    source_block = source_block_by_name(read(CONFIG_PATH), COMMITTEE_DOC_SOURCE_NAME)

    assert_statewide_source_coverage_contract(source_block)
    assert "Document export (`Type=DocGen`) is per-committee list export only" in source_block
    assert "no statewide bulk document-index export path was found" in source_block


def test_nc_fixtures_are_ascii_and_crlf_terminated_without_bom():
    assert_ascii_crlf_without_bom(TRANSACTION_EXPORT_FIXTURE)
    assert_ascii_crlf_without_bom(COMMITTEE_DOC_EXPORT_FIXTURE)


def test_readme_documents_role_splitting_known_limitation():
    readme_text = read(README_PATH)

    assert "role-splitting" in readme_text.lower() or "role splitting" in readme_text.lower()
    assert "participant.*" in readme_text or "participant." in readme_text
    assert "Transction Type" in readme_text


def test_config_field_mappings_use_participant_paths_for_role_ambiguous_fields():
    config_text = read(CONFIG_PATH)
    source_block = source_block_by_name(config_text, TRANSACTION_SOURCE_NAME)
    field_mappings_block = extract_named_block(source_block, "field_mappings")

    # These fields currently map to generic participant.* paths (not role-specific)
    assert '"participant.name"' in field_mappings_block
    assert '"participant.address.street1"' in field_mappings_block
    assert '"participant.occupation"' in field_mappings_block
    assert '"participant.employer_or_business"' in field_mappings_block


def test_coverage_examples_match_stage1_evidence_tokens():
    in_scope = _in_scope_rows()
    stage1_office_classes = {row["office_class"] for row in in_scope}
    stage1_tokens = set(EVIDENCE_TOKEN_BY_FIXTURE_SLUG.values())

    assert set(EXPECTED_COVERAGE_EXAMPLES) == stage1_tokens, (
        f"EXPECTED_COVERAGE_EXAMPLES must match Stage 1 evidence tokens exactly; "
        f"missing={stage1_tokens - set(EXPECTED_COVERAGE_EXAMPLES)}, "
        f"extra={set(EXPECTED_COVERAGE_EXAMPLES) - stage1_tokens}"
    )
    assert len(stage1_office_classes) == len(EXPECTED_COVERAGE_EXAMPLES), (
        f"one evidence token per in-scope office class; "
        f"classes={len(stage1_office_classes)}, examples={len(EXPECTED_COVERAGE_EXAMPLES)}"
    )


def test_readme_names_per_class_proof_test_path():
    readme_text = read(README_PATH)
    assert "tests/test_office_class_coverage.py" in readme_text, (
        "README must reference tests/test_office_class_coverage.py as the per-class proof owner"
    )


def test_readme_states_committee_document_level_classification():
    readme_text = read(README_PATH)
    assert "committee-document level" in readme_text, (
        "README must state that office-level classification is proven at the committee-document level"
    )
