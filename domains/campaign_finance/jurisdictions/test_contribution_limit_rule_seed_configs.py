"""What the checked-in seed configs must contain as flat and structured rule seeds.

This module owns assertions about the *checked-in* state and city ``config.yaml`` files.
``test_contribution_limit_rules.py`` owns the loader contract and seeds ``tmp_path``
fixtures for it; nothing here writes a fixture, and nothing here mutates a config.

Two halves, deliberately split into separate tests so one failure cannot mask the other:

* The **flat-block snapshots** below are hard-coded string literals captured from the live
  files before city structured-rule seeding. Re-reading the block out of the file at
  assert time would pass no matter what was later written into it, so the literal is the
  guard: it is what makes an unintended rewrite of ``laws.contribution_limits`` fail. The
  state and Stage 1 city snapshots and parsed-value expectations are expected to pass.
* The **structured-rule expectations** pin the exact seeded rule matrix carried by the
  checked-in state and city configs, including citation/date and note predicates that the
  row projection intentionally leaves to this owner.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from domains.campaign_finance.jurisdictions._config_specimens import (
    CA_CONFIG_PATH,
    CO_CONFIG_PATH,
    GA_CONFIG_PATH,
    LA_CONFIG_PATH,
    NC_CONFIG_PATH,
    NYC_CONFIG_PATH,
    PHL_CONFIG_PATH,
    SF_CONFIG_PATH,
)
from domains.campaign_finance.jurisdictions._test_contribution_rule_seed_matrix import (
    CA_FLAT_BLOCK_VINTAGE_LIMITS,
    CA_STRUCTURED_2025_26_CANDIDATE_LIMITS,
    CO_LOCAL_OVERRIDE_OFFICE_LEVELS,
    EXPECTED_STRUCTURED_RULE_COUNTS,
    EXPECTED_STRUCTURED_RULE_PROJECTIONS,
    RULE_PROJECTION_FIELDS,
    RuleProjection,
)
from domains.campaign_finance.jurisdictions.config_schema import (
    ContributionLimitRule,
    load_jurisdiction_config,
)


SEED_CONFIG_PATHS: dict[str, Path] = {
    "cities-LA": LA_CONFIG_PATH,
    "cities-NYC": NYC_CONFIG_PATH,
    "cities-PHL": PHL_CONFIG_PATH,
    "cities-SF": SF_CONFIG_PATH,
    "states-CA": CA_CONFIG_PATH,
    "states-CO": CO_CONFIG_PATH,
    "states-GA": GA_CONFIG_PATH,
    "states-NC": NC_CONFIG_PATH,
}
SEED_CODES = sorted(SEED_CONFIG_PATHS)
STRUCTURED_SEED_CODES = sorted(EXPECTED_STRUCTURED_RULE_COUNTS)
CITY_SEED_JURISDICTION_EXPECTATIONS = {
    "cities-LA": ("LA", "municipality", "06037"),
    "cities-NYC": ("NYC", "municipality", "36061"),
    "cities-PHL": ("PHL", "municipality", "42101"),
    "cities-SF": ("SF", "municipality", "06075"),
}
CITY_STRUCTURED_SEED_CODES = tuple(code for code in STRUCTURED_SEED_CODES if code.startswith("cities-"))
NUMERIC_CITY_SEED_CODES = ("cities-LA", "cities-NYC", "cities-SF")

# --- Pre-edit flat-block snapshots (verbatim, including inline comments) ----------
#
# Copied byte-for-byte out of the live ``config.yaml`` files while
# ``laws.contribution_limit_rules`` was still absent from all four. Do not regenerate
# these from the files: a snapshot read back out of its own source cannot fail.

CA_FLAT_CONTRIBUTION_LIMITS_BLOCK = """\
  contribution_limits:
    individual_to_candidate: 5500
    pac_to_candidate: 10200
    corporate_direct: "prohibited"
    union_direct: "prohibited"
    party_to_candidate: null
"""

CO_FLAT_CONTRIBUTION_LIMITS_BLOCK = """\
  contribution_limits:
    individual_to_candidate: 725 # statewide offices; $225 for legislative — see notes
    pac_to_candidate: 725 # same limits as individual; Art. XXVIII § 3
    corporate_direct: "prohibited" # Art. XXVIII § 3(4)(a)
    union_direct: "prohibited" # Art. XXVIII § 3(4)(a)
    party_to_candidate: 789060 # governor; varies dramatically by office — see notes
