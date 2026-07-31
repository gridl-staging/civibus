"""Contract tests for the July 2026 single-deploy recovery receipt."""

from __future__ import annotations

import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
RECEIPT_PATH = REPO_ROOT / "docs/live-state/2026_07_24_single_deploy.md"
JULY_30_RECEIPT_PATH = REPO_ROOT / "docs/live-state/2026_07_30_single_deploy.md"
ROADMAP_PATH = REPO_ROOT / "ROADMAP.md"

RECEIPT_RELATIVE_PATH = "docs/live-state/2026_07_24_single_deploy.md"
EXPECTED_CLOSED_TITLES = {
    "Large merged-but-undeployed delta",
    "CI does not run most of the suite",
}

REQUIRED_RECEIPT_TOKENS = (
    "d4a63ed40fd77c1a2f465654cbf59c2a4217465e",
    "d1d14ef235bd76170e8634201cec03dfe20fe585",
    "30159110547",
    "each_key_duplicate",
    "cm:2026:C00718866",
    "key-metrics",
    "19-candidate unsafe-identity gap",
    "L5 stopped RED",
    "L5R stopped RED",
    "6943e6b2cc3da2600115393538ee7204b6d1a6c0",
    "563643e3d9dc857738574ae924e044cef56fd64f",
    "607953323b81973669bd98f50ae568de988ef51f",
    "1af3e2e106f831ea119f599fbfacb0ac2aaf3770",
    "30171349290",
    "https://github.com/gridl-staging/civibus/actions/runs/30171349290",
    "30171349288",
    "https://github.com/gridl-staging/civibus/actions/runs/30171349288",
    "30171507412",
    "https://github.com/gridl-hq/civibus/actions/runs/30171507412",
    "89713328037",
    "https://github.com/gridl-hq/civibus/actions/runs/30171507412/job/89713328037",
    "4396 collected",
    "3063 selected",
    "3024 passed",
    "39 skipped",
    "1333 deselected",
    "108 files",
    "1065 tests passed",
    "1069 passed, 52 skipped, 2622 deselected",
    "production smoke: 9 passed",
    "API SHA = web SHA = repaired dev SHA = 563643e3d9dc857738574ae924e044cef56fd64f",
    '`/api/health/content` exactly `{"healthy":true}`',
    "Data is current.",
    "2026-07-25",
    "donor `smith` API/page probes HTTP 200 with nonempty rows",
    "donor `johnson` API/page probes HTTP 200 with nonempty rows",
    "surfaces_probed=13 failed=0",
    "candidate_api_total=8249",
    "canonical_eligible_count=7183",
    "sitemap_candidate_count=7183",
    "bare_uuid_candidate_url_count=0",
)

COUPLED_RECEIPT_SNIPPETS = (
    "Rejected original freeze `d4a63ed40fd77c1a2f465654cbf59c2a4217465e`: never accepted as deployed proof.",
    "First deployed-but-RED SHA `d1d14ef235bd76170e8634201cec03dfe20fe585`: prod Deploy run `30159110547` reached the production smoke gate and failed.",
    "Batman repair merge `6943e6b2cc3da2600115393538ee7204b6d1a6c0` produced repaired dev `563643e3d9dc857738574ae924e044cef56fd64f`.",
    "Prod Deploy run `30171507412` for prod SHA `1af3e2e106f831ea119f599fbfacb0ac2aaf3770` passed job `89713328037`.",
    "sitemap oracle on repaired dev `563643e3d9dc857738574ae924e044cef56fd64f`: candidate_api_total=8249, canonical_eligible_count=7183, sitemap_candidate_count=7183, bare_uuid_candidate_url_count=0.",
)

JULY_30_NAVIGATION_ROWS = (
    "| Home | `/` | Federal-first landing heading and body plus `Browse Congress` CTA with `/congress` href | PASS |",
    "| Search | `/search` | Search form; fixture-owned `civ` organization query; nonzero result-count value; matching named result with `/org/<id>` href | PASS |",
    "| Candidates | `/candidates` | Nonzero candidate rows; nonblank named link with `/candidate/<id>` href; campaign-context value; nonzero first-page range | PASS |",
    "| Committees | `/committees` | Nonzero committee rows; nonblank named link with `/committee/<id>` href; committee-context value; nonzero first-page range | PASS |",
    "| Congress | `/congress` | Parsed member count at or above the 500-member production floor (observed 540); first named member links to `/person/<id>` | PASS |",
    "| Developers | `/developers` | `Public API` heading and exact `GET /api/public/v1/federal/officials` endpoint heading inside `main` | PASS |",
    "| Methodology | `/methodology` | Exact page heading and fixture-owned data-freshness policy body | PASS |",
)

