from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from pydantic import BaseModel

from core.types.python.models import compute_record_hash
from domains.campaign_finance.jurisdictions.states.NC.scraper.parse import (
    parse_committee_docs,
    parse_nc_date,
    parse_transactions,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_EVIDENCE_ROOT = _REPO_ROOT / "evidence" / "L6"
_DOMAIN_CF_KEEL_CONFIG_RELATIVE = Path("domains") / "campaign_finance" / "keel_config.yaml"
_NC_COMMITTEE_DOC_TYPES = frozenset({"committee-documents", "ie-document-index"})
_NC_TRANSACTION_DATE_FIELDS = ("Date Occured",)
_NC_COMMITTEE_DOC_DATE_FIELDS = ("Received Image", "Received Data", "Start Date", "End Date")
_MAX_EXAMPLE_ROWS = 10
_NC_FIXTURE_ROOT = (
    _REPO_ROOT / "domains" / "campaign_finance" / "jurisdictions" / "states" / "NC" / "tests" / "fixtures"
)
_NC_PILOT_FIXTURE_PATHS = {
    "transactions": _NC_FIXTURE_ROOT / "transaction_export_sample.csv",
    "committee-documents": _NC_FIXTURE_ROOT / "committee_document_export_sample.csv",
    "ie-document-index": _NC_FIXTURE_ROOT / "cfdoclkup_ie_document_index_sample_2026_04_18.csv",
}


class L6ExampleRow(BaseModel, extra="forbid"):
    record_id: str
    field: str
    value: object


class L6Evidence(BaseModel, extra="forbid"):
    layer: str
    scope: str
    schema_version: int
    produced_at_utc: datetime
    repo_sha: str
    gate_command: str
    status: str
    load_id: str
    total_rows: int
    out_of_range_rows: int
    example_rows: list[L6ExampleRow]


@dataclass(slots=True)
class TemporalValidationSummary:
    total_rows: int
    out_of_range_rows: int
    example_rows: list[L6ExampleRow]


@dataclass(slots=True)
class L6EvidenceResult:
    load_id: str
    total_rows: int
    out_of_range_rows: int
    example_rows: list[L6ExampleRow]
    evidence_path: Path
    status: str


def build_scope(*, jurisdiction: str, data_type: str) -> str:
    return f"{jurisdiction.upper()}_{data_type.replace('-', '_')}"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _repo_sha() -> str:
    return subprocess.check_output(["git", "rev-parse", "--short=8", "HEAD"], cwd=_REPO_ROOT, text=True).strip()


def build_load_id(*, jurisdiction: str, data_type: str, produced_at: datetime) -> str:
    return f"{jurisdiction.lower()}-{data_type.replace('_', '-')}-{produced_at.strftime('%Y%m%dT%H%M%SZ')}"


def _parse_load_date(raw_value: str | None) -> date:
    if raw_value is None:
        return _utc_now().date()
    return date.fromisoformat(raw_value)


@dataclass(slots=True, frozen=True)
class DomainDateWindow:
    """Resolved L6 date-window config for a single domain."""

    years_back: int


def load_domain_date_window() -> DomainDateWindow:
    """Read the L6 date_window config from the campaign_finance keel_config.yaml.

    Single source of truth: the YAML, not a Python constant. Tests can override
    by monkey-patching `_REPO_ROOT` to a synthetic config tree.
    """
    import yaml as _yaml  # local import keeps module import-time cost unchanged

    config_path = _REPO_ROOT / _DOMAIN_CF_KEEL_CONFIG_RELATIVE
    payload = _yaml.safe_load(config_path.read_text(encoding="utf-8"))
    years_back = payload["l6"]["date_window"]["years_back"]
    if not isinstance(years_back, int) or years_back < 1:
        raise ValueError(f"l6.date_window.years_back must be a positive int (got {years_back!r})")
    return DomainDateWindow(years_back=years_back)


def _date_window_start(load_date: date) -> date:
    window = load_domain_date_window()
    return date(load_date.year - window.years_back, 1, 1)


def _append_example_rows(
    current_rows: list[L6ExampleRow],
    new_rows: list[L6ExampleRow],
) -> list[L6ExampleRow]:
    if len(current_rows) >= _MAX_EXAMPLE_ROWS:
        return current_rows
    remaining = _MAX_EXAMPLE_ROWS - len(current_rows)
    return [*current_rows, *new_rows[:remaining]]


def _parse_and_validate_date(
    *,
    record_id: str,
    field_name: str,
    raw_value: str | None,
    load_date: date,
) -> tuple[date | None, list[L6ExampleRow]]:
    if raw_value in (None, "", " "):
        return None, []

    try:
        parsed_date = date.fromisoformat(parse_nc_date(raw_value) or "")
    except ValueError:
        return None, [L6ExampleRow(record_id=record_id, field=field_name, value=raw_value)]

    if parsed_date < _date_window_start(load_date) or parsed_date > load_date:
        return parsed_date, [L6ExampleRow(record_id=record_id, field=field_name, value=raw_value)]
    return parsed_date, []


def validate_nc_rows(
    *,
    data_type: str,
    rows: list[dict[str, str | None]],
    load_date: date,
) -> TemporalValidationSummary:
    if data_type not in {"transactions", *sorted(_NC_COMMITTEE_DOC_TYPES)}:
        raise ValueError(f"Unsupported NC L6 data type: {data_type}")

    total_rows = 0
    out_of_range_rows = 0
    example_rows: list[L6ExampleRow] = []

    for row in rows:
        total_rows += 1
        record_id = compute_record_hash(dict(row))
        row_issues: list[L6ExampleRow] = []

        if data_type == "transactions":
            for field_name in _NC_TRANSACTION_DATE_FIELDS:
                _, issues = _parse_and_validate_date(
                    record_id=record_id,
                    field_name=field_name,
                    raw_value=row.get(field_name),
                    load_date=load_date,
                )
                row_issues.extend(issues)
        else:
            parsed_dates: dict[str, date] = {}
            for field_name in _NC_COMMITTEE_DOC_DATE_FIELDS:
                parsed_date, issues = _parse_and_validate_date(
                    record_id=record_id,
                    field_name=field_name,
                    raw_value=row.get(field_name),
                    load_date=load_date,
                )
                row_issues.extend(issues)
                if parsed_date is not None:
                    parsed_dates[field_name] = parsed_date

            if (
                "Start Date" in parsed_dates
                and "End Date" in parsed_dates
                and parsed_dates["Start Date"] > parsed_dates["End Date"]
            ):
                row_issues.append(
                    L6ExampleRow(
                        record_id=record_id,
                        field="coverage_window",
                        value={"start": row.get("Start Date"), "end": row.get("End Date")},
                    )
                )

        if row_issues:
            out_of_range_rows += 1
            example_rows = _append_example_rows(example_rows, row_issues)

    return TemporalValidationSummary(
        total_rows=total_rows,
        out_of_range_rows=out_of_range_rows,
        example_rows=example_rows,
    )


def _load_nc_rows(path: Path, *, data_type: str) -> list[dict[str, str | None]]:
    if data_type == "transactions":
        return list(parse_transactions(path))
    if data_type in _NC_COMMITTEE_DOC_TYPES:
        return list(parse_committee_docs(path))
    raise ValueError(f"Unsupported NC L6 data type: {data_type}")


def _status(summary: TemporalValidationSummary) -> str:
    return "pass" if summary.out_of_range_rows == 0 else "fail"


def write_l6_evidence(
    *,
    jurisdiction: str,
    load_id: str,
    data_type: str,
    summary: TemporalValidationSummary,
    repo_sha: str,
    produced_at: datetime,
    evidence_root: Path,
) -> Path:
    payload = L6Evidence(
        layer="L6",
        scope=build_scope(jurisdiction=jurisdiction, data_type=data_type),
        schema_version=1,
        produced_at_utc=produced_at,
        repo_sha=repo_sha,
        gate_command=f"make gate-L6 JURISDICTION={jurisdiction} DATA_TYPE={data_type} LOAD_ID={load_id}",
        status=_status(summary),
        load_id=load_id,
        total_rows=summary.total_rows,
        out_of_range_rows=summary.out_of_range_rows,
        example_rows=summary.example_rows,
    )
    evidence_root.mkdir(parents=True, exist_ok=True)
    destination = evidence_root / f"{load_id}.json"
    destination.write_text(json.dumps(payload.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8")
    return destination


def run_l6_gate_for_nc_load(
    *,
    path: Path,
    data_type: str,
    load_id: str,
    load_date: date | None = None,
    evidence_root: Path = _DEFAULT_EVIDENCE_ROOT,
    produced_at: datetime | None = None,
) -> L6EvidenceResult:
    resolved_produced_at = _utc_now() if produced_at is None else produced_at
    resolved_load_date = resolved_produced_at.date() if load_date is None else load_date
    summary = validate_nc_rows(
        data_type=data_type,
        rows=_load_nc_rows(path, data_type=data_type),
        load_date=resolved_load_date,
    )
    evidence_path = write_l6_evidence(
        jurisdiction="NC",
        load_id=load_id,
        data_type=data_type,
        summary=summary,
        repo_sha=_repo_sha(),
        produced_at=resolved_produced_at,
        evidence_root=evidence_root,
    )
    return L6EvidenceResult(
        load_id=load_id,
        total_rows=summary.total_rows,
        out_of_range_rows=summary.out_of_range_rows,
        example_rows=summary.example_rows,
        evidence_path=evidence_path,
        status=_status(summary),
    )


def run_nc_pilot_fixture_suite(
    *,
    evidence_root: Path = _DEFAULT_EVIDENCE_ROOT,
    produced_at: datetime | None = None,
) -> list[L6EvidenceResult]:
    resolved_produced_at = _utc_now() if produced_at is None else produced_at
    results: list[L6EvidenceResult] = []
    for data_type, fixture_path in _NC_PILOT_FIXTURE_PATHS.items():
        results.append(
            run_l6_gate_for_nc_load(
                path=fixture_path,
                data_type=data_type,
                load_id=build_load_id(
                    jurisdiction="NC",
                    data_type=data_type,
                    produced_at=resolved_produced_at,
                ),
                load_date=resolved_produced_at.date(),
                evidence_root=evidence_root,
                produced_at=resolved_produced_at,
            )
        )
    return results


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Keel L6 temporal integrity gate")
    parser.add_argument("--jurisdiction", required=True, choices=["NC"])
    parser.add_argument(
        "--pilot-fixture-suite",
        action="store_true",
        help="Run the canonical NC pilot fixture suite and emit evidence for all expected pilot scopes.",
    )
    parser.add_argument(
        "--data-type",
        choices=["transactions", "committee-documents", "ie-document-index"],
    )
    parser.add_argument("--path", type=Path)
    parser.add_argument("--load-id")
    parser.add_argument("--load-date", help="Load date in YYYY-MM-DD. Defaults to today UTC.")
    parser.add_argument("--evidence-root", type=Path, default=_DEFAULT_EVIDENCE_ROOT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)

    try:
        if args.pilot_fixture_suite:
            results = run_nc_pilot_fixture_suite(evidence_root=args.evidence_root)
        else:
            if args.data_type is None or args.path is None or args.load_id is None:
                raise ValueError("--data-type, --path, and --load-id are required unless --pilot-fixture-suite is set")
            results = [
                run_l6_gate_for_nc_load(
                    path=args.path,
                    data_type=args.data_type,
                    load_id=args.load_id,
                    load_date=_parse_load_date(args.load_date),
                    evidence_root=args.evidence_root,
                )
            ]
    except Exception as error:  # noqa: BLE001
        print(f"gate-L6 failed: {error}", file=sys.stderr)
        return 1

    for result in results:
        print(
            f"{result.status.upper()}: jurisdiction={args.jurisdiction} "
            f"load_id={result.load_id} total_rows={result.total_rows} "
            f"out_of_range_rows={result.out_of_range_rows} evidence={result.evidence_path}"
        )
    return 0 if all(result.status == "pass" for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