"""

GA_FLAT_CONTRIBUTION_LIMITS_BLOCK = """\
  contribution_limits:
    individual_to_candidate: 8400
    pac_to_candidate: 8400
    corporate_direct: 8400
    union_direct: 8400
    party_to_candidate: 8400
"""

NC_FLAT_CONTRIBUTION_LIMITS_BLOCK = """\
  contribution_limits:
    individual_to_candidate: 6800
    pac_to_candidate: 6800
    corporate_direct: "prohibited"
    union_direct: "prohibited"
    party_to_candidate: "unlimited"
"""

NYC_FLAT_CONTRIBUTION_LIMITS_BLOCK = """\
  contribution_limits:
    individual_to_candidate: 2000
    pac_to_candidate: 2000
    corporate_direct: "prohibited"
    union_direct: 2000
    party_to_candidate: null
"""

PHL_FLAT_CONTRIBUTION_LIMITS_BLOCK = """\
  contribution_limits:
    individual_to_candidate: null  # PHL local limits not yet captured
    pac_to_candidate: null
    corporate_direct: null
    union_direct: null
    party_to_candidate: null
"""

SF_FLAT_CONTRIBUTION_LIMITS_BLOCK = """\
  contribution_limits:
    individual_to_candidate: 500
    pac_to_candidate: 500
    corporate_direct: "prohibited"
    union_direct: 500
    party_to_candidate: null
"""

LA_FLAT_CONTRIBUTION_LIMITS_BLOCK = """\
  contribution_limits:
    individual_to_candidate: 900
    pac_to_candidate: 900
    corporate_direct: "prohibited"
    union_direct: 900
    party_to_candidate: null
