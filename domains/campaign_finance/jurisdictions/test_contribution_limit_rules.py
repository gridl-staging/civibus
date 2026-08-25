"""Loader contract for the structured ``laws.contribution_limit_rules`` block.

Extracted from ``test_config_schema.py`` so each module stays inside the repo file-size
standard and owns one contract: that module owns the whole-config reader discipline and
this one owns the structured legal-rule contract from
``docs/reference/specs/jurisdiction-config.md``. Seeds and assertion helpers are shared
through ``_contribution_rule_seeds`` rather than imported across pytest modules.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from domains.campaign_finance.jurisdictions._config_specimens import GA_CONFIG_PATH
from domains.campaign_finance.jurisdictions._contribution_rule_seeds import (
    KNOWN_NONNUMERIC_STATUSES,
    assert_limit_status_error_location,
    assert_rule_error_location,
    assert_status_rule_error,
    drop_keys,
    expect_rule_error,
    known_nonnumeric_rule,
    load_one_rule,
    load_seeded_rules,
    numeric_rule,
    unknown_rule,
)


# --- Positive: the five ``limit_status`` branches (spec "Value semantics") --------


def test_numeric_rule_loads_amount_basis_and_effective_date(tmp_path: Path) -> None:
    """GA statewide primary cap: hand-calculated 8400 / per_election / 2023-03-27."""
    rule = load_one_rule(
        tmp_path,
        {
            "donor_type": "individual",
            "recipient_type": "candidate_committee",
            "office_level": "statewide",
            "election_type": "primary",
            "limit_status": "numeric",
            "limit_amount": 8400,
            "limit_basis": "per_election",
            "effective_date": "2023-03-27",
            "source_citation": "O.C.G.A. § 21-5-41(k); Commission notice 2023-03-27",
        },
        base_path=GA_CONFIG_PATH,
    )

    assert rule.limit_status == "numeric"
    assert rule.limit_amount == 8400
    assert rule.limit_basis == "per_election"
    assert rule.effective_date == date(2023, 3, 27)
    assert rule.donor_type == "individual"
    assert rule.recipient_type == "candidate_committee"
    assert rule.office_level == "statewide"
    assert rule.election_type == "primary"


def test_prohibited_rule_loads_without_amount_or_basis(tmp_path: Path) -> None:
    rule = load_one_rule(tmp_path, known_nonnumeric_rule("prohibited"))

    assert rule.limit_status == "prohibited"
    assert rule.limit_amount is None
    assert rule.limit_basis is None
    assert rule.effective_date == date(2013, 12, 1)


def test_unlimited_rule_loads_without_amount_or_basis(tmp_path: Path) -> None:
    rule = load_one_rule(
        tmp_path,
        known_nonnumeric_rule("unlimited", donor_type="party_committee"),
    )

    assert rule.limit_status == "unlimited"
    assert rule.limit_amount is None
    assert rule.limit_basis is None


def test_no_statutory_limit_rule_loads_without_amount_or_basis(tmp_path: Path) -> None:
    rule = load_one_rule(
        tmp_path,
        known_nonnumeric_rule(
            "no_statutory_limit",
            donor_type="party_committee",
            source_citation="No explicit party-to-candidate limit in the Political Reform Act",
        ),
    )

    assert rule.limit_status == "no_statutory_limit"
    assert rule.limit_amount is None
    assert rule.limit_basis is None


def test_unknown_rule_loads_with_research_date_and_note(tmp_path: Path) -> None:
    rule = load_one_rule(tmp_path, unknown_rule())

    assert rule.limit_status == "unknown"
    assert rule.limit_amount is None
    assert rule.limit_basis is None
    assert rule.effective_date is None
    assert rule.research_observed_date == date(2026, 8, 22)
    assert rule.note.startswith("PHL local limits not yet captured")


@pytest.mark.parametrize("limit_status", ["numeric", *KNOWN_NONNUMERIC_STATUSES])
def test_known_rule_accepts_optional_sunset_date(tmp_path: Path, limit_status: str) -> None:
    """Every known-status branch preserves a repealed rule's ``sunset_date``."""
    rule_data = (
        numeric_rule(sunset_date="2013-07-01")
        if limit_status == "numeric"
        else known_nonnumeric_rule(limit_status, sunset_date="2013-07-01")
    )

    rule = load_one_rule(tmp_path, rule_data)

    assert rule.sunset_date == date(2013, 7, 1)


