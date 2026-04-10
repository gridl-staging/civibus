from __future__ import annotations

from pathlib import Path

import psycopg
import pytest
from psycopg.rows import dict_row

from domains.campaign_finance.jurisdictions.states.CO.scraper.load import (
    ensure_co_data_source,
    load_co_contributions,
    load_co_expenditures,
)

_SAMPLE_CONTRIBUTIONS_PATH = Path(__file__).parent / "test_fixtures" / "sample_contributions.csv"
_SAMPLE_EXPENDITURES_PATH = Path(__file__).parent / "test_fixtures" / "sample_expenditures.csv"

pytestmark = pytest.mark.integration


def test_load_co_fixture_verifies_stage5_end_to_end_requirements(db_conn: psycopg.Connection) -> None:
    data_source_id = ensure_co_data_source(db_conn)
    result = load_co_contributions(db_conn, _SAMPLE_CONTRIBUTIONS_PATH, data_source_id=data_source_id)
    assert result.inserted + result.skipped + result.errors == 10

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT DISTINCT person.canonical_name
            FROM core.person AS person
            JOIN core.entity_source AS entity_source
              ON entity_source.entity_id = person.id
             AND entity_source.entity_type = 'person'
            JOIN core.source_record AS source_record
              ON source_record.id = entity_source.source_record_id
            WHERE source_record.data_source_id = %s
              AND person.canonical_name IN ('Jane Doe', 'Pat Q Johnson Jr')
            """,
            (data_source_id,),
        )
        donor_names = {row["canonical_name"] for row in cursor.fetchall()}

        cursor.execute(
            """
            SELECT data_source.domain, data_source.jurisdiction
            FROM core.person AS person
            JOIN core.entity_source AS entity_source
              ON entity_source.entity_id = person.id
             AND entity_source.entity_type = 'person'
            JOIN core.source_record AS source_record
              ON source_record.id = entity_source.source_record_id
            JOIN core.data_source AS data_source
              ON data_source.id = source_record.data_source_id
            WHERE person.canonical_name = 'Jane Doe'
              AND source_record.data_source_id = %s
            LIMIT 1
            """,
            (data_source_id,),
        )
        provenance_row = cursor.fetchone()

        cursor.execute(
            """
            SELECT source_record.raw_fields ->> 'Amended' AS amended
            FROM core.source_record AS source_record
            WHERE source_record.data_source_id = %s
              AND source_record.source_record_key = '1004'
            LIMIT 1
            """,
            (data_source_id,),
        )
        superseded_row = cursor.fetchone()

        cursor.execute(
            """
            SELECT person.identifiers ->> 'llc_name' AS llc_name
            FROM core.person AS person
            JOIN core.entity_source AS entity_source
              ON entity_source.entity_id = person.id
             AND entity_source.entity_type = 'person'
             AND entity_source.extraction_role = 'donor'
            JOIN core.source_record AS source_record
              ON source_record.id = entity_source.source_record_id
            WHERE source_record.data_source_id = %s
              AND source_record.source_record_key = '1003'
            LIMIT 1
            """,
            (data_source_id,),
        )
        llc_identifier_row = cursor.fetchone()

        cursor.execute(
            """
            SELECT organization.identifiers ->> 'co_committee_id' AS co_committee_id
            FROM core.organization AS organization
            JOIN core.entity_source AS entity_source
              ON entity_source.entity_id = organization.id
             AND entity_source.entity_type = 'organization'
             AND entity_source.extraction_role = 'recipient'
            JOIN core.source_record AS source_record
              ON source_record.id = entity_source.source_record_id
            WHERE source_record.data_source_id = %s
              AND source_record.source_record_key = '1001'
              AND organization.canonical_name = 'Friends of Example'
            LIMIT 1
            """,
            (data_source_id,),
        )
        committee_row = cursor.fetchone()

    assert donor_names == {"Jane Doe", "Pat Q Johnson Jr"}
    assert provenance_row is not None
    assert provenance_row["domain"] == "campaign_finance"
    assert provenance_row["jurisdiction"] == "state/CO"
    assert superseded_row is not None
    assert superseded_row["amended"] == "Y"
    assert llc_identifier_row is not None
    assert llc_identifier_row["llc_name"] == "HOWES WOLF LLC"
    assert committee_row is not None
    assert committee_row["co_committee_id"] == "20155000001"


def test_load_co_expenditure_fixture_verifies_stage6_end_to_end_requirements(
    db_conn: psycopg.Connection,
) -> None:
    data_source_id = ensure_co_data_source(db_conn, data_type="expenditures")
    result = load_co_expenditures(db_conn, _SAMPLE_EXPENDITURES_PATH, data_source_id=data_source_id)
    assert result.inserted + result.skipped + result.errors == 5

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT DISTINCT person.canonical_name
            FROM core.person AS person
            JOIN core.entity_source AS entity_source
              ON entity_source.entity_id = person.id
             AND entity_source.entity_type = 'person'
             AND entity_source.extraction_role = 'payee'
            JOIN core.source_record AS source_record
              ON source_record.id = entity_source.source_record_id
            WHERE source_record.data_source_id = %s
              AND person.canonical_name IN ('Elena Garcia', 'Kim Nguyen')
            """,
            (data_source_id,),
        )
        payee_names = {row["canonical_name"] for row in cursor.fetchall()}

        cursor.execute(
            """
            SELECT DISTINCT organization.canonical_name
            FROM core.organization AS organization
            JOIN core.entity_source AS entity_source
              ON entity_source.entity_id = organization.id
             AND entity_source.entity_type = 'organization'
             AND entity_source.extraction_role = 'payee'
            JOIN core.source_record AS source_record
              ON source_record.id = entity_source.source_record_id
            WHERE source_record.data_source_id = %s
              AND organization.canonical_name = 'ACME PRINTING LLC'
            """,
            (data_source_id,),
        )
        payee_organizations = {row["canonical_name"] for row in cursor.fetchall()}

        cursor.execute(
            """
            SELECT data_source.name
            FROM core.entity_source AS entity_source
            JOIN core.source_record AS source_record
              ON source_record.id = entity_source.source_record_id
            JOIN core.data_source AS data_source
              ON data_source.id = source_record.data_source_id
            WHERE entity_source.extraction_role = 'payee'
              AND source_record.data_source_id = %s
            LIMIT 1
            """,
            (data_source_id,),
        )
        provenance_row = cursor.fetchone()

    assert payee_names == {"Elena Garcia", "Kim Nguyen"}
    assert payee_organizations == {"ACME PRINTING LLC"}
    assert provenance_row is not None
    assert provenance_row["name"] == "TRACER Bulk Download — Expenditures"