"""

FLAT_BLOCK_SNAPSHOTS: dict[str, str] = {
    "cities-LA": LA_FLAT_CONTRIBUTION_LIMITS_BLOCK,
    "cities-NYC": NYC_FLAT_CONTRIBUTION_LIMITS_BLOCK,
    "cities-PHL": PHL_FLAT_CONTRIBUTION_LIMITS_BLOCK,
    "cities-SF": SF_FLAT_CONTRIBUTION_LIMITS_BLOCK,
    "states-CA": CA_FLAT_CONTRIBUTION_LIMITS_BLOCK,
    "states-CO": CO_FLAT_CONTRIBUTION_LIMITS_BLOCK,
    "states-GA": GA_FLAT_CONTRIBUTION_LIMITS_BLOCK,
    "states-NC": NC_FLAT_CONTRIBUTION_LIMITS_BLOCK,
}

# The same five channels as parsed by the loader, hand-transcribed from the snapshots
# above. Text identity and parsed semantics are pinned separately so a YAML-level change
# that preserved neither could pass by satisfying only one of them.
FLAT_CONTRIBUTION_LIMIT_VALUES: dict[str, dict[str, int | str | None]] = {
    "cities-LA": {
        "individual_to_candidate": 900,
        "pac_to_candidate": 900,
        "corporate_direct": "prohibited",
        "union_direct": 900,
        "party_to_candidate": None,
    },
    "cities-NYC": {
        "individual_to_candidate": 2000,
        "pac_to_candidate": 2000,
        "corporate_direct": "prohibited",
        "union_direct": 2000,
        "party_to_candidate": None,
    },
    "cities-PHL": {
        "individual_to_candidate": None,
        "pac_to_candidate": None,
        "corporate_direct": None,
        "union_direct": None,
        "party_to_candidate": None,
    },
    "cities-SF": {
        "individual_to_candidate": 500,
        "pac_to_candidate": 500,
        "corporate_direct": "prohibited",
        "union_direct": 500,
        "party_to_candidate": None,
    },
    "states-CA": {
        "individual_to_candidate": 5500,
        "pac_to_candidate": 10200,
        "corporate_direct": "prohibited",
        "union_direct": "prohibited",
        "party_to_candidate": None,
    },
    "states-CO": {
        "individual_to_candidate": 725,
        "pac_to_candidate": 725,
        "corporate_direct": "prohibited",
        "union_direct": "prohibited",
        "party_to_candidate": 789060,
    },
    "states-GA": {
        "individual_to_candidate": 8400,
        "pac_to_candidate": 8400,
        "corporate_direct": 8400,
        "union_direct": 8400,
        "party_to_candidate": 8400,
    },
    "states-NC": {
        "individual_to_candidate": 6800,
        "pac_to_candidate": 6800,
        "corporate_direct": "prohibited",
        "union_direct": "prohibited",
        "party_to_candidate": "unlimited",
    },
}
CITY_EXPECTED_EFFECTIVE_DATES = {
    "cities-LA": "2011-04-08",
    "cities-NYC": "2018-01-12",
    "cities-SF": "2009-11-20",
}
CITY_EXPECTED_SOURCE_CITATIONS = {
    "cities-LA": "L.A. Charter § 470(c)(3)-(4), (f); Charter Amendment H approved 2011-03-08 effective 2011-04-08",
    "cities-NYC": "NYC CFB 2021 Limits & Thresholds (new program participant contribution limits); contributions received beginning 2018-01-12",
    "cities-PHL": (
        "docs/reference/research/phl_campaign_finance_contract_2026_04_25.md; "
        "Philadelphia Board of Ethics campaign-finance research gap observed 2026-08-22"
    ),
    "cities-SF": (
        "S.F. C&GCC § 1.114(a); SF Ethics contributor guide; "
        "S.F. Ethics 2025 streamlining preview notes the $500 cap was set in 2009 and has not been adjusted"
    ),
}
PHL_UNKNOWN_RULE_NOTE = (
    "PHL local candidate limits remain unresearched; see "
    "docs/reference/research/phl_campaign_finance_contract_2026_04_25.md and the Philadelphia Board of Ethics "
    "campaign-finance page."
)

DIRECT_FLAT_PROHIBITION_CHANNELS = {
    "corporation": "corporate_direct",
    "union": "union_direct",
}


def load_seed_rules(code: str) -> list[ContributionLimitRule]:
    """Read one checked-in seed config through the loader owner and return its rules."""
    config = load_jurisdiction_config(SEED_CONFIG_PATHS[code])
    return list(config.laws.contribution_limit_rules or [])


def select_rules(rules: list[ContributionLimitRule], **dimensions: object) -> list[ContributionLimitRule]:
    """Rules matching every named dimension exactly (``None`` matches only an absent value)."""
    return [rule for rule in rules if all(getattr(rule, name) == value for name, value in dimensions.items())]


def require_one_rule(rules: list[ContributionLimitRule], **dimensions: object) -> ContributionLimitRule:
    matches = select_rules(rules, **dimensions)
    assert len(matches) == 1, f"expected exactly one rule matching {dimensions!r}, got {len(matches)}"
    return matches[0]


def numeric_amounts(rules: list[ContributionLimitRule], **dimensions: object) -> set[int]:
    """The distinct dollar caps carried by the ``numeric`` rules matching ``dimensions``."""
    return {rule.limit_amount for rule in select_rules(rules, limit_status="numeric", **dimensions)}


def expected_ca_candidate_amount(donor_type: str, office_level: str) -> int:
    return CA_STRUCTURED_2025_26_CANDIDATE_LIMITS[(donor_type, office_level)]


def project_rule(rule: ContributionLimitRule) -> RuleProjection:
    return tuple(getattr(rule, field_name) for field_name in RULE_PROJECTION_FIELDS)


def sorted_projection(projection: list[RuleProjection]) -> list[RuleProjection]:
    return sorted(projection, key=lambda row: tuple("" if value is None else str(value) for value in row))


def projection_matching(projection: list[RuleProjection], **dimensions: object) -> list[RuleProjection]:
    field_indexes = {field_name: index for index, field_name in enumerate(RULE_PROJECTION_FIELDS)}
    return [row for row in projection if all(row[field_indexes[name]] == value for name, value in dimensions.items())]


def assert_rule_projection_matches_expected(
    actual_projection: list[RuleProjection],
    expected_projection: list[RuleProjection],
) -> None:
    assert sorted_projection(actual_projection) == sorted_projection(expected_projection)


def metadata_text(rule: ContributionLimitRule) -> str:
    """One searchable string of a rule's metadata descriptions and their citations."""
    return " ".join(f"{item.description} {item.source_citation}" for item in rule.metadata)


