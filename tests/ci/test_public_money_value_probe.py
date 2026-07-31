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
    _write_helper_fixture(fixture_dir, export_payload=_export_rows(denominator=540, fec_rows=540))

    result = _run_probe(fixture_dir)

    assert result.returncode == 0, result.stderr
    assert (
        "money_value_assertion fec_money_coverage PASS numerator=540 denominator=540 "
        "diagnostic=540/540 public export rows have FEC money"
    ) in result.stdout


def test_partial_fec_money_coverage_reports_fail_with_denominator(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "partial-coverage"
    _write_helper_fixture(fixture_dir, export_payload=_export_rows(denominator=540, fec_rows=13))

    result = _run_probe(fixture_dir)

    assert result.returncode == 1
    assert (
        "money_value_assertion fec_money_coverage FAIL numerator=13 denominator=540 "
        "diagnostic=13/540 public export rows have FEC money; expected 540"
    ) in result.stdout


def test_zero_export_rows_reports_vacuous_not_pass(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "zero-export"
    _write_helper_fixture(fixture_dir, export_payload=[])

    result = _run_probe(fixture_dir)

    assert result.returncode == 0, result.stderr
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

    assert result.returncode == 1
    assert (
        "money_value_assertion export_payload FAIL numerator=0 denominator=1 "
        "diagnostic=/api/public/v1/federal/export.json JSON payload must be a list"
    ) in result.stdout


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

    assert result.returncode == 1
    assert (
        "money_value_assertion candidates_rows FAIL numerator=0 denominator=1 "
        "diagnostic=/candidates rendered 0 result rows"
    ) in result.stdout
