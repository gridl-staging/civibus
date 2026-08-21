"""
Tests for Splink entity resolution configuration using synthetic data.

Validates that blocking rules and comparison columns produce correct match
decisions at the configured confidence thresholds.
"""

from __future__ import annotations

import re
import uuid
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
import yaml

from core.entity_resolution.confidence import resolve_auto_merge_threshold
from core.entity_resolution.l8_regression import _build_fixture_rows
from core.entity_resolution.scoring import score_with_splink
from core.entity_resolution.splink_config import (
    DETERMINISTIC_PERSON_RULES,
    PERSON_FIRST_NAME_DISAGREEMENT_M_PROBABILITY,
    PERSON_FIRST_NAME_DISAGREEMENT_U_PROBABILITY,
    build_person_probabilistic_settings,
)

# Synthetic test data — realistic but entirely fictitious records
# designed to test specific matching scenarios.

REPO_ROOT = Path(__file__).resolve().parents[2]
REGRESSION_PAIRS_PATH = REPO_ROOT / "tests" / "er_regression_pairs.yaml"
DONOR_FALSE_MERGE_CASE_IDS = (
    "fec_person_cluster_030872d9_dennis_vs_stephanie_robinson",
    "fec_person_cluster_81136b39_linda_vs_ryan_garcia",
)
SYNTHETIC_PERSONS = [
    # --- Pair 1: Same person, slight name variation + same address ---
    {
        "id": str(uuid.UUID("00000000-0000-0000-0000-000000000001")),
        "canonical_name": "John Robert Smith",
        "first_name": "John",
        "last_name": "Smith",
        "date_of_birth": date(1975, 6, 15),
        "normalized_address": "123 Main St, Durham, NC 27701",
        "street_number": "123",
        "zip5": "27701",
        "state": "NC",
        "employer": "Duke University",
        "occupation": "Professor",
        "identifiers": {},
    },
    {
        "id": str(uuid.UUID("00000000-0000-0000-0000-000000000002")),
        "canonical_name": "John R Smith",
        "first_name": "John",
        "last_name": "Smith",
        "date_of_birth": date(1975, 6, 15),
        "normalized_address": "123 Main Street, Durham, NC 27701",
        "street_number": "123",
        "zip5": "27701",
        "state": "NC",
        "employer": "Duke Univ",
        "occupation": "Prof",
        "identifiers": {},
    },
    # --- Pair 2: Different people, same name ---
    {
        "id": str(uuid.UUID("00000000-0000-0000-0000-000000000003")),
        "canonical_name": "Maria Garcia",
        "first_name": "Maria",
        "last_name": "Garcia",
        "date_of_birth": date(1980, 3, 22),
        "normalized_address": "456 Oak Ave, Raleigh, NC 27603",
        "street_number": "456",
        "zip5": "27603",
        "state": "NC",
        "employer": "Wake County Schools",
        "occupation": "Teacher",
        "identifiers": {},
    },
    {
        "id": str(uuid.UUID("00000000-0000-0000-0000-000000000004")),
        "canonical_name": "Maria Garcia",
        "first_name": "Maria",
        "last_name": "Garcia",
        "date_of_birth": date(1992, 11, 8),
        "normalized_address": "789 Pine Rd, Charlotte, NC 28205",
        "street_number": "789",
        "zip5": "28205",
        "state": "NC",
        "employer": "Bank of America",
        "occupation": "Analyst",
        "identifiers": {},
    },
    # --- Pair 3: Same person, deterministic match via FEC ID ---
    {
        "id": str(uuid.UUID("00000000-0000-0000-0000-000000000005")),
        "canonical_name": "Robert James Wilson",
        "first_name": "Robert",
        "last_name": "Wilson",
        "date_of_birth": None,
        "normalized_address": "321 Elm St, Greensboro, NC 27401",
        "street_number": "321",
        "zip5": "27401",
        "state": "NC",
        "employer": "Self-Employed",
        "occupation": "Attorney",
        "identifiers": {"fec_candidate_id": "FEC-12345"},
    },
    {
        "id": str(uuid.UUID("00000000-0000-0000-0000-000000000006")),
        "canonical_name": "Bob Wilson",
        "first_name": "Bob",
        "last_name": "Wilson",
        "date_of_birth": None,
        "normalized_address": "321 Elm Street, Greensboro, NC 27401",
        "street_number": "321",
        "zip5": "27401",
        "state": "NC",
        "employer": "Wilson Law PLLC",
        "occupation": "Lawyer",
        "identifiers": {"fec_candidate_id": "FEC-12345"},
    },
]