def assert_ga_union_note_records_same_cap_family_normalization(note: str | None) -> None:
    assert note is not None and note.strip(), "GA union rule carries no normalization note"
    normalized_note = " ".join(note.casefold().replace("-", " ").split())
    union_gap_phrases = (
        "does not enumerate union specific",
        "no distinct union",
        "no separate union",
        "not list union",
        "not separately list union",
        "not enumerate union",
        "without a distinct union",
    )
    corporation_cap_patterns = (
        r"\b(?:same|shared|common) (?:contribution )?(?:cap|limit)s? as corporations\b",
        r"\b(?:same|shared|common) (?:corporation|corporate) (?:contribution )?(?:cap|limit)s?\b",
        r"\bnormalizes? unions to (?:the )?(?:corporation|corporate) (?:contribution )?(?:cap|limit)s?\b",
        r"\b(?:treated as|treats unions as) corporations\b",
        r"\b(?:corporation|corporate) (?:contribution )?(?:cap|limit)s? appl(?:y|ies) to unions\b",
        r"\bunions (?:use|share|follow) (?:the )?(?:corporation|corporate) (?:contribution )?(?:cap|limit)s?\b",
    )
    negated_corporation_normalization_patterns = (
        r"\b(?:not|never|no|does not|do not|don't) (?:\w+ ){0,4}(?:treated as|treats? .* as) corporations\b",
        r"\b(?:not|never|no|does not|do not|don't) (?:\w+ ){0,4}(?:use|share|follow|apply|applies) "
        r"(?:\w+ ){0,4}(?:corporation|corporate) (?:contribution )?(?:cap|limit)s?\b",
        r"\bunions (?:do not|don't|never|not) (?:\w+ ){0,4}(?:use|share|follow) (?:\w+ ){0,4}"
        r"(?:corporation|corporate) (?:contribution )?(?:cap|limit)s?\b",
        r"\b(?:corporation|corporate) (?:contribution )?(?:cap|limit)s? (?:does not|do not|never|not) "
        r"(?:\w+ ){0,4}appl(?:y|ies) to unions\b",
        r"\b(?:false|untrue|incorrect|wrong) that (?:\w+ ){0,4}unions (?:\w+ ){0,4}"
        r"(?:use|share|follow) (?:\w+ ){0,4}(?:corporation|corporate) "
        r"(?:contribution )?(?:cap|limit)s?\b",
    )

    assert "union" in normalized_note
    assert any(phrase in normalized_note for phrase in union_gap_phrases), (
        "GA union note must say the statute supplies no distinct union limit"
    )
    assert not any(re.search(pattern, normalized_note) for pattern in negated_corporation_normalization_patterns), (
        "GA union note must not negate corporation-cap normalization"
    )
    assert any(re.search(pattern, normalized_note) for pattern in corporation_cap_patterns), (
        "GA union note must say union caps are normalized to the corporation cap"
    )


def assert_metadata_text_carries_only_state_party_sublimit(
    row_label: str,
    text: str,
    *,
    expected_sublimit: str,
    forbidden_sublimit: str,
) -> None:
    assert expected_sublimit in text, f"{row_label} metadata does not mention {expected_sublimit}"
    assert forbidden_sublimit not in text, f"{row_label} metadata also mentions {forbidden_sublimit}"


def city_rule_search_text(rule: ContributionLimitRule) -> str:
    text_parts = [rule.source_citation]
    if rule.note is not None:
        text_parts.append(rule.note)
    if rule.metadata:
        text_parts.append(metadata_text(rule))
    return " ".join(text_parts)


def assert_city_rule_text_excludes_match_program_semantics(text: str) -> None:
    normalized_text = " ".join(text.casefold().replace("-", " ").split())
    forbidden_patterns = (
        r"\b8\s*(?::|to)\s*1\b",
        r"\bmatch(?:ing|able)?\b",
        r"\bpublic funds?\b",
        r"\bparticipat(?:e|es|ed|ing|ion)\b",
    )
    assert not any(re.search(pattern, normalized_text) for pattern in forbidden_patterns), (
        "city rule prose must not carry matching-funds or participation semantics"
    )


def assert_flat_direct_prohibitions_remain_outside_structured_matrix(
    code: str,
    projection: list[RuleProjection],
    *,
    expected_vintage_limits: dict[str, int | str | None] | None = None,
    snapshot_citation_assertion: tuple[str, str] | None = None,
) -> None:
    for donor_type, flat_channel in DIRECT_FLAT_PROHIBITION_CHANNELS.items():
        actual_flat_value = FLAT_CONTRIBUTION_LIMIT_VALUES[code][flat_channel]
        if expected_vintage_limits is not None:
            assert actual_flat_value == expected_vintage_limits[flat_channel]
        assert actual_flat_value == "prohibited"
        if snapshot_citation_assertion is not None:
            flat_block_snapshot, required_snapshot_citation = snapshot_citation_assertion
            assert f'{flat_channel}: "prohibited" # {required_snapshot_citation}' in flat_block_snapshot
        assert not projection_matching(projection, donor_type=donor_type)


