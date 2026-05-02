from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest

import core.keel_gate_l7 as keel_gate_l7
from core.db import (
    insert_address,
    insert_data_source,
    insert_entity_source,
    insert_organization,
    insert_person,
    insert_source_record,
)
from core.types.python.models import Address, DataSource, Organization, Person, SourceRecord


def _insert_test_data_source(
    conn: psycopg.Connection,
    *,
    name: str,
) -> DataSource:
    data_source = DataSource(
        domain="campaign_finance",
        jurisdiction="test/l7",
        name=name,
        source_url=f"https://example.test/{name.lower().replace(' ', '-')}",
    )
    insert_data_source(conn, data_source)
    return data_source


def _insert_test_source_record(
    conn: psycopg.Connection,
    *,
    data_source_id: UUID,
    source_record_key: str,
) -> SourceRecord:
    source_record = SourceRecord(
        data_source_id=data_source_id,
        source_record_key=source_record_key,
        raw_fields={"source_record_key": source_record_key},
        pull_date=datetime(2026, 4, 24, 12, 0, tzinfo=UTC),
    )
    insert_source_record(conn, source_record)
    return source_record


def _insert_clustered_person(
    conn: psycopg.Connection,
    *,
    cluster_id: UUID,
    canonical_name: str,
    address_text: str | None,
    source_record_id: UUID,
) -> Person:
    address_id = None
    if address_text is not None:
        address = Address(raw_address=address_text, normalized_address=address_text)
        insert_address(conn, address)
        address_id = address.id

    person = Person(
        canonical_name=canonical_name,
        first_name=canonical_name.split()[0],
        last_name=canonical_name.split()[-1],
        primary_address_id=address_id,
        er_cluster_id=cluster_id,
    )
    insert_person(conn, person)
    insert_entity_source(conn, "person", person.id, source_record_id, "donor")
    return person


def _insert_clustered_organization(
    conn: psycopg.Connection,
    *,
    cluster_id: UUID,
    canonical_name: str,
    address_text: str | None,
    source_record_id: UUID,
) -> Organization:
    address_id = None
    if address_text is not None:
        address = Address(raw_address=address_text, normalized_address=address_text)
        insert_address(conn, address)
        address_id = address.id

    organization = Organization(
        canonical_name=canonical_name,
        primary_address_id=address_id,
        er_cluster_id=cluster_id,
    )
    insert_organization(conn, organization)
    insert_entity_source(conn, "organization", organization.id, source_record_id, "committee")
    return organization


@pytest.mark.integration
def test_summarize_discrepancies_flags_only_multi_source_cluster_conflicts(db_conn: psycopg.Connection) -> None:
    source_a = _insert_test_data_source(db_conn, name=f"L7 Source A {uuid4()}")
    source_b = _insert_test_data_source(db_conn, name=f"L7 Source B {uuid4()}")
    source_c = _insert_test_data_source(db_conn, name=f"L7 Source C {uuid4()}")

    record_a = _insert_test_source_record(conn=db_conn, data_source_id=source_a.id, source_record_key=f"a-{uuid4()}")
    record_b = _insert_test_source_record(conn=db_conn, data_source_id=source_b.id, source_record_key=f"b-{uuid4()}")
    record_c = _insert_test_source_record(conn=db_conn, data_source_id=source_c.id, source_record_key=f"c-{uuid4()}")

    discrepant_person_cluster = uuid4()
    _insert_clustered_person(
        db_conn,
        cluster_id=discrepant_person_cluster,
        canonical_name="Alice Smith",
        address_text="123 MAIN ST DURHAM NC 27701",
        source_record_id=record_a.id,
    )
    _insert_clustered_person(
        db_conn,
        cluster_id=discrepant_person_cluster,
        canonical_name="Alice J Smith",
        address_text="500 ELM ST DURHAM NC 27701",
        source_record_id=record_b.id,
    )

    same_source_only_cluster = uuid4()
    _insert_clustered_person(
        db_conn,
        cluster_id=same_source_only_cluster,
        canonical_name="Jordan Lee",
        address_text="10 OAK ST DURHAM NC 27701",
        source_record_id=record_c.id,
    )
    _insert_clustered_person(
        db_conn,
        cluster_id=same_source_only_cluster,
        canonical_name="Jordan Q Lee",
        address_text="11 OAK ST DURHAM NC 27701",
        source_record_id=record_c.id,
    )

    agreeing_org_cluster = uuid4()
    _insert_clustered_organization(
        db_conn,
        cluster_id=agreeing_org_cluster,
        canonical_name="Civibus Action Fund",
        address_text="200 BROAD ST RALEIGH NC 27601",
        source_record_id=record_a.id,
    )
    _insert_clustered_organization(
        db_conn,
        cluster_id=agreeing_org_cluster,
        canonical_name="Civibus Action Fund",
        address_text="200 BROAD ST RALEIGH NC 27601",
        source_record_id=record_b.id,
    )

    summary = keel_gate_l7.summarize_discrepancies(db_conn)

    assert summary.checked_clusters == 3
    assert summary.overlapping_clusters == 2
    assert summary.discrepancy_count == 2
    assert summary.discrepancies_by_field == {"canonical_name": 1, "primary_address": 1}
    assert {(item.entity_type, item.field) for item in summary.sample_discrepancies} == {
        ("person", "canonical_name"),
        ("person", "primary_address"),
    }
    assert all(str(same_source_only_cluster) != item.cluster_id for item in summary.sample_discrepancies)