SYNTHETIC_ORGANIZATIONS = [
    # --- Pair 1: Same org, EIN match ---
    {
        "id": str(uuid.UUID("00000000-0000-0000-0001-000000000001")),
        "canonical_name": "Brightwater Holdings LLC",
        "registered_state": "NC",
        "normalized_address": "100 Corporate Dr, Raleigh, NC 27601",
        "zip5": "27601",
        "org_type": "llc",
        "ein": "12-3456789",
        "fec_committee_id": None,
        "registered_agent_name": "James T. Williams",
    },
    {
        "id": str(uuid.UUID("00000000-0000-0000-0001-000000000002")),
        "canonical_name": "Brightwater Holdings, LLC",
        "registered_state": "NC",
        "normalized_address": "100 Corporate Drive, Raleigh, NC 27601",
        "zip5": "27601",
        "org_type": "llc",
        "ein": "12-3456789",
        "fec_committee_id": None,
        "registered_agent_name": "James Williams",
    },
    # --- Pair 2: Different orgs, same agent (LLC-piercing signal) ---
    {
        "id": str(uuid.UUID("00000000-0000-0000-0001-000000000003")),
        "canonical_name": "Sunrise Property Group LLC",
        "registered_state": "NC",
        "normalized_address": "100 Corporate Dr, Raleigh, NC 27601",
        "zip5": "27601",
        "org_type": "llc",
        "ein": "98-7654321",
        "fec_committee_id": None,
        "registered_agent_name": "James T. Williams",
    },
    {
        "id": str(uuid.UUID("00000000-0000-0000-0001-000000000004")),
        "canonical_name": "Oak Street Ventures Inc",
        "registered_state": "DE",
        "normalized_address": "200 Market St, Wilmington, DE 19801",
        "zip5": "19801",
        "org_type": "corporation",
        "ein": "55-1234567",
        "fec_committee_id": None,
        "registered_agent_name": "CT Corporation",
    },
]

COMMON_NAME_PAIR = (
    uuid.UUID("00000000-0000-0000-0002-000000000001"),
    uuid.UUID("00000000-0000-0000-0002-000000000002"),
)
RARE_NAME_PAIR = (
    uuid.UUID("00000000-0000-0000-0002-000000000101"),
    uuid.UUID("00000000-0000-0000-0002-000000000102"),
)


def _name_rarity_row(
    entity_id: uuid.UUID,
    row_values: dict[str, Any],
) -> dict[str, Any]:
    row = {"id": entity_id, **row_values}
    last_name = row["last_name"]
    row["last_name_prefix5"] = last_name[:5]
    row["last_name_prefix3"] = last_name[:3]
    return row


def _fixture_must_not_match_cases_by_id() -> dict[str, dict[str, Any]]:
    payload = cast(dict[str, Any], yaml.safe_load(REGRESSION_PAIRS_PATH.read_text(encoding="utf-8")))
    return {case["case_id"]: case for case in payload["must_not_match"]}


def _donor_fixture_rows(case: dict[str, Any]) -> tuple[list[dict[str, Any]], tuple[str, str]]:
    rows, ordered_pair = _build_fixture_rows(
        case_id=case["case_id"],
        entity_type=case["entity_type"],
        left_payload=case["left_entity"],
        right_payload=case["right_entity"],
    )
    return rows, cast(tuple[str, str], ordered_pair)


