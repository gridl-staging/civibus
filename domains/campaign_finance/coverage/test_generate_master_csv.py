from __future__ import annotations

from domains.campaign_finance.coverage.generate_master_csv import _audit_method, _get_portal_url


def test_get_portal_url_uses_current_illinois_bulk_download_page() -> None:
    row = {
        "jurisdiction_code": "IL",
        "jurisdiction_type": "state",
    }

    assert _get_portal_url(row) == "https://elections.il.gov/CampaignDisclosure/DownloadCDDataFiles.aspx"


def test_get_portal_url_reads_municipal_portal_url_for_independent_cities() -> None:
    row = {
        "jurisdiction_code": "CA_SAN_FRANCISCO",
        "jurisdiction_type": "municipality",
        "parent_jurisdiction_code": "CA",
        "municipal_audit_decision": "independent_target",
        "municipal_portal_url": "https://sfethics.org/disclosures/campaign-finance-disclosure",
    }
    assert _get_portal_url(row) == "https://sfethics.org/disclosures/campaign-finance-disclosure"


def test_get_portal_url_falls_back_to_needs_investigation_when_no_municipal_url() -> None:
    row = {
        "jurisdiction_code": "CA_SAN_FRANCISCO",
        "jurisdiction_type": "municipality",
        "parent_jurisdiction_code": "CA",
        "municipal_audit_decision": "independent_target",
    }
    assert _get_portal_url(row) == "needs_investigation"


def test_get_portal_url_covered_by_parent_still_shows_parent_reference() -> None:
    row = {
        "jurisdiction_code": "IL_CHICAGO",
        "jurisdiction_type": "municipality",
        "parent_jurisdiction_code": "IL",
        "municipal_audit_decision": "covered_by_parent",
    }
    assert _get_portal_url(row) == "(see IL)"


def test_audit_method_returns_browser_verified_for_browser_evidence() -> None:
    row = {
        "jurisdiction_code": "CA_SAN_FRANCISCO",
        "jurisdiction_type": "municipality",
        "runner_wired": False,
        "tier": "deferred/blocked",
        "evidence_summary": "Browser-verified city portal research (2026-03-31): SF Ethics Commission",
        "evidence_date": "2026-03-31",
    }
    assert _audit_method(row) == "browser_verified"
