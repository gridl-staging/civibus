"""
Stub summary for /Users/stuart/parallel_development/civibus_dev/mar26_pm_1_prod_data_deploy_and_runner_cleanup/civibus_dev/domains/campaign_finance/jurisdictions/protected_portal.py.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright as _sync_playwright
except ImportError as import_error:
    _sync_playwright = None
    _playwright_import_error: Exception | None = import_error
else:
    _playwright_import_error = None


_CHALLENGE_MARKERS = (
    "just a moment",
    "enable javascript and cookies to continue",
    "challenge-platform",
    "/cdn-cgi/challenge-platform/",
    "cf-chl",
    "turnstile",
    "checking your browser before accessing",
)
_BLOCK_MARKERS = (
    "incapsula incident id",
    "error code 1020",
    "sorry, you have been blocked",
    "forbidden",
)
_PRIVATE_DIRECTORY_MODE = 0o700


class PortalPageClassification(StrEnum):
    APPLICATION = "application"
    CHALLENGE = "challenge"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ProtectedPortalPageSnapshot:
    url: str
    title: str = ""
    html: str = ""
    cookie_names: frozenset[str] = frozenset()
    response_headers: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProtectedPortalAssessment:
    classification: PortalPageClassification
    reasons: tuple[str, ...] = ()
    has_clearance_cookie: bool = False
    indicates_cloudflare: bool = False


@dataclass(frozen=True, slots=True)
class ProtectedPortalBrowserSettings:
    channel: str | None = "chrome"
    headless: bool = False
    accept_downloads: bool = True
    user_data_dir: Path | None = None


@dataclass(slots=True)
class BrowserSessionHandle:

    browser: object | None
    context: object

    def close(self) -> None:
        context_error: Exception | None = None
        try:
            self.context.close()  # type: ignore[union-attr]
        except Exception as error:  # pragma: no cover - defensive cleanup path
            context_error = error

        try:
            if self.browser is not None:
                self.browser.close()  # type: ignore[union-attr]
        except Exception:
            if context_error is not None:
                raise context_error
            raise

        if context_error is not None:
            raise context_error

    def __enter__(self) -> BrowserSessionHandle:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        self.close()
        return False


def ensure_private_directory(path: Path) -> Path:
    """Create a browser/session artifact directory with private permissions."""
    path.mkdir(parents=True, exist_ok=True, mode=_PRIVATE_DIRECTORY_MODE)
    path.chmod(_PRIVATE_DIRECTORY_MODE)
    return path


def require_playwright(feature_name: str) -> None:
    if _sync_playwright is not None:
        return
    raise RuntimeError(
        f"Playwright is required for {feature_name}. "
        "Install download dependencies with `uv sync --extra download` "
        "and browser binaries with `uv run --extra download playwright install chromium`."
    ) from _playwright_import_error


def open_playwright(feature_name: str):
    require_playwright(feature_name)
    assert _sync_playwright is not None
    return _sync_playwright()


def launch_browser_session(
    playwright: object,
    settings: ProtectedPortalBrowserSettings,
) -> BrowserSessionHandle:
    chromium = playwright.chromium  # type: ignore[union-attr]

    if settings.user_data_dir is not None:
        ensure_private_directory(settings.user_data_dir)
        context = chromium.launch_persistent_context(
            str(settings.user_data_dir),
            accept_downloads=settings.accept_downloads,
            channel=settings.channel,
            headless=settings.headless,
        )
        return BrowserSessionHandle(browser=None, context=context)

    launch_kwargs: dict[str, object] = {"headless": settings.headless}
    if settings.channel is not None:
        launch_kwargs["channel"] = settings.channel
    browser = chromium.launch(**launch_kwargs)
    context = browser.new_context(accept_downloads=settings.accept_downloads)
    return BrowserSessionHandle(browser=browser, context=context)


def assess_portal_page(snapshot: ProtectedPortalPageSnapshot) -> ProtectedPortalAssessment:
    normalized_headers = {key.lower(): value.lower() for key, value in snapshot.response_headers.items()}
    normalized_cookie_names = {cookie_name.lower() for cookie_name in snapshot.cookie_names}
    content_haystack = "\n".join((snapshot.title, snapshot.html)).lower()

    reasons: list[str] = []
    has_clearance_cookie = "cf_clearance" in normalized_cookie_names
    indicates_cloudflare = _indicates_cloudflare(
        content_haystack=content_haystack,
        normalized_headers=normalized_headers,
        normalized_cookie_names=normalized_cookie_names,
    )

    if normalized_headers.get("cf-mitigated") == "challenge":
        reasons.append("header:cf-mitigated=challenge")

    reasons.extend(_marker_reasons(content_haystack, _CHALLENGE_MARKERS))

    if reasons:
        return _build_assessment(
            PortalPageClassification.CHALLENGE,
            reasons=reasons,
            has_clearance_cookie=has_clearance_cookie,
            indicates_cloudflare=indicates_cloudflare,
        )

    block_reasons = _marker_reasons(content_haystack, _BLOCK_MARKERS)
    if block_reasons:
        return _build_assessment(
            PortalPageClassification.BLOCKED,
            reasons=block_reasons,
            has_clearance_cookie=has_clearance_cookie,
            indicates_cloudflare=indicates_cloudflare,
        )

    classification = (
        PortalPageClassification.APPLICATION
        if snapshot.title.strip() or snapshot.html.strip()
        else PortalPageClassification.UNKNOWN
    )
    return _build_assessment(
        classification,
        reasons=(),
        has_clearance_cookie=has_clearance_cookie,
        indicates_cloudflare=indicates_cloudflare,
    )


def _build_assessment(
    classification: PortalPageClassification,
    *,
    reasons: list[str] | tuple[str, ...],
    has_clearance_cookie: bool,
    indicates_cloudflare: bool,
) -> ProtectedPortalAssessment:
    return ProtectedPortalAssessment(
        classification=classification,
        reasons=tuple(reasons),
        has_clearance_cookie=has_clearance_cookie,
        indicates_cloudflare=indicates_cloudflare,
    )


def _marker_reasons(content_haystack: str, markers: tuple[str, ...]) -> list[str]:
    return [f"marker:{marker}" for marker in markers if marker in content_haystack]


def _indicates_cloudflare(
    *,
    content_haystack: str,
    normalized_headers: Mapping[str, str],
    normalized_cookie_names: set[str],
) -> bool:
    if normalized_headers.get("server") == "cloudflare":
        return True
    if "cf-ray" in normalized_headers:
        return True
    if any(cookie_name == "cf_clearance" or cookie_name.startswith("__cf") for cookie_name in normalized_cookie_names):
        return True
    return "cloudflare" in content_haystack
