from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
import yaml

from domains.campaign_finance.jurisdictions.config_schema import (
    JurisdictionConfig,
    PublicFinancingConfig,
    discover_jurisdiction_configs,
    load_jurisdiction_config,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
JURISDICTIONS_DIR = REPO_ROOT / "domains" / "campaign_finance" / "jurisdictions"
TEMPLATE_CONFIG_PATH = JURISDICTIONS_DIR / "_template" / "config.yaml"
SF_CONFIG_PATH = JURISDICTIONS_DIR / "cities" / "SF" / "config.yaml"
CO_CONFIG_PATH = JURISDICTIONS_DIR / "states" / "CO" / "config.yaml"
GA_CONFIG_PATH = JURISDICTIONS_DIR / "states" / "GA" / "config.yaml"
NC_CONFIG_PATH = JURISDICTIONS_DIR / "states" / "NC" / "config.yaml"
PILOT_CONFIG_PATHS = [
    CO_CONFIG_PATH,
    GA_CONFIG_PATH,
    NC_CONFIG_PATH,
]
EXPANDED_CONFIG_PATHS = [JURISDICTIONS_DIR / "cities" / code / "config.yaml" for code in ("LA", "NYC", "PHL", "SF")] + [
    JURISDICTIONS_DIR / "states" / code / "config.yaml"
    for code in (
        "AL",
        "CA",
        "CO",
        "FL",
        "GA",
        "IL",
        "IN",
        "KY",
        "LA",
        "MA",
        "MN",
        "NC",
        "NE",
        "NJ",
        "NY",
        "OH",
        "OR",
        "PA",
        "TX",
        "VA",
        "WA",
        "WI",
    )
]


@pytest.mark.parametrize("config_path", PILOT_CONFIG_PATHS)
def test_load_jurisdiction_config_loads_each_pilot(config_path: Path) -> None:
    config = load_jurisdiction_config(config_path)

    assert isinstance(config, JurisdictionConfig)
    assert config.jurisdiction.code in {"CO", "GA", "NC"}


def test_load_jurisdiction_config_loads_san_francisco_city_config() -> None:
    config = load_jurisdiction_config(SF_CONFIG_PATH)

    assert isinstance(config, JurisdictionConfig)
    assert config.jurisdiction.type == "municipality"
    assert config.jurisdiction.parent == "CA"
    assert config.jurisdiction.code == "SF"
    assert config.laws.contribution_limits.corporate_direct == "prohibited"
    assert config.laws.contribution_limits.union_direct == 500


def test_discover_jurisdiction_configs_returns_sorted_non_template_paths() -> None:
    discovered_paths = discover_jurisdiction_configs(JURISDICTIONS_DIR)

    assert discovered_paths == sorted(EXPANDED_CONFIG_PATHS)
    assert TEMPLATE_CONFIG_PATH not in discovered_paths


def test_nested_extra_field_raises_validation_error_with_extra_forbid(tmp_path: Path) -> None:
    invalid_config_path = tmp_path / "invalid_extra_field_config.yaml"
    base_text = PILOT_CONFIG_PATHS[0].read_text(encoding="utf-8")
    invalid_text = base_text.replace(
        "covers_sub_jurisdictions: true",
        "covers_sub_jurisdictions: true\n      unexpected_flag: true",
        1,
    )
    invalid_config_path.write_text(invalid_text, encoding="utf-8")

    with pytest.raises(ValueError, match=r"extra fields not permitted|Extra inputs are not permitted"):
        load_jurisdiction_config(invalid_config_path)


@pytest.mark.parametrize(
    ("field_path", "expected_error_location"),
    [
        (("data_sources", 0, "coverage", "start_year"), "data_sources.0.coverage.start_year"),
        (("laws", "itemization_threshold"), "laws.itemization_threshold"),
        (
            ("laws", "contribution_limits", "individual_to_candidate"),
            "laws.contribution_limits.individual_to_candidate",
        ),
    ],
)
def test_boolean_values_are_rejected_for_integer_fields(
    tmp_path: Path,
    field_path: tuple[str | int, ...],
    expected_error_location: str,
) -> None:
    invalid_config_path = tmp_path / f"invalid_{expected_error_location.replace('.', '_')}.yaml"
    config_data = yaml.safe_load(PILOT_CONFIG_PATHS[0].read_text(encoding="utf-8"))
    target = config_data
    for path_part in field_path[:-1]:
        target = target[path_part]
    target[field_path[-1]] = False

    invalid_config_path.write_text(
        yaml.safe_dump(config_data, sort_keys=False),
        encoding="utf-8",
    )

    with pytest.raises(ValueError) as validation_error:
        load_jurisdiction_config(invalid_config_path)

    validation_message = str(validation_error.value)
    assert expected_error_location in validation_message
    assert "valid integer" in validation_message


def test_load_jurisdiction_config_reports_path_and_error_locations(tmp_path: Path) -> None:
    invalid_model_path = tmp_path / "invalid_model_config.yaml"
    invalid_model_text = (
        PILOT_CONFIG_PATHS[0]
        .read_text(encoding="utf-8")
        .replace(
            "covers_sub_jurisdictions: true",
            "covers_sub_jurisdictions: true\n      unexpected_flag: true",
            1,
        )
    )
    invalid_model_path.write_text(invalid_model_text, encoding="utf-8")

    invalid_yaml_path = tmp_path / "invalid_yaml_config.yaml"
    invalid_yaml_path.write_text("jurisdiction: [\n", encoding="utf-8")

    with pytest.raises(ValueError) as validation_error:
        load_jurisdiction_config(invalid_model_path)

    validation_message = str(validation_error.value)
    assert str(invalid_model_path) in validation_message
    assert "data_sources.0.coverage.unexpected_flag" in validation_message

    with pytest.raises(ValueError) as parsing_error:
        load_jurisdiction_config(invalid_yaml_path)

    parsing_message = str(parsing_error.value)
    assert str(invalid_yaml_path) in parsing_message
    assert "line" in parsing_message.lower()


def test_public_financing_accepts_false_and_required_object_shape(tmp_path: Path) -> None:
    config_with_object_path = tmp_path / "public_financing_object.yaml"
    object_config_text = (
        PILOT_CONFIG_PATHS[0]
        .read_text(encoding="utf-8")
        .replace(
            "  public_financing: false",
            '  public_financing:\n    type: "matching_funds"\n    administering_agency: "State Elections Office"',
            1,
        )
    )
    config_with_object_path.write_text(object_config_text, encoding="utf-8")

    false_config = load_jurisdiction_config(PILOT_CONFIG_PATHS[0])
    object_config = load_jurisdiction_config(config_with_object_path)

    assert false_config.laws.public_financing is False
    assert isinstance(object_config.laws.public_financing, PublicFinancingConfig)
    assert object_config.laws.public_financing.type == "matching_funds"
    assert object_config.laws.public_financing.administering_agency == "State Elections Office"


def test_nc_field_mappings_preserve_quoted_and_spaced_yaml_keys() -> None:
    nc_config = load_jurisdiction_config(NC_CONFIG_PATH)
    first_data_source_keys = list(nc_config.data_sources[0].field_mappings.keys())

    assert "Street Line 1" in first_data_source_keys
    assert "Employer's Name/Specific Field" in first_data_source_keys
    assert nc_config.data_sources[0].field_mappings["Street Line 1"] == "participant.address.street1"
    assert (
        nc_config.data_sources[0].field_mappings["Employer's Name/Specific Field"] == "participant.employer_or_business"
    )


@pytest.mark.parametrize("config_path", PILOT_CONFIG_PATHS)
def test_yaml_dates_parse_to_date_or_none(config_path: Path) -> None:
    config = load_jurisdiction_config(config_path)

    assert config.laws.last_verified is None or isinstance(config.laws.last_verified, date)
    assert config.status.last_full_update is None or isinstance(config.status.last_full_update, date)

    for source in config.data_sources:
        assert source.last_successful_pull is None or isinstance(source.last_successful_pull, date)
        assert source.last_verified_working is None or isinstance(source.last_verified_working, date)