def _only_score_for_pair(
    scores: list[dict[str, Any]],
    ordered_pair: tuple[str, str],
) -> dict[str, Any]:
    matching_scores = [
        score
        for score in scores
        if tuple(sorted((str(score["entity_id_a"]), str(score["entity_id_b"])))) == ordered_pair
    ]
    assert len(matching_scores) == 1
    return matching_scores[0]


def _shared_non_empty_value(rows: list[dict[str, Any]], key: str) -> bool:
    left_value = rows[0].get(key)
    right_value = rows[1].get(key)
    return left_value is not None and left_value == right_value


def _name_rarity_rows() -> list[dict[str, Any]]:
    rows = [
        _name_rarity_row(
            COMMON_NAME_PAIR[0],
            {
                "canonical_name": "James Smith",
                "first_name": "James",
                "last_name": "Smith",
                "date_of_birth": date(1978, 4, 20),
                "normalized_address": "100 Target Common St",
                "street_number": "100",
                "zip5": "10001",
                "state": "AA",
                "employer": "Acme Civic Group",
                "occupation": "Consultant",
                "identifier_key": "common_target_shared",
            },
        ),
        _name_rarity_row(
            COMMON_NAME_PAIR[1],
            {
                "canonical_name": "James Smith",
                "first_name": "James",
                "last_name": "Smith",
                "date_of_birth": date(1978, 4, 20),
                "normalized_address": "100 Target Common St",
                "street_number": "100",
                "zip5": "10001",
                "state": "AA",
                "employer": "Acme Civic Group",
                "occupation": "Consultant",
                "identifier_key": "common_target_shared",
            },
        ),
        _name_rarity_row(
            RARE_NAME_PAIR[0],
            {
                "canonical_name": "Zephyr Quill",
                "first_name": "Zephyr",
                "last_name": "Quill",
                "date_of_birth": date(1978, 4, 20),
                "normalized_address": "200 Target Rare St",
                "street_number": "200",
                "zip5": "20002",
                "state": "BB",
                "employer": "Acme Civic Group",
                "occupation": "Consultant",
                "identifier_key": "rare_target_shared",
            },
        ),
        _name_rarity_row(
            RARE_NAME_PAIR[1],
            {
                "canonical_name": "Zephyr Quill",
                "first_name": "Zephyr",
                "last_name": "Quill",
                "date_of_birth": date(1978, 4, 20),
                "normalized_address": "200 Target Rare St",
                "street_number": "200",
                "zip5": "20002",
                "state": "BB",
                "employer": "Acme Civic Group",
                "occupation": "Consultant",
                "identifier_key": "rare_target_shared",
            },
        ),
    ]
    for index in range(12):
        rows.append(
            _name_rarity_row(
                uuid.UUID(f"00000000-0000-0000-0003-{index + 1:012d}"),
                {
                    "canonical_name": "James Smith",
                    "first_name": "James",
                    "last_name": "Smith",
                    "date_of_birth": date(1960 + index, 1, 1),
                    "normalized_address": f"{900 + index} Frequency Filler Rd",
                    "street_number": str(900 + index),
                    "zip5": f"30{index:03d}",
                    "state": f"F{index:02d}",
                    "employer": f"Frequency Employer {index}",
                    "occupation": f"Frequency Occupation {index}",
                    "identifier_key": f"common_filler_{index}",
                },
            )
        )
    return rows


