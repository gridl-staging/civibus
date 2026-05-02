
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from core.db import get_connection

_DEFAULT_ARTIFACT_PATH = (
    Path(__file__).resolve().parents[2] / "docs" / "research" / "artifacts" / "er-cross-jurisdiction-proof.json"
)
_DEFAULT_PERSISTED_STATE_ARTIFACT_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "research"
    / "artifacts"
    / "2026_04_29_dwo_er"
    / "stage8_hetzner_cutover"
    / "persisted_state_proof.json"
)


def _serialize_match_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "entity_id_a": str(row["entity_id_a"]),
        "entity_id_b": str(row["entity_id_b"]),
        "decision": row["decision"],
        "confidence": row["confidence"],
        "decision_method": row["decision_method"],
        "decided_by": row["decided_by"],
    }


def _serialize_run_row(run_row: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": str(run_row["id"]),
        "entity_type": run_row["entity_type"],
        "status": run_row["status"],
        "started_at": run_row["started_at"].isoformat() if run_row["started_at"] is not None else None,
        "completed_at": run_row["completed_at"].isoformat() if run_row["completed_at"] is not None else None,
        "input_record_count": run_row["input_record_count"],
        "pairs_compared": run_row["pairs_compared"],
        "matches_found": run_row["matches_found"],
        "auto_merged": run_row["auto_merged"],
        "probable_matches": run_row["probable_matches"],
        "possible_matches": run_row["possible_matches"],
    }


def _serialize_source_row(row: dict[str, Any]) -> dict[str, Any]:
    entity_id = str(row["entity_id"])
    return {
        "entity_id": entity_id,
        "source_record_id": str(row["source_record_id"]),
        "source_record_key": row["source_record_key"],
        "data_source_id": str(row["data_source_id"]),
        "data_source_name": row["data_source_name"],
        "jurisdiction": row["jurisdiction"],
        "extraction_role": row["extraction_role"],
    }


def _serialize_l8_pair_result(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_id": str(row["case_id"]),
        "expected_relation": str(row["expected_relation"]),
        "entity_type": str(row["entity_type"]),
        "entity_id_a": str(row["entity_id_a"]),
        "entity_id_b": str(row["entity_id_b"]),
        "decision": str(row["decision"]),
        "confidence": float(row["confidence"]),
        "decision_method": str(row["decision_method"]),
        "decided_by": str(row["decided_by"]),
        "passed": bool(row["passed"]),
    }


def build_l8_regression_payload(
    *,
    scope: str,
    produced_at: datetime,
    repo_sha: str,
    gate_command: str,
    pair_results: list[dict[str, Any]],
    false_positive_summary: dict[str, Any],
) -> dict[str, Any]:
    """Build the repo-owned L8 evidence payload from evaluated regression results."""
    serialized_pair_results = sorted(
        (_serialize_l8_pair_result(row) for row in pair_results),
        key=lambda row: row["case_id"],
    )
    must_match_violations = sum(
        1
        for row in serialized_pair_results
        if row["expected_relation"] == "must_match" and not row["passed"]
    )
    must_not_match_violations = sum(
        1
        for row in serialized_pair_results
        if row["expected_relation"] == "must_not_match" and not row["passed"]
    )
    status = "pass" if must_match_violations == 0 and must_not_match_violations == 0 else "fail"
    return {
        "layer": "L8",
        "scope": scope,
        "schema_version": 1,
        "produced_at_utc": produced_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "repo_sha": repo_sha,
        "gate_command": gate_command,
        "status": status,
        "regression_pairs_checked": len(serialized_pair_results),
        "must_match_violations": must_match_violations,
        "must_not_match_violations": must_not_match_violations,
        "pair_results": serialized_pair_results,
        "false_positive_summary": {
            "cases_evaluated": int(false_positive_summary["cases_evaluated"]),
            "flagged_false_positives": int(false_positive_summary["flagged_false_positives"]),
            "flagged_case_ids": sorted(str(case_id) for case_id in false_positive_summary["flagged_case_ids"]),
            "false_positive_rate": float(false_positive_summary["false_positive_rate"]),
        },
    }


def write_l8_regression_artifact(
    payload: dict[str, Any],
    *,
    artifact_path: Path | str,
) -> dict[str, Any]:
    """Persist a prepared L8 evidence payload to the requested artifact path."""
    resolved_path = Path(artifact_path)
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_path.write_text(f"{json.dumps(payload, indent=2, sort_keys=False)}\n", encoding="utf-8")
    return payload


