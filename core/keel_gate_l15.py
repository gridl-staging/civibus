
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from core.keel_gate_l7 import sync_findings_section

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_EVIDENCE_ROOT = _REPO_ROOT / "evidence" / "L15"
_DEFAULT_FINDINGS_ROOT = _REPO_ROOT / "findings"
_L15_FINDINGS_START = "<!-- keel:L15:start -->"
_L15_FINDINGS_END = "<!-- keel:L15:end -->"
_NUMERIC_PATTERN = re.compile(r"^[-+]?\d+(?:\.\d+)?$")
_ROUTE_RENDER_FIXTURE_PATH = Path("web/src/lib/campaign-finance-detail/route-render.test-fixtures.ts")

@dataclass(frozen=True, slots=True)
class L15CorpusCase:
    case_id: str
    case_type: str
    route_path: str
    owner_paths: list[str]
    owner_symbols: list[str]
    metric_name: str
    expected_value: object
    # Single-sourced from tests/regression_corpus.yaml: which TS fixture export to read
    # and which capture-group regex extracts the metric value from that export's body.
    fixture_export: str
    fixture_value_pattern: str


@dataclass(frozen=True, slots=True)
class L15CaseResult:
    case_id: str
    case_type: str
    route_path: str
    metric_name: str
    normalized_expected: str
    normalized_observed: str
    passed: bool


@dataclass(frozen=True, slots=True)
class L15RunSummary:
    total_cases: int
    failing_cases: int
    results: list[L15CaseResult]


class L15CorpusCasePayload(BaseModel, extra="forbid"):
    case_id: str = Field(min_length=1)
    layer: str = Field(pattern=r"^L15$")
    case_type: str = Field(min_length=1)
    route_path: str = Field(min_length=1)
    owner_paths: list[str] = Field(min_length=1)
    owner_symbols: list[str] = Field(min_length=1)
    metric_name: str = Field(min_length=1)
    expected_value: object
    fixture_export: str = Field(min_length=1)
    fixture_value_pattern: str = Field(min_length=1)


class L15CorpusPayload(BaseModel, extra="forbid"):
    schema_version: int = Field(ge=1)
    cases: list[L15CorpusCasePayload] = Field(min_length=1)


class L15EvidenceResult(BaseModel, extra="forbid"):
    case_id: str
    case_type: str
    route_path: str
    metric_name: str
    normalized_expected: str
    normalized_observed: str
    passed: bool


class L15Evidence(BaseModel, extra="forbid"):
    layer: str
    scope: str
    schema_version: int
    produced_at_utc: datetime
    repo_sha: str
    gate_command: str
    status: str
    total_cases: int
    failing_cases: int
    results: list[L15EvidenceResult]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _parse_date(value: str | None) -> date:
    if value is None:
        return _utc_now().date()
    return date.fromisoformat(value)


def _stable_produced_at(evidence_date: date) -> datetime:
    # Use a date-derived timestamp so identical same-day inputs emit byte-stable evidence.
    return datetime(evidence_date.year, evidence_date.month, evidence_date.day, tzinfo=UTC)


def _repo_sha(repo_root: Path) -> str:
    return subprocess.check_output(["git", "rev-parse", "--short=8", "HEAD"], cwd=repo_root, text=True).strip()


def _decimal_from_value(value: object) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        try:
            return Decimal(str(value))
        except InvalidOperation:
            return None
    if isinstance(value, str):
        trimmed = value.strip().replace(",", "")
        if not trimmed or not _NUMERIC_PATTERN.fullmatch(trimmed):
            return None
        try:
            return Decimal(trimmed)
        except InvalidOperation:
            return None
    return None


def normalize_metric_value(value: object) -> str:
    decimal_value = _decimal_from_value(value)
    if decimal_value is not None:
        quantized = decimal_value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return f"{quantized:.2f}"
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    if value is None:
        return ""
    return str(value).strip()


