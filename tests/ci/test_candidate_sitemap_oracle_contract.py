"""Contract tests for the candidate sitemap deploy-proof oracle."""

from __future__ import annotations

import pytest

from infra.scripts.candidate_sitemap_oracle import (
    HttpResponse,
    OracleError,
    evaluate_candidate_sitemap,
)


BASE_URL = "https://civibus.example"
SAFE_CANDIDATE = {
    "id": "11111111-1111-4111-8111-111111111111",
    "slug": "alice-representative-2026",
    "slug_is_unique": True,
    "identity_is_safe": True,
}
UNSAFE_UNIQUE_CANDIDATE = {
    "id": "22222222-2222-4222-8222-222222222222",
    "slug": "212-n-half-w-john-rodney-howard-mr",
    "slug_is_unique": True,
    "identity_is_safe": False,
}
DUPLICATE_SLUG_CANDIDATE = {
    "id": "33333333-3333-4333-8333-333333333333",
    "slug": "shared-committee-slug",
    "slug_is_unique": False,
    "identity_is_safe": True,
}
EMPTY_SLUG_CANDIDATE = {
    "id": "44444444-4444-4444-8444-444444444444",
    "slug": "",
    "slug_is_unique": True,
    "identity_is_safe": True,
}
BARE_UUID_FALLBACK_CANDIDATE = {
    "id": "55555555-5555-4555-8555-555555555555",
    "slug": "",
    "slug_is_unique": False,
    "identity_is_safe": False,
}
KNOWN_ANSWER_CANDIDATES = [
    SAFE_CANDIDATE,
    UNSAFE_UNIQUE_CANDIDATE,
    DUPLICATE_SLUG_CANDIDATE,
    EMPTY_SLUG_CANDIDATE,
    BARE_UUID_FALLBACK_CANDIDATE,
]
SAFE_URL = f"{BASE_URL}/candidate/{SAFE_CANDIDATE['slug']}"
UNSAFE_URL = f"{BASE_URL}/candidate/{UNSAFE_UNIQUE_CANDIDATE['slug']}"
BARE_UUID_URL = f"{BASE_URL}/candidate/{BARE_UUID_FALLBACK_CANDIDATE['id']}"


def _sitemap(candidate_urls: list[str]) -> str:
    locs = [f"{BASE_URL}/", *candidate_urls, f"{BASE_URL}/committees"]
    entries = "\n".join(f"  <url><loc>{loc}</loc></url>" for loc in locs)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{entries}\n"
        "</urlset>"
    )


class FixtureSurface:
    def __init__(
        self,
        *,
        candidate_pages: list[dict],
        sitemap_xml: str,
        status_by_path: dict[str, int] | None = None,
    ) -> None:
        self.candidate_pages = candidate_pages
        self.sitemap_xml = sitemap_xml
        self.status_by_path = status_by_path or {}
        self.requested_paths: list[str] = []

    def fetch(self, url: str) -> HttpResponse:
        path = url.removeprefix(BASE_URL)
        self.requested_paths.append(path)
        status = self.status_by_path.get(path, 200)
        if path.startswith("/v1/candidates"):
            offset = int(path.split("offset=", 1)[1])
            page_index = offset // 200
            return HttpResponse(status_code=status, body=self.candidate_pages[page_index])
        if path == "/sitemap.xml":
            return HttpResponse(status_code=status, body=self.sitemap_xml)
        raise AssertionError(f"Unexpected URL: {url}")


def _candidate_pages() -> list[dict]:
    return [
        {
            "items": KNOWN_ANSWER_CANDIDATES[:2],
            "has_next": True,
            "offset": 0,
            "limit": 200,
        },
        {
            "items": KNOWN_ANSWER_CANDIDATES[2:],
            "has_next": False,
            "offset": 200,
            "limit": 200,
        },
    ]


def test_candidate_sitemap_oracle_accepts_canonical_sitemap() -> None:
    surface = FixtureSurface(candidate_pages=_candidate_pages(), sitemap_xml=_sitemap([SAFE_URL]))

    report = evaluate_candidate_sitemap(BASE_URL, surface.fetch)

    assert surface.requested_paths == [
        "/v1/candidates?limit=200&offset=0",
        "/v1/candidates?limit=200&offset=200",
        "/sitemap.xml",
    ]
    assert report.ok is True
    assert report.candidate_api_total == 5
    assert report.canonical_eligible_count == 1
    assert report.sitemap_candidate_count == 1
    assert report.bare_uuid_candidate_url_count == 0
    assert report.duplicate_candidate_urls == []
    assert report.missing_eligible_urls == []
    assert report.unexpected_candidate_urls == []
    assert "candidate_api_total=5" in report.evidence()
    assert "canonical_eligible_count=1" in report.evidence()


@pytest.mark.parametrize(
    ("candidate_urls", "expected_evidence"),
    [
        ([UNSAFE_URL, SAFE_URL], f"unexpected_candidate_urls={UNSAFE_URL}"),
        ([], f"missing_eligible_urls={SAFE_URL}"),
        ([SAFE_URL, SAFE_URL], f"duplicate_candidate_urls={SAFE_URL}"),
        ([SAFE_URL, BARE_UUID_URL], "bare_uuid_candidate_url_count=1"),
    ],
)
def test_candidate_sitemap_oracle_fails_closed_on_candidate_url_drift(
    candidate_urls: list[str], expected_evidence: str
) -> None:
    surface = FixtureSurface(candidate_pages=_candidate_pages(), sitemap_xml=_sitemap(candidate_urls))

    report = evaluate_candidate_sitemap(BASE_URL, surface.fetch)

    assert report.ok is False
    assert expected_evidence in report.evidence()


def test_candidate_sitemap_oracle_fails_closed_on_malformed_candidate_json() -> None:
    surface = FixtureSurface(
        candidate_pages=["not-json-object"],
        sitemap_xml=_sitemap([SAFE_URL]),
    )

    with pytest.raises(OracleError, match="candidate_json_malformed"):
        evaluate_candidate_sitemap(BASE_URL, surface.fetch)


def test_candidate_sitemap_oracle_fails_closed_on_malformed_sitemap_xml() -> None:
    surface = FixtureSurface(candidate_pages=_candidate_pages(), sitemap_xml="<urlset><url>")

    with pytest.raises(OracleError, match="sitemap_xml_malformed"):
        evaluate_candidate_sitemap(BASE_URL, surface.fetch)


def test_candidate_sitemap_oracle_fails_closed_on_unexpected_http_status() -> None:
    surface = FixtureSurface(
        candidate_pages=_candidate_pages(),
        sitemap_xml=_sitemap([SAFE_URL]),
        status_by_path={"/v1/candidates?limit=200&offset=0": 503},
    )

    with pytest.raises(OracleError, match="candidate_api_unexpected_http_status 503"):
        evaluate_candidate_sitemap(BASE_URL, surface.fetch)