# --- Flat-block snapshots: expected GREEN today ----------------------------------


@pytest.mark.parametrize("code", SEED_CODES)
def test_flat_contribution_limits_block_matches_pre_edit_snapshot(code: str) -> None:
    """The live file still contains the exact pre-seeding block, exactly once."""
    config_text = SEED_CONFIG_PATHS[code].read_text(encoding="utf-8")
    snapshot = FLAT_BLOCK_SNAPSHOTS[code]

    assert snapshot in config_text, f"{code} laws.contribution_limits no longer matches its pre-edit snapshot"
    assert config_text.count(snapshot) == 1, f"{code} contains the contribution_limits snapshot more than once"


@pytest.mark.parametrize("code", SEED_CODES)
def test_flat_contribution_limits_parse_to_pinned_values(code: str) -> None:
    """The loader still reports the five hand-transcribed flat channel values."""
    contribution_limits = load_jurisdiction_config(SEED_CONFIG_PATHS[code]).laws.contribution_limits

    actual = contribution_limits.model_dump()
    assert actual == FLAT_CONTRIBUTION_LIMIT_VALUES[code]


@pytest.mark.parametrize("city_id", sorted(CITY_SEED_JURISDICTION_EXPECTATIONS))
def test_city_seed_configs_load_with_expected_jurisdiction_identity(city_id: str) -> None:
    config = load_jurisdiction_config(SEED_CONFIG_PATHS[city_id])
    expected_code, expected_type, expected_fips = CITY_SEED_JURISDICTION_EXPECTATIONS[city_id]

    assert config.jurisdiction.code == expected_code
    assert config.jurisdiction.type == expected_type
    assert config.jurisdiction.fips == expected_fips


# --- Structured seed matrix --------------------------------------------------------


@pytest.mark.parametrize("code", STRUCTURED_SEED_CODES)
def test_expected_structured_rule_counts_match_projection_rows(code: str) -> None:
    """The count pin must stay derivable from the exact row matrix."""
    assert len(EXPECTED_STRUCTURED_RULE_PROJECTIONS[code]) == EXPECTED_STRUCTURED_RULE_COUNTS[code]


def test_expected_structured_rule_count_subtotals_match_stage_contract() -> None:
    """State and city subtotals are both hand-pinned so neither can silently drift."""
    state_total = sum(count for code, count in EXPECTED_STRUCTURED_RULE_COUNTS.items() if code.startswith("states-"))
    city_total = sum(count for code, count in EXPECTED_STRUCTURED_RULE_COUNTS.items() if code.startswith("cities-"))

    assert state_total == 66
    assert city_total == 26


@pytest.mark.parametrize("code", STRUCTURED_SEED_CODES)
def test_expected_structured_rule_projection_rows_match_loader_projection_shape(code: str) -> None:
    """Every expected matrix row must be satisfiable by ``project_rule``."""
    assert {len(row) for row in EXPECTED_STRUCTURED_RULE_PROJECTIONS[code]} == {len(RULE_PROJECTION_FIELDS)}


@pytest.mark.parametrize("code", STRUCTURED_SEED_CODES)
def test_seed_config_carries_expected_structured_rule_count(code: str) -> None:
    """Each seed config declares exactly the number of structured rules the matrix names."""
    rules = load_seed_rules(code)

    assert len(rules) == EXPECTED_STRUCTURED_RULE_COUNTS[code]


@pytest.mark.parametrize("code", STRUCTURED_SEED_CODES)
def test_seed_config_carries_exact_structured_rule_projection(code: str) -> None:
    """Each seed config declares the exact planned rule matrix, not just the right count."""
    actual_projection = [project_rule(rule) for rule in load_seed_rules(code)]

    assert_rule_projection_matches_expected(actual_projection, EXPECTED_STRUCTURED_RULE_PROJECTIONS[code])


def test_structured_rule_projection_guard_rejects_count_preserving_substitution() -> None:
    """A duplicate plus an omitted row must not satisfy the exact matrix guard."""
    expected_projection = EXPECTED_STRUCTURED_RULE_PROJECTIONS["states-NC"]
    count_preserving_bad_projection = [*expected_projection[:-2], expected_projection[-1], expected_projection[-1]]

    with pytest.raises(AssertionError):
        assert_rule_projection_matches_expected(count_preserving_bad_projection, expected_projection)


