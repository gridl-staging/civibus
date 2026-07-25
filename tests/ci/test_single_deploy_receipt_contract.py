"""Contract tests for the July 2026 single-deploy recovery receipt."""

from __future__ import annotations

import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
RECEIPT_PATH = REPO_ROOT / "docs/live-state/2026_07_24_single_deploy.md"
ROADMAP_PATH = REPO_ROOT / "ROADMAP.md"
UPTIME_PROBE_WORKFLOW_PATH = REPO_ROOT / ".github/workflows/uptime_probe.yml"

RECEIPT_RELATIVE_PATH = "docs/live-state/2026_07_24_single_deploy.md"
EXPECTED_CLOSED_TITLES = {
    "Large merged-but-undeployed delta",
    "CI does not run most of the suite",
}

REQUIRED_RECEIPT_TOKENS = (
    "d4a63ed40fd77c1a2f465654cbf59c2a4217465e",
    "d1d14ef235bd76170e8634201cec03dfe20fe585",
    "30159110547",
    "each_key_duplicate",
    "cm:2026:C00718866",
    "key-metrics",
    "19-candidate unsafe-identity gap",
    "L5 stopped RED",
    "L5R stopped RED",
    "6943e6b2cc3da2600115393538ee7204b6d1a6c0",
    "563643e3d9dc857738574ae924e044cef56fd64f",
    "607953323b81973669bd98f50ae568de988ef51f",
    "1af3e2e106f831ea119f599fbfacb0ac2aaf3770",
    "30171349290",
    "https://github.com/gridl-staging/civibus/actions/runs/30171349290",
    "30171349288",
    "https://github.com/gridl-staging/civibus/actions/runs/30171349288",
    "30171507412",
    "https://github.com/gridl-hq/civibus/actions/runs/30171507412",
    "89713328037",
    "https://github.com/gridl-hq/civibus/actions/runs/30171507412/job/89713328037",
    "4396 collected",
    "3063 selected",
    "3024 passed",
    "39 skipped",
    "1333 deselected",
    "108 files",
    "1065 tests passed",
    "1069 passed, 52 skipped, 2622 deselected",
    "production smoke: 9 passed",
    "API SHA = web SHA = repaired dev SHA = 563643e3d9dc857738574ae924e044cef56fd64f",
    '`/api/health/content` exactly `{"healthy":true}`',
    "Data is current.",
    "2026-07-25",
    "donor `smith` API/page probes HTTP 200 with nonempty rows",
    "donor `johnson` API/page probes HTTP 200 with nonempty rows",
    "surfaces_probed=13 failed=0",
    "candidate_api_total=8249",
    "canonical_eligible_count=7183",
    "sitemap_candidate_count=7183",
    "bare_uuid_candidate_url_count=0",
)

COUPLED_RECEIPT_SNIPPETS = (
    "Rejected original freeze `d4a63ed40fd77c1a2f465654cbf59c2a4217465e`: never accepted as deployed proof.",
    "First deployed-but-RED SHA `d1d14ef235bd76170e8634201cec03dfe20fe585`: prod Deploy run `30159110547` reached the production smoke gate and failed.",
    "Batman repair merge `6943e6b2cc3da2600115393538ee7204b6d1a6c0` produced repaired dev `563643e3d9dc857738574ae924e044cef56fd64f`.",
    "Prod Deploy run `30171507412` for prod SHA `1af3e2e106f831ea119f599fbfacb0ac2aaf3770` passed job `89713328037`.",
    "sitemap oracle on repaired dev `563643e3d9dc857738574ae924e044cef56fd64f`: candidate_api_total=8249, canonical_eligible_count=7183, sitemap_candidate_count=7183, bare_uuid_candidate_url_count=0.",
)


def _assert_receipt_contract(receipt_text: str) -> None:
    missing_tokens = [token for token in REQUIRED_RECEIPT_TOKENS if token not in receipt_text]
    assert missing_tokens == []

    missing_coupled_snippets = [snippet for snippet in COUPLED_RECEIPT_SNIPPETS if snippet not in receipt_text]
    assert missing_coupled_snippets == []


def _roadmap_rows(roadmap_text: str) -> dict[str, str]:
    rows: dict[str, str] = {}
    for line in roadmap_text.splitlines():
        match = re.match(r"^\| P\d \| (?P<title>.+?) — .+? \|", line)
        if match:
            rows[match.group("title")] = line
    return rows


def _closed_pass_titles_for_date(roadmap_text: str, close_date: str) -> set[str]:
    closed_titles: set[str] = set()
    for title, row in _roadmap_rows(roadmap_text).items():
        if f"**CLOSED/PASS {close_date}**" in row:
            closed_titles.add(title)
    return closed_titles


def _assert_roadmap_contract(roadmap_text: str, uptime_probe_workflow_text: str) -> None:
    rows = _roadmap_rows(roadmap_text)

    assert _closed_pass_titles_for_date(roadmap_text, "2026-07-25") == EXPECTED_CLOSED_TITLES
    for title in EXPECTED_CLOSED_TITLES:
        assert RECEIPT_RELATIVE_PATH in rows[title]

    assert "Weekly federal refresh terminal RED" in rows
    assert "Serving gates cannot observe endpoint failure" in rows

    deploy_currency_row = rows["Deploy currency"]
    assert "**CLOSED/PASS 2026-07-17**" in deploy_currency_row
    assert "Promotion still not done" in deploy_currency_row
    assert "continue-on-error: true" in deploy_currency_row
    assert "(2×) in `uptime_probe.yml`" in deploy_currency_row
    assert uptime_probe_workflow_text.count("continue-on-error: true") == 2


@pytest.mark.dev_repo_only(
    private_asset="private single-deploy recovery receipt under docs/live-state/",
    owner="single deploy recovery receipt contract",
)
def test_single_deploy_receipt_contains_fail_closed_recovery_chain() -> None:
    _assert_receipt_contract(RECEIPT_PATH.read_text(encoding="utf-8"))


@pytest.mark.dev_repo_only(
    private_asset="ROADMAP.md and .github/workflows/uptime_probe.yml",
    owner="single deploy recovery receipt contract",
)
def test_roadmap_closes_only_authorized_single_deploy_rows() -> None:
    _assert_roadmap_contract(
        ROADMAP_PATH.read_text(encoding="utf-8"),
        UPTIME_PROBE_WORKFLOW_PATH.read_text(encoding="utf-8"),
    )


def test_receipt_guard_fails_when_required_sha_or_count_is_removed() -> None:
    specimen = "\n".join(REQUIRED_RECEIPT_TOKENS + COUPLED_RECEIPT_SNIPPETS)

    with pytest.raises(AssertionError):
        _assert_receipt_contract(specimen.replace("candidate_api_total=8249", ""))


@pytest.mark.dev_repo_only(
    private_asset="ROADMAP.md and .github/workflows/uptime_probe.yml",
    owner="single deploy recovery receipt contract",
)
def test_roadmap_guard_fails_when_extra_row_closes_on_single_deploy_date() -> None:
    roadmap_text = ROADMAP_PATH.read_text(encoding="utf-8")
    extra_closed_row = "\n| P0 | Deploy currency — **CLOSED/PASS 2026-07-25** | bad closure | bad gate |"

    with pytest.raises(AssertionError):
        _assert_roadmap_contract(
            roadmap_text + extra_closed_row,
            UPTIME_PROBE_WORKFLOW_PATH.read_text(encoding="utf-8"),
        )
