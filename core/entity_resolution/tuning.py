
from __future__ import annotations

import argparse
import json
import shlex
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.db import get_connection
from core.entity_resolution.clustering import cluster_scored_pairs
from core.entity_resolution.confidence import classify_scored_pairs
from core.entity_resolution.extract import extract_rows_for_matching
from core.entity_resolution.l8_regression import run_l8_regression_gate
from core.entity_resolution.persist import persist_auto_merge_clusters
from core.entity_resolution.scoring import score_entities
from core.entity_resolution.splink_config import (
    build_person_probabilistic_settings,
    get_probabilistic_settings,
)
from domains.civics.scripts.er_cohort_baseline_probe import (
    compute_all_cohort_baselines,
    compute_gate_target_pct,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_STAGE2_BASELINE_PATH = (
    _REPO_ROOT / "docs" / "reference" / "research" / "artifacts" / "2026_04_29_dwo_er" / "stage2_cohort_baseline.json"
)
_DEFAULT_SUMMARY_PATH = (
    _REPO_ROOT / "docs" / "reference" / "research" / "artifacts" / "2026_04_29_dwo_er" / "stage3_tuning_summary.jsonl"
)
_STAGE7_L8_FILENAME = "stage7_final_l8_regression.json"
_STAGE7_COHORT_FILENAME = "stage7_final_cohort_gate.json"


def _write_json_artifact(payload: dict[str, Any], artifact_path: Path) -> dict[str, Any]:
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(f"{json.dumps(payload, indent=2, sort_keys=False)}\n", encoding="utf-8")
    return payload


def append_tuning_summary_row(summary_path: Path | str, row: dict[str, Any]) -> None:
    resolved_path = Path(summary_path)
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    with resolved_path.open("a", encoding="utf-8") as handle:
        handle.write(f"{json.dumps(row, sort_keys=False)}\n")


def _regression_rollup(pair_results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(pair_results)
    passed = sum(1 for row in pair_results if bool(row.get("passed")))
    return {
        "passed": passed,
        "total": total,
        "pass_rate": 0.0 if total == 0 else passed / total,
    }


def load_stage2_cohort_baseline(path: Path | None = None) -> dict[str, Any]:
    baseline_path = path or _DEFAULT_STAGE2_BASELINE_PATH
    payload = json.loads(baseline_path.read_text(encoding="utf-8"))
    cohorts = payload.get("cohorts", payload)
    if not isinstance(cohorts, dict):
        raise ValueError("stage2 cohort baseline must be a mapping keyed by cohort slug")
    baseline_pcts = [
        float(values["pct_resolved"])
        for values in cohorts.values()
        if isinstance(values, dict) and "pct_resolved" in values
    ]
    if baseline_pcts and not any(pct > 0.0 for pct in baseline_pcts):
        raise ValueError("stage2 cohort baseline must include at least one cohort baseline with pct_resolved > 0.0")
    return cohorts


def _regressed_cohort_slugs(
    *,
    stage2_baseline: dict[str, Any],
    candidate_cohorts: dict[str, Any],
) -> list[str]:
    regressed: list[str] = []
    for slug, cohort in candidate_cohorts.items():
        baseline = stage2_baseline.get(slug)
        if not isinstance(baseline, dict):
            continue
        baseline_pct = baseline.get("pct_resolved")
        candidate_pct = cohort.get("pct_resolved") if isinstance(cohort, dict) else None
        if baseline_pct is None or candidate_pct is None:
            continue
        if float(candidate_pct) < float(baseline_pct):
            regressed.append(slug)
    return sorted(regressed)


def _required_target_pct_from_stage2_baseline(stage2_baseline_row: dict[str, Any]) -> float:
    """Resolve the required Stage 7 target pct for one cohort from Stage 2 baseline."""
    if "gate_target_pct" in stage2_baseline_row:
        return float(stage2_baseline_row["gate_target_pct"])
    if "pct_resolved" in stage2_baseline_row and "floor" in stage2_baseline_row:
        return compute_gate_target_pct(
            pct_resolved=float(stage2_baseline_row["pct_resolved"]),
            floor=float(stage2_baseline_row["floor"]),
        )
    raise ValueError("stage2 cohort baseline row must include gate_target_pct or both pct_resolved and floor")


def _evaluate_stage7_cohort_gate(
    *,
    stage2_baseline: dict[str, Any],
    candidate_cohorts: dict[str, Any],
) -> dict[str, Any]:
    """Build per-cohort Stage 7 gate verdict with explicit miss details."""
    cohort_rows: dict[str, dict[str, Any]] = {}
    misses: list[dict[str, Any]] = []

    for slug, cohort in candidate_cohorts.items():
        stage2_row = stage2_baseline.get(slug)
        if not isinstance(stage2_row, dict):
            raise ValueError(f"stage2 cohort baseline missing cohort slug {slug!r}")
        if not isinstance(cohort, dict):
            raise ValueError(f"candidate cohort row must be an object for {slug!r}")
        if "pct_resolved" not in cohort or "gate_target_pct" not in cohort:
            raise ValueError(f"candidate cohort row must include pct_resolved and gate_target_pct for {slug!r}")

        pct_resolved = float(cohort["pct_resolved"])
        gate_target_pct = float(cohort["gate_target_pct"])
        required_target_pct = _required_target_pct_from_stage2_baseline(stage2_row)
        delta_pct = pct_resolved - required_target_pct
        passes_gate = pct_resolved >= required_target_pct

        cohort_rows[slug] = {
            "pct_resolved": pct_resolved,
            "gate_target_pct": gate_target_pct,
            "required_target_pct": required_target_pct,
            "delta_pct": delta_pct,
            "passes_gate": passes_gate,
        }
        if not passes_gate:
            misses.append(
                {
                    "cohort_slug": slug,
                    "pct_resolved": pct_resolved,
                    "required_target_pct": required_target_pct,
                    "delta_pct": delta_pct,
                }
            )

    for slug, stage2_row in stage2_baseline.items():
        if slug in candidate_cohorts:
            continue
        if not isinstance(stage2_row, dict):
            continue
        required_target_pct = _required_target_pct_from_stage2_baseline(stage2_row)
        cohort_rows[slug] = {
            "pct_resolved": 0.0,
            "gate_target_pct": required_target_pct,
            "required_target_pct": required_target_pct,
            "delta_pct": -required_target_pct,
            "passes_gate": False,
        }
        misses.append(
            {
                "cohort_slug": slug,
                "pct_resolved": 0.0,
                "required_target_pct": required_target_pct,
                "delta_pct": -required_target_pct,
            }
        )

    failed_cohort_slugs = sorted(miss["cohort_slug"] for miss in misses)
    ordered_misses = sorted(misses, key=lambda miss: miss["cohort_slug"])
    return {
        "status": "pass" if not ordered_misses else "fail",
        "failed_cohort_slugs": failed_cohort_slugs,
        "misses": ordered_misses,
        "cohorts": cohort_rows,
    }


def load_candidate_bundle(candidate_id: str) -> dict[str, Any]:
    if candidate_id == "default":
        return {
            "candidate_id": candidate_id,
            "hypothesis": "production default person settings",
            "probabilistic_settings": get_probabilistic_settings("person"),
        }

    candidates_path = (
        _REPO_ROOT / "docs" / "reference" / "research" / "artifacts" / "2026_04_29_dwo_er" / "stage3_candidates.json"
    )
    if not candidates_path.exists():
        raise ValueError(f"candidate {candidate_id!r} not found; expected candidate definition at {candidates_path}")
    payload = json.loads(candidates_path.read_text(encoding="utf-8"))
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("stage3_candidates.json must contain a candidates list")
    for item in candidates:
        if item.get("candidate_id") != candidate_id:
            continue
        tuning_overrides = item.get("person_tuning_overrides")
        if tuning_overrides is not None and not isinstance(tuning_overrides, dict):
            raise ValueError("person_tuning_overrides must be an object when provided")
        return {
            "candidate_id": candidate_id,
            "hypothesis": str(item.get("hypothesis", "")),
            "probabilistic_settings": build_person_probabilistic_settings(tuning_overrides=tuning_overrides),
        }
    raise ValueError(f"candidate {candidate_id!r} not found in {candidates_path}")


def _apply_candidate_clusters(
    conn: Any,
    *,
    probabilistic_settings: Any,
) -> None:
    entity_rows = extract_rows_for_matching(conn, "person")
    scored_pairs = score_entities(
        conn,
        "person",
        probabilistic_settings=probabilistic_settings,
    )
    classified_pairs = classify_scored_pairs(scored_pairs)
    clustered_pairs = cluster_scored_pairs(classified_pairs, entity_rows)
    persist_auto_merge_clusters(conn, clustered_pairs["auto_merge_clusters"], "person")


def compute_all_cohort_baselines_for_candidate(probabilistic_settings: Any) -> dict[str, dict[str, Any]]:
    conn = get_connection()
    try:
        # Stage 2 cohort math reads persisted er_cluster_id from core.person.
        # Apply candidate clusters first, then probe within the same transaction.
        _apply_candidate_clusters(
            conn,
            probabilistic_settings=probabilistic_settings,
        )
        return compute_all_cohort_baselines(conn)
    finally:
        conn.rollback()
        conn.close()


def evaluate_persisted_state_cohort_gate(
    conn: Any,
    *,
    stage2_baseline_path: Path | None = None,
) -> dict[str, Any]:
    """Evaluate Stage 7 cohort gate against already-persisted ER state."""
    candidate_cohorts = compute_all_cohort_baselines(conn)
    stage2_baseline = load_stage2_cohort_baseline(stage2_baseline_path)
    return {
        "stage2_baseline_path": str(Path(stage2_baseline_path or _DEFAULT_STAGE2_BASELINE_PATH)),
        "cohorts": candidate_cohorts,
        "cohort_gate": _evaluate_stage7_cohort_gate(
            stage2_baseline=stage2_baseline,
            candidate_cohorts=candidate_cohorts,
        ),
    }


def run_tuning_candidate(
    *,
    candidate_id: str,
    artifact_dir: Path | str,
    stage2_baseline_path: Path | None = None,
    summary_path: Path | str = _DEFAULT_SUMMARY_PATH,
) -> dict[str, Any]:
    candidate = load_candidate_bundle(candidate_id)
    probabilistic_settings = candidate["probabilistic_settings"]
    artifact_root = Path(artifact_dir)
    artifact_root.mkdir(parents=True, exist_ok=True)
    resolved_stage2_baseline_path = stage2_baseline_path or _DEFAULT_STAGE2_BASELINE_PATH
    resolved_summary_path = Path(summary_path)
    recorded_at_utc = datetime.now(UTC).isoformat().replace("+00:00", "Z")

    gate_command = shlex.join(
        [
            "uv",
            "run",
            "python",
            "-m",
            "core.entity_resolution.tuning",
            "--candidate-id",
            candidate_id,
            "--artifact-dir",
            str(artifact_root),
            "--stage2-baseline-path",
            str(resolved_stage2_baseline_path),
            "--summary-path",
            str(resolved_summary_path),
        ]
    )
    l8_payload = run_l8_regression_gate(
        artifact_path=artifact_root / _STAGE7_L8_FILENAME,
        gate_command=gate_command,
        scope=f"stage3_tuning:{candidate_id}",
        probabilistic_settings=probabilistic_settings,
    )
    _write_json_artifact(l8_payload, artifact_root / _STAGE7_L8_FILENAME)
    cohort_baselines = compute_all_cohort_baselines_for_candidate(probabilistic_settings)
    stage2_baseline = load_stage2_cohort_baseline(resolved_stage2_baseline_path)
    regression = _regression_rollup(l8_payload["pair_results"])
    cohort_gate = _evaluate_stage7_cohort_gate(
        stage2_baseline=stage2_baseline,
        candidate_cohorts=cohort_baselines,
    )
    status = "pass" if l8_payload.get("status") == "pass" and cohort_gate["status"] == "pass" else "fail"

    summary_row = {
        "status": status,
        "candidate_id": candidate_id,
        "hypothesis": candidate["hypothesis"],
        "recorded_at_utc": recorded_at_utc,
        "command_metadata": {
            "module": "core.entity_resolution.tuning",
            "candidate_id": candidate_id,
            "artifact_dir": str(artifact_root),
            "stage2_baseline_path": str(Path(resolved_stage2_baseline_path)),
            "summary_path": str(resolved_summary_path),
        },
        "regression": regression,
        "l8_status": str(l8_payload.get("status", "unknown")),
        "false_positive_summary": l8_payload["false_positive_summary"],
        "cohort_gate": cohort_gate,
        "regressed_cohorts": _regressed_cohort_slugs(
            stage2_baseline=stage2_baseline,
            candidate_cohorts=cohort_baselines,
        ),
    }
    _write_json_artifact(summary_row, artifact_root / _STAGE7_COHORT_FILENAME)
    append_tuning_summary_row(resolved_summary_path, summary_row)

    if cohort_gate["status"] != "pass":
        failed_cohorts = ", ".join(cohort_gate["failed_cohort_slugs"])
        raise RuntimeError(f"Stage 7 cohort gate failed: {failed_cohorts}")
    if l8_payload.get("status") != "pass":
        raise RuntimeError(f"Stage 7 acceptance gate failed: l8 status={l8_payload.get('status')}")

    return summary_row


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stage 3 ER tuning candidate orchestrator")
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--artifact-dir", required=True, type=Path)
    parser.add_argument("--stage2-baseline-path", default=None, type=Path)
    parser.add_argument("--summary-path", default=_DEFAULT_SUMMARY_PATH, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_argument_parser().parse_args(argv)
    try:
        row = run_tuning_candidate(
            candidate_id=args.candidate_id,
            artifact_dir=args.artifact_dir,
            stage2_baseline_path=args.stage2_baseline_path,
            summary_path=args.summary_path,
        )
    except RuntimeError as exc:
        print(str(exc))
        return 1
    print(json.dumps(row, indent=2, sort_keys=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