def test_main_writes_fail_evidence_and_replaces_l7_findings_section(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    findings_root = repo_root / "findings"
    findings_root.mkdir()
    findings_path = findings_root / "2026-04-24.md"
    findings_path.write_text(
        "# Keel Findings - 2026-04-24\n\nIntro text.\n\n<!-- keel:L7:start -->old<!-- keel:L7:end -->\n",
        encoding="utf-8",
    )

    summary = keel_gate_l7.L7Summary(
        checked_clusters=5,
        overlapping_clusters=2,
        discrepancy_count=1,
        discrepancies_by_field={"canonical_name": 1, "primary_address": 0},
        sample_discrepancies=[
            keel_gate_l7.L7Discrepancy(
                entity_type="organization",
                cluster_id="cluster-1",
                field="canonical_name",
                source_count=2,
                distinct_value_count=2,
                source_names=["Source A", "Source B"],
                values=["ACME CORP", "ACME CORPORATION"],
            )
        ],
    )

    class _FakeConnection:
        def close(self) -> None:
            return None

    monkeypatch.setattr(keel_gate_l7, "get_connection", lambda: _FakeConnection())
    monkeypatch.setattr(
        keel_gate_l7,
        "summarize_discrepancies",
        lambda connection, sample_limit=20: summary,
    )
    monkeypatch.setattr(keel_gate_l7, "_repo_sha", lambda repo_root: "6a78078d")
    monkeypatch.setattr(keel_gate_l7, "_utc_now", lambda: datetime(2026, 4, 24, 13, 30, tzinfo=UTC))

    exit_code = keel_gate_l7.main(
        [
            "--repo-root",
            str(repo_root),
            "--date",
            "2026-04-24",
        ]
    )

    evidence_path = repo_root / "evidence" / "L7" / "global" / "2026-04-24.json"
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    findings_text = findings_path.read_text(encoding="utf-8")

    assert exit_code == 1
    assert payload["status"] == "fail"
    assert payload["discrepancy_count"] == 1
    assert payload["sample_discrepancies"][0]["values"] == ["ACME CORP", "ACME CORPORATION"]
    assert "<!-- keel:L7:start -->" in findings_text
    assert "cluster-1" in findings_text
    assert "ACME CORP" in findings_text
    assert "old" not in findings_text
    assert "FAIL: checked_clusters=5 overlapping_clusters=2 discrepancies=1" in capsys.readouterr().out


def test_summarize_discrepancies_reports_total_counts_beyond_sample_limit() -> None:
    class _FakeCursor:
        def __init__(self) -> None:
            self._execute_count = 0

        def __enter__(self) -> _FakeCursor:
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def execute(self, query: str, params: tuple[int] | None = None) -> None:
            self._execute_count += 1
            if self._execute_count == 1:
                assert params is None
                return None
            assert params == (2,)
            return None

        def fetchone(self) -> tuple[int, int]:
            return (4, 3)

        def fetchall(self) -> list[tuple[object, ...]]:
            return [
                (
                    "person",
                    "cluster-1",
                    "canonical_name",
                    2,
                    2,
                    ["Source A", "Source B"],
                    ["Alice Smith", "Alice J Smith"],
                    3,
                    2,
                    1,
                ),
                (
                    "organization",
                    "cluster-2",
                    "primary_address",
                    2,
                    2,
                    ["Source A", "Source C"],
                    ["1 Main St", "2 Main St"],
                    3,
                    2,
                    1,
                ),
            ]

    class _FakeConnection:
        def cursor(self) -> _FakeCursor:
            return _FakeCursor()

    summary = keel_gate_l7.summarize_discrepancies(_FakeConnection(), sample_limit=2)

    assert summary.checked_clusters == 4
    assert summary.overlapping_clusters == 3
    assert summary.discrepancy_count == 3
    assert summary.discrepancies_by_field == {"canonical_name": 2, "primary_address": 1}
    assert [item.cluster_id for item in summary.sample_discrepancies] == ["cluster-1", "cluster-2"]
