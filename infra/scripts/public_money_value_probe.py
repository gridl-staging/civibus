#!/usr/bin/env python3
"""DB-free public money-value assertions for the deployed surface probe."""

import argparse
import http.client
import json
import random
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, field_validator

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from core.people.federal_officeholders import (  # noqa: E402
    SEATED_FEDERAL_OFFICIALS_MAX,
    SEATED_FEDERAL_OFFICIALS_MIN,
)


STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_VACUOUS = "VACUOUS"
PROMOTED_FATAL_ASSERTIONS = frozenset(
    {
        "fec_money_coverage",
        "federal_export_http",
        "specimen_total_raised",
        "ie_support_nonzero",
        "ie_oppose_nonzero",
        "candidates_http",
        "candidates_rows",
        "committees_http",
        "committees_rows",
    }
)
MINIMUM_NONEMPTY_ROWS = 1
HTTP_OK_STATUS = 200

EXPORT_PATH = "/api/public/v1/federal/export.json"
CANDIDATES_PATH = "/candidates"
COMMITTEES_PATH = "/committees"
CANDIDATE_ROW_TEST_ID = "candidate-result-row"
COMMITTEE_ROW_TEST_ID = "committee-result-row"
DONOR_ROW_TEST_ID = "donor-result-row"
RELEASE_TARGETS_PATH = Path("web/tests/smoke/production_release_targets.json")

# --- Indexed-page coverage sampling -----------------------------------------
#
# Everything below runs only when --sample-indexed-candidates is passed a
# positive number. The deploy lane (infra/scripts/probe_deployed_surface_parity.sh)
# does not pass it, so the gating assertion set above is unchanged. This lane is
# a network sample over live indexed pages and belongs in a probe run, never in
# a fast test tier.
#
# What it exists for: the only way to know whether the site publishes a dollar
# figure it cannot justify is to read what the server actually served AND what
# the page actually rendered, on the same URL, at the same moment. A one-off
# script that measures that once and is thrown away is how a stale impact number
# outlives the defect it described.

SITEMAP_INDEX_PATH = "/sitemap.xml"
CANDIDATE_SITEMAP_BASENAME_PREFIX = "sitemap-candidate-"
SITEMAP_LOC_PATTERN = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>")
# Deliberately fixed rather than time-seeded: a probe whose sample changes on
# every run cannot be used to compare two deploys.
DEFAULT_SAMPLE_SEED = 20260819

MONEY_GLANCE_CLASS = "detail__money-glance"
PERSON_MONEY_NOT_LOADED_TEST_ID = "person-money-not-loaded"
# Matches a rendered currency figure such as "$0.00" or "$1,234,567.89". The
# rendered page is the only place the reader's claim exists, so this is what the
# render half of the probe counts.
RENDERED_CURRENCY_PATTERN = re.compile(r"\$[0-9][0-9,]*\.[0-9]{2}")

# The states api/queries/campaign_finance.py::_candidate_money_coverage callers
# can emit. Fundraising adds out_of_cycle_official_total; Schedule E cannot
# carry it (a prior cycle's IE total is never promoted). An observed state that
# is not in these sets fails the run rather than being silently counted honest:
# the probe would not know which of the four true statements it implies.
KNOWN_FUNDRAISING_ACTIVITY_STATES = frozenset({"populated", "loaded_zero", "not_loaded", "out_of_cycle_official_total"})
KNOWN_IE_ACTIVITY_STATES = frozenset({"populated", "loaded_zero", "not_loaded"})
# The fundraising states that assert filings were actually read. Each one owes
# the reader the figure it read -- including a zero. ``None`` is in the set
# because ``public_money_totals`` attaches a coverage block only when it carries
# news, so an absent block on an export row means "populated".
#
# Deliberately restated here rather than imported from
# ``api.routes.public_federal``. This module is a DB-free probe that runs
# against a deployed URL and never imports the application, and more to the
# point a guard sharing the implementation's constant cannot catch a change to
# that constant -- the two agreeing is the thing being checked.
_MEASURED_FUNDRAISING_ACTIVITY_STATES = frozenset({None, "populated", "loaded_zero", "out_of_cycle_official_total"})

