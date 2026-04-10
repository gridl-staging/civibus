from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from domains.campaign_finance.jurisdictions import protected_portal
from domains.campaign_finance.jurisdictions.protected_portal import (
    PortalPageClassification,
    ProtectedPortalBrowserSettings,
    ProtectedPortalPageSnapshot,
    assess_portal_page,
    launch_browser_session,
    require_playwright,
)


def test_require_playwright_raises_clear_runtime_error_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(protected_portal, "_sync_playwright", None)
    monkeypatch.setattr(protected_portal, "_playwright_import_error", ImportError("No module named 'playwright'"))

    with pytest.raises(RuntimeError, match="Playwright is required for OH protected portal probing"):
        require_playwright("OH protected portal probing")


def test_launch_browser_session_uses_persistent_context_when_profile_dir_present(tmp_path: Path) -> None:
    playwright = MagicMock()
    persistent_context = MagicMock()
    playwright.chromium.launch_persistent_context.return_value = persistent_context
    settings = ProtectedPortalBrowserSettings(
        channel="chrome",
        headless=False,
        accept_downloads=True,
        user_data_dir=tmp_path / "oh-profile",
    )

    handle = launch_browser_session(playwright, settings)

    assert handle.browser is None
    assert handle.context is persistent_context
    assert settings.user_data_dir is not None and settings.user_data_dir.is_dir()
    playwright.chromium.launch_persistent_context.assert_called_once_with(
        str(settings.user_data_dir),
        accept_downloads=True,
        channel="chrome",
        headless=False,
    )


def test_launch_browser_session_uses_ephemeral_context_when_no_profile_dir() -> None:
    playwright = MagicMock()
    browser = MagicMock()
    browser_context = MagicMock()
    playwright.chromium.launch.return_value = browser
    browser.new_context.return_value = browser_context

    handle = launch_browser_session(
        playwright,
        ProtectedPortalBrowserSettings(channel="chrome", headless=True, accept_downloads=False, user_data_dir=None),
    )

    assert handle.browser is browser
    assert handle.context is browser_context
    playwright.chromium.launch.assert_called_once_with(channel="chrome", headless=True)
    browser.new_context.assert_called_once_with(accept_downloads=False)


def test_browser_session_handle_closes_context_then_browser() -> None:
    browser = MagicMock()
    context = MagicMock()
    handle = protected_portal.BrowserSessionHandle(browser=browser, context=context)

    handle.close()

    context.close.assert_called_once_with()
    browser.close.assert_called_once_with()


def test_assess_portal_page_classifies_cloudflare_challenge() -> None:
    assessment = assess_portal_page(
        ProtectedPortalPageSnapshot(
            url="https://example.gov",
            title="Just a moment...",
            html="<html><body>Enable JavaScript and cookies to continue<div>turnstile</div></body></html>",
            cookie_names=frozenset({"__cf_bm"}),
            response_headers={"server": "cloudflare", "cf-mitigated": "challenge"},
        )
    )

    assert assessment.classification == PortalPageClassification.CHALLENGE
    assert assessment.indicates_cloudflare is True
    assert assessment.has_clearance_cookie is False
    assert "header:cf-mitigated=challenge" in assessment.reasons


def test_assess_portal_page_classifies_block_page() -> None:
    assessment = assess_portal_page(
        ProtectedPortalPageSnapshot(
            url="https://example.gov",
            title="Access denied",
            html="<html><body>Sorry, you have been blocked</body></html>",
            cookie_names=frozenset(),
            response_headers={},
        )
    )

    assert assessment.classification == PortalPageClassification.BLOCKED


def test_assess_portal_page_classifies_application_and_clearance_cookie() -> None:
    assessment = assess_portal_page(
        ProtectedPortalPageSnapshot(
            url="https://www6.ohiosos.gov/ords/f?p=CFDISCLOSURE:73",
            title="New Files - File Transfer Page – Ohio Secretary of State",
            html="<html><body><h1>New Files</h1></body></html>",
            cookie_names=frozenset({"cf_clearance", "ORA_WWV_APP_119"}),
            response_headers={"server": "cloudflare"},
        )
    )

    assert assessment.classification == PortalPageClassification.APPLICATION
    assert assessment.has_clearance_cookie is True
    assert assessment.indicates_cloudflare is True
