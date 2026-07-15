from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from domains.campaign_finance.jurisdictions.states.NC.scraper import diagnose_failed_committee_exports as diagnose
from domains.campaign_finance.jurisdictions.states.NC.scraper.download import BrowserAutomationRequiredError

_EXPECTED_SAMPLE_IDS = [
    "079-7SE7OZ-C-001",
    "321-NEVC06-C-001",
    "443-UT2COW-C-001",
    "BUN-FK398N-C-001",
    "GRN-P8HKN3-C-001",
    "MAR-6BA3TF-C-001",
    "NEW-C0835N-C-001",
    "SCO-3RMJO3-C-001",
    "STA-8P35Z4-C-002",
    "STA-9RUJZ1-C-001",
]

_COHORT_ARTIFACT = (
    Path(__file__).resolve().parents[6]
    / "docs"
    / "reference"
    / "research"
    / "artifacts"
    / "2026_04_27_nc_orch_failed_cohort"
    / "nc_orch_failed_cohort_window_2026_01_01_2026_04_25.csv"
)


def test_select_sample_rows_matches_stage2_ids() -> None:
    sample_rows = diagnose.select_sample_rows_from_cohort(_COHORT_ARTIFACT, sample_size=10)

    assert [row.sboe_id for row in sample_rows] == _EXPECTED_SAMPLE_IDS
    assert len(sample_rows) == 10
    assert all(row.org_group_id for row in sample_rows)
    assert all(row.committee_name for row in sample_rows)


@pytest.fixture
def valid_diagnostic_row() -> dict[str, object]:
    return {
        "sboe_id": "079-7SE7OZ-C-001",
        "org_group_id": "34419",
        "committee_name": "COMMITTEE FOR A BALANCED CARY",
        "attempt_count": 4,
        "last_error": "Committee export returned empty CSV",
        "disposition": "recovered",
        "reason": "export returned rows",
        "artifacts": {
            "export_csv_path": "docs/reference/research/artifacts/example/079/committee_export.csv",
            "export_raw_path": "docs/reference/research/artifacts/example/079/export_response.bin",
            "portal_html_path": "docs/reference/research/artifacts/example/079/committee_document_page.html",
            "portal_screenshot_path": "docs/reference/research/artifacts/example/079/committee_document_page.png",
        },
    }


@pytest.mark.parametrize(
    "disposition",
    sorted(diagnose.ALLOWED_DISPOSITIONS),
)
def test_validate_sample_diagnostics_payload_accepts_fixed_dispositions(
    disposition: str,
    valid_diagnostic_row: dict[str, object],
) -> None:
    row = dict(valid_diagnostic_row)
    row["disposition"] = disposition

    payload = diagnose.build_sample_diagnostics_payload(rows=[row])

    assert payload["rows"][0]["disposition"] == disposition


@pytest.mark.parametrize(
    "field_to_remove",
    ["sboe_id", "disposition", "reason", "artifacts"],
)
def test_validate_sample_diagnostics_payload_rejects_missing_required_keys(
    field_to_remove: str,
    valid_diagnostic_row: dict[str, object],
) -> None:
    row = dict(valid_diagnostic_row)
    row.pop(field_to_remove)

    with pytest.raises(ValueError, match="required"):
        diagnose.build_sample_diagnostics_payload(rows=[row])


def test_validate_sample_diagnostics_payload_rejects_unknown_disposition(
    valid_diagnostic_row: dict[str, object],
) -> None:
    row = dict(valid_diagnostic_row)
    row["disposition"] = "unknown_state"

    with pytest.raises(ValueError, match="disposition"):
        diagnose.build_sample_diagnostics_payload(rows=[row])