# --- Positive: nullable dimension semantics (spec "Rule identity and dimensions") --


def test_omitted_dimensions_load_as_none_meaning_all_values(tmp_path: Path) -> None:
    rule = load_one_rule(tmp_path, drop_keys(numeric_rule(), "office_level", "election_type"))

    assert rule.donor_type == "individual"
    assert rule.recipient_type == "candidate_committee"
    assert rule.office_level is None
    assert rule.election_type is None


def test_explicit_null_dimensions_load_as_none(tmp_path: Path) -> None:
    rule = load_one_rule(
        tmp_path,
        numeric_rule(donor_type=None, recipient_type=None, office_level=None, election_type=None),
    )

    assert rule.donor_type is None
    assert rule.recipient_type is None
    assert rule.office_level is None
    assert rule.election_type is None


def test_concrete_dimension_values_are_preserved(tmp_path: Path) -> None:
    rule = load_one_rule(
        tmp_path,
        numeric_rule(
            donor_type="pac",
            recipient_type="party_committee",
            office_level="governor",
            election_type="runoff",
        ),
    )

    assert rule.donor_type == "pac"
    assert rule.recipient_type == "party_committee"
    assert rule.office_level == "governor"
    assert rule.election_type == "runoff"


# --- Positive: closed vocabularies (spec dimension + office tables) ----------------


@pytest.mark.parametrize(
    "donor_type",
    [
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
    ],
)
def test_donor_type_vocabulary_specimens_load(tmp_path: Path, donor_type: str) -> None:
    rule = load_one_rule(tmp_path, numeric_rule(donor_type=donor_type))
    assert rule.donor_type == donor_type


@pytest.mark.parametrize(
    "recipient_type",
    [
        "candidate_committee",
        "party_committee",
        "pac",
        "issue_committee",
        "ie_committee",
        "ballot_measure_committee",
    ],
)
def test_recipient_type_vocabulary_specimens_load(tmp_path: Path, recipient_type: str) -> None:
    rule = load_one_rule(tmp_path, numeric_rule(recipient_type=recipient_type))
    assert rule.recipient_type == recipient_type


@pytest.mark.parametrize(
    "office_level",
    [
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
        "citywide",
        "county",
        "municipal",
        "school_district",
        "special_district",
        "rtd",
        "statewide",
        "statewide_except_governor",
        "legislative",
        "other_office",
    ],
)
def test_office_level_vocabulary_specimens_load(tmp_path: Path, office_level: str) -> None:
    rule = load_one_rule(tmp_path, numeric_rule(office_level=office_level))
    assert rule.office_level == office_level


@pytest.mark.parametrize("election_type", ["primary", "general", "runoff", "special", "recall"])
def test_election_type_vocabulary_specimens_load(tmp_path: Path, election_type: str) -> None:
    rule = load_one_rule(tmp_path, numeric_rule(election_type=election_type))
    assert rule.election_type == election_type


@pytest.mark.parametrize(
    ("limit_basis", "overrides"),
    [
        ("per_election", {"limit_amount": 6800, "source_citation": "N.C.G.S. § 163-278.13"}),
        (
            "per_cycle",
            {"limit_amount": 725, "office_level": "statewide", "source_citation": "Colo. Const. XXVIII § 3(1)"},
        ),
        (
            "per_calendar_year",
            {
                "limit_amount": 789060,
                "recipient_type": "party_committee",
                "source_citation": "Colo. Const. XXVIII § 3(3)",
            },
        ),
    ],
    ids=["per_election", "per_cycle", "per_calendar_year"],
)
def test_limit_basis_vocabulary_specimens_load(tmp_path: Path, limit_basis: str, overrides: dict) -> None:
    """Every ``limit_basis`` token must load unchanged (spec "Value semantics").

    The spec names the basis *instead of* normalizing amounts because CO's per-cycle $725 and
    NC's per-election $6,800 are different statutory numbers. A Stage 2
    ``Literal["per_election"]`` would accept NC and reject both CO specimens, so every token
    carries its own real statutory amount rather than sharing a placeholder.
    """
    rule = load_one_rule(
        tmp_path,
        numeric_rule(limit_basis=limit_basis, **overrides),
        filename=f"basis_{limit_basis}.yaml",
    )

    assert rule.limit_basis == limit_basis
    assert rule.limit_amount == overrides["limit_amount"]


# --- Positive: local_override_allowed and metadata (spec "Exceptions...") ----------


