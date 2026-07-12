from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Iterator
from dataclasses import dataclass
from math import ceil
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import httpx
import pytest
from psycopg.rows import dict_row

from api.queries.civics import fetch_current_federal_members
from core.db import get_connection
from core.keel_gate_l14 import FEDERAL_OFFICE_NAMES
from test_support.api_real_path import (
    build_public_headers,
    configure_real_path_environment,
    real_path_environment_values,
    restore_environment,
)

pytestmark = [pytest.mark.integration, pytest.mark.e2e]

_EXPECTED_ACTIVE_FEDERAL_OFFICEHOLDERS = 543
_MIN_CURRENT_OFFICEHOLDING_FLOOR = 535
_MIN_PORTRAIT_COVERAGE_PERCENT = 90.0
_MIN_BIO_COVERAGE_PERCENT = 80.0
_MIN_CANDIDATE_LINK_COVERAGE_PERCENT = 95.0
_MIN_IE_CANDIDATE_COVERAGE_PERCENT = 1.0
_BIOGUIDE_RIGHTS_PROBE_ID = "P000197"
_LIVE_API_BASE_URL = "http://127.0.0.1:8015"
_LIVE_API_READY_TIMEOUT_SECONDS = 45.0

_ACTIVE_FEDERAL_OFFICEHOLDERS_SQL = """
    SELECT DISTINCT
        oh.person_id,
        p.canonical_name,
        p.identifiers->>'bioguide_id' AS bioguide_id,
        p.identifiers->>'wikidata_id' AS wikidata_id,
        p.bio_text
    FROM civic.officeholding oh
    JOIN civic.office o ON o.id = oh.office_id
    JOIN core.person p ON p.id = oh.person_id
    WHERE o.office_level = 'federal'
      AND upper_inf(oh.valid_period)
"""


@dataclass(frozen=True)
class CoverageGate:
    numerator: int
    denominator: int

    @property
    def percentage(self) -> float:
        if self.denominator == 0:
            return 0.0
        return (self.numerator / self.denominator) * 100


@dataclass(frozen=True)
class LiveApiServer:
    base_url: str
    stderr_path: Path

    def stderr_tail(self, *, max_chars: int = 2000) -> str:
        try:
            return self.stderr_path.read_text(encoding="utf-8")[-max_chars:]
        except OSError as error:
            return f"<stderr unavailable: {error}>"


@pytest.fixture(scope="module")
def real_path_environment() -> Iterator[None]:
    previous_environment = configure_real_path_environment()
    try:
        yield
    finally:
        restore_environment(previous_environment)


@pytest.fixture(scope="module")
def federal_connection(real_path_environment: None) -> Iterator[Any]:
    connection = get_connection()
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture(scope="module")
def live_api_server(real_path_environment: None) -> Iterator[LiveApiServer]:
    server_environment = os.environ.copy()
    server_environment.update(real_path_environment_values())
    server_environment["PYTHONUNBUFFERED"] = "1"
    with TemporaryDirectory() as tmp_dir:
        stderr_path = Path(tmp_dir) / "uvicorn.stderr.log"
        stdout_path = Path(tmp_dir) / "uvicorn.stdout.log"
        with (
            stdout_path.open("w", encoding="utf-8") as stdout_file,
            stderr_path.open(
                "w",
                encoding="utf-8",
            ) as stderr_file,
        ):
            process = subprocess.Popen(
                [
                    "uv",
                    "run",
                    "--extra",
                    "dev",
                    "--extra",
                    "api",
                    "uvicorn",
                    "api.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "8015",
                ],
                env=server_environment,
                stdout=stdout_file,
                stderr=stderr_file,
                text=True,
            )
            try:
                server = LiveApiServer(base_url=_LIVE_API_BASE_URL, stderr_path=stderr_path)
                _wait_for_live_api_readiness(process, server)
                yield server
            finally:
                _terminate_live_api_process(process)


