#!/usr/bin/env python3
"""Deploy-proof oracle for candidate URLs in the public sitemap."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from pydantic import BaseModel, ConfigDict, StrictBool, ValidationError


BATCH_LIMIT = 200
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

    def evidence(self) -> str:
        return "\n".join(
            [
                f"candidate_api_total={self.candidate_api_total}",
                f"canonical_eligible_count={self.canonical_eligible_count}",
                f"sitemap_candidate_count={self.sitemap_candidate_count}",
                f"bare_uuid_candidate_url_count={self.bare_uuid_candidate_url_count}",
                f"duplicate_candidate_urls={_format_values(self.duplicate_candidate_urls)}",
                f"missing_eligible_urls={_format_values(self.missing_eligible_urls)}",
                f"unexpected_candidate_urls={_format_values(self.unexpected_candidate_urls)}",
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


def _loc_texts(xml_body: str) -> list[str]:
    try:
        root = ElementTree.fromstring(xml_body)
    except ElementTree.ParseError as exc:
        raise OracleError(f"sitemap_xml_malformed {exc}") from exc
    locs: list[str] = []
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] == "loc" and element.text:
            locs.append(element.text.strip())
    return locs


def _fetch_sitemap_locs(fetch_url: FetchUrl, base_url: str) -> list[str]:
    response = fetch_url(_build_url(base_url, "/sitemap.xml"))
    if response.status_code != 200:
        raise OracleError(f"sitemap_unexpected_http_status {response.status_code} path=/sitemap.xml")
    if not isinstance(response.body, str):
        raise OracleError("sitemap_xml_malformed")
    return _loc_texts(response.body)


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
    sitemap_candidate_urls = [loc for loc in _fetch_sitemap_locs(fetch_url, canonical_base) if _is_candidate_url(loc)]
    sitemap_counts = Counter(sitemap_candidate_urls)
    duplicate_urls = sorted(url for url, count in sitemap_counts.items() if count > 1)
    unique_sitemap_urls = set(sitemap_candidate_urls)

    return CandidateSitemapReport(
        candidate_api_total=len(candidates),
        canonical_eligible_count=len(eligible_urls),
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
    def fetch_url(url: str) -> HttpResponse:
        headers = {"User-Agent": "civibus-candidate-sitemap-oracle/1.0"}
        if candidate_api_key and urlparse(url).path.startswith(PUBLIC_CANDIDATE_LIST_PATH):
            headers["X-API-Key"] = candidate_api_key
        request = Request(url, headers=headers)
        try:
            with urlopen(request, timeout=60) as response:
                body = response.read().decode(response.headers.get_content_charset() or "utf-8")
                return HttpResponse(status_code=response.status, body=body)
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            return HttpResponse(status_code=exc.code, body=body)
        except URLError as exc:
            raise OracleError(f"http_request_failed {url} {exc.reason}") from exc

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
        print("candidate_sitemap_oracle_ok")
        return 0
    print("candidate_sitemap_oracle_failed", file=sys.stderr)
    print(report.evidence(), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
