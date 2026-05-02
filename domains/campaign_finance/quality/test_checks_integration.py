"""Integration tests for quality SQL edge cases."""

from __future__ import annotations

from uuid import UUID, uuid4

import psycopg
import pytest

from core.db import insert_data_source, insert_source_record
from core.types.python.models import DataSource, SourceRecord, utc_now
from domains.campaign_finance.quality.conftest import EXPECTED_EDGE_FAMILIES
from domains.campaign_finance.quality.checks import (
    check_amount_sanity,
    check_duplicate_records,
    check_raw_field_null_rate,
    check_source_count,
)


pytestmark = pytest.mark.integration


def _insert_quality_data_source(conn: psycopg.Connection) -> DataSource:
    data_source = DataSource(
        domain="campaign_finance",
        jurisdiction="state/CO",
        name=f"Quality Integration {uuid4()}",
        source_url="https://example.com/quality",
    )
    insert_data_source(conn, data_source)
    return data_source


def _insert_quality_source_record(
    conn: psycopg.Connection,
    *,
    data_source_id: UUID,
    source_record_key: str,
    raw_fields: dict[str, object],
    record_hash: str | None,
) -> SourceRecord:
    source_record = SourceRecord(
        data_source_id=data_source_id,
        source_record_key=source_record_key,
        raw_fields=raw_fields,
        pull_date=utc_now(),
        record_hash=record_hash,
    )
    insert_source_record(conn, source_record)
    return source_record


def test_check_duplicate_records_ignores_null_record_hashes(db_conn: psycopg.Connection) -> None:
    data_source = _insert_quality_data_source(db_conn)
    _insert_quality_source_record(
        db_conn,
        data_source_id=data_source.id,
        source_record_key="record-1",
        raw_fields={"row_id": "1"},
        record_hash=None,
    )
    _insert_quality_source_record(
        db_conn,
        data_source_id=data_source.id,
        source_record_key="record-2",
        raw_fields={"row_id": "2"},
        record_hash=None,
    )

    result = check_duplicate_records(db_conn, data_source.id, data_source.name)

    assert result.status == "pass"
    assert result.metric_value == 0.0
    assert result.details["duplicate_hash_groups"] == 0


def test_check_amount_sanity_counts_non_numeric_values_as_outliers(db_conn: psycopg.Connection) -> None:
    data_source = _insert_quality_data_source(db_conn)
    _insert_quality_source_record(
        db_conn,
        data_source_id=data_source.id,
        source_record_key="record-valid",
        raw_fields={"transaction_amt": "25.00"},
        record_hash="hash-valid",
    )
    _insert_quality_source_record(
        db_conn,
        data_source_id=data_source.id,
        source_record_key="record-invalid",
        raw_fields={"transaction_amt": "not-a-number"},
        record_hash="hash-invalid",
    )

    result = check_amount_sanity(db_conn, data_source.id, data_source.name)

    assert result.status == "fail"
    assert result.metric_value == 1.0
    assert result.details["invalid_amount_count"] == 1
    assert result.details["records_with_field"] == 2


def test_check_source_count_with_prefix_scopes_to_matching_keys(db_conn: psycopg.Connection) -> None:
    """source_key_prefix filters count to only matching source_record_keys."""
    data_source = _insert_quality_data_source(db_conn)
    # Two schedule_e records
    for i in range(2):
        _insert_quality_source_record(
            db_conn,
            data_source_id=data_source.id,
            source_record_key=f"schedule_e:2024:C00001:F001:T{i}",
            raw_fields={"sup_opp": "S"},
            record_hash=f"hash-se-{i}",
        )
    # One non-schedule_e record in the same data source
    _insert_quality_source_record(
        db_conn,
        data_source_id=data_source.id,
        source_record_key="contributions:2024:C00001:F001:T0",
        raw_fields={"amount": "100"},
        record_hash="hash-contrib-0",
    )

    result = check_source_count(
        db_conn,
        data_source.id,
        data_source.name,
        source_key_prefix="schedule_e:",
    )

    assert result.status == "pass"
    assert result.metric_value == 2.0