def _wait_for_live_api_readiness(process: subprocess.Popen[str], server: LiveApiServer) -> None:
    deadline = time.monotonic() + _LIVE_API_READY_TIMEOUT_SECONDS
    last_error: str | None = None
    while time.monotonic() < deadline:
        return_code = process.poll()
        if return_code is not None:
            pytest.fail(
                "live API server exited before readiness "
                f"return_code={return_code} stderr={server.stderr_tail(max_chars=1000)}"
            )
        try:
            response = httpx.get(f"{_LIVE_API_BASE_URL}/health", timeout=1.0)
            if response.status_code == 200:
                return
            last_error = f"status={response.status_code} body={response.text[:500]}"
        except httpx.HTTPError as error:
            last_error = repr(error)
        time.sleep(0.25)
    _terminate_live_api_process(process)
    pytest.fail(f"live API server did not become ready after {_LIVE_API_READY_TIMEOUT_SECONDS}s: {last_error}")


def _terminate_live_api_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def _fetch_single_int(connection: Any, sql: str) -> int:
    with connection.cursor() as cursor:
        cursor.execute(sql)
        row = cursor.fetchone()
    assert row is not None
    return int(row[0])


def _fetch_rows(connection: Any, sql: str, *, limit: int = 10) -> list[dict[str, Any]]:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(f"{sql} LIMIT %s", (limit,))
        return list(cursor.fetchall())


def _format_rows(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "none"
    formatted_rows = []
    for row in rows:
        formatted_rows.append(
            ", ".join(
                f"{key}={value}"
                for key, value in row.items()
                if key in {"person_id", "canonical_name", "bioguide_id", "wikidata_id"}
            )
        )
    return "; ".join(formatted_rows)


def _active_federal_denominator(connection: Any) -> int:
    return _fetch_single_int(
        connection,
        f"""
        WITH active_federal AS ({_ACTIVE_FEDERAL_OFFICEHOLDERS_SQL})
        SELECT COUNT(DISTINCT person_id)
        FROM active_federal
        """,
    )


def _coverage_gate(connection: Any, *, covered_sql: str) -> CoverageGate:
    denominator = _active_federal_denominator(connection)
    numerator = _fetch_single_int(connection, covered_sql)
    return CoverageGate(numerator=numerator, denominator=denominator)


def _missing_identifier_diagnostics(connection: Any) -> str:
    missing_bioguide_rows = _fetch_rows(
        connection,
        f"""
        WITH active_federal AS ({_ACTIVE_FEDERAL_OFFICEHOLDERS_SQL})
        SELECT person_id, canonical_name, bioguide_id, wikidata_id
        FROM active_federal
        WHERE NULLIF(BTRIM(bioguide_id), '') IS NULL
        ORDER BY canonical_name, person_id
        """,
    )
    missing_wikidata_rows = _fetch_rows(
        connection,
        f"""
        WITH active_federal AS ({_ACTIVE_FEDERAL_OFFICEHOLDERS_SQL})
        SELECT person_id, canonical_name, bioguide_id, wikidata_id
        FROM active_federal
        WHERE NULLIF(BTRIM(wikidata_id), '') IS NULL
        ORDER BY canonical_name, person_id
        """,
    )
    return (
        "missing_bioguide_samples=["
        f"{_format_rows(missing_bioguide_rows)}"
        "] missing_wikidata_samples=["
        f"{_format_rows(missing_wikidata_rows)}"
        "]"
    )


def _missing_portrait_diagnostics(connection: Any) -> str:
    rows = _fetch_rows(
        connection,
        f"""
        WITH active_federal AS ({_ACTIVE_FEDERAL_OFFICEHOLDERS_SQL})
        SELECT person_id, canonical_name, bioguide_id
        FROM active_federal af
        WHERE NOT EXISTS (
            SELECT 1
            FROM core.person_portrait pp
            WHERE pp.person_id = af.person_id
              AND pp.status = 'active'
        )
        ORDER BY canonical_name, person_id
        """,
    )
    return f"missing_active_portrait_samples=[{_format_rows(rows)}]"


def _missing_bio_diagnostics(connection: Any) -> str:
    rows = _fetch_rows(
        connection,
        f"""
        WITH active_federal AS ({_ACTIVE_FEDERAL_OFFICEHOLDERS_SQL})
        SELECT person_id, canonical_name, bioguide_id
        FROM active_federal
        WHERE NULLIF(BTRIM(bio_text), '') IS NULL
        ORDER BY canonical_name, person_id
        """,
    )
    return f"missing_bio_samples=[{_format_rows(rows)}]"


def _resolve_active_federal_person_for_bioguide_id(connection: Any, bioguide_id: str) -> dict[str, Any]:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            f"""
            WITH active_federal AS ({_ACTIVE_FEDERAL_OFFICEHOLDERS_SQL})
            SELECT person_id, canonical_name, bioguide_id
            FROM active_federal
            WHERE bioguide_id = %s
            ORDER BY canonical_name, person_id
            LIMIT 2
            """,
            (bioguide_id,),
        )
        rows = list(cursor.fetchall())

    assert len(rows) == 1, (
        "expected exactly one active federal officeholder for Bioguide probe "
        f"bioguide_id={bioguide_id} matches={len(rows)} samples=[{_format_rows(rows)}]"
    )
    return rows[0]