def test_phl_seed_rows_are_explicit_unknowns() -> None:
    rules = load_seed_rules("cities-PHL")

    assert len(rules) == 5
    for rule in rules:
        assert rule.limit_status == "unknown"
        assert rule.note == PHL_UNKNOWN_RULE_NOTE
        assert str(rule.research_observed_date) == "2026-08-22"
        assert rule.limit_amount is None
        assert rule.effective_date is None
        assert rule.source_citation == CITY_EXPECTED_SOURCE_CITATIONS["cities-PHL"]


@pytest.mark.parametrize(
    "text",
    [
        "This row includes an 8:1 matching funds ratio.",
        "Participant candidates may receive public funds under this rule.",
        "Up to $250 in matchable contributions qualifies for matching.",
    ],
)
def test_city_match_program_guard_rejects_match_semantics(text: str) -> None:
    with pytest.raises(AssertionError):
        assert_city_rule_text_excludes_match_program_semantics(text)


def test_city_seed_rules_exclude_match_program_semantics() -> None:
    city_rules = [rule for city_id in CITY_STRUCTURED_SEED_CODES for rule in load_seed_rules(city_id)]

    assert city_rules, "city seed carries no structured rules"
    assert {rule.limit_amount for rule in city_rules if rule.limit_amount is not None}.isdisjoint({8, 250})
    for rule in city_rules:
        assert_city_rule_text_excludes_match_program_semantics(city_rule_search_text(rule))


@pytest.mark.parametrize("city_id", NUMERIC_CITY_SEED_CODES)
def test_numeric_city_seed_rows_pin_effective_dates_and_citations(city_id: str) -> None:
    rules = load_seed_rules(city_id)

    assert rules, f"{city_id} seed carries no structured rules"
    for rule in rules:
        assert rule.limit_status == "numeric"
        assert rule.limit_amount is not None and rule.limit_amount > 0
        assert str(rule.effective_date) == CITY_EXPECTED_EFFECTIVE_DATES[city_id]
        assert rule.source_citation == CITY_EXPECTED_SOURCE_CITATIONS[city_id]


def test_la_seed_rows_carry_indexation_reverification_note() -> None:
    config = load_jurisdiction_config(SEED_CONFIG_PATHS["cities-LA"])
    rules = load_seed_rules("cities-LA")

    assert config.laws.public_financing is not False
    assert config.laws.public_financing.type == "matching_funds"
    assert rules, "cities-LA seed carries no structured rules"
    for rule in rules:
        assert rule.note is not None and rule.note.strip(), "LA numeric rules must carry a re-verification note"
        normalized_note = rule.note.casefold()
        assert "index" in normalized_note or "adjust" in normalized_note


def test_ca_flat_snapshot_and_structured_projection_vintages_are_explicitly_distinct() -> None:
    """CA flat channels are the pre-edit legacy snapshot; structured rows pin 2025-26 FPPC caps."""
    assert (
        FLAT_CONTRIBUTION_LIMIT_VALUES["states-CA"]["individual_to_candidate"]
        == CA_FLAT_BLOCK_VINTAGE_LIMITS["individual_to_candidate"]
    )
    assert (
        FLAT_CONTRIBUTION_LIMIT_VALUES["states-CA"]["pac_to_candidate"]
        == CA_FLAT_BLOCK_VINTAGE_LIMITS["pac_to_candidate"]
    )

    ca_projection = EXPECTED_STRUCTURED_RULE_PROJECTIONS["states-CA"]
    for (donor_type, office_level), amount in CA_STRUCTURED_2025_26_CANDIDATE_LIMITS.items():
        rows = projection_matching(
            ca_projection,
            donor_type=donor_type,
            recipient_type="candidate_committee",
            office_level=office_level,
            limit_status="numeric",
        )
        assert {row[RULE_PROJECTION_FIELDS.index("limit_amount")] for row in rows} == {amount}

    assert set(CA_FLAT_BLOCK_VINTAGE_LIMITS.values()).isdisjoint(CA_STRUCTURED_2025_26_CANDIDATE_LIMITS.values())


def test_ca_flat_snapshot_and_structured_projection_status_vintages_are_explicitly_distinct() -> None:
    """CA's frozen corporate/union flat status is deliberately outside the bounded matrix."""
    assert_flat_direct_prohibitions_remain_outside_structured_matrix(
        "states-CA",
        EXPECTED_STRUCTURED_RULE_PROJECTIONS["states-CA"],
        expected_vintage_limits=CA_FLAT_BLOCK_VINTAGE_LIMITS,
    )


