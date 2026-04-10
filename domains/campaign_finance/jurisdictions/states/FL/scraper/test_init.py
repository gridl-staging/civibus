from __future__ import annotations

from pathlib import Path

import pytest

from domains.campaign_finance.jurisdictions._test_helpers import nested_keys, read, source_block_by_name
from domains.campaign_finance.jurisdictions.states.FL.scraper import (
    _load_column_for_semantic_path,
    _load_columns_for_data_type,
    _load_data_source_name_for_data_type,
    _load_data_source_url_for_data_type,
    _load_fl_config,
    _load_fl_data_source_blocks,
    load_supported_data_types,
)

REPO_ROOT = Path(__file__).resolve().parents[6]
FL_DIR = REPO_ROOT / "domains" / "campaign_finance" / "jurisdictions" / "states" / "FL"
CONFIG_PATH = FL_DIR / "config.yaml"


def _expected_columns_from_config(source_name: str) -> tuple[str, ...]:
    config_text = read(CONFIG_PATH)
    source_block = source_block_by_name(config_text, source_name)
    return tuple(nested_keys(source_block, "field_mappings"))


def test_config_loads_successfully() -> None:
    config = _load_fl_config()

    assert config.jurisdiction.code == "FL"
    assert config.jurisdiction.name == "Florida"
    assert config.jurisdiction.type == "state"
    assert config.jurisdiction.fips == "12"


def test_data_source_blocks_include_expected_names() -> None:
    blocks = _load_fl_data_source_blocks()
    names = {block.name for block in blocks}

    assert names == {
        "FL DOS Campaign Finance - Contributions",
        "FL DOS Campaign Finance - Expenditures",
        "FL DOS Campaign Finance - Transfers",
        "FL DOS Campaign Finance - Other Disbursements",
        "FL Senate Officeholder Directory",
        "FL House Representatives Directory (Blocked in Datacenter)",
    }


def test_data_source_blocks_return_four_blocks() -> None:
    blocks = _load_fl_data_source_blocks()
    assert len(blocks) == 6


def test_supported_data_types_follow_config_order() -> None:
    assert load_supported_data_types() == (
        "contributions",
        "expenditures",
        "transfers",
        "other",
        "officeholder_directory",
        "officeholder_directory",
    )


def test_columns_for_contributions_derive_from_config_order() -> None:
    columns = _load_columns_for_data_type("contributions")

    assert columns == _expected_columns_from_config("FL DOS Campaign Finance - Contributions")


def test_columns_for_expenditures_derive_from_config_order() -> None:
    columns = _load_columns_for_data_type("expenditures")

    assert columns == _expected_columns_from_config("FL DOS Campaign Finance - Expenditures")


def test_columns_for_transfers_derive_from_config_order() -> None:
    columns = _load_columns_for_data_type("transfers")

    assert columns == _expected_columns_from_config("FL DOS Campaign Finance - Transfers")


def test_columns_for_other_derive_from_config_order() -> None:
    columns = _load_columns_for_data_type("other")

    assert columns == _expected_columns_from_config("FL DOS Campaign Finance - Other Disbursements")


def test_semantic_path_resolves_committee_name_for_contributions() -> None:
    assert _load_column_for_semantic_path("contributions", "committee.name") == "Candidate/Committee"


def test_semantic_path_resolves_donor_name_for_contributions() -> None:
    assert _load_column_for_semantic_path("contributions", "donor.name") == "Contributor Name"


def test_semantic_path_resolves_payee_name_for_expenditures() -> None:
    assert _load_column_for_semantic_path("expenditures", "payee.name") == "Payee Name"


def test_semantic_path_resolves_payee_name_for_transfers() -> None:
    assert _load_column_for_semantic_path("transfers", "payee.name") == "Funds Transferred To"


def test_semantic_path_resolves_payee_name_for_other() -> None:
    assert _load_column_for_semantic_path("other", "payee.name") == "Distributed To"


def test_data_source_name_for_data_type() -> None:
    assert _load_data_source_name_for_data_type("contributions") == "FL DOS Campaign Finance - Contributions"
    assert _load_data_source_name_for_data_type("other") == "FL DOS Campaign Finance - Other Disbursements"


def test_data_source_url_for_data_type() -> None:
    assert _load_data_source_url_for_data_type("contributions") == (
        "https://dos.elections.myflorida.com/campaign-finance/contributions/"
    )


def test_columns_for_unsupported_type_raises() -> None:
    with pytest.raises(ValueError, match="Unsupported FL data type"):
        _load_columns_for_data_type("pledges")


def test_semantic_path_for_nonexistent_path_raises() -> None:
    with pytest.raises(RuntimeError, match="No FL field mapping found"):
        _load_column_for_semantic_path("contributions", "donor.pac_fein")
