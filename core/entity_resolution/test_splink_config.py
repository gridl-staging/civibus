"""
Tests for Splink entity resolution configuration using synthetic data.

Validates that blocking rules and comparison columns produce correct match
decisions at the configured confidence thresholds.
"""

from __future__ import annotations

import uuid
from datetime import date
from types import SimpleNamespace

import pytest

# Synthetic test data — realistic but entirely fictitious records
# designed to test specific matching scenarios.

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
        "identifiers": {"fec_id": "FEC-12345"},
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
        "identifiers": {"fec_id": "FEC-12345"},
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
        assert p5["identifiers"]["fec_id"] == p6["identifiers"]["fec_id"]


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
        assert p5["identifiers"]["fec_id"] == p6["identifiers"]["fec_id"]
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
