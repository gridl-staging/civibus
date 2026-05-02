from __future__ import annotations

import json
import subprocess
from datetime import date
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest

from core.db import insert_organization
from core.types.python.models import Organization
from domains.campaign_finance.jurisdictions.states.NC.scraper.committee_candidacy_match import (
    run_name_match_pass,
)
from domains.campaign_finance.jurisdictions.states.NC.scraper.load import (
    ensure_nc_committee_document_data_source,
)
from domains.civics.scripts.candidacy_committee_coverage_probe import (
    build_coverage_payload,
    compute_nc_committee_coverage,
    write_coverage_artifact,
)

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
    office_level: str,
    office_state: str,
    name_on_ballot: str,
) -> UUID:
    office_row = conn.execute(
        """
        INSERT INTO civic.office (name, office_level, state)
        VALUES (%s, %s, %s)
        RETURNING id
        """,
        (f"{office_name} {uuid4().hex}", office_level, office_state),
    ).fetchone()
    assert office_row is not None
    office_id = office_row[0]

    contest_row = conn.execute(
        """
        INSERT INTO civic.contest (name, election_date, election_type, office_id)
        VALUES (%s, %s, %s, %s)
        RETURNING id
        """,
        (f"{office_name} 2026 General {uuid4().hex}", date(2026, 11, 3), "general", office_id),
    ).fetchone()
    assert contest_row is not None
    contest_id = contest_row[0]

    person_id = _insert_person(conn, canonical_name=person_name)
    candidacy_row = conn.execute(
        """
        INSERT INTO civic.candidacy (person_id, contest_id, name_on_ballot)
        VALUES (%s, %s, %s)
        RETURNING id
        """,
        (person_id, contest_id, name_on_ballot),
    ).fetchone()
    assert candidacy_row is not None
    return candidacy_row[0]


def _seed_nc_coverage_fixture(conn: psycopg.Connection) -> None:
    data_source_id = ensure_nc_committee_document_data_source(conn)

    registry_rows = [
        ("STA-MATCH-C-001", "ALICE A ADAMS"),
        ("STA-MATCH-C-002", "CAROL C CLARK"),
        ("STA-MATCH-C-003", "ELLE E EVANS"),
        ("STA-AMBIG-C-001", "BOB B BROWN"),
        ("STA-AMBIG-C-002", "BOB B BROWN"),
    ]
    for sboe_id, _ in registry_rows:
        insert_organization(
            conn,
            Organization(
                canonical_name=f"Org {sboe_id}",
                identifiers={"nc_sboe_id": sboe_id},
            ),
        )
    for sboe_id, candidate_name in registry_rows:
        _insert_nc_registry_row(
            conn,
            data_source_id=data_source_id,
            sboe_id=sboe_id,
            candidate_name=candidate_name,
        )

    _seed_candidacy(
        conn,
        person_name="Alice Adams",
        office_name="NC House 1",
        office_level="state",
        office_state="NC",
        name_on_ballot="  ALICE   A   ADAMS ",
    )
    _seed_candidacy(
        conn,
        person_name="Carol Clark",
        office_name="NC House 2",
        office_level="state",
        office_state="NC",
        name_on_ballot="CAROL C CLARK",
    )
    _seed_candidacy(
        conn,
        person_name="Elle Evans",
        office_name="Wake County Sheriff",
        office_level="county",
        office_state="NC",
        name_on_ballot="ELLE E EVANS",
    )
    _seed_candidacy(
        conn,
        person_name="Bob Brown",
        office_name="Mecklenburg Sheriff",
        office_level="county",
        office_state="NC",
        name_on_ballot="BOB B BROWN",
    )
    _seed_candidacy(
        conn,
        person_name="Nora NoMatch",
        office_name="NC House 3",
        office_level="state",
        office_state="NC",
        name_on_ballot="NORA NO MATCH",
    )

    updated_count = run_name_match_pass(conn)
    assert updated_count == 3