_FEDERAL_OFFICE_NAMES_SQL_ARRAY = "ARRAY[" + ", ".join(f"'{name}'" for name in FEDERAL_OFFICE_NAMES) + "]"


def _federal_seat_total(connection: Any) -> int:
    return _fetch_single_int(
        connection,
        f"""
        SELECT COALESCE(SUM(number_of_seats), 0)::int
        FROM civic.office
        WHERE office_level = 'federal'
          AND name = ANY({_FEDERAL_OFFICE_NAMES_SQL_ARRAY})
        """,
    )


def _documented_federal_vacancy_count(connection: Any) -> int:
    return _fetch_single_int(
        connection,
        f"""
        WITH office_state AS (
            SELECT
                o.id,
                o.number_of_seats,
                COUNT(*) FILTER (WHERE upper_inf(oh.valid_period)) AS active_count,
                COUNT(*) FILTER (WHERE NOT upper_inf(oh.valid_period)) AS closed_count
            FROM civic.office o
            LEFT JOIN civic.officeholding oh ON oh.office_id = o.id
            WHERE o.office_level = 'federal'
              AND o.name = ANY({_FEDERAL_OFFICE_NAMES_SQL_ARRAY})
            GROUP BY o.id, o.number_of_seats
        )
        SELECT COALESCE(
            SUM(
                LEAST(
                    GREATEST(number_of_seats - active_count, 0),
                    closed_count
                )
            ),
            0
        )::int
        FROM office_state
        """,
    )


def _undocumented_missing_federal_seat_count(connection: Any) -> int:
    return _fetch_single_int(
        connection,
        f"""
        WITH office_state AS (
            SELECT
                o.id,
                o.number_of_seats,
                COUNT(*) FILTER (WHERE upper_inf(oh.valid_period)) AS active_count,
                COUNT(*) FILTER (WHERE NOT upper_inf(oh.valid_period)) AS closed_count
            FROM civic.office o
            LEFT JOIN civic.officeholding oh ON oh.office_id = o.id
            WHERE o.office_level = 'federal'
              AND o.name = ANY({_FEDERAL_OFFICE_NAMES_SQL_ARRAY})
            GROUP BY o.id, o.number_of_seats
        )
        SELECT COALESCE(
            SUM(
                GREATEST(number_of_seats - active_count, 0)
                - LEAST(GREATEST(number_of_seats - active_count, 0), closed_count)
            ),
            0
        )::int
        FROM office_state
        """,
    )


def _missing_seat_diagnostics(connection: Any) -> str:
    rows = _fetch_rows(
        connection,
        f"""
        SELECT o.name AS office_name, o.state, o.number_of_seats,
               COUNT(oh.id)::int AS active_holders
        FROM civic.office o
        LEFT JOIN civic.officeholding oh
            ON oh.office_id = o.id AND upper_inf(oh.valid_period)
        WHERE o.office_level = 'federal'
          AND o.name = ANY({_FEDERAL_OFFICE_NAMES_SQL_ARRAY})
        GROUP BY o.id, o.name, o.state, o.number_of_seats
        HAVING COUNT(oh.id) < o.number_of_seats
        ORDER BY o.name, o.state
        """,
        limit=20,
    )
    if not rows:
        return "all seats filled"
    parts = []
    for row in rows:
        parts.append(
            f"{row['office_name']}"
            f"(state={row.get('state')}, seats={row['number_of_seats']}, "
            f"active={row['active_holders']})"
        )
    return f"under-filled_offices=[{'; '.join(parts)}]"