JULY_30_COUPLED_RECEIPT_SNIPPETS = (
    "stage_start_sha=80566b06c1ce0f95a97b21088c71d2739f0ddefd; path-scoped starting state: clean.",
    "Stage 1 served SHA `3e2179b7b7d3cae6258aede5b9ff1aa3c923706a` was an ancestor of its HEAD (exit `0`), with `29` commits and `29 files changed, 781 insertions, 77 deletions`; the migration diff was empty.",
    "Baseline prod Deploy run `30527690669` had public-mirror head SHA `52690a04260b75b1edb42e8d218026b7bd8302af` and conclusion `failure` because `Run production smoke gate` failed.",
    "Separate morning prod Deploy run `30527690726` concluded `success` at `2026-07-30T08:41:35Z`; it is neither baseline failed run `30527690669` nor the final Stage 3 deployment.",
    "workflow_primary_nav_occurrences=1",
    "Gate owners: `.github/workflows/deploy.yml` and `tests/ci/test_deploy_workflow_contract.py`; execution seam: `web/tests/smoke/run-playwright.sh`.",
    "dev_sha=d00782dc234194b2008870f13f17916c95f1a581; staging_sha=32709e957997048f75d33485edfb0522aacd3d30; staging CI `30570413122` exact-head `success`; staging Integration `30570413009` exact-head `success`; prod_sha=80179220745efe0c0e60c504fdfc759ac0c4d290; prod Deploy `30570726522` exact-head `success`.",
    "The deploy gate ran `primary-nav non-empty: Home`, `Search`, `Candidates`, `Committees`, `Congress`, `Developers`, and `Methodology`, then finished `16 passed (28.9s)`.",
    "The focused live committee/finance rerun finished `9 passed (22.7s)`.",
    'API: `{"git_sha":"d00782dc234194b2008870f13f17916c95f1a581","built_at":"2026-07-30T18:30:57Z"}`; web: `{"git_sha":"d00782dc234194b2008870f13f17916c95f1a581","built_at":"2026-07-30T18:30:57Z"}`.',
    '`/api/health/content`: HTTP 200 with exact body `{"healthy":true}`.',
    "`cf_candidate_money_serving_coverage`: `2079 >= 1800`; `cf_candidate_money_recent_summary_coverage`: `1669 >= 1440`.",
    "`abel-william-p`: rich, HTTP 200, source-linked, indexable; `aalders-tim`: out-of-cycle official total, HTTP 200, source-linked, indexable; `aaron-richard`: thin, HTTP 200, source-linked, noindex.",
    "`ADAMS, ALMA SHEALEY`: `rows_count=10`; public page showed `Unknown / unclassified $35,250.00 27 transactions`.",
    "`uv run python infra/scripts/candidate_sitemap_oracle.py --base-url https://civibus.shareborough.com` exited `1`, stdout was empty, and stderr ended `TimeoutError: The read operation timed out`; `repo-owner:web/src/routes/sitemap.xml`; sitemap/indexability clause is not proven.",
    "`curl -fsS -o /tmp/johnson.html -w 'query=johnson http_code=%{http_code} total_time=%{time_total} size_download=%{size_download}\\n' --max-time 12 'https://civibus.shareborough.com/donors?q=johnson&by=name'` returned `http_code=000 total_time=12.002112`, then the immediate same-shape rerun returned `http_code=504 total_time=10.323085`; both had empty bodies and zero rows.",
    "Donor owners: `web/src/routes/donors/+page.server.ts:90`, `api/routes/donors.py:13`, and `api/queries/campaign_finance.py:2554`; the `smith` rerun passed with `http_code=200 total_time=6.492196 size_download=49097` and `donor_result_rows=20`; cold donor timing is not proven.",
)