def _snapshot_candidacy_state(conn: psycopg.Connection) -> tuple[int, str | None, list[tuple[UUID, UUID | None]]]:
    count_row = conn.execute(
        """
        SELECT COUNT(*), MAX(ca.updated_at)
        FROM civic.candidacy ca
        JOIN civic.contest ct ON ct.id = ca.contest_id
        JOIN civic.office ofc ON ofc.id = ct.office_id
        WHERE ofc.state = 'NC'
        """
    ).fetchone()
    assert count_row is not None

    pair_rows = conn.execute(
        """
        SELECT ca.id, ca.committee_id
        FROM civic.candidacy ca
        JOIN civic.contest ct ON ct.id = ca.contest_id
        JOIN civic.office ofc ON ofc.id = ct.office_id
        WHERE ofc.state = 'NC'
        ORDER BY ca.id
        """
    ).fetchall()
    return int(count_row[0]), count_row[1].isoformat() if count_row[1] is not None else None, list(pair_rows)


class TestNcCandidacyCommitteeCoverageProbe:
    def test_probe_reports_expected_exact_counts(self, db_conn: psycopg.Connection) -> None:
        _seed_nc_coverage_fixture(db_conn)

        coverage = compute_nc_committee_coverage(db_conn)
        payload = build_coverage_payload(coverage)

        assert payload["total_nc_candidacies"] == 5
        assert payload["linked_to_committee"] == 3
        assert payload["pct_linked"] == pytest.approx(0.6, abs=1e-9)
        assert payload["ambiguous_unlinked"] == 1
        assert payload["no_match_unlinked"] == 1

        by_level = payload["linked_pct_by_office_level"]
        assert set(by_level.keys()) == {"state", "county"}
        assert by_level["state"]["total"] == 3
        assert by_level["state"]["linked"] == 2
        assert by_level["state"]["pct_linked"] == pytest.approx(2 / 3, abs=1e-9)
        assert by_level["county"]["total"] == 2
        assert by_level["county"]["linked"] == 1
        assert by_level["county"]["pct_linked"] == pytest.approx(0.5, abs=1e-9)

    def test_probe_is_read_only_for_candidacy_rows(self, db_conn: psycopg.Connection) -> None:
        _seed_nc_coverage_fixture(db_conn)

        before = _snapshot_candidacy_state(db_conn)
        _ = build_coverage_payload(compute_nc_committee_coverage(db_conn))
        after = _snapshot_candidacy_state(db_conn)

        assert after == before


class TestArtifactAndCli:
    def test_write_coverage_artifact_round_trip_and_trailing_newline(self, tmp_path: Path) -> None:
        payload = {
            "schema_version": 1,
            "scope": "stage_05_nc_candidacy_committee_coverage",
            "total_nc_candidacies": 5,
            "linked_to_committee": 3,
            "pct_linked": 0.6,
            "ambiguous_unlinked": 1,
            "no_match_unlinked": 1,
            "linked_pct_by_office_level": {
                "state": {"total": 3, "linked": 2, "pct_linked": 2 / 3},
            },
            "unresolved_name_sample": ["BOB B BROWN", "NORA NO MATCH"],
            "prerequisite_metadata": {
                "required_candidacy_columns": ["name_on_ballot", "committee_id"],
                "present_candidacy_columns": ["name_on_ballot", "committee_id"],
            },
        }
        artifact_path = tmp_path / "nested" / "out" / "d3_committee_coverage.json"

        write_coverage_artifact(payload, artifact_path=artifact_path)

        assert artifact_path.parent.exists()
        raw_text = artifact_path.read_text(encoding="utf-8")
        assert raw_text.endswith("\n")
        assert json.loads(raw_text) == payload

    def test_cli_writes_requested_output_file(self, db_conn: psycopg.Connection, tmp_path: Path) -> None:
        _seed_nc_coverage_fixture(db_conn)

        artifact_path = tmp_path / "cli" / "d3_committee_coverage.json"
        result = subprocess.run(
            [
                "uv",
                "run",
                "python",
                "-m",
                "domains.civics.scripts.candidacy_committee_coverage_probe",
                "--output",
                str(artifact_path),
            ],
            check=False,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, result.stderr
        assert artifact_path.exists()