def evaluate_persisted_state_cohort_gate(
    conn: psycopg.Connection,
    *,
    stage2_baseline_path: Path | None = None,
) -> dict[str, Any]:
    """Delegate persisted-state cohort gate evaluation to tuning owner code."""
    from core.entity_resolution.tuning import evaluate_persisted_state_cohort_gate as _evaluate

    return _evaluate(conn, stage2_baseline_path=stage2_baseline_path)


def _latest_completed_run(conn: psycopg.Connection, *, entity_type: str) -> dict[str, Any] | None:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT
                id,
                entity_type,
                status,
                started_at,
                completed_at,
                input_record_count,
                pairs_compared,
                matches_found,
                auto_merged,
                probable_matches,
                possible_matches
            FROM core.splink_run
            WHERE entity_type = %s
              AND status = 'completed'
            ORDER BY completed_at DESC NULLS LAST, started_at DESC, id DESC
            LIMIT 1
            """,
            (entity_type,),
        )
        return cursor.fetchone()


def _active_entity_state_counts(conn: psycopg.Connection, *, entity_type: str) -> dict[str, int]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            "SELECT count(*)::int AS count FROM core.entity_cluster WHERE entity_type = %s",
            (entity_type,),
        )
        cluster_count_row = cursor.fetchone()
        cursor.execute(
            """
            SELECT count(*)::int AS count
            FROM core.cluster_member
            WHERE entity_type = %s
              AND split_at IS NULL
            """,
            (entity_type,),
        )
        member_count_row = cursor.fetchone()
    return {
        "active_cluster_count": int(cluster_count_row["count"]) if cluster_count_row else 0,
        "active_member_count": int(member_count_row["count"]) if member_count_row else 0,
    }


def build_persisted_state_cutover_proof(
    conn: psycopg.Connection,
    *,
    stage2_baseline_path: Path | None = None,
    scope: str = "stage8_hetzner_cutover",
) -> dict[str, Any]:
    """Build Stage 8 persisted-state proof payload from live relational state."""
    latest_runs = {
        "person": _latest_completed_run(conn, entity_type="person"),
        "organization": _latest_completed_run(conn, entity_type="organization"),
    }
    serialized_runs = {
        entity_type: _serialize_run_row(run_row) if run_row is not None else None
        for entity_type, run_row in latest_runs.items()
    }
    missing_entity_types = sorted(entity_type for entity_type, run_row in latest_runs.items() if run_row is None)
    cohort_payload = evaluate_persisted_state_cohort_gate(
        conn,
        stage2_baseline_path=stage2_baseline_path,
    )

    failures: list[str] = []
    if missing_entity_types:
        failures.append(f"missing completed core.splink_run rows for: {', '.join(missing_entity_types)}")
    if cohort_payload["cohort_gate"]["status"] != "pass":
        failures.append(
            "cohort gate failed for: "
            + ", ".join(cohort_payload["cohort_gate"]["failed_cohort_slugs"])
        )

    return {
        "status": "pass" if not failures else "fail",
        "scope": scope,
        "produced_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "latest_completed_runs": serialized_runs,
        "entity_state": {
            "person": _active_entity_state_counts(conn, entity_type="person"),
            "organization": _active_entity_state_counts(conn, entity_type="organization"),
        },
        "cohort": cohort_payload,
        "failures": failures,
    }


def write_persisted_state_cutover_proof_artifact(
    conn: psycopg.Connection,
    *,
    artifact_path: Path | str | None = None,
    stage2_baseline_path: Path | None = None,
    scope: str = "stage8_hetzner_cutover",
) -> dict[str, Any]:
    payload = build_persisted_state_cutover_proof(
        conn,
        stage2_baseline_path=stage2_baseline_path,
        scope=scope,
    )
    resolved_path = Path(artifact_path) if artifact_path is not None else _DEFAULT_PERSISTED_STATE_ARTIFACT_PATH
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_path.write_text(f"{json.dumps(payload, indent=2, sort_keys=False)}\n", encoding="utf-8")
    return payload


def _build_blocker_payload(
    *,
    status: str,
    run: dict[str, Any] | None,
    reason: str,
    pairs_compared: int | None,
    total_active_clusters: int,
    qualifying_clusters: int,
    jurisdictions_present: list[str],
) -> dict[str, Any]:
    return {
        "status": status,
        "run": run,
        "blocker": {
            "reason": reason,
            "pairs_compared": pairs_compared,
            "cluster_counts": {
                "total_active_clusters": total_active_clusters,
                "qualifying_clusters": qualifying_clusters,
                "single_jurisdiction_clusters": total_active_clusters - qualifying_clusters,
            },
            "jurisdictions_present": jurisdictions_present,
        },
    }


def _latest_completed_person_run(conn: psycopg.Connection) -> dict[str, Any] | None:
    return _latest_completed_run(conn, entity_type="person")


def _active_person_clusters(conn: psycopg.Connection) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT
                ec.id AS cluster_id,
                ec.canonical_entity_id,
                ec.cluster_confidence,
                cm.entity_id,
                cm.is_canonical
            FROM core.entity_cluster ec
            JOIN core.cluster_member cm
              ON cm.cluster_id = ec.id
             AND cm.entity_type = ec.entity_type
            WHERE ec.entity_type = 'person'
              AND cm.split_at IS NULL
            ORDER BY ec.id, cm.entity_id
            """
        )
        rows = cursor.fetchall()

    clusters_by_id: dict[UUID, dict[str, Any]] = {}
    for row in rows:
        cluster_id = row["cluster_id"]
        clusters_by_id.setdefault(
            cluster_id,
            {
                "cluster_id": str(cluster_id),
                "canonical_entity_id": str(row["canonical_entity_id"]),
                "cluster_confidence": row["cluster_confidence"],
                "members": [],
            },
        )
        clusters_by_id[cluster_id]["members"].append(
            {
                "entity_id": str(row["entity_id"]),
                "is_canonical": bool(row["is_canonical"]),
            }
        )

    clusters = list(clusters_by_id.values())
    for cluster in clusters:
        cluster["members"] = sorted(cluster["members"], key=lambda member: member["entity_id"])
        cluster["member_count"] = len(cluster["members"])
    return sorted(clusters, key=lambda cluster: cluster["cluster_id"])