JULY_30_DB_PROBE_COMMAND_SNIPPETS = (
    "$ set -a; source /Users/stuart/repos/gridl-dev/civibus_dev/.secret/civibus-fly.env; set +a",
    "uv run --extra api python - <<'PY'",
    "$ proxy_ready_deadline=$((SECONDS + 30))",
    "$ while ! pg_isready -h 127.0.0.1 -p 16610 -d civibus >/dev/null 2>&1; do",
    '$   if ! kill -0 "$proxy_pid" 2>/dev/null; then',
    '$     echo "flyctl proxy exited before PostgreSQL became ready" >&2',
    "$     cat /tmp/civibus-db-proxy.log >&2",
    "$     exit 1",
    '$   if [ "$SECONDS" -ge "$proxy_ready_deadline" ]; then',
    '$     echo "timed out waiting for PostgreSQL proxy on 127.0.0.1:16610" >&2',
    "$   fi",
    "$   sleep 1",
    "$ done",
    "from api.health_content import FEDERAL_FIRST_CONTENT_FLOORS, _CHECK_QUERIES",
    "from api.queries.campaign_finance import resolve_selected_cycle",
    "from core.db import get_connection",
    'TARGET_CHECKS = ("cf_candidate_money_serving_coverage", "cf_candidate_money_recent_summary_coverage")',
    'cursor.execute("BEGIN READ ONLY")',
    """cursor.execute("SET LOCAL statement_timeout = '10s'")""",
    'print(f"check={check} actual={actual} floor={floor} pass={str(actual >= floor).lower()}")',
    'cursor.execute("ROLLBACK")',
)

JULY_30_DB_PROBE_OUTPUT_BLOCK = """```text
db_identity host=127.0.0.1 port=16610 dbname=civibus
transaction_read_only=on statement_timeout=10s current_database=civibus server_addr=fdaa:6d:a55b:a7b:818:9919:1b00:2 server_port=5432
selected_cycle=2026 coverage_start=2025-01-01 coverage_end=2026-12-31
check=cf_candidate_money_serving_coverage actual=2079 floor=1800 pass=true
check=cf_candidate_money_recent_summary_coverage actual=1669 floor=1440 pass=true
```"""
JULY_30_DB_PROBE_EXIT_LINE = "The documented probe exited `0`."

JULY_30_FORBIDDEN_RECEIPT_SNIPPETS = (
    "$ set -a; source .secret/civibus-fly.env; set +a",
    "uv run --extra api python read-only api.health_content coverage probe",
    "$ until pg_isready -h 127.0.0.1 -p 16610 -d civibus >/dev/null 2>&1; do sleep 1; done",
    "proxy_ready host=127.0.0.1 port=16610",
    "Proxying localhost:16610 to remote [civibus-db.internal]:5432",
)

JULY_30_ROADMAP_DISPOSITION_ROWS = (
    (
        "| `Undeployed delta` | The final exact-head deployment shipped the measured delta; this closes the "
        "deployment instance and materially narrows the row to any later delta. |"
    ),
    (
        "| `Serving gates cannot observe endpoint failure` | The owned deploy workflow now runs all seven "
        "primary-navigation cases, and the successful final Deploy log proves that standing guard executed; "
        "the named primary-nav clause closes. |"
    ),
    (
        "| `Candidate money coverage regressed in production` | Live health floors passed (`2079 >= 1800`, "
        "`1669 >= 1440`) and rich/out-of-cycle/thin specimens behaved correctly; this narrows the row but "
        "does not claim a production masters reload or sitemap proof. |"
    ),
    (
        "| `Employer/occupation canonicalization + industry classification` | The public "
        "`ADAMS, ALMA SHEALEY` page proves the unknown/unclassified rollup and closes only clause (1); "
        "the structured-coverage clause remains open. |"
    ),
    (
        "| `Unbounded serving queries at 16M rows` | Remains open because `/sitemap.xml` timed out and the "
        "cold `johnson` donor query timed out/returned 504. |"
    ),
)

ALLOWED_DEPLOY_VERDICTS = {
    "DEPLOY VERDICT: SHIPPED_AND_GATED",
    "DEPLOY VERDICT: SHIPPED_GATE_NOT_WIRED",
    "DEPLOY VERDICT: NOT_SHIPPED",
}


def _assert_receipt_contract(receipt_text: str) -> None:
    missing_tokens = [token for token in REQUIRED_RECEIPT_TOKENS if token not in receipt_text]
    assert missing_tokens == []

    missing_coupled_snippets = [snippet for snippet in COUPLED_RECEIPT_SNIPPETS if snippet not in receipt_text]
    assert missing_coupled_snippets == []


