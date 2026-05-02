from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest

from core.entity_resolution.persist import (
    log_splink_run_complete,
    log_splink_run_start,
    persist_auto_merge_clusters,
    persist_match_decisions,
)
from core.entity_resolution.proof import (
    build_l8_regression_payload,
    build_persisted_state_cutover_proof,
    build_cross_jurisdiction_proof,
    write_l8_regression_artifact,
    write_cross_jurisdiction_proof_artifact,
)
from core.entity_resolution.test_persist import (
    _create_org,
    _create_person,
    _insert_data_source,
    _insert_entity_source,
    _insert_source_record,
)

pytestmark = pytest.mark.integration


def _insert_completed_person_run(
    db_conn: psycopg.Connection,
    *,
    pairs_compared: int,
    matches_found: int,
    auto_merged: int,
) -> UUID:
    started_at = datetime(2026, 3, 20, 12, 0, 0, tzinfo=UTC)
    completed_at = datetime(2026, 3, 20, 12, 1, 0, tzinfo=UTC)
    run_id = log_splink_run_start(
        db_conn,
        entity_type="person",
        splink_version="4.0.0",
        model_config={"stage": "proof-test"},
        started_at=started_at,
    )
    log_splink_run_complete(
        db_conn,
        run_id,
        completed_at=completed_at,
        duration_seconds=60.0,
        counts={
            "input_record_count": 8,
            "pairs_compared": pairs_compared,
            "matches_found": matches_found,
            "auto_merged": auto_merged,
            "probable_matches": 0,
            "possible_matches": 0,
        },
    )
    return run_id


def _insert_completed_run(
    db_conn: psycopg.Connection,
    *,
    entity_type: str,
    started_at: datetime,
    completed_at: datetime,
    pairs_compared: int,
    matches_found: int,
    auto_merged: int,
) -> UUID:
    run_id = log_splink_run_start(
        db_conn,
        entity_type=entity_type,
        splink_version="4.0.0",
        model_config={"stage": "proof-test"},
        started_at=started_at,
    )
    log_splink_run_complete(
        db_conn,
        run_id,
        completed_at=completed_at,
        duration_seconds=(completed_at - started_at).total_seconds(),
        counts={
            "input_record_count": 8,
            "pairs_compared": pairs_compared,
            "matches_found": matches_found,
            "auto_merged": auto_merged,
            "probable_matches": 0,
            "possible_matches": 0,
        },
    )
    return run_id


def _seed_cluster_member_sources(
    db_conn: psycopg.Connection,
    *,
    members: list[UUID],
    jurisdictions_by_member: dict[UUID, str],
    data_source_name_prefix: str,
) -> None:
    data_source_ids: dict[str, UUID] = {}
    source_counter_by_jurisdiction: dict[str, int] = {}
    for member_id in members:
        jurisdiction = jurisdictions_by_member[member_id]
        if jurisdiction not in data_source_ids:
            data_source_ids[jurisdiction] = _insert_data_source(
                db_conn,
                name=f"{data_source_name_prefix}-{jurisdiction}",
                jurisdiction=jurisdiction,
            )
            source_counter_by_jurisdiction[jurisdiction] = 0
        source_counter_by_jurisdiction[jurisdiction] += 1
        source_record_id = _insert_source_record(
            db_conn,
            data_source_id=data_source_ids[jurisdiction],
            source_record_key=f"{jurisdiction.replace('/', '-')}-{source_counter_by_jurisdiction[jurisdiction]}",
        )
        _insert_entity_source(
            db_conn,
            entity_type="person",
            entity_id=member_id,
            source_record_id=source_record_id,
            extraction_role="donor",
        )