def _source_rows_by_entity_id(conn: psycopg.Connection, *, entity_ids: list[UUID]) -> dict[str, list[dict[str, Any]]]:
    if not entity_ids:
        return {}

    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT
                es.entity_id,
                es.source_record_id,
                sr.source_record_key,
                sr.data_source_id,
                ds.name AS data_source_name,
                ds.jurisdiction,
                es.extraction_role
            FROM core.entity_source es
            JOIN core.source_record sr
              ON sr.id = es.source_record_id
            JOIN core.data_source ds
              ON ds.id = sr.data_source_id
            WHERE es.entity_type = 'person'
              AND es.entity_id = ANY(%s)
            ORDER BY ds.jurisdiction NULLS LAST, es.source_record_id, es.extraction_role, es.entity_id
            """,
            (entity_ids,),
        )
        rows = cursor.fetchall()

    by_entity_id: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        entity_id = str(row["entity_id"])
        by_entity_id.setdefault(entity_id, []).append(_serialize_source_row(row))
    return by_entity_id


def _active_person_matches(conn: psycopg.Connection) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT
                entity_id_a,
                entity_id_b,
                decision,
                confidence,
                decision_method,
                decided_by
            FROM core.active_matches
            WHERE entity_type = 'person'
            ORDER BY entity_id_a, entity_id_b
            """
        )
        rows = cursor.fetchall()
    return [_serialize_match_row(row) for row in rows]