def test_contribution_and_expenditure_loads_use_distinct_data_sources_and_roles(
    db_conn: psycopg.Connection,
) -> None:
    contribution_source_id = ensure_co_data_source(db_conn, data_type="contributions")
    expenditure_source_id = ensure_co_data_source(db_conn, data_type="expenditures")
    assert contribution_source_id != expenditure_source_id

    contribution_result = load_co_contributions(
        db_conn,
        _SAMPLE_CONTRIBUTIONS_PATH,
        data_source_id=contribution_source_id,
    )
    expenditure_result = load_co_expenditures(
        db_conn,
        _SAMPLE_EXPENDITURES_PATH,
        data_source_id=expenditure_source_id,
    )

    assert contribution_result.inserted + contribution_result.skipped + contribution_result.errors == 10
    assert expenditure_result.inserted + expenditure_result.skipped + expenditure_result.errors == 5

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT extraction_role, COUNT(*) AS count
            FROM core.entity_source AS entity_source
            JOIN core.source_record AS source_record
              ON source_record.id = entity_source.source_record_id
            WHERE source_record.data_source_id = %s
            GROUP BY extraction_role
            """,
            (contribution_source_id,),
        )
        contribution_roles = {row["extraction_role"]: row["count"] for row in cursor.fetchall()}

        cursor.execute(
            """
            SELECT extraction_role, COUNT(*) AS count
            FROM core.entity_source AS entity_source
            JOIN core.source_record AS source_record
              ON source_record.id = entity_source.source_record_id
            WHERE source_record.data_source_id = %s
            GROUP BY extraction_role
            """,
            (expenditure_source_id,),
        )
        expenditure_roles = {row["extraction_role"]: row["count"] for row in cursor.fetchall()}

    assert contribution_roles.get("donor", 0) > 0
    assert contribution_roles.get("recipient", 0) > 0
    assert contribution_roles.get("payee", 0) == 0
    assert contribution_roles.get("payer", 0) == 0

    assert expenditure_roles.get("payee", 0) > 0
    assert expenditure_roles.get("payer", 0) > 0
    assert expenditure_roles.get("donor", 0) == 0
    assert expenditure_roles.get("recipient", 0) == 0
