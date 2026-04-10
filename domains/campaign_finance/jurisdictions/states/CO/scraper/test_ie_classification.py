from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from domains.campaign_finance.jurisdictions.states.CO.scraper import load
from domains.campaign_finance.jurisdictions.states.CO.scraper.parse import (
    parse_contributions,
    parse_expenditures,
)

_SAMPLE_CONTRIBUTIONS_PATH = Path(__file__).parent / "test_fixtures" / "sample_contributions.csv"
_SAMPLE_EXPENDITURES_PATH = Path(__file__).parent / "test_fixtures" / "sample_expenditures.csv"


def _collect_committee_key_conflicts(
    rows: list[dict[str, str | None]],
) -> tuple[
    dict[str, set[tuple[str | None, str | None]]],
    dict[tuple[str | None, str | None], set[str]],
]:
    """Collect inconsistent key mappings in both directions."""
    identities_by_co_id: dict[str, set[tuple[str | None, str | None]]] = {}
    co_ids_by_identity: dict[tuple[str | None, str | None], set[str]] = {}

    for row in rows:
        co_id = row.get("CO_ID")
        assert co_id is not None
        identity = (row.get("CommitteeName"), row.get("CommitteeType"))
        identities_by_co_id.setdefault(co_id, set()).add(identity)
        co_ids_by_identity.setdefault(identity, set()).add(co_id)

    conflicting_ids = {co_id: identities for co_id, identities in identities_by_co_id.items() if len(identities) > 1}
    conflicting_identities = {identity: co_ids for identity, co_ids in co_ids_by_identity.items() if len(co_ids) > 1}
    return conflicting_ids, conflicting_identities


def test_co_fixtures_co_id_map_to_single_committee_identity() -> None:
    """A fixture committee key must not alias multiple committee identities."""
    rows = list(parse_contributions(_SAMPLE_CONTRIBUTIONS_PATH))
    rows.extend(parse_expenditures(_SAMPLE_EXPENDITURES_PATH))
    conflicting_ids, conflicting_identities = _collect_committee_key_conflicts(rows)

    assert conflicting_ids == {}
    assert conflicting_identities == {}


def test_fixture_guard_rejects_committee_identity_under_multiple_co_ids() -> None:
    """A committee identity must not appear under multiple CO_ID values."""
    rows = [
        {
            "CO_ID": "20155000008",
            "CommitteeName": "Clean Water Now",
            "CommitteeType": "Issue Committee",
        },
        {
            "CO_ID": "20155009999",
            "CommitteeName": "Clean Water Now",
            "CommitteeType": "Issue Committee",
        },
    ]
    conflicting_ids, conflicting_identities = _collect_committee_key_conflicts(rows)

    assert conflicting_ids == {}
    assert conflicting_identities == {("Clean Water Now", "Issue Committee"): {"20155000008", "20155009999"}}