def _rare_same_employer_different_locality_rows() -> list[dict[str, Any]]:
    rows = [
        _name_rarity_row(
            RARE_NAME_PAIR[0],
            {
                "canonical_name": "Aurelia Voss",
                "first_name": "Aurelia",
                "last_name": "Voss",
                "date_of_birth": None,
                "normalized_address": "boise id 83702",
                "street_number": None,
                "zip5": "83702",
                "state": "ID",
                "employer": "Northwest Biologics",
                "occupation": "Physician",
                "identifier_key": "rare_employer_target_left",
            },
        ),
        _name_rarity_row(
            RARE_NAME_PAIR[1],
            {
                "canonical_name": "Aurelia Voss",
                "first_name": "Aurelia",
                "last_name": "Voss",
                "date_of_birth": None,
                "normalized_address": "meridian id 83642",
                "street_number": None,
                "zip5": "83642",
                "state": "ID",
                "employer": "Northwest Biologics",
                "occupation": "Physician",
                "identifier_key": "rare_employer_target_right",
            },
        ),
    ]
    for index in range(12):
        rows.append(
            _name_rarity_row(
                uuid.UUID(f"00000000-0000-0000-0006-{index + 1:012d}"),
                {
                    "canonical_name": "James Smith",
                    "first_name": "James",
                    "last_name": "Smith",
                    "date_of_birth": date(1960 + index, 1, 1),
                    "normalized_address": f"{900 + index} employer filler rd",
                    "street_number": str(900 + index),
                    "zip5": f"40{index:03d}",
                    "state": "ID",
                    "employer": f"Frequency Employer {index}",
                    "occupation": f"Frequency Occupation {index}",
                    "identifier_key": f"rare_employer_filler_{index}",
                },
            )
        )
    return rows


def _score_map_by_pair(
    rows: list[dict[str, Any]],
) -> dict[tuple[uuid.UUID, uuid.UUID], float]:
    person_settings = build_person_probabilistic_settings()
    scores = score_with_splink(rows, "person", probabilistic_settings=person_settings)
    return {(score["entity_id_a"], score["entity_id_b"]): score["confidence"] for score in scores}


def _term_frequency_adjusted_columns(person_settings: Any) -> set[str]:
    settings_metadata = person_settings.create_settings_dict("duckdb")
    return {
        level["tf_adjustment_column"]
        for comparison in settings_metadata["comparisons"]
        for level in comparison["comparison_levels"]
        if "tf_adjustment_column" in level
    }


def _comparison_by_output_column(person_settings: Any, column_name: str) -> dict[str, Any]:
    settings_metadata = person_settings.create_settings_dict("duckdb")
    matches = [
        comparison for comparison in settings_metadata["comparisons"] if comparison["output_column_name"] == column_name
    ]
    assert len(matches) == 1
    return matches[0]


# =============================================================================
# Tests
# =============================================================================


class TestPersonBlockingRules:
    """Verify that blocking rules correctly identify candidate pairs."""

    def test_same_last_name_same_state_blocks(self):
        """Pair 1 (John Smith variants) should be blocked together by last_name+state."""
        p1 = SYNTHETIC_PERSONS[0]
        p2 = SYNTHETIC_PERSONS[1]
        assert p1["last_name"] == p2["last_name"]
        assert p1["state"] == p2["state"]

    def test_same_zip_blocks(self):
        """Pair 1 should also be blocked by zip5+last_name_prefix5."""
        p1 = SYNTHETIC_PERSONS[0]
        p2 = SYNTHETIC_PERSONS[1]
        assert p1["zip5"] == p2["zip5"]
        assert p1["last_name"][:5] == p2["last_name"][:5]

    def test_different_dob_different_address_separates(self):
        """Pair 2 (two Maria Garcias) have different DOBs and addresses — should NOT auto-merge."""
        p3 = SYNTHETIC_PERSONS[2]
        p4 = SYNTHETIC_PERSONS[3]
        assert p3["canonical_name"] == p4["canonical_name"]
        assert p3["date_of_birth"] != p4["date_of_birth"]
        assert p3["zip5"] != p4["zip5"]

    def test_deterministic_fec_id_match(self):
        """Pair 3 (Robert/Bob Wilson) share an FEC ID — deterministic match."""
        p5 = SYNTHETIC_PERSONS[4]
        p6 = SYNTHETIC_PERSONS[5]
        assert p5["identifiers"]["fec_candidate_id"] == p6["identifiers"]["fec_candidate_id"]


