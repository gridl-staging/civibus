"""
Stub summary for /Users/stuart/parallel_development/civibus_dev/mar26_pm_1_prod_data_deploy_and_runner_cleanup/civibus_dev/domains/campaign_finance/jurisdictions/states/OH/scraper/probe.py.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import urljoin, urlparse

from domains.campaign_finance.jurisdictions.protected_portal import (
    ProtectedPortalBrowserSettings,
    ProtectedPortalPageSnapshot,
    assess_portal_page,
    ensure_private_directory,
    launch_browser_session,
    open_playwright,
)

from . import _load_bulk_download_url_for_data_type, _load_data_source_for_data_type

_ALLOWED_OH_HOSTS = frozenset({"www6.ohiosos.gov", "www.ohiosos.gov"})
_DEFAULT_WAIT_AFTER_GOTO_MS = 5_000
_P72_GETID_PATTERN = re.compile(r"P72_GETID:([^:&?#]+)", re.IGNORECASE)
_PRIVATE_ARTIFACT_FILE_MODE = 0o600
_SENSITIVE_RESPONSE_HEADERS = frozenset(
    {
        "authorization",
        "cookie",
        "proxy-authorization",
        "set-cookie",
        "x-api-key",
        "x-auth-token",
    }
)


@dataclass(frozen=True, slots=True)
class OHApexDownloadAction:
    label: str
    url: str
    get_id: str


@dataclass(frozen=True, slots=True)
class OHPortalProbeResult:
    requested_url: str
    final_url: str
    response_status: int | None
    title: str
    classification: str
    reasons: tuple[str, ...]
    cookie_names: tuple[str, ...]
    apex_download_actions: tuple[OHApexDownloadAction, ...]
    artifact_dir: Path
    metadata_path: Path
    html_path: Path
    screenshot_path: Path


class _AnchorParser(HTMLParser):

    def __init__(self) -> None:
        super().__init__()
        self._active_href: str | None = None
        self._active_text_parts: list[str] = []
        self.anchors: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        for attr_name, attr_value in attrs:
            if attr_name.lower() == "href" and attr_value:
                self._active_href = attr_value
                self._active_text_parts = []
                return

    def handle_data(self, data: str) -> None:
        if self._active_href is not None:
            self._active_text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or self._active_href is None:
            return
        label = " ".join(part.strip() for part in self._active_text_parts if part.strip())
        self.anchors.append((self._active_href, label))
        self._active_href = None
        self._active_text_parts = []


def build_oh_ftp_probe_url(data_type: str, committee_type: str) -> str:
    return _load_bulk_download_url_for_data_type(data_type).replace("{TYPE}", committee_type.strip().upper())


def get_oh_search_url(data_type: str = "contributions") -> str:
    return _load_data_source_for_data_type(data_type).url


def discover_oh_apex_download_actions(html: str, *, base_url: str) -> tuple[OHApexDownloadAction, ...]:
    parser = _AnchorParser()
    parser.feed(html)

    actions: list[OHApexDownloadAction] = []
    seen_urls: set[str] = set()
    for href, label in parser.anchors:
        resolved_url = urljoin(base_url, href)
        if resolved_url in seen_urls:
            continue

        parsed_url = urlparse(resolved_url)
        if parsed_url.hostname not in _ALLOWED_OH_HOSTS:
            continue

        get_id_match = _P72_GETID_PATTERN.search(resolved_url)
        if get_id_match is None or "CFDISCLOSURE:72" not in resolved_url.upper():
            continue

        seen_urls.add(resolved_url)
        actions.append(
            OHApexDownloadAction(
                label=label,
                url=resolved_url,
                get_id=get_id_match.group(1),
            )
        )

    return tuple(actions)


def _sanitize_response_headers(response_headers: Mapping[str, str]) -> dict[str, str]:
    sanitized_headers: dict[str, str] = {}
    for header_name, header_value in response_headers.items():
        normalized_name = header_name.lower()
        if normalized_name in _SENSITIVE_RESPONSE_HEADERS or normalized_name.endswith("-token"):
            sanitized_headers[header_name] = "<redacted>"
            continue
        sanitized_headers[header_name] = header_value
    return sanitized_headers


def _write_private_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(_PRIVATE_ARTIFACT_FILE_MODE)


def _set_private_file_mode(path: Path) -> None:
    if path.exists():
        path.chmod(_PRIVATE_ARTIFACT_FILE_MODE)


def _collect_cookie_names(session_context: object) -> tuple[str, ...]:
    return tuple(sorted(cookie["name"] for cookie in session_context.cookies()))  # type: ignore[union-attr]


def _serialize_apex_download_actions(
    actions: tuple[OHApexDownloadAction, ...],
) -> list[dict[str, str]]:
    return [{"label": action.label, "url": action.url, "get_id": action.get_id} for action in actions]


def _build_probe_metadata(
    *,
    requested_url: str,
    final_url: str,
    response_status: int | None,
    title: str,
    assessment: object,
    cookie_count: int,
    sanitized_response_headers: dict[str, str],
    apex_download_actions: tuple[OHApexDownloadAction, ...],
) -> str:
    return (
        json.dumps(
            {
                "requested_url": requested_url,
                "final_url": final_url,
                "status": response_status,
                "title": title,
                "classification": assessment.classification,
                "reasons": list(assessment.reasons),
                "has_clearance_cookie": assessment.has_clearance_cookie,
                "indicates_cloudflare": assessment.indicates_cloudflare,
                # Persist only aggregate cookie state; raw names reveal
                # session and infrastructure identifiers in tracked artifacts.
                "cookie_count": cookie_count,
                "response_headers": sanitized_response_headers,
                "apex_download_actions": _serialize_apex_download_actions(apex_download_actions),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def probe_oh_portal(
    *,
    url: str,
    artifact_dir: Path,
    browser_settings: ProtectedPortalBrowserSettings | None = None,
    wait_after_goto_ms: int = _DEFAULT_WAIT_AFTER_GOTO_MS,
) -> OHPortalProbeResult:
    settings = browser_settings or ProtectedPortalBrowserSettings()
    ensure_private_directory(artifact_dir)

    with open_playwright("OH protected portal probing") as playwright:
        with launch_browser_session(playwright, settings) as session:
            page = session.context.new_page()  # type: ignore[union-attr]
            response = page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(wait_after_goto_ms)

            final_url = page.url
            response_status = response.status if response is not None else None
            title = page.title()
            html = page.content()
            response_headers = response.all_headers() if response is not None else {}
            sanitized_response_headers = _sanitize_response_headers(response_headers)
            cookie_names = _collect_cookie_names(session.context)
            assessment = assess_portal_page(
                ProtectedPortalPageSnapshot(
                    url=final_url,
                    title=title,
                    html=html,
                    cookie_names=frozenset(cookie_names),
                    response_headers=response_headers,
                )
            )
            apex_download_actions = discover_oh_apex_download_actions(html, base_url=final_url)

            html_path = artifact_dir / "page.html"
            screenshot_path = artifact_dir / "page.png"
            metadata_path = artifact_dir / "probe.json"

            _write_private_text(html_path, html)
            page.screenshot(path=str(screenshot_path), full_page=True)
            _set_private_file_mode(screenshot_path)
            _write_private_text(
                metadata_path,
                _build_probe_metadata(
                    requested_url=url,
                    final_url=final_url,
                    response_status=response_status,
                    title=title,
                    assessment=assessment,
                    cookie_count=len(cookie_names),
                    sanitized_response_headers=sanitized_response_headers,
                    apex_download_actions=apex_download_actions,
                ),
            )

    return OHPortalProbeResult(
        requested_url=url,
        final_url=final_url,
        response_status=response_status,
        title=title,
        classification=str(assessment.classification),
        reasons=assessment.reasons,
        cookie_names=cookie_names,
        apex_download_actions=apex_download_actions,
        artifact_dir=artifact_dir,
        metadata_path=metadata_path,
        html_path=html_path,
        screenshot_path=screenshot_path,
    )