def _assert_july_30_receipt_contract(receipt_text: str) -> None:
    missing_navigation_rows = [row for row in JULY_30_NAVIGATION_ROWS if row not in receipt_text]
    assert missing_navigation_rows == []

    coupled_receipt_snippets = tuple(
        snippet
        for snippet in JULY_30_COUPLED_RECEIPT_SNIPPETS
        if not snippet.startswith("`curl -fsS -o /tmp/johnson.html")
    )
    missing_coupled_snippets = [snippet for snippet in coupled_receipt_snippets if snippet not in receipt_text]
    assert missing_coupled_snippets == []
    assert "curl -fsS -o /tmp/johnson.html" not in receipt_text
    secure_donor_probe_snippets = (
        "$ (\n$ johnson_output=$(mktemp /tmp/civibus-johnson.XXXXXX) || exit 1",
        """$ trap 'rm -f -- "$johnson_output"' EXIT""",
        """curl -fsS -o "$johnson_output" -w 'query=johnson http_code=%{http_code} """
        """total_time=%{time_total} size_download=%{size_download}\\n' --max-time 12 """
        """'https://civibus.shareborough.com/donors?q=johnson&by=name'\n$ )""",
    )
    assert [snippet for snippet in secure_donor_probe_snippets if snippet not in receipt_text] == []

    insecure_fixed_log_snippets = (
        ">/tmp/civibus-db-proxy.log 2>&1 &",
        "$     cat /tmp/civibus-db-proxy.log >&2",
    )
    assert [snippet for snippet in insecure_fixed_log_snippets if snippet in receipt_text] == []
    assert (
        "$ set -a; source /Users/stuart/repos/gridl-dev/civibus_dev/.secret/civibus-fly.env; set +a" not in receipt_text
    )

    db_probe_boundary_snippets = (
        "$ (\n$ set -a",
        "$ source /Users/stuart/repos/gridl-dev/civibus_dev/.secret/civibus-fly.env || { set +a; exit 1; }",
        "$ set +a",
        "$ proxy_log=$(mktemp /tmp/civibus-db-proxy.XXXXXX) || exit 1",
        '$ flyctl proxy 16610:5432 -a civibus-db >"$proxy_log" 2>&1 &',
        "$ proxy_pid=$!",
        """$ trap 'kill "$proxy_pid" 2>/dev/null || true; rm -f -- "$proxy_log"' EXIT""",
        '$     cat "$proxy_log" >&2',
        (
            "$ POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=16610 POSTGRES_USER=civibus POSTGRES_DB=civibus "
            "uv run --extra api python - <<'PY'"
        ),
        "PY\n$ )",
    )
    db_probe_command_snippets = tuple(
        snippet
        for snippet in JULY_30_DB_PROBE_COMMAND_SNIPPETS
        if snippet
        not in {
            "$ set -a; source /Users/stuart/repos/gridl-dev/civibus_dev/.secret/civibus-fly.env; set +a",
            "$     cat /tmp/civibus-db-proxy.log >&2",
        }
    )
    required_db_probe_command_snippets = db_probe_command_snippets + db_probe_boundary_snippets
    missing_db_probe_command_snippets = [
        snippet for snippet in required_db_probe_command_snippets if snippet not in receipt_text
    ]
    assert missing_db_probe_command_snippets == []
    assert JULY_30_DB_PROBE_OUTPUT_BLOCK in receipt_text
    assert JULY_30_DB_PROBE_EXIT_LINE in receipt_text

    forbidden_receipt_snippets = [snippet for snippet in JULY_30_FORBIDDEN_RECEIPT_SNIPPETS if snippet in receipt_text]
    assert forbidden_receipt_snippets == []

    missing_roadmap_disposition_rows = [row for row in JULY_30_ROADMAP_DISPOSITION_ROWS if row not in receipt_text]
    assert missing_roadmap_disposition_rows == []

    assert receipt_text.count("workflow_primary_nav_occurrences=1") == 1
    verdict_lines = [line for line in receipt_text.splitlines() if line.startswith("DEPLOY VERDICT:")]
    assert verdict_lines == ["DEPLOY VERDICT: SHIPPED_AND_GATED"]
    assert verdict_lines[0] in ALLOWED_DEPLOY_VERDICTS


