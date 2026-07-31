"""Contract tests for the candidate sitemap deploy-proof oracle."""

from __future__ import annotations

import pytest

import infra.scripts.candidate_sitemap_oracle as oracle_module
from infra.scripts.candidate_sitemap_oracle import (
    HttpResponse,
    OracleError,
    PUBLIC_CANDIDATE_LIST_PATH,
    _build_http_fetch_url,
    _candidate_api_key,
    evaluate_candidate_sitemap,
)


BASE_URL = "https://civibus.example"
SAFE_CANDIDATE = {
    "id": "11111111-1111-4111-8111-111111111111",
    "slug": "alice-representative-2026",
    "slug_is_unique": True,
    "identity_is_safe": True,
    "has_official_total": True,
}
CANONICAL_NO_OFFICIAL_TOTAL_CANDIDATE = {
    "id": "66666666-6666-4666-8666-666666666666",
    "slug": "casey-no-official-total-2026",
    "slug_is_unique": True,
    "identity_is_safe": True,
    "has_official_total": False,
}
UNSAFE_UNIQUE_CANDIDATE = {
    "id": "22222222-2222-4222-8222-222222222222",
    "slug": "212-n-half-w-john-rodney-howard-mr",
    "slug_is_unique": True,
    "identity_is_safe": False,
    "has_official_total": True,
}
DUPLICATE_SLUG_CANDIDATE = {
    "id": "33333333-3333-4333-8333-333333333333",
    "slug": "shared-committee-slug",
    "slug_is_unique": False,
    "identity_is_safe": True,
    "has_official_total": True,
}
EMPTY_SLUG_CANDIDATE = {
    "id": "44444444-4444-4444-8444-444444444444",
    "slug": "",
    "slug_is_unique": True,
    "identity_is_safe": True,
    "has_official_total": True,
}
BARE_UUID_FALLBACK_CANDIDATE = {
    "id": "55555555-5555-4555-8555-555555555555",
    "slug": "",
    "slug_is_unique": False,
    "identity_is_safe": False,
    "has_official_total": False,
}
KNOWN_ANSWER_CANDIDATES = [
    SAFE_CANDIDATE,
    CANONICAL_NO_OFFICIAL_TOTAL_CANDIDATE,
    UNSAFE_UNIQUE_CANDIDATE,
    DUPLICATE_SLUG_CANDIDATE,
    EMPTY_SLUG_CANDIDATE,
    BARE_UUID_FALLBACK_CANDIDATE,
]
SAFE_URL = f"{BASE_URL}/candidate/{SAFE_CANDIDATE['slug']}"
CANONICAL_NO_OFFICIAL_TOTAL_URL = f"{BASE_URL}/candidate/{CANONICAL_NO_OFFICIAL_TOTAL_CANDIDATE['slug']}"
UNSAFE_URL = f"{BASE_URL}/candidate/{UNSAFE_UNIQUE_CANDIDATE['slug']}"
BARE_UUID_URL = f"{BASE_URL}/candidate/{BARE_UUID_FALLBACK_CANDIDATE['id']}"
EXPECTED_CANONICAL_OFFICIAL_TOTAL_URLS = [SAFE_URL]
EXPECTED_EXCLUDED_CANONICAL_URLS = [CANONICAL_NO_OFFICIAL_TOTAL_URL]


def _sitemap(candidate_urls: list[str], *, extra_urls: list[str] | None = None) -> str:
    locs = [f"{BASE_URL}/", *candidate_urls, f"{BASE_URL}/committees", *(extra_urls or [])]
    entries = "\n".join(f"  <url><loc>{loc}</loc></url>" for loc in locs)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{entries}\n"
        "</urlset>"
    )


def _sitemap_index(paths: list[str]) -> str:
    entries = "\n".join(
        f"  <sitemap><loc>{path if path.startswith(('http://', 'https://')) else f'{BASE_URL}{path}'}</loc></sitemap>"
        for path in paths
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{entries}\n"
        "</sitemapindex>"
    )


