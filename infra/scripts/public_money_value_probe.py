#!/usr/bin/env python3
"""DB-free public money-value assertions for the deployed surface probe."""

import argparse
import http.client
import json
import sys
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict


STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_VACUOUS = "VACUOUS"
EXPECTED_FEC_MONEY_ROWS = 540
MINIMUM_NONEMPTY_ROWS = 1
HTTP_OK_STATUS = 200

EXPORT_PATH = "/api/public/v1/federal/export.json"
CANDIDATES_PATH = "/candidates"
COMMITTEES_PATH = "/committees"
CANDIDATE_ROW_TEST_ID = "candidate-result-row"
COMMITTEE_ROW_TEST_ID = "committee-result-row"
DONOR_ROW_TEST_ID = "donor-result-row"
RELEASE_TARGETS_PATH = Path("web/tests/smoke/production_release_targets.json")


class PublicMoneyAssertion(BaseModel):
    name: str
    status: str
    numerator: int
    denominator: int
    diagnostic: str

    def format_line(self) -> str:
        return (
            f"money_value_assertion {self.name} {self.status} "
            f"numerator={self.numerator} denominator={self.denominator} diagnostic={self.diagnostic}"
        )


class PublicMoneyProbeReport(BaseModel):
    assertions: list[PublicMoneyAssertion]

    @property
    def failed(self) -> bool:
        return any(assertion.status == STATUS_FAIL for assertion in self.assertions)


class SharedReleaseTargets(BaseModel):
    finance_visual_person_id: str
    finance_visual_person_name: str
    finance_visual_person_path: str
    finance_visual_minimum_total_raised: Decimal
    finance_visual_donor_query: str


class HttpPayload(BaseModel):
    status_code: int
    body: str = ""
    error: Optional[str] = None


class FederalExportMoneyRow(BaseModel):
    model_config = ConfigDict(extra="allow")

    person_id: str
    person_name: str
    has_fec_money: bool
    total_raised: Decimal
    ie_support_total: Decimal
    ie_oppose_total: Decimal