def _roadmap_rows(roadmap_text: str) -> dict[str, list[str]]:
    rows: dict[str, list[str]] = {}
    for line in roadmap_text.splitlines():
        match = re.match(r"^\| P\d \| (?P<title>.+?) — .+? \|", line)
        if match:
            rows.setdefault(match.group("title"), []).append(line)
    return rows


def _closed_pass_titles_for_date(roadmap_text: str, close_date: str) -> set[str]:
    closed_titles: set[str] = set()
    for title, row_lines in _roadmap_rows(roadmap_text).items():
        if any(f"**CLOSED/PASS {close_date}**" in row for row in row_lines):
            closed_titles.add(title)
    return closed_titles


def _assert_roadmap_contract(roadmap_text: str) -> None:
    rows = _roadmap_rows(roadmap_text)
    closed_pass_marker = "**CLOSED/PASS 2026-07-25**"

    assert _closed_pass_titles_for_date(roadmap_text, "2026-07-25") == EXPECTED_CLOSED_TITLES
    for title in EXPECTED_CLOSED_TITLES:
        closed_rows = [row for row in rows[title] if closed_pass_marker in row]
        assert len(closed_rows) == 1
        assert RECEIPT_RELATIVE_PATH in closed_rows[0]

    assert "Weekly federal refresh terminal RED" in rows
    assert "Serving gates cannot observe endpoint failure" in rows

    deploy_currency_rows = rows["Deploy currency"]
    assert len(deploy_currency_rows) == 1
    deploy_currency_row = deploy_currency_rows[0]
    assert "**CLOSED/PASS 2026-07-17**" in deploy_currency_row
    assert "20 consecutive observations per gate" in deploy_currency_row
    assert "at least one deploy in the combined window" in deploy_currency_row
    assert "zero false would-be kills" in deploy_currency_row
    assert "docs/live-state/2026_07_24_shadow_gate_promotion.md" in deploy_currency_row


@pytest.mark.dev_repo_only(
    private_asset="private single-deploy recovery receipt under docs/live-state/",
    owner="single deploy recovery receipt contract",
)
def test_single_deploy_receipt_contains_fail_closed_recovery_chain() -> None:
    _assert_receipt_contract(RECEIPT_PATH.read_text(encoding="utf-8"))


@pytest.mark.dev_repo_only(
    private_asset="private July 30 single-deploy receipt under docs/live-state/",
    owner="single deploy recovery receipt contract",
)
def test_july_30_single_deploy_receipt_preserves_gated_chain_and_red_findings() -> None:
    _assert_july_30_receipt_contract(JULY_30_RECEIPT_PATH.read_text(encoding="utf-8"))


def test_july_30_receipt_guard_fails_when_db_probe_command_is_not_executable() -> None:
    receipt_text = JULY_30_RECEIPT_PATH.read_text(encoding="utf-8")

    with pytest.raises(AssertionError):
        _assert_july_30_receipt_contract(
            receipt_text.replace(
                "uv run --extra api python - <<'PY'",
                "uv run --extra api python read-only api.health_content coverage probe",
            )
        )


def test_july_30_receipt_guard_fails_when_secret_source_path_is_relative() -> None:
    receipt_text = JULY_30_RECEIPT_PATH.read_text(encoding="utf-8")

    with pytest.raises(AssertionError):
        _assert_july_30_receipt_contract(
            receipt_text.replace(
                "/Users/stuart/repos/gridl-dev/civibus_dev/.secret/civibus-fly.env",
                ".secret/civibus-fly.env",
            )
        )


def test_july_30_receipt_guard_fails_when_db_proxy_readiness_wait_is_unbounded() -> None:
    receipt_text = JULY_30_RECEIPT_PATH.read_text(encoding="utf-8")
    bounded_wait = """$ proxy_ready_deadline=$((SECONDS + 30))
$ while ! pg_isready -h 127.0.0.1 -p 16610 -d civibus >/dev/null 2>&1; do
$   if ! kill -0 "$proxy_pid" 2>/dev/null; then
$     echo "flyctl proxy exited before PostgreSQL became ready" >&2
$     cat "$proxy_log" >&2
$     exit 1
$   fi
$   if [ "$SECONDS" -ge "$proxy_ready_deadline" ]; then
$     echo "timed out waiting for PostgreSQL proxy on 127.0.0.1:16610" >&2
$     cat "$proxy_log" >&2
$     exit 1
$   fi
$   sleep 1
$ done"""

    with pytest.raises(AssertionError):
        _assert_july_30_receipt_contract(
            receipt_text.replace(
                bounded_wait,
                "$ until pg_isready -h 127.0.0.1 -p 16610 -d civibus >/dev/null 2>&1; do sleep 1; done",
            )
        )


