from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNBOOK = REPO_ROOT / "docs/howto/operations/long_running_ingest_discipline.md"
PROTOCOLS = REPO_ROOT / "docs/protocols.md"
AUTHORING_GUIDE = REPO_ROOT / "chats/icg/_authoring_guide.md"
ROADMAP = REPO_ROOT / "ROADMAP.md"


def _markdown_links(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    links = re.findall(r"(?<!!)\[[^\]]+\]\(([^)]+)\)", text)
    return [link for link in links if not link.startswith(("http://", "https://", "mailto:", "#"))]


def test_detached_load_docs_use_one_canonical_runner_contract() -> None:
    runbook = RUNBOOK.read_text(encoding="utf-8")
    normalized_runbook = " ".join(runbook.split())
    runner_lifecycle = normalized_runbook.partition("## Runner Lifecycle")[2].partition("## Job State Contract")[0]
    job_state_contract = normalized_runbook.partition("## Job State Contract")[2].partition("## Progress Observation")[
        0
    ]
    supervisor_interpretation = normalized_runbook.partition("## Supervisor Interpretation")[2].partition(
        "## Open Questions"
    )[0]
    authoring_guide = AUTHORING_GUIDE.read_text(encoding="utf-8")
    roadmap = ROADMAP.read_text(encoding="utf-8")

    assert "infra/scripts/detached_runner.sh" in runbook
    assert "build/detached_jobs/" in runbook
    assert "detached_runner.sh start <job_name> -- <command...>" in runbook
    assert "detached_runner.sh status <job_name>" in runbook
    assert "detached_runner.sh wait <job_name> --poll-seconds N --timeout-seconds M" in runbook
    assert "detached_runner.sh stop <job_name>" in runbook
    assert "long_running_dispatch.sh" not in runbook
    assert "Foreground-Only No-Detach Rule" not in runbook
    assert "`pgid`: verified wrapper-led process group recorded at start" in job_state_contract
    assert "0600 atomic-write discipline as `pid` and `process_identity`" in job_state_contract
    assert "`setsid` when available, otherwise Python `start_new_session`" in runner_lifecycle
    assert (
        "start fails closed with a clear error and no non-isolated job becomes a later stop target" in runner_lifecycle
    )
    assert "Stop terminates the verified owned process group" in runner_lifecycle
    assert "signals the negative verified `pgid` with TERM, then escalates to KILL" in runner_lifecycle
    assert "`pgid` metadata is missing, mismatched, or reused" in runner_lifecycle
    assert "wrapper no longer leads its recorded group" in runner_lifecycle
    assert "required metadata is incomplete" in runner_lifecycle
    assert "wrapper has already disappeared before stop can verify ownership" in runner_lifecycle
    assert "targets only the verified owned process group recorded for that job" in supervisor_interpretation
    assert "Treat any stop refusal as a safety outcome" in supervisor_interpretation
    assert "missing, mismatched, or reused `pgid` state" in supervisor_interpretation
    assert "wrapper that no longer leads its recorded group" in supervisor_interpretation
    assert "incomplete metadata" in supervisor_interpretation
    assert "wrapper that is already gone before ownership can be revalidated" in supervisor_interpretation

    assert "projected over 30 minutes" in authoring_guide
    assert "infra/scripts/detached_runner.sh" in authoring_guide
    assert "ps -p <pid> -o command" in authoring_guide
    assert "mike_dev stuck-detector changes remain out of scope" in authoring_guide
    assert "nohup ... >> /var/log/civibus/<job>-<utc-ts>.log 2>&1 & disown" not in authoring_guide

    assert "Bulk-load execution home | CLOSED/PASS" in roadmap
    assert (
        "POSTGRES_PORT=5456 uv run --extra dev pytest domains/campaign_finance/ingest/test_bulk_cli_stage2_integration.py -q"
        in roadmap
    )
    assert "current blocker" not in roadmap


def test_protocols_routes_bulk_load_work_to_detached_discipline() -> None:
    # Derive the routed path from RUNBOOK so the runbook location has one owner in
    # this module; a rename edits that constant alone and this route stays checked.
    routed_path = RUNBOOK.relative_to(REPO_ROOT).as_posix()
    route_lines = [line for line in PROTOCOLS.read_text(encoding="utf-8").splitlines() if routed_path in line]

    assert len(route_lines) == 1
    route_line = route_lines[0]

    assert route_line.startswith("|")
    # Assert the work-shape keywords against the work-shape cell alone. Checking them
    # against the whole row would make "ingest" unfalsifiable, since the routed path
    # in the read-first cell already contains that substring.
    work_shape, read_first = (cell.strip() for cell in route_line.strip().strip("|").split("|"))
    work_shape_text = work_shape.lower()

    assert "bulk" in work_shape_text
    assert "ingest" in work_shape_text
    assert "refresh" in work_shape_text
    assert read_first == f"`{routed_path}`"
    assert "long_running_dispatch.sh" not in route_line


def test_changed_detached_load_doc_links_resolve() -> None:
    checked_paths = [RUNBOOK, AUTHORING_GUIDE]

    missing_links: list[str] = []
    for path in checked_paths:
        for link in _markdown_links(path):
            target = (path.parent / link.split("#", 1)[0]).resolve()
            if not target.exists():
                missing_links.append(f"{path.relative_to(REPO_ROOT)} -> {link}")

    assert missing_links == []