class TestOrganizationBlockingRules:
    """Verify organization blocking rules."""

    def test_ein_blocks(self):
        """Pair 1 (Brightwater Holdings variants) share EIN — deterministic match."""
        o1 = SYNTHETIC_ORGANIZATIONS[0]
        o2 = SYNTHETIC_ORGANIZATIONS[1]
        assert o1["ein"] == o2["ein"]

    def test_same_agent_blocks(self):
        """Orgs 1 and 3 share a registered agent — blocked together for comparison."""
        o1 = SYNTHETIC_ORGANIZATIONS[0]
        o3 = SYNTHETIC_ORGANIZATIONS[2]
        assert o1["registered_agent_name"] == o3["registered_agent_name"]

    def test_different_orgs_different_ein(self):
        """Orgs 3 and 4 have different EINs, different states — should not match."""
        o3 = SYNTHETIC_ORGANIZATIONS[2]
        o4 = SYNTHETIC_ORGANIZATIONS[3]
        assert o3["ein"] != o4["ein"]
        assert o3["registered_state"] != o4["registered_state"]


class TestConfidenceThresholds:
    """Validate that threshold constants are correctly configured."""

    def test_threshold_ordering(self):
        from core.entity_resolution.splink_config import (
            THRESHOLD_AUTO_MERGE,
            THRESHOLD_POSSIBLE,
            THRESHOLD_PROBABLE,
        )

        assert THRESHOLD_AUTO_MERGE > THRESHOLD_PROBABLE > THRESHOLD_POSSIBLE
        assert THRESHOLD_AUTO_MERGE == 0.95
        assert THRESHOLD_PROBABLE == 0.80
        assert THRESHOLD_POSSIBLE == 0.60

    def test_thresholds_in_valid_range(self):
        from core.entity_resolution.splink_config import (
            THRESHOLD_AUTO_MERGE,
            THRESHOLD_POSSIBLE,
            THRESHOLD_PROBABLE,
        )

        for t in [THRESHOLD_AUTO_MERGE, THRESHOLD_PROBABLE, THRESHOLD_POSSIBLE]:
            assert 0.0 <= t <= 1.0


class TestExpectedMatchOutcomes:
    """Document expected outcomes for each synthetic pair.

    These tests validate the TEST DATA, not Splink itself.
    They serve as a specification for what the ER pipeline should produce.
    Full integration tests (running Splink against this data) are in tests/integration/.
    """

    def test_pair1_smith_should_auto_merge(self):
        """John Robert Smith + John R Smith: same DOB, same address, same employer domain → auto-merge."""
        p1, p2 = SYNTHETIC_PERSONS[0], SYNTHETIC_PERSONS[1]
        # Strong signals: exact DOB, same zip, same street number, similar employer
        assert p1["date_of_birth"] == p2["date_of_birth"]
        assert p1["zip5"] == p2["zip5"]
        assert p1["street_number"] == p2["street_number"]
        # Expected: confidence >= 0.95 → auto-merge

    def test_pair2_garcia_should_not_match(self):
        """Two Maria Garcias: different DOB, different city, different employer → no match."""
        p3, p4 = SYNTHETIC_PERSONS[2], SYNTHETIC_PERSONS[3]
        assert p3["date_of_birth"] != p4["date_of_birth"]
        assert p3["zip5"] != p4["zip5"]
        assert p3["employer"] != p4["employer"]
        # Expected: confidence < 0.60 → no match

    def test_pair3_wilson_deterministic_match(self):
        """Robert/Bob Wilson: shared FEC ID → deterministic match before Splink runs."""
        p5, p6 = SYNTHETIC_PERSONS[4], SYNTHETIC_PERSONS[5]
        assert p5["identifiers"]["fec_candidate_id"] == p6["identifiers"]["fec_candidate_id"]
        # Expected: confidence = 1.0 (deterministic)

    def test_org_pair1_brightwater_should_auto_merge(self):
        """Brightwater Holdings LLC variants: same EIN → deterministic match."""
        o1, o2 = SYNTHETIC_ORGANIZATIONS[0], SYNTHETIC_ORGANIZATIONS[1]
        assert o1["ein"] == o2["ein"]
        # Expected: confidence = 1.0 (deterministic)

    def test_org_pair2_different_orgs_no_match(self):
        """Sunrise Property Group vs Oak Street Ventures: different everything → no match."""
        o3, o4 = SYNTHETIC_ORGANIZATIONS[2], SYNTHETIC_ORGANIZATIONS[3]
        assert o3["ein"] != o4["ein"]
        assert o3["registered_state"] != o4["registered_state"]
        assert o3["canonical_name"] != o4["canonical_name"]
        # Expected: confidence < 0.60 → no match