def test_federal_officeholder_universe_is_bounded(federal_connection: Any) -> None:
    total_seats = _federal_seat_total(federal_connection)

    assert total_seats == _EXPECTED_ACTIVE_FEDERAL_OFFICEHOLDERS, (
        "federal officeholder seat universe mismatch "
        f"expected={_EXPECTED_ACTIVE_FEDERAL_OFFICEHOLDERS} actual={total_seats} "
        f"{_missing_seat_diagnostics(federal_connection)}"
    )


def test_federal_member_directory_decomposes_to_543(federal_connection: Any) -> None:
    active = _active_federal_denominator(federal_connection)
    documented_vacancies = _documented_federal_vacancy_count(federal_connection)
    undocumented_missing = _undocumented_missing_federal_seat_count(federal_connection)
    total_seats = _federal_seat_total(federal_connection)

    assert total_seats == _EXPECTED_ACTIVE_FEDERAL_OFFICEHOLDERS, (
        "federal office seat total does not equal expected denominator "
        f"sum(number_of_seats)={total_seats} "
        f"expected={_EXPECTED_ACTIVE_FEDERAL_OFFICEHOLDERS} "
        f"{_missing_seat_diagnostics(federal_connection)}"
    )
    assert undocumented_missing == 0, (
        "federal seats are missing without a documented vacancy (no prior holder "
        "found in civic.officeholding); a documented vacancy requires a closed "
        "officeholding row for the same office. "
        f"undocumented_missing={undocumented_missing} "
        f"active={active} documented_vacancies={documented_vacancies} "
        f"{_missing_seat_diagnostics(federal_connection)}"
    )
    assert active + documented_vacancies == _EXPECTED_ACTIVE_FEDERAL_OFFICEHOLDERS, (
        "vacancy-aware decomposition failed: "
        f"active={active} + documented_vacancies={documented_vacancies} "
        f"= {active + documented_vacancies} "
        f"expected={_EXPECTED_ACTIVE_FEDERAL_OFFICEHOLDERS} "
        f"{_missing_seat_diagnostics(federal_connection)}"
    )


def test_current_federal_officeholding_floor(federal_connection: Any) -> None:
    active = _active_federal_denominator(federal_connection)

    assert active >= _MIN_CURRENT_OFFICEHOLDING_FLOOR, (
        "active federal officeholder count below minimum floor "
        f"active={active} floor={_MIN_CURRENT_OFFICEHOLDING_FLOOR} "
        f"{_missing_seat_diagnostics(federal_connection)}"
    )


def test_active_federal_candidate_link_coverage_meets_gate(federal_connection: Any) -> None:
    coverage = _coverage_gate(
        federal_connection,
        covered_sql=f"""
        WITH active_federal AS ({_ACTIVE_FEDERAL_OFFICEHOLDERS_SQL})
        SELECT COUNT(DISTINCT af.person_id)
        FROM active_federal af
        JOIN cf.candidate c ON c.person_id = af.person_id
        """,
    )

    assert coverage.percentage >= _MIN_CANDIDATE_LINK_COVERAGE_PERCENT, (
        "active federal candidate-link coverage below gate: "
        f"linked={coverage.numerator} denominator={coverage.denominator} "
        f"percentage={coverage.percentage:.2f}% "
        f"threshold={_MIN_CANDIDATE_LINK_COVERAGE_PERCENT:.2f}% "
        "— officeholders without a cf.candidate row cannot be joined to FEC money data"
    )


