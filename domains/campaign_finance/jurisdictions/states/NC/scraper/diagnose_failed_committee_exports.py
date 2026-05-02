from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any

import httpx

from . import download

# Stage 2 sampling is pinned to the exact shell recipe documented in the
# Stage 1 handoff: line-oriented NR%6==1 over the frozen cohort artifact.
# We keep that contract here so later stages reuse the exact same 10 IDs.
SAMPLE_RULE_DESCRIPTION = (
    "From the frozen Stage 1 cohort artifact text, skip the header line, "
    "select lines where 1-based NR % 6 == 1, keep lines whose first CSV field "
    "matches an NC SBoE committee id, then take the first 10."
)
SAMPLE_STRIDE = 6
DEFAULT_SAMPLE_SIZE = 10

SAMPLE_SELECTION_FILENAME = "sample_selection.json"
SAMPLE_DIAGNOSTICS_FILENAME = "sample_diagnostics.json"

ALLOWED_DISPOSITIONS = frozenset(
    {
        "recovered",
        "legitimately_empty",
        "portal_blocked",
        "unknown",
    }
)
_REQUIRED_ARTIFACT_KEYS = (
    "export_csv_path",
    "export_raw_path",
    "portal_html_path",
    "portal_screenshot_path",
)
_REQUIRED_DIAGNOSTIC_KEYS = (
    "sboe_id",
    "org_group_id",
    "committee_name",
    "attempt_count",
    "last_error",
    "disposition",
    "reason",
    "artifacts",
)
_SBOE_ID_PATTERN = re.compile(r"^[A-Z0-9]{3}-[A-Z0-9]+-C-\d{3}$")
_LEGITIMATE_EMPTY_PORTAL_MARKERS = (
    "results returned: 0",
    "no documents found.",
    "no 2026 org paperwork received",
)
_PORTAL_READY_MARKERS = (
    "results returned:",
    "no documents found.",
    "click on the link(s) below to view the document.",
)
_PORTAL_RESULTS_READY_TIMEOUT_MS = 30_000
_PORTAL_BLOCKED_MARKERS = (
    "access denied",
    "captcha",
    "challenge",
    "cloudflare",
    "forbidden",
    "http 401",
    "http 403",
    "http 429",
    "http 500",
    "http 503",
    "login",
)


@dataclass(frozen=True, slots=True)
class FailedCohortRow:
    sboe_id: str
    org_group_id: str
    committee_name: str
    attempt_count: int
    last_error: str


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Diagnose a deterministic 10-row sample of NC failed committee exports."
    )
    parser.add_argument(
        "--cohort-path",
        required=True,
        type=Path,
        help="Path to the frozen Stage 1 failed cohort CSV artifact.",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help="Output directory for sample_selection.json, sample_diagnostics.json, and per-committee artifacts.",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=DEFAULT_SAMPLE_SIZE,
        help=f"Number of sampled committees (default: {DEFAULT_SAMPLE_SIZE}).",
    )
    return parser.parse_args(argv)


def _select_sample_ids_from_cohort_text(
    cohort_text: str,
    *,
    sample_size: int = DEFAULT_SAMPLE_SIZE,
) -> list[str]:
    if sample_size <= 0:
        raise ValueError("sample_size must be positive")

    lines = cohort_text.splitlines()
    if len(lines) <= 1:
        raise ValueError("cohort artifact must contain header and at least one data line")

    selected_ids: list[str] = []
    for line_number, line in enumerate(lines[1:], start=1):
        if line_number % SAMPLE_STRIDE != 1:
            continue
        sboe_id = line.split(",", 1)[0].strip()
        if not _SBOE_ID_PATTERN.fullmatch(sboe_id):
            continue
        selected_ids.append(sboe_id)
        if len(selected_ids) >= sample_size:
            return selected_ids

    raise ValueError(
        f"Could not select {sample_size} sample ids from the frozen cohort text using NR % {SAMPLE_STRIDE} == 1"
    )


def _load_failed_cohort_rows(cohort_path: Path) -> list[FailedCohortRow]:
    with cohort_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        rows: list[FailedCohortRow] = []
        for row in reader:
            sboe_id = (row.get("sboe_id") or "").strip()
            org_group_id = (row.get("org_group_id") or "").strip()
            committee_name = row.get("committee_name") or ""
            attempt_count_raw = (row.get("attempt_count") or "").strip()
            last_error = row.get("last_error") or ""
            if not sboe_id or not org_group_id:
                continue
            rows.append(
                FailedCohortRow(
                    sboe_id=sboe_id,
                    org_group_id=org_group_id,
                    committee_name=committee_name,
                    attempt_count=int(attempt_count_raw),
                    last_error=last_error,
                )
            )
    return rows


