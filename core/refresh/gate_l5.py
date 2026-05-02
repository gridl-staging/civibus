from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import psycopg
from pydantic import BaseModel

from core.db import get_connection

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_EVIDENCE_ROOT = _REPO_ROOT / "evidence" / "L5"
_STATUS_KEYS = ("crashed", "empty", "degraded", "success")


class L5Evidence(BaseModel, extra="forbid"):
    layer: str
    scope: str
    schema_version: int
    produced_at_utc: datetime
    repo_sha: str
    gate_command: str
    status: str
    total_runs: int
    status_counts: dict[str, int]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_date(value: str | None) -> date:
    if value is None:
        return _utc_now().date()
    return date.fromisoformat(value)


def _utc_window(evidence_date: date) -> tuple[datetime, datetime]:
    window_start = datetime.combine(evidence_date, time.min, tzinfo=timezone.utc)
    return window_start, window_start + timedelta(days=1)


def summarize_refresh_runs(
    connection: psycopg.Connection,
    *,
    evidence_date: date,
) -> tuple[dict[str, int], int]:
    counts = {status: 0 for status in _STATUS_KEYS}
    window_start, window_end = _utc_window(evidence_date)

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT pull_status, COUNT(*)
            FROM core.refresh_run
            WHERE completed_at >= %s
              AND completed_at < %s
            GROUP BY pull_status
            """,
            (window_start, window_end),
        )
        rows = cursor.fetchall()

    for pull_status, count in rows:
        if pull_status in counts:
            counts[pull_status] = count

    return counts, sum(counts.values())


def _evidence_status(*, counts: dict[str, int], total_runs: int) -> str:
    if total_runs == 0:
        return "fail"
    if counts["crashed"] or counts["empty"] or counts["degraded"]:
        return "fail"
    return "pass"


def write_l5_evidence(
    *,
    counts: dict[str, int],
    total_runs: int,
    repo_sha: str,
    produced_at: datetime,
    evidence_root: Path,
    evidence_date: date,
) -> Path:
    scope_root = evidence_root / "global"
    payload = L5Evidence(
        layer="L5",
        scope="global",
        schema_version=1,
        produced_at_utc=produced_at,
        repo_sha=repo_sha,
        gate_command="make gate-L5",
        status=_evidence_status(counts=counts, total_runs=total_runs),
        total_runs=total_runs,
        status_counts={status: counts[status] for status in _STATUS_KEYS},
    )
    scope_root.mkdir(parents=True, exist_ok=True)
    destination = scope_root / f"{evidence_date.isoformat()}.json"
    destination.write_text(json.dumps(payload.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8")
    return destination


def _repo_sha() -> str:
    return subprocess.check_output(["git", "rev-parse", "--short=8", "HEAD"], cwd=_REPO_ROOT, text=True).strip()


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Summarize refresh-run truthfulness for Keel L5")
    parser.add_argument("--date", help="UTC date to summarize (YYYY-MM-DD). Defaults to today UTC.")
    parser.add_argument(
        "--evidence-root",
        type=Path,
        default=_DEFAULT_EVIDENCE_ROOT,
        help="Override evidence output directory for tests or local debugging.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    evidence_date = _parse_date(args.date)
    produced_at = _utc_now()

    connection: psycopg.Connection | None = None
    try:
        connection = get_connection()
        counts, total_runs = summarize_refresh_runs(connection, evidence_date=evidence_date)
        evidence_path = write_l5_evidence(
            counts=counts,
            total_runs=total_runs,
            repo_sha=_repo_sha(),
            produced_at=produced_at,
            evidence_root=args.evidence_root,
            evidence_date=evidence_date,
        )
    except Exception as error:  # noqa: BLE001
        print(f"gate-L5 failed: {error}", file=sys.stderr)
        return 1
    finally:
        if connection is not None:
            connection.close()

    status = _evidence_status(counts=counts, total_runs=total_runs)
    print(
        f"{status.upper()}: total_runs={total_runs} "
        f"crashed={counts['crashed']} empty={counts['empty']} degraded={counts['degraded']} success={counts['success']} "
        f"evidence={evidence_path}"
    )
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
