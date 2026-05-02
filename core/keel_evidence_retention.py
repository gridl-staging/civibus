
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_EVIDENCE_ROOT = _REPO_ROOT / "evidence"
_DATE_FILE_PATTERN = re.compile(r"^(\d{4}-\d{2}-\d{2})\.json$")


@dataclass(slots=True)
class RotationSummary:
    deleted_count: int = 0
    rolled_up_count: int = 0
    rollup_files_written: int = 0
    buckets_processed: int = 0
    deleted_paths: list[str] = field(default_factory=list)
    rollup_paths: list[str] = field(default_factory=list)


def _is_evidence_bucket(directory: Path) -> bool:
    """A bucket is any directory that contains at least one date-named JSON file."""
    if not directory.is_dir():
        return False
    return any(_DATE_FILE_PATTERN.match(child.name) for child in directory.iterdir() if child.is_file())


def _iter_buckets(evidence_root: Path) -> list[Path]:
    """Find every bucket directory under the evidence tree."""
    buckets: list[Path] = []
    if not evidence_root.is_dir():
        return buckets
    for path in evidence_root.rglob("*"):
        if _is_evidence_bucket(path):
            buckets.append(path)
    return sorted(buckets)


def _collect_dailies(bucket: Path) -> list[tuple[date, Path]]:
    out: list[tuple[date, Path]] = []
    for child in bucket.iterdir():
        if not child.is_file():
            continue
        match = _DATE_FILE_PATTERN.match(child.name)
        if not match:
            continue
        try:
            evidence_date = date.fromisoformat(match.group(1))
        except ValueError:
            continue
        out.append((evidence_date, child))
    return sorted(out, key=lambda pair: pair[0])


def _read_status(path: Path) -> str:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return "unknown"
    status = payload.get("status")
    return status if isinstance(status, str) else "unknown"


def _layer_and_scope_for_bucket(*, evidence_root: Path, bucket: Path) -> tuple[str, str]:
    relative_parts = bucket.relative_to(evidence_root).parts
    layer = relative_parts[0] if relative_parts else "unknown"
    scope = "/".join(relative_parts[1:]) or "global"
    return layer, scope


def _build_rollup_payload(
    *,
    layer: str,
    scope: str,
    year_month: tuple[int, int],
    rolled_dailies: list[tuple[date, Path]],
) -> dict[str, object]:
    status_counts: dict[str, int] = defaultdict(int)
    for _, path in rolled_dailies:
        status_counts[_read_status(path)] += 1
    return {
        "layer": layer,
        "scope": scope,
        "rollup_kind": "monthly",
        "rollup_year": year_month[0],
        "rollup_month": year_month[1],
        "covered_dates": [str(d) for d, _ in rolled_dailies],
        "status_counts": dict(status_counts),
        "covered_count": len(rolled_dailies),
    }


def rotate(
    *,
    evidence_root: Path,
    now_date: date,
    retention_days: int,
    dry_run: bool,
) -> RotationSummary:
    """Rotate evidence trees per the Option C contract.

    Returns a RotationSummary describing what changed (or what would change in
    dry-run). Idempotent: running twice on the same tree yields no further
    deletions on the second pass.
    """
    summary = RotationSummary()
    cutoff = now_date - timedelta(days=retention_days)

    for bucket in _iter_buckets(evidence_root):
        summary.buckets_processed += 1
        layer, scope = _layer_and_scope_for_bucket(evidence_root=evidence_root, bucket=bucket)
        dailies = _collect_dailies(bucket)
        if not dailies:
            continue

        # The two preserved old anchors: most recent passing, most recent failing.
        last_pass_old: Path | None = None
        last_fail_old: Path | None = None
        for evidence_date, path in reversed(dailies):
            if evidence_date >= cutoff:
                continue
            status = _read_status(path)
            if status == "pass" and last_pass_old is None:
                last_pass_old = path
            if status == "fail" and last_fail_old is None:
                last_fail_old = path
            if last_pass_old is not None and last_fail_old is not None:
                break

        # Bucket the older-than-cutoff dailies by (year, month) for rollup.
        rollup_buckets: dict[tuple[int, int], list[tuple[date, Path]]] = defaultdict(list)
        to_delete: list[Path] = []
        for evidence_date, path in dailies:
            if evidence_date >= cutoff:
                continue  # within the retention window: keep daily
            if path == last_pass_old or path == last_fail_old:
                # Preserved anchor: still gets rolled up for accounting, but the file stays.
                rollup_buckets[(evidence_date.year, evidence_date.month)].append((evidence_date, path))
                continue
            rollup_buckets[(evidence_date.year, evidence_date.month)].append((evidence_date, path))
            to_delete.append(path)

        # Write rollups for every month that has rolled-up content.
        for year_month, rolled in sorted(rollup_buckets.items()):
            rollup_path = bucket / f"rollup_{year_month[0]:04d}-{year_month[1]:02d}.json"
            payload = _build_rollup_payload(
                layer=layer,
                scope=scope,
                year_month=year_month,
                rolled_dailies=sorted(rolled, key=lambda pair: pair[0]),
            )
            summary.rolled_up_count += len(rolled)
            summary.rollup_paths.append(str(rollup_path))
            if not dry_run:
                rollup_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
                summary.rollup_files_written += 1

        for path in to_delete:
            summary.deleted_paths.append(str(path))
            if not dry_run:
                path.unlink()
                summary.deleted_count += 1

    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Keel evidence retention rotation.")
    parser.add_argument("--evidence-root", default=str(_DEFAULT_EVIDENCE_ROOT))
    parser.add_argument("--retention-days", type=int, default=30)
    parser.add_argument("--now-date", default=None, help="ISO date override for tests")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    evidence_root = Path(args.evidence_root)
    now = date.fromisoformat(args.now_date) if args.now_date else date.today()
    summary = rotate(
        evidence_root=evidence_root,
        now_date=now,
        retention_days=args.retention_days,
        dry_run=args.dry_run,
    )
    mode = "dry-run" if args.dry_run else "applied"
    print(
        f"{mode}: buckets={summary.buckets_processed} "
        f"deleted={summary.deleted_count if not args.dry_run else len(summary.deleted_paths)} "
        f"rolled_up={summary.rolled_up_count} "
        f"rollup_files={summary.rollup_files_written if not args.dry_run else len(summary.rollup_paths)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
