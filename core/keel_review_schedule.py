
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

CadenceLiteral = Literal["weekly", "quarterly"]
StatusLiteral = Literal["on_time", "overdue"]

# Quarterly cadence is implemented as a fixed 90-day window. Calendar quarters
# would require deciding which quarter calendar to use; 90 days is unambiguous,
# trivially mechanical, and close enough for "review every quarter".
_CADENCE_DAYS: dict[str, int] = {
    "weekly": 7,
    "quarterly": 90,
}

_REVIEW_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
_EVIDENCE_DATE_PATTERN = re.compile(r"^(\d{4}-\d{2}-\d{2})\.json$")


class ReviewSchedulePayload(BaseModel, extra="forbid"):
    review_id: str = Field(min_length=1)
    cadence: CadenceLiteral
    primary_prompt: str = Field(min_length=1)
    skeptic_prompt: str = Field(min_length=1)
    evidence_root: str = Field(min_length=1)
    # Optional integer thresholds the review prompts cite (e.g. auto_block_days,
    # max_evidence_files_per_window). Single source of truth lives here so the
    # prompts do not hardcode numbers that drift from the schedule.
    thresholds: dict[str, int] = Field(default_factory=dict)


class ReviewSchedule(BaseModel, extra="forbid"):
    schema_version: int = Field(ge=1)
    reviews: list[ReviewSchedulePayload] = Field(min_length=1)


@dataclass(frozen=True, slots=True)
class ReviewEntry:
    review_id: str
    cadence: CadenceLiteral
    primary_prompt: str
    skeptic_prompt: str
    evidence_root: str
    thresholds: dict[str, int]


@dataclass(frozen=True, slots=True)
class ReviewStatusRow:
    review_id: str
    cadence: CadenceLiteral
    last_evidence_date: date | None
    next_due_date: date
    status: StatusLiteral
    days_overdue: int


def load_schedule(schedule_path: Path) -> list[ReviewEntry]:
    raw = yaml.safe_load(schedule_path.read_text(encoding="utf-8"))
    validated = ReviewSchedule.model_validate(raw)
    entries: list[ReviewEntry] = []
    seen_ids: set[str] = set()
    for review in validated.reviews:
        if not _REVIEW_ID_PATTERN.fullmatch(review.review_id):
            raise ValueError(
                f"review_id must be lowercase alnum/underscore: {review.review_id}"
            )
        if review.review_id in seen_ids:
            raise ValueError(f"duplicate review_id: {review.review_id}")
        seen_ids.add(review.review_id)
        entries.append(
            ReviewEntry(
                review_id=review.review_id,
                cadence=review.cadence,
                primary_prompt=review.primary_prompt,
                skeptic_prompt=review.skeptic_prompt,
                evidence_root=review.evidence_root,
                thresholds=dict(review.thresholds),
            )
        )
    return entries


def _latest_evidence_date(*, repo_root: Path, evidence_root: str) -> date | None:
    evidence_dir = repo_root / evidence_root
    if not evidence_dir.is_dir():
        return None
    candidates: list[date] = []
    for child in evidence_dir.iterdir():
        if not child.is_file():
            continue
        match = _EVIDENCE_DATE_PATTERN.match(child.name)
        if match is None:
            continue
        try:
            candidates.append(date.fromisoformat(match.group(1)))
        except ValueError:
            continue
    if not candidates:
        return None
    return max(candidates)


def _next_due_date(*, last_evidence_date: date | None, cadence: str, now_date: date) -> date:
    if last_evidence_date is None:
        return now_date
    days = _CADENCE_DAYS[cadence]
    return date.fromordinal(last_evidence_date.toordinal() + days)


def compute_review_status(
    *,
    repo_root: Path,
    schedule: list[ReviewEntry],
    now_date: date,
) -> list[ReviewStatusRow]:
    rows: list[ReviewStatusRow] = []
    for entry in schedule:
        last_date = _latest_evidence_date(repo_root=repo_root, evidence_root=entry.evidence_root)
        next_due = _next_due_date(
            last_evidence_date=last_date,
            cadence=entry.cadence,
            now_date=now_date,
        )
        days_overdue = now_date.toordinal() - next_due.toordinal()
        # Missing evidence is always overdue. With committed evidence, "due today"
        # is still on_time; only `days_overdue > 0` (i.e. now is past next_due) is overdue.
        status: StatusLiteral
        if last_date is None:
            status = "overdue"
            days_overdue = max(0, days_overdue)
        else:
            status = "overdue" if days_overdue > 0 else "on_time"
        rows.append(
            ReviewStatusRow(
                review_id=entry.review_id,
                cadence=entry.cadence,
                last_evidence_date=last_date,
                next_due_date=next_due,
                status=status,
                days_overdue=days_overdue,
            )
        )
    return rows


def format_status_table(rows: list[ReviewStatusRow]) -> str:
    if not rows:
        return "no reviews configured"
    lines = ["review_id\tcadence\tlast_evidence\tnext_due\tstatus\tdays_overdue"]
    for row in rows:
        last = row.last_evidence_date.isoformat() if row.last_evidence_date else "-"
        lines.append(
            f"{row.review_id}\t{row.cadence}\t{last}\t{row.next_due_date.isoformat()}\t"
            f"{row.status}\t{row.days_overdue}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Keel recurring-review status report.")
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--schedule-path", default=None)
    parser.add_argument("--now-date", default=None, help="ISO date override for tests")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero when at least one review is overdue (for cron alerting).",
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root)
    schedule_path = Path(args.schedule_path) if args.schedule_path else repo_root / "keel_reviews.yaml"
    now = date.fromisoformat(args.now_date) if args.now_date else date.today()
    schedule = load_schedule(schedule_path)
    rows = compute_review_status(repo_root=repo_root, schedule=schedule, now_date=now)
    print(format_status_table(rows))
    if args.strict and any(row.status == "overdue" for row in rows):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