# PersonMoneyHeadlineState arms in web/src/lib/server/api/entity-detail.ts. Only
# "loaded" may publish a figure; every other arm is a statement about missing
# evidence and must publish none.
PERSON_HEADLINE_KINDS_WITHOUT_FIGURES = frozenset(
    {"not_loaded", "no_linked_candidate", "missing_summary", "temporarily_unavailable"}
)

# devalue's flattened-array sentinels, from the format SvelteKit serves at
# /__data.json. Negative indices are values, not references.
DEVALUE_UNDEFINED = -1
DEVALUE_HOLE = -2
DEVALUE_NAN = -3
DEVALUE_POSITIVE_INFINITY = -4
DEVALUE_NEGATIVE_INFINITY = -5
DEVALUE_NEGATIVE_ZERO = -6


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
    # Optional for the same reason as the outside-spending fields below: the
    # export ships ``null`` (empty CSV cell) when no Schedule A was loaded for
    # the cycle. Unknown is not zero, and the probe must be able to read the
    # difference rather than coerce one into the other.
    total_raised: Optional[Decimal] = None
    # The row's own statement about whether that total was measured. Present
    # only when the state is not ``populated`` (public_money_totals attaches it
    # solely when it carries news), so ``None`` here means "populated".
    fundraising_coverage: Optional[dict[str, Any]] = None
    # Optional because the export leaves these cells empty when no Schedule E
    # was loaded for the cycle. An empty cell is "unknown", not "$0", and the
    # probe must be able to parse it rather than crash the whole assertion set.
    ie_support_total: Optional[Decimal] = None
    ie_oppose_total: Optional[Decimal] = None

    @field_validator("total_raised", "ie_support_total", "ie_oppose_total", mode="before")
    @classmethod
    def _empty_csv_cell_is_unknown(cls, value: object) -> object:
        return None if value == "" else value

    @property
    def _fundraising_activity_state(self) -> Optional[str]:
        return (self.fundraising_coverage or {}).get("activity_state")

    @property
    def publishes_unmeasured_total(self) -> bool:
        """True when this row prints a figure its own coverage says is unknown.

        The export ships the coverage block and the money field side by side, so
        a ``not_loaded`` state next to a ``total_raised`` is the payload
        contradicting itself in a single row. ``has_fec_money is False`` rows
        are excluded: those carry no coverage block and the documented
        discriminator for them is ``has_fec_money``, which clients already read.
        """
        return self.has_fec_money and self._fundraising_activity_state == "not_loaded" and self.total_raised is not None

    @property
    def withholds_measured_total(self) -> bool:
        """True when this row hides a figure its own coverage says was measured.

        The inverse defect, and the one a repair overshoots into: blanking every
        zero would hide the candidates who really did raise nothing, which is
        the same false statement pointing the other way. ``populated`` (the
        state carried by an absent coverage block), ``loaded_zero`` and
        ``out_of_cycle_official_total`` all assert that filings WERE read, so
        each of them owes the reader the number that was read.
        """
        return (
            self.has_fec_money
            and self._fundraising_activity_state in _MEASURED_FUNDRAISING_ACTIVITY_STATES
            and self.total_raised is None
        )


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
        STATUS_PASS
        if (
            SEATED_FEDERAL_OFFICIALS_MIN <= numerator <= SEATED_FEDERAL_OFFICIALS_MAX
            and SEATED_FEDERAL_OFFICIALS_MIN <= denominator <= SEATED_FEDERAL_OFFICIALS_MAX
        )
        else STATUS_FAIL
    )
    diagnostic = f"{numerator}/{denominator} public export rows have FEC money"
    if status == STATUS_FAIL:
        diagnostic = (
            f"{diagnostic}; expected numerator and denominator within "
            f"[{SEATED_FEDERAL_OFFICIALS_MIN}, {SEATED_FEDERAL_OFFICIALS_MAX}]"
        )
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
    # The specimen is the release target's live high-raiser. An unknown there is
    # a defect, never a pass: the floor may only get harder to meet, so a null
    # reaches a FAIL verdict rather than being skipped or raising a TypeError
    # that would take the rest of the assertion set down with it.
    passed = (
        specimen.total_raised is not None
        and specimen.total_raised >= targets.finance_visual_minimum_total_raised
        and specimen.total_raised > Decimal("0")
    )
    observed = "unknown" if specimen.total_raised is None else str(specimen.total_raised)
    return PublicMoneyAssertion(
        name="specimen_total_raised",
        status=STATUS_PASS if passed else STATUS_FAIL,
        numerator=1 if passed else 0,
        denominator=1,
        diagnostic=(
            f"{targets.finance_visual_person_name} total_raised={observed} "
            f"minimum={targets.finance_visual_minimum_total_raised}"
        ),
    )


