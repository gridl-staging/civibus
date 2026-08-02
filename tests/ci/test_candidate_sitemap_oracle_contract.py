"""Contract tests for the candidate sitemap deploy-proof oracle."""

from __future__ import annotations

import socket
from urllib.error import HTTPError
from urllib.request import Request

import pytest

import infra.scripts.candidate_sitemap_oracle as oracle_module
from infra.scripts.candidate_sitemap_oracle import (
    HttpResponse,
    OracleError,
    PUBLIC_CANDIDATE_LIST_PATH,
    _build_http_fetch_url,
    _candidate_api_key,
    _candidate_api_key_source,
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
    assert report.exit_code == 0
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


def test_candidate_sitemap_oracle_renders_vacuous_for_empty_index_union(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
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
    assert report.exit_code == 1
    assert report.evidence().endswith("verdict=VACUOUS")

    monkeypatch.setattr(oracle_module, "_candidate_api_key", lambda: None)
    monkeypatch.setattr(oracle_module, "evaluate_candidate_sitemap", lambda *_args: report)
    monkeypatch.setattr(
        oracle_module.sys,
        "argv",
        ["candidate_sitemap_oracle.py", "--base-url", BASE_URL],
    )

    assert oracle_module.main() == 1
    captured = capsys.readouterr()
    assert captured.out.endswith("verdict=VACUOUS\n")
    assert captured.err.startswith("VACUOUS\n")


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
    assert report.exit_code == 1
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


def test_candidate_sitemap_oracle_fails_closed_when_pagination_cannot_advance() -> None:
    surface = FixtureSurface(
        candidate_pages=[
            {
                "items": [],
                "has_next": True,
                "offset": 0,
                "limit": 200,
            }
        ],
        sitemap_xml=_sitemap([]),
    )

    with pytest.raises(OracleError, match="candidate_api_empty_page_with_next offset=0"):
        evaluate_candidate_sitemap(BASE_URL, surface.fetch)

    assert surface.requested_paths == [f"{PUBLIC_CANDIDATE_LIST_PATH}?limit=200&offset=0"]


def test_candidate_sitemap_oracle_reads_api_key_from_environment(tmp_path) -> None:
    env_path = tmp_path / "civibus-fly.env"
    env_path.write_text("CIVIBUS_API_KEY=file-key\nCIVIBUS_API_KEYS=file-list-key,second\n")

    assert _candidate_api_key({"CIVIBUS_API_KEY": "env-key"}, env_path) == "env-key"
    assert _candidate_api_key({"CIVIBUS_API_KEYS": "env-list-key,second"}, env_path) == "env-list-key"
    assert _candidate_api_key_source({"CIVIBUS_API_KEY": "env-key"}, env_path) == "environment"
    assert _candidate_api_key_source({"CIVIBUS_API_KEYS": "env-list-key,second"}, env_path) == "environment"


def test_candidate_sitemap_oracle_reads_api_key_from_repo_secret_env_file(tmp_path) -> None:
    env_path = tmp_path / "civibus-fly.env"
    env_path.write_text("# local deploy proof secrets\nCIVIBUS_API_KEYS=file-list-key,second\n")

    assert _candidate_api_key({}, env_path) == "file-list-key"
    assert _candidate_api_key_source({}, env_path) == "repo_env_file"


class _StubHttpResponse:
    """Minimal context-manager response for the spy opener seam."""

    def __init__(self, *, status: int = 200, body: bytes = b"{}", charset: str | None = "utf-8") -> None:
        self.status = status
        self._body = body
        self._charset = charset

    def __enter__(self) -> "_StubHttpResponse":
        return self

    def __exit__(self, *_args: object) -> bool:
        return False

    def read(self) -> bytes:
        return self._body

    @property
    def headers(self) -> object:
        charset = self._charset

        class _Headers:
            def get_content_charset(self) -> str | None:
                return charset

        return _Headers()


class _SpyOpener:
    """Records the timeout and requests reaching opener.open for the fetch seam."""

    def __init__(self) -> None:
        self.redirect_handler: object | None = None
        self.captured_timeouts: list[object] = []
        self.captured_requests: list[Request] = []
        self.raise_exc: BaseException | None = None

    def open(self, request: Request, timeout: object) -> object:
        self.captured_timeouts.append(timeout)
        self.captured_requests.append(request)
        if self.raise_exc is not None:
            raise self.raise_exc
        return _StubHttpResponse()


def _install_spy_opener(monkeypatch: pytest.MonkeyPatch, spy: _SpyOpener) -> None:
    def _factory(redirect_handler: object) -> _SpyOpener:
        spy.redirect_handler = redirect_handler
        return spy

    monkeypatch.setattr(oracle_module, "build_opener", _factory)


def test_candidate_sitemap_oracle_widens_http_fetch_timeout_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    spy = _SpyOpener()
    _install_spy_opener(monkeypatch, spy)

    response = _build_http_fetch_url("deploy-secret")(f"{BASE_URL}{PUBLIC_CANDIDATE_LIST_PATH}?limit=200&offset=0")

    assert response.status_code == 200
    assert spy.captured_timeouts, "opener.open was never called"
    # Post-repair budget must be at least 30s; red against HTTP_FETCH_TIMEOUT_SECONDS = 15.
    assert spy.captured_timeouts[0] >= 30


@pytest.mark.parametrize("timeout_exc", [TimeoutError("read timed out"), socket.timeout("read timed out")])
def test_candidate_sitemap_oracle_fails_closed_on_fetch_timeout(
    monkeypatch: pytest.MonkeyPatch, timeout_exc: BaseException
) -> None:
    spy = _SpyOpener()
    spy.raise_exc = timeout_exc
    _install_spy_opener(monkeypatch, spy)

    fetch_url = _build_http_fetch_url("deploy-secret")
    with pytest.raises(OracleError, match=r"http_request_failed .* timed out"):
        fetch_url(f"{BASE_URL}{PUBLIC_CANDIDATE_LIST_PATH}?limit=200&offset=0")


def test_candidate_sitemap_oracle_fetch_preserves_security_invariants(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    spy = _SpyOpener()
    _install_spy_opener(monkeypatch, spy)

    fetch_url = _build_http_fetch_url("deploy-secret")
    with pytest.raises(OracleError, match="candidate_api_key_requires_https"):
        fetch_url(f"http://civibus.example{PUBLIC_CANDIDATE_LIST_PATH}?limit=200&offset=0")

    fetch_url(f"{BASE_URL}{PUBLIC_CANDIDATE_LIST_PATH}?limit=200&offset=0")
    fetch_url(f"{BASE_URL}/sitemap.xml")

    candidate_request, sitemap_request = spy.captured_requests
    # X-API-Key stays scoped to the candidate-list path; widening the budget must
    # not begin attaching it to other origins/paths.
    assert candidate_request.get_header("X-api-key") == "deploy-secret"
    assert sitemap_request.get_header("X-api-key") is None

    # Redirects are rejected fail-closed so the key can never follow a
    # non-same-origin 3xx to an attacker-controlled target.
    assert isinstance(spy.redirect_handler, oracle_module.HTTPRedirectHandler)
    with pytest.raises(HTTPError):
        spy.redirect_handler.redirect_request(
            Request(f"{BASE_URL}/candidate/x"),
            None,
            302,
            "Found",
            {},
            "https://attacker.example/capture",
        )

    monkeypatch.setattr(oracle_module, "_candidate_api_key", lambda: "deploy-secret")
    monkeypatch.setattr(oracle_module, "_candidate_api_key_source", lambda: "repo_env_file")
    monkeypatch.setattr(
        oracle_module,
        "evaluate_candidate_sitemap",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected evaluation")),
    )
    monkeypatch.setattr(
        oracle_module.sys,
        "argv",
        ["candidate_sitemap_oracle.py", "--base-url", "https://attacker.example"],
    )

    assert oracle_module.main() == 2
    assert "candidate_sitemap_oracle_error base_url_untrusted_for_repo_api_key" in capsys.readouterr().err


def test_candidate_sitemap_oracle_rejects_repo_secret_key_for_localhost(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(oracle_module, "_candidate_api_key", lambda: "deploy-secret")
    monkeypatch.setattr(oracle_module, "_candidate_api_key_source", lambda: "repo_env_file")
    monkeypatch.setattr(
        oracle_module,
        "evaluate_candidate_sitemap",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected evaluation")),
    )
    monkeypatch.setattr(
        oracle_module.sys,
        "argv",
        ["candidate_sitemap_oracle.py", "--base-url", "http://127.0.0.1:8080"],
    )

    assert oracle_module.main() == 2
    assert "candidate_sitemap_oracle_error base_url_untrusted_for_repo_api_key" in capsys.readouterr().err
