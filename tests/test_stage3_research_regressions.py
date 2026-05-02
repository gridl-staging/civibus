from pathlib import Path
import json
import re


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_LICENSING_PATH = REPO_ROOT / "docs" / "research" / "data-licensing.md"
SCRAPING_POLITENESS_PATH = REPO_ROOT / "docs" / "research" / "scraping-politeness.md"
STATE_IE_AUDIT_PATH = REPO_ROOT / "docs" / "research" / "state-ie-coverage-audit.md"
PRIORITIES_PATH = REPO_ROOT / "PRIORITIES.md"
ROADMAP_PATH = REPO_ROOT / "ROADMAP.md"
IMPLEMENTED_ROADMAP_PATH = REPO_ROOT / "roadmap" / "implemented.md"
DWO_READINESS_PATH = REPO_ROOT / "docs" / "research" / "2026_dwo_mvp_launch_readiness.md"

_DWO_CANONICAL_VERDICT = (
    "D/W/O MVP launch-readiness remains scoped: repository evidence proves the NC receipt-side L1 "
    "anchor, the L14 projection gate, and the committed Stage 2/4/5 owner surfaces, but the missing "
    "pm sentinel artifacts and still-unshipped browser route lanes keep this as a partial proof "
    "rather than a full shipped-surface launch verdict."
)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_georgia_legal_access_section_records_tos_status_and_prohibition_findings():
    text = read(DATA_LICENSING_PATH)

    assert "No reachable Terms of Use or acceptable-use page was found on media.ethics.ga.gov" in text
    assert (
        "No explicit portal prohibition text for automated access, bulk retrieval, or redistribution was found" in text
    )
    assert "Georgia reuse/commercial/redistribution verdict:" in text


def test_colorado_legal_access_section_records_fee_and_permission_constraints():
    text = read(DATA_LICENSING_PATH)

    assert "No fee, purchase flow, or request gate was observed on the public TRACER `DataDownload.aspx` page" in text
    assert "attempted data mining without permission will be blocked" in text
    assert "may not be reproduced in whole or in part without prior written permission" in text


def test_colorado_scraping_guidance_records_blocking_and_capacity_controls():
    text = read(SCRAPING_POLITENESS_PATH)

    assert "attempted data mining from the public website without permission will be blocked" in text
    assert (
        "regulate the duration, timing, and method of data recovery based on available technological capacity" in text
    )
    assert "No documented numeric TRACER bulk-endpoint rate limits were found" in text


def test_state_ie_audit_machine_readable_block_tracks_scope_and_ranking_contract():
    text = read(STATE_IE_AUDIT_PATH)
    match = re.search(
        r"## Machine-Readable Audit Facts\n```json\n(.*?)\n```",
        text,
        flags=re.DOTALL,
    )
    assert match is not None, "Missing 'Machine-Readable Audit Facts' JSON block in state IE audit"

    audit_facts = json.loads(match.group(1))

    assert audit_facts["captured_at_utc"] == "2026-04-29T08:04:20Z"
    assert audit_facts["runner_state_scope"] == [
        "AL",
        "CA",
        "CO",
        "FL",
        "GA",
        "IL",
        "IN",
        "KY",
        "LA",
        "MA",
        "MN",
        "NC",
        "NE",
        "NJ",
        "NY",
        "OR",
        "PA",
        "TX",
        "VA",
        "WA",
        "WI",
    ]
    assert audit_facts["excluded_deferred_state_codes"] == ["OH"]
    assert audit_facts["ranked_follow_through_candidates"] == ["NC", "NY", "NJ"]


def test_stage6_status_docs_capture_apr29_ca_ie_closeout_facts():
    priorities_text = read(PRIORITIES_PATH)
    roadmap_text = read(ROADMAP_PATH)
    implemented_text = read(IMPLEMENTED_ROADMAP_PATH)

    assert "**Last updated:** 2026-04-30" in priorities_text
    assert "CA receipt-side L1 boundary remains zero-row" in priorities_text
    assert "`Campaign_ByIEFiler.aspx` contract returned HTTP 404 on `2026-04-29`" in priorities_text

    assert "Last updated: 2026-04-30" in roadmap_text
    assert "CA receipt-side L1 boundary remains zero-row under `make gate-L1 JURISDICTION=CA`" in roadmap_text
    assert "`Campaign_ByIEFiler.aspx` contract currently returns HTTP 404" in roadmap_text

    assert "Status update (2026-04-29):" in implemented_text
    assert "evidence/L1/CA/2026-04-29.json" in implemented_text
    assert "evidence/L3/CA/ca_cal_access_raw_export/prototyped_2026-04-29.json" in implemented_text


def test_stage6_dwo_readiness_note_and_status_docs_stay_in_lockstep():
    readiness_text = read(DWO_READINESS_PATH)
    priorities_text = read(PRIORITIES_PATH)
    roadmap_text = read(ROADMAP_PATH)

    assert _DWO_CANONICAL_VERDICT in readiness_text
    assert _DWO_CANONICAL_VERDICT in priorities_text
    assert _DWO_CANONICAL_VERDICT in roadmap_text

    missing_pm_paths = [
        "docs/research/artifacts/2026_04_29_dwo_cf_fanout/hetzner/closeout.json",
        "docs/research/artifacts/2026_04_29_dwo_keystone/hetzner/evidence.json",
    ]
    for pm_path in missing_pm_paths:
        assert not (REPO_ROOT / pm_path).exists()
        assert pm_path not in readiness_text
