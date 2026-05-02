#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ALLOWED_TERMINAL_STATUSES = {"succeeded", "failed", "interrupted"}
LIFECYCLE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class MonitorResult:
    dispatch_id: str
    status: str
    reason: str


@dataclass(frozen=True)
class DispatchData:
    schema_version: int
    dispatch_id: str
    started_at_utc: datetime


@dataclass(frozen=True)
class CloseoutData:
    schema_version: int
    dispatch_id: str
    finished_at_utc: datetime
    terminal_status: str
    exit_code: int


def _parse_utc_timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError("timestamp must be a non-empty string")
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    parsed = datetime.fromisoformat(value)
    return parsed.astimezone(timezone.utc)


def _load_json(path: Path) -> dict:
    if path.is_symlink():
        raise ValueError(f"{path.name} must not be a symlink")
    if not path.is_file():
        raise ValueError(f"{path.name} must be a regular file")
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("artifact root must be an object")
    return payload


def _parse_dispatch(path: Path) -> DispatchData:
    payload = _load_json(path)
    schema_version = payload.get("schema_version")
    if schema_version != LIFECYCLE_SCHEMA_VERSION:
        raise ValueError("dispatch.json schema_version must be 1")
    dispatch_id = payload.get("dispatch_id")
    if not isinstance(dispatch_id, str) or not dispatch_id:
        raise ValueError("dispatch.json missing dispatch_id")
    started_at_utc = _parse_utc_timestamp(payload.get("started_at_utc"))
    return DispatchData(
        schema_version=LIFECYCLE_SCHEMA_VERSION,
        dispatch_id=dispatch_id,
        started_at_utc=started_at_utc,
    )


def _parse_closeout(path: Path) -> CloseoutData:
    payload = _load_json(path)
    schema_version = payload.get("schema_version")
    if schema_version != LIFECYCLE_SCHEMA_VERSION:
        raise ValueError("closeout.json schema_version must be 1")
    dispatch_id = payload.get("dispatch_id")
    if not isinstance(dispatch_id, str) or not dispatch_id:
        raise ValueError("closeout.json missing dispatch_id")

    finished_at_utc = _parse_utc_timestamp(payload.get("finished_at_utc"))
    terminal_status = payload.get("terminal_status")
    if not isinstance(terminal_status, str):
        raise ValueError("closeout.json terminal_status must be a string")
    exit_code = payload.get("exit_code")
    if not isinstance(exit_code, int):
        raise ValueError("closeout.json exit_code must be an integer")
    return CloseoutData(
        schema_version=LIFECYCLE_SCHEMA_VERSION,
        dispatch_id=dispatch_id,
        finished_at_utc=finished_at_utc,
        terminal_status=terminal_status,
        exit_code=exit_code,
    )


def _classify_from_log_freshness(log_path: Path, stale_seconds_threshold: int) -> tuple[str, str]:
    try:
        if not log_path.exists():
            return "hung", "closeout unavailable and dispatch.log missing"
        if log_path.is_symlink():
            return "unknown", "closeout unavailable and dispatch.log must not be a symlink"
        if not log_path.is_file():
            return "unknown", "closeout unavailable and dispatch.log must be a regular file"
        log_mtime = log_path.stat().st_mtime
    except OSError as exc:
        return "unknown", f"closeout unavailable and dispatch.log unreadable: {exc.__class__.__name__}"

    age_seconds = (datetime.now(timezone.utc) - datetime.fromtimestamp(log_mtime, timezone.utc)).total_seconds()
    if age_seconds <= stale_seconds_threshold:
        return "running", f"closeout unavailable and log fresh ({int(age_seconds)}s old)"
    return "hung", f"closeout unavailable and log stale ({int(age_seconds)}s old)"


def resolve_status(evidence_dir: Path, stale_seconds_threshold: int) -> MonitorResult:
    dispatch_path = evidence_dir / "dispatch.json"
    closeout_path = evidence_dir / "closeout.json"
    log_path = evidence_dir / "dispatch.log"

    try:
        dispatch = _parse_dispatch(dispatch_path)
    except Exception as exc:
        return MonitorResult(dispatch_id="unknown", status="unknown", reason=f"invalid or missing dispatch.json: {exc}")

    if closeout_path.exists():
        try:
            closeout = _parse_closeout(closeout_path)
        except Exception as exc:
            if "schema_version" in str(exc):
                return MonitorResult(
                    dispatch_id=dispatch.dispatch_id,
                    status="unknown",
                    reason=f"invalid closeout.json schema_version: {exc}",
                )
            fallback_status, fallback_reason = _classify_from_log_freshness(log_path, stale_seconds_threshold)
            return MonitorResult(
                dispatch_id=dispatch.dispatch_id,
                status=fallback_status,
                reason=fallback_reason,
            )

        if closeout.schema_version != dispatch.schema_version:
            return MonitorResult(
                dispatch_id=dispatch.dispatch_id,
                status="unknown",
                reason="schema_version mismatch between dispatch.json and closeout.json",
            )
        if closeout.dispatch_id != dispatch.dispatch_id:
            return MonitorResult(
                dispatch_id=dispatch.dispatch_id,
                status="unknown",
                reason="dispatch_id mismatch between dispatch.json and closeout.json",
            )
        if closeout.finished_at_utc < dispatch.started_at_utc:
            return MonitorResult(
                dispatch_id=dispatch.dispatch_id,
                status="unknown",
                reason="finished_at_utc is earlier than started_at_utc",
            )

        if closeout.terminal_status not in ALLOWED_TERMINAL_STATUSES:
            return MonitorResult(
                dispatch_id=dispatch.dispatch_id,
                status="unknown",
                reason="closeout.json terminal_status is invalid",
            )
        if closeout.terminal_status == "succeeded" and closeout.exit_code != 0:
            return MonitorResult(
                dispatch_id=dispatch.dispatch_id,
                status="unknown",
                reason="closeout.json exit_code must be 0 when terminal_status is succeeded",
            )
        if closeout.terminal_status in {"failed", "interrupted"} and closeout.exit_code == 0:
            return MonitorResult(
                dispatch_id=dispatch.dispatch_id,
                status="unknown",
                reason="closeout.json exit_code must be non-zero when terminal_status is failed or interrupted",
            )

        return MonitorResult(
            dispatch_id=dispatch.dispatch_id,
            status=str(closeout.terminal_status),
            reason="valid closeout.json present",
        )

    fallback_status, fallback_reason = _classify_from_log_freshness(log_path, stale_seconds_threshold)
    return MonitorResult(
        dispatch_id=dispatch.dispatch_id,
        status=fallback_status,
        reason=fallback_reason,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Read lifecycle artifacts from long_running_dispatch.sh and emit one canonical "
            "monitor status: running|hung|succeeded|failed|interrupted|unknown."
        )
    )
    parser.add_argument("--evidence-dir", required=True, type=Path, help="Directory containing dispatch artifacts")
    parser.add_argument(
        "--stale-seconds-threshold",
        type=int,
        default=300,
        help="Dispatch log age threshold in seconds before fallback classification becomes hung",
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    result = resolve_status(args.evidence_dir, args.stale_seconds_threshold)
    print(
        json.dumps(
            {
                "dispatch_id": result.dispatch_id,
                "status": result.status,
                "reason": result.reason,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
