from __future__ import annotations

from datetime import date
from uuid import UUID, uuid4

import psycopg
import pytest

from core.db import insert_organization
from core.types.python.models import Organization
from domains.campaign_finance.ingest.filing_loader import generate_synthetic_committee_id
from domains.campaign_finance.jurisdictions.states.NC.scraper.load import (
    ensure_nc_committee_document_data_source,
)
from domains.campaign_finance.jurisdictions.states.NC.scraper.committee_candidacy_match import (
    run_name_match_pass,
)
from domains.civics.ingest import upsert_candidacy, upsert_contest, upsert_office
from domains.civics.types import Candidacy, Contest, Office

pytestmark = pytest.mark.integration


def _insert_person(conn: psycopg.Connection, *, canonical_name: str) -> UUID:
    row = conn.execute(
        """
        INSERT INTO core.person (canonical_name)
        VALUES (%s)
        RETURNING id
        """,
        (canonical_name,),
    ).fetchone()
    assert row is not None
    return row[0]


def _insert_nc_registry_row(
    conn: psycopg.Connection,
    *,
    data_source_id: UUID,
    sboe_id: str,
    candidate_name: str,
) -> None:
    conn.execute(
        """
        INSERT INTO cf.nc_committee_registry (
            org_group_id,
            sboe_id,
            committee_name,
            status_desc,
            old_id,
            candidate_name,
            data_source_id,
            first_seen_at,
            last_seen_at
        )
        VALUES (%s, %s, %s, 'ACTIVE (NON-EXEMPT)', NULL, %s, %s, NOW(), NOW())
        """,
        (int(uuid4().int % 900000) + 100000, sboe_id, f"Committee {sboe_id}", candidate_name, data_source_id),
    )


def _seed_candidacy(
    conn: psycopg.Connection,
    *,
    person_name: str,
    office_name: str,
    office_state: str,
    name_on_ballot: str,
) -> UUID:
    office_id = upsert_office(
        conn,
        Office(
            name=office_name,
            office_level="state",
            state=office_state,
        ),
    )
    contest_id = upsert_contest(
        conn,
        Contest(
            name=f"{office_name} 2026 General",
            election_date=date(2026, 11, 3),
            election_type="general",
            office_id=office_id,
        ),
    )
    person_id = _insert_person(conn, canonical_name=person_name)
    candidacy_id = upsert_candidacy(
        conn,
        Candidacy(
            person_id=person_id,
            contest_id=contest_id,
            name_on_ballot=name_on_ballot,
        ),
    )
    return candidacy_id


def test_run_name_match_pass_updates_only_unambiguous_nc_candidacies(db_conn: psycopg.Connection) -> None:
    data_source_id = ensure_nc_committee_document_data_source(db_conn)

    unambiguous_sboe_id = "STA-MATCH-C-001"
    ambiguous_sboe_id_one = "STA-AMBIG-C-001"
    ambiguous_sboe_id_two = "STA-AMBIG-C-002"
    matched_name = "ALICE A ADAMS"
    ambiguous_name = "BOB B BROWN"

    insert_organization(
        db_conn,
        Organization(
            canonical_name=f"Org {unambiguous_sboe_id}",
            identifiers={"nc_sboe_id": unambiguous_sboe_id},
        ),
    )
    insert_organization(
        db_conn,
        Organization(
            canonical_name=f"Org {ambiguous_sboe_id_one}",
            identifiers={"nc_sboe_id": ambiguous_sboe_id_one},
        ),
    )
    insert_organization(
        db_conn,
        Organization(
            canonical_name=f"Org {ambiguous_sboe_id_two}",
            identifiers={"nc_sboe_id": ambiguous_sboe_id_two},
        ),
    )

    _insert_nc_registry_row(
        db_conn,
        data_source_id=data_source_id,
        sboe_id=unambiguous_sboe_id,
        candidate_name=matched_name,
    )
    _insert_nc_registry_row(
        db_conn,
        data_source_id=data_source_id,
        sboe_id=ambiguous_sboe_id_one,
        candidate_name=ambiguous_name,
    )
    _insert_nc_registry_row(
        db_conn,
        data_source_id=data_source_id,
        sboe_id=ambiguous_sboe_id_two,
        candidate_name=ambiguous_name,
    )

    matched_candidacy_id = _seed_candidacy(
        db_conn,
        person_name="Alice Adams",
        office_name="NC House 1",
        office_state="NC",
        name_on_ballot="  ALICE   A   ADAMS  ",
    )
    ambiguous_candidacy_id = _seed_candidacy(
        db_conn,
        person_name="Bob Brown",
        office_name="NC House 2",
        office_state="NC",
        name_on_ballot="BOB B BROWN",
    )
    non_nc_candidacy_id = _seed_candidacy(
        db_conn,
        person_name="Alice Adams SC",
        office_name="SC House 1",
        office_state="SC",
        name_on_ballot="ALICE A ADAMS",
    )

    updated_count = run_name_match_pass(db_conn)
    assert updated_count == 1

    expected_committee_fec_id = generate_synthetic_committee_id("NC", unambiguous_sboe_id)
    expected_committee_row = db_conn.execute(
        "SELECT id FROM cf.committee WHERE fec_committee_id = %s",
        (expected_committee_fec_id,),
    ).fetchone()
    assert expected_committee_row is not None
    expected_committee_id = expected_committee_row[0]

    matched_committee_id = db_conn.execute(
        "SELECT committee_id FROM civic.candidacy WHERE id = %s",
        (matched_candidacy_id,),
    ).fetchone()[0]
    ambiguous_committee_id = db_conn.execute(
        "SELECT committee_id FROM civic.candidacy WHERE id = %s",
        (ambiguous_candidacy_id,),
    ).fetchone()[0]
    non_nc_committee_id = db_conn.execute(
        "SELECT committee_id FROM civic.candidacy WHERE id = %s",
        (non_nc_candidacy_id,),
    ).fetchone()[0]

    assert matched_committee_id == expected_committee_id
    assert ambiguous_committee_id is None
    assert non_nc_committee_id is None

    rerun_updated_count = run_name_match_pass(db_conn)
    assert rerun_updated_count == 0
