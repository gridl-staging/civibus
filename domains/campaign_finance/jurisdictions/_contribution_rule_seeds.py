"""Seed builders and assertion helpers for the ``laws.contribution_limit_rules`` contract.

The contract itself comes from ``docs/reference/specs/jurisdiction-config.md`` ("Rule
identity and dimensions", "Value semantics", "Citation and date semantics", "Exceptions,
aggregation, and local overrides") and is exercised through the canonical owner,
``config_schema.load_jurisdiction_config``.

All seeds are temporary (``tmp_path``) and derived from checked-in pilot configs via
``yaml.safe_load``; no jurisdiction ``config.yaml`` is mutated. The assertion helpers are
pinned by ``test_contribution_rule_assertions.py`` so a helper that accepted a
root-prose error could not turn the loader contract falsely green.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from domains.campaign_finance.jurisdictions._config_specimens import CO_CONFIG_PATH
from domains.campaign_finance.jurisdictions.config_schema import load_jurisdiction_config

KNOWN_NONNUMERIC_STATUSES = ("prohibited", "unlimited", "no_statutory_limit")
LIMIT_STATUSES = ("numeric", *KNOWN_NONNUMERIC_STATUSES, "unknown")
CONTRIBUTION_RULES_OMITTED = object()


def write_seeded_config(
    tmp_path: Path,
    rules: object = CONTRIBUTION_RULES_OMITTED,
    *,
    base_path: Path = CO_CONFIG_PATH,
    filename: str | Path = "contribution_rules_seeded.yaml",
    jurisdiction_fips: str | None = None,
) -> Path:
    """Copy a specimen config and control its contribution-rule key in isolation."""
    config_data = yaml.safe_load(base_path.read_text(encoding="utf-8"))
    if jurisdiction_fips is not None:
        config_data["jurisdiction"]["fips"] = jurisdiction_fips
    if rules is CONTRIBUTION_RULES_OMITTED:
        config_data["laws"].pop("contribution_limit_rules", None)
    else:
        config_data["laws"]["contribution_limit_rules"] = rules
    seeded_path = tmp_path / filename
    seeded_path.parent.mkdir(parents=True, exist_ok=True)
    seeded_path.write_text(yaml.safe_dump(config_data, sort_keys=False), encoding="utf-8")
    return seeded_path


def write_seeded_config_to_root(
    config_root: Path,
    *,
    base_path: Path,
    jurisdiction_fips: str,
    rules: object = CONTRIBUTION_RULES_OMITTED,
    directory_name: str | None = None,
) -> Path:
    """Place a specimen-derived config in a discoverable, region-agnostic temp root.

    The specimen's existing ``cities/<code>`` or ``states/<code>`` location supplies
    the directory shape without branching on jurisdiction type. Tests may deliberately
    use a misleading ``directory_name`` to prove row identity comes from the validated
    config rather than from its path.
    """
    region_directory = base_path.parent.parent.name
    fixture_directory = directory_name or f"{base_path.parent.name}_fixture"
    return write_seeded_config(
        config_root,
        rules,
        base_path=base_path,
        filename=Path(region_directory) / fixture_directory / "config.yaml",
        jurisdiction_fips=jurisdiction_fips,
    )


def load_seeded_rules(tmp_path: Path, rules: object, **kwargs: object) -> list:
    """Load a seeded config and return its ``laws.contribution_limit_rules`` list."""
    seeded_path = write_seeded_config(tmp_path, rules, **kwargs)  # type: ignore[arg-type]
    return load_jurisdiction_config(seeded_path).laws.contribution_limit_rules


def load_one_rule(tmp_path: Path, rule: dict, **kwargs: object):
    """Load a single-rule seed and return the one loaded rule object."""
    return load_seeded_rules(tmp_path, [rule], **kwargs)[0]


def expect_rule_error(tmp_path: Path, rules: object, **kwargs: object) -> str:
    """Seed ``rules``, assert rejection, return the error *details* with the path stripped.

    ``load_jurisdiction_config`` wraps every failure as
    ``f"Invalid jurisdiction config at {config_path}: {details}"`` (config_schema.py). The
    seeded filename is therefore inside the raw message, so any assertion that a field name
    or ``limit_status`` token appears would be satisfied by a filename like
    ``numeric_missing_limit_amount.yaml`` rather than by the pydantic error detail — the
    spoof caught in review (``per-status-assertions-spoofed-by-seed-filename``). Returning
    only the ``details`` half forces every substring assertion to prove itself against the
    real validation error. The prefix is asserted, not silently skipped, so a loader that
    stopped emitting it turns these tests red instead of leaking the path back in.
    """
    seeded_path = write_seeded_config(tmp_path, rules, **kwargs)  # type: ignore[arg-type]
    with pytest.raises(ValueError) as validation_error:
        load_jurisdiction_config(seeded_path)
    message = str(validation_error.value)
    prefix = f"Invalid jurisdiction config at {seeded_path}: "
    assert message.startswith(prefix), message
    return message[len(prefix) :]


def assert_rule_error_location(message: str, rule_index: int, field_path: str) -> None:
    """Require the rule index and field path without prescribing Pydantic's model shape.

    A flat model reports ``...<index>.<field_path>`` while a discriminated union may insert
    its ``limit_status`` tag between the list index and field path. Both preserve the facts
    this loader contract owns: which rule failed and which nested field was responsible.
    """
    rule_location = f"laws.contribution_limit_rules.{rule_index}"
    allowed_locations = {f"{rule_location}.{field_path}"}
    allowed_locations.update(f"{rule_location}.{limit_status}.{field_path}" for limit_status in LIMIT_STATUSES)
    reported_locations = {formatted_error.partition(": ")[0] for formatted_error in message.split("; ")}

    assert reported_locations & allowed_locations, (
        f"expected one of {sorted(allowed_locations)!r} in reported locations {sorted(reported_locations)!r}"
    )


def assert_limit_status_error_location(message: str, rule_index: int, rejected_value: str) -> None:
    """Accept flat-model and tagged-union locations for an invalid discriminator tag."""
    rule_location = f"laws.contribution_limit_rules.{rule_index}"
    reported_locations = {formatted_error.partition(": ")[0] for formatted_error in message.split("; ")}
    flat_location = f"{rule_location}.limit_status"
    allowed_locations = {rule_location, flat_location}

    assert reported_locations & allowed_locations, (
        f"expected one of {sorted(allowed_locations)!r} in reported locations {sorted(reported_locations)!r}"
    )
    if rule_location in reported_locations and flat_location not in reported_locations:
        assert rejected_value in message


def assert_status_rule_error(message: str, *, rule_index: int, field_name: str, limit_status: str) -> None:
    """Pin a status-matrix violation to its rule, offending field, and status branch."""
    assert_rule_error_location(message, rule_index, field_name)
    assert limit_status in message


def format_pydantic_error_details(error: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(location) for location in pydantic_error['loc'])}: {pydantic_error['msg']}"
        for pydantic_error in error.errors()
    )


def numeric_rule(**overrides: object) -> dict:
    rule: dict = {
        "donor_type": "individual",
        "recipient_type": "candidate_committee",
        "limit_status": "numeric",
        "limit_amount": 6800,
        "limit_basis": "per_election",
        "effective_date": "2023-02-15",
        "source_citation": "N.C.G.S. § 163-278.13",
    }
    rule.update(overrides)
    return rule


def known_nonnumeric_rule(limit_status: str, **overrides: object) -> dict:
    """A valid ``prohibited`` / ``unlimited`` / ``no_statutory_limit`` rule."""
    rule: dict = {
        "donor_type": "corporation",
        "recipient_type": "candidate_committee",
        "limit_status": limit_status,
        "effective_date": "2013-12-01",
        "source_citation": "N.C.G.S. § 163-278.13(h)",
    }
    rule.update(overrides)
    return rule


def unknown_rule(**overrides: object) -> dict:
    rule: dict = {
        "donor_type": "individual",
        "recipient_type": "candidate_committee",
        "limit_status": "unknown",
        "research_observed_date": "2026-08-22",
        "source_citation": (
            "domains/campaign_finance/jurisdictions/cities/PHL/config.yaml "
            "laws.contribution_limits.individual_to_candidate; Stage 1 audit 2026-08-22"
        ),
        "note": "PHL local limits not yet captured; see Board-of-Ethics research gap",
    }
    rule.update(overrides)
    return rule


def drop_keys(rule: dict, *keys: str) -> dict:
    trimmed = dict(rule)
    for key in keys:
        trimmed.pop(key, None)
    return trimmed