def test_non_vacant_officeholding_completeness(federal_connection: Any) -> None:
    incomplete_count = _fetch_single_int(
        federal_connection,
        f"""
        WITH active_federal AS ({_ACTIVE_FEDERAL_OFFICEHOLDERS_SQL})
        SELECT COUNT(*)
        FROM active_federal af
        JOIN civic.officeholding oh ON oh.person_id = af.person_id
            AND upper_inf(oh.valid_period)
        JOIN civic.office o ON o.id = oh.office_id
            AND o.office_level = 'federal'
        WHERE (
              o.name NOT IN ('us_president', 'us_vice_president')
              AND NULLIF(BTRIM(af.bioguide_id), '') IS NULL
           )
           OR (
              o.name IN ('us_president', 'us_vice_president')
              AND NULLIF(BTRIM(af.bioguide_id), '') IS NULL
              AND NULLIF(BTRIM(af.wikidata_id), '') IS NULL
           )
           OR oh.office_id IS NULL
           OR af.person_id IS NULL
        """,
    )
    missing_party_count = _fetch_single_int(
        federal_connection,
        f"""
        WITH active_federal AS ({_ACTIVE_FEDERAL_OFFICEHOLDERS_SQL}),
        party_check AS (
            SELECT af.person_id, af.canonical_name, af.bioguide_id,
                       COALESCE(
                           (SELECT c.party FROM cf.candidate c
                            WHERE c.person_id = af.person_id AND c.party IS NOT NULL
                            ORDER BY c.summary_coverage_end_date DESC NULLS LAST LIMIT 1),
                           (SELECT cd.party FROM civic.candidacy cd
                            JOIN civic.contest ct ON ct.id = cd.contest_id
                            WHERE cd.person_id = af.person_id AND cd.party IS NOT NULL
                            ORDER BY ct.election_date DESC NULLS LAST LIMIT 1),
                           (SELECT sr.raw_fields->>'party'
                            FROM civic.officeholding oh
                            JOIN core.source_record sr ON sr.id = oh.source_record_id
                            JOIN civic.office o ON o.id = oh.office_id
                            WHERE oh.person_id = af.person_id
                              AND o.office_level = 'federal'
                              AND upper_inf(oh.valid_period)
                              AND NULLIF(BTRIM(sr.raw_fields->>'party'), '') IS NOT NULL
                            LIMIT 1)
                       ) AS resolved_party
                FROM active_federal af
            )
        SELECT COUNT(*) FROM party_check WHERE resolved_party IS NULL
        """,
    )

    assert incomplete_count == 0, (
        "non-vacant federal officeholdings with missing core fields "
        f"incomplete={incomplete_count} "
        "(missing congressional bioguide_id, executive bioguide_id-or-wikidata_id, office_id, or person_id)"
    )
    assert missing_party_count == 0, (
        "non-vacant federal officeholders without resolvable party affiliation "
        f"missing_party={missing_party_count} "
        "— party is resolved from cf.candidate, civic.candidacy, or officeholding source raw_fields"
    )


def test_active_federal_independent_expenditure_presence(federal_connection: Any) -> None:
    linked_active_candidates = _fetch_single_int(
        federal_connection,
        f"""
        WITH active_federal AS ({_ACTIVE_FEDERAL_OFFICEHOLDERS_SQL})
        SELECT COUNT(DISTINCT af.person_id)
        FROM active_federal af
        JOIN cf.candidate c ON c.person_id = af.person_id
        """,
    )
    min_candidates_with_ie = ceil(linked_active_candidates * (_MIN_IE_CANDIDATE_COVERAGE_PERCENT / 100))
    candidates_with_ie = _fetch_single_int(
        federal_connection,
        f"""
        WITH active_federal AS ({_ACTIVE_FEDERAL_OFFICEHOLDERS_SQL})
        SELECT COUNT(DISTINCT af.person_id)
        FROM active_federal af
        JOIN cf.candidate c ON c.person_id = af.person_id
        JOIN cf.transaction t ON t.recipient_candidate_id = c.id
        WHERE t.transaction_type = 'Independent Expenditure'
        """,
    )
    coverage = CoverageGate(numerator=candidates_with_ie, denominator=linked_active_candidates)

    assert linked_active_candidates > 0, (
        "no active federal officeholders are linked to cf.candidate — "
        "FEC bulk ingest and candidate linkage must run before this gate"
    )
    assert coverage.percentage >= _MIN_IE_CANDIDATE_COVERAGE_PERCENT, (
        "active federal independent-expenditure coverage below gate: "
        f"candidates_with_ie={coverage.numerator} "
        f"linked_active_candidates={coverage.denominator} "
        f"percentage={coverage.percentage:.2f}% "
        f"threshold={_MIN_IE_CANDIDATE_COVERAGE_PERCENT:.2f}% "
        f"hand_calculated_min=ceil({coverage.denominator} * "
        f"{_MIN_IE_CANDIDATE_COVERAGE_PERCENT:.2f} / 100) = {min_candidates_with_ie} "
        "— IE data must be loaded via schedule_e_loader into cf.transaction "
        "before this gate can pass"
    )


