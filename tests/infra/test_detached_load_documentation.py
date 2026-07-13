from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNBOOK = REPO_ROOT / "docs/howto/operations/long_running_ingest_discipline.md"
AUTHORING_GUIDE = REPO_ROOT / "chats/icg/_authoring_guide.md"
ROADMAP = REPO_ROOT / "ROADMAP.md"


def _markdown_links(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    links = re.findall(r"(?<!!)\[[^\]]+\]\(([^)]+)\)", text)
    return [link for link in links if not link.startswith(("http://", "https://", "mailto:", "#"))]


def test_detached_load_docs_use_one_canonical_runner_contract() -> None:
    runbook = RUNBOOK.read_text(encoding="utf-8")
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


def test_changed_detached_load_doc_links_resolve() -> None:
    checked_paths = [RUNBOOK, AUTHORING_GUIDE]

    missing_links: list[str] = []
    for path in checked_paths:
        for link in _markdown_links(path):
            target = (path.parent / link.split("#", 1)[0]).resolve()
            if not target.exists():
                missing_links.append(f"{path.relative_to(REPO_ROOT)} -> {link}")

    assert missing_links == []
