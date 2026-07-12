from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Literal, TypeAlias

import yaml
from pydantic import BaseModel, ConfigDict, StrictInt, ValidationError


JurisdictionTypeLiteral = Literal["federal", "state", "county", "municipality"]
DataSourceFormatLiteral = Literal["csv", "api", "web_portal", "pdf", "pipe_delimited"]
UpdateFrequencyLiteral = Literal["continuous", "daily", "weekly", "monthly", "quarterly", "annual"]
ElectronicFilingRequiredLiteral = Literal["required", "not_required", "voluntary", "paper_only"]
StatusValueLiteral = Literal["pending", "in_progress", "complete", "working", "partial", "broken", "unknown"]
StrictIntegerValue: TypeAlias = StrictInt
ContributionLimitValue: TypeAlias = StrictIntegerValue | Literal["unlimited", "prohibited"] | None


class JurisdictionConfigBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class JurisdictionIdentity(JurisdictionConfigBaseModel):
    name: str
    code: str
    type: JurisdictionTypeLiteral
    fips: str
    parent: str | None


class DataSourceCoverageConfig(JurisdictionConfigBaseModel):
    start_year: StrictIntegerValue
    covers_sub_jurisdictions: bool
    office_levels: list[str]
    transaction_types: list[str]


class DataSourceConfig(JurisdictionConfigBaseModel):

    name: str
    url: str
    date_start_selector: str | None = None
    date_end_selector: str | None = None
    bulk_download_url: str | None
    api_base_url: str | None
    format: DataSourceFormatLiteral
    auth_required: bool
    update_frequency: UpdateFrequencyLiteral
    coverage: DataSourceCoverageConfig
    field_mappings: dict[str, str]
    scraper: str | None
    last_successful_pull: date | None
    last_verified_working: date | None
    known_issues: list[str]


class ContributionLimitsConfig(JurisdictionConfigBaseModel):
    individual_to_candidate: ContributionLimitValue
    pac_to_candidate: ContributionLimitValue
    corporate_direct: ContributionLimitValue
    union_direct: ContributionLimitValue
    party_to_candidate: ContributionLimitValue


class ReportingConfig(JurisdictionConfigBaseModel):
    periods: list[str]
    electronic_filing_required: ElectronicFilingRequiredLiteral


class PublicFinancingConfig(JurisdictionConfigBaseModel):
    type: str
    administering_agency: str


class LawsConfig(JurisdictionConfigBaseModel):
    source_url: str
    last_verified: date | None
    contribution_limits: ContributionLimitsConfig
    itemization_threshold: StrictIntegerValue
    reporting: ReportingConfig
    public_financing: Literal[False] | PublicFinancingConfig
    notes: list[str]


class StatusConfig(JurisdictionConfigBaseModel):
    discovery: StatusValueLiteral
    scraper: StatusValueLiteral
    normalization: StatusValueLiteral
    entity_resolution: StatusValueLiteral
    last_full_update: date | None


class JurisdictionConfig(JurisdictionConfigBaseModel):
    jurisdiction: JurisdictionIdentity
    data_sources: list[DataSourceConfig]
    laws: LawsConfig
    status: StatusConfig


def _format_validation_errors(validation_error: ValidationError) -> str:
    formatted_errors: list[str] = []
    for error in validation_error.errors():
        location = ".".join(str(part) for part in error["loc"])
        if not location:
            location = "<root>"
        formatted_errors.append(f"{location}: {error['msg']}")
    return "; ".join(formatted_errors)


def _format_yaml_error(config_path: Path, error: yaml.YAMLError) -> str:
    problem_mark = getattr(error, "problem_mark", None)
    if problem_mark is None:
        return f"Failed to parse YAML jurisdiction config at {config_path}: {error}"

    location = f"line {problem_mark.line + 1}, column {problem_mark.column + 1}"
    return f"Failed to parse YAML jurisdiction config at {config_path} ({location}): {error}"


def _load_raw_config(config_path: Path) -> object:
    try:
        with config_path.open("r", encoding="utf-8") as config_file:
            return yaml.safe_load(config_file)
    except OSError as error:
        raise ValueError(f"Failed to read jurisdiction config at {config_path}: {error}") from error
    except yaml.YAMLError as error:
        raise ValueError(_format_yaml_error(config_path, error)) from error


def load_jurisdiction_config(path: str | Path) -> JurisdictionConfig:
    config_path = Path(path)
    raw_config = _load_raw_config(config_path)

    try:
        return JurisdictionConfig.model_validate(raw_config)
    except ValidationError as error:
        details = _format_validation_errors(error)
        raise ValueError(f"Invalid jurisdiction config at {config_path}: {details}") from error


def discover_jurisdiction_configs(base_path: str | Path) -> list[Path]:
    search_root = Path(base_path)
    if (search_root / "domains" / "campaign_finance" / "jurisdictions").exists():
        search_root = search_root / "domains" / "campaign_finance" / "jurisdictions"

    config_paths = [
        config_path.resolve()
        for config_path in search_root.glob("**/config.yaml")
        if "_template" not in config_path.parts
    ]
    return sorted(config_paths)


__all__ = [
    "DataSourceConfig",
    "DataSourceCoverageConfig",
    "JurisdictionConfig",
    "JurisdictionIdentity",
    "LawsConfig",
    "PublicFinancingConfig",
    "ReportingConfig",
    "StatusConfig",
    "discover_jurisdiction_configs",
    "load_jurisdiction_config",
]
