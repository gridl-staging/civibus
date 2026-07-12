
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import yaml
from jsonschema.validators import validator_for

from core.keel_emitted_evidence import latest_emitted_payload_by_key

_REPO_ROOT = Path(__file__).resolve().parents[1]
_ACTIVE_LAYER_STATUSES = {"piloted", "enforced"}


@dataclass(frozen=True, slots=True)
class StatusRow:
    layer_id: str
    scope: str
    status: str
    evidence_path: Path | None
    produced_at_utc: datetime | None
    detail: str | None


@dataclass(frozen=True, slots=True)
class LayerSummary:
    """Casual-mode per-layer rollup row.

    `interpretation` is a one-line natural-language reading of `scope_rows`,
    produced by `_interpret_scope_rows`. The casual-mode prompt asks the LLM
    to walk every layer; the interpretation gives that walk a starting point
    without restating layers.yaml content.
    """

    layer_id: str
    name: str
    status: str
    scope_rows: list[StatusRow]
    interpretation: str


# Status values produced by `_fixed_scope_row` / `_emitted_scope_rows`. Any
# resolved-status string outside this set is bucketed as "other" by the
# casual interpretation (it can occur when an evidence payload's `status`
# field passes through unchanged — see `core/keel_status.py:202-203`).
_CANONICAL_STATUSES = ("pass", "stale", "error", "waived")