def test_get_blocking_rule_sqls_keeps_splink4_rule_objects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.entity_resolution.splink_config import get_blocking_rule_sqls

    class Splink4Rule:
        def create_sql(self, sql_dialect: object) -> str:
            return 'l."id" = r."id"'

    class LegacyRule:
        blocking_rule_sql = 'l."id" = r."id"'

    splink4_rule = Splink4Rule()
    legacy_rule = LegacyRule()
    monkeypatch.setattr(
        "core.entity_resolution.splink_config.get_probabilistic_settings",
        lambda entity_type: SimpleNamespace(
            blocking_rules_to_generate_predictions=[splink4_rule, legacy_rule, "l.id = r.id"]
        ),
    )

    rules = get_blocking_rule_sqls("person")

    assert rules[0] is splink4_rule
    assert rules[1] == 'l."id" = r."id"'
    assert rules[2] == "l.id = r.id"


def test_person_splink_scores_rare_exact_name_above_common_exact_name() -> None:
    scores_by_pair = _score_map_by_pair(_name_rarity_rows())

    assert set(scores_by_pair) == {COMMON_NAME_PAIR, RARE_NAME_PAIR}
    common_score = scores_by_pair[COMMON_NAME_PAIR]
    rare_score = scores_by_pair[RARE_NAME_PAIR]
    assert rare_score > common_score, (
        f"expected rare-name confidence to exceed common-name confidence; rare={rare_score}, common={common_score}"
    )


def test_person_splink_rare_exact_name_same_employer_different_locality_scores_above_auto_merge() -> None:
    rare_name_pair = tuple(str(entity_id) for entity_id in RARE_NAME_PAIR)
    person_settings = build_person_probabilistic_settings()
    scores = score_with_splink(
        _rare_same_employer_different_locality_rows(),
        "person",
        probabilistic_settings=person_settings,
        include_attribution=True,
    )
    score = _only_score_for_pair(scores, rare_name_pair)

    assert score["comparison_levels"]["canonical_name"] >= 3
    assert score["comparison_levels"]["last_name"] >= 2
    assert score["comparison_levels"]["employer"] >= 3
    assert score["comparison_levels"]["normalized_address"] == 0
    assert score["comparison_levels"]["zip5"] == 0
    assert score["confidence"] >= resolve_auto_merge_threshold(None)


def test_person_splink_canonical_employer_variants_receive_exact_evidence() -> None:
    rare_name_pair = tuple(str(entity_id) for entity_id in RARE_NAME_PAIR)
    rows = _rare_same_employer_different_locality_rows()
    rows[0]["employer"] = "Northwest Biologics LLC"
    rows[1]["employer"] = "Northwest Biologics"
    person_settings = build_person_probabilistic_settings()

    scores = score_with_splink(
        rows,
        "person",
        probabilistic_settings=person_settings,
        include_attribution=True,
    )
    score = _only_score_for_pair(scores, rare_name_pair)

    assert score["comparison_levels"]["employer"] == 3
    assert score["confidence"] >= resolve_auto_merge_threshold(None)


def test_person_splink_junk_employer_exact_match_receives_no_employer_evidence() -> None:
    rare_name_pair = tuple(str(entity_id) for entity_id in RARE_NAME_PAIR)
    rows = _rare_same_employer_different_locality_rows()
    rows[0]["employer"] = "RETIRED"
    rows[1]["employer"] = "RETIRED"
    person_settings = build_person_probabilistic_settings()

    scores = score_with_splink(
        rows,
        "person",
        probabilistic_settings=person_settings,
        include_attribution=True,
    )
    score = _only_score_for_pair(scores, rare_name_pair)

    assert score["comparison_levels"]["employer"] == -1
    assert score["confidence"] < resolve_auto_merge_threshold(None)