def test_july_30_receipt_guard_fails_when_db_probe_output_includes_impossible_proxy_lines() -> None:
    receipt_text = JULY_30_RECEIPT_PATH.read_text(encoding="utf-8")
    impossible_proxy_output = """```text
proxy_ready host=127.0.0.1 port=16610
Proxying localhost:16610 to remote [civibus-db.internal]:5432
```"""

    with pytest.raises(AssertionError):
        _assert_july_30_receipt_contract(
            receipt_text.replace(
                JULY_30_DB_PROBE_OUTPUT_BLOCK,
                f"{JULY_30_DB_PROBE_OUTPUT_BLOCK}\n\n{impossible_proxy_output}",
            )
        )


def test_july_30_receipt_guard_fails_when_roadmap_disposition_overclaims() -> None:
    receipt_text = JULY_30_RECEIPT_PATH.read_text(encoding="utf-8")

    with pytest.raises(AssertionError):
        _assert_july_30_receipt_contract(
            receipt_text.replace(
                "| `Unbounded serving queries at 16M rows` | Remains open because `/sitemap.xml` timed out "
                "and the cold `johnson` donor query timed out/returned 504. |",
                "| `Unbounded serving queries at 16M rows` | Closed by the successful deploy. |",
            )
        )


@pytest.mark.dev_repo_only(
    private_asset="ROADMAP.md",
    owner="single deploy recovery receipt contract",
)
def test_roadmap_closes_only_authorized_single_deploy_rows() -> None:
    roadmap_text = ROADMAP_PATH.read_text(encoding="utf-8")

    _assert_roadmap_contract(roadmap_text)

    shadow_gate_receipt_text = (REPO_ROOT / "docs/live-state/2026_07_24_shadow_gate_promotion.md").read_text(
        encoding="utf-8"
    )
    assert "Canonical deployed dev SHA:" in shadow_gate_receipt_text
    assert "Prod `Deploy` run `30179991749`:" in shadow_gate_receipt_text
    assert "Post-promotion run:" in shadow_gate_receipt_text
    assert "This receipt is private dev evidence." in shadow_gate_receipt_text

    duplicate_closed_row = (
        "\n| P0 | CI does not run most of the suite — **CLOSED/PASS 2026-07-25** | "
        "duplicate closure with docs/live-state/2026_07_24_single_deploy.md evidence | duplicate gate |"
    )
    with pytest.raises(AssertionError):
        _assert_roadmap_contract(roadmap_text + duplicate_closed_row)

    with pytest.raises(AssertionError):
        _assert_roadmap_contract(
            roadmap_text.replace(
                "Promotion receipt: `docs/live-state/2026_07_24_shadow_gate_promotion.md`.",
                "Promotion receipt removed.",
            )
        )


def test_receipt_guard_fails_when_required_sha_or_count_is_removed() -> None:
    specimen = "\n".join(REQUIRED_RECEIPT_TOKENS + COUPLED_RECEIPT_SNIPPETS)

    with pytest.raises(AssertionError):
        _assert_receipt_contract(specimen.replace("candidate_api_total=8249", ""))

    with pytest.raises(AssertionError):
        _assert_receipt_contract(
            specimen.replace(
                "Prod Deploy run `30171507412` for prod SHA `1af3e2e106f831ea119f599fbfacb0ac2aaf3770` passed job `89713328037`.",
                "",
            )
        )


@pytest.mark.dev_repo_only(
    private_asset="ROADMAP.md",
    owner="single deploy recovery receipt contract",
)
def test_roadmap_guard_fails_when_extra_row_closes_on_single_deploy_date() -> None:
    roadmap_text = ROADMAP_PATH.read_text(encoding="utf-8")
    extra_closed_row = "\n| P0 | Deploy currency — **CLOSED/PASS 2026-07-25** | bad closure | bad gate |"

    with pytest.raises(AssertionError):
        _assert_roadmap_contract(roadmap_text + extra_closed_row)