def test_check_source_count_without_prefix_counts_all(db_conn: psycopg.Connection) -> None:
    """Without prefix, all records in the data source are counted."""
    data_source = _insert_quality_data_source(db_conn)
    for i in range(3):
        _insert_quality_source_record(
            db_conn,
            data_source_id=data_source.id,
            source_record_key=f"record-{i}",
            raw_fields={"x": "y"},
            record_hash=f"hash-{i}",
        )

    result = check_source_count(db_conn, data_source.id, data_source.name)

    assert result.metric_value == 3.0


def test_check_raw_field_null_rate_detects_missing_jsonb_key(db_conn: psycopg.Connection) -> None:
    """raw_field_null_rate counts missing JSONB keys as null."""
    data_source = _insert_quality_data_source(db_conn)
    # Record WITH the field
    _insert_quality_source_record(
        db_conn,
        data_source_id=data_source.id,
        source_record_key="schedule_e:2024:C00001:F001:T0",
        raw_fields={"sup_opp": "S", "exp_amo": "1000"},
        record_hash="hash-0",
    )
    # Record WITHOUT the field (missing key)
    _insert_quality_source_record(
        db_conn,
        data_source_id=data_source.id,
        source_record_key="schedule_e:2024:C00001:F001:T1",
        raw_fields={"exp_amo": "500"},
        record_hash="hash-1",
    )

    result = check_raw_field_null_rate(
        db_conn,
        data_source.id,
        data_source.name,
        "sup_opp",
        source_key_prefix="schedule_e:",
    )

    # 1 null out of 2 = 0.5, above default threshold 0.05
    assert result.status == "fail"
    assert result.metric_value == 0.5
    assert result.details["null_count"] == 1
    assert result.details["total_count"] == 2


def test_check_raw_field_null_rate_counts_empty_strings_as_null(db_conn: psycopg.Connection) -> None:
    """Empty/whitespace-only values in raw_fields are treated as null."""
    data_source = _insert_quality_data_source(db_conn)
    _insert_quality_source_record(
        db_conn,
        data_source_id=data_source.id,
        source_record_key="schedule_e:2024:C00001:F001:T0",
        raw_fields={"sup_opp": "S"},
        record_hash="hash-0",
    )
    _insert_quality_source_record(
        db_conn,
        data_source_id=data_source.id,
        source_record_key="schedule_e:2024:C00001:F001:T1",
        raw_fields={"sup_opp": "  "},
        record_hash="hash-1",
    )

    result = check_raw_field_null_rate(
        db_conn,
        data_source.id,
        data_source.name,
        "sup_opp",
        source_key_prefix="schedule_e:",
    )

    assert result.details["null_count"] == 1
    assert result.details["total_count"] == 2


def test_check_duplicate_records_with_prefix_scopes_to_matching_keys(db_conn: psycopg.Connection) -> None:
    """source_key_prefix scopes duplicate detection to only matching records."""
    data_source = _insert_quality_data_source(db_conn)
    # Two schedule_e records with same hash (duplicate)
    for i in range(2):
        _insert_quality_source_record(
            db_conn,
            data_source_id=data_source.id,
            source_record_key=f"schedule_e:2024:C00001:F001:T{i}",
            raw_fields={"sup_opp": "S"},
            record_hash="duplicate-hash",
        )
    # Non-schedule_e record with same hash — should be excluded by prefix
    _insert_quality_source_record(
        db_conn,
        data_source_id=data_source.id,
        source_record_key="contributions:2024:C00001:F001:T0",
        raw_fields={"amount": "100"},
        record_hash="duplicate-hash",
    )

    result = check_duplicate_records(
        db_conn,
        data_source.id,
        data_source.name,
        source_key_prefix="schedule_e:",
    )

    # Only 2 schedule_e records share the hash → 1 extra
    assert result.status == "warn"
    assert result.metric_value == 1.0