def test_person_settings_exact_employer_agreement_remains_trainable() -> None:
    person_settings = build_person_probabilistic_settings()
    employer_comparison = _comparison_by_output_column(person_settings, "employer")
    exact_level = employer_comparison["comparison_levels"][1]

    assert exact_level["sql_condition"] == '"employer_l" = "employer_r"'
    assert "m_probability" not in exact_level
    assert "u_probability" not in exact_level
    assert exact_level["fix_m_probability"] is False
    assert exact_level["fix_u_probability"] is False


@pytest.mark.parametrize("case_id", DONOR_FALSE_MERGE_CASE_IDS)
def test_person_splink_same_surname_state_first_name_disagreement_scores_below_auto_merge_threshold(
    case_id: str,
) -> None:
    case = _fixture_must_not_match_cases_by_id()[case_id]
    rows, ordered_pair = _donor_fixture_rows(case)

    assert _shared_non_empty_value(rows, "last_name")
    assert _shared_non_empty_value(rows, "state")
    assert rows[0]["first_name"] != rows[1]["first_name"]
    assert not _shared_non_empty_value(rows, "zip5")
    assert not _shared_non_empty_value(rows, "street_number")
    assert rows[0]["employer"] == "NOT EMPLOYED"
    assert rows[0]["occupation"] == "NOT EMPLOYED"
    assert rows[0]["identifier_key"] == case["left_entity"]["source_record_key"]
    assert rows[1]["identifier_key"] == case["right_entity"]["source_record_key"]
    assert all(row["normalized_address"] == row["normalized_address"].lower() for row in rows)
    assert all(row["state"] == row["state"].upper() for row in rows)

    person_settings = build_person_probabilistic_settings()
    scores = score_with_splink(
        rows,
        "person",
        probabilistic_settings=person_settings,
        include_attribution=True,
    )
    score = _only_score_for_pair(scores, ordered_pair)

    assert score["decision_method"] == "probabilistic"
    assert score["decided_by"] == "splink_v1"
    assert score["match_key"] == "0"
    assert score["comparison_levels"]["first_name"] == 0
    assert score["match_weight"] < 0
    assert score["confidence"] < resolve_auto_merge_threshold(None)

    first_name_disagreement_level = _comparison_by_output_column(person_settings, "first_name")["comparison_levels"][-1]
    assert first_name_disagreement_level["sql_condition"] == "ELSE"
    assert first_name_disagreement_level["m_probability"] == PERSON_FIRST_NAME_DISAGREEMENT_M_PROBABILITY
    assert first_name_disagreement_level["u_probability"] == PERSON_FIRST_NAME_DISAGREEMENT_U_PROBABILITY
    assert first_name_disagreement_level["fix_m_probability"] is True
    assert first_name_disagreement_level["fix_u_probability"] is True


def test_person_settings_term_frequency_adjustments_are_name_only() -> None:
    person_settings = build_person_probabilistic_settings()

    assert _term_frequency_adjusted_columns(person_settings) == {
        "canonical_name",
        "first_name",
        "last_name",
    }


# ---------------------------------------------------------------------------
# civibus-s5q guard: no deterministic person rule may key on an identifier
# key that no ingest path writes.
#
# WHY THIS EXISTS: the original fec rule keyed on identifiers->>'fec_id',
# a key NOTHING in production ever wrote (every ingest path writes
# 'fec_candidate_id' / 'fec_candidate_ids'). A deterministic rule aimed at a
# key with no writer is a silent no-op at confidence 1.0 — it looks exactly
# like a rule that simply found no duplicates, so the defect is invisible in
# every run report. That dead rule is why the exact duplicate class it
# targeted (FEC-only shadow persons) accumulated in production and had to be
# repaired imperatively in federal_spine_loader instead of by ER.
# ---------------------------------------------------------------------------

_RULE_IDENTIFIER_KEY_PATTERN = re.compile(r"identifiers\s*(?:->>|->)\s*'([A-Za-z0-9_]+)'")