class TestIdCounter(HTMLParser):
    def __init__(self, test_id: str) -> None:
        super().__init__()
        self.test_id = test_id
        self.count = 0

    def handle_starttag(self, _tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if ("data-testid", self.test_id) in attrs:
            self.count += 1


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_release_targets() -> SharedReleaseTargets:
    payload = json.loads((_repo_root() / RELEASE_TARGETS_PATH).read_text(encoding="utf-8"))
    return SharedReleaseTargets.model_validate(payload)


def _normalized_base_url(raw_base_url: str) -> str:
    parsed = urlsplit(raw_base_url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("base URL must be an http(s) URL")
    if parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
        raise ValueError("base URL must not include credentials, query, or fragment")
    hostname = parsed.hostname
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    netloc = hostname if parsed.port is None else f"{hostname}:{parsed.port}"
    return f"{parsed.scheme}://{netloc}{parsed.path.rstrip('/')}"


def _route_slug(path: str) -> str:
    return path.encode("utf-8").hex()


def _fixture_status(fixture_dir: Path, path: str) -> int:
    status_path = fixture_dir / "helper_http_statuses.tsv"
    if not status_path.exists():
        return HTTP_OK_STATUS
    for line in status_path.read_text(encoding="utf-8").splitlines():
        route, separator, status = line.partition("\t")
        if separator and route == path:
            try:
                return int(status.strip())
            except ValueError:
                return 599
    return HTTP_OK_STATUS


def _fixture_payload(fixture_dir: Path, path: str) -> HttpPayload:
    body_path = fixture_dir / "helper_http_bodies" / f"{_route_slug(path)}.txt"
    status_code = _fixture_status(fixture_dir, path)
    if not body_path.exists():
        return HttpPayload(status_code=599, error=f"{path} fixture body missing")
    return HttpPayload(status_code=status_code, body=body_path.read_text(encoding="utf-8"))


def _fetch_http(base_url: str, path: str, fixture_dir: Optional[Path]) -> HttpPayload:
    if fixture_dir is not None:
        return _fixture_payload(fixture_dir, path)
    request = Request(f"{base_url}{path}", headers={"Accept": "text/html, application/json"})
    try:
        with urlopen(request, timeout=25) as response:
            return HttpPayload(status_code=response.status, body=response.read().decode("utf-8"))
    except HTTPError as error:
        return HttpPayload(status_code=error.code, error=f"{path} returned HTTP {error.code}")
    except URLError as error:
        return HttpPayload(status_code=599, error=f"{path} fetch error: {error.__class__.__name__}")
    except (http.client.IncompleteRead, OSError, UnicodeDecodeError) as error:
        return HttpPayload(status_code=599, error=f"{path} fetch error: {error.__class__.__name__}")


def _assert_http_ok(name: str, path: str, response: HttpPayload) -> PublicMoneyAssertion:
    status = STATUS_PASS if response.status_code == HTTP_OK_STATUS else STATUS_FAIL
    if status == STATUS_PASS:
        diagnostic = f"{path} returned HTTP 200"
    elif response.error is not None:
        diagnostic = f"{response.error}; expected HTTP 200"
    else:
        diagnostic = f"{path} returned HTTP {response.status_code}; expected 200"
    return PublicMoneyAssertion(
        name=name,
        status=status,
        numerator=response.status_code,
        denominator=HTTP_OK_STATUS,
        diagnostic=diagnostic,
    )


def _fail(name: str, diagnostic: str) -> PublicMoneyAssertion:
    return PublicMoneyAssertion(name=name, status=STATUS_FAIL, numerator=0, denominator=1, diagnostic=diagnostic)


def _parse_export_rows(response: HttpPayload) -> tuple[list[FederalExportMoneyRow], Optional[PublicMoneyAssertion]]:
    if response.status_code != HTTP_OK_STATUS:
        return [], None
    if response.error is not None:
        return [], _fail("export_payload", response.error)
    try:
        payload = json.loads(response.body)
    except json.JSONDecodeError as error:
        return [], _fail("export_payload", f"{EXPORT_PATH} malformed JSON: {error.__class__.__name__}")
    if not isinstance(payload, list):
        return [], _fail("export_payload", f"{EXPORT_PATH} JSON payload must be a list")
    try:
        return [FederalExportMoneyRow.model_validate(row) for row in payload], None
    except Exception as error:  # noqa: BLE001 - probe output must stay stable for malformed contracts
        return [], _fail("export_payload", f"{EXPORT_PATH} row validation failed: {error.__class__.__name__}")


def _coverage_assertion(rows: list[FederalExportMoneyRow]) -> PublicMoneyAssertion:
    denominator = len(rows)
    numerator = sum(1 for row in rows if row.has_fec_money)
    if denominator == 0:
        return PublicMoneyAssertion(
            name="fec_money_coverage",
            status=STATUS_VACUOUS,
            numerator=0,
            denominator=0,
            diagnostic="0/0 public export rows available; cannot assert FEC money coverage",
        )
    status = (
        STATUS_PASS if numerator == EXPECTED_FEC_MONEY_ROWS and denominator == EXPECTED_FEC_MONEY_ROWS else STATUS_FAIL
    )
    diagnostic = f"{numerator}/{denominator} public export rows have FEC money"
    if status == STATUS_FAIL:
        diagnostic = f"{diagnostic}; expected {EXPECTED_FEC_MONEY_ROWS}"
    return PublicMoneyAssertion(
        name="fec_money_coverage",
        status=status,
        numerator=numerator,
        denominator=denominator,
        diagnostic=diagnostic,
    )


def _specimen_total_assertion(rows: list[FederalExportMoneyRow], targets: SharedReleaseTargets) -> PublicMoneyAssertion:
    denominator = len(rows)
    if denominator == 0:
        return PublicMoneyAssertion(
            name="specimen_total_raised",
            status=STATUS_VACUOUS,
            numerator=0,
            denominator=0,
            diagnostic="0/0 public export rows available; cannot assert specimen total_raised",
        )
    specimen = next((row for row in rows if row.person_id == targets.finance_visual_person_id), None)
    if specimen is None:
        return PublicMoneyAssertion(
            name="specimen_total_raised",
            status=STATUS_FAIL,
            numerator=0,
            denominator=denominator,
            diagnostic=f"{targets.finance_visual_person_id} missing from public export",
        )
    passed = specimen.total_raised >= targets.finance_visual_minimum_total_raised and specimen.total_raised > Decimal(
        "0"
    )
    return PublicMoneyAssertion(
        name="specimen_total_raised",
        status=STATUS_PASS if passed else STATUS_FAIL,
        numerator=1 if passed else 0,
        denominator=1,
        diagnostic=(
            f"{targets.finance_visual_person_name} total_raised={specimen.total_raised} "
            f"minimum={targets.finance_visual_minimum_total_raised}"
        ),
    )


def _nonzero_money_assertion(
    name: str,
    rows: list[FederalExportMoneyRow],
    field_name: str,
    label: str,
) -> PublicMoneyAssertion:
    denominator = len(rows)
    if denominator == 0:
        return PublicMoneyAssertion(
            name=name,
            status=STATUS_VACUOUS,
            numerator=0,
            denominator=0,
            diagnostic=f"0/0 public export rows available; cannot assert {label}",
        )
    numerator = sum(1 for row in rows if getattr(row, field_name) > Decimal("0"))
    return PublicMoneyAssertion(
        name=name,
        status=STATUS_PASS if numerator >= MINIMUM_NONEMPTY_ROWS else STATUS_FAIL,
        numerator=numerator,
        denominator=denominator,
        diagnostic=f"{numerator}/{denominator} public export rows have nonzero {label}",
    )


def _count_rendered_rows(body: str, row_test_id: str) -> int:
    parser = TestIdCounter(row_test_id)
    parser.feed(body)
    parser.close()
    return parser.count


def _nonempty_rendered_result_assertion(
    name: str,
    path: str,
    response: HttpPayload,
    row_test_id: str,
) -> PublicMoneyAssertion:
    if response.error is not None:
        return _fail(name, response.error)
    if response.status_code != HTTP_OK_STATUS:
        return _fail(name, f"{path} returned HTTP {response.status_code}; expected 200")
    row_count = _count_rendered_rows(response.body, row_test_id)
    return PublicMoneyAssertion(
        name=name,
        status=STATUS_PASS if row_count >= MINIMUM_NONEMPTY_ROWS else STATUS_FAIL,
        numerator=row_count,
        denominator=max(row_count, 1),
        diagnostic=f"{path} rendered {row_count} result rows",
    )


def evaluate_public_money_value(base_url: str, fixture_dir: Optional[Path] = None) -> PublicMoneyProbeReport:
    targets = _load_release_targets()
    donor_path = f"/donors?q={quote(targets.finance_visual_donor_query)}&by=name"
    responses = {
        EXPORT_PATH: _fetch_http(base_url, EXPORT_PATH, fixture_dir),
        CANDIDATES_PATH: _fetch_http(base_url, CANDIDATES_PATH, fixture_dir),
        COMMITTEES_PATH: _fetch_http(base_url, COMMITTEES_PATH, fixture_dir),
        donor_path: _fetch_http(base_url, donor_path, fixture_dir),
    }
    export_rows, export_error = _parse_export_rows(responses[EXPORT_PATH])

    assertions = [
        _assert_http_ok("federal_export_http", EXPORT_PATH, responses[EXPORT_PATH]),
    ]
    if export_error is not None:
        assertions.append(export_error)
    assertions.extend(
        [
            _coverage_assertion(export_rows),
            _specimen_total_assertion(export_rows, targets),
            _nonzero_money_assertion("ie_support_nonzero", export_rows, "ie_support_total", "ie_support_total"),
            _nonzero_money_assertion("ie_oppose_nonzero", export_rows, "ie_oppose_total", "ie_oppose_total"),
            _assert_http_ok("candidates_http", CANDIDATES_PATH, responses[CANDIDATES_PATH]),
            _nonempty_rendered_result_assertion(
                "candidates_rows", CANDIDATES_PATH, responses[CANDIDATES_PATH], CANDIDATE_ROW_TEST_ID
            ),
            _assert_http_ok("committees_http", COMMITTEES_PATH, responses[COMMITTEES_PATH]),
            _nonempty_rendered_result_assertion(
                "committees_rows", COMMITTEES_PATH, responses[COMMITTEES_PATH], COMMITTEE_ROW_TEST_ID
            ),
            _assert_http_ok("donor_search_http", donor_path, responses[donor_path]),
            _nonempty_rendered_result_assertion(
                "donor_search_rows", donor_path, responses[donor_path], DONOR_ROW_TEST_ID
            ),
        ]
    )
    return PublicMoneyProbeReport(assertions=assertions)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--fixture-dir", default="")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        base_url = _normalized_base_url(args.base_url)
    except ValueError as error:
        print(f"money_value_probe_invalid_base_url {error}", file=sys.stderr)
        return 1
    fixture_dir = Path(args.fixture_dir) if args.fixture_dir else None
    report = evaluate_public_money_value(base_url, fixture_dir)
    for assertion in report.assertions:
        print(assertion.format_line())
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
