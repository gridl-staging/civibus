
from __future__ import annotations

from collections.abc import Callable

import httpx

from core.people.enrichment.models import (
    CandidateEnrichmentRecord,
    CandidateEnrichmentTarget,
    EnrichmentAttempt,
    JsonLikeMapping,
)
from core.people.enrichment.strategy_shared import run_strategy_fetch
from domains.campaign_finance.jurisdictions.protected_portal import (
    ProtectedPortalBrowserSettings,
    launch_browser_session,
    open_playwright,
)


class CampaignSiteEnrichmentStrategy:

    source_name = "campaign_site"

    def __init__(
        self,
        *,
        http_fetcher: Callable[[str], JsonLikeMapping | None] | None = None,
        browser_fetcher: Callable[[object, CandidateEnrichmentTarget], JsonLikeMapping | None] | None = None,
        require_browser: bool = False,
        browser_settings: ProtectedPortalBrowserSettings | None = None,
        timeout_seconds: float = 15.0,
        portrait_fetcher: Callable[[str], bytes | None] | None = None,
    ) -> None:
        self._http_fetcher = http_fetcher or (lambda url: self._fetch_http(url, timeout_seconds=timeout_seconds))
        self._browser_fetcher = browser_fetcher
        self._require_browser = require_browser
        self._portrait_fetcher = portrait_fetcher or (lambda _url: None)
        self._browser_settings = browser_settings or ProtectedPortalBrowserSettings(
            channel="chrome",
            headless=True,
            accept_downloads=False,
            user_data_dir=None,
        )

    def fetch(
        self,
        target: CandidateEnrichmentTarget,
        missing_fields: tuple[str, ...],
    ) -> tuple[CandidateEnrichmentRecord, EnrichmentAttempt]:
        campaign_site_url = (target.verified_campaign_site_url or "").strip()
        if campaign_site_url == "":
            return CandidateEnrichmentRecord(), EnrichmentAttempt.no_data(
                source=self.source_name,
                requested_fields=missing_fields,
            )

        return run_strategy_fetch(
            source_name=self.source_name,
            missing_fields=missing_fields,
            fetch_payload=lambda: (
                self._fetch_browser(target, campaign_site_url)
                if self._require_browser
                else self._http_fetcher(campaign_site_url)
            ),
            fetch_portrait_bytes=self._portrait_fetcher,
        )

    def _fetch_browser(
        self,
        target: CandidateEnrichmentTarget,
        campaign_site_url: str,
    ) -> JsonLikeMapping | None:
        if self._browser_fetcher is None:
            return None

        with open_playwright("campaign-site candidate enrichment") as playwright:
            with launch_browser_session(playwright, self._browser_settings) as session:
                page = session.context.new_page()
                page.goto(campaign_site_url, wait_until="domcontentloaded")
                return self._browser_fetcher(page, target)

    def _fetch_http(self, url: str, *, timeout_seconds: float) -> JsonLikeMapping | None:
        response = httpx.get(url, timeout=timeout_seconds)
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else None
