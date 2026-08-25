from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Annotated, Literal, TypeAlias

import yaml
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StringConstraints, ValidationError


JurisdictionTypeLiteral = Literal["federal", "state", "county", "municipality"]
DataSourceFormatLiteral = Literal["csv", "api", "web_portal", "pdf", "pipe_delimited"]
UpdateFrequencyLiteral = Literal["continuous", "daily", "weekly", "monthly", "quarterly", "annual"]
ElectronicFilingRequiredLiteral = Literal["required", "not_required", "voluntary", "paper_only"]
StatusValueLiteral = Literal["pending", "in_progress", "complete", "working", "partial", "broken", "unknown"]
StrictIntegerValue: TypeAlias = StrictInt
ContributionLimitValue: TypeAlias = StrictIntegerValue | Literal["unlimited", "prohibited"] | None
NonBlankText: TypeAlias = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

# Closed vocabularies for the structured legal rules in ``laws.contribution_limit_rules``
# (docs/reference/specs/jurisdiction-config.md, "Rule identity and dimensions"). They are
# seeded lists: a newly researched office or donor class requires a spec change before it
# can appear in a rule. They deliberately do not constrain
# ``data_sources[].coverage.office_levels``, which is an unvalidated source-scope fact with
# its own owner and still carries legacy spellings.
ContributionDonorTypeLiteral = Literal[
    "individual",
    "pac",
    "party_committee",
    "corporation",
    "union",
    "small_donor_committee",
    "small_contributor_committee",
    "candidate",
    "self",
    "issue_committee",
    "ie_committee",
]
ContributionRecipientTypeLiteral = Literal[
    "candidate_committee",
    "party_committee",
    "pac",
    "issue_committee",
    "ie_committee",
    "ballot_measure_committee",
]
LegalRuleOfficeLevelLiteral = Literal[
    # Office-specific tokens. ``comptroller``, ``city_controller``, and ``state_assembly``
    # are deliberately absent: the spec names them as legacy aliases of ``controller`` and
    # ``state_house`` that remain legal only in existing source-scope coverage lists.
    "attorney_general",
    "board_of_equalization",
    "board_of_supervisors",
    "borough_president",
    "city_attorney",
    "city_commissioners",
    "city_council",
    "controller",
    "cu_regent",
    "district_attorney",
    "governor",
    "insurance_commissioner",
    "judicial",
    "lieutenant_governor",
    "mayor",
    "public_advocate",
    "register_of_wills",
    "secretary_of_state",
    "sheriff",
    "state_board_of_education",
    "state_controller",
    "state_house",
    "state_senate",
    "state_treasurer",
    "superintendent_of_public_instruction",
    # Jurisdiction/scope tokens.
    "citywide",
    "county",
    "municipal",
    "school_district",
    "special_district",
    "rtd",
    # Legal-tier tokens.
    "statewide",
    "statewide_except_governor",
    "legislative",
    "other_office",
]
ElectionTypeLiteral = Literal["primary", "general", "runoff", "special", "recall"]
ContributionLimitBasisLiteral = Literal["per_election", "per_cycle", "per_calendar_year"]


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


class ContributionRuleMetadataItem(JurisdictionConfigBaseModel):
    """One carve-out, aggregation rule, or extra prohibition attached to a single rule.

    The escape hatch for the exceptions the spec declines to type in this pass. Both
    fields are required and non-blank so an item always carries the prose *and* the
    authority it rests on, never one without the other.
    """

    description: NonBlankText
    source_citation: NonBlankText


class NoMonetaryCapAccessors:
    """Read-only ``None`` accessors for the statuses that carry no dollar cap.

    ``prohibited``, ``unlimited``, ``no_statutory_limit``, and ``unknown`` all omit the
    amount and the basis, and ``extra="forbid"`` rejects both on input. Reporting them as
    ``None`` here keeps a consumer from having to branch on ``limit_status`` just to read
    an amount that is never present.
    """

    @property
    def limit_amount(self) -> None:
        return None

    @property
    def limit_basis(self) -> None:
        return None