# ---------------------------------------------------------------------------
# Graph-edge population integration tests (Stage 1: contract-only failing tests)
# ---------------------------------------------------------------------------


def _seed_complete_graph_fixture(conn: psycopg.Connection, *, data_source_id: UUID) -> dict:
    """Seed one data source with all six campaign-finance edge families.

    Returns a dict with entity IDs and source_record_ids for verification.
    """
    from datetime import date
    from decimal import Decimal

    from core.graph.loader_test_support import (
        seed_candidate,
        seed_candidate_committee_link,
        seed_committee,
        seed_entity_source,
        seed_filing,
        seed_person,
        seed_source_record,
        seed_transaction,
    )

    person_id = seed_person(conn, name="Test Donor")
    committee_id = seed_committee(conn, name="Test Committee")
    candidate_id = seed_candidate(conn, name="Test Candidate")

    sr_contrib = seed_source_record(conn, data_source_id=data_source_id, key="contrib:1")
    sr_expend = seed_source_record(conn, data_source_id=data_source_id, key="expend:1")
    sr_support = seed_source_record(conn, data_source_id=data_source_id, key="support:1")
    sr_oppose = seed_source_record(conn, data_source_id=data_source_id, key="oppose:1")
    sr_filing = seed_source_record(conn, data_source_id=data_source_id, key="filing:1")
    sr_ccl = seed_source_record(conn, data_source_id=data_source_id, key="ccl:1")

    seed_entity_source(
        conn, entity_type="Person", entity_id=person_id, source_record_id=sr_contrib, extraction_role="donor"
    )
    seed_entity_source(
        conn, entity_type="Person", entity_id=person_id, source_record_id=sr_expend, extraction_role="payee"
    )
    seed_entity_source(
        conn, entity_type="Person", entity_id=person_id, source_record_id=sr_support, extraction_role="donor"
    )
    seed_entity_source(
        conn, entity_type="Person", entity_id=person_id, source_record_id=sr_oppose, extraction_role="donor"
    )

    filing_id = seed_filing(conn, committee_id=committee_id, source_record_id=sr_filing)

    # CONTRIBUTED_TO: Monetary (Itemized), support_oppose=None
    seed_transaction(
        conn,
        filing_id=filing_id,
        committee_id=committee_id,
        source_record_id=sr_contrib,
        transaction_type="Monetary (Itemized)",
        amount=Decimal("100.00"),
        transaction_date=date(2025, 1, 1),
        contributor_person_id=person_id,
    )
    # SPENT_ON: Expenditure (Itemized), support_oppose=None
    seed_transaction(
        conn,
        filing_id=filing_id,
        committee_id=committee_id,
        source_record_id=sr_expend,
        transaction_type="Expenditure (Itemized)",
        amount=Decimal("200.00"),
        transaction_date=date(2025, 2, 1),
        contributor_person_id=person_id,
    )
    # SUPPORTS: support_oppose='S'
    seed_transaction(
        conn,
        filing_id=filing_id,
        committee_id=committee_id,
        source_record_id=sr_support,
        transaction_type="Independent Expenditure",
        amount=Decimal("300.00"),
        transaction_date=date(2025, 3, 1),
        support_oppose="S",
        recipient_candidate_id=candidate_id,
    )
    # OPPOSES: support_oppose='O'
    seed_transaction(
        conn,
        filing_id=filing_id,
        committee_id=committee_id,
        source_record_id=sr_oppose,
        transaction_type="Independent Expenditure",
        amount=Decimal("400.00"),
        transaction_date=date(2025, 4, 1),
        support_oppose="O",
        recipient_candidate_id=candidate_id,
    )
    # AFFILIATED_WITH: candidate_committee_link
    seed_candidate_committee_link(
        conn,
        candidate_id=candidate_id,
        committee_id=committee_id,
        source_record_id=sr_ccl,
        designation="P",
        candidate_election_year=2026,
        fec_election_year=2026,
        valid_period_start=date(2025, 1, 1),
        valid_period_end=date(2026, 12, 31),
    )

    return {
        "person_id": person_id,
        "committee_id": committee_id,
        "candidate_id": candidate_id,
        "source_record_ids": {
            "CONTRIBUTED_TO": sr_contrib,
            "SPENT_ON": sr_expend,
            "SUPPORTS": sr_support,
            "OPPOSES": sr_oppose,
            "FILED": sr_filing,
            "AFFILIATED_WITH": sr_ccl,
        },
    }