def test_local_override_allowed_loads_true(tmp_path: Path) -> None:
    rule = load_one_rule(tmp_path, numeric_rule(local_override_allowed=True))
    assert rule.local_override_allowed is True


def test_local_override_allowed_defaults_false_when_omitted(tmp_path: Path) -> None:
    rule = load_one_rule(tmp_path, numeric_rule())
    assert rule.local_override_allowed is False


def test_metadata_stays_attached_to_the_rule(tmp_path: Path) -> None:
    """Carve-out prose and its citation stay attached to the rule, not a new owner."""
    rule = load_one_rule(
        tmp_path,
        numeric_rule(
            metadata=[
                {
                    "description": "Self-funding and immediate-family contributions are exempt.",
                    "source_citation": "O.C.G.A. § 21-5-41(g)",
                }
            ]
        ),
    )

    assert len(rule.metadata) == 1
    assert rule.metadata[0].description == "Self-funding and immediate-family contributions are exempt."
    assert rule.metadata[0].source_citation == "O.C.G.A. § 21-5-41(g)"


def test_metadata_defaults_to_empty_when_omitted(tmp_path: Path) -> None:
    """The spec defines omitted ``metadata`` as an empty list, never an unknown value."""
    assert load_one_rule(tmp_path, numeric_rule()).metadata == []


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("description", ""),
        ("description", " \t "),
        ("source_citation", ""),
        ("source_citation", " \t "),
    ],
    ids=[
        "empty_description",
        "whitespace_description",
        "empty_source_citation",
        "whitespace_source_citation",
    ],
)
def test_metadata_rejects_blank_required_evidence(
    tmp_path: Path,
    field_name: str,
    invalid_value: str,
) -> None:
    """Every metadata item must carry substantive carve-out prose and authority."""
    metadata = {
        "description": "Self-funding and immediate-family contributions are exempt.",
        "source_citation": "O.C.G.A. § 21-5-41(g)",
    }
    metadata[field_name] = invalid_value

    message = expect_rule_error(tmp_path, [numeric_rule(metadata=[metadata])])

    assert_rule_error_location(message, 0, f"metadata.0.{field_name}")


@pytest.mark.parametrize("missing_field", ["description", "source_citation"])
def test_metadata_rejects_missing_required_evidence(tmp_path: Path, missing_field: str) -> None:
    metadata = {
        "description": "Self-funding and immediate-family contributions are exempt.",
        "source_citation": "O.C.G.A. § 21-5-41(g)",
    }
    metadata.pop(missing_field)

    message = expect_rule_error(tmp_path, [numeric_rule(metadata=[metadata])])

    assert_rule_error_location(message, 0, f"metadata.0.{missing_field}")


# --- Positive/negative: the rule list carries more than one rule ------------------


def test_multiple_rules_load_in_order(tmp_path: Path) -> None:
    """A jurisdiction's rules are a list, and every rule survives the load in order.

    Every other positive test seeds one rule, so a loader that kept only the first (or
    re-sorted them) would still be green. The spec's CO row calls for "multiple ``numeric``
    rules keyed by ``office_level`` + ``limit_basis``" — multi-rule is the real shape.
    """
    rules = [
        numeric_rule(office_level="statewide", limit_amount=725, limit_basis="per_cycle"),
        known_nonnumeric_rule("prohibited"),
    ]

    loaded = load_seeded_rules(tmp_path, rules, filename="two_rules.yaml")

    assert len(loaded) == 2
    assert loaded[0].limit_status == "numeric"
    assert loaded[0].limit_amount == 725
    assert loaded[0].limit_basis == "per_cycle"
    assert loaded[0].office_level == "statewide"
    assert loaded[1].limit_status == "prohibited"
    assert loaded[1].donor_type == "corporation"
    assert loaded[1].limit_amount is None


def test_validation_error_reports_the_offending_rule_index(tmp_path: Path) -> None:
    """A bad second rule must report index ``1``, not ``0``.

    Every other negative test pins ``.0``, which an error path hard-coding the first index
    would satisfy. Seeding a valid rule ahead of the invalid one proves the reported index
    tracks the real list position and does not blame the innocent rule.
    """
    message = expect_rule_error(
        tmp_path,
        [numeric_rule(), numeric_rule(donor_type="not_a_real_value")],
        filename="second_rule_invalid.yaml",
    )

    assert_rule_error_location(message, 1, "donor_type")
    assert "laws.contribution_limit_rules.0" not in message