def select_sample_rows_from_cohort(
    cohort_path: Path,
    *,
    sample_size: int = DEFAULT_SAMPLE_SIZE,
) -> list[FailedCohortRow]:
    cohort_text = cohort_path.read_text(encoding="utf-8")
    selected_ids = _select_sample_ids_from_cohort_text(cohort_text, sample_size=sample_size)

    rows_by_id = {row.sboe_id: row for row in _load_failed_cohort_rows(cohort_path)}
    missing_ids = [sboe_id for sboe_id in selected_ids if sboe_id not in rows_by_id]
    if missing_ids:
        raise ValueError(f"Missing sampled ids in cohort CSV rows: {missing_ids}")
    return [rows_by_id[sboe_id] for sboe_id in selected_ids]


def write_sample_selection_manifest(
    *,
    cohort_path: Path,
    sample_rows: list[FailedCohortRow],
    output_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "cohort_path": str(cohort_path),
        "sample_rule": SAMPLE_RULE_DESCRIPTION,
        "sample_size": len(sample_rows),
        "selected": [
            {
                "sboe_id": row.sboe_id,
                "org_group_id": row.org_group_id,
                "committee_name": row.committee_name,
                "attempt_count": row.attempt_count,
                "last_error": row.last_error,
            }
            for row in sample_rows
        ],
    }
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _classify_disposition(
    *,
    export_error: Exception | None,
    committee_export_csv_path: Path,
    portal_html: str,
    portal_error: Exception | None = None,
) -> tuple[str, str]:
    if committee_export_csv_path.exists() and committee_export_csv_path.read_bytes().strip():
        return ("recovered", "Committee export returned non-empty CSV data")

    if portal_error is not None:
        lowered_error = str(portal_error).lower()
        if any(marker in lowered_error for marker in _PORTAL_BLOCKED_MARKERS):
            return ("portal_blocked", f"Committee portal was blocked: {portal_error}")

    if export_error is None:
        return ("unknown", "Committee export did not produce a saved CSV despite no raised error")

    error_message = str(export_error)
    if "Committee export returned empty CSV" in error_message:
        normalized_portal_html = " ".join(portal_html.lower().split())
        if any(marker in normalized_portal_html for marker in _LEGITIMATE_EMPTY_PORTAL_MARKERS):
            return (
                "legitimately_empty",
                "Committee export is empty and portal page shows the documented NC empty-state markers",
            )
        if "click on the link(s) below to view the document." in normalized_portal_html:
            return ("recovered", "Portal page shows document links even though export returned empty CSV")
        results_count_match = re.search(r"results returned:\s*(\d+)", normalized_portal_html)
        if results_count_match and int(results_count_match.group(1)) > 0:
            return ("recovered", "Portal page shows one or more committee documents despite the empty CSV export")
        return ("unknown", "Committee export returned empty CSV without portal evidence that the committee is empty")

    return ("unknown", error_message)


def _capture_raw_export_response(
    *,
    org_group_id: str,
    committee_name: str,
    output_path: Path,
) -> None:
    url = download._build_committee_export_url(org_group_id, committee_name)
    with httpx.Client(timeout=download._REQUEST_TIMEOUT_SECONDS) as client:
        response = client.get(url)
        response.raise_for_status()
        output_path.write_bytes(response.content)


def _capture_committee_portal_artifacts(
    *,
    sboe_id: str,
    org_group_id: str,
    html_path: Path,
    screenshot_path: Path,
) -> str:
    download._require_playwright()
    url = download.build_committee_document_result_url(sboe_id=sboe_id, org_group_id=org_group_id)
    with download._sync_playwright() as playwright:  # type: ignore[misc]
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        try:
            browser_context = browser.new_context()
            try:
                page = browser_context.new_page()
                page.goto(url, wait_until="domcontentloaded")
                # DocumentGeneralResult HTML can load before the results summary.
                # Wait for a known-ready marker so snapshots match the rendered
                # committee state instead of a pre-results shell.
                page.wait_for_function(
                    """(readyMarkers) => {
                        const bodyText = (document.body && document.body.innerText
                            ? document.body.innerText
                            : ""
                        ).toLowerCase();
                        return readyMarkers.some((marker) => bodyText.includes(marker));
                    }""",
                    arg=list(_PORTAL_READY_MARKERS),
                    timeout=_PORTAL_RESULTS_READY_TIMEOUT_MS,
                )
                html = page.content()
                html_path.write_text(html, encoding="utf-8")
                page.screenshot(path=str(screenshot_path), full_page=True)
                return html
            finally:
                browser_context.close()
        finally:
            browser.close()


