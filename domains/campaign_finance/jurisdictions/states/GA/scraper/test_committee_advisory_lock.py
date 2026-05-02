"""Unit test verifying _resolve_ga_committee_id acquires an advisory lock."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from core.types.python.models import Organization

from domains.campaign_finance.jurisdictions.states.GA.scraper import load as ga_load


def test_resolve_ga_committee_id_acquires_advisory_lock_for_known_identifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When a ga_filer_id is present, the function should acquire an advisory lock
    before checking for an existing organization."""
    mock_conn = MagicMock()
    existing_id = uuid4()

    monkeypatch.setattr(ga_load, "find_organization_by_identifier", lambda _c, _k, _v: existing_id)

    committee = Organization(
        canonical_name="TEST COMMITTEE FOR GA",
        identifiers={"ga_filer_id": "C2026000123"},
    )
    result = ga_load._resolve_ga_committee_id(mock_conn, committee)

    advisory_calls = [call for call in mock_conn.execute.call_args_list if "pg_advisory_xact_lock" in str(call)]
    assert len(advisory_calls) == 1, "Expected exactly one advisory lock call"
    assert result == existing_id


def test_resolve_ga_committee_id_no_lock_without_identifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When no ga_filer_id is present, no advisory lock should be acquired."""
    mock_conn = MagicMock()
    new_id = uuid4()

    monkeypatch.setattr(ga_load, "insert_organization", lambda _c, _o: new_id)

    committee = Organization(
        canonical_name="UNKNOWN GA COMMITTEE",
        identifiers={},
    )
    result = ga_load._resolve_ga_committee_id(mock_conn, committee)

    advisory_calls = [call for call in mock_conn.execute.call_args_list if "pg_advisory_xact_lock" in str(call)]
    assert len(advisory_calls) == 0, "No advisory lock expected without identifier"
    assert result == new_id