def test_ga_seed_rules_separate_runoff_caps_from_primary_and_general() -> None:
    """GA halves the statewide cap for runoffs: 4800 vs 8400, and 1800 vs 3300 elsewhere."""
    rules = load_seed_rules("states-GA")

    assert numeric_amounts(rules, office_level="statewide", election_type="runoff") == {4800}
    assert numeric_amounts(rules, office_level="other_office", election_type="runoff") == {1800}
    for election_type in ("primary", "general"):
        assert numeric_amounts(rules, office_level="statewide", election_type=election_type) == {8400}
        assert numeric_amounts(rules, office_level="other_office", election_type=election_type) == {3300}


def test_ga_seed_union_rows_record_same_cap_family_normalization() -> None:
    """GA lets unions give directly, at the corporation cap; every union row says so."""
    rules = load_seed_rules("states-GA")
    union_rules = select_rules(rules, donor_type="union")

    assert union_rules, "GA seed carries no union donor rows"
    for rule in union_rules:
        assert rule.limit_status == "numeric", "GA does not prohibit direct union contributions"
        assert_ga_union_note_records_same_cap_family_normalization(rule.note)
        matching_corporation_amounts = numeric_amounts(
            rules,
            donor_type="corporation",
            office_level=rule.office_level,
            election_type=rule.election_type,
        )
        assert matching_corporation_amounts == {rule.limit_amount}


@pytest.mark.parametrize(
    "note",
    [
        "Union contribution row",
        "Union donor shares the numeric limit",
        "Union donors have no distinct statutory ceiling.",
        "Union donors use a corporation cap.",
    ],
)
def test_ga_union_note_guard_rejects_non_semantic_union_notes(note: str) -> None:
    with pytest.raises(AssertionError):
        assert_ga_union_note_records_same_cap_family_normalization(note)


@pytest.mark.parametrize(
    "note",
    [
        (
            "This config normalizes unions to the corporation cap because O.C.G.A. § 21-5-41 "
            "does not enumerate union-specific language separately."
        ),
        (
            "Georgia treats unions as corporations for contribution caps because the statute "
            "provides no distinct union ceiling."
        ),
    ],
)
def test_ga_union_note_guard_accepts_same_cap_family_normalization(note: str) -> None:
    assert_ga_union_note_records_same_cap_family_normalization(note)


def test_ga_union_note_guard_rejects_negated_corporation_cap_normalization() -> None:
    rejected_notes = (
        (
            "The statute provides no distinct union ceiling, but unions are not treated as "
            "corporations for contribution caps."
        ),
        "The law has no distinct union ceiling, and unions do not use the corporation cap.",
        "Georgia does not enumerate union-specific limits; unions never share the corporation cap.",
        "No separate union limit exists, but the corporation contribution cap does not apply to unions.",
        "The statute provides no distinct union ceiling; it is false that unions share the corporation cap.",
    )

    for note in rejected_notes:
        with pytest.raises(AssertionError):
            assert_ga_union_note_records_same_cap_family_normalization(note)


def test_co_flat_direct_corporate_union_prohibitions_remain_outside_structured_matrix() -> None:
    """CO's first seed matrix excludes flat-block corporate/union direct prohibitions."""
    assert_flat_direct_prohibitions_remain_outside_structured_matrix(
        "states-CO",
        EXPECTED_STRUCTURED_RULE_PROJECTIONS["states-CO"],
        snapshot_citation_assertion=(CO_FLAT_CONTRIBUTION_LIMITS_BLOCK, "Art. XXVIII § 3(4)(a)"),
    )


def test_ca_seed_party_to_candidate_rows_are_no_statutory_limit() -> None:
    """CA's ``null`` flat value means "no cap was ever enacted", not "unknown" or "absent"."""
    rules = load_seed_rules("states-CA")
    party_to_candidate = select_rules(rules, donor_type="party_committee", recipient_type="candidate_committee")

    assert party_to_candidate, "CA seed carries no party_committee to candidate_committee rows"
    assert {rule.limit_status for rule in party_to_candidate} == {"no_statutory_limit"}
    assert all(rule.limit_amount is None for rule in party_to_candidate)