def test_check_graph_edge_presence_all_families_at_full_ratio(graph_conn: psycopg.Connection) -> None:
    """Integration: seed all six edge families, load them, and assert
    check_graph_edge_presence reports each family at 1.0 ratio."""
    from core.graph.loader import (
        load_affiliated_with_edges,
        load_contributed_to_edges,
        load_filed_edges,
        load_ie_edges,
        load_spent_on_edges,
    )
    from core.graph.loader_test_support import seed_data_source
    from domains.campaign_finance.quality.checks import check_graph_edge_presence

    ds_id = seed_data_source(graph_conn, label="Graph Edge Integration Test")
    _seed_complete_graph_fixture(graph_conn, data_source_id=ds_id)

    load_contributed_to_edges(graph_conn, limit=1000)
    load_spent_on_edges(graph_conn, limit=1000)
    load_ie_edges(graph_conn, limit=1000)
    load_affiliated_with_edges(graph_conn, limit=1000)
    load_filed_edges(graph_conn, limit=1000)

    result = check_graph_edge_presence(graph_conn, ds_id, "Graph Edge Integration Test")
    assert result.name == "graph_edge_presence"
    assert result.status == "pass"
    assert result.metric_value == pytest.approx(1.0)

    families = result.details["edge_families"]
    for fam in EXPECTED_EDGE_FAMILIES:
        assert fam in families, f"Missing edge family {fam} in details"
        assert families[fam]["ratio"] == pytest.approx(1.0), (
            f"Edge family {fam} expected ratio 1.0, got {families[fam]['ratio']}"
        )


def test_check_graph_edge_presence_ignores_other_data_source_edges(graph_conn: psycopg.Connection) -> None:
    """Scoped-noise regression: a second data source has graph edges of the
    same types. Assert the target data source's result ignores those edges and
    only reconciles source records belonging to the requested data_source_id."""
    from core.graph.loader import (
        load_affiliated_with_edges,
        load_contributed_to_edges,
        load_filed_edges,
        load_ie_edges,
        load_spent_on_edges,
    )
    from core.graph.loader_test_support import seed_data_source
    from domains.campaign_finance.quality.checks import check_graph_edge_presence

    # Target data source: seed all six families
    target_ds_id = seed_data_source(graph_conn, label="Target DS")
    _seed_complete_graph_fixture(graph_conn, data_source_id=target_ds_id)

    # Noise data source: seed all six families with different entities
    noise_ds_id = seed_data_source(graph_conn, label="Noise DS")
    _seed_complete_graph_fixture(graph_conn, data_source_id=noise_ds_id)

    # Load ALL edges (both data sources)
    load_contributed_to_edges(graph_conn, limit=10000)
    load_spent_on_edges(graph_conn, limit=10000)
    load_ie_edges(graph_conn, limit=10000)
    load_affiliated_with_edges(graph_conn, limit=10000)
    load_filed_edges(graph_conn, limit=10000)

    # Check scoped to target only
    result = check_graph_edge_presence(graph_conn, target_ds_id, "Target DS")
    assert result.status == "pass"
    assert result.metric_value == pytest.approx(1.0)

    families = result.details["edge_families"]
    for fam in EXPECTED_EDGE_FAMILIES:
        assert families[fam]["ratio"] == pytest.approx(1.0), f"Edge family {fam} was polluted by noise data source"
