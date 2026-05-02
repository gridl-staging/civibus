from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from pydantic import BaseModel

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_EVIDENCE_ROOT = _REPO_ROOT / "evidence" / "L10"
_DEFAULT_WEB_ROOT = _REPO_ROOT / "web"
_SMOKE_SPEC = "tests/smoke/campaign-finance.spec.ts"
_L10_SCHEMA_VERSION = 2
_L10_BOOTSTRAP_SCRIPT = "infra/scripts/bootstrap_l10_gate.sh"


@dataclass(frozen=True, slots=True)
class L10RouteCase:
    route: str
    case_type: str
    title_pattern: str


@dataclass(frozen=True, slots=True)
class L10CaseResult:
    route: str
    case_type: str
    passed: bool


class L10Evidence(BaseModel, extra="forbid"):
    layer: str
    scope: str
    schema_version: int
    produced_at_utc: datetime
    repo_sha: str
    gate_command: str
    status: str
    evaluated_routes: int
    empty_banner_cases: int
    deviation_banner_cases: int
    al_freshness_note_cases: int
    ga_freshness_note_cases: int
    failing_routes: list[str]


_L10_CASES = (
    L10RouteCase(
        route="/candidate/bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        case_type="empty",
        title_pattern="empty fixture shows provenance empty state",
    ),
    L10RouteCase(
        route="/candidate/dddddddd-dddd-4ddd-8ddd-dddddddddddd",
        case_type="deviation",
        title_pattern="deviant fixture shows an L10 anchor-deviation warning",
    ),
    L10RouteCase(
        route="/candidate/abababab-abab-4aba-8aba-abababababab",
        case_type="al",
        title_pattern="Alabama fixture shows a jurisdiction freshness warning",
    ),
    L10RouteCase(
        route="/candidate/cdcdcdcd-cdcd-4cdc-8cdc-cdcdcdcdcdcd",
        case_type="ga",
        title_pattern="Georgia fixture shows a jurisdiction freshness warning",
    ),
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _repo_sha() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "--short=8", "HEAD"],
        cwd=_REPO_ROOT,
        text=True,
    ).strip()


def _status(results: list[L10CaseResult]) -> str:
    return "pass" if all(result.passed for result in results) else "fail"


def _web_dependencies_preflight_error(web_root: Path) -> str | None:
    node_modules_path = web_root / "node_modules"
    if node_modules_path.is_dir():
        return None
    return (
        f"gate-L10 preflight failed: missing {node_modules_path}. "
        f"Run `{_L10_BOOTSTRAP_SCRIPT}` to install frontend dependencies."
    )


def run_l10_case(case: L10RouteCase, *, web_root: Path) -> L10CaseResult:
    command = [
        "npm",
        "run",
        "test:smoke",
        "--",
        "--grep",
        case.title_pattern,
        _SMOKE_SPEC,
    ]
    completed = subprocess.run(command, cwd=web_root, check=False)
    return L10CaseResult(
        route=case.route,
        case_type=case.case_type,
        passed=completed.returncode == 0,
    )


def write_l10_evidence(
    *,
    scope: str,
    results: list[L10CaseResult],
    repo_sha: str,
    produced_at: datetime,
    evidence_root: Path,
    evidence_date: date,
) -> Path:
    scope_root = evidence_root / scope
    scope_root.mkdir(parents=True, exist_ok=True)
    payload = L10Evidence(
        layer="L10",
        scope=scope,
        schema_version=_L10_SCHEMA_VERSION,
        produced_at_utc=produced_at,
        repo_sha=repo_sha,
        gate_command="make gate-L10",
        status=_status(results),
        evaluated_routes=len(results),
        empty_banner_cases=sum(1 for result in results if result.case_type == "empty"),
        deviation_banner_cases=sum(1 for result in results if result.case_type == "deviation"),
        al_freshness_note_cases=sum(1 for result in results if result.case_type == "al"),
        ga_freshness_note_cases=sum(1 for result in results if result.case_type == "ga"),
        failing_routes=[result.route for result in results if not result.passed],
    )
    destination = scope_root / f"{evidence_date.isoformat()}.json"
    destination.write_text(json.dumps(payload.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8")
    return destination


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Keel L10 UI completeness honesty gate")
    parser.add_argument("--scope", default="NC", choices=["NC"])
    parser.add_argument("--evidence-root", type=Path, default=_DEFAULT_EVIDENCE_ROOT)
    parser.add_argument("--web-root", type=Path, default=_DEFAULT_WEB_ROOT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    preflight_error = _web_dependencies_preflight_error(args.web_root)
    if preflight_error is not None:
        print(preflight_error, file=sys.stderr)
        return 2

    produced_at = _utc_now()

    try:
        results = [run_l10_case(case, web_root=args.web_root) for case in _L10_CASES]
        evidence_path = write_l10_evidence(
            scope=args.scope,
            results=results,
            repo_sha=_repo_sha(),
            produced_at=produced_at,
            evidence_root=args.evidence_root,
            evidence_date=produced_at.date(),
        )
    except Exception as error:  # noqa: BLE001
        print(f"gate-L10 failed: {error}", file=sys.stderr)
        return 1

    status = _status(results)
    print(
        f"{status.upper()}: scope={args.scope} evaluated_routes={len(results)} "
        f"failing_routes={len([result for result in results if not result.passed])} evidence={evidence_path}"
    )
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