def test_ca_seed_carries_small_contributor_committee_caps() -> None:
    """CA's small-contributor committees are a distinct donor class with their own caps."""
    rules = load_seed_rules("states-CA")

    assert select_rules(rules, donor_type="small_contributor_committee"), (
        "CA seed carries no small_contributor_committee rows"
    )
    assert numeric_amounts(rules, donor_type="individual", office_level="governor") == {
        expected_ca_candidate_amount("individual", "governor")
    }
    assert numeric_amounts(rules, donor_type="small_contributor_committee", office_level="legislative") == {
        expected_ca_candidate_amount("small_contributor_committee", "legislative")
    }


def test_nc_seed_uncapped_rows_cite_their_removing_statutes() -> None:
    """NC party and self-funding rows are ``unlimited`` by statute, each citing its own."""
    rules = load_seed_rules("states-NC")
    expected_citations = {"party_committee": "G.S. 163-278.13(h)", "self": "G.S. 163-278.13(d)"}

    for donor_type, citation in expected_citations.items():
        donor_rules = select_rules(rules, donor_type=donor_type)
        assert donor_rules, f"NC seed carries no {donor_type} donor rows"
        for rule in donor_rules:
            assert rule.limit_status == "unlimited"
            assert citation in rule.source_citation


def test_nc_seed_prohibited_rows_record_the_segregated_fund_exception() -> None:
    """NC bans direct corporate and union money but allows a segregated fund; both say so."""
    rules = load_seed_rules("states-NC")

    for donor_type in ("corporation", "union"):
        donor_rules = select_rules(rules, donor_type=donor_type)
        assert donor_rules, f"NC seed carries no {donor_type} donor rows"
        for rule in donor_rules:
            assert rule.limit_status == "prohibited"
            assert rule.metadata, f"NC {donor_type} rule {rule!r} carries no metadata exception"
            exception_text = metadata_text(rule)
            assert "G.S. 163-278.19" in exception_text
            assert "segregated" in exception_text.lower()


def test_co_seed_uses_all_three_limit_bases() -> None:
    """CO's statutes are stated per-cycle, per-election, and per-calendar-year alike."""
    rules = load_seed_rules("states-CO")

    numeric_rules = select_rules(rules, limit_status="numeric")
    assert {rule.limit_basis for rule in numeric_rules} == {"per_cycle", "per_election", "per_calendar_year"}


def test_co_seed_marks_local_override_only_on_county_and_municipal_rows() -> None:
    """Home-rule locals may set their own caps; state-level rows may not be overridden."""
    rules = load_seed_rules("states-CO")

    local_rules = [rule for rule in rules if rule.office_level in CO_LOCAL_OVERRIDE_OFFICE_LEVELS]
    state_rules = [rule for rule in rules if rule.office_level not in CO_LOCAL_OVERRIDE_OFFICE_LEVELS]

    assert local_rules, "CO seed carries no county or municipal rows"
    assert state_rules, "CO seed carries only county and municipal rows"
    assert all(rule.local_override_allowed for rule in local_rules)
    assert not any(rule.local_override_allowed for rule in state_rules)


def test_co_seed_party_aggregate_rows_carry_state_party_sublimits() -> None:
    """Both aggregate party rows record the state-party share of the aggregate cap."""
    rules = load_seed_rules("states-CO")
    individual_aggregate = require_one_rule(
        rules,
        donor_type="individual",
        recipient_type="party_committee",
    )
    small_donor_aggregate = require_one_rule(
        rules,
        donor_type="small_donor_committee",
        recipient_type="party_committee",
    )

    assert individual_aggregate.metadata, f"CO individual aggregate rule {individual_aggregate!r} carries no metadata"
    assert small_donor_aggregate.metadata, (
        f"CO small-donor aggregate rule {small_donor_aggregate!r} carries no metadata"
    )
    assert_metadata_text_carries_only_state_party_sublimit(
        "CO individual -> party_committee",
        metadata_text(individual_aggregate),
        expected_sublimit="$3,875",
        forbidden_sublimit="$19,650",
    )
    assert_metadata_text_carries_only_state_party_sublimit(
        "CO small_donor_committee -> party_committee",
        metadata_text(small_donor_aggregate),
        expected_sublimit="$19,650",
        forbidden_sublimit="$3,875",
    )


def test_co_state_party_sublimit_guard_rejects_concatenated_metadata() -> None:
    with pytest.raises(AssertionError):
        assert_metadata_text_carries_only_state_party_sublimit(
            "CO individual -> party_committee",
            "$3,875 state-party sublimit; $19,650 state-party sublimit",
            expected_sublimit="$3,875",
            forbidden_sublimit="$19,650",
        )