def _probe_sample_committee(
    *,
    sample_row: FailedCohortRow,
    output_dir: Path,
) -> dict[str, Any]:
    committee_dir = output_dir / sample_row.sboe_id
    committee_dir.mkdir(parents=True, exist_ok=True)

    committee_export_csv_path = committee_dir / "committee_export.csv"
    export_raw_path = committee_dir / "committee_export_response.bin"
    export_error_path = committee_dir / "committee_export_error.txt"
    portal_html_path = committee_dir / "committee_document_page.html"
    portal_screenshot_path = committee_dir / "committee_document_page.png"
    portal_error_path = committee_dir / "committee_document_page_error.txt"

    export_error: Exception | None = None
    try:
        download.download_committee_document_export(
            sample_row.org_group_id,
            sample_row.committee_name,
            committee_export_csv_path,
        )
    except Exception as error:  # pragma: no cover - exercised by live stage run, not local unit tests
        export_error = error
        export_error_path.write_text(str(error) + "\n", encoding="utf-8")
        try:
            _capture_raw_export_response(
                org_group_id=sample_row.org_group_id,
                committee_name=sample_row.committee_name,
                output_path=export_raw_path,
            )
        except Exception as raw_error:
            export_raw_path.write_text(f"raw export capture failed: {raw_error}\n", encoding="utf-8")

    portal_error: Exception | None = None
    try:
        portal_html = _capture_committee_portal_artifacts(
            sboe_id=sample_row.sboe_id,
            org_group_id=sample_row.org_group_id,
            html_path=portal_html_path,
            screenshot_path=portal_screenshot_path,
        )
    except Exception as portal_error:  # pragma: no cover - exercised by live stage run, not local unit tests
        portal_html = ""
        portal_error_path.write_text(str(portal_error) + "\n", encoding="utf-8")

    disposition, reason = _classify_disposition(
        export_error=export_error,
        committee_export_csv_path=committee_export_csv_path,
        portal_html=portal_html,
        portal_error=portal_error,
    )
    return {
        "sboe_id": sample_row.sboe_id,
        "org_group_id": sample_row.org_group_id,
        "committee_name": sample_row.committee_name,
        "attempt_count": sample_row.attempt_count,
        "last_error": sample_row.last_error,
        "disposition": disposition,
        "reason": reason,
        "artifacts": {
            "export_csv_path": str(committee_export_csv_path),
            "export_raw_path": str(export_raw_path),
            "portal_html_path": str(portal_html_path),
            "portal_screenshot_path": str(portal_screenshot_path),
        },
    }


def build_sample_diagnostics_payload(
    *,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    for row in rows:
        for required_key in _REQUIRED_DIAGNOSTIC_KEYS:
            if required_key not in row:
                raise ValueError(f"required key missing from diagnostic row: {required_key}")
        disposition = row["disposition"]
        if disposition not in ALLOWED_DISPOSITIONS:
            raise ValueError(f"disposition must be one of {sorted(ALLOWED_DISPOSITIONS)}")
        artifacts = row["artifacts"]
        if not isinstance(artifacts, dict):
            raise ValueError("required key missing from diagnostic row: artifacts")
        for artifact_key in _REQUIRED_ARTIFACT_KEYS:
            if artifact_key not in artifacts:
                raise ValueError(f"required artifact key missing from diagnostic row: {artifact_key}")
    return {
        "row_count": len(rows),
        "rows": rows,
    }


def run_failed_committee_export_diagnostics(
    *,
    cohort_path: Path,
    output_dir: Path,
    sample_size: int = DEFAULT_SAMPLE_SIZE,
) -> dict[str, Any]:
    sample_rows = select_sample_rows_from_cohort(cohort_path, sample_size=sample_size)
    output_dir.mkdir(parents=True, exist_ok=True)

    write_sample_selection_manifest(
        cohort_path=cohort_path,
        sample_rows=sample_rows,
        output_path=output_dir / SAMPLE_SELECTION_FILENAME,
    )

    diagnostics_rows = [
        _probe_sample_committee(sample_row=sample_row, output_dir=output_dir) for sample_row in sample_rows
    ]
    diagnostics_payload = build_sample_diagnostics_payload(rows=diagnostics_rows)
    diagnostics_path = output_dir / SAMPLE_DIAGNOSTICS_FILENAME
    diagnostics_path.write_text(json.dumps(diagnostics_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return diagnostics_payload


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    run_failed_committee_export_diagnostics(
        cohort_path=args.cohort_path,
        output_dir=args.output_dir,
        sample_size=args.sample_size,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
