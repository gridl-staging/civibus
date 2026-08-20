"""Known-answer tests for the DB-free public money-value probe."""

from __future__ import annotations

import importlib.util
import http.client
import json
import subprocess
from pathlib import Path
from urllib.error import HTTPError

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
PROBE_PATH = REPO_ROOT / "infra/scripts/public_money_value_probe.py"
RELEASE_TARGETS_PATH = REPO_ROOT / "web/tests/smoke/production_release_targets.json"

# Stage 1 owns the post-repair `fec_money_coverage` diagnostic wording so Stage 2
# implements to exactly this string and the probe + parity suites cannot drift to
# different wordings. Post-repair rule (Stage 2 wires it to the single denominator
# owner in core/people/federal_officeholders.py): PASS iff BOTH numerator and denominator fall
# inside the canonical federal-officeholder range [535, 543]; otherwise FAIL; 0/0
# stays VACUOUS. The sub-floor / out-of-range FAIL case must name the [535, 543]
# bounds. Chosen wording:
#   PASS diagnostic: "<n>/<d> public export rows have FEC money"
#   FAIL diagnostic: "<n>/<d> public export rows have FEC money; "
#                    "expected numerator and denominator within [535, 543]"
COVERAGE_BOUNDS_DIAGNOSTIC_SUFFIX = "expected numerator and denominator within [535, 543]"