class TestCoElectioneeringIeClassification:
    """Unit tests for CO electioneering IE classification behavior."""

    @pytest.mark.parametrize("electioneering_value", ["Yes", "true", "1"])
    def test_truthy_electioneering_tokens_get_ie_type(
        self,
        monkeypatch,
        electioneering_value: str,
    ) -> None:
        captured_transactions = []
        monkeypatch.setattr(
            load,
            "upsert_transaction",
            lambda conn, txn: captured_transactions.append(txn),
        )
        monkeypatch.setattr(
            load,
            "resolve_transaction_counterparty_ids",
            lambda conn, **kw: (None, None),
        )

        ie_row = {
            "CO_ID": "20155000008",
            "ExpenditureAmount": "2200.00",
            "ExpenditureDate": "2025-02-04 00:00:00",
            "LastName": "",
            "FirstName": "",
            "Address1": "700 Broadcast Blvd",
            "City": "Denver",
            "State": "CO",
            "Zip": "80205",
            "RecordID": "2004",
            "FiledDate": "2025-02-08 00:00:00",
            "ExpenditureType": "Electioneering Communication",
            "Electioneering": electioneering_value,
            "CommitteeName": "Clean Water Now",
            "Amendment": "N",
            "Employer": None,
            "Occupation": None,
        }
        conn = MagicMock()
        load._upsert_co_transaction_with_filing(
            conn,
            ie_row,
            filing_id=uuid4(),
            committee_id=uuid4(),
            source_record_id=uuid4(),
            data_type="expenditures",
        )
        assert len(captured_transactions) == 1
        assert captured_transactions[0].transaction_type == "Independent Expenditure"
        assert captured_transactions[0].support_oppose is None

    def test_electioneering_expenditure_gets_ie_type(self, monkeypatch) -> None:
        captured_transactions = []
        monkeypatch.setattr(
            load,
            "upsert_transaction",
            lambda conn, txn: captured_transactions.append(txn),
        )
        monkeypatch.setattr(
            load,
            "resolve_transaction_counterparty_ids",
            lambda conn, **kw: (None, None),
        )

        ie_row = {
            "CO_ID": "20155000005",
            "ExpenditureAmount": "2200.00",
            "ExpenditureDate": "2025-02-04 00:00:00",
            "LastName": "",
            "FirstName": "",
            "Address1": "700 Broadcast Blvd",
            "City": "Denver",
            "State": "CO",
            "Zip": "80205",
            "RecordID": "2004",
            "FiledDate": "2025-02-08 00:00:00",
            "ExpenditureType": "Electioneering Communication",
            "Electioneering": "Y",
            "CommitteeName": "Clean Water Now",
            "Amendment": "N",
            "Employer": None,
            "Occupation": None,
        }
        conn = MagicMock()
        load._upsert_co_transaction_with_filing(
            conn,
            ie_row,
            filing_id=uuid4(),
            committee_id=uuid4(),
            source_record_id=uuid4(),
            data_type="expenditures",
        )
        assert len(captured_transactions) == 1
        assert captured_transactions[0].transaction_type == "Independent Expenditure"
        assert captured_transactions[0].support_oppose is None

    def test_non_electioneering_expenditure_keeps_original_type(self, monkeypatch) -> None:
        captured_transactions = []
        monkeypatch.setattr(
            load,
            "upsert_transaction",
            lambda conn, txn: captured_transactions.append(txn),
        )
        monkeypatch.setattr(
            load,
            "resolve_transaction_counterparty_ids",
            lambda conn, **kw: (None, None),
        )

        non_ie_row = {
            "CO_ID": "20155000099",
            "ExpenditureAmount": "500.00",
            "ExpenditureDate": "2025-03-01 00:00:00",
            "LastName": "Smith",
            "FirstName": "Jane",
            "Address1": "100 Test Ave",
            "City": "Denver",
            "State": "CO",
            "Zip": "80202",
            "RecordID": "9999",
            "FiledDate": "2025-03-05 00:00:00",
            "ExpenditureType": "Electioneering Communication",
            "Electioneering": "N",
            "CommitteeName": "Test Committee",
            "Amendment": "N",
            "Employer": None,
            "Occupation": None,
        }
        conn = MagicMock()
        load._upsert_co_transaction_with_filing(
            conn,
            non_ie_row,
            filing_id=uuid4(),
            committee_id=uuid4(),
            source_record_id=uuid4(),
            data_type="expenditures",
        )
        assert len(captured_transactions) == 1
        assert captured_transactions[0].transaction_type == "Electioneering Communication"
        assert captured_transactions[0].support_oppose is None

    def test_electioneering_contribution_does_not_reclassify_to_ie(self, monkeypatch) -> None:
        captured_transactions = []
        monkeypatch.setattr(
            load,
            "upsert_transaction",
            lambda conn, txn: captured_transactions.append(txn),
        )
        monkeypatch.setattr(
            load,
            "resolve_transaction_counterparty_ids",
            lambda conn, **kw: (None, None),
        )

        contribution_row = {
            "CO_ID": "20155000005",
            "ContributionAmount": "400.00",
            "ContributionDate": "2025-01-10 00:00:00",
            "LastName": "Martinez",
            "FirstName": "Carlos",
            "Address1": "800 Oak Blvd",
            "City": "Denver",
            "State": "CO",
            "Zip": "80205",
            "RecordID": "1011",
            "FiledDate": "2025-01-15 00:00:00",
            "ContributionType": "Monetary (Itemized)",
            "Electioneering": "Y",
            "CommitteeName": "Clean Water Now",
            "Amendment": "N",
            "Employer": "Green Corp",
            "Occupation": "Advocate",
        }
        conn = MagicMock()
        load._upsert_co_transaction_with_filing(
            conn,
            contribution_row,
            filing_id=uuid4(),
            committee_id=uuid4(),
            source_record_id=uuid4(),
            data_type="contributions",
        )
        assert len(captured_transactions) == 1
        assert captured_transactions[0].transaction_type == "Monetary (Itemized)"
        assert captured_transactions[0].support_oppose is None


class TestCoIsElectioneeringDirectBranches:
    """Direct tests for _co_is_electioneering edge-case branches."""

    def test_none_electioneering_value_returns_false(self) -> None:
        assert load._co_is_electioneering({"Electioneering": None}) is False

    def test_missing_electioneering_key_returns_false(self) -> None:
        assert load._co_is_electioneering({}) is False

    def test_empty_string_returns_false(self) -> None:
        assert load._co_is_electioneering({"Electioneering": ""}) is False

    def test_whitespace_only_returns_false(self) -> None:
        assert load._co_is_electioneering({"Electioneering": "   "}) is False

    def test_truthy_value_returns_true(self) -> None:
        assert load._co_is_electioneering({"Electioneering": "Yes"}) is True
