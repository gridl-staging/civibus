#!/usr/bin/env python3
"""Deploy-proof oracle for candidate URLs in the public sitemap."""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener
from xml.etree import ElementTree

from pydantic import BaseModel, ConfigDict, StrictBool, ValidationError


BATCH_LIMIT = 200
HTTP_FETCH_TIMEOUT_SECONDS = 15
PUBLIC_CANDIDATE_LIST_PATH = "/api/v1/candidates"
REPO_SECRET_ENV_PATH = Path(__file__).resolve().parents[2] / ".secret" / "civibus-fly.env"
BARE_UUID_CANDIDATE_PATH = re.compile(
    r"^/candidate/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


class OracleError(RuntimeError):
    """Raised when the deploy-proof surface cannot be evaluated safely."""


class HttpResponse(BaseModel):
    status_code: int
    body: Any


class CandidateListItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    slug: str
    slug_is_unique: bool
    identity_is_safe: bool
    has_official_total: StrictBool


class CandidateListPage(BaseModel):
    model_config = ConfigDict(extra="allow")

    items: list[CandidateListItem]
    has_next: bool
    offset: int
    limit: int


class CandidateSitemapReport(BaseModel):
    candidate_api_total: int
    canonical_eligible_count: int
    sitemap_url_count: int
    sitemap_candidate_count: int
    bare_uuid_candidate_url_count: int
    duplicate_candidate_urls: list[str]
    missing_eligible_urls: list[str]
    unexpected_candidate_urls: list[str]

    @property
    def ok(self) -> bool:
        return (
            self.bare_uuid_candidate_url_count == 0
            and not self.duplicate_candidate_urls
            and not self.missing_eligible_urls
            and not self.unexpected_candidate_urls
        )

    @property
    def verdict(self) -> str:
        if not self.ok:
            return "candidate_sitemap_oracle_failed"
        if self.canonical_eligible_count == 0:
            return "VACUOUS"
        return "candidate_sitemap_oracle_ok"

    @property
    def exit_code(self) -> int:
        return 0 if self.ok else 1

    def evidence(self) -> str:
        return "\n".join(
            [
                f"candidate_api_total={self.candidate_api_total}",
                f"canonical_eligible_count={self.canonical_eligible_count}",
                f"sitemap_url_count={self.sitemap_url_count}",
                f"sitemap_candidate_count={self.sitemap_candidate_count}",
                f"bare_uuid_candidate_url_count={self.bare_uuid_candidate_url_count}",
                f"duplicate_candidate_urls={_format_values(self.duplicate_candidate_urls)}",
                f"missing_eligible_urls={_format_values(self.missing_eligible_urls)}",
                f"unexpected_candidate_urls={_format_values(self.unexpected_candidate_urls)}",
                f"verdict={self.verdict}",
            ]
        )


FetchUrl = Callable[[str], HttpResponse]


def _format_values(values: list[str]) -> str:
    return ",".join(values) if values else "none"


def _canonical_base_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise OracleError("base_url_invalid")
    return normalized


def _build_url(base_url: str, path: str) -> str:
    return urljoin(f"{base_url}/", path.lstrip("/"))


def _decode_json_body(response: HttpResponse, *, label: str) -> dict[str, Any]:
    if isinstance(response.body, dict):
        return response.body
    if not isinstance(response.body, str):
        raise OracleError(f"{label}_json_malformed")
    try:
        payload = json.loads(response.body)
    except json.JSONDecodeError as exc:
        raise OracleError(f"{label}_json_malformed {exc}") from exc
    if not isinstance(payload, dict):
        raise OracleError(f"{label}_json_malformed")
    return payload


def _fetch_candidate_page(fetch_url: FetchUrl, base_url: str, offset: int) -> CandidateListPage:
    path = f"{PUBLIC_CANDIDATE_LIST_PATH}?limit={BATCH_LIMIT}&offset={offset}"
    response = fetch_url(_build_url(base_url, path))
    if response.status_code != 200:
        raise OracleError(f"candidate_api_unexpected_http_status {response.status_code} path={path}")
    payload = _decode_json_body(response, label="candidate")
    try:
        page = CandidateListPage.model_validate(payload)
    except ValidationError as exc:
        raise OracleError(f"candidate_json_malformed {exc}") from exc
    if page.limit != BATCH_LIMIT:
        raise OracleError(f"candidate_api_unexpected_page_limit {page.limit}")
    if page.offset != offset:
        raise OracleError(f"candidate_api_unexpected_page_offset expected={offset} actual={page.offset}")
    return page


def _collect_candidates(fetch_url: FetchUrl, base_url: str) -> list[CandidateListItem]:
    candidates: list[CandidateListItem] = []
    offset = 0
    while True:
        page = _fetch_candidate_page(fetch_url, base_url, offset)
        candidates.extend(page.items)
        if not page.has_next:
            return candidates
        offset += BATCH_LIMIT


def has_canonical_candidate_slug(candidate: CandidateListItem) -> bool:
    """Deploy-proof mirror of web hasCanonicalCandidateSlug, not route policy ownership."""
    return candidate.identity_is_safe and candidate.slug_is_unique and candidate.slug != ""


def _candidate_url(base_url: str, candidate: CandidateListItem) -> str:
    return _build_url(base_url, f"/candidate/{candidate.slug}")


def _local_name(element: ElementTree.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _parse_sitemap_xml(xml_body: str) -> tuple[str, list[str]]:
    try:
        root = ElementTree.fromstring(xml_body)
    except ElementTree.ParseError as exc:
        raise OracleError(f"sitemap_xml_malformed {exc}") from exc
    root_name = _local_name(root)
    if root_name not in {"urlset", "sitemapindex"}:
        raise OracleError(f"sitemap_xml_unexpected_root {root_name}")
    locs: list[str] = []
    for element in root.iter():
        if _local_name(element) == "loc" and element.text:
            locs.append(element.text.strip())
    return root_name, locs


def _loc_texts(xml_body: str) -> list[str]:
    return _parse_sitemap_xml(xml_body)[1]


def _sitemap_error_path(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path or "/"
    return f"{path}?{parsed.query}" if parsed.query else path


def _fetch_sitemap_xml(fetch_url: FetchUrl, url: str) -> str:
    response = fetch_url(url)
    if response.status_code != 200:
        raise OracleError(f"sitemap_unexpected_http_status {response.status_code} path={_sitemap_error_path(url)}")
    if not isinstance(response.body, str):
        raise OracleError("sitemap_xml_malformed")
    return response.body


def _sitemap_loc_fetch_url(base_url: str, loc: str) -> str:
    base = urlparse(base_url)
    parsed = urlparse(loc)
    if parsed.scheme or parsed.netloc:
        if parsed.scheme != base.scheme or parsed.netloc != base.netloc:
            raise OracleError(f"sitemap_shard_cross_origin {loc}")
        return loc
    return _build_url(base_url, loc)


def _fetch_sitemap_locs(fetch_url: FetchUrl, base_url: str) -> list[str]:
    root_body = _fetch_sitemap_xml(fetch_url, _build_url(base_url, "/sitemap.xml"))
    root_kind, root_locs = _parse_sitemap_xml(root_body)
    if root_kind == "urlset":
        return root_locs

    locs: list[str] = []
    for shard_loc in root_locs:
        shard_body = _fetch_sitemap_xml(fetch_url, _sitemap_loc_fetch_url(base_url, shard_loc))
        shard_kind, shard_locs = _parse_sitemap_xml(shard_body)
        if shard_kind != "urlset":
            raise OracleError(f"sitemap_shard_unexpected_root {shard_kind} path={_sitemap_error_path(shard_loc)}")
        locs.extend(shard_locs)
    return locs


def _is_candidate_url(value: str) -> bool:
    return urlparse(value).path.startswith("/candidate/")


def _is_bare_uuid_candidate_url(value: str) -> bool:
    return bool(BARE_UUID_CANDIDATE_PATH.match(urlparse(value).path))


def evaluate_candidate_sitemap(base_url: str, fetch_url: FetchUrl) -> CandidateSitemapReport:
    canonical_base = _canonical_base_url(base_url)
    candidates = _collect_candidates(fetch_url, canonical_base)
    eligible_urls = sorted(
        _candidate_url(canonical_base, item)
        for item in candidates
        if has_canonical_candidate_slug(item) and item.has_official_total
    )
    sitemap_locs = _fetch_sitemap_locs(fetch_url, canonical_base)
    sitemap_candidate_urls = [loc for loc in sitemap_locs if _is_candidate_url(loc)]
    sitemap_counts = Counter(sitemap_candidate_urls)
    duplicate_urls = sorted(url for url, count in sitemap_counts.items() if count > 1)
    unique_sitemap_urls = set(sitemap_candidate_urls)

    return CandidateSitemapReport(
        candidate_api_total=len(candidates),
        canonical_eligible_count=len(eligible_urls),
        sitemap_url_count=len(sitemap_locs),
        sitemap_candidate_count=len(sitemap_candidate_urls),
        bare_uuid_candidate_url_count=sum(1 for url in sitemap_candidate_urls if _is_bare_uuid_candidate_url(url)),
        duplicate_candidate_urls=duplicate_urls,
        missing_eligible_urls=sorted(set(eligible_urls) - unique_sitemap_urls),
        unexpected_candidate_urls=sorted(unique_sitemap_urls - set(eligible_urls)),
    )


def _read_env_file_api_key(path: Path) -> str:
    if not path.exists():
        return ""
    values: dict[str, str] = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values.get("CIVIBUS_API_KEY", "") or values.get("CIVIBUS_API_KEYS", "").split(",", 1)[0].strip()


def _candidate_api_key(environ: dict[str, str] | None = None, env_path: Path = REPO_SECRET_ENV_PATH) -> str:
    source = os.environ if environ is None else environ
    return (
        source.get("CIVIBUS_API_KEY", "")
        or source.get("CIVIBUS_API_KEYS", "").split(",", 1)[0].strip()
        or _read_env_file_api_key(env_path)
    )


def _build_http_fetch_url(candidate_api_key: str) -> FetchUrl:
    class FailClosedRedirectHandler(HTTPRedirectHandler):
        def redirect_request(
            self,
            req: Request,
            fp: Any,
            code: int,
            msg: str,
            headers: Any,
            newurl: str,
        ) -> Request:
            # urllib otherwise copies X-API-Key to redirected requests, including
            # cross-origin targets. The oracle requires operators to supply the
            # canonical public origin, so redirects are evidence failures.
            raise HTTPError(req.full_url, code, "redirect_not_allowed", headers, fp)

    opener = build_opener(FailClosedRedirectHandler())

    def fetch_url(url: str) -> HttpResponse:
        headers = {"User-Agent": "civibus-candidate-sitemap-oracle/1.0"}
        if candidate_api_key and urlparse(url).path.startswith(PUBLIC_CANDIDATE_LIST_PATH):
            headers["X-API-Key"] = candidate_api_key
        request = Request(url, headers=headers)
        try:
            with opener.open(request, timeout=HTTP_FETCH_TIMEOUT_SECONDS) as response:
                body = response.read().decode(response.headers.get_content_charset() or "utf-8")
                return HttpResponse(status_code=response.status, body=body)
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            return HttpResponse(status_code=exc.code, body=body)
        except URLError as exc:
            raise OracleError(f"http_request_failed {url} {exc.reason}") from exc
        except TimeoutError as exc:
            raise OracleError(f"http_request_failed {url} timed out") from exc
        except socket.timeout as exc:
            raise OracleError(f"http_request_failed {url} timed out") from exc

    return fetch_url


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate canonical candidate URLs in a public sitemap.")
    parser.add_argument(
        "--base-url", required=True, help="Public origin to inspect, for example https://civibus.example"
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    try:
        report = evaluate_candidate_sitemap(args.base_url, _build_http_fetch_url(_candidate_api_key()))
    except OracleError as exc:
        print(f"candidate_sitemap_oracle_error {exc}", file=sys.stderr)
        return 2
    print(report.evidence())
    if report.ok:
        print(report.verdict)
        return report.exit_code
    print(report.verdict, file=sys.stderr)
    print(report.evidence(), file=sys.stderr)
    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