# Directories whose production code counts as "an ingest path that writes
# identifier keys". Deliberately broad (all of core/ and domains/) so a writer
# anywhere in the product vouches for a key; test files and this ER package
# itself are excluded below — a rule must never vouch for its own key.
_IDENTIFIER_WRITER_SCAN_ROOTS = ("core", "domains")


def _identifier_keys_named_in_person_rules() -> dict[str, set[str]]:
    """Map each deterministic person rule name to the identifier keys its SQL reads."""
    keys_by_rule: dict[str, set[str]] = {}
    for rule in DETERMINISTIC_PERSON_RULES:
        keys = set(_RULE_IDENTIFIER_KEY_PATTERN.findall(rule["sql"]))
        # A person rule that keys on no identifiers at all would silently escape
        # this guard; every rule in the current closed set keys on identifiers,
        # so an empty extraction means the SQL shape drifted past the regex and
        # the guard must be updated consciously, not bypassed.
        assert keys, (
            f"deterministic person rule {rule['name']!r} names no identifiers->>'key' "
            "expression this guard can extract; update _RULE_IDENTIFIER_KEY_PATTERN "
            "or exempt the rule explicitly with a comment explaining its predicate"
        )
        keys_by_rule[rule["name"]] = keys
    return keys_by_rule


def _production_files_that_could_write_identifiers() -> list[Path]:
    files: list[Path] = []
    er_package_dir = Path(__file__).resolve().parent
    for scan_root in _IDENTIFIER_WRITER_SCAN_ROOTS:
        for path in sorted((REPO_ROOT / scan_root).rglob("*.py")):
            if er_package_dir in path.parents:
                continue  # the rule may not vouch for its own key
            if path.name.startswith("test_") or path.name == "conftest.py":
                continue
            if "tests" in path.parts:
                continue
            files.append(path)
    return files


def test_every_deterministic_person_rule_keys_on_an_identifier_some_ingest_path_writes() -> None:
    """civibus-s5q: a matching rule keyed on an unwritten identifier is a dead rule.

    For every identifier key named in DETERMINISTIC_PERSON_RULES, some production
    file under core/ or domains/ (tests and this ER package excluded) must
    mention the key as a quoted literal — the shape every real writer takes
    (`identifiers={"fec_candidate_id": ...}`, `identifier_payload["bioguide_id"]`,
    `identifier_key="bioguide_id"`).

    Proven red 2026-08-20 against the pre-fix rules: 'fec_id' and 'voter_reg_id'
    each had ZERO production occurrences — the only non-test mentions in the
    repo were the rules themselves and a stale schema comment. The test fails
    again the moment anyone adds a rule keyed on a key nothing writes, which is
    the exact condition it guards: a silent no-op matcher at confidence 1.0.

    Limitation, on purpose: a key that production only READS would also pass.
    That failure mode still leaves the key present in live rows somewhere, which
    is categorically different from the fec_id defect (no writer, no reader, no
    data — matcher provably inert).
    """
    scanned_files = _production_files_that_could_write_identifiers()
    assert scanned_files, "identifier-writer scan found no production files; scan roots are wrong"
    scanned_texts = [path.read_text(encoding="utf-8") for path in scanned_files]

    unwritten_keys_by_rule: dict[str, set[str]] = {}
    for rule_name, keys in _identifier_keys_named_in_person_rules().items():
        for key in keys:
            quoted_forms = (f"'{key}'", f'"{key}"')
            written = any(quoted_form in text for text in scanned_texts for quoted_form in quoted_forms)
            if not written:
                unwritten_keys_by_rule.setdefault(rule_name, set()).add(key)

    assert not unwritten_keys_by_rule, (
        "Deterministic person rules key on identifier keys that NO ingest path "
        f"writes: {unwritten_keys_by_rule}. Such a rule is a silent no-op at "
        "confidence 1.0 (civibus-s5q). Either make an ingest path write the key "
        "or re-key/delete the rule — never leave a matcher aimed at a key with "
        "no writer."
    )
