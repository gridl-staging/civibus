from __future__ import annotations

from decimal import Decimal
from datetime import datetime, timezone
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from api.queries.civics import fetch_current_federal_members
from api.queries.metadata import (
    _COVERAGE_REGISTRY_SQL,
    _DATA_SOURCES_METADATA_SQL,
    _PUBLIC_FEDERAL_DATA_SOURCES_SQL,
)
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
from core.db import insert_data_source, insert_entity_source
from core.types.python.models import DataSource

pytestmark = pytest.mark.integration


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


def _normalize_sql(sql: str) -> str:
    return " ".join(sql.lower().split())


def _sync_data_source_metadata_for_test(
    db_conn: psycopg.Connection,
    *,
    data_source_id: UUID,
    record_count: int | None,
    last_pull_at: datetime | None,
    last_pull_status: str | None = "success",
) -> None:
    with db_conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE core.data_source
            SET record_count = %s,
                last_pull_at = %s,
                last_pull_status = %s
            WHERE id = %s
            """,
            (record_count, last_pull_at, last_pull_status, data_source_id),
        )


def test_data_sources_metadata_sql_reads_bounded_data_source_snapshot() -> None:
    normalized_sql = _normalize_sql(_DATA_SOURCES_METADATA_SQL)

    assert "from core.data_source ds" in normalized_sql
    assert "core.source_record" not in normalized_sql
    assert "left join lateral" not in normalized_sql


def test_coverage_registry_sql_reads_bounded_data_source_snapshot() -> None:
    normalized_sql = _normalize_sql(_COVERAGE_REGISTRY_SQL)

    assert "from core.data_source ds" in normalized_sql
    assert "coalesce(ds.record_count, 0) > 0" in normalized_sql
    assert "core.source_record" not in normalized_sql
    assert "cf.transaction" not in normalized_sql
    assert "cf.filing" not in normalized_sql


def test_public_federal_data_sources_sql_scopes_to_federal_first_sources() -> None:
    normalized_sql = _normalize_sql(_PUBLIC_FEDERAL_DATA_SOURCES_SQL)

    # Reuses the bounded data_source snapshot — no source_record fan-out.
    assert "from core.data_source ds" in normalized_sql
    assert "core.source_record" not in normalized_sql
    assert "left join lateral" not in normalized_sql
    # Scope: campaign-finance federal/fec plus civics federal/officeholder/%.
    assert "ds.domain = 'campaign_finance'" in normalized_sql
    assert "ds.jurisdiction = 'federal/fec'" in normalized_sql
    assert "ds.domain = 'civics'" in normalized_sql
    assert "ds.jurisdiction like 'federal/officeholder/%'" in normalized_sql


def _insert_civics_officeholder_data_source_for_test(
    db_conn: psycopg.Connection,
    *,
    jurisdiction: str,
    name_suffix: str,
    source_url: str,
) -> DataSource:
    data_source = DataSource(
        domain="civics",
        jurisdiction=jurisdiction,
        name=f"Civics officeholder source {name_suffix}",
        source_url=source_url,
    )
    insert_data_source(db_conn, data_source)
    return data_source


class TestMetadataEndpoints:
    # No existing runtime-only owner fits both endpoint contracts:
    # - api/queries/campaign_finance.py coverage logic depends on file registry loaders.
    # - api/queries/civics.py has no source-registry query surface.
    # Stage 1 therefore adds dedicated metadata owners.
    def test_data_sources_returns_one_row_per_seeded_source_from_data_source_metadata(
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

        alpha_last_pull_at = datetime(2026, 4, 10, 12, 0, tzinfo=timezone.utc)
        beta_last_pull_at = datetime(2026, 4, 11, 8, 30, tzinfo=timezone.utc)
        _sync_data_source_metadata_for_test(
            db_conn,
            data_source_id=data_source_alpha.id,
            record_count=3,
            last_pull_at=alpha_last_pull_at,
        )
        _sync_data_source_metadata_for_test(
            db_conn,
            data_source_id=data_source_beta.id,
            record_count=1,
            last_pull_at=beta_last_pull_at,
        )
        insert_source_record_for_test(
            db_conn,
            source_record_id=UUID("20000000-0000-0000-0000-000000000001"),
            data_source_id=data_source_alpha.id,
            source_record_key="alpha-active-latest",
            source_url="https://example.org/alpha-active-latest",
            pull_date=alpha_last_pull_at,
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
            superseded_by=UUID("20000000-0000-0000-0000-000000000001"),
        )
        insert_source_record_for_test(
            db_conn,
            source_record_id=UUID("20000000-0000-0000-0000-000000000004"),
            data_source_id=data_source_beta.id,
            source_record_key="beta-active",
            source_url="https://example.org/beta-active",
            pull_date=beta_last_pull_at,
        )

        response = api_client.get("/v1/data-sources")

        assert response.status_code == 200
        payload = response.json()
        seeded_rows = [
            row for row in payload if row["data_source_id"] in {str(data_source_alpha.id), str(data_source_beta.id)}
        ]
        assert len(seeded_rows) == 2

        by_source_id = {row["data_source_id"]: row for row in seeded_rows}
        alpha_payload = by_source_id[str(data_source_alpha.id)]
        beta_payload = by_source_id[str(data_source_beta.id)]

        assert alpha_payload["domain"] == "campaign_finance"
        assert alpha_payload["jurisdiction"] == jurisdiction_alpha
        assert alpha_payload["record_count"] == 3
        assert alpha_payload["latest_source_record_id"] is None
        assert alpha_payload["latest_source_record_key"] is None
        assert alpha_payload["latest_source_record_url"] is None
        assert _parse_iso_datetime(alpha_payload["latest_source_pull_date"]) == alpha_last_pull_at

        assert beta_payload["domain"] == "campaign_finance"
        assert beta_payload["jurisdiction"] == jurisdiction_beta
        assert beta_payload["record_count"] == 1
        assert beta_payload["latest_source_record_id"] is None
        assert beta_payload["latest_source_record_key"] is None
        assert beta_payload["latest_source_record_url"] is None
        assert _parse_iso_datetime(beta_payload["latest_source_pull_date"]) == beta_last_pull_at

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
        uningested_source = insert_data_source_for_test(
            db_conn,
            jurisdiction=uningested_jurisdiction,
            name_suffix=f"no-records-{uuid4()}",
        )
        _sync_data_source_metadata_for_test(
            db_conn,
            data_source_id=source_one.id,
            record_count=1,
            last_pull_at=datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc),
        )
        _sync_data_source_metadata_for_test(
            db_conn,
            data_source_id=source_two.id,
            record_count=1,
            last_pull_at=datetime(2026, 4, 12, 12, 0, tzinfo=timezone.utc),
        )
        _sync_data_source_metadata_for_test(
            db_conn,
            data_source_id=source_three.id,
            record_count=1,
            last_pull_at=datetime(2026, 4, 8, 6, 0, tzinfo=timezone.utc),
        )
        _sync_data_source_metadata_for_test(
            db_conn,
            data_source_id=uningested_source.id,
            record_count=0,
            last_pull_at=datetime(2026, 4, 13, 6, 0, tzinfo=timezone.utc),
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
        assert _parse_iso_datetime(shared_payload["latest_data_source_pull_at"]) == datetime(
            2026,
            4,
            12,
            12,
            0,
            tzinfo=timezone.utc,
        )
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
        assert _parse_iso_datetime(alternate_payload["latest_data_source_pull_at"]) == datetime(
            2026,
            4,
            8,
            6,
            0,
            tzinfo=timezone.utc,
        )
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
        _sync_data_source_metadata_for_test(
            db_conn,
            data_source_id=source.id,
            record_count=1,
            last_pull_at=datetime(2026, 4, 10, 9, 0, tzinfo=timezone.utc),
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
        _sync_data_source_metadata_for_test(
            db_conn,
            data_source_id=covered_source.id,
            record_count=1,
            last_pull_at=datetime(2026, 4, 13, 10, 0, tzinfo=timezone.utc),
        )
        _sync_data_source_metadata_for_test(
            db_conn,
            data_source_id=uncovered_source.id,
            record_count=0,
            last_pull_at=datetime(2026, 4, 14, 10, 0, tzinfo=timezone.utc),
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
        _sync_data_source_metadata_for_test(
            db_conn,
            data_source_id=source.id,
            record_count=1,
            last_pull_at=datetime(2026, 4, 15, 10, 0, tzinfo=timezone.utc),
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
            row["jurisdiction"]: row for row in payload if row["jurisdiction"] == transaction_only_jurisdiction
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
        _sync_data_source_metadata_for_test(
            db_conn,
            data_source_id=source.id,
            record_count=2,
            last_pull_at=datetime(2026, 4, 18, 10, 0, tzinfo=timezone.utc),
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
        assert _parse_iso_datetime(seeded_row["latest_source_pull_date"]) == datetime(
            2026,
            4,
            18,
            10,
            0,
            tzinfo=timezone.utc,
        )


class TestPublicFederalMetadata:
    """Assembled ``GET /public/v1/federal/metadata`` contract (Stage 2)."""

    def _seed_federal_and_unrelated_sources(
        self,
        db_conn: psycopg.Connection,
    ) -> dict[str, DataSource]:
        federal_fec = insert_data_source_for_test(
            db_conn,
            jurisdiction="federal/fec",
            name_suffix=f"fec-{uuid4()}",
        )
        _sync_data_source_metadata_for_test(
            db_conn,
            data_source_id=federal_fec.id,
            record_count=42,
            last_pull_at=datetime(2026, 7, 20, 9, 0, tzinfo=timezone.utc),
            last_pull_status="success",
        )
        # A federal source whose freshness is unknown must stay visibly null,
        # never be silently treated as fresh.
        federal_fec_stale = insert_data_source_for_test(
            db_conn,
            jurisdiction="federal/fec",
            name_suffix=f"fec-null-{uuid4()}",
        )
        _sync_data_source_metadata_for_test(
            db_conn,
            data_source_id=federal_fec_stale.id,
            record_count=None,
            last_pull_at=None,
            last_pull_status=None,
        )
        federal_officeholder = _insert_civics_officeholder_data_source_for_test(
            db_conn,
            jurisdiction="federal/officeholder/house",
            name_suffix=f"house-{uuid4()}",
            source_url="https://example.org/civics-officeholder-house",
        )
        _sync_data_source_metadata_for_test(
            db_conn,
            data_source_id=federal_officeholder.id,
            record_count=435,
            last_pull_at=datetime(2026, 7, 21, 6, 30, tzinfo=timezone.utc),
            last_pull_status="success",
        )
        # Unrelated non-federal sources that must be excluded from the payload.
        state_campaign_finance = insert_data_source_for_test(
            db_conn,
            jurisdiction=f"state/co-{uuid4()}",
            name_suffix=f"state-{uuid4()}",
        )
        _sync_data_source_metadata_for_test(
            db_conn,
            data_source_id=state_campaign_finance.id,
            record_count=7,
            last_pull_at=datetime(2026, 7, 19, 9, 0, tzinfo=timezone.utc),
            last_pull_status="success",
        )
        state_officeholder = _insert_civics_officeholder_data_source_for_test(
            db_conn,
            jurisdiction=f"state/ca/officeholder-{uuid4()}",
            name_suffix=f"state-oh-{uuid4()}",
            source_url="https://example.org/civics-officeholder-state",
        )
        _sync_data_source_metadata_for_test(
            db_conn,
            data_source_id=state_officeholder.id,
            record_count=5,
            last_pull_at=datetime(2026, 7, 18, 9, 0, tzinfo=timezone.utc),
            last_pull_status="success",
        )
        return {
            "federal_fec": federal_fec,
            "federal_fec_stale": federal_fec_stale,
            "federal_officeholder": federal_officeholder,
            "state_campaign_finance": state_campaign_finance,
            "state_officeholder": state_officeholder,
        }

    def test_metadata_data_sources_include_only_federal_first_sources(
        self,
        api_client: TestClient,
        db_conn: psycopg.Connection,
    ) -> None:
        seeded = self._seed_federal_and_unrelated_sources(db_conn)

        response = api_client.get("/public/v1/federal/metadata")

        assert response.status_code == 200
        payload = response.json()
        by_source_id = {row["data_source_id"]: row for row in payload["data_sources"]}

        # Every published row is in scope: federal FEC or a federal officeholder source.
        for row in payload["data_sources"]:
            in_scope = (row["domain"] == "campaign_finance" and row["jurisdiction"] == "federal/fec") or (
                row["domain"] == "civics" and row["jurisdiction"].startswith("federal/officeholder/")
            )
            assert in_scope, row

        # Unrelated sources are excluded.
        assert str(seeded["state_campaign_finance"].id) not in by_source_id
        assert str(seeded["state_officeholder"].id) not in by_source_id

        # Exact freshness/record facts for the seeded federal FEC source.
        fec_row = by_source_id[str(seeded["federal_fec"].id)]
        assert fec_row["record_count"] == 42
        assert fec_row["last_pull_status"] == "success"
        assert _parse_iso_datetime(fec_row["last_pull_at"]) == datetime(2026, 7, 20, 9, 0, tzinfo=timezone.utc)
        assert fec_row["source_url"] == "https://example.org/campaign-finance-source"

        officeholder_row = by_source_id[str(seeded["federal_officeholder"].id)]
        assert officeholder_row["record_count"] == 435
        assert officeholder_row["last_pull_status"] == "success"
        assert officeholder_row["source_url"] == "https://example.org/civics-officeholder-house"

    def test_metadata_keeps_null_freshness_visible(
        self,
        api_client: TestClient,
        db_conn: psycopg.Connection,
    ) -> None:
        seeded = self._seed_federal_and_unrelated_sources(db_conn)

        payload = api_client.get("/public/v1/federal/metadata").json()
        by_source_id = {row["data_source_id"]: row for row in payload["data_sources"]}

        stale_row = by_source_id[str(seeded["federal_fec_stale"].id)]
        assert stale_row["last_pull_at"] is None
        assert stale_row["last_pull_status"] is None
        assert stale_row["record_count"] is None

    def test_metadata_officeholder_count_matches_current_roster_query(
        self,
        api_client: TestClient,
        db_conn: psycopg.Connection,
    ) -> None:
        self._seed_federal_and_unrelated_sources(db_conn)
        expected_count = len(fetch_current_federal_members(db_conn))

        payload = api_client.get("/public/v1/federal/metadata").json()

        coverage = payload["coverage"]
        assert coverage["current_officeholder_count"] == expected_count
        assert coverage["officeholder_denominator_is_fixed"] is False

    def test_metadata_reports_fixed_industry_benchmark(
        self,
        api_client: TestClient,
        db_conn: psycopg.Connection,
    ) -> None:
        self._seed_federal_and_unrelated_sources(db_conn)

        payload = api_client.get("/public/v1/federal/metadata").json()

        employer_industry = payload["coverage"]["employer_industry"]
        assert employer_industry["classified_count"] == 837
        assert employer_industry["unknown_count"] == 13487
        # Hand-calculated: 837 / (837 + 13487) * 100 == 5.843340 (six decimals).
        assert employer_industry["sampled_coverage_percentage"] == "5.843340"

    def test_metadata_reports_unresolved_donor_identity(
        self,
        api_client: TestClient,
        db_conn: psycopg.Connection,
    ) -> None:
        self._seed_federal_and_unrelated_sources(db_conn)

        payload = api_client.get("/public/v1/federal/metadata").json()

        assert payload["coverage"]["donor_identity_resolution"] == "unresolved"

    def test_metadata_publishes_configured_rate_limit_policy(
        self,
        api_client: TestClient,
        db_conn: psycopg.Connection,
    ) -> None:
        import os

        self._seed_federal_and_unrelated_sources(db_conn)

        payload = api_client.get("/public/v1/federal/metadata").json()

        rate_limit = payload["rate_limit"]
        assert rate_limit["max_requests"] == int(os.environ["CIVIBUS_RATE_LIMIT_REQUESTS"])
        assert rate_limit["window_seconds"] == int(os.environ["CIVIBUS_RATE_LIMIT_WINDOW_SECONDS"])
        assert rate_limit["max_requests"] > 0
        assert rate_limit["window_seconds"] > 0