def _today_utc() -> date:
    return datetime.now(UTC).date()


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _load_json_schema(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_json_payload(*, payload_path: Path, schema_path: Path) -> tuple[bool, dict[str, object] | None]:
    try:
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False, None

    if not isinstance(payload, dict):
        return False, None

    schema = _load_json_schema(schema_path)
    validator_cls = validator_for(schema)
    validator_cls.check_schema(schema)
    validator = validator_cls(schema)
    if list(validator.iter_errors(payload)):
        return False, payload
    return True, payload


def _validate_waiver_payload(*, waiver_path: Path, schema_path: Path) -> tuple[bool, dict[str, object] | None]:
    payload = yaml.safe_load(waiver_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return False, None

    schema = _load_json_schema(schema_path)
    validator_cls = validator_for(schema)
    validator_cls.check_schema(schema)
    validator = validator_cls(schema)
    if list(validator.iter_errors(payload)):
        return False, payload
    return True, payload


def _format_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _active_layers(layers_payload: dict) -> list[dict]:
    return [layer for layer in layers_payload["layers"] if layer["status"] in _ACTIVE_LAYER_STATUSES]


def _latest_fixed_scope_path(scope_root: Path) -> tuple[Path | None, date | None]:
    dated_paths: list[tuple[date, Path]] = []
    for candidate in scope_root.glob("*.json"):
        try:
            candidate_date = date.fromisoformat(candidate.stem)
        except ValueError:
            continue
        dated_paths.append((candidate_date, candidate))
    if not dated_paths:
        return None, None
    latest_date, latest_path = max(dated_paths, key=lambda item: item[0])
    return latest_path, latest_date


def _waiver_status(
    *,
    repo_root: Path,
    layer_id: str,
    scope: str,
    evidence_path: Path,
    current_time_utc: datetime,
) -> str | None:
    waiver_root = repo_root / "waivers"
    waiver_schema_path = repo_root / "evidence_schemas" / "waiver.json"
    if not waiver_root.is_dir() or not waiver_schema_path.is_file():
        return None

    expected_evidence_path = evidence_path.relative_to(repo_root).as_posix()
    saw_expired = False
    saw_invalid = False

    for waiver_path in sorted(waiver_root.glob(f"{layer_id}_{scope}_*.yaml")):
        schema_valid, payload = _validate_waiver_payload(waiver_path=waiver_path, schema_path=waiver_schema_path)
        if not schema_valid or payload is None:
            saw_invalid = True
            continue
        if payload["layer"] != layer_id or payload["scope"] != scope:
            saw_invalid = True
            continue
        if payload["evidence_path"] != expected_evidence_path:
            continue

        expires_at = datetime.fromisoformat(str(payload["expires_at_utc"]))
        if expires_at <= current_time_utc:
            saw_expired = True
            continue
        return "waived"

    if saw_expired or saw_invalid:
        return "error"
    return None


def _fixed_scope_row(*, repo_root: Path, layer: dict, today_utc: date) -> StatusRow:
    layer_id = layer["id"]
    scope = layer["scope_strategy"]["value"]
    scope_root = repo_root / "evidence" / layer_id / scope
    latest_path, latest_date = _latest_fixed_scope_path(scope_root)
    if latest_path is None or latest_date is None:
        return StatusRow(
            layer_id=layer_id,
            scope=scope,
            status="error",
            evidence_path=None,
            produced_at_utc=None,
            detail="missing evidence",
        )

    schema_path = repo_root / layer["required_evidence"]["schema"]
    schema_valid, payload = _validate_json_payload(payload_path=latest_path, schema_path=schema_path)
    if not schema_valid or payload is None:
        return StatusRow(
            layer_id=layer_id,
            scope=scope,
            status="error",
            evidence_path=latest_path.relative_to(repo_root),
            produced_at_utc=None,
            detail="schema-invalid evidence",
        )

    produced_at = datetime.fromisoformat(str(payload["produced_at_utc"]))
    if latest_date != today_utc or produced_at.date() != today_utc:
        return StatusRow(
            layer_id=layer_id,
            scope=scope,
            status="stale",
            evidence_path=latest_path.relative_to(repo_root),
            produced_at_utc=produced_at,
            detail=f"latest evidence date {latest_date.isoformat()}",
        )

    evidence_status = str(payload["status"])
    if evidence_status == "pass":
        resolved_status = "pass"
        detail = None
    else:
        waiver_status = _waiver_status(
            repo_root=repo_root,
            layer_id=layer_id,
            scope=scope,
            evidence_path=latest_path,
            current_time_utc=_now_utc(),
        )
        if waiver_status == "waived":
            resolved_status = "waived"
            detail = "waiver active"
        elif waiver_status == "error":
            resolved_status = "error"
            detail = "expired or invalid waiver"
        else:
            resolved_status = evidence_status
            detail = None if evidence_status == "pass" else f"evidence status {evidence_status}"

    return StatusRow(
        layer_id=layer_id,
        scope=scope,
        status=resolved_status,
        evidence_path=latest_path.relative_to(repo_root),
        produced_at_utc=produced_at,
        detail=detail,
    )


def _emitted_scope_rows(*, repo_root: Path, layer: dict, today_utc: date) -> list[StatusRow]:
    layer_id = layer["id"]
    scope_strategy = layer["scope_strategy"]
    field = str(scope_strategy.get("field", "scope"))
    expected_scopes = list(scope_strategy.get("expected_scopes", []))
    latest_by_scope = latest_emitted_payload_by_key(
        repo_root=repo_root,
        layer=layer,
        key_field=field,
        scope_filter_field=scope_strategy.get("scope_filter_field"),
        scope_filter_value=scope_strategy.get("scope_filter_value"),
    )
    if not latest_by_scope and expected_scopes:
        return [
            StatusRow(
                layer_id=layer_id,
                scope=scope,
                status="error",
                evidence_path=None,
                produced_at_utc=None,
                detail="missing evidence",
            )
            for scope in expected_scopes
        ]

    rows: list[StatusRow] = []
    ordered_scopes = [scope for scope in expected_scopes if scope not in latest_by_scope]
    ordered_scopes.extend(scope for scope in expected_scopes if scope in latest_by_scope)
    ordered_scopes.extend(scope for scope in sorted(latest_by_scope) if scope not in expected_scopes)

    for scope in ordered_scopes:
        if scope not in latest_by_scope:
            rows.append(
                StatusRow(
                    layer_id=layer_id,
                    scope=scope,
                    status="error",
                    evidence_path=None,
                    produced_at_utc=None,
                    detail="missing evidence",
                )
            )
            continue

        evidence = latest_by_scope[scope]
        if not evidence.schema_valid:
            rows.append(
                StatusRow(
                    layer_id=layer_id,
                    scope=scope,
                    status="error",
                    evidence_path=evidence.evidence_path.relative_to(repo_root),
                    produced_at_utc=None,
                    detail="schema-invalid evidence",
                )
            )
            continue

        if evidence.produced_at_utc.date() != today_utc:
            rows.append(
                StatusRow(
                    layer_id=layer_id,
                    scope=scope,
                    status="stale",
                    evidence_path=evidence.evidence_path.relative_to(repo_root),
                    produced_at_utc=evidence.produced_at_utc,
                    detail=f"latest evidence date {evidence.produced_at_utc.date().isoformat()}",
                )
            )
            continue

        evidence_status = str(evidence.payload["status"])
        if evidence_status == "pass":
            resolved_status = "pass"
            detail = None
        else:
            waiver_scope = str(evidence.payload.get(field, evidence.payload.get("scope", scope)))
            waiver_status = _waiver_status(
                repo_root=repo_root,
                layer_id=layer_id,
                scope=waiver_scope,
                evidence_path=evidence.evidence_path,
                current_time_utc=_now_utc(),
            )
            if waiver_status == "waived":
                resolved_status = "waived"
                detail = "waiver active"
            elif waiver_status == "error":
                resolved_status = "error"
                detail = "expired or invalid waiver"
            else:
                resolved_status = evidence_status
                detail = None if evidence_status == "pass" else f"evidence status {evidence_status}"

        rows.append(
            StatusRow(
                layer_id=layer_id,
                scope=scope,
                status=resolved_status,
                evidence_path=evidence.evidence_path.relative_to(repo_root),
                produced_at_utc=evidence.produced_at_utc,
                detail=detail,
            )
        )

    return rows


def _collect_scope_rows_for_layer(*, repo_root: Path, layer: dict, today_utc: date) -> list[StatusRow]:
    """Dispatch a single layer to its scope-strategy collector.

    Shared by `collect_status_rows` (strict mode, active-statuses only) and
    `collect_layer_summaries` (casual mode, all layers). Keeping the dispatch
    in one place is the SSOT seam — adding a new scope_strategy means one
    edit here, not two.

    Raises ValueError on unsupported strategies, EXCEPT `session_summary`
    which callers must intercept before invoking this helper (L12-style
    layers have no snapshot evidence; running this dispatch on them is a
    contract violation).
    """
    scope_strategy = layer["scope_strategy"]["type"]
    if scope_strategy == "fixed_scope":
        return [_fixed_scope_row(repo_root=repo_root, layer=layer, today_utc=today_utc)]
    if scope_strategy == "emitted_by_gate":
        return _emitted_scope_rows(repo_root=repo_root, layer=layer, today_utc=today_utc)
    raise ValueError(f"Unsupported scope strategy: {scope_strategy}")


def collect_status_rows(*, repo_root: Path, today_utc: date) -> list[StatusRow]:
    layers_payload = _load_yaml(repo_root / "layers.yaml")
    rows: list[StatusRow] = []
    for layer in _active_layers(layers_payload):
        rows.extend(_collect_scope_rows_for_layer(repo_root=repo_root, layer=layer, today_utc=today_utc))
    return rows


def _interpret_scope_rows(*, scope_rows: list[StatusRow], scope_strategy_type: str) -> str:
    """Casual-mode one-line interpretation of a layer's scope rows.

    Branches are evaluated in declared order; first match wins. The branch
    table is documented in `chats/apr26_4pm_1_keel_casual_mode.md` Stage 1
    and asserted as the contract by `tests/keel/test_keel_summary.py`.
    """
    # Branch 0 — session_summary short-circuit (L12-style layers have no
    # snapshot evidence; the casual prompt still needs to mention them).
    if scope_strategy_type == "session_summary":
        return "per-session summary; no snapshot evidence"

    # Branch 1 — no rows at all (e.g. expected_scopes empty AND no emitted).
    if not scope_rows:
        return "no evidence emitted yet"

    statuses = [row.status for row in scope_rows]
    n = len(scope_rows)

    # Branches 2–5 — homogeneous bucket states. These are checked BEFORE
    # the missing-evidence branch so e.g. all-error doesn't get caught
    # by "missing emitted scope" first.
    if all(s == "pass" for s in statuses):
        return "all expected scopes pass"
    if all(s == "stale" for s in statuses):
        return "all evidence stale"
    if all(s == "error" for s in statuses):
        return f"all {n} scopes errored"
    if all(s == "waived" for s in statuses):
        return f"all {n} scopes waived"

    # Branch 6 — any error row with detail="missing evidence" wins over
    # the catch-all distribution. Reports the first such scope.
    for row in scope_rows:
        if row.status == "error" and row.detail == "missing evidence":
            return f"missing emitted scope: {row.scope}"

    # Branch 7 — catch-all distribution. Counts canonical buckets plus an
    # "other" bucket for any passthrough status outside the four canonical
    # values (e.g. payload `status: "warn"`).
    counts = {key: 0 for key in _CANONICAL_STATUSES}
    other = 0
    for s in statuses:
        if s in counts:
            counts[s] += 1
        else:
            other += 1
    parts: list[str] = []
    for key in _CANONICAL_STATUSES:
        if counts[key]:
            parts.append(f"{counts[key]} {key}")
    if other:
        parts.append(f"{other} other")
    return ", ".join(parts)


def collect_layer_summaries(*, repo_root: Path, today_utc: date) -> list[LayerSummary]:
    """Casual-mode per-layer rollup over the FULL layer catalog.

    Diverges from `collect_status_rows` in two ways:
    - No filter on layer status. Casual mode wants the LLM to think about
      every layer including `introduced`-status ones (cognitive scaffolding
      doesn't depend on enforcement).
    - Handles `session_summary` strategy explicitly instead of raising.
    """
    layers_payload = _load_yaml(repo_root / "layers.yaml")
    summaries: list[LayerSummary] = []
    for layer in layers_payload["layers"]:
        scope_strategy_type = layer["scope_strategy"]["type"]
        if scope_strategy_type == "session_summary":
            scope_rows: list[StatusRow] = []
        else:
            scope_rows = _collect_scope_rows_for_layer(repo_root=repo_root, layer=layer, today_utc=today_utc)
        summaries.append(
            LayerSummary(
                layer_id=layer["id"],
                name=layer["name"],
                status=layer["status"],
                scope_rows=scope_rows,
                interpretation=_interpret_scope_rows(scope_rows=scope_rows, scope_strategy_type=scope_strategy_type),
            )
        )
    return summaries


def _render_status_row(row: StatusRow) -> str:
    parts = [f"{row.layer_id} scope={row.scope} status={row.status}"]
    formatted_time = _format_datetime(row.produced_at_utc)
    if formatted_time is not None:
        parts.append(f"produced_at={formatted_time}")
    if row.detail is not None:
        parts.append(f"detail={row.detail}")
    if row.evidence_path is not None:
        parts.append(f"evidence={row.evidence_path.as_posix()}")
    return " ".join(parts)


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Summarize the latest Keel evidence state for active pilot layers")
    parser.add_argument("--repo-root", type=Path, default=_REPO_ROOT)
    parser.add_argument("--date", help="UTC date to evaluate (YYYY-MM-DD). Defaults to today UTC.")
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Casual-mode rollup: one block per layer (full catalog) plus the recurring-review status.",
    )
    return parser


def _render_layer_summary(summary: LayerSummary) -> str:
    lines = [f"### {summary.layer_id} ({summary.name}) — status={summary.status}"]
    lines.append(f"interpretation: {summary.interpretation}")
    for row in summary.scope_rows:
        lines.append(f"  - {_render_status_row(row)}")
    return "\n".join(lines)


def _render_recurring_reviews_block(*, repo_root: Path, today_utc: date) -> str:
    """Append the recurring-review status to the casual rollup.

    Why bundle here: the casual operator wants ONE paste-able rollup, not
    two separate command outputs. The strict cron path keeps
    `make keel-reviews-status` separate because it's a non-blocking
    heartbeat that's checked on its own schedule.
    """
    # Local import: keep the strict-mode `keel-status` start-up time free of
    # the review-schedule dep when --summary is not used.
    from core.keel_review_schedule import (
        compute_review_status,
        format_status_table,
        load_schedule,
    )

    schedule_path = repo_root / "keel_reviews.yaml"
    if not schedule_path.is_file():
        return "## Recurring reviews\n(no recurring reviews configured)"
    schedule = load_schedule(schedule_path)
    rows = compute_review_status(repo_root=repo_root, schedule=schedule, now_date=today_utc)
    return "## Recurring reviews\n" + format_status_table(rows)


def main(argv: list[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    repo_root = args.repo_root.resolve()
    today_utc = date.fromisoformat(args.date) if args.date else _today_utc()
    if args.summary:
        summaries = collect_layer_summaries(repo_root=repo_root, today_utc=today_utc)
        for summary in summaries:
            print(_render_layer_summary(summary))
            print()
        print(_render_recurring_reviews_block(repo_root=repo_root, today_utc=today_utc))
        return 0
    rows = collect_status_rows(repo_root=repo_root, today_utc=today_utc)
    for row in rows:
        print(_render_status_row(row))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