def _hydrate_clusters(
    clusters: list[dict[str, Any]],
    *,
    source_rows_by_entity_id: dict[str, list[dict[str, Any]]],
    active_matches: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    hydrated_clusters: list[dict[str, Any]] = []
    for cluster in clusters:
        member_ids = {member["entity_id"] for member in cluster["members"]}
        cluster_source_rows = [
            source_row for member_id in sorted(member_ids) for source_row in source_rows_by_entity_id.get(member_id, [])
        ]
        cluster_source_rows = sorted(
            cluster_source_rows,
            key=lambda row: (str(row["jurisdiction"]), row["source_record_id"], row["extraction_role"]),
        )
        jurisdictions = sorted({str(row["jurisdiction"]) for row in cluster_source_rows if row["jurisdiction"]})
        cluster_matches = [
            match
            for match in active_matches
            if match["entity_id_a"] in member_ids and match["entity_id_b"] in member_ids
        ]
        cluster_matches = sorted(cluster_matches, key=lambda row: (row["entity_id_a"], row["entity_id_b"]))
        hydrated_clusters.append(
            {
                "cluster_id": cluster["cluster_id"],
                "canonical_entity_id": cluster["canonical_entity_id"],
                "member_count": cluster["member_count"],
                "cluster_confidence": cluster["cluster_confidence"],
                "jurisdictions": jurisdictions,
                "members": cluster["members"],
                "source_records": cluster_source_rows,
                "matches": cluster_matches,
            }
        )
    return hydrated_clusters


def build_cross_jurisdiction_proof(conn: psycopg.Connection) -> dict[str, Any]:
    run_row = _latest_completed_person_run(conn)
    if run_row is None:
        return _build_blocker_payload(
            status="blocked_no_completed_person_run",
            run=None,
            reason="No completed person run found in core.splink_run.",
            pairs_compared=None,
            total_active_clusters=0,
            qualifying_clusters=0,
            jurisdictions_present=[],
        )

    serialized_run = _serialize_run_row(run_row)
    base_clusters = _active_person_clusters(conn)
    member_ids = [UUID(member["entity_id"]) for cluster in base_clusters for member in cluster["members"]]
    source_rows_by_entity_id = _source_rows_by_entity_id(conn, entity_ids=member_ids)
    active_matches = _active_person_matches(conn)
    hydrated_clusters = _hydrate_clusters(
        base_clusters,
        source_rows_by_entity_id=source_rows_by_entity_id,
        active_matches=active_matches,
    )

    qualifying_clusters = [cluster for cluster in hydrated_clusters if len(cluster["jurisdictions"]) >= 2]
    if not qualifying_clusters:
        jurisdictions_present = sorted(
            {jurisdiction for cluster in hydrated_clusters for jurisdiction in cluster["jurisdictions"]}
        )
        return _build_blocker_payload(
            status="blocked_no_qualifying_cluster",
            run=serialized_run,
            reason="No active person cluster spans multiple jurisdictions via core.source_record -> core.data_source.",
            pairs_compared=serialized_run["pairs_compared"],
            total_active_clusters=len(hydrated_clusters),
            qualifying_clusters=0,
            jurisdictions_present=jurisdictions_present,
        )

    selected_cluster = sorted(
        qualifying_clusters,
        key=lambda cluster: (-len(cluster["jurisdictions"]), -cluster["member_count"], cluster["cluster_id"]),
    )[0]
    return {
        "status": "ok",
        "run": serialized_run,
        "selection": {
            "total_active_clusters": len(hydrated_clusters),
            "qualifying_clusters": len(qualifying_clusters),
            "selected_cluster_id": selected_cluster["cluster_id"],
        },
        "cluster": selected_cluster,
    }


def write_cross_jurisdiction_proof_artifact(
    conn: psycopg.Connection,
    *,
    artifact_path: Path | str | None = None,
) -> dict[str, Any]:
    payload = build_cross_jurisdiction_proof(conn)
    if payload["status"] != "ok":
        return payload

    resolved_path = Path(artifact_path) if artifact_path is not None else _DEFAULT_ARTIFACT_PATH
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_path.write_text(f"{json.dumps(payload, indent=2, sort_keys=False)}\n", encoding="utf-8")
    return payload


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build persisted-state ER proof artifacts.")
    parser.add_argument(
        "--artifact-path",
        type=Path,
        default=_DEFAULT_PERSISTED_STATE_ARTIFACT_PATH,
        help="Output path for persisted-state cutover proof JSON artifact.",
    )
    parser.add_argument(
        "--stage2-baseline-path",
        type=Path,
        default=None,
        help="Optional override for Stage 2 cohort baseline JSON path.",
    )
    parser.add_argument(
        "--scope",
        default="stage8_hetzner_cutover",
        help="Proof scope label recorded in the artifact payload.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_argument_parser().parse_args(argv)
    conn = get_connection()
    try:
        payload = write_persisted_state_cutover_proof_artifact(
            conn,
            artifact_path=args.artifact_path,
            stage2_baseline_path=args.stage2_baseline_path,
            scope=args.scope,
        )
    finally:
        conn.close()
    print(json.dumps(payload, indent=2, sort_keys=False))
    return 0 if payload["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
