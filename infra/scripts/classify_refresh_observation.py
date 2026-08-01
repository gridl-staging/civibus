#!/usr/bin/env python3
"""Classify one scheduled federal refresh from captured read-only artifacts."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from collections.abc import Mapping
from typing import Literal, NoReturn

from pydantic import BaseModel, ConfigDict

from core.refresh.job_builders import build_refresh_plan
from core.refresh.runner import RefreshJob, cadence_last_pull_owner, should_run_job


Verdict = Literal["FULL", "PARTIAL", "NO_OP", "FAILED"]

PARTIAL_EXIT_CODE = 2
NO_OP_EXIT_CODE = 3
FAILED_EXIT_CODE = 4

FEC_BULK_DATA_SOURCE = "FEC Bulk Data"
FEDERAL_SPINE_SOURCE = "US Congress Legislators (unitedstates/congress-legislators)"

# Each observation source maps to every federal-plan job that can advance its
# timestamp. Runtime validation below fails closed if the plan adds an active
# shared-source job without adding it here.
OBSERVED_SOURCE_JOB_KEYS = {
    FEC_BULK_DATA_SOURCE: (
        "federal-fec-masters",
        "federal-fec-schedule-a",
        "federal-fec-committee-summary",
        "federal-fec-schedule-b",
        "federal-fec-schedule-e",
    ),
    FEDERAL_SPINE_SOURCE: ("federal-congress-spine",),
    "FEC Federal Races": ("federal-fec-races",),
    "Census TIGER congressional district listing": ("federal-geometry-probe",),
    "people-enrichment-federal-congress": ("federal-enrichment",),
    "IRS Form 8872 Political Organizations": ("federal-irs-527",),
}

_TIMESTAMP_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})")
_EVENT_PATTERN = re.compile(
    r"^\s*(started|stopped|crashed)\s*(?:[│|]\s*)?(start|exit|crash)\b",
    re.IGNORECASE,
)
_NULL_TIMESTAMP_VALUES = frozenset({"", "null", "none", "unknown"})


class ObservationError(ValueError):
    """Raised when a captured artifact cannot support a trustworthy verdict."""


class _ImmutableModel(BaseModel):
    model_config = ConfigDict(frozen=True)


class MachineRun(_ImmutableModel):
    start_at: datetime
    stop_at: datetime
    exit_code: int | None
    oom_killed: bool
    requested_stop: bool
    crashed: bool

    @property
    def failure_reason(self) -> str | None:
        if self.crashed:
            return "crash"
        if self.exit_code != 0:
            return f"exit_code={self.exit_code}"
        if self.oom_killed:
            return "oom_killed=true"
        if self.requested_stop:
            return "requested_stop=true"
        return None


class SourcePull(_ImmutableModel):
    name: str
    jurisdiction: str
    last_pull_at: datetime | None


class Classification(_ImmutableModel):
    verdict: Verdict
    reason: str


class EligibilityEvidence(_ImmutableModel):
    eligible: set[str]
    unknown: set[str]


class _MachineEvent(_ImmutableModel):
    state: str
    event: str
    occurred_at: datetime
    line: str


class _HtmlTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell_parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag == "tr":
            self._row = []
        elif tag in {"th", "td"} and self._row is not None:
            self._cell_parts = []

    def handle_data(self, data: str) -> None:
        if self._cell_parts is not None:
            self._cell_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"th", "td"} and self._row is not None and self._cell_parts is not None:
            self._row.append(" ".join("".join(self._cell_parts).split()))
            self._cell_parts = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None


def _parse_timestamp(value: str, *, label: str) -> datetime:
    if not _TIMESTAMP_PATTERN.fullmatch(value):
        raise ObservationError(f"malformed timestamp for {label}: {value!r}")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ObservationError(f"malformed timestamp for {label}: timezone is required")
    return parsed.astimezone(timezone.utc)


def _parse_optional_timestamp(value: str, *, label: str) -> datetime | None:
    if value.strip().lower() in _NULL_TIMESTAMP_VALUES:
        return None
    return _parse_timestamp(value.strip(), label=label)


def _machine_events(machine_status_text: str) -> list[_MachineEvent]:
    events: list[_MachineEvent] = []
    for line in machine_status_text.splitlines():
        event_match = _EVENT_PATTERN.match(line)
        timestamp_match = _TIMESTAMP_PATTERN.search(line)
        if event_match is None or timestamp_match is None:
            continue
        events.append(
            _MachineEvent(
                state=event_match.group(1).lower(),
                event=event_match.group(2).lower(),
                occurred_at=_parse_timestamp(timestamp_match.group(), label="Machine event"),
                line=line,
            )
        )
    return events


def _parse_boolean_flag(line: str, name: str) -> bool:
    match = re.search(rf"\b{re.escape(name)}=(true|false)\b", line, re.IGNORECASE)
    if match is None:
        raise ObservationError(f"unparseable Machine status: terminal event lacks {name}")
    return match.group(1).lower() == "true"


def parse_machine_run(machine_status_text: str) -> MachineRun:
    events = _machine_events(machine_status_text)
    if not events:
        raise ObservationError("unparseable Machine status: no run events")

    terminal = events[0]
    if terminal.state not in {"stopped", "crashed"} or terminal.event not in {"exit", "crash"}:
        raise ObservationError("missing start/stop pair for latest Machine run")

    start = None
    for event in events[1:]:
        if event.state in {"stopped", "crashed"} and event.event in {"exit", "crash"}:
            break
        if event.state == "started" and event.event == "start":
            start = event
            break
    if start is None or start.occurred_at >= terminal.occurred_at:
        raise ObservationError("missing start/stop pair for latest Machine run")

    crashed = terminal.state == "crashed" or terminal.event == "crash"
    if crashed:
        return MachineRun(
            start_at=start.occurred_at,
            stop_at=terminal.occurred_at,
            exit_code=None,
            oom_killed=False,
            requested_stop=False,
            crashed=True,
        )

    exit_match = re.search(r"\bexit_code=(-?\d+)\b", terminal.line)
    if exit_match is None:
        raise ObservationError("unparseable Machine status: terminal event lacks exit_code")
    return MachineRun(
        start_at=start.occurred_at,
        stop_at=terminal.occurred_at,
        exit_code=int(exit_match.group(1)),
        oom_killed=_parse_boolean_flag(terminal.line, "oom_killed"),
        requested_stop=_parse_boolean_flag(terminal.line, "requested_stop"),
        crashed=False,
    )


def parse_data_sources(data_sources_html: str, *, label: str) -> dict[str, SourcePull]:
    parser = _HtmlTableParser()
    try:
        parser.feed(data_sources_html)
        parser.close()
    except Exception as error:
        raise ObservationError(f"unparseable {label} data-sources HTML: {error}") from error

    header_index, headers = _find_header_row(parser.rows, label=label)
    required_columns = {name: headers.index(name) for name in ("Name", "Jurisdiction", "Last pull at")}
    observed: dict[str, SourcePull] = {}
    for row in parser.rows[header_index + 1 :]:
        if len(row) <= max(required_columns.values()):
            continue
        jurisdiction = row[required_columns["Jurisdiction"]]
        if not jurisdiction.startswith("federal/"):
            continue
        name = row[required_columns["Name"]]
        if name not in OBSERVED_SOURCE_JOB_KEYS:
            raise ObservationError(f"unknown federal source in {label} evidence: {name!r}")
        if name in observed:
            raise ObservationError(f"duplicate federal source in {label} evidence: {name!r}")
        observed[name] = SourcePull(
            name=name,
            jurisdiction=jurisdiction,
            last_pull_at=_parse_optional_timestamp(row[required_columns["Last pull at"]], label=f"{label} {name}"),
        )

    missing = set(OBSERVED_SOURCE_JOB_KEYS).difference(observed)
    if missing:
        raise ObservationError(f"missing federal sources in {label} evidence: {_format_sources(missing)}")
    return observed


def parse_refresh_history(refresh_history_json: str, *, label: str) -> dict[str, datetime | None]:
    try:
        raw_values = json.loads(refresh_history_json)
    except json.JSONDecodeError as error:
        raise ObservationError(f"unparseable {label} refresh-history JSON: {error.msg}") from error
    if not isinstance(raw_values, dict):
        raise ObservationError(f"unparseable {label} refresh-history JSON: expected object")

    parsed: dict[str, datetime | None] = {}
    for job_key, value in raw_values.items():
        if not isinstance(job_key, str):
            raise ObservationError(f"unparseable {label} refresh-history JSON: job key must be a string")
        if value is None:
            parsed[job_key] = None
        elif isinstance(value, str):
            parsed[job_key] = _parse_optional_timestamp(value, label=f"{label} {job_key}")
        else:
            raise ObservationError(f"unparseable {label} refresh-history JSON: {job_key} must be a timestamp or null")
    return parsed


def _find_header_row(rows: list[list[str]], *, label: str) -> tuple[int, list[str]]:
    required_headers = {"Name", "Jurisdiction", "Last pull at"}
    for index, row in enumerate(rows):
        if required_headers.issubset(row):
            return index, row
    raise ObservationError(f"unparseable {label} data-sources HTML: required table headers not found")


def _format_timestamp(timestamp: datetime) -> str:
    return timestamp.isoformat().replace("+00:00", "Z")


def _advanced_sources(
    run: MachineRun,
    before: dict[str, SourcePull],
    after: dict[str, SourcePull],
) -> set[str]:
    advanced: set[str] = set()
    for name in OBSERVED_SOURCE_JOB_KEYS:
        before_at = before[name].last_pull_at
        after_at = after[name].last_pull_at
        if before_at is not None and before_at > run.start_at:
            raise ObservationError(
                f"before timestamp for {name} is later than Machine start: "
                f"{_format_timestamp(before_at)} > {_format_timestamp(run.start_at)}"
            )
        if before_at is not None and after_at is None:
            raise ObservationError(f"source timestamp regressed to null: {name}")
        if before_at is not None and after_at is not None and after_at < before_at:
            raise ObservationError(f"source timestamp regressed: {name}")
        changed = after_at != before_at
        if changed and after_at is not None and after_at > run.stop_at:
            raise ObservationError(
                f"after timestamp for {name} is later than Machine stop: "
                f"{_format_timestamp(after_at)} > {_format_timestamp(run.stop_at)}"
            )
        if changed and after_at is not None and run.start_at <= after_at:
            advanced.add(name)
    return advanced


def _cadence_last_pull_at(
    source_name: str,
    job: RefreshJob,
    before: dict[str, SourcePull],
    refresh_history_completed_at_by_job_key: Mapping[str, datetime | None] | None,
    *,
    run_start_at: datetime,
) -> datetime | None:
    if cadence_last_pull_owner(job) == "data_source":
        return before[source_name].last_pull_at
    if refresh_history_completed_at_by_job_key is None:
        raise KeyError(job.refresh_history_key)
    if job.refresh_history_key not in refresh_history_completed_at_by_job_key:
        raise KeyError(job.refresh_history_key)
    last_pull_at = refresh_history_completed_at_by_job_key[job.refresh_history_key]
    if last_pull_at is not None and last_pull_at > run_start_at:
        raise ObservationError(
            "post-run refresh-history timestamp for "
            f"{job.refresh_history_key}: {_format_timestamp(last_pull_at)} "
            f"is later than Machine start {_format_timestamp(run_start_at)}"
        )
    return last_pull_at


def _eligible_sources(
    run: MachineRun,
    before: dict[str, SourcePull],
    refresh_history_completed_at_by_job_key: Mapping[str, datetime | None] | None,
) -> EligibilityEvidence:
    active_jobs = build_refresh_plan(scope="federal", now=run.start_at)
    jobs_by_source = _mapped_active_jobs_by_source(active_jobs)
    eligible: set[str] = set()
    unknown: set[str] = set()
    for source_name, jobs in jobs_by_source.items():
        for job in jobs:
            try:
                last_pull_at = _cadence_last_pull_at(
                    source_name,
                    job,
                    before,
                    refresh_history_completed_at_by_job_key,
                    run_start_at=run.start_at,
                )
            except KeyError:
                unknown.add(source_name)
                continue
            if should_run_job(job, last_pull_at=last_pull_at, now=run.start_at):
                eligible.add(source_name)
    return EligibilityEvidence(eligible=eligible, unknown=unknown)


def _mapped_active_jobs_by_source(active_jobs: list[RefreshJob]) -> dict[str, tuple[RefreshJob, ...]]:
    jobs_by_key = {job.key: job for job in active_jobs}
    unmapped_job_keys = {
        job.key
        for job in active_jobs
        for source_name in set(job.data_source_names).intersection(OBSERVED_SOURCE_JOB_KEYS)
        if job.key not in OBSERVED_SOURCE_JOB_KEYS[source_name]
    }
    if unmapped_job_keys:
        raise ObservationError("active jobs missing from observation mapping: " + ", ".join(sorted(unmapped_job_keys)))
    return {
        source_name: tuple(jobs_by_key[job_key] for job_key in job_keys if job_key in jobs_by_key)
        for source_name, job_keys in OBSERVED_SOURCE_JOB_KEYS.items()
    }


def _format_sources(sources: set[str]) -> str:
    ordered = [name for name in OBSERVED_SOURCE_JOB_KEYS if name in sources]
    return "; ".join(ordered)


def _reason(run: MachineRun, *, eligible: set[str], advanced: set[str], detail: str) -> str:
    skipped = set(OBSERVED_SOURCE_JOB_KEYS).difference(advanced)
    window = f"{_format_timestamp(run.start_at)}/{_format_timestamp(run.stop_at)}"
    return (
        f"run={window}; eligible=[{_format_sources(eligible)}]; advanced=[{_format_sources(advanced)}]; "
        f"skipped=[{_format_sources(skipped)}]; {detail}"
    )


def classify_refresh_observation(
    machine_status_text: str,
    before_data_sources_html: str,
    after_data_sources_html: str,
    *,
    refresh_history_completed_at_by_job_key: Mapping[str, datetime | None] | None = None,
) -> Classification:
    run = parse_machine_run(machine_status_text)
    before = parse_data_sources(before_data_sources_html, label="before")
    after = parse_data_sources(after_data_sources_html, label="after")
    advanced = _advanced_sources(run, before, after)
    eligibility = _eligible_sources(run, before, refresh_history_completed_at_by_job_key)
    eligible = eligibility.eligible

    if run.failure_reason is not None:
        return Classification(
            verdict="FAILED",
            reason=_reason(run, eligible=eligible, advanced=advanced, detail=run.failure_reason),
        )

    missed = eligible.difference(advanced)
    unexpected = advanced.difference(eligible)
    repair_hazard = FEC_BULK_DATA_SOURCE in advanced and FEDERAL_SPINE_SOURCE not in advanced
    if repair_hazard:
        detail = f"{FEC_BULK_DATA_SOURCE} advanced without repair owner {FEDERAL_SPINE_SOURCE}"
        return Classification(
            verdict="PARTIAL",
            reason=_reason(run, eligible=eligible, advanced=advanced, detail=detail),
        )
    if eligibility.unknown:
        detail = f"cannot prove refresh-history cadence for {_format_sources(eligibility.unknown)}"
        return Classification(
            verdict="FAILED",
            reason=_reason(run, eligible=eligible, advanced=advanced, detail=detail),
        )
    if not advanced and not eligible:
        return Classification(
            verdict="NO_OP",
            reason=_reason(run, eligible=eligible, advanced=advanced, detail="nothing due"),
        )
    if not advanced:
        detail = f"eligible sources did not advance: {_format_sources(missed)}"
        return Classification(
            verdict="FAILED",
            reason=_reason(run, eligible=eligible, advanced=advanced, detail=detail),
        )
    if missed or unexpected:
        detail = f"missed=[{_format_sources(missed)}]; unexpected=[{_format_sources(unexpected)}]"
        return Classification(
            verdict="PARTIAL",
            reason=_reason(run, eligible=eligible, advanced=advanced, detail=detail),
        )
    return Classification(
        verdict="FULL",
        reason=_reason(run, eligible=eligible, advanced=advanced, detail="all eligible sources advanced"),
    )


def _failed(reason: str) -> Classification:
    return Classification(
        verdict="FAILED",
        reason=f"run=unavailable; eligible=[]; advanced=[]; skipped=[]; {reason}",
    )


def _read_artifact(path: Path, *, label: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as error:
        raise ObservationError(f"cannot read {label} artifact {path}: {error.strerror}") from error


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--machine-status", required=True, type=Path)
    parser.add_argument("--before", required=True, type=Path)
    parser.add_argument("--after", required=True, type=Path)
    parser.add_argument("--refresh-history", type=Path)
    return parser


def _exit_code(verdict: Verdict) -> int:
    return {"FULL": 0, "PARTIAL": PARTIAL_EXIT_CODE, "NO_OP": NO_OP_EXIT_CODE, "FAILED": FAILED_EXIT_CODE}[verdict]


def main(argv: list[str] | None = None) -> NoReturn:
    args = build_argument_parser().parse_args(argv)
    try:
        classification = classify_refresh_observation(
            _read_artifact(args.machine_status, label="Machine status"),
            _read_artifact(args.before, label="before data-sources"),
            _read_artifact(args.after, label="after data-sources"),
            refresh_history_completed_at_by_job_key=(
                parse_refresh_history(
                    _read_artifact(args.refresh_history, label="refresh-history"),
                    label="before",
                )
                if args.refresh_history is not None
                else None
            ),
        )
    except (ObservationError, ValueError) as error:
        classification = _failed(str(error))
    print(json.dumps({"verdict": classification.verdict, "reason": classification.reason}, separators=(",", ":")))
    raise SystemExit(_exit_code(classification.verdict))


if __name__ == "__main__":
    main()