def test_write_sample_selection_json_round_trips_expected_shape(tmp_path: Path) -> None:
    sample_rows = diagnose.select_sample_rows_from_cohort(_COHORT_ARTIFACT, sample_size=10)
    output_path = tmp_path / "sample_selection.json"

    diagnose.write_sample_selection_manifest(
        cohort_path=_COHORT_ARTIFACT,
        sample_rows=sample_rows,
        output_path=output_path,
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["sample_size"] == 10
    assert payload["sample_rule"] == diagnose.SAMPLE_RULE_DESCRIPTION
    assert [entry["sboe_id"] for entry in payload["selected"]] == _EXPECTED_SAMPLE_IDS


def test_classify_disposition_marks_recovered_when_csv_contains_rows(tmp_path: Path) -> None:
    export_csv_path = tmp_path / "committee_export.csv"
    export_csv_path.write_text("doc_id,title\n1,Quarterly report\n", encoding="utf-8")

    disposition, reason = diagnose._classify_disposition(
        export_error=None,
        committee_export_csv_path=export_csv_path,
        portal_html="",
    )

    assert disposition == "recovered"
    assert "non-empty csv" in reason.lower()


def test_classify_disposition_accepts_portal_empty_markers_from_live_html(tmp_path: Path) -> None:
    export_error = BrowserAutomationRequiredError(
        "Committee export returned empty CSV; the export URL or required portal state may have changed"
    )
    empty_csv_path = tmp_path / "committee_export.csv"
    empty_csv_path.write_text("\n", encoding="utf-8")

    disposition, reason = diagnose._classify_disposition(
        export_error=export_error,
        committee_export_csv_path=empty_csv_path,
        portal_html=(
            "<html><body><div>Results Returned: 0</div><center><b>No documents found.</b></center></body></html>"
        ),
    )

    assert disposition == "legitimately_empty"
    assert "empty-state marker" in reason.lower()


def test_classify_disposition_marks_portal_blocked_from_portal_error(tmp_path: Path) -> None:
    empty_csv_path = tmp_path / "committee_export.csv"
    empty_csv_path.write_text("\n", encoding="utf-8")

    disposition, reason = diagnose._classify_disposition(
        export_error=BrowserAutomationRequiredError("Committee export returned empty CSV"),
        committee_export_csv_path=empty_csv_path,
        portal_html="",
        portal_error=RuntimeError("HTTP 403 Cloudflare challenge"),
    )

    assert disposition == "portal_blocked"
    assert "blocked" in reason.lower()


def test_classify_disposition_marks_unknown_when_empty_csv_has_no_portal_evidence(tmp_path: Path) -> None:
    empty_csv_path = tmp_path / "committee_export.csv"
    empty_csv_path.write_text("\n", encoding="utf-8")

    disposition, reason = diagnose._classify_disposition(
        export_error=BrowserAutomationRequiredError("Committee export returned empty CSV"),
        committee_export_csv_path=empty_csv_path,
        portal_html="<html><body><div>Results Returned: ???</div></body></html>",
    )

    assert disposition == "unknown"
    assert "without portal evidence" in reason.lower()


def test_capture_committee_portal_artifacts_waits_for_results_state_before_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, Any] = {"wait_for_function_calls": []}

    class _FakePage:
        def goto(self, _url: str, wait_until: str) -> None:
            calls["goto_wait_until"] = wait_until

        def wait_for_function(self, expression: str, *, arg: object, timeout: int) -> None:
            calls["wait_for_function_calls"].append((expression, arg, timeout))

        def content(self) -> str:
            return "<html><body>Results Returned: 0 No documents found.</body></html>"

        def screenshot(self, *, path: str, full_page: bool) -> None:
            Path(path).write_bytes(b"PNG")
            calls["screenshot_full_page"] = full_page

    class _FakeContext:
        def __init__(self) -> None:
            self._page = _FakePage()

        def new_page(self) -> _FakePage:
            return self._page

        def close(self) -> None:
            calls["context_closed"] = True

    class _FakeBrowser:
        def __init__(self) -> None:
            self._context = _FakeContext()

        def new_context(self) -> _FakeContext:
            return self._context

        def close(self) -> None:
            calls["browser_closed"] = True

    class _FakePlaywrightRuntime:
        class _Chromium:
            def launch(self, *, channel: str, headless: bool) -> _FakeBrowser:
                calls["launch"] = {"channel": channel, "headless": headless}
                return _FakeBrowser()

        def __init__(self) -> None:
            self.chromium = self._Chromium()

    class _FakePlaywrightManager:
        def __enter__(self) -> _FakePlaywrightRuntime:
            return _FakePlaywrightRuntime()

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    monkeypatch.setattr(diagnose.download, "_require_playwright", lambda: None)
    monkeypatch.setattr(diagnose.download, "_sync_playwright", lambda: _FakePlaywrightManager())

    html_path = tmp_path / "page.html"
    screenshot_path = tmp_path / "page.png"
    diagnose._capture_committee_portal_artifacts(
        sboe_id="STA-9RUJZ1-C-001",
        org_group_id="58252",
        html_path=html_path,
        screenshot_path=screenshot_path,
    )

    assert calls["goto_wait_until"] == "domcontentloaded"
    assert calls["wait_for_function_calls"], "must wait for committee result markers before snapshot"
    assert calls["screenshot_full_page"] is True
    assert html_path.exists()
    assert screenshot_path.exists()


def test_capture_committee_portal_artifacts_uses_download_owned_url_builder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str] = {}

    class _FakePage:
        def goto(self, url: str, wait_until: str) -> None:
            captured["url"] = url
            captured["wait_until"] = wait_until

        def wait_for_function(self, _expression: str, *, arg: object, timeout: int) -> None:
            captured["ready_markers"] = str(arg)
            captured["timeout"] = str(timeout)

        def content(self) -> str:
            return "<html><body>Results Returned: 0 No documents found.</body></html>"

        def screenshot(self, *, path: str, full_page: bool) -> None:
            Path(path).write_bytes(b"PNG")
            captured["full_page"] = str(full_page)

    class _FakeContext:
        def new_page(self) -> _FakePage:
            return _FakePage()

        def close(self) -> None:
            return None

    class _FakeBrowser:
        def new_context(self) -> _FakeContext:
            return _FakeContext()

        def close(self) -> None:
            return None

    class _FakePlaywrightRuntime:
        class _Chromium:
            def launch(self, *, channel: str, headless: bool) -> _FakeBrowser:
                return _FakeBrowser()

        def __init__(self) -> None:
            self.chromium = self._Chromium()

    class _FakePlaywrightManager:
        def __enter__(self) -> _FakePlaywrightRuntime:
            return _FakePlaywrightRuntime()

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    monkeypatch.setattr(diagnose.download, "_require_playwright", lambda: None)
    monkeypatch.setattr(diagnose.download, "_sync_playwright", lambda: _FakePlaywrightManager())
    monkeypatch.setattr(
        diagnose.download,
        "build_committee_document_result_url",
        lambda sboe_id, org_group_id: f"https://example.invalid/custom?s={sboe_id}&o={org_group_id}",
    )

    diagnose._capture_committee_portal_artifacts(
        sboe_id="079-7SE7OZ-C-001",
        org_group_id="34419",
        html_path=tmp_path / "committee.html",
        screenshot_path=tmp_path / "committee.png",
    )

    assert captured["url"] == "https://example.invalid/custom?s=079-7SE7OZ-C-001&o=34419"