def _seed_person_cluster(
    db_conn: psycopg.Connection,
    *,
    member_names: list[str],
    jurisdiction_order: list[str],
    data_source_name_prefix: str,
    persist_cluster: bool = True,
) -> dict[str, object]:
    member_ids = [uuid4() for _ in member_names]
    for member_id, name in zip(member_ids, member_names, strict=True):
        _create_person(db_conn, person_id=member_id, name=name)

    _seed_cluster_member_sources(
        db_conn,
        members=member_ids,
        jurisdictions_by_member={
            member_id: jurisdiction for member_id, jurisdiction in zip(member_ids, jurisdiction_order, strict=True)
        },
        data_source_name_prefix=data_source_name_prefix,
    )

    match_pairs = [
        {
            "entity_id_a": member_ids[index],
            "entity_id_b": member_ids[index + 1],
            "decision": "match",
            "confidence": 0.98,
            "decision_method": "deterministic",
            "decided_by": "deterministic_fec_id_match",
        }
        for index in range(len(member_ids) - 1)
    ]
    cluster_component = {
        "canonical_entity_id": member_ids[0],
        "member_ids": set(member_ids),
        "min_confidence": 0.98,
        "min_decision": "match",
        "links": [],
    }
    if persist_cluster:
        persist_match_decisions(db_conn, match_pairs, "person")
        persist_auto_merge_clusters(db_conn, [cluster_component], "person")

    return {
        "member_ids": member_ids,
        "match_pairs": match_pairs,
        "cluster_component": cluster_component,
    }


def test_build_cross_jurisdiction_proof_selects_expected_cluster_and_is_deterministic(
    db_conn: psycopg.Connection,
) -> None:
    _insert_completed_person_run(
        db_conn,
        pairs_compared=3,
        matches_found=3,
        auto_merged=2,
    )
    first_cluster = _seed_person_cluster(
        db_conn,
        member_names=["Proof One", "Proof Two"],
        jurisdiction_order=["federal/fec", "state/CO"],
        data_source_name_prefix="proof-cluster-one",
        persist_cluster=False,
    )
    second_cluster = _seed_person_cluster(
        db_conn,
        member_names=["Proof Three", "Proof Four", "Proof Five"],
        jurisdiction_order=["state/GA", "state/NC", "federal/fec"],
        data_source_name_prefix="proof-cluster-two",
        persist_cluster=False,
    )
    persist_match_decisions(
        db_conn,
        [*first_cluster["match_pairs"], *second_cluster["match_pairs"]],
        "person",
    )
    persist_auto_merge_clusters(
        db_conn,
        [first_cluster["cluster_component"], second_cluster["cluster_component"]],
        "person",
    )

    first_payload = build_cross_jurisdiction_proof(db_conn)
    second_payload = build_cross_jurisdiction_proof(db_conn)

    assert first_payload == second_payload
    assert list(first_payload) == ["status", "run", "selection", "cluster"]
    assert first_payload["status"] == "ok"
    assert first_payload["run"]["pairs_compared"] == 3
    assert first_payload["selection"] == {
        "total_active_clusters": 2,
        "qualifying_clusters": 2,
        "selected_cluster_id": first_payload["cluster"]["cluster_id"],
    }

    cluster = first_payload["cluster"]
    selected_member_ids = second_cluster["member_ids"]
    assert cluster["canonical_entity_id"] == str(selected_member_ids[0])
    assert cluster["member_count"] == 3
    assert cluster["jurisdictions"] == ["federal/fec", "state/GA", "state/NC"]
    assert [member["entity_id"] for member in cluster["members"]] == sorted(
        str(member_id) for member_id in selected_member_ids
    )

    source_rows = cluster["source_records"]
    assert source_rows == sorted(
        source_rows, key=lambda row: (row["jurisdiction"], row["source_record_id"], row["extraction_role"])
    )
    assert all(
        set(row)
        == {
            "entity_id",
            "source_record_id",
            "source_record_key",
            "data_source_id",
            "data_source_name",
            "jurisdiction",
            "extraction_role",
        }
        for row in source_rows
    )

    match_rows = cluster["matches"]
    assert match_rows == sorted(match_rows, key=lambda row: (row["entity_id_a"], row["entity_id_b"]))
    assert all(
        set(row) == {"entity_id_a", "entity_id_b", "decision", "confidence", "decision_method", "decided_by"}
        for row in match_rows
    )

    serialized = json.dumps(first_payload, indent=2, sort_keys=False)
    assert '"status": "ok"' in serialized
    assert '"selection"' in serialized
    assert '"cluster"' in serialized