def _probe_module():
    spec = importlib.util.spec_from_file_location("public_money_value_probe", PROBE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _route_slug(path: str) -> str:
    return path.encode("utf-8").hex()


def _release_targets() -> dict[str, object]:
    return json.loads(RELEASE_TARGETS_PATH.read_text(encoding="utf-8"))


def _money_row(
    index: int,
    *,
    person_id: str | None = None,
    person_name: str | None = None,
    has_fec_money: bool = True,
    total_raised: str = "100.00",
    ie_support_total: str = "0.00",
    ie_oppose_total: str = "0.00",
) -> dict[str, object]:
    row_person_id = person_id or f"00000000-0000-4000-8000-{index:012d}"
    return {
        "person_id": row_person_id,
        "person_name": person_name or f"Member {index}",
        "has_fec_money": has_fec_money,
        "candidate_id": f"10000000-0000-4000-8000-{index:012d}" if has_fec_money else None,
        "total_raised": total_raised,
        "total_spent": "50.00",
        "net": "50.00",
        "cash_on_hand": "25.00",
        "summary_source": "fec_candidate_summary" if has_fec_money else None,
        "ie_support_total": ie_support_total,
        "ie_oppose_total": ie_oppose_total,
        "ie_support_count": 1 if ie_support_total != "0.00" else 0,
        "ie_oppose_count": 1 if ie_oppose_total != "0.00" else 0,
        "sources": [{"record_url": "https://www.fec.gov/data/candidate/example/"}],
    }


def _export_rows(*, denominator: int, fec_rows: int) -> list[dict[str, object]]:
    targets = _release_targets()
    rows = [
        _money_row(
            0,
            person_id=str(targets["finance_visual_person_id"]),
            person_name=str(targets["finance_visual_person_name"]),
            total_raised=str(targets["finance_visual_minimum_total_raised"]),
            ie_support_total="12.00",
            ie_oppose_total="8.00",
        )
    ]
    for index in range(1, denominator):
        rows.append(_money_row(index, has_fec_money=index < fec_rows))
    return rows[:denominator]


def _write_helper_fixture(
    fixture_dir: Path,
    *,
    export_payload: object,
    candidates_body: str | None = None,
    committees_body: str | None = None,
    donor_body: str | None = None,
    statuses: dict[str, int] | None = None,
) -> None:
    targets = _release_targets()
    donor_query = targets["finance_visual_donor_query"]
    route_bodies = {
        "/api/public/v1/federal/export.json": json.dumps(export_payload),
        "/candidates": candidates_body or '<li data-testid="candidate-result-row">Candidate</li>',
        "/committees": committees_body or '<li data-testid="committee-result-row">Committee</li>',
        f"/donors?q={donor_query}&by=name": donor_body or '<tr data-testid="donor-result-row"><td>Donor</td></tr>',
    }
    fixture_dir.mkdir()
    body_dir = fixture_dir / "helper_http_bodies"
    body_dir.mkdir()
    for route, body in route_bodies.items():
        (body_dir / f"{_route_slug(route)}.txt").write_text(body, encoding="utf-8")
    (fixture_dir / "helper_http_statuses.tsv").write_text(
        "".join(f"{route}\t{status}\n" for route, status in (statuses or {}).items()),
        encoding="utf-8",
    )


def _run_probe(fixture_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "python3",
            str(PROBE_PATH),
            "--base-url",
            "https://fixture.example",
            "--fixture-dir",
            str(fixture_dir),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_full_fec_money_coverage_reports_pass_with_denominator(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "full-coverage"
    # 537 and 539 both sit inside the canonical [535, 543] range, so the
    # post-repair rule must report PASS even though numerator != denominator.
    _write_helper_fixture(fixture_dir, export_payload=_export_rows(denominator=539, fec_rows=537))

    result = _run_probe(fixture_dir)

    assert result.returncode == 0, result.stderr
    assert (
        "money_value_assertion fec_money_coverage PASS numerator=537 denominator=539 "
        "diagnostic=537/539 public export rows have FEC money"
    ) in result.stdout


def test_partial_fec_money_coverage_reports_fail_with_denominator(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "partial-coverage"
    # 534 is below the [535, 543] floor while 539 is in range: sub-floor numerator
    # must FAIL and, once fec_money_coverage joins PROMOTED_FATAL_ASSERTIONS in
    # Stage 2, must leave through the promoted-fatal exit path with code 2.
    _write_helper_fixture(fixture_dir, export_payload=_export_rows(denominator=539, fec_rows=534))

    result = _run_probe(fixture_dir)

    assert result.returncode == 2
    assert (
        "money_value_assertion fec_money_coverage FAIL numerator=534 denominator=539 "
        f"diagnostic=534/539 public export rows have FEC money; {COVERAGE_BOUNDS_DIAGNOSTIC_SUFFIX}"
    ) in result.stdout


def test_out_of_range_denominator_fails_even_at_full_coverage(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "out-of-range-denominator"
    # 544/544 is full coverage but the denominator is above the [535, 543]
    # ceiling, so the rule must FAIL (not PASS) and promote to fatal exit 2.
    _write_helper_fixture(fixture_dir, export_payload=_export_rows(denominator=544, fec_rows=544))

    result = _run_probe(fixture_dir)

    assert result.returncode == 2
    assert (
        "money_value_assertion fec_money_coverage FAIL numerator=544 denominator=544 "
        f"diagnostic=544/544 public export rows have FEC money; {COVERAGE_BOUNDS_DIAGNOSTIC_SUFFIX}"
    ) in result.stdout
    assert "money_value_assertion fec_money_coverage PASS" not in result.stdout


def test_promoted_http_failure_exits_two(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "promoted-http-failure"
    _write_helper_fixture(
        fixture_dir,
        export_payload=_export_rows(denominator=540, fec_rows=540),
        statuses={"/candidates": 503},
    )

    result = _run_probe(fixture_dir)

    assert result.returncode == 2
    assert "money_value_assertion candidates_http FAIL numerator=503 denominator=200" in result.stdout


def test_zero_export_rows_reports_vacuous_not_pass(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "zero-export"
    _write_helper_fixture(fixture_dir, export_payload=[])

    result = _run_probe(fixture_dir)

    assert result.returncode == 2
    assert (
        "money_value_assertion fec_money_coverage VACUOUS numerator=0 denominator=0 "
        "diagnostic=0/0 public export rows available; cannot assert FEC money coverage"
    ) in result.stdout
    assert "money_value_assertion specimen_total_raised VACUOUS" in result.stdout
    assert "PASS numerator=0 denominator=0" not in result.stdout


def test_malformed_export_payload_reports_fail(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "malformed-export"
    _write_helper_fixture(fixture_dir, export_payload={"items": []})

    result = _run_probe(fixture_dir)

    assert result.returncode == 2
    assert (
        "money_value_assertion export_payload FAIL numerator=0 denominator=1 "
        "diagnostic=/api/public/v1/federal/export.json JSON payload must be a list"
    ) in result.stdout
    assert "money_value_probe_error" not in result.stderr


def test_fixture_backed_list_and_search_probes_report_non_empty_rows(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "list-search"
    donor_query = _release_targets()["finance_visual_donor_query"]
    _write_helper_fixture(
        fixture_dir,
        export_payload=_export_rows(denominator=540, fec_rows=540),
        candidates_body=(
            '<li data-testid="candidate-result-row">First</li><li data-testid="candidate-result-row">Second</li>'
        ),
        committees_body='<li data-testid="committee-result-row">Committee</li>',
        donor_body='<tr data-testid="donor-result-row"><td>Williams</td></tr>',
    )

    result = _run_probe(fixture_dir)

    assert result.returncode == 0, result.stderr
    assert (
        "money_value_assertion federal_export_http PASS numerator=200 denominator=200 "
        "diagnostic=/api/public/v1/federal/export.json returned HTTP 200"
    ) in result.stdout
    assert (
        "money_value_assertion candidates_rows PASS numerator=2 denominator=2 "
        "diagnostic=/candidates rendered 2 result rows"
    ) in result.stdout
    assert (
        "money_value_assertion committees_rows PASS numerator=1 denominator=1 "
        "diagnostic=/committees rendered 1 result rows"
    ) in result.stdout
    assert (
        "money_value_assertion donor_search_rows PASS numerator=1 denominator=1 "
        f"diagnostic=/donors?q={donor_query}&by=name rendered 1 result rows"
    ) in result.stdout


def test_live_http_errors_preserve_upstream_status(monkeypatch) -> None:
    probe = _probe_module()

    def raise_http_error(_request, timeout):  # noqa: ANN001 - monkeypatch signature mirrors urllib
        raise HTTPError("https://fixture.example/candidates", 404, "Not Found", hdrs=None, fp=None)

    monkeypatch.setattr(probe, "urlopen", raise_http_error)

    response = probe._fetch_http("https://fixture.example", "/candidates", None)

    assert response.status_code == 404
    assert response.error == "/candidates returned HTTP 404"


@pytest.mark.parametrize(
    ("read_result", "expected_error"),
    [
        (TimeoutError("read timed out"), "TimeoutError"),
        (http.client.IncompleteRead(b"partial body", 10), "IncompleteRead"),
        (OSError("connection reset"), "OSError"),
        (b"\xff", "UnicodeDecodeError"),
    ],
)
def test_response_body_failures_become_structured_route_failures(
    monkeypatch,
    read_result: bytes | Exception,
    expected_error: str,
) -> None:
    probe = _probe_module()

    class FailingResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self) -> bytes:
            if isinstance(read_result, Exception):
                raise read_result
            return read_result

    monkeypatch.setattr(probe, "urlopen", lambda _request, timeout: FailingResponse())

    response = probe._fetch_http("https://fixture.example", "/candidates", None)
    assertion = probe._assert_http_ok("candidates_http", "/candidates", response)

    assert response.status_code == 599
    assert response.error == f"/candidates fetch error: {expected_error}"
    assert assertion.format_line() == (
        "money_value_assertion candidates_http FAIL numerator=599 denominator=200 "
        f"diagnostic=/candidates fetch error: {expected_error}; expected HTTP 200"
    )


def test_response_open_timeout_becomes_structured_route_failure(monkeypatch) -> None:
    probe = _probe_module()

    def raise_timeout(_request, timeout):  # noqa: ANN001 - monkeypatch signature mirrors urllib
        raise TimeoutError("connect timed out")

    monkeypatch.setattr(probe, "urlopen", raise_timeout)

    response = probe._fetch_http("https://fixture.example", "/committees", None)

    assert response.status_code == 599
    assert response.error == "/committees fetch error: TimeoutError"


def test_public_page_with_zero_rendered_rows_reports_fail(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "empty-public-page"
    _write_helper_fixture(
        fixture_dir,
        export_payload=_export_rows(denominator=540, fec_rows=540),
        candidates_body="<html><body>No candidates found.</body></html>",
    )

    result = _run_probe(fixture_dir)

    assert result.returncode == 2
    assert (
        "money_value_assertion candidates_rows FAIL numerator=0 denominator=1 "
        "diagnostic=/candidates rendered 0 result rows"
    ) in result.stdout


# --- Indexed-page coverage sampling -----------------------------------------
#
# Known-answer tests for the sampling lane. Every payload below is hand-built so
# each assertion names a value computed by hand, not a shape. Pure logic and
# fixture I/O only: the sampling lane makes live HTTP requests in production use
# and must never do so from a fast test tier.


def _devalue_person_payload(*, kind: str, aggregate_activity_state: str) -> str:
    """One SvelteKit /__data.json body whose money headline is server-rendered.

    Hand-flattened the way devalue writes it: element 0 is the root and every
    integer is an index back into the same array.
    """
    payload = {
        "type": "data",
        "nodes": [
            None,
            {
                "type": "data",
                "data": [
                    {"personMoneyHeadline": 1},
                    {"kind": 2, "summary": 3},
                    kind,
                    {"coverage": 4},
                    {"activity_state": 5},
                    aggregate_activity_state,
                ],
                "uses": {},
            },
        ],
    }
    return json.dumps(payload)


def _devalue_candidate_payload(
    *,
    person_id: str,
    fundraising_activity_state: str,
    total_raised: str,
    ie_activity_state: str,
) -> str:
    """A candidate /__data.json whose money summaries arrive as streamed chunks.

    This is the real production shape: `summary` and `ieSummary` are deferred
    promises, so their values live on later `chunk` lines rather than the first
    line. A decoder that read only line 0 would see no money at all.
    """
    root = {
        "type": "data",
        "nodes": [
            None,
            {
                "type": "data",
                # index 2 -> ["Promise", 3]; index 3 -> 1, the chunk id.
                "data": [
                    {"detail": 1, "summary": 2, "ieSummary": 4},
                    {"person_id": 6},
                    ["Promise", 3],
                    1,
                    ["Promise", 5],
                    2,
                    person_id,
                ],
                "uses": {},
            },
        ],
    }
    summary_chunk = {
        "type": "chunk",
        "id": 1,
        "data": [
            {"total_raised": 1, "coverage": 2, "out_of_cycle_official_total": 5},
            total_raised,
            {"activity_state": 3},
            fundraising_activity_state,
            "1234.56",
            {"total_raised": 4},
        ],
    }
    ie_chunk = {
        "type": "chunk",
        "id": 2,
        "data": [{"coverage": 1}, {"activity_state": 2}, ie_activity_state],
    }
    return "\n".join(json.dumps(line) for line in (root, summary_chunk, ie_chunk))


def _person_html(*, figures: list[str], not_loaded_marker: bool) -> str:
    """A person page whose money-glance panel holds exactly `figures`.

    The trailing panel outside the money glance is deliberate: it proves the
    extractor is scoped, because a whole-page currency scan would count it.
    """
    marker = f' data-testid="{PROBE_NOT_LOADED_TEST_ID}"' if not_loaded_marker else ""
    rows = "".join(f"<div><dt>Total receipts</dt> <dd>{figure}</dd></div>" for figure in figures)
    return (
        '<main><section class="detail__panel"><h3>Campaign finance</h3>'
        f'<section class="detail__money-glance" aria-label="Money at a glance"{marker}>'
        f"<h4>Money at a glance</h4><dl>{rows}</dl>"
        "</section></section>"
        # Itemized transactions legitimately carry dollars and are NOT a defect.
        '<section class="detail__panel"><dd>$99,999.99</dd></section></main>'
    )


PROBE_NOT_LOADED_TEST_ID = "person-money-not-loaded"


def _observation(module, **overrides):
    defaults = {
        "candidate_path": "/candidate/example",
        "person_path": "/person/00000000-0000-4000-8000-000000000001",
    }
    return module.IndexedCandidateObservation(**{**defaults, **overrides})


def test_streamed_sveltekit_money_payload_decodes_to_its_served_values() -> None:
    module = _probe_module()
    decoded = module.parse_sveltekit_data(
        _devalue_candidate_payload(
            person_id="abc",
            fundraising_activity_state="out_of_cycle_official_total",
            total_raised="0.00",
            ie_activity_state="not_loaded",
        )
    )

    assert decoded["detail"]["person_id"] == "abc"
    # The selected-cycle total is zero while a real prior-cycle total exists.
    # Reading only one of the two is how a probe mistakes an honest label for a
    # fabricated zero, so both must survive decoding.
    assert decoded["summary"]["total_raised"] == "0.00"
    assert decoded["summary"]["coverage"]["activity_state"] == "out_of_cycle_official_total"
    assert decoded["summary"]["out_of_cycle_official_total"]["total_raised"] == "1234.56"
    assert decoded["ieSummary"]["coverage"]["activity_state"] == "not_loaded"


def test_missing_streamed_chunk_fails_closed_instead_of_reading_as_no_money() -> None:
    module = _probe_module()
    truncated = _devalue_candidate_payload(
        person_id="abc",
        fundraising_activity_state="populated",
        total_raised="500.00",
        ie_activity_state="populated",
    ).splitlines()[0]

    # A truncated stream must raise, not decode to an absent summary. Silently
    # returning "no money here" would report a clean bill of health the probe
    # never actually checked.
    with pytest.raises(module.SvelteKitPayloadError):
        module.parse_sveltekit_data(truncated)


def test_money_glance_extractor_counts_only_figures_inside_the_panel() -> None:
    module = _probe_module()
    extractor = module.MoneyGlanceExtractor()
    extractor.feed(_person_html(figures=["$1,200.00", "$0.00"], not_loaded_marker=False))
    extractor.close()

    assert extractor.present is True
    # Exactly the two panel figures; the $99,999.99 in the sibling panel is a
    # legitimate itemized-transaction figure and must not be counted.
    assert len(module.RENDERED_CURRENCY_PATTERN.findall(extractor.text)) == 2
    assert PROBE_NOT_LOADED_TEST_ID not in extractor.test_ids


def test_not_loaded_coverage_rendered_as_a_dollar_figure_is_a_defect() -> None:
    module = _probe_module()
    is_honest, reason = module._money_render_verdict(
        _observation(
            module,
            person_headline_kind="not_loaded",
            person_aggregate_activity_state="not_loaded",
            money_glance_present=True,
            money_glance_currency_figures=2,
            money_glance_not_loaded_marker=True,
        )
    )

    # This is civibus-c4t exactly: a sum over an empty set published as a figure.
    assert is_honest is False
    assert "2 currency figures" in reason


def test_not_loaded_coverage_rendered_with_its_marker_and_no_figure_is_honest() -> None:
    module = _probe_module()
    is_honest, _ = module._money_render_verdict(
        _observation(
            module,
            person_headline_kind="not_loaded",
            person_aggregate_activity_state="not_loaded",
            money_glance_present=True,
            money_glance_currency_figures=0,
            money_glance_not_loaded_marker=True,
        )
    )

    assert is_honest is True


def test_measured_zero_rendered_as_a_figure_stays_honest() -> None:
    module = _probe_module()
    is_honest, _ = module._money_render_verdict(
        _observation(
            module,
            person_headline_kind="loaded",
            person_aggregate_activity_state="loaded_zero",
            money_glance_present=True,
            # "$0.00" is one currency figure, and here it is a measurement.
            money_glance_currency_figures=1,
            money_glance_not_loaded_marker=False,
        )
    )

    # The inverse direction. A probe that flagged every rendered zero would push
    # the product into suppressing facts it actually established.
    assert is_honest is True


def test_loaded_headline_that_renders_no_figure_is_a_defect() -> None:
    module = _probe_module()
    is_honest, reason = module._money_render_verdict(
        _observation(
            module,
            person_headline_kind="loaded",
            person_aggregate_activity_state="populated",
            money_glance_present=True,
            money_glance_currency_figures=0,
        )
    )

    # Over-correction guard: measured coverage that publishes nothing is its own
    # dishonesty, so the probe has to be able to fail in this direction too.
    assert is_honest is False
    assert "no currency figure" in reason


def test_not_loaded_aggregate_served_through_the_loaded_headline_is_a_defect() -> None:
    module = _probe_module()
    is_honest, reason = module._money_render_verdict(
        _observation(
            module,
            person_headline_kind="loaded",
            person_aggregate_activity_state="not_loaded",
            money_glance_present=True,
            money_glance_currency_figures=3,
        )
    )

    # Catches the defect one layer earlier than the render: the headline arm is
    # derived from the aggregate coverage, and this is the derivation civibus-c4t
    # was filed about.
    assert is_honest is False
    assert "not_loaded aggregate" in reason


def test_unreachable_person_page_is_not_counted_honest() -> None:
    module = _probe_module()
    is_honest, reason = module._money_render_verdict(_observation(module, error="person page returned HTTP 503"))

    # Fail closed. An unreadable page is not evidence of honesty, and counting
    # it as honest is how a sampling probe drifts to vacuous.
    assert is_honest is False
    assert reason == "person page returned HTTP 503"


def test_unrecognised_activity_state_fails_the_known_state_assertion() -> None:
    module = _probe_module()
    assertion = module._known_activity_state_assertion(
        "candidate_money_activity_states_known",
        ["populated", "not_loaded", "brand_new_state"],
        module.KNOWN_FUNDRAISING_ACTIVITY_STATES,
    )

    # A state the probe cannot judge must fail the run rather than pass by
    # default; the whole guard rests on knowing what each state claims.
    assert assertion.status == "FAIL"
    assert assertion.numerator == 2
    assert assertion.denominator == 3
    assert "brand_new_state=1" in assertion.diagnostic


def test_fixture_backed_sample_reports_the_measured_coverage_distribution(tmp_path: Path) -> None:
    module = _probe_module()
    fixture_dir = tmp_path / "sample"
    body_dir = fixture_dir / "helper_http_bodies"
    body_dir.mkdir(parents=True)

    honest_person = "00000000-0000-4000-8000-000000000001"
    dishonest_person = "00000000-0000-4000-8000-000000000002"
    routes = {
        "/sitemap.xml": (
            "<sitemapindex>"
            "<sitemap><loc>https://fixture.example/sitemap-candidate-0.xml</loc></sitemap>"
            "<sitemap><loc>https://fixture.example/sitemap-person-0.xml</loc></sitemap>"
            "</sitemapindex>"
        ),
        "/sitemap-candidate-0.xml": (
            "<urlset>"
            "<url><loc>https://fixture.example/candidate/honest</loc></url>"
            "<url><loc>https://fixture.example/candidate/dishonest</loc></url>"
            "</urlset>"
        ),
        "/candidate/honest/__data.json": _devalue_candidate_payload(
            person_id=honest_person,
            fundraising_activity_state="not_loaded",
            total_raised="0.00",
            ie_activity_state="not_loaded",
        ),
        "/candidate/dishonest/__data.json": _devalue_candidate_payload(
            person_id=dishonest_person,
            fundraising_activity_state="populated",
            total_raised="4200.00",
            ie_activity_state="loaded_zero",
        ),
        f"/person/{honest_person}/__data.json": _devalue_person_payload(
            kind="not_loaded", aggregate_activity_state="not_loaded"
        ),
        f"/person/{honest_person}": _person_html(figures=[], not_loaded_marker=True),
        # Served as not_loaded, rendered through the loaded arm with figures:
        # the defect, hand-built so the sample has a known-red member.
        f"/person/{dishonest_person}/__data.json": _devalue_person_payload(
            kind="loaded", aggregate_activity_state="not_loaded"
        ),
        f"/person/{dishonest_person}": _person_html(figures=["$0.00"], not_loaded_marker=False),
    }
    for route, body in routes.items():
        (body_dir / f"{_route_slug(route)}.txt").write_text(body, encoding="utf-8")
    (fixture_dir / "helper_http_statuses.tsv").write_text("", encoding="utf-8")

    assertions, observations = module.evaluate_indexed_candidate_sample(
        "https://fixture.example", sample_size=2, seed=1, fixture_dir=fixture_dir
    )
    by_name = {assertion.name: assertion for assertion in assertions}

    assert by_name["indexed_candidate_sample"].status == "PASS"
    assert by_name["indexed_candidate_sample"].numerator == 2
    # Sorted sample order: /candidate/dishonest then /candidate/honest.
    assert [observation.candidate_path for observation in observations] == [
        "/candidate/dishonest",
        "/candidate/honest",
    ]
    assert observations[1].fundraising_total_raised == "0.00"
    assert observations[0].out_of_cycle_total_raised == "1234.56"
    assert by_name["candidate_money_activity_states_known"].diagnostic.endswith("not_loaded=1 populated=1")
    assert by_name["outside_spending_activity_states_known"].diagnostic.endswith("loaded_zero=1 not_loaded=1")
    # Exactly one of the two pages is honest, and the FAIL names the other.
    assert by_name["person_money_render_honesty"].status == "FAIL"
    assert by_name["person_money_render_honesty"].numerator == 1
    assert by_name["person_money_render_honesty"].denominator == 2
    assert "not_loaded aggregate" in by_name["person_money_render_honesty"].diagnostic


def _export_row_with_coverage(index: int, *, activity_state: str | None, total_raised: str = "0.00"):
    row = _money_row(index, total_raised=total_raised)
    if activity_state is not None:
        row["fundraising_coverage"] = {
            "activity_state": activity_state,
            "completeness": "unknown" if activity_state == "not_loaded" else "complete",
            "basis": "no_authoritative_load_evidence"
            if activity_state == "not_loaded"
            else "fec_official_candidate_summary",
        }
    return row


def test_export_row_publishing_a_total_under_not_loaded_coverage_is_a_defect() -> None:
    module = _probe_module()
    rows = [
        module.FederalExportMoneyRow.model_validate(
            _export_row_with_coverage(0, activity_state=None, total_raised="9000.00")
        ),
        module.FederalExportMoneyRow.model_validate(
            _export_row_with_coverage(1, activity_state="not_loaded", total_raised="0.00")
        ),
    ]

    assertion = module._export_money_honesty_assertion(rows)

    # The row states "no_authoritative_load_evidence" and prints $0.00 in the
    # same object. Exactly one of those two claims can be true.
    assert assertion.status == "FAIL"
    assert assertion.numerator == 1
    assert assertion.denominator == 2
    assert "coverage says not_loaded" in assertion.diagnostic
    assert "Member 1" in assertion.diagnostic


def test_export_row_with_measured_coverage_keeps_its_zero() -> None:
    module = _probe_module()
    rows = [
        module.FederalExportMoneyRow.model_validate(
            _export_row_with_coverage(0, activity_state="loaded_zero", total_raised="0.00")
        ),
        module.FederalExportMoneyRow.model_validate(
            _export_row_with_coverage(1, activity_state=None, total_raised="0.00")
        ),
        # has_fec_money False mints a documented zero and carries no coverage
        # block; has_fec_money is the discriminator clients already read.
        module.FederalExportMoneyRow.model_validate({**_money_row(2, total_raised="0.00"), "has_fec_money": False}),
    ]

    assertion = module._export_money_honesty_assertion(rows)

    # The inverse direction: a measured zero, an out-of-band populated row, and
    # a documented no-FEC-money row are all honest and must not be flagged.
    assert assertion.status == "PASS"
    assert assertion.numerator == 3
    assert assertion.denominator == 3


def test_export_row_that_suppresses_a_total_under_not_loaded_coverage_is_honest() -> None:
    """The shape the repaired export ships: no coverage, no figure.

    This is the assertion that moves from FAIL to PASS when the fundraising
    side gains the ``not_loaded`` suppression branch its outside-spending
    sibling already has. It stays able to fail: reinstate the ``0.00`` beside
    the ``not_loaded`` block and the test above goes red again.
    """
    module = _probe_module()
    rows = [
        module.FederalExportMoneyRow.model_validate(
            _export_row_with_coverage(0, activity_state=None, total_raised="9000.00")
        ),
        module.FederalExportMoneyRow.model_validate(
            {**_export_row_with_coverage(1, activity_state="not_loaded"), "total_raised": None}
        ),
    ]

    assertion = module._export_money_honesty_assertion(rows)

    assert assertion.status == "PASS"
    assert assertion.numerator == 2
    assert assertion.denominator == 2


def test_export_row_that_hides_a_measured_total_is_also_a_defect() -> None:
    """Blanking a measured figure is the same lie pointing the other way.

    A ``populated`` or ``loaded_zero`` row states that the filings WERE read.
    Withholding the number it read is as dishonest as inventing one, and the
    guard has to catch a fix that overshoots into suppressing every zero.
    """
    module = _probe_module()
    rows = [
        # populated by omission: public_money_totals attaches the coverage block
        # only when it carries news, so an absent block means "populated".
        module.FederalExportMoneyRow.model_validate(
            {**_export_row_with_coverage(0, activity_state=None), "total_raised": None}
        ),
        module.FederalExportMoneyRow.model_validate(
            {**_export_row_with_coverage(1, activity_state="loaded_zero"), "total_raised": None}
        ),
        module.FederalExportMoneyRow.model_validate(
            _export_row_with_coverage(2, activity_state="loaded_zero", total_raised="0.00")
        ),
    ]

    assertion = module._export_money_honesty_assertion(rows)

    assert assertion.status == "FAIL"
    assert assertion.numerator == 1
    assert assertion.denominator == 3
    assert "withhold a measured total" in assertion.diagnostic
    assert "Member 0" in assertion.diagnostic


def test_unknown_specimen_total_fails_rather_than_crashing_the_probe() -> None:
    """The release specimen is a live high-raiser; an unknown there is a defect.

    Its ``total_raised`` is now nullable, so this assertion has to reach a FAIL
    verdict on ``None`` instead of raising a TypeError that would take down the
    whole assertion set with it.
    """
    module = _probe_module()
    targets = _release_targets()
    specimen = module.FederalExportMoneyRow.model_validate(
        {
            **_money_row(
                0,
                person_id=str(targets["finance_visual_person_id"]),
                person_name=str(targets["finance_visual_person_name"]),
            ),
            "total_raised": None,
        }
    )

    assertion = module._specimen_total_assertion([specimen], module._load_release_targets())

    assert assertion.status == "FAIL"
    assert assertion.numerator == 0
    assert assertion.denominator == 1
    assert "total_raised=unknown" in assertion.diagnostic


def test_unknown_money_never_counts_toward_the_nonempty_floor() -> None:
    """An unknown is not a nonzero value; nullability may only raise the bar.

    MINIMUM_NONEMPTY_ROWS is unchanged. A file of rows that all say "unknown"
    must fail this floor exactly as a file of zeros does.
    """
    module = _probe_module()
    unknown_rows = [
        module.FederalExportMoneyRow.model_validate(
            {**_money_row(index), "total_raised": None, "ie_support_total": None}
        )
        for index in range(3)
    ]

    assertion = module._nonzero_money_assertion(
        "ie_support_nonzero", unknown_rows, "ie_support_total", "ie_support_total"
    )

    assert module.MINIMUM_NONEMPTY_ROWS == 1
    assert assertion.status == "FAIL"
    assert assertion.numerator == 0
    assert assertion.denominator == 3
