from __future__ import annotations

import psycopg
import pytest
from psycopg.rows import dict_row

from domains.campaign_finance.ingest.loader import ensure_fec_data_source, load_contribution
from test_support.fec_fixtures import clone_with_unique_sub_id, load_fixture_results

pytestmark = pytest.mark.integration


def _load_all_fixture_contributions(conn: psycopg.Connection) -> None:
    data_source_id = ensure_fec_data_source(conn)
    for record in load_fixture_results():
        cloned = clone_with_unique_sub_id(record)
        load_contribution(conn, data_source_id, cloned)


class TestDurhamDonorsOverThreshold:
    def test_returns_durham_donors_with_amount_above_10(self, db_conn):
        _load_all_fixture_contributions(db_conn)

        with db_conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT p.canonical_name,
                       (sr.raw_fields->>'contribution_receipt_amount')::numeric AS amount
                FROM core.person p
                JOIN core.entity_source es
                    ON es.entity_type = 'person' AND es.entity_id = p.id
                JOIN core.source_record sr
                    ON sr.id = es.source_record_id
                WHERE (sr.raw_fields->>'contributor_city') = 'DURHAM'
                  AND (sr.raw_fields->>'contribution_receipt_amount')::numeric > 10
                """
            )
            rows = cur.fetchall()

        assert len(rows) >= 1
        for row in rows:
            assert row["amount"] > 10


class TestProvenanceChain:
    def test_person_to_data_source_chain(self, db_conn):
        records = load_fixture_results()
        # Pick first IND record (has a person)
        ind_record = next(r for r in records if r.get("entity_type") == "IND")
        contribution = clone_with_unique_sub_id(ind_record)
        sub_id = contribution["sub_id"]

        data_source_id = ensure_fec_data_source(db_conn)
        load_contribution(db_conn, data_source_id, contribution)

        with db_conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT p.canonical_name,
                       ds.name AS data_source_name,
                       sr.raw_fields->>'sub_id' AS raw_sub_id
                FROM core.person p
                JOIN core.entity_source es
                    ON es.entity_type = 'person' AND es.entity_id = p.id
                JOIN core.source_record sr
                    ON sr.id = es.source_record_id
                JOIN core.data_source ds
                    ON ds.id = sr.data_source_id
                WHERE sr.source_record_key = %s
                """,
                (sub_id,),
            )
            row = cur.fetchone()

        assert row is not None
        assert row["data_source_name"] == "FEC Schedule A API"
        assert row["raw_sub_id"] == sub_id