def test_federal_denominator_consistency(federal_connection: Any) -> None:
    test_denominator = _active_federal_denominator(federal_connection)
    api_members = fetch_current_federal_members(federal_connection)
    api_person_ids = {row["person_id"] for row in api_members}
    api_denominator = len(api_person_ids)

    assert test_denominator == api_denominator, (
        "federal denominator mismatch between test helper and API query: "
        f"_active_federal_denominator()={test_denominator} "
        f"len(fetch_current_federal_members())={api_denominator} "
        "— these two queries should return the same count of active federal officeholders"
    )


def test_active_federal_portrait_coverage_meets_gate(federal_connection: Any) -> None:
    coverage = _coverage_gate(
        federal_connection,
        covered_sql=f"""
        WITH active_federal AS ({_ACTIVE_FEDERAL_OFFICEHOLDERS_SQL})
        SELECT COUNT(DISTINCT af.person_id)
        FROM active_federal af
        JOIN core.person_portrait pp ON pp.person_id = af.person_id
        WHERE pp.status = 'active'
        """,
    )

    assert coverage.percentage >= _MIN_PORTRAIT_COVERAGE_PERCENT, (
        "active federal portrait coverage below gate "
        f"covered={coverage.numerator} denominator={coverage.denominator} "
        f"percentage={coverage.percentage:.2f} threshold={_MIN_PORTRAIT_COVERAGE_PERCENT:.2f} "
        f"{_missing_identifier_diagnostics(federal_connection)} "
        f"{_missing_portrait_diagnostics(federal_connection)}"
    )


def test_active_federal_bio_coverage_meets_gate(federal_connection: Any) -> None:
    coverage = _coverage_gate(
        federal_connection,
        covered_sql=f"""
        WITH active_federal AS ({_ACTIVE_FEDERAL_OFFICEHOLDERS_SQL})
        SELECT COUNT(DISTINCT person_id)
        FROM active_federal
        WHERE NULLIF(BTRIM(bio_text), '') IS NOT NULL
        """,
    )

    assert coverage.percentage >= _MIN_BIO_COVERAGE_PERCENT, (
        "active federal bio coverage below gate "
        f"covered={coverage.numerator} denominator={coverage.denominator} "
        f"percentage={coverage.percentage:.2f} threshold={_MIN_BIO_COVERAGE_PERCENT:.2f} "
        f"{_missing_identifier_diagnostics(federal_connection)} "
        f"{_missing_bio_diagnostics(federal_connection)}"
    )


def test_live_person_api_surfaces_public_domain_bioguide_portrait(
    federal_connection: Any,
    live_api_server: LiveApiServer,
) -> None:
    probe_person = _resolve_active_federal_person_for_bioguide_id(federal_connection, _BIOGUIDE_RIGHTS_PROBE_ID)
    person_id = str(probe_person["person_id"])

    response = httpx.get(
        f"{live_api_server.base_url}/v1/person/{person_id}",
        headers=build_public_headers(),
        timeout=10.0,
    )

    assert response.status_code == 200, (
        f"GET /v1/person/{person_id} failed "
        f"bioguide_id={_BIOGUIDE_RIGHTS_PROBE_ID} status={response.status_code} "
        f"body={response.text[:500]} server_stderr={live_api_server.stderr_tail()}"
    )
    payload = response.json()
    portrait = payload.get("portrait")
    assert portrait is not None, (
        f"GET /v1/person/{person_id} returned no portrait bioguide_id={_BIOGUIDE_RIGHTS_PROBE_ID}"
    )
    bio_text = payload.get("bio_text")
    assert isinstance(bio_text, str) and bio_text.strip(), (
        f"GET /v1/person/{person_id} did not surface nonblank biography data "
        f"person_id={person_id} bioguide_id={_BIOGUIDE_RIGHTS_PROBE_ID} "
        f"canonical_name={probe_person['canonical_name']} bio_source_url={payload.get('bio_source_url')}"
    )
    assert portrait.get("rights_status") == "public_domain", (
        "Bioguide-backed portrait did not surface reusable public_domain rights "
        f"person_id={person_id} bioguide_id={_BIOGUIDE_RIGHTS_PROBE_ID} "
        f"rights_status={portrait.get('rights_status')} source_image_url={portrait.get('source_image_url')}"
    )