# --- Negative: invalid vocabulary values report owned locations --------------------


@pytest.mark.parametrize(
    "field",
    [
        "donor_type",
        "recipient_type",
        "office_level",
        "election_type",
        "limit_basis",
    ],
)
def test_invalid_vocabulary_value_reports_nested_location(tmp_path: Path, field: str) -> None:
    message = expect_rule_error(
        tmp_path,
        [numeric_rule(**{field: "not_a_real_value"})],
        filename=f"invalid_{field}.yaml",
    )
    assert_rule_error_location(message, 0, field)


def test_invalid_limit_status_value_reports_owned_location(tmp_path: Path) -> None:
    rejected_value = "not_a_real_value"
    message = expect_rule_error(
        tmp_path,
        [numeric_rule(limit_status=rejected_value)],
        filename="invalid_limit_status.yaml",
    )
    assert_limit_status_error_location(message, 0, rejected_value)


@pytest.mark.parametrize("legacy_alias", ["comptroller", "city_controller", "state_assembly"])
def test_legacy_office_aliases_are_rejected_in_a_legal_rule(tmp_path: Path, legacy_alias: str) -> None:
    """The spec's named legacy aliases must not be accepted in a legal-rule ``office_level``.

    Spec "One office vocabulary, two fields" keeps these three spellings legal in the
    *unvalidated* ``coverage.office_levels`` while forbidding them in a legal rule. That
    shared vocabulary makes "admit the alias so existing coverage keeps working" the likely
    Stage 2 mistake, which a synthetic ``not_a_real_value`` cannot catch: a ``Literal``
    containing ``comptroller`` still rejects it.
    """
    message = expect_rule_error(
        tmp_path,
        [numeric_rule(office_level=legacy_alias)],
        filename=f"office_alias_{legacy_alias}.yaml",
    )
    assert_rule_error_location(message, 0, "office_level")


# --- Negative: per-status field requirements and prohibitions ---------------------
#
# Each asserts three things: the offending rule's list index, the field that violated the
# status matrix, and the ``limit_status`` whose rule was violated. The bare
# ``laws.contribution_limit_rules.0`` prefix matches *every* error on that rule and cannot
# prove the named matrix rule fired. The field must be in the reported pydantic location:
# a discriminated union can provide that by inserting the status tag before the field, while
# a flat model must raise field-located errors rather than a root ``model_validator`` error
# whose prose merely names the field.


@pytest.mark.parametrize("missing_field", ["limit_amount", "limit_basis", "effective_date", "source_citation"])
def test_numeric_status_requires_amount_basis_date_and_citation(tmp_path: Path, missing_field: str) -> None:
    message = expect_rule_error(
        tmp_path,
        [drop_keys(numeric_rule(), missing_field)],
        filename=f"numeric_missing_{missing_field}.yaml",
    )
    assert_status_rule_error(message, rule_index=0, field_name=missing_field, limit_status="numeric")


def test_numeric_status_rejects_research_observed_date(tmp_path: Path) -> None:
    message = expect_rule_error(
        tmp_path,
        [numeric_rule(research_observed_date="2026-08-22")],
    )
    assert_status_rule_error(
        message,
        rule_index=0,
        field_name="research_observed_date",
        limit_status="numeric",
    )


@pytest.mark.parametrize("invalid_amount", [True, 6800.5, "6800"], ids=["bool", "float", "string"])
def test_numeric_status_requires_strict_integer_amount(tmp_path: Path, invalid_amount: object) -> None:
    message = expect_rule_error(tmp_path, [numeric_rule(limit_amount=invalid_amount)])

    assert_rule_error_location(message, 0, "limit_amount")


@pytest.mark.parametrize("limit_status", KNOWN_NONNUMERIC_STATUSES)
@pytest.mark.parametrize("missing_field", ["effective_date", "source_citation"])
def test_known_nonnumeric_status_requires_date_and_citation(
    tmp_path: Path, limit_status: str, missing_field: str
) -> None:
    message = expect_rule_error(
        tmp_path,
        [drop_keys(known_nonnumeric_rule(limit_status), missing_field)],
        filename=f"{limit_status}_missing_{missing_field}.yaml",
    )
    assert_status_rule_error(message, rule_index=0, field_name=missing_field, limit_status=limit_status)