class ContributionLimitRuleBase(JurisdictionConfigBaseModel):
    """Fields every structured contribution rule carries, whatever its ``limit_status``.

    An omitted or ``null`` dimension means "applies to all values of that dimension".
    That is kept strictly separate from ``limit_status: unknown``, which means the rule
    itself has not been researched.
    """

    donor_type: ContributionDonorTypeLiteral | None = None
    recipient_type: ContributionRecipientTypeLiteral | None = None
    office_level: LegalRuleOfficeLevelLiteral | None = None
    election_type: ElectionTypeLiteral | None = None
    source_citation: NonBlankText
    local_override_allowed: bool = False
    metadata: list[ContributionRuleMetadataItem] = Field(default_factory=list)


class KnownContributionLimitRuleBase(ContributionLimitRuleBase):
    """A rule whose legal status is settled, so legal effectivity dates apply to it.

    ``research_observed_date`` is absent by design: it records when an *unresolved* state
    was observed, and ``extra="forbid"`` therefore rejects it on every known status.
    """

    effective_date: date
    sunset_date: date | None = None
    note: NonBlankText | None = None

    @property
    def research_observed_date(self) -> None:
        """A settled rule has no unresolved state to have observed."""
        return None


class NumericContributionLimitRule(KnownContributionLimitRuleBase):
    """A dollar cap that applies to this donor/recipient/office/election combination.

    The basis is named rather than normalized, so each statute's own number survives:
    CO's per-cycle $725 and NC's per-election $6,800 stay the amounts the statutes state.
    """

    limit_status: Literal["numeric"]
    limit_amount: StrictIntegerValue
    limit_basis: ContributionLimitBasisLiteral


class KnownNonNumericContributionLimitRule(NoMonetaryCapAccessors, KnownContributionLimitRuleBase):
    """A settled rule that carries no dollar cap, in one of three distinct meanings.

    ``prohibited`` bans the combination, ``unlimited`` means a statute affirmatively
    removed the cap, and ``no_statutory_limit`` means no cap provision was ever enacted.
    They share one model because they share one field set; the discriminator keeps the
    three meanings distinguishable, and ``extra="forbid"`` rejects the amount and basis
    that only a ``numeric`` rule may carry.
    """

    limit_status: Literal["prohibited", "unlimited", "no_statutory_limit"]


class UnknownContributionLimitRule(NoMonetaryCapAccessors, ContributionLimitRuleBase):
    """The explicit-unknown state: not yet researched, never a placeholder number.

    It carries research dates rather than legal dates, and requires a note naming the
    gap, so an unresearched rule can never be mistaken for a cap of zero or for no cap.
    """

    limit_status: Literal["unknown"]
    research_observed_date: date
    note: NonBlankText

    @property
    def effective_date(self) -> None:
        """An unresearched rule has no known legal effectivity date to report."""
        return None

    @property
    def sunset_date(self) -> None:
        """An unresearched rule cannot be known to have ceased to apply."""
        return None


ContributionLimitRule: TypeAlias = Annotated[
    NumericContributionLimitRule | KnownNonNumericContributionLimitRule | UnknownContributionLimitRule,
    Field(discriminator="limit_status"),
]


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
    contribution_limit_rules: list[ContributionLimitRule] | None = None
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
    "ContributionLimitRule",
    "ContributionLimitRuleBase",
    "ContributionLimitsConfig",
    "ContributionRuleMetadataItem",
    "DataSourceConfig",
    "DataSourceCoverageConfig",
    "JurisdictionConfig",
    "JurisdictionIdentity",
    "KnownContributionLimitRuleBase",
    "KnownNonNumericContributionLimitRule",
    "LawsConfig",
    "NoMonetaryCapAccessors",
    "NumericContributionLimitRule",
    "PublicFinancingConfig",
    "ReportingConfig",
    "StatusConfig",
    "UnknownContributionLimitRule",
    "discover_jurisdiction_configs",
    "load_jurisdiction_config",
]