def test_build_cross_jurisdiction_proof_returns_blocker_when_all_clusters_are_single_jurisdiction(
    db_conn: psycopg.Connection,
) -> None:
    _insert_completed_person_run(
        db_conn,
        pairs_compared=1,
        matches_found=1,
        auto_merged=1,
    )
    _seed_person_cluster(
        db_conn,
        member_names=["Single Jur A", "Single Jur B"],
        jurisdiction_order=["federal/fec", "federal/fec"],
        data_source_name_prefix="proof-single-jur",
    )

    payload = build_cross_jurisdiction_proof(db_conn)

    assert payload == {
        "status": "blocked_no_qualifying_cluster",
        "run": payload["run"],
        "blocker": {
            "reason": "No active person cluster spans multiple jurisdictions via core.source_record -> core.data_source.",
            "pairs_compared": 1,
            "cluster_counts": {
                "total_active_clusters": 1,
                "qualifying_clusters": 0,
                "single_jurisdiction_clusters": 1,
            },
            "jurisdictions_present": ["federal/fec"],
        },
    }


def test_write_cross_jurisdiction_proof_artifact_does_not_write_file_for_blocker(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    _insert_completed_person_run(
        db_conn,
        pairs_compared=0,
        matches_found=0,
        auto_merged=0,
    )
    output_path = tmp_path / "proof.json"

    payload = write_cross_jurisdiction_proof_artifact(db_conn, artifact_path=output_path)

    assert payload["status"] == "blocked_no_qualifying_cluster"
    assert output_path.exists() is False


def test_build_l8_regression_payload_sorts_pair_results_and_flagged_case_ids() -> None:
    payload = build_l8_regression_payload(
        scope="global",
        produced_at=datetime(2026, 4, 24, 21, 45, tzinfo=UTC),
        repo_sha="abc1234",
        gate_command="uv run python -m core.keel_gate_l8",
        pair_results=[
            {
                "case_id": "z_case",
                "expected_relation": "must_not_match",
                "entity_type": "person",
                "entity_id_a": "a",
                "entity_id_b": "b",
                "decision": "match",
                "confidence": 0.98,
                "decision_method": "probabilistic",
                "decided_by": "splink_v1",
                "passed": False,
            },
            {
                "case_id": "a_case",
                "expected_relation": "must_match",
                "entity_type": "person",
                "entity_id_a": "c",
                "entity_id_b": "d",
                "decision": "match",
                "confidence": 0.99,
                "decision_method": "probabilistic",
                "decided_by": "splink_v1",
                "passed": True,
            },
        ],
        false_positive_summary={
            "cases_evaluated": 3,
            "flagged_false_positives": 2,
            "flagged_case_ids": ["fp_z", "fp_a"],
            "false_positive_rate": 2 / 3,
        },
    )

    assert [row["case_id"] for row in payload["pair_results"]] == ["a_case", "z_case"]
    assert payload["must_match_violations"] == 0
    assert payload["must_not_match_violations"] == 1
    assert payload["status"] == "fail"
    assert payload["false_positive_summary"]["flagged_case_ids"] == ["fp_a", "fp_z"]


def test_write_l8_regression_artifact_writes_prepared_payload(tmp_path: Path) -> None:
    payload = {
        "layer": "L8",
        "scope": "global",
        "schema_version": 1,
        "produced_at_utc": "2026-04-24T21:45:00Z",
        "repo_sha": "abc1234",
        "gate_command": "uv run python -m core.keel_gate_l8",
        "status": "pass",
        "regression_pairs_checked": 0,
        "must_match_violations": 0,
        "must_not_match_violations": 0,
        "pair_results": [],
        "false_positive_summary": {
            "cases_evaluated": 0,
            "flagged_false_positives": 0,
            "flagged_case_ids": [],
            "false_positive_rate": 0.0,
        },
    }
    artifact_path = tmp_path / "evidence" / "L8" / "regression_run_2026-04-24.json"

    written = write_l8_regression_artifact(payload, artifact_path=artifact_path)

    assert written == payload
    assert json.loads(artifact_path.read_text(encoding="utf-8")) == payload


def test_build_persisted_state_cutover_proof_uses_latest_completed_runs_and_cluster_member_counts(
    db_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    old_person_started_at = datetime(2026, 4, 30, 9, 0, 0, tzinfo=UTC)
    old_person_completed_at = datetime(2026, 4, 30, 9, 30, 0, tzinfo=UTC)
    new_person_started_at = datetime(2026, 4, 30, 11, 0, 0, tzinfo=UTC)
    new_person_completed_at = datetime(2026, 4, 30, 11, 45, 0, tzinfo=UTC)
    old_org_started_at = datetime(2026, 4, 30, 8, 0, 0, tzinfo=UTC)
    old_org_completed_at = datetime(2026, 4, 30, 8, 20, 0, tzinfo=UTC)
    new_org_started_at = datetime(2026, 4, 30, 10, 0, 0, tzinfo=UTC)
    new_org_completed_at = datetime(2026, 4, 30, 10, 40, 0, tzinfo=UTC)

    _insert_completed_run(
        db_conn,
        entity_type="person",
        started_at=old_person_started_at,
        completed_at=old_person_completed_at,
        pairs_compared=12,
        matches_found=9,
        auto_merged=4,
    )
    latest_person_run_id = _insert_completed_run(
        db_conn,
        entity_type="person",
        started_at=new_person_started_at,
        completed_at=new_person_completed_at,
        pairs_compared=20,
        matches_found=11,
        auto_merged=5,
    )
    _insert_completed_run(
        db_conn,
        entity_type="organization",
        started_at=old_org_started_at,
        completed_at=old_org_completed_at,
        pairs_compared=5,
        matches_found=3,
        auto_merged=2,
    )
    latest_org_run_id = _insert_completed_run(
        db_conn,
        entity_type="organization",
        started_at=new_org_started_at,
        completed_at=new_org_completed_at,
        pairs_compared=7,
        matches_found=4,
        auto_merged=3,
    )

    person_cluster = _seed_person_cluster(
        db_conn,
        member_names=["Cutover Person One", "Cutover Person Two"],
        jurisdiction_order=["state/NC", "federal/fec"],
        data_source_name_prefix="cutover-proof-person",
    )
    org_a = uuid4()
    org_b = uuid4()
    _create_org(db_conn, organization_id=org_a, name="Cutover Org A")
    _create_org(db_conn, organization_id=org_b, name="Cutover Org B")
    org_cluster_component = {
        "canonical_entity_id": org_a,
        "member_ids": {org_a, org_b},
        "min_confidence": 0.97,
        "min_decision": "match",
        "links": [],
    }
    persist_match_decisions(
        db_conn,
        [
            {
                "entity_id_a": org_a,
                "entity_id_b": org_b,
                "decision": "match",
                "confidence": 0.97,
                "decision_method": "deterministic",
                "decided_by": "deterministic_fec_id_match",
            }
        ],
        "organization",
    )
    persist_auto_merge_clusters(db_conn, [org_cluster_component], "organization")

    expected_cohort_payload = {
        "stage2_baseline_path": str(tmp_path / "stage2_baseline.json"),
        "cohorts": {"ncga_house": {"pct_resolved": 0.82, "gate_target_pct": 0.8}},
        "cohort_gate": {"status": "pass", "failed_cohort_slugs": [], "misses": [], "cohorts": {}},
    }
    monkeypatch.setattr(
        "core.entity_resolution.proof.evaluate_persisted_state_cohort_gate",
        lambda conn, *, stage2_baseline_path: expected_cohort_payload if conn is db_conn else {},
    )

    payload = build_persisted_state_cutover_proof(
        db_conn,
        stage2_baseline_path=tmp_path / "stage2_baseline.json",
    )

    assert payload["status"] == "pass"
    assert payload["cohort"] == expected_cohort_payload
    assert payload["latest_completed_runs"]["person"]["run_id"] == str(latest_person_run_id)
    assert payload["latest_completed_runs"]["person"]["pairs_compared"] == 20
    assert payload["latest_completed_runs"]["organization"]["run_id"] == str(latest_org_run_id)
    assert payload["latest_completed_runs"]["organization"]["pairs_compared"] == 7

    person_counts = payload["entity_state"]["person"]
    organization_counts = payload["entity_state"]["organization"]
    assert person_counts["active_cluster_count"] == 1
    assert person_counts["active_member_count"] == len(person_cluster["member_ids"])
    assert organization_counts["active_cluster_count"] == 1
    assert organization_counts["active_member_count"] == 2
