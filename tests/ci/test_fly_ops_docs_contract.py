"""Contract tests for the Fly operations SSOT and open-work ledger."""

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNBOOK_PATH = REPO_ROOT / "docs/howto/operations/fly_deployment_runbook.md"
LIVE_STATE_PATH = REPO_ROOT / "docs/live-state/2026_07_07_lane1_fly_probe.md"
ROADMAP_PATH = REPO_ROOT / "ROADMAP.md"
PROJECT_OVERVIEW_PATH = REPO_ROOT / "PROJECT_OVERVIEW.md"
RUNNABLE_PASSWORD_DOC_PATHS = (
    REPO_ROOT / "docs/live-state/2026_07_07_lane6_schedule_a_sizing.md",
    REPO_ROOT / "docs/live-state/2026_07_07_lane7_local_load.md",
    REPO_ROOT / "docs/live-state/2026_07_08_stage5_fly_schedule_a_probe.md",
    REPO_ROOT / "docs/live-state/2026_07_09_lane4_local_full_load.md",
    REPO_ROOT / "docs/live-state/2026_07_09_schedule_a_full_scale_rehearsal.md",
    REPO_ROOT / "docs/live-state/2026_07_09_stage3_schedule_a_checkpoint_resume.md",
    REPO_ROOT / "docs/reference/keel/checklist.md",
    REPO_ROOT / "docs/reference/keel/roadmap.md",
    REPO_ROOT / "docs/reference/research/2026_04_27_l9_provenance_walk_launch_v1.md",
    REPO_ROOT / "docs/reference/research/irs_527_first_production_run_plan_2026_04_18.md",
    REPO_ROOT / "docs/reference/research/stage2-graph-foundations-closeout.md",
    REPO_ROOT / "docs/reference/research/stage4-checklist-item-investigation.md",
)

SECRET_SHAPED_FLY_IMPORT_RE = re.compile(
    r"POSTGRES_PASSWORD=<[a-z]+>.*flyctl secrets import"
    r"|flyctl secrets import.*POSTGRES_PASSWORD="
)
RUNNABLE_POSTGRES_PASSWORD_PLACEHOLDER_RE = re.compile(r"POSTGRES_PASSWORD=<[^>\n]+>")


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_fly_runbook_documents_current_refresh_machine_model() -> None:
    runbook_text = _read_text(RUNBOOK_PATH)

    required_fragments = (
        "civibus-refresh",
        "volume mounted at `/data`",
        "`python -m core.refresh.runner --scope federal`",
        "`civibus-db.internal:5432`",
        "database `civibus`",
        "Stage 3 Fly Refresh Deployment Evidence",
    )
    for fragment in required_fragments:
        assert fragment in runbook_text

    forbidden_fragments = (
        "scheduled GH Actions workflow running",
        "make refresh-cf-data --job-key-prefix federal-",
        "weekly-refresh cron resume",
    )
    for fragment in forbidden_fragments:
        assert fragment not in runbook_text


def test_fly_runbook_documents_current_deploy_workflow_model() -> None:
    runbook_text = _read_text(RUNBOOK_PATH)

    required_fragments = (
        "`gridl-hq/civibus`",
        "`superfly/flyctl-actions/setup-flyctl`",
        "`infra/fly/api.fly.toml`",
        "`infra/fly/web.fly.toml`",
        "`infra/fly/caddy.fly.toml`",
        "`SMOKE_MODE=production`",
        "`PROD_SMOKE_BASE_URL`",
    )
    for fragment in required_fragments:
        assert fragment in runbook_text

    forbidden_fragments = (
        "Hetzner-SSH-compose",
        "Deferred to here",
        "billing-coupled",
    )
    for fragment in forbidden_fragments:
        assert fragment not in runbook_text


def test_fly_runbook_password_guidance_points_to_pgpass_owners() -> None:
    runbook_text = _read_text(RUNBOOK_PATH)
    live_state_text = _read_text(LIVE_STATE_PATH)

    required_fragments = (
        "`infra/scripts/postgres_local.py::create_backup`",
        "`infra/scripts/postgres_local.py::restore_backup`",
        "`infra/scripts/backup_to_b2.sh`",
        "`.pgpass`",
        "`PGPASSFILE`",
        "`/Users/stuart/repos/gridl-dev/civibus_dev/.secret/civibus-fly.env`",
        "`KEY=VALUE`",
        "`flyctl secrets import -a civibus-db < /path/to/secretsfile`",
        "corrected Stage 5 rotation evidence at HEAD",
        "forbid secret-bearing argv",
        "`docker exec -e PGPASSWORD`",
        "shell history",
        "documented command strings",
    )
    for fragment in required_fragments:
        assert fragment in runbook_text

    forbidden_fragments = (
        "Stage 5 rotation evidence remains unresolved",
        'echo "POSTGRES_PASSWORD=<new>"',
    )
    for fragment in forbidden_fragments:
        assert fragment not in runbook_text

    assert not SECRET_SHAPED_FLY_IMPORT_RE.search(live_state_text)


def test_stage_owned_runnable_docs_do_not_publish_password_prefix_commands() -> None:
    offenders: list[str] = []
    for path in RUNNABLE_PASSWORD_DOC_PATHS:
        for line_number, line in enumerate(_read_text(path).splitlines(), start=1):
            if RUNNABLE_POSTGRES_PASSWORD_PLACEHOLDER_RE.search(line):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{line_number}: {line.strip()}")

    assert offenders == []


def test_roadmap_tracks_only_unresolved_stage4_and_rotation_work() -> None:
    roadmap_text = _read_text(ROADMAP_PATH)
    runbook_text = _read_text(RUNBOOK_PATH)

    assert "Weekly refresh is implemented on Fly Machines" in runbook_text
    assert "App `civibus-refresh`" in runbook_text
    assert "`deploy.yml` is implemented for Fly serving apps" in runbook_text
    assert "corrected Stage 5 rotation evidence at HEAD" in runbook_text
    assert "Stage 5 password-rotation evidence is resolved at HEAD" in roadmap_text
    assert "Stage 4 ops hygiene and Colima socket verification are resolved at HEAD" in roadmap_text
    assert "Public DNS cutover + go-live" in roadmap_text
    assert "Cloudflare API" in roadmap_text

    forbidden_fragments = (
        "Phase D weekly refresh cron",
        "P2 | Ops evidence hygiene",
        "P2 | Colima note",
        "`deploy.yml`→Fly rewrite",
        "switch container-exec pg tooling to `.pgpass`",
        "Stage 5 rotation evidence remains unresolved",
        "Stage 5 password-rotation evidence remains unresolved",
        'echo "POSTGRES_PASSWORD=<new>"',
    )
    for fragment in forbidden_fragments:
        assert fragment not in roadmap_text


def test_project_overview_current_scope_matches_implemented_fly_refresh_model() -> None:
    overview_text = _read_text(PROJECT_OVERVIEW_PATH)

    assert "federal-first" in overview_text
    assert "543 elected federal officials" in overview_text
    assert "Fly self-managed Postgres" in overview_text
    assert "scheduled Fly machine `civibus-refresh`" in overview_text