class FixtureSurface:
    def __init__(
        self,
        *,
        candidate_pages: list[dict],
        sitemap_xml: str | None = None,
        sitemap_xml_by_path: dict[str, str] | None = None,
        status_by_path: dict[str, int] | None = None,
    ) -> None:
        self.candidate_pages = candidate_pages
        if sitemap_xml is not None and sitemap_xml_by_path is not None:
            raise ValueError("Use either sitemap_xml or sitemap_xml_by_path")
        self.sitemap_xml_by_path = sitemap_xml_by_path or {"/sitemap.xml": sitemap_xml or ""}
        self.status_by_path = status_by_path or {}
        self.requested_paths: list[str] = []

    def fetch(self, url: str) -> HttpResponse:
        path = url.removeprefix(BASE_URL)
        self.requested_paths.append(path)
        status = self.status_by_path.get(path, 200)
        if path.startswith(PUBLIC_CANDIDATE_LIST_PATH):
            offset = int(path.split("offset=", 1)[1])
            page_index = offset // 200
            return HttpResponse(status_code=status, body=self.candidate_pages[page_index])
        if path in self.sitemap_xml_by_path:
            return HttpResponse(status_code=status, body=self.sitemap_xml_by_path[path])
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


def test_candidate_sitemap_oracle_accepts_canonical_official_total_sitemap() -> None:
    surface = FixtureSurface(
        candidate_pages=_candidate_pages(),
        sitemap_xml=_sitemap(EXPECTED_CANONICAL_OFFICIAL_TOTAL_URLS),
    )

    report = evaluate_candidate_sitemap(BASE_URL, surface.fetch)

    assert surface.requested_paths == [
        f"{PUBLIC_CANDIDATE_LIST_PATH}?limit=200&offset=0",
        f"{PUBLIC_CANDIDATE_LIST_PATH}?limit=200&offset=200",
        "/sitemap.xml",
    ]
    assert report.ok is True
    assert report.candidate_api_total == 6
    assert report.canonical_eligible_count == 1
    assert report.sitemap_url_count == 3
    assert report.sitemap_candidate_count == 1
    assert report.bare_uuid_candidate_url_count == 0
    assert report.duplicate_candidate_urls == []
    assert report.missing_eligible_urls == []
    assert report.unexpected_candidate_urls == []
    assert EXPECTED_CANONICAL_OFFICIAL_TOTAL_URLS == [SAFE_URL]
    assert EXPECTED_EXCLUDED_CANONICAL_URLS == [CANONICAL_NO_OFFICIAL_TOTAL_URL]
    assert report.verdict == "candidate_sitemap_oracle_ok"
    assert report.evidence() == "\n".join(
        [
            "candidate_api_total=6",
            "canonical_eligible_count=1",
            "sitemap_url_count=3",
            "sitemap_candidate_count=1",
            "bare_uuid_candidate_url_count=0",
            "duplicate_candidate_urls=none",
            "missing_eligible_urls=none",
            "unexpected_candidate_urls=none",
            "verdict=candidate_sitemap_oracle_ok",
        ]
    )


def test_candidate_sitemap_oracle_accepts_sitemap_index_union() -> None:
    surface = FixtureSurface(
        candidate_pages=_candidate_pages(),
        sitemap_xml_by_path={
            "/sitemap.xml": _sitemap_index(["/sitemap-static.xml", "/sitemap-candidate-0.xml"]),
            "/sitemap-static.xml": _sitemap([], extra_urls=[f"{BASE_URL}/about"]),
            "/sitemap-candidate-0.xml": _sitemap(EXPECTED_CANONICAL_OFFICIAL_TOTAL_URLS),
        },
    )

    report = evaluate_candidate_sitemap(BASE_URL, surface.fetch)

    assert surface.requested_paths == [
        f"{PUBLIC_CANDIDATE_LIST_PATH}?limit=200&offset=0",
        f"{PUBLIC_CANDIDATE_LIST_PATH}?limit=200&offset=200",
        "/sitemap.xml",
        "/sitemap-static.xml",
        "/sitemap-candidate-0.xml",
    ]
    assert report.ok is True
    assert report.candidate_api_total == 6
    assert report.canonical_eligible_count == 1
    assert report.sitemap_url_count == 6
    assert report.sitemap_candidate_count == 1
    assert report.bare_uuid_candidate_url_count == 0
    assert report.duplicate_candidate_urls == []
    assert report.missing_eligible_urls == []
    assert report.unexpected_candidate_urls == []
    assert report.verdict == "candidate_sitemap_oracle_ok"


