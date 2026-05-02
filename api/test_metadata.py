from __future__ import annotations

from decimal import Decimal
from datetime import datetime, timezone
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from api.test_campaign_finance_support import (
    CommitteeRowSeed,
    FilingRowSeed,
    TransactionRowSeed,
    insert_committee_row,
    insert_data_source_for_test,
    insert_filing_row,
    insert_source_record_for_test,
    insert_transaction_row,
)
from core.db import insert_entity_source

pytestmark = pytest.mark.integration


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


class TestMetadataEndpoints:
    # No existing runtime-only owner fits both endpoint contracts:
    # - api/queries/campaign_finance.py coverage logic depends on file registry loaders.
    # - api/queries/civics.py has no source-registry query surface.
    # Stage 1 therefore adds dedicated metadata owners.
    def test_data_sources_returns_one_row_per_seeded_source_and_prefers_latest_active_record(
        self,
        api_client: TestClient,
        db_conn: psycopg.Connection,
    ) -> None:
        jurisdiction_alpha = f"test/metadata-{uuid4()}/alpha"
        jurisdiction_beta = f"test/metadata-{uuid4()}/beta"
        data_source_alpha = insert_data_source_for_test(
            db_conn,
            jurisdiction=jurisdiction_alpha,
            name_suffix=f"alpha-{uuid4()}",
        )
        data_source_beta = insert_data_source_for_test(
            db_conn,
            jurisdiction=jurisdiction_beta,
            name_suffix=f"beta-{uuid4()}",
        )

        alpha_latest_active = insert_source_record_for_test(
            db_conn,
            source_record_id=UUID("20000000-0000-0000-0000-000000000001"),
            data_source_id=data_source_alpha.id,
            source_record_key="alpha-active-latest",
            source_url="https://example.org/alpha-active-latest",
            pull_date=datetime(2026, 4, 10, 12, 0, tzinfo=timezone.utc),
        )
        insert_source_record_for_test(
            db_conn,
            source_record_id=UUID("20000000-0000-0000-0000-000000000002"),
            data_source_id=data_source_alpha.id,
            source_record_key="alpha-active-older",
            source_url="https://example.org/alpha-active-older",
            pull_date=datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc),
        )
        insert_source_record_for_test(
            db_conn,
            source_record_id=UUID("20000000-0000-0000-0000-000000000003"),
            data_source_id=data_source_alpha.id,
            source_record_key="alpha-superseded-newest",
            source_url="https://example.org/alpha-superseded-newest",
            pull_date=datetime(2026, 4, 20, 12, 0, tzinfo=timezone.utc),
            superseded_by=alpha_latest_active.id,
        )
        beta_active = insert_source_record_for_test(
            db_conn,
            source_record_id=UUID("20000000-0000-0000-0000-000000000004"),
            data_source_id=data_source_beta.id,
            source_record_key="beta-active",
            source_url="https://example.org/beta-active",
            pull_date=datetime(2026, 4, 11, 8, 30, tzinfo=timezone.utc),
        )

        response = api_client.get("/v1/data-sources")

        assert response.status_code == 200
        payload = response.json()
        seeded_rows = [
            row
            for row in payload
            if row["data_source_id"] in {str(data_source_alpha.id), str(data_source_beta.id)}
        ]
        assert len(seeded_rows) == 2

        by_source_id = {row["data_source_id"]: row for row in seeded_rows}
        alpha_payload = by_source_id[str(data_source_alpha.id)]
        beta_payload = by_source_id[str(data_source_beta.id)]

        assert alpha_payload["domain"] == "campaign_finance"
        assert alpha_payload["jurisdiction"] == jurisdiction_alpha
        assert alpha_payload["latest_source_record_id"] == str(alpha_latest_active.id)
        assert alpha_payload["latest_source_record_key"] == "alpha-active-latest"
        assert alpha_payload["latest_source_record_url"] == "https://example.org/alpha-active-latest"
        assert _parse_iso_datetime(alpha_payload["latest_source_pull_date"]) == alpha_latest_active.pull_date

        assert beta_payload["domain"] == "campaign_finance"
        assert beta_payload["jurisdiction"] == jurisdiction_beta
        assert beta_payload["latest_source_record_id"] == str(beta_active.id)
        assert beta_payload["latest_source_record_key"] == "beta-active"
        assert beta_payload["latest_source_record_url"] == "https://example.org/beta-active"
        assert _parse_iso_datetime(beta_payload["latest_source_pull_date"]) == beta_active.pull_date

    def test_coverage_registry_aggregates_runtime_rows_by_domain_and_jurisdiction(
        self,
        api_client: TestClient,
        db_conn: psycopg.Connection,
    ) -> None:
        shared_jurisdiction = f"test/coverage-{uuid4()}"
        alternate_jurisdiction = f"test/coverage-{uuid4()}"
        uningested_jurisdiction = f"test/coverage-{uuid4()}"

        source_one = insert_data_source_for_test(
            db_conn,
            jurisdiction=shared_jurisdiction,
            name_suffix=f"shared-a-{uuid4()}",
        )
        source_two = insert_data_source_for_test(
            db_conn,
            jurisdiction=shared_jurisdiction,
            name_suffix=f"shared-b-{uuid4()}",
        )
        source_three = insert_data_source_for_test(
            db_conn,
            jurisdiction=alternate_jurisdiction,
            name_suffix=f"alternate-{uuid4()}",
        )
        insert_data_source_for_test(
            db_conn,
            jurisdiction=uningested_jurisdiction,
            name_suffix=f"no-records-{uuid4()}",
        )

        insert_source_record_for_test(
            db_conn,
            source_record_id=UUID("30000000-0000-0000-0000-000000000001"),
            data_source_id=source_one.id,
            source_record_key="shared-a-current",
            source_url="https://example.org/shared-a-current",
            pull_date=datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc),
        )
        insert_source_record_for_test(
            db_conn,
            source_record_id=UUID("30000000-0000-0000-0000-000000000002"),
            data_source_id=source_two.id,
            source_record_key="shared-b-current",
            source_url="https://example.org/shared-b-current",
            pull_date=datetime(2026, 4, 12, 12, 0, tzinfo=timezone.utc),
        )
        insert_source_record_for_test(
            db_conn,
            source_record_id=UUID("30000000-0000-0000-0000-000000000003"),
            data_source_id=source_three.id,
            source_record_key="alternate-current",
            source_url="https://example.org/alternate-current",
            pull_date=datetime(2026, 4, 8, 6, 0, tzinfo=timezone.utc),
        )
        insert_entity_source(db_conn, "person", uuid4(), UUID("30000000-0000-0000-0000-000000000001"), "donor")
        insert_entity_source(db_conn, "person", uuid4(), UUID("30000000-0000-0000-0000-000000000002"), "donor")
        insert_entity_source(db_conn, "person", uuid4(), UUID("30000000-0000-0000-0000-000000000003"), "donor")

        response = api_client.get("/v1/coverage/registry")

        assert response.status_code == 200
        payload = response.json()
        by_jurisdiction = {
            row["jurisdiction"]: row
            for row in payload
            if row["jurisdiction"] in {shared_jurisdiction, alternate_jurisdiction, uningested_jurisdiction}
        }
        assert set(by_jurisdiction) == {shared_jurisdiction, alternate_jurisdiction}

        shared_payload = by_jurisdiction[shared_jurisdiction]
        assert shared_payload["domain"] == "campaign_finance"
        assert shared_payload["data_source_count"] == 2
        assert _parse_iso_datetime(shared_payload["latest_source_pull_date"]) == datetime(
            2026,
            4,
            12,
            12,
            0,
            tzinfo=timezone.utc,
        )

        alternate_payload = by_jurisdiction[alternate_jurisdiction]
        assert alternate_payload["domain"] == "campaign_finance"
        assert alternate_payload["data_source_count"] == 1
        assert _parse_iso_datetime(alternate_payload["latest_source_pull_date"]) == datetime(
            2026,
            4,
            8,
            6,
            0,
            tzinfo=timezone.utc,
        )

    def test_coverage_registry_ignores_superseded_records_for_latest_source_pull_date(
        self,
        api_client: TestClient,
        db_conn: psycopg.Connection,
    ) -> None:
        jurisdiction = f"test/coverage-superseded-{uuid4()}"
        source = insert_data_source_for_test(
            db_conn,
            jurisdiction=jurisdiction,
            name_suffix=f"superseded-{uuid4()}",
        )
        active_record = insert_source_record_for_test(
            db_conn,
            source_record_id=UUID("40000000-0000-0000-0000-000000000001"),
            data_source_id=source.id,
            source_record_key="active-current",
            source_url="https://example.org/active-current",
            pull_date=datetime(2026, 4, 10, 9, 0, tzinfo=timezone.utc),
        )
        insert_source_record_for_test(
            db_conn,
            source_record_id=UUID("40000000-0000-0000-0000-000000000002"),
            data_source_id=source.id,
            source_record_key="superseded-newer",
            source_url="https://example.org/superseded-newer",
            pull_date=datetime(2026, 4, 20, 9, 0, tzinfo=timezone.utc),
            superseded_by=active_record.id,
        )
        insert_entity_source(db_conn, "person", uuid4(), active_record.id, "donor")

        response = api_client.get("/v1/coverage/registry")

        assert response.status_code == 200
        payload = response.json()
        seeded_row = next(row for row in payload if row["jurisdiction"] == jurisdiction)
        assert _parse_iso_datetime(seeded_row["latest_source_pull_date"]) == active_record.pull_date

    def test_coverage_registry_excludes_source_records_without_runtime_fact_evidence(
        self,
        api_client: TestClient,
        db_conn: psycopg.Connection,
    ) -> None:
        covered_jurisdiction = f"test/coverage-facts-{uuid4()}"
        uncovered_jurisdiction = f"test/coverage-no-facts-{uuid4()}"

        covered_source = insert_data_source_for_test(
            db_conn,
            jurisdiction=covered_jurisdiction,
            name_suffix=f"covered-{uuid4()}",
        )
        uncovered_source = insert_data_source_for_test(
            db_conn,
            jurisdiction=uncovered_jurisdiction,
            name_suffix=f"uncovered-{uuid4()}",
        )

        covered_record = insert_source_record_for_test(
            db_conn,
            source_record_id=UUID("50000000-0000-0000-0000-000000000001"),
            data_source_id=covered_source.id,
            source_record_key="covered-active",
            source_url="https://example.org/covered-active",
            pull_date=datetime(2026, 4, 13, 10, 0, tzinfo=timezone.utc),
        )
        insert_source_record_for_test(
            db_conn,
            source_record_id=UUID("50000000-0000-0000-0000-000000000002"),
            data_source_id=uncovered_source.id,
            source_record_key="uncovered-active",
            source_url="https://example.org/uncovered-active",
            pull_date=datetime(2026, 4, 14, 10, 0, tzinfo=timezone.utc),
        )
        insert_entity_source(
            db_conn,
            "person",
            uuid4(),
            covered_record.id,
            "donor",
        )

        response = api_client.get("/v1/coverage/registry")

        assert response.status_code == 200
        payload = response.json()
        by_jurisdiction = {
            row["jurisdiction"]: row
            for row in payload
            if row["jurisdiction"] in {covered_jurisdiction, uncovered_jurisdiction}
        }
        assert set(by_jurisdiction) == {covered_jurisdiction}

    def test_coverage_registry_includes_transaction_only_runtime_fact_evidence(
        self,
        api_client: TestClient,
        db_conn: psycopg.Connection,
    ) -> None:
        transaction_only_jurisdiction = f"test/coverage-transaction-only-{uuid4()}"
        source = insert_data_source_for_test(
            db_conn,
            jurisdiction=transaction_only_jurisdiction,
            name_suffix=f"transaction-only-{uuid4()}",
        )
        source_record = insert_source_record_for_test(
            db_conn,
            source_record_id=UUID("60000000-0000-0000-0000-000000000001"),
            data_source_id=source.id,
            source_record_key="transaction-only-active",
            source_url="https://example.org/transaction-only-active",
            pull_date=datetime(2026, 4, 15, 10, 0, tzinfo=timezone.utc),
        )

        committee_id = UUID("60000000-0000-0000-0000-000000000101")
        filing_id = UUID("60000000-0000-0000-0000-000000000102")
        transaction_id = UUID("60000000-0000-0000-0000-000000000103")
        insert_committee_row(
            db_conn,
            CommitteeRowSeed(
                id=committee_id,
                fec_committee_id="C12345678",
                name="Transaction Evidence Committee",
                state="CA",
            ),
        )
        insert_filing_row(
            db_conn,
            FilingRowSeed(
                id=filing_id,
                filing_fec_id=f"trx-filing-{uuid4().hex[:8]}",
                committee_id=committee_id,
            ),
        )
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT source_record_id FROM cf.filing WHERE id = %s",
                (filing_id,),
            )
            filing_source_record_id = cur.fetchone()
        assert filing_source_record_id is not None
        assert filing_source_record_id[0] is None
        insert_transaction_row(
            db_conn,
            TransactionRowSeed(
                id=transaction_id,
                filing_id=filing_id,
                committee_id=committee_id,
                transaction_type="contribution",
                amount=Decimal("25.00"),
                amendment_indicator="N",
                source_record_id=source_record.id,
                transaction_identifier=f"trx-{uuid4().hex[:8]}",
            ),
        )

        response = api_client.get("/v1/coverage/registry")

        assert response.status_code == 200
        payload = response.json()
        by_jurisdiction = {
            row["jurisdiction"]: row
            for row in payload
            if row["jurisdiction"] == transaction_only_jurisdiction
        }
        assert set(by_jurisdiction) == {transaction_only_jurisdiction}
        assert by_jurisdiction[transaction_only_jurisdiction]["data_source_count"] == 1

    def test_coverage_registry_counts_runtime_evidence_from_non_latest_active_record(
        self,
        api_client: TestClient,
        db_conn: psycopg.Connection,
    ) -> None:
        jurisdiction = f"test/coverage-active-evidence-{uuid4()}"
        source = insert_data_source_for_test(
            db_conn,
            jurisdiction=jurisdiction,
            name_suffix=f"active-evidence-{uuid4()}",
        )
        evidenced_active_record = insert_source_record_for_test(
            db_conn,
            source_record_id=UUID("70000000-0000-0000-0000-000000000001"),
            data_source_id=source.id,
            source_record_key=None,
            source_url="https://example.org/active-evidenced",
            pull_date=datetime(2026, 4, 5, 10, 0, tzinfo=timezone.utc),
        )
        insert_source_record_for_test(
            db_conn,
            source_record_id=UUID("70000000-0000-0000-0000-000000000002"),
            data_source_id=source.id,
            source_record_key=None,
            source_url="https://example.org/active-not-evidenced-newer",
            pull_date=datetime(2026, 4, 18, 10, 0, tzinfo=timezone.utc),
        )
        insert_entity_source(db_conn, "person", uuid4(), evidenced_active_record.id, "donor")

        response = api_client.get("/v1/coverage/registry")

        assert response.status_code == 200
        payload = response.json()
        seeded_row = next(row for row in payload if row["jurisdiction"] == jurisdiction)
        assert seeded_row["data_source_count"] == 1
        assert _parse_iso_datetime(seeded_row["latest_source_pull_date"]) == evidenced_active_record.pull_date