def _export_money_honesty_assertion(rows: list[FederalExportMoneyRow]) -> PublicMoneyAssertion:
    """Assert every export row's fundraising figure agrees with its own coverage.

    Both directions are defects and both are counted here.

    A row that PRINTS a total while its coverage says ``not_loaded`` states two
    contradictory claims in one object -- the original ``civibus-9nu`` shape,
    measured at 74 of 539 seated officials.

    A row that WITHHOLDS a total while its coverage says the filings were read
    is the same false statement inverted: it hides a zero the product actually
    established. A repair that blanks every zero to clear the first offence
    lands squarely in the second, so the guard has to see both.

    Not promoted to fatal: the first direction is a pre-existing production
    defect, and the probe's job here is to make it visible and measurable, not
    to block a deploy that would not make it worse.
    """
    denominator = len(rows)
    if denominator == 0:
        return PublicMoneyAssertion(
            name="export_money_matches_its_own_coverage",
            status=STATUS_VACUOUS,
            numerator=0,
            denominator=0,
            diagnostic="0/0 public export rows available; cannot assert money-vs-coverage agreement",
        )
    publishing_offenders = [row for row in rows if row.publishes_unmeasured_total]
    withholding_offenders = [row for row in rows if row.withholds_measured_total]
    offender_count = len(publishing_offenders) + len(withholding_offenders)
    numerator = denominator - offender_count
    diagnostic = f"{numerator}/{denominator} public export rows publish money consistent with their coverage"
    if publishing_offenders:
        named = ", ".join(row.person_name for row in publishing_offenders[:3])
        diagnostic = (
            f"{diagnostic}; {len(publishing_offenders)} publish a total while coverage says not_loaded (e.g. {named})"
        )
    if withholding_offenders:
        named = ", ".join(row.person_name for row in withholding_offenders[:3])
        diagnostic = (
            f"{diagnostic}; {len(withholding_offenders)} withhold a measured total "
            f"their coverage says was loaded (e.g. {named})"
        )
    return PublicMoneyAssertion(
        name="export_money_matches_its_own_coverage",
        status=STATUS_PASS if offender_count == 0 else STATUS_FAIL,
        numerator=numerator,
        denominator=denominator,
        diagnostic=diagnostic,
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
    # An unknown value is not a nonzero value: it does not count toward the
    # floor. The floor itself is unchanged — MINIMUM_NONEMPTY_ROWS still has to
    # be met by rows carrying real money — so nullability cannot weaken this
    # assertion, only make it harder to satisfy.
    numerator = sum(1 for row in rows if (getattr(row, field_name) or Decimal("0")) > Decimal("0"))
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
            _export_money_honesty_assertion(export_rows),
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


class SvelteKitPayloadError(ValueError):
    """A ``/__data.json`` body was not the shape SvelteKit serves."""


def _decode_devalue(values: list[Any], resolve_promise: Callable[[Any], Any]) -> Any:
    """Rehydrate one devalue-flattened array into plain Python data.

    devalue writes a value graph as a flat array: element 0 is the root, and
    every integer inside it is an index back into that same array, which is how
    the payload shares (and can cycle) structure. Decoding it is the only way to
    read what the server actually handed the page. That matters here because the
    probe's whole job is to compare the *served* coverage state against the
    *rendered* figure; reading only one of the two proves nothing.
    """
    hydrated: dict[int, Any] = {}

    def hydrate(reference: Any) -> Any:
        if not isinstance(reference, int) or isinstance(reference, bool):
            raise SvelteKitPayloadError("devalue reference must be an integer")
        # Negative sentinels encode values that have no slot in the array.
        if reference in (DEVALUE_UNDEFINED, DEVALUE_HOLE):
            return None
        if reference == DEVALUE_NEGATIVE_ZERO:
            return 0
        if reference in (DEVALUE_NAN, DEVALUE_POSITIVE_INFINITY, DEVALUE_NEGATIVE_INFINITY):
            # Money payloads are decimal strings. A non-finite number here means
            # the payload is not what this probe thinks it is, so fail loudly
            # rather than decode something else and judge it.
            raise SvelteKitPayloadError("non-finite devalue value in a money payload")
        if reference < 0 or reference >= len(values):
            raise SvelteKitPayloadError(f"devalue reference {reference} out of range")
        if reference in hydrated:
            return hydrated[reference]

        raw = values[reference]
        if raw is None or isinstance(raw, (str, bool, int, float)):
            hydrated[reference] = raw
            return raw
        if isinstance(raw, list):
            if raw and isinstance(raw[0], str):
                return _hydrate_tagged(reference, raw, hydrate, hydrated, resolve_promise)
            container: list[Any] = []
            # Registered before its children so a self-referential payload
            # terminates instead of recursing forever.
            hydrated[reference] = container
            container.extend(hydrate(child) for child in raw)
            return container
        if isinstance(raw, dict):
            mapping: dict[str, Any] = {}
            hydrated[reference] = mapping
            for key, child in raw.items():
                mapping[key] = hydrate(child)
            return mapping
        raise SvelteKitPayloadError(f"unsupported devalue node type {type(raw).__name__}")

    if not isinstance(values, list) or not values:
        raise SvelteKitPayloadError("devalue payload must be a non-empty array")
    return hydrate(0)


def _hydrate_tagged(
    reference: int,
    raw: list[Any],
    hydrate: Callable[[Any], Any],
    hydrated: dict[int, Any],
    resolve_promise: Callable[[Any], Any],
) -> Any:
    """Rehydrate one devalue type-tagged node (``["Date", ...]`` and friends)."""
    tag = raw[0]
    if tag == "Promise":
        # SvelteKit streams a deferred load value as this placeholder plus a
        # later `chunk` line. Candidate-page money summaries arrive exactly this
        # way, so a probe that stopped at the first line would see no money at
        # all and would report a clean bill of health it never checked.
        # raw[1] is a reference whose value is the chunk id, not the id itself.
        value = resolve_promise(hydrate(raw[1]))
    elif tag == "Date":
        # Kept as the ISO string: the probe compares and prints dates, never
        # does arithmetic on them.
        value = raw[1]
    elif tag == "Set":
        value = [hydrate(child) for child in raw[1:]]
    elif tag == "Map":
        value = {hydrate(raw[index]): hydrate(raw[index + 1]) for index in range(1, len(raw) - 1, 2)}
    elif tag == "BigInt":
        value = int(raw[1])
    elif tag == "Object":
        value = raw[1]
    else:
        raise SvelteKitPayloadError(f"unsupported devalue tag {tag!r}")
    hydrated[reference] = value
    return value


def parse_sveltekit_data(body: str) -> dict[str, Any]:
    """Decode a SvelteKit ``/__data.json`` response into one merged data dict.

    The endpoint is newline-delimited JSON: the first line carries the route's
    server-resolved data and each later ``chunk`` line resolves one streamed
    promise. Nodes are merged in order, which is how SvelteKit itself layers
    layout data under page data.
    """
    lines = [line for line in body.splitlines() if line.strip()]
    if not lines:
        raise SvelteKitPayloadError("empty /__data.json body")

    root_nodes: Optional[list[Any]] = None
    chunks: dict[Any, list[Any]] = {}
    for line in lines:
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError as error:
            raise SvelteKitPayloadError("malformed /__data.json line") from error
        if not isinstance(parsed, dict):
            raise SvelteKitPayloadError("/__data.json line must be a JSON object")
        if parsed.get("type") == "data":
            root_nodes = parsed.get("nodes")
        elif parsed.get("type") == "chunk":
            chunks[parsed.get("id")] = parsed.get("data")

    if not isinstance(root_nodes, list):
        raise SvelteKitPayloadError("/__data.json carried no data nodes")

    def resolve_promise(chunk_id: Any) -> Any:
        # A referenced chunk that never arrived means a truncated stream. Fail
        # closed: an absent money summary must not read as an absent defect.
        if chunk_id not in chunks:
            raise SvelteKitPayloadError(f"streamed chunk {chunk_id!r} missing from /__data.json")
        return _decode_devalue(chunks[chunk_id], resolve_promise)

    merged: dict[str, Any] = {}
    for node in root_nodes:
        if not isinstance(node, dict) or node.get("type") != "data":
            continue
        decoded = _decode_devalue(node.get("data"), resolve_promise)
        if isinstance(decoded, dict):
            merged.update(decoded)
    return merged


class MoneyGlanceExtractor(HTMLParser):
    """Capture the text and test ids of the person page's money-at-a-glance panel.

    Scoped to that one ``<section>`` on purpose. The rest of a person page
    legitimately carries dollar figures (itemized transactions, top donors), and
    a whole-page currency search would flag those as defects.
    """

    def __init__(self) -> None:
        super().__init__()
        self.present = False
        self.text_parts: list[str] = []
        self.test_ids: set[str] = set()
        self._depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        attributes = dict(attrs)
        if self._depth == 0:
            if tag == "section" and MONEY_GLANCE_CLASS in (attributes.get("class") or ""):
                self.present = True
                self._depth = 1
                test_id = attributes.get("data-testid")
                if test_id:
                    self.test_ids.add(test_id)
            return
        # Inside the panel: track nesting so the panel ends at its own close tag.
        if tag == "section":
            self._depth += 1
        test_id = attributes.get("data-testid")
        if test_id:
            self.test_ids.add(test_id)

    def handle_endtag(self, tag: str) -> None:
        if self._depth > 0 and tag == "section":
            self._depth -= 1

    def handle_data(self, data: str) -> None:
        if self._depth > 0:
            self.text_parts.append(data)

    @property
    def text(self) -> str:
        return " ".join(self.text_parts)


class IndexedCandidateObservation(BaseModel):
    """One sampled candidate page, its served coverage, and its rendered money."""

    candidate_path: str
    person_path: Optional[str] = None
    fundraising_activity_state: Optional[str] = None
    # The selected-cycle total the server served, and the prior-cycle total it
    # offers instead when the selected cycle is empty. Recorded because
    # "activity_state=out_of_cycle_official_total" alone does not say whether a
    # real campaign is hiding behind the selected cycle's zero.
    fundraising_total_raised: Optional[str] = None
    out_of_cycle_total_raised: Optional[str] = None
    outside_spending_activity_state: Optional[str] = None
    person_headline_kind: Optional[str] = None
    person_aggregate_activity_state: Optional[str] = None
    money_glance_present: bool = False
    money_glance_currency_figures: int = 0
    money_glance_not_loaded_marker: bool = False
    error: Optional[str] = None


def _money_render_verdict(observation: IndexedCandidateObservation) -> tuple[bool, str]:
    """Is the rendered person money panel true to the coverage the server served?

    This is the whole feature, so each branch states why a zero is or is not
    trustworthy there.
    """
    if observation.error is not None:
        # Fail closed. An unreachable or undecodable page is not evidence of
        # honesty, and counting it as honest is how a probe drifts to vacuous.
        return False, observation.error

    kind = observation.person_headline_kind
    aggregate = observation.person_aggregate_activity_state
    if kind is None:
        return False, "person page served no money headline"

    # Derivation check, ahead of the render check: the headline arm is computed
    # from the aggregate coverage state, and "not_loaded coverage rendered as
    # the loaded arm" is precisely the defect civibus-c4t described.
    if aggregate == "not_loaded" and kind != "not_loaded":
        return False, f"not_loaded aggregate served as headline kind {kind!r}"

    if kind == "not_loaded":
        # The served totals are a sum over an empty set. Publishing any figure
        # for them asserts a measurement nobody took, so the panel must carry
        # the marker and no currency at all.
        if observation.money_glance_currency_figures:
            return False, f"not_loaded panel rendered {observation.money_glance_currency_figures} currency figures"
        if not observation.money_glance_not_loaded_marker:
            return False, "not_loaded panel rendered without its not-loaded marker"
        return True, "not_loaded rendered as unknown"

    if kind == "loaded":
        # The aggregate is populated or all-loaded_zero, so the zero (or
        # nonzero) was measured. A figure here is a true statement, and
        # $0.00 among them is correct rather than a defect. Suppressing it
        # would be the same dishonesty pointing the other way, so an empty
        # panel fails this branch.
        if not observation.money_glance_present:
            return False, "loaded headline rendered no money panel"
        if not observation.money_glance_currency_figures:
            return False, "loaded headline rendered no currency figure"
        return True, "measured totals rendered as figures"

    if kind in PERSON_HEADLINE_KINDS_WITHOUT_FIGURES:
        # no_linked_candidate / missing_summary / temporarily_unavailable are
        # all statements about absent evidence; none may carry a figure.
        if observation.money_glance_currency_figures:
            return False, f"{kind} panel rendered {observation.money_glance_currency_figures} currency figures"
        return True, f"{kind} rendered without figures"

    return False, f"unrecognised person money headline kind {kind!r}"


def _sitemap_locations(base_url: str, path: str, fixture_dir: Optional[Path]) -> list[str]:
    response = _fetch_http(base_url, path, fixture_dir)
    if response.status_code != HTTP_OK_STATUS or response.error is not None:
        return []
    return SITEMAP_LOC_PATTERN.findall(response.body)


def sample_indexed_candidate_paths(
    base_url: str,
    *,
    sample_size: int,
    seed: int,
    fixture_dir: Optional[Path] = None,
) -> list[str]:
    """Draw a deterministic random sample of live indexed candidate page paths.

    Sampling the sitemap rather than the database is the point: the sitemap is
    what search engines crawl, so it is the exact population whose rendered
    claims are publicly readable.
    """
    shard_urls = [
        location
        for location in _sitemap_locations(base_url, SITEMAP_INDEX_PATH, fixture_dir)
        if urlsplit(location).path.rsplit("/", 1)[-1].startswith(CANDIDATE_SITEMAP_BASENAME_PREFIX)
    ]
    candidate_paths: list[str] = []
    for shard_url in shard_urls:
        shard_path = urlsplit(shard_url).path
        candidate_paths.extend(
            urlsplit(location).path for location in _sitemap_locations(base_url, shard_path, fixture_dir)
        )

    # Sorted before sampling so the seed alone fixes the draw; sitemap order is
    # a server detail that must not silently change which pages get judged.
    unique_paths = sorted(set(candidate_paths))
    if len(unique_paths) <= sample_size:
        return unique_paths
    return sorted(random.Random(seed).sample(unique_paths, sample_size))


def _coverage_activity_state(payload: Any) -> Optional[str]:
    if not isinstance(payload, dict):
        return None
    coverage = payload.get("coverage")
    if not isinstance(coverage, dict):
        return None
    state = coverage.get("activity_state")
    return state if isinstance(state, str) else None


def observe_indexed_candidate(
    base_url: str,
    candidate_path: str,
    fixture_dir: Optional[Path] = None,
) -> IndexedCandidateObservation:
    """Read one candidate page's served coverage and its person page's rendering."""
    candidate_data = _fetch_http(base_url, f"{candidate_path}/__data.json", fixture_dir)
    if candidate_data.status_code != HTTP_OK_STATUS or candidate_data.error is not None:
        return IndexedCandidateObservation(
            candidate_path=candidate_path,
            error=f"candidate data returned HTTP {candidate_data.status_code}",
        )
    try:
        candidate_payload = parse_sveltekit_data(candidate_data.body)
    except SvelteKitPayloadError as error:
        return IndexedCandidateObservation(candidate_path=candidate_path, error=f"candidate data undecodable: {error}")

    summary = candidate_payload.get("summary")
    out_of_cycle = summary.get("out_of_cycle_official_total") if isinstance(summary, dict) else None
    observation = IndexedCandidateObservation(
        candidate_path=candidate_path,
        fundraising_activity_state=_coverage_activity_state(summary),
        fundraising_total_raised=summary.get("total_raised") if isinstance(summary, dict) else None,
        out_of_cycle_total_raised=out_of_cycle.get("total_raised") if isinstance(out_of_cycle, dict) else None,
        outside_spending_activity_state=_coverage_activity_state(candidate_payload.get("ieSummary")),
    )

    detail = candidate_payload.get("detail")
    person_id = detail.get("person_id") if isinstance(detail, dict) else None
    if not isinstance(person_id, str) or not person_id:
        # No canonical person means no person page to judge. Not a defect in
        # itself, but the render half cannot run, so say so instead of passing.
        observation.error = "candidate page carries no canonical person id"
        return observation
    observation.person_path = f"/person/{person_id}"

    person_data = _fetch_http(base_url, f"{observation.person_path}/__data.json", fixture_dir)
    if person_data.status_code != HTTP_OK_STATUS or person_data.error is not None:
        observation.error = f"person data returned HTTP {person_data.status_code}"
        return observation
    try:
        person_payload = parse_sveltekit_data(person_data.body)
    except SvelteKitPayloadError as error:
        observation.error = f"person data undecodable: {error}"
        return observation

    headline = person_payload.get("personMoneyHeadline")
    if isinstance(headline, dict):
        kind = headline.get("kind")
        observation.person_headline_kind = kind if isinstance(kind, str) else None
        observation.person_aggregate_activity_state = _coverage_activity_state(headline.get("summary"))

    person_html = _fetch_http(base_url, observation.person_path, fixture_dir)
    if person_html.status_code != HTTP_OK_STATUS or person_html.error is not None:
        observation.error = f"person page returned HTTP {person_html.status_code}"
        return observation

    extractor = MoneyGlanceExtractor()
    extractor.feed(person_html.body)
    extractor.close()
    observation.money_glance_present = extractor.present
    observation.money_glance_currency_figures = len(RENDERED_CURRENCY_PATTERN.findall(extractor.text))
    observation.money_glance_not_loaded_marker = PERSON_MONEY_NOT_LOADED_TEST_ID in extractor.test_ids
    return observation


def _activity_state_distribution(states: list[Optional[str]]) -> str:
    counted: dict[str, int] = {}
    for state in states:
        counted[state or "absent"] = counted.get(state or "absent", 0) + 1
    return " ".join(f"{name}={count}" for name, count in sorted(counted.items()))


def _known_activity_state_assertion(
    name: str,
    states: list[Optional[str]],
    known_states: frozenset[str],
) -> PublicMoneyAssertion:
    denominator = len(states)
    numerator = sum(1 for state in states if state in known_states)
    distribution = _activity_state_distribution(states)
    if denominator == 0:
        return PublicMoneyAssertion(
            name=name,
            status=STATUS_VACUOUS,
            numerator=0,
            denominator=0,
            diagnostic=f"0/0 sampled pages; cannot assert {name}",
        )
    return PublicMoneyAssertion(
        name=name,
        status=STATUS_PASS if numerator == denominator else STATUS_FAIL,
        numerator=numerator,
        denominator=denominator,
        diagnostic=f"{numerator}/{denominator} sampled pages carry a known coverage state; distribution {distribution}",
    )


def evaluate_indexed_candidate_sample(
    base_url: str,
    *,
    sample_size: int,
    seed: int,
    fixture_dir: Optional[Path] = None,
    max_workers: int = 6,
) -> tuple[list[PublicMoneyAssertion], list[IndexedCandidateObservation]]:
    """Sample live indexed candidate pages and judge their money honesty."""
    paths = sample_indexed_candidate_paths(base_url, sample_size=sample_size, seed=seed, fixture_dir=fixture_dir)
    if not paths:
        return (
            [
                PublicMoneyAssertion(
                    name="indexed_candidate_sample",
                    status=STATUS_VACUOUS,
                    numerator=0,
                    denominator=sample_size,
                    diagnostic="candidate sitemap yielded no indexed candidate pages",
                )
            ],
            [],
        )

    def observe(path: str) -> IndexedCandidateObservation:
        return observe_indexed_candidate(base_url, path, fixture_dir)

    # ThreadPoolExecutor.map preserves input order, so the report stays
    # deterministic for a given seed even though the fetches interleave.
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        observations = list(executor.map(observe, paths))

    verdicts = [_money_render_verdict(observation) for observation in observations]
    honest = sum(1 for is_honest, _ in verdicts if is_honest)
    first_defect = next((reason for is_honest, reason in verdicts if not is_honest), "none")

    assertions = [
        PublicMoneyAssertion(
            name="indexed_candidate_sample",
            # A sample that silently shrank is how the 58% figure went stale.
            # Getting fewer pages than asked for is a probe failure, not a
            # smaller answer.
            status=STATUS_PASS if len(observations) == sample_size else STATUS_FAIL,
            numerator=len(observations),
            denominator=sample_size,
            diagnostic=f"{len(observations)}/{sample_size} indexed candidate pages sampled at seed {seed}",
        ),
        _known_activity_state_assertion(
            "candidate_money_activity_states_known",
            [observation.fundraising_activity_state for observation in observations],
            KNOWN_FUNDRAISING_ACTIVITY_STATES,
        ),
        _known_activity_state_assertion(
            "outside_spending_activity_states_known",
            [observation.outside_spending_activity_state for observation in observations],
            KNOWN_IE_ACTIVITY_STATES,
        ),
        PublicMoneyAssertion(
            name="person_money_render_honesty",
            status=STATUS_PASS if honest == len(observations) else STATUS_FAIL,
            numerator=honest,
            denominator=len(observations),
            diagnostic=(
                f"{honest}/{len(observations)} sampled person pages render money consistently "
                f"with their served coverage; first defect: {first_defect}"
            ),
        ),
    ]
    return assertions, observations


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--fixture-dir", default="")
    parser.add_argument(
        "--sample-indexed-candidates",
        type=int,
        default=0,
        help=(
            "Sample this many live indexed candidate pages and assert their rendered money "
            "matches their served coverage. Off by default: this is a network sample, not a "
            "deploy gate."
        ),
    )
    parser.add_argument("--sample-seed", type=int, default=DEFAULT_SAMPLE_SEED)
    parser.add_argument(
        "--sample-observations-path",
        default="",
        help="Optional path to write the per-page sample observations as JSON.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        base_url = _normalized_base_url(args.base_url)
    except ValueError as error:
        print(f"money_value_probe_invalid_base_url {error}", file=sys.stderr)
        return 3
    fixture_dir = Path(args.fixture_dir) if args.fixture_dir else None
    try:
        report = evaluate_public_money_value(base_url, fixture_dir)
        # Opt-in only. The deploy lane never passes --sample-indexed-candidates,
        # so the gating assertion set stays exactly what it was.
        if args.sample_indexed_candidates > 0:
            sample_assertions, observations = evaluate_indexed_candidate_sample(
                base_url,
                sample_size=args.sample_indexed_candidates,
                seed=args.sample_seed,
                fixture_dir=fixture_dir,
            )
            report = PublicMoneyProbeReport(assertions=[*report.assertions, *sample_assertions])
            if args.sample_observations_path:
                Path(args.sample_observations_path).write_text(
                    json.dumps([observation.model_dump() for observation in observations], indent=2),
                    encoding="utf-8",
                )
    except Exception as error:  # noqa: BLE001 - probe must fail closed on unexpected runtime errors
        print(f"money_value_probe_error {error.__class__.__name__}", file=sys.stderr)
        return 3
    for assertion in report.assertions:
        print(assertion.format_line())
    if any(
        assertion.name in PROMOTED_FATAL_ASSERTIONS and assertion.status in {STATUS_FAIL, STATUS_VACUOUS}
        for assertion in report.assertions
    ):
        return 2
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