def test_candidate_sitemap_oracle_fails_closed_on_bare_uuid_in_sitemap_index_shard() -> None:
    surface = FixtureSurface(
        candidate_pages=_candidate_pages(),
        sitemap_xml_by_path={
            "/sitemap.xml": _sitemap_index(["/sitemap-candidate-0.xml"]),
            "/sitemap-candidate-0.xml": _sitemap([SAFE_URL, BARE_UUID_URL]),
        },
    )

    report = evaluate_candidate_sitemap(BASE_URL, surface.fetch)

    assert report.ok is False
    assert report.sitemap_url_count == 4
    assert report.sitemap_candidate_count == 2
    assert report.bare_uuid_candidate_url_count == 1
    assert report.unexpected_candidate_urls == [BARE_UUID_URL]
    assert "bare_uuid_candidate_url_count=1" in report.evidence()
    assert f"unexpected_candidate_urls={BARE_UUID_URL}" in report.evidence()


@pytest.mark.parametrize(
    ("shard_loc", "status_by_path", "expected_error"),
    [
        (
            "/sitemap-candidate-0.xml",
            {"/sitemap-candidate-0.xml": 503},
            "sitemap_unexpected_http_status 503 path=/sitemap-candidate-0.xml",
        ),
        (
            "https://attacker.example/sitemap-candidate-0.xml",
            {},
            r"sitemap_shard_cross_origin https://attacker\.example/sitemap-candidate-0\.xml",
        ),
    ],
)
def test_candidate_sitemap_oracle_fails_closed_on_sitemap_index_shard_http_status(
    shard_loc: str,
    status_by_path: dict[str, int],
    expected_error: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    surface = FixtureSurface(
        candidate_pages=_candidate_pages(),
        sitemap_xml_by_path={
            "/sitemap.xml": _sitemap_index([shard_loc]),
            "/sitemap-candidate-0.xml": _sitemap([SAFE_URL]),
        },
        status_by_path=status_by_path,
    )

    with pytest.raises(OracleError, match=expected_error):
        evaluate_candidate_sitemap(BASE_URL, surface.fetch)

    if shard_loc.startswith("https://attacker.example"):

        class RedirectingOpener:
            def __init__(self, redirect_handler: object) -> None:
                self.redirect_handler = redirect_handler

            def open(self, request: object, timeout: int) -> object:
                assert timeout == oracle_module.HTTP_FETCH_TIMEOUT_SECONDS
                assert request.get_header("X-api-key") == "deploy-secret"
                return self.redirect_handler.redirect_request(
                    request,
                    None,
                    302,
                    "Found",
                    {},
                    "https://attacker.example/capture",
                )

        monkeypatch.setattr(
            oracle_module,
            "build_opener",
            lambda redirect_handler: RedirectingOpener(redirect_handler),
        )
        response = _build_http_fetch_url("deploy-secret")(f"{BASE_URL}{PUBLIC_CANDIDATE_LIST_PATH}?limit=200&offset=0")

        assert response.status_code == 302


def test_candidate_sitemap_oracle_renders_vacuous_for_empty_index_union() -> None:
    surface = FixtureSurface(
        candidate_pages=[
            {
                "items": [],
                "has_next": False,
                "offset": 0,
                "limit": 200,
            }
        ],
        sitemap_xml_by_path={"/sitemap.xml": _sitemap_index([])},
    )

    report = evaluate_candidate_sitemap(BASE_URL, surface.fetch)

    assert surface.requested_paths == [
        f"{PUBLIC_CANDIDATE_LIST_PATH}?limit=200&offset=0",
        "/sitemap.xml",
    ]
    assert report.ok is True
    assert report.candidate_api_total == 0
    assert report.canonical_eligible_count == 0
    assert report.sitemap_url_count == 0
    assert report.sitemap_candidate_count == 0
    assert report.verdict == "VACUOUS"
    assert report.evidence().endswith("verdict=VACUOUS")


@pytest.mark.parametrize(
    "malformed_candidate",
    [
        {key: value for key, value in SAFE_CANDIDATE.items() if key != "has_official_total"},
        {**SAFE_CANDIDATE, "has_official_total": "true"},
        {**SAFE_CANDIDATE, "has_official_total": 1},
    ],
)
def test_candidate_sitemap_oracle_fails_closed_on_malformed_has_official_total(
    malformed_candidate: dict,
) -> None:
    surface = FixtureSurface(
        candidate_pages=[
            {
                "items": [malformed_candidate],
                "has_next": False,
                "offset": 0,
                "limit": 200,
            }
        ],
        sitemap_xml=_sitemap([SAFE_URL]),
    )

    with pytest.raises(OracleError, match="candidate_json_malformed"):
        evaluate_candidate_sitemap(BASE_URL, surface.fetch)


@pytest.mark.parametrize(
    ("candidate_urls", "expected_evidence"),
    [
        ([UNSAFE_URL, SAFE_URL], f"unexpected_candidate_urls={UNSAFE_URL}"),
        (
            [CANONICAL_NO_OFFICIAL_TOTAL_URL, SAFE_URL],
            f"unexpected_candidate_urls={CANONICAL_NO_OFFICIAL_TOTAL_URL}",
        ),
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
        status_by_path={f"{PUBLIC_CANDIDATE_LIST_PATH}?limit=200&offset=0": 503},
    )

    with pytest.raises(OracleError, match="candidate_api_unexpected_http_status 503"):
        evaluate_candidate_sitemap(BASE_URL, surface.fetch)


def test_candidate_sitemap_oracle_fails_closed_on_sitemap_http_status() -> None:
    surface = FixtureSurface(
        candidate_pages=_candidate_pages(),
        sitemap_xml=_sitemap([SAFE_URL]),
        status_by_path={"/sitemap.xml": 503},
    )

    with pytest.raises(OracleError, match="sitemap_unexpected_http_status 503"):
        evaluate_candidate_sitemap(BASE_URL, surface.fetch)


@pytest.mark.parametrize(
    ("candidate_page_patch", "expected_error"),
    [
        ({"limit": 100}, "candidate_api_unexpected_page_limit 100"),
        ({"offset": 400}, "candidate_api_unexpected_page_offset expected=0 actual=400"),
    ],
)
def test_candidate_sitemap_oracle_fails_closed_on_candidate_page_contract_drift(
    candidate_page_patch: dict,
    expected_error: str,
) -> None:
    candidate_page = {
        "items": [SAFE_CANDIDATE],
        "has_next": False,
        "offset": 0,
        "limit": 200,
        **candidate_page_patch,
    }
    surface = FixtureSurface(candidate_pages=[candidate_page], sitemap_xml=_sitemap([SAFE_URL]))

    with pytest.raises(OracleError, match=expected_error):
        evaluate_candidate_sitemap(BASE_URL, surface.fetch)


def test_candidate_sitemap_oracle_reads_api_key_from_environment(tmp_path) -> None:
    env_path = tmp_path / "civibus-fly.env"
    env_path.write_text("CIVIBUS_API_KEY=file-key\nCIVIBUS_API_KEYS=file-list-key,second\n")

    assert _candidate_api_key({"CIVIBUS_API_KEY": "env-key"}, env_path) == "env-key"
    assert _candidate_api_key({"CIVIBUS_API_KEYS": "env-list-key,second"}, env_path) == "env-list-key"


def test_candidate_sitemap_oracle_reads_api_key_from_repo_secret_env_file(tmp_path) -> None:
    env_path = tmp_path / "civibus-fly.env"
    env_path.write_text("# local deploy proof secrets\nCIVIBUS_API_KEYS=file-list-key,second\n")

    assert _candidate_api_key({}, env_path) == "file-list-key"
