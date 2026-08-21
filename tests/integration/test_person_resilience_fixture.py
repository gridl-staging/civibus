"""Person-resilience specimen contract: the poison/restore round-trip (civibus-e7v).

The browser journey web/tests/smoke/person_resilience.spec.ts poisons this
dedicated specimen mid-test and asserts the person page degrades per
docs/reference/screen_specs/person_detail.md (### Error) instead of 500ing.
This DB-backed test pins the mutator's mechanics so the journey's oracle stays
honest:

- the poison is the civibus-ga8 failure class (column-legal ``NaN`` in
  ``cf.candidate.total_receipts``, rejected by the response contract's finite
  ``Decimal``), and it makes ``GET /v1/candidates/{id}/summary`` a 500 while
  ``GET /v1/person/{id}`` stays a valid 200 — a SECTION failure, not a page one;
- the restore returns the exact seeded official total, so the journey's
  follow-up healthy navigation proves restoration rather than absence.

If the API ever grows a defensive branch that serves NaN totals as something
healthy, the poisoned-summary assertion here goes red FIRST — the signal that
the browser journey's failure injection no longer reproduces the diagnosed
class and needs a new seam, instead of silently passing against a healthy page.
"""

from __future__ import annotations

from collections.abc import Iterator

import psycopg
import pytest
from fastapi.testclient import TestClient

from api.deps import get_db
from api.middleware import require_administrative_request, require_authorized_request
from test_support.person_resilience_fixture import (
    SMOKE_RESILIENCE_CANDIDATE_ID,
    SMOKE_RESILIENCE_PERSON_CANONICAL_NAME,
    SMOKE_RESILIENCE_PERSON_ID,
    cleanup_person_resilience_fixture,
    poison_person_resilience_candidate,
    restore_person_resilience_candidate,
    seed_person_resilience_fixture,
)

pytestmark = pytest.mark.integration

_PERSON_PATH = f"/v1/person/{SMOKE_RESILIENCE_PERSON_ID}"
_SUMMARY_PATH = f"/v1/candidates/{SMOKE_RESILIENCE_CANDIDATE_ID}/summary"


@pytest.fixture
def resilience_api_client(db_conn: psycopg.Connection) -> Iterator[TestClient]:
    """A non-raising client over the test transaction: 500s surface as 500s.

    ``raise_server_exceptions=False`` because the poisoned request's WHOLE point
    is the served status code — the same thing uvicorn gives the web tier.
    """
    from api.main import create_app

    app = create_app()

    def _get_db_override() -> Iterator[psycopg.Connection]:
        yield db_conn

    app.dependency_overrides[get_db] = _get_db_override
    app.dependency_overrides[require_administrative_request] = lambda: None
    app.dependency_overrides[require_authorized_request] = lambda: None
    client = TestClient(app, raise_server_exceptions=False)
    try:
        with client:
            yield client
    finally:
        app.dependency_overrides.clear()


def test_poison_fails_the_candidate_summary_section_while_person_payload_stays_valid(
    resilience_api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    seed_person_resilience_fixture(db_conn)

    healthy_person = resilience_api_client.get(_PERSON_PATH)
    assert healthy_person.status_code == 200
    healthy_person_body = healthy_person.json()
    assert healthy_person_body["canonical_name"] == SMOKE_RESILIENCE_PERSON_CANONICAL_NAME
    # Office context must be present: the journey asserts bio/office survive
    # the poisoned window, which is only meaningful if they exist beforehand.
    assert healthy_person_body["current_office"] is not None
    assert healthy_person_body["current_office"]["office_name"] == "Representative"

    healthy_summary = resilience_api_client.get(_SUMMARY_PATH)
    assert healthy_summary.status_code == 200
    healthy_summary_body = healthy_summary.json()
    assert healthy_summary_body["total_raised"] == "400.00"
    assert healthy_summary_body["summary_source"] == "fec_weball"

    poison_person_resilience_candidate(db_conn)

    # The section producer fails (pydantic rejects the non-finite Decimal) …
    poisoned_summary = resilience_api_client.get(_SUMMARY_PATH)
    assert poisoned_summary.status_code == 500
    # … while the core person payload stays a valid 200: a partial backend
    # failure, which the degradation contract says must NOT take the page down.
    poisoned_person = resilience_api_client.get(_PERSON_PATH)
    assert poisoned_person.status_code == 200
    assert poisoned_person.json()["canonical_name"] == SMOKE_RESILIENCE_PERSON_CANONICAL_NAME

    restore_person_resilience_candidate(db_conn)

    restored_summary = resilience_api_client.get(_SUMMARY_PATH)
    assert restored_summary.status_code == 200
    assert restored_summary.json()["total_raised"] == "400.00"


def test_seed_is_idempotent_and_cleanup_removes_every_specimen_row(
    db_conn: psycopg.Connection,
) -> None:
    seed_person_resilience_fixture(db_conn)
    seed_person_resilience_fixture(db_conn)

    person_count = db_conn.execute(
        "SELECT COUNT(*) FROM core.person WHERE id = %s", (SMOKE_RESILIENCE_PERSON_ID,)
    ).fetchone()[0]
    candidate_count = db_conn.execute(
        "SELECT COUNT(*) FROM cf.candidate WHERE id = %s", (SMOKE_RESILIENCE_CANDIDATE_ID,)
    ).fetchone()[0]
    officeholding_count = db_conn.execute(
        "SELECT COUNT(*) FROM civic.officeholding WHERE person_id = %s",
        (SMOKE_RESILIENCE_PERSON_ID,),
    ).fetchone()[0]
    assert (person_count, candidate_count, officeholding_count) == (1, 1, 1)

    cleanup_person_resilience_fixture(db_conn)

    remaining = db_conn.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM core.person WHERE id = %(person_id)s)
          + (SELECT COUNT(*) FROM cf.candidate WHERE id = %(candidate_id)s)
          + (SELECT COUNT(*) FROM civic.officeholding WHERE person_id = %(person_id)s)
        """,
        {
            "person_id": SMOKE_RESILIENCE_PERSON_ID,
            "candidate_id": SMOKE_RESILIENCE_CANDIDATE_ID,
        },
    ).fetchone()[0]
    assert remaining == 0