def load_l15_corpus(corpus_path: Path) -> list[L15CorpusCase]:
    payload = yaml.safe_load(corpus_path.read_text(encoding="utf-8"))
    validated = L15CorpusPayload.model_validate(payload)
    return [
        L15CorpusCase(
            case_id=item.case_id,
            case_type=item.case_type,
            route_path=item.route_path,
            owner_paths=list(item.owner_paths),
            owner_symbols=list(item.owner_symbols),
            metric_name=item.metric_name,
            expected_value=item.expected_value,
            fixture_export=item.fixture_export,
            fixture_value_pattern=item.fixture_value_pattern,
        )
        for item in validated.cases
    ]


def _extract_export_const_block(source: str, const_name: str) -> str:
    anchor = f"export const {const_name} ="
    start_index = source.find(anchor)
    if start_index < 0:
        raise ValueError(f"missing fixture export: {const_name}")

    block_start = source.find("{", start_index)
    if block_start < 0:
        raise ValueError(f"missing object block for fixture export: {const_name}")

    depth = 0
    in_string = False
    quote_char = ""
    escaped = False
    for index in range(block_start, len(source)):
        char = source[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote_char:
                in_string = False
            continue

        if char in {"'", '"'}:
            in_string = True
            quote_char = char
            continue
        if char == "{":
            depth += 1
            continue
        if char == "}":
            depth -= 1
            if depth == 0:
                return source[block_start : index + 1]

    raise ValueError(f"unterminated fixture export block: {const_name}")


def _extract_fixture_case_value(*, fixture_source: str, case: L15CorpusCase) -> str:
    fixture_block = _extract_export_const_block(fixture_source, case.fixture_export)
    match = re.search(case.fixture_value_pattern, fixture_block, flags=re.DOTALL)
    if match is None:
        raise ValueError(f"unable to extract fixture value for case_id={case.case_id}")
    return match.group(1)


def _owner_symbols_exist(*, repo_root: Path, owner_paths: list[str], owner_symbols: list[str]) -> bool:
    owner_texts: list[str] = []
    for owner_path in owner_paths:
        absolute_owner_path = repo_root / owner_path
        if not absolute_owner_path.is_file():
            return False
        owner_texts.append(absolute_owner_path.read_text(encoding="utf-8"))

    for symbol in owner_symbols:
        pattern = re.compile(rf"\b{re.escape(symbol)}\b")
        if not any(pattern.search(owner_text) for owner_text in owner_texts):
            return False
    return True


def collect_observed_values(*, repo_root: Path, corpus: list[L15CorpusCase]) -> dict[str, object]:
    fixture_source = (repo_root / _ROUTE_RENDER_FIXTURE_PATH).read_text(encoding="utf-8")
    observed_values: dict[str, object] = {}
    for case in sorted(corpus, key=lambda item: item.case_id):
        if not _owner_symbols_exist(repo_root=repo_root, owner_paths=case.owner_paths, owner_symbols=case.owner_symbols):
            observed_values[case.case_id] = "<missing-owner>"
            continue
        observed_values[case.case_id] = _extract_fixture_case_value(fixture_source=fixture_source, case=case)
    return observed_values


def execute_corpus(*, corpus: list[L15CorpusCase], observed_values: dict[str, object]) -> L15RunSummary:
    results: list[L15CaseResult] = []
    for case in sorted(corpus, key=lambda item: item.case_id):
        case_observed = observed_values.get(case.case_id)
        observed_metric = case_observed
        if isinstance(case_observed, dict):
            observed_metric = case_observed.get("observed_value")
        if case.case_id not in observed_values:
            observed_metric = "<missing>"

        normalized_expected = normalize_metric_value(case.expected_value)
        normalized_observed = normalize_metric_value(observed_metric)
        results.append(
            L15CaseResult(
                case_id=case.case_id,
                case_type=case.case_type,
                route_path=case.route_path,
                metric_name=case.metric_name,
                normalized_expected=normalized_expected,
                normalized_observed=normalized_observed,
                passed=normalized_expected == normalized_observed,
            )
        )

    failing_cases = sum(1 for result in results if not result.passed)
    return L15RunSummary(total_cases=len(results), failing_cases=failing_cases, results=results)


def _evidence_status(summary: L15RunSummary) -> str:
    return "pass" if summary.failing_cases == 0 else "fail"


def write_l15_evidence(
    *,
    repo_root: Path,
    evidence_root: Path,
    evidence_date: date,
    produced_at: datetime,
    summary: L15RunSummary,
    gate_command: str,
    repo_sha: str,
) -> Path:
    scope_root = evidence_root / "global"
    scope_root.mkdir(parents=True, exist_ok=True)
    payload = L15Evidence(
        layer="L15",
        scope="global",
        schema_version=1,
        produced_at_utc=produced_at,
        repo_sha=repo_sha,
        gate_command=gate_command,
        status=_evidence_status(summary),
        total_cases=summary.total_cases,
        failing_cases=summary.failing_cases,
        results=[
            L15EvidenceResult(
                case_id=item.case_id,
                case_type=item.case_type,
                route_path=item.route_path,
                metric_name=item.metric_name,
                normalized_expected=item.normalized_expected,
                normalized_observed=item.normalized_observed,
                passed=item.passed,
            )
            for item in summary.results
        ],
    )
    destination = scope_root / f"{evidence_date.isoformat()}.json"
    destination.write_text(json.dumps(payload.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8")
    return destination


def _build_l15_findings_section(*, evidence_date: date, summary: L15RunSummary) -> str:
    lines = [
        _L15_FINDINGS_START,
        "## L15 - Regression Corpus",
        "",
        f"- Date: {evidence_date.isoformat()}",
        f"- Cases evaluated: {summary.total_cases}",
        f"- Failing cases: {summary.failing_cases}",
        "",
    ]

    failing = [result for result in summary.results if not result.passed]
    if not failing:
        lines.append("- No regressions detected in the current corpus snapshot.")
    else:
        for item in failing:
            lines.append(
                f"- `{item.case_id}` metric `{item.metric_name}` expected `{item.normalized_expected}` "
                f"observed `{item.normalized_observed}`"
            )

    lines.extend(["", _L15_FINDINGS_END])
    return "\n".join(lines)


def sync_l15_findings(
    *,
    findings_root: Path,
    evidence_date: date,
    summary: L15RunSummary,
) -> Path:
    section_text = _build_l15_findings_section(evidence_date=evidence_date, summary=summary)
    findings_path = sync_findings_section(
        findings_root=findings_root,
        evidence_date=evidence_date,
        section_start=_L15_FINDINGS_START,
        section_end=_L15_FINDINGS_END,
        section_text=section_text,
    )
    assert findings_path is not None
    return findings_path


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Keel L15 regression corpus gate")
    parser.add_argument("--repo-root", type=Path, default=_REPO_ROOT)
    parser.add_argument("--date", help="UTC date to write evidence for (YYYY-MM-DD). Defaults to today UTC.")
    parser.add_argument("--corpus-path", type=Path)
    parser.add_argument("--evidence-root", type=Path)
    parser.add_argument("--findings-root", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    repo_root = args.repo_root.resolve()
    evidence_date = _parse_date(args.date)
    produced_at = _stable_produced_at(evidence_date)
    corpus_path = args.corpus_path.resolve() if args.corpus_path else repo_root / "tests" / "regression_corpus.yaml"
    evidence_root = args.evidence_root.resolve() if args.evidence_root else repo_root / "evidence" / "L15"
    findings_root = args.findings_root.resolve() if args.findings_root else repo_root / "findings"

    try:
        corpus = load_l15_corpus(corpus_path)
        observed_values = collect_observed_values(repo_root=repo_root, corpus=corpus)
        summary = execute_corpus(corpus=corpus, observed_values=observed_values)
        gate_command = "python -m core.keel_gate_l15 " f"--corpus-path {corpus_path.relative_to(repo_root)}"
        evidence_path = write_l15_evidence(
            repo_root=repo_root,
            evidence_root=evidence_root,
            evidence_date=evidence_date,
            produced_at=produced_at,
            summary=summary,
            gate_command=gate_command,
            repo_sha=_repo_sha(repo_root),
        )
        findings_path = sync_l15_findings(
            findings_root=findings_root,
            evidence_date=evidence_date,
            summary=summary,
        )
    except Exception as error:  # noqa: BLE001
        print(f"gate-L15 failed: {error}", file=sys.stderr)
        return 1

    status = _evidence_status(summary)
    print(
        f"{status.upper()}: total_cases={summary.total_cases} "
        f"failing_cases={summary.failing_cases} evidence={evidence_path} findings={findings_path}"
    )
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
