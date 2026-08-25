"""Self-tests for the contribution-rule assertion helpers.

The helpers in ``_contribution_rule_seeds`` are what every negative loader test in
``test_contribution_limit_rules.py`` trusts, so a helper that silently accepts a
root-prose error would turn that whole module falsely green. These tests pin the
helpers against real Pydantic error shapes — flat model and discriminated union alike
— independently of whether the loader implements the field yet.
"""

from __future__ import annotations

from typing import Annotated, Literal

import pytest
from pydantic import BaseModel, Field, ValidationError

from domains.campaign_finance.jurisdictions._contribution_rule_seeds import (
    KNOWN_NONNUMERIC_STATUSES,
    assert_limit_status_error_location,
    assert_rule_error_location,
    assert_status_rule_error,
    format_pydantic_error_details,
)


@pytest.mark.parametrize(
    ("message", "field_path"),
    [
        ("laws.contribution_limit_rules.0.donor_type: Input should be valid", "donor_type"),
        ("laws.contribution_limit_rules.0.numeric.donor_type: Input should be valid", "donor_type"),
        (
            "laws.contribution_limit_rules.0.metadata.0.unexpected_meta_key: Extra inputs are not permitted",
            "metadata.0.unexpected_meta_key",
        ),
        (
            "laws.contribution_limit_rules.0.numeric.metadata.0.unexpected_meta_key: Extra inputs are not permitted",
            "metadata.0.unexpected_meta_key",
        ),
    ],
    ids=["flat", "discriminated_union", "flat_nested_metadata", "union_nested_metadata"],
)
def test_rule_error_location_accepts_owned_loader_shapes(message: str, field_path: str) -> None:
    assert_rule_error_location(message, 0, field_path)


@pytest.mark.parametrize(
    "message",
    [
        "laws.contribution_limit_rules.0.limit_status: Input should be 'numeric'",
        (
            "laws.contribution_limit_rules.0: Input tag 'not_a_real_value' found using "
            "'limit_status' does not match any of the expected tags"
        ),
    ],
    ids=["flat_literal", "discriminated_union_tag"],
)
def test_limit_status_error_location_accepts_owned_loader_shapes(message: str) -> None:
    assert_limit_status_error_location(message, 0, "not_a_real_value")


def test_limit_status_error_location_accepts_pydantic_flat_and_union_shapes() -> None:
    class FlatRule(BaseModel):
        limit_status: Literal["numeric"]

    class FlatLaws(BaseModel):
        contribution_limit_rules: list[FlatRule]

    class FlatConfig(BaseModel):
        laws: FlatLaws

    class NumericRule(BaseModel):
        limit_status: Literal["numeric"]
        limit_amount: int

    class ProhibitedRule(BaseModel):
        limit_status: Literal["prohibited"]

    TaggedRule = Annotated[NumericRule | ProhibitedRule, Field(discriminator="limit_status")]

    class TaggedLaws(BaseModel):
        contribution_limit_rules: list[TaggedRule]

    class TaggedConfig(BaseModel):
        laws: TaggedLaws

    config_data = {"laws": {"contribution_limit_rules": [{"limit_status": "not_a_real_value"}]}}

    with pytest.raises(ValidationError) as flat_error:
        FlatConfig.model_validate(config_data)
    with pytest.raises(ValidationError) as tagged_error:
        TaggedConfig.model_validate(config_data)

    assert_limit_status_error_location(format_pydantic_error_details(flat_error.value), 0, "not_a_real_value")
    assert_limit_status_error_location(format_pydantic_error_details(tagged_error.value), 0, "not_a_real_value")


def test_limit_status_root_error_requires_rejected_value() -> None:
    with pytest.raises(AssertionError):
        assert_limit_status_error_location(
            "laws.contribution_limit_rules.0: Input tag is invalid",
            0,
            "not_a_real_value",
        )


@pytest.mark.parametrize(
    ("limit_status", "field_name"),
    [
        *(
            ("numeric", field)
            for field in (
                "limit_amount",
                "limit_basis",
                "effective_date",
                "source_citation",
                "research_observed_date",
            )
        ),
        *(
            (status, field)
            for status in KNOWN_NONNUMERIC_STATUSES
            for field in (
                "effective_date",
                "source_citation",
                "limit_amount",
                "limit_basis",
                "research_observed_date",
            )
        ),
        *(
            ("unknown", field)
            for field in (
                "research_observed_date",
                "source_citation",
                "note",
                "limit_amount",
                "limit_basis",
                "effective_date",
                "sunset_date",
            )
        ),
    ],
    ids=lambda value: value,
)
def test_status_rule_error_rejects_field_named_only_in_root_error_prose(limit_status: str, field_name: str) -> None:
    malformed_detail = f"laws.contribution_limit_rules.0: Value error, {limit_status} {field_name} invalid"

    with pytest.raises(AssertionError):
        assert_status_rule_error(
            malformed_detail,
            rule_index=0,
            field_name=field_name,
            limit_status=limit_status,
        )