@pytest.mark.parametrize("limit_status", KNOWN_NONNUMERIC_STATUSES)
@pytest.mark.parametrize(
    ("forbidden_field", "forbidden_value"),
    [
        ("limit_amount", 5000),
        ("limit_basis", "per_election"),
        ("research_observed_date", "2026-08-22"),
    ],
)
def test_known_nonnumeric_status_rejects_amount_basis_and_research_date(
    tmp_path: Path, limit_status: str, forbidden_field: str, forbidden_value: object
) -> None:
    message = expect_rule_error(
        tmp_path,
        [known_nonnumeric_rule(limit_status, **{forbidden_field: forbidden_value})],
        filename=f"{limit_status}_with_{forbidden_field}.yaml",
    )
    assert_status_rule_error(
        message,
        rule_index=0,
        field_name=forbidden_field,
        limit_status=limit_status,
    )


@pytest.mark.parametrize("missing_field", ["research_observed_date", "source_citation", "note"])
def test_unknown_status_requires_research_date_citation_and_note(tmp_path: Path, missing_field: str) -> None:
    message = expect_rule_error(
        tmp_path,
        [drop_keys(unknown_rule(), missing_field)],
        filename=f"unknown_missing_{missing_field}.yaml",
    )
    assert_status_rule_error(message, rule_index=0, field_name=missing_field, limit_status="unknown")


@pytest.mark.parametrize(
    ("forbidden_field", "forbidden_value"),
    [
        ("limit_amount", 5000),
        ("limit_basis", "per_election"),
        ("effective_date", "2023-02-15"),
        ("sunset_date", "2024-01-01"),
    ],
)
def test_unknown_status_rejects_legal_amount_basis_and_dates(
    tmp_path: Path, forbidden_field: str, forbidden_value: object
) -> None:
    message = expect_rule_error(
        tmp_path,
        [unknown_rule(**{forbidden_field: forbidden_value})],
        filename=f"unknown_with_{forbidden_field}.yaml",
    )
    assert_status_rule_error(
        message,
        rule_index=0,
        field_name=forbidden_field,
        limit_status="unknown",
    )


@pytest.mark.parametrize("limit_status", ["numeric", *KNOWN_NONNUMERIC_STATUSES, "unknown"])
@pytest.mark.parametrize("invalid_citation", ["", " \t "], ids=["empty", "whitespace"])
def test_every_status_rejects_blank_source_citation(
    tmp_path: Path,
    limit_status: str,
    invalid_citation: str,
) -> None:
    rule = (
        numeric_rule(source_citation=invalid_citation)
        if limit_status == "numeric"
        else unknown_rule(source_citation=invalid_citation)
        if limit_status == "unknown"
        else known_nonnumeric_rule(limit_status, source_citation=invalid_citation)
    )

    message = expect_rule_error(tmp_path, [rule])

    assert_rule_error_location(message, 0, "source_citation")


@pytest.mark.parametrize("invalid_note", ["", " \t "], ids=["empty", "whitespace"])
def test_unknown_status_rejects_blank_gap_note(tmp_path: Path, invalid_note: str) -> None:
    message = expect_rule_error(tmp_path, [unknown_rule(note=invalid_note)])

    assert_rule_error_location(message, 0, "note")


# --- Negative: extra="forbid" still reports full nested path -----------------------


def test_rule_error_details_exclude_the_seeded_path(tmp_path: Path) -> None:
    """A path containing contract tokens cannot satisfy assertions about error details."""
    filename = "numeric_limit_amount_path_spoof.yaml"
    message = expect_rule_error(
        tmp_path,
        [numeric_rule(unexpected_rule_key=True)],
        filename=filename,
    )

    assert filename not in message
    assert str(tmp_path) not in message


def test_unexpected_nested_rule_key_reports_full_path(tmp_path: Path) -> None:
    message = expect_rule_error(
        tmp_path,
        [numeric_rule(unexpected_rule_key=True)],
    )
    assert_rule_error_location(message, 0, "unexpected_rule_key")


def test_unexpected_nested_metadata_key_reports_full_path(tmp_path: Path) -> None:
    message = expect_rule_error(
        tmp_path,
        [
            numeric_rule(
                metadata=[
                    {
                        "description": "Self-funding and immediate-family contributions are exempt.",
                        "source_citation": "O.C.G.A. § 21-5-41(g)",
                        "unexpected_meta_key": True,
                    }
                ]
            )
        ],
    )
    assert_rule_error_location(message, 0, "metadata.0.unexpected_meta_key")
