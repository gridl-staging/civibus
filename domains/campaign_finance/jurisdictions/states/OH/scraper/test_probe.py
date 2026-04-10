from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from domains.campaign_finance.jurisdictions.protected_portal import ProtectedPortalBrowserSettings
from domains.campaign_finance.jurisdictions.states.OH.scraper import probe as oh_probe


def test_build_oh_ftp_probe_url_uses_config_template(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        oh_probe,
        "_load_bulk_download_url_for_data_type",
        lambda data_type: "https://www6.ohiosos.gov/ords/f?p=CFDISCLOSURE:73:0::NO:RP:P73_TYPE:{TYPE}:",
    )

    assert oh_probe.build_oh_ftp_probe_url("contributions", "can") == (
        "https://www6.ohiosos.gov/ords/f?p=CFDISCLOSURE:73:0::NO:RP:P73_TYPE:CAN:"
    )


def test_discover_oh_apex_download_actions_extracts_page72_links() -> None:
    html = """
    <html>
      <body>
        <a href="https://www6.ohiosos.gov/ords/f?p=CFDISCLOSURE:72:::NO::P72_GETID:6509">Download</a>
        <a href="/ords/f?p=CFDISCLOSURE:72:::NO::P72_GETID:6510">Candidate Contributions</a>
        <a href="https://evil.example/ords/f?p=CFDISCLOSURE:72:::NO::P72_GETID:9999">Bad Host</a>
        <a href="/ords/r/cfdisclosure/files/static/v5/CAC_CON_2022.CSV">Static Guess</a>
      </body>
    </html>
    """

    actions = oh_probe.discover_oh_apex_download_actions(
        html,
        base_url="https://www6.ohiosos.gov/ords/f?p=CFDISCLOSURE:73",
    )

    assert actions == (
        oh_probe.OHApexDownloadAction(
            label="Download",
            url="https://www6.ohiosos.gov/ords/f?p=CFDISCLOSURE:72:::NO::P72_GETID:6509",
            get_id="6509",
        ),
        oh_probe.OHApexDownloadAction(
            label="Candidate Contributions",
            url="https://www6.ohiosos.gov/ords/f?p=CFDISCLOSURE:72:::NO::P72_GETID:6510",
            get_id="6510",
        ),
    )


def test_probe_oh_portal_writes_artifacts_and_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    page = MagicMock()
    response = MagicMock()
    response.all_headers.return_value = {"server": "cloudflare"}
    response.status = 403
    page.goto.return_value = response
    page.url = "https://www6.ohiosos.gov/ords/f?p=CFDISCLOSURE:73"
    page.title.return_value = "New Files - File Transfer Page – Ohio Secretary of State"
    page.content.return_value = """
    <html>
      <body>
        <h1>New Files</h1>
        <a href="https://www6.ohiosos.gov/ords/f?p=CFDISCLOSURE:72:::NO::P72_GETID:6509">Download</a>
      </body>
    </html>
    """

    context = MagicMock()
    context.new_page.return_value = page
    context.cookies.return_value = [{"name": "cf_clearance"}, {"name": "ORA_WWV_APP_119"}]

    session_handle = MagicMock()
    session_handle.__enter__.return_value = session_handle
    session_handle.__exit__.return_value = None
    session_handle.context = context

    playwright = MagicMock()
    playwright_manager = MagicMock()
    playwright_manager.__enter__.return_value = playwright
    playwright_manager.__exit__.return_value = None

    monkeypatch.setattr(oh_probe, "open_playwright", lambda feature_name: playwright_manager)
    monkeypatch.setattr(oh_probe, "launch_browser_session", lambda pw, settings: session_handle)

    artifact_dir = tmp_path / "probe"
    result = oh_probe.probe_oh_portal(
        url="https://www6.ohiosos.gov/ords/f?p=CFDISCLOSURE:73",
        artifact_dir=artifact_dir,
        browser_settings=ProtectedPortalBrowserSettings(
            channel="chrome",
            headless=False,
            user_data_dir=tmp_path / "profile",
        ),
        wait_after_goto_ms=10,
    )

    assert result.metadata_path == artifact_dir / "probe.json"
    assert result.html_path.read_text(encoding="utf-8").startswith("\n    <html>")
    metadata = json.loads(result.metadata_path.read_text(encoding="utf-8"))
    assert metadata["classification"] == "application"
    assert metadata["status"] == 403
    assert metadata["cookie_count"] == 2
    assert metadata["apex_download_actions"] == [
        {
            "get_id": "6509",
            "label": "Download",
            "url": "https://www6.ohiosos.gov/ords/f?p=CFDISCLOSURE:72:::NO::P72_GETID:6509",
        }
    ]
    assert result.response_status == 403
    page.goto.assert_called_once_with(
        "https://www6.ohiosos.gov/ords/f?p=CFDISCLOSURE:73", wait_until="domcontentloaded"
    )
    page.wait_for_timeout.assert_called_once_with(10)
    page.screenshot.assert_called_once_with(path=str(artifact_dir / "page.png"), full_page=True)
