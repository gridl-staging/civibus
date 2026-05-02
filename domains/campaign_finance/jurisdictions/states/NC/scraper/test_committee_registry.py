"""Unit tests locking the NC committee registry row contract.

Validates NCCommitteeRegistryRow against the Stage 1 contract in
docs/research/nc_committee_discovery_contract_2026_04_24.md (lines 100-139).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from domains.campaign_finance.jurisdictions.states.NC.scraper.committee_registry import (
    NC_COMMITTEE_STATUS_VALUES,
    NCCommitteeRegistryRow,
)


class TestNCCommitteeRegistryRowFields:
    def test_valid_row_all_fields(self):
        row = NCCommitteeRegistryRow(
            org_group_id=12345,
            sboe_id="STA-C3672N-C-001",
            committee_name="Friends of Testing",
            status_desc="ACTIVE (NON-EXEMPT)",
            old_id="OLD-123",
            candidate_name="Jane Doe",
        )
        assert row.org_group_id == 12345
        assert row.sboe_id == "STA-C3672N-C-001"
        assert row.committee_name == "Friends of Testing"
        assert row.status_desc == "ACTIVE (NON-EXEMPT)"
        assert row.old_id == "OLD-123"
        assert row.candidate_name == "Jane Doe"

    def test_valid_row_minimal_required(self):
        row = NCCommitteeRegistryRow(
            org_group_id=1,
            sboe_id="STA-TEST-C-001",
            committee_name="Minimal Committee",
            status_desc="CLOSED",
        )
        assert row.old_id is None
        assert row.candidate_name is None

    def test_org_group_id_is_integer_dedupe_key(self):
        row = NCCommitteeRegistryRow(
            org_group_id=58871,
            sboe_id="STA-MAX-C-001",
            committee_name="Max ID Committee",
            status_desc="ACTIVE (EXEMPT)",
        )
        assert isinstance(row.org_group_id, int)

    def test_org_group_id_rejects_non_positive(self):
        with pytest.raises(ValidationError):
            NCCommitteeRegistryRow(
                org_group_id=0,
                sboe_id="STA-ZERO-C-001",
                committee_name="Zero ID",
                status_desc="ACTIVE (EXEMPT)",
            )

        with pytest.raises(ValidationError):
            NCCommitteeRegistryRow(
                org_group_id=-1,
                sboe_id="STA-NEG-C-001",
                committee_name="Negative ID",
                status_desc="ACTIVE (EXEMPT)",
            )

    def test_unexpected_fields_rejected(self):
        with pytest.raises(
            ValidationError,
            match="extra fields not permitted|Extra inputs are not permitted",
        ):
            NCCommitteeRegistryRow(
                org_group_id=1,
                sboe_id="STA-X-C-001",
                committee_name="Unexpected Field Committee",
                status_desc="ACTIVE (EXEMPT)",
                unexpected_field="not-allowed",
            )


class TestNCCommitteeRegistryRowRequired:
    def test_missing_sboe_id_rejected(self):
        with pytest.raises(ValidationError):
            NCCommitteeRegistryRow(
                org_group_id=1,
                committee_name="No SBoE ID",
                status_desc="ACTIVE (EXEMPT)",
            )

    def test_missing_committee_name_rejected(self):
        with pytest.raises(ValidationError):
            NCCommitteeRegistryRow(
                org_group_id=1,
                sboe_id="STA-X-C-001",
                status_desc="ACTIVE (EXEMPT)",
            )

    def test_missing_status_desc_rejected(self):
        with pytest.raises(ValidationError):
            NCCommitteeRegistryRow(
                org_group_id=1,
                sboe_id="STA-X-C-001",
                committee_name="No Status",
            )

    def test_missing_org_group_id_rejected(self):
        with pytest.raises(ValidationError):
            NCCommitteeRegistryRow(
                sboe_id="STA-X-C-001",
                committee_name="No Org ID",
                status_desc="ACTIVE (EXEMPT)",
            )


class TestNCCommitteeRegistryRowNullable:
    def test_old_id_nullable(self):
        row = NCCommitteeRegistryRow(
            org_group_id=1,
            sboe_id="STA-X-C-001",
            committee_name="Test",
            status_desc="CLOSED",
            old_id=None,
        )
        assert row.old_id is None

    def test_candidate_name_nullable(self):
        row = NCCommitteeRegistryRow(
            org_group_id=1,
            sboe_id="STA-X-C-001",
            committee_name="Test",
            status_desc="CLOSED",
            candidate_name=None,
        )
        assert row.candidate_name is None


class TestNCCommitteeRegistryRowStatus:
    def test_all_observed_statuses_accepted(self):
        for status in NC_COMMITTEE_STATUS_VALUES:
            row = NCCommitteeRegistryRow(
                org_group_id=1,
                sboe_id="STA-X-C-001",
                committee_name="Status Test",
                status_desc=status,
            )
            assert row.status_desc == status

    def test_unknown_status_rejected(self):
        with pytest.raises(ValidationError):
            NCCommitteeRegistryRow(
                org_group_id=1,
                sboe_id="STA-X-C-001",
                committee_name="Bad Status",
                status_desc="DISSOLVED",
            )

    def test_status_values_match_contract(self):
        expected = {
            "ACTIVE (EXEMPT)",
            "ACTIVE (NON-EXEMPT)",
            "CLOSED",
            "CLOSED (PENDING)",
            "CONDITIONALLY CLOSED",
            "INACTIVE",
            "TERMINATED",
        }
        assert NC_COMMITTEE_STATUS_VALUES == expected
