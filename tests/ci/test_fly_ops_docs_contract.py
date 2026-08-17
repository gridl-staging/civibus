"""Contract tests for the Fly operations SSOT and open-work ledger."""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest


pytestmark = pytest.mark.dev_repo_only(
    private_asset="private Fly ops docs and ledgers: ROADMAP.md, PROJECT_OVERVIEW.md, docs/live-state/",
    owner="Fly ops documentation and private open-work ledger",
)


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNBOOK_PATH = REPO_ROOT / "docs/howto/operations/fly_deployment_runbook.md"
LIVE_STATE_PATH = REPO_ROOT / "docs/live-state/2026_07_07_lane1_fly_probe.md"
ROADMAP_PATH = REPO_ROOT / "ROADMAP.md"
PROJECT_OVERVIEW_PATH = REPO_ROOT / "PROJECT_OVERVIEW.md"
CAMPAIGN_FINANCE_REFRESH_RUNBOOK_PATH = REPO_ROOT / "docs/howto/operations/campaign-finance-refresh.md"
REFRESH_MACHINE_IMAGE_RECEIPT_PATH = REPO_ROOT / "docs/live-state/2026_07_31_refresh_machine_image_deploy.md"
SCHEDULER_BOUNDARY_RED_RECEIPT_PATH = REPO_ROOT / "docs/live-state/2026_07_28_refresh_scheduler_boundary.md"
SCHEDULER_BOUNDARY_NO_START_RECEIPT_PATH = REPO_ROOT / "docs/live-state/2026_08_04_refresh_scheduler_boundary.md"
SCHEDULER_BOUNDARY_RECHECK_CHECKLIST_PATH = REPO_ROOT / "chats/icg/aug04_pm_1_refresh_scheduler_boundary_recheck.md"
REFRESH_RELIABILITY_RECEIPT_PATH = REPO_ROOT / "docs/live-state/2026_08_03_refresh_partial_run_reliability.md"
END_PERSON_OUTAGE_RECEIPT_PATH = REPO_ROOT / "docs/live-state/2026_08_05_end_the_person_outage.md"
FEATURE_MATRIX_PATH = REPO_ROOT / "implemented/2026_07_18_federal_first_v1_landed_history_jul13_jul17.md"
FEATURE_MATRIX_JUL13_JUL17_DETAIL_PATH = (
    REPO_ROOT / "implemented/2026_07_18_federal_first_v1_landed_history_jul13_jul17_detail.md"
)
FEATURE_MATRIX_RECONCILIATIONS_JUL27_AUG03_PATH = (
    REPO_ROOT
    / "implemented/2026_07_18_federal_first_v1_landed_history_jul13_jul17_matrix_reconciliations_jul27_aug03_detail.md"
)
FEATURE_MATRIX_RECONCILIATIONS_AUG03_AUG05_PATH = (
    REPO_ROOT
    / "implemented/2026_07_18_federal_first_v1_landed_history_jul13_jul17_matrix_reconciliations_aug03_aug05_detail.md"
)
FEATURE_MATRIX_JUL19_JUL23_NARRATIVE_PATH = (
    REPO_ROOT / "implemented/2026_07_18_federal_first_v1_landed_history_jul13_jul17_narrative_jul19_jul23_detail.md"
)
FEATURE_MATRIX_ARCHIVE_PATHS = (
    FEATURE_MATRIX_PATH,
    FEATURE_MATRIX_JUL13_JUL17_DETAIL_PATH,
    FEATURE_MATRIX_RECONCILIATIONS_JUL27_AUG03_PATH,
    FEATURE_MATRIX_RECONCILIATIONS_AUG03_AUG05_PATH,
    FEATURE_MATRIX_JUL19_JUL23_NARRATIVE_PATH,
)
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


def _single_line_starting_with(text: str, prefix: str) -> str:
    rows = [line for line in text.splitlines() if line.startswith(prefix)]
    assert len(rows) == 1
    return rows[0]


def _split_markdown_row(row: str) -> list[str]:
    cells: list[str] = []
    current: list[str] = []
    escaped = False
    for character in row.strip().strip("|"):
        if escaped:
            current.append(character)
            escaped = False
        elif character == "\\":
            current.append(character)
            escaped = True
        elif character == "|":
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(character)
    cells.append("".join(current).strip())
    return cells


def _active_table_rows(roadmap_text: str) -> list[str]:
    active_section = roadmap_text.split("## Active", 1)[1].split("## Planned", 1)[0]
    in_active_ledger_table = False
    rows = []
    for line in active_section.splitlines():
        if line == "| Priority | Owner / seam | Open work | Gate |":
            in_active_ledger_table = True
            continue
        if not in_active_ledger_table:
            continue
        if not line.startswith("|"):
            break
        if line == "| --- | --- | --- | --- |":
            continue
        rows.append(line)
    return rows


def _lane10_digest_proof_script() -> str:
    receipt_text = _read_text(REFRESH_RELIABILITY_RECEIPT_PATH)
    start_marker = "# lane10_refresh_digest_proof_start"
    end_marker = "# lane10_refresh_digest_proof_end"
    assert receipt_text.count(start_marker) == 1
    assert receipt_text.count(end_marker) == 1
    return receipt_text.split(start_marker, 1)[1].split(end_marker, 1)[0].strip()


def _run_lane10_digest_proof(
    tmp_path: Path,
    *,
    expected_digest: str,
    live_digest: str,
) -> subprocess.CompletedProcess[str]:
    evidence_dir = tmp_path / "refresh_deploy_evidence"
    evidence_dir.mkdir()
    dev_sha = "0123456789abcdef0123456789abcdef01234567"
    (evidence_dir / "dev_sha.txt").write_text(f"{dev_sha}\n", encoding="utf-8")
    (evidence_dir / "image_digest.txt").write_text(f"{expected_digest}\n", encoding="utf-8")
    machines_path = tmp_path / "machines.json"
    repository, digest = live_digest.rsplit("@", 1)
    registry, repository_name = repository.split("/", 1)
    machines_path.write_text(
        json.dumps(
            [
                {
                    "id": "859e0da479e678",
                    "updated_at": "2099-01-01T00:00:00Z",
                    "image_ref": {
                        "registry": registry,
                        "repository": repository_name,
                        "digest": digest,
                    },
                }
            ]
        ),
        encoding="utf-8",
    )
    return subprocess.run(
        [sys.executable, "-", str(evidence_dir), str(machines_path), dev_sha],
        input=_lane10_digest_proof_script(),
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )


def test_fly_runbook_documents_current_refresh_machine_model() -> None:
    runbook_text = _read_text(RUNBOOK_PATH)
    refresh_runbook_text = _read_text(CAMPAIGN_FINANCE_REFRESH_RUNBOOK_PATH)

    required_fragments = (
        "civibus-refresh",
        "volume mounted at `/data`",
        "`python -m core.refresh.runner --scope federal`",
        "`civibus-db.internal:5432`",
        "database `civibus`",
        "Stage 3 Fly Refresh Deployment Evidence",
        "Automatic scheduled-start acceptance remains pending",
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

    assert REFRESH_MACHINE_IMAGE_RECEIPT_PATH.is_file(), (
        "docs/live-state/2026_07_31_refresh_machine_image_deploy.md must record the shipped refresh image"
    )
    for fragment in (
        "### Stage 3 Fly Refresh Deployment Evidence",
        "infra/scripts/deploy_refresh_machine.sh",
        "docs/live-state/2026_07_31_refresh_machine_image_deploy.md",
    ):
        assert fragment in refresh_runbook_text


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


def test_lane10_refresh_digest_proof_accepts_the_deployed_workflow_image(tmp_path: Path) -> None:
    digest = f"registry.fly.io/civibus-refresh@sha256:{'a' * 64}"

    result = _run_lane10_digest_proof(
        tmp_path,
        expected_digest=digest,
        live_digest=digest,
    )

    assert result.returncode == 0, result.stderr
    assert "refresh_machine_digest_match" in result.stdout


def test_lane10_refresh_digest_proof_rejects_old_image_after_unrelated_machine_update(
    tmp_path: Path,
) -> None:
    expected_digest = f"registry.fly.io/civibus-refresh@sha256:{'a' * 64}"
    stale_digest = f"registry.fly.io/civibus-refresh@sha256:{'b' * 64}"

    result = _run_lane10_digest_proof(
        tmp_path,
        expected_digest=expected_digest,
        live_digest=stale_digest,
    )

    assert result.returncode != 0
    assert "does not match workflow-proven digest" in result.stderr


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

    assert "Weekly refresh is configured on one Fly Machine" in runbook_text
    assert "Automatic scheduled-start acceptance remains pending" in runbook_text
    assert "Weekly refresh is implemented on Fly Machines" not in runbook_text
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


def test_scheduler_boundary_red_keeps_weekly_refresh_recheck_open() -> None:
    receipt_text = _read_text(SCHEDULER_BOUNDARY_RED_RECEIPT_PATH)
    no_start_receipt_text = _read_text(SCHEDULER_BOUNDARY_NO_START_RECEIPT_PATH)
    roadmap_text = _read_text(ROADMAP_PATH)
    runbook_text = _read_text(CAMPAIGN_FINANCE_REFRESH_RUNBOOK_PATH)
    successor_text = _read_text(SCHEDULER_BOUNDARY_RECHECK_CHECKLIST_PATH)
    matrix_text = _read_text(FEATURE_MATRIX_PATH)
    normalized_receipt_text = re.sub(r"\s+", " ", receipt_text)
    normalized_no_start_receipt_text = re.sub(r"\s+", " ", no_start_receipt_text)
    normalized_runbook_text = re.sub(r"\s+", " ", runbook_text)

    assert receipt_text.rstrip().endswith("AUTOMATIC_REFRESH_RED")
    assert (
        "The first failed condition was the required no-other-running-Civibus-lane attribution gate."
        in normalized_receipt_text
    )
    assert "`2026-08-04T18:53:21Z` through `2026-08-04T19:23:21Z`" in normalized_receipt_text
    weekly_refresh_row = _single_line_starting_with(roadmap_text, "| P0 | Weekly federal refresh")
    assert "**CLOSED" not in weekly_refresh_row
    for fragment in (
        "2026-07-28 attribution RED",
        "docs/howto/operations/campaign-finance-refresh.md",
        "chats/icg/aug04_pm_1_refresh_scheduler_boundary_recheck.md",
        "core/refresh/job_builders.py::build_refresh_plan()",
        "core.refresh_run",
    ):
        assert fragment in weekly_refresh_row
    for owner_text in (roadmap_text, runbook_text):
        assert "docs/live-state/2026_07_28_refresh_scheduler_boundary.md" in owner_text
        assert "2026-08-04T18:53:21Z" in owner_text
        assert "2026-08-04T19:23:21Z" in owner_text
        assert "no-other-running-Civibus-lane attribution gate" in owner_text
    for fragment in (
        "### Automatic scheduler observation",
        "scheduler/host-originated rather than user/operator-originated",
        "same Machine reaching terminal `stopped` with `exit_code=0`",
        "matching federal `core.refresh_run` rows",
        "exact read-only SQL and output",
        "first failed condition",
    ):
        assert fragment in normalized_runbook_text
    for fragment in (
        "target `main` through Batman with `MATT_DIRECT=1`",
        "zero other running Civibus lanes",
        "absent before this watch: `docs/live-state/2026_08_04_refresh_scheduler_boundary.md`",
        "2026-08-04T18:53:21Z` through `2026-08-04T19:23:21Z",
        "docs/live-state/2026_08_04_refresh_scheduler_boundary.md",
        "no manual start, no deploy, and no production write",
        "docs/howto/operations/campaign-finance-refresh.md",
        "core/refresh/job_builders.py::build_refresh_plan()",
        "core.refresh_run",
    ):
        assert fragment in successor_text
    assert "zero running Civibus lanes" not in successor_text
    assert no_start_receipt_text.rstrip().endswith("AUTOMATIC_START_NOT_OBSERVED")
    first_failed_condition = "The first failed condition was the absence of a scheduler start event for Machine `859e0da479e678` by the `2026-08-04T19:23:21Z` deadline."
    next_recheck = "The next smallest read-only recheck is a Fly-only inspection of the same app and Machine event log to confirm whether Fly records a late scheduler start after the deadline."
    assert first_failed_condition in normalized_no_start_receipt_text
    assert next_recheck in normalized_no_start_receipt_text
    assert "**CLOSED" not in weekly_refresh_row
    for fragment in (
        "AUTOMATIC_START_NOT_OBSERVED",
        "docs/live-state/2026_08_04_refresh_scheduler_boundary.md",
        first_failed_condition,
        next_recheck,
        "docs/howto/operations/campaign-finance-refresh.md",
        "core/refresh/job_builders.py::build_refresh_plan()",
        "core.refresh_run",
        "infra/scripts/deploy_refresh_machine.sh",
        "infra/scripts/verify_refresh_machine.sh",
        "Exit **(2)**, the local masters-with-spine-skipped red test, remains unrun",
        "A second structural exit is added",
        "Superseded pre-deploy account",
    ):
        assert fragment in weekly_refresh_row
    for fragment in (
        "The next scheduled fire is **`2026-08-04T18:53:21Z`**",
        "automatic scheduler acceptance is still owed by the bounded",
        "Scheduled-fire observation stays owned by `chats/icg/jul31_2pm_12_observed_refresh_completion.md`",
        "Resolve to a single owner before 2026-08-04",
        "downstream database and public probes failed",
        "The two Wave-1 lanes did their jobs and the wrap-up step that connects them did not run.",
    ):
        assert fragment not in weekly_refresh_row
    matrix_row = _single_line_starting_with(matrix_text, "| Weekly auto-refresh (`civibus-refresh`, `--scope federal`)")
    matrix_cells = _split_markdown_row(matrix_row)
    assert len(matrix_cells) == 6
    assert matrix_cells[3] == "◐ — no scheduler start observed by the August 4 deadline"
    for fragment in (
        "AUTOMATIC_START_NOT_OBSERVED",
        "docs/live-state/2026_08_04_refresh_scheduler_boundary.md",
        first_failed_condition,
        "Live` remains `◐`",
        "no SQL or public-surface probe was eligible",
    ):
        assert fragment in matrix_row
    assert "scheduled fire unobserved" not in matrix_row
    assert "automatic scheduler acceptance is still owed by the bounded" not in matrix_row


def test_feature_matrix_history_split_preserves_owner_contract_and_continuations() -> None:
    archive_text_by_path = {path: _read_text(path) for path in FEATURE_MATRIX_ARCHIVE_PATHS}
    owner_text = archive_text_by_path[FEATURE_MATRIX_PATH]

    archive_section_marker_re = re.compile(
        r"^(?:## |\*\*(?:Reconciled|Re-reconciled|Corrected|Terminal|The lesson|Operator review))"
    )
    section_owner_by_marker: dict[str, Path] = {}
    for path, text in archive_text_by_path.items():
        for line in text.splitlines():
            if not archive_section_marker_re.match(line):
                continue
            assert line not in section_owner_by_marker, (
                f"archive section marker duplicated between {section_owner_by_marker[line].relative_to(REPO_ROOT)} "
                f"and {path.relative_to(REPO_ROOT)}: {line}"
            )
            section_owner_by_marker[line] = path

    expected_owner_links = (
        FEATURE_MATRIX_JUL13_JUL17_DETAIL_PATH.name,
        FEATURE_MATRIX_RECONCILIATIONS_JUL27_AUG03_PATH.name,
        FEATURE_MATRIX_RECONCILIATIONS_AUG03_AUG05_PATH.name,
        FEATURE_MATRIX_JUL19_JUL23_NARRATIVE_PATH.name,
    )
    for file_name in expected_owner_links:
        assert f"({file_name})" in owner_text

    moved_section_owners = {
        "## Jul13_3pm — Person money visualization system": FEATURE_MATRIX_JUL13_JUL17_DETAIL_PATH,
        "**Reconciled 2026-07-27 across the `jul25_pm` / `jul26_am` / `jul26_1pm` / `jul26_4pm` window.**": FEATURE_MATRIX_RECONCILIATIONS_JUL27_AUG03_PATH,
        "**Re-reconciled 2026-08-05 across the `aug03_8pm` batch closeout-after-donor-fix": FEATURE_MATRIX_RECONCILIATIONS_AUG03_AUG05_PATH,
        "## Jul22_9pm — Public-surface truth (8 lanes)": FEATURE_MATRIX_JUL19_JUL23_NARRATIVE_PATH,
        "## Jul23_pm — Sitemap recovery chain (R1–R3)": FEATURE_MATRIX_JUL19_JUL23_NARRATIVE_PATH,
    }
    for fragment, expected_path in moved_section_owners.items():
        assert fragment not in owner_text
        assert fragment in archive_text_by_path[expected_path]

    for path, text in archive_text_by_path.items():
        assert len(text.splitlines()) < 300, f"{path.relative_to(REPO_ROOT)} must stay below the 300-line cap"
        if path != FEATURE_MATRIX_PATH:
            assert f"`{FEATURE_MATRIX_PATH.name}`" in text


def test_end_the_person_outage_receipt_is_falsifiable() -> None:
    assert END_PERSON_OUTAGE_RECEIPT_PATH.is_file()
    receipt_text = _read_text(END_PERSON_OUTAGE_RECEIPT_PATH)

    required_fragments = (
        "PURPOSE:",
        "High-level goals:",
        "Out of scope:",
        "## Stage 1 — Source, preflight, smoke buckets, and donor warmers",
        "authorized_dev_sha=46f942e066667aff68a332941aa6e88e87367cd4",
        "curl -sS https://civibus.shareborough.com/api/health/version",
        '{"git_sha":"559f5509206f3a05ec49ec1d79bb7e3aa10ed89f","built_at":"2026-08-02T15:10:24Z"}',
        "curl -sS https://civibus.shareborough.com/version.json",
        '{"git_sha":"1e40e363074941b6c8ed7597063245beb30607d4","built_at":"2026-08-03T14:34:16Z"}',
        "curl -sS https://civibus.shareborough.com/api/health/content",
        '{"healthy":true}',
        "person_path=/person/d2944415-3ec6-47b0-b44f-2cd28ddfbc0b",
        "denominator=539",
        "person_status=500",
        "production_deploy.spec.ts:244",
        "production_deploy.spec.ts:279",
        "production_deploy.spec.ts:343",
        "production_finance_visuals.spec.ts:168",
        "production_finance_visuals.spec.ts:99",
        "production_finance_visuals.spec.ts:136",
        "primary_nav_nonempty.spec.ts",
        "smith 200 1.609322",
        "williams 200 2.237898",
        "johnson 200 2.049918",
        "brown 200 1.471079",
        "jones 200 1.856283",
        "## Stage 2 — Staging authorization",
        "Arm B",
        "3a5299f3b93e11e15c14c866d9be64a1a2a80865",
        "CI `31024375299`",
        "Integration `31024373588`",
        "historical committed staging manifest",
        "post-sync working manifest",
        "## Stage 3 — Production deploy path",
        "NOT RUN - no prod commit/push, therefore no matching Deploy run",
        "mirror changed: yes",
        "commit: not attempted",
        "push: not attempted",
        "afbfcb86c8177033b7ba7670df286ac2a6406786",
        "terminal_no_trigger_gap",
        "deployed_sha: not-shipped",
        "prod-sync-no-push",
        "## Stage 4 — Guard verdicts",
        "donor-rollup freshness guard",
        "NOT APPLICABLE - deploy did not ship",
        "uptime person-detail workflow guard",
        "FAIL - not live in prod mirror",
        "31031434191",
        "truthful live 500 comparison",
        "refresh-machine carry-forward guard",
        "NOT APPLICABLE - deploy_refresh did not run",
        "## Stage 5 — Donor rollup rebuild",
        "target `127.0.0.1:5701`",
        "database `civibus`",
        "writer gate `off`",
        "federal-donor-search-rollup",
        "completed_at=2026-08-05T18:07:40.184612Z",
        "e4616a8e3b13945c89d66206fc741eef085fb9259cb368d934fece14dfef6d34",
        "1011704",
        "1064009",
        "provenance count `1`",
        "build duration `250394 ms`",
        "2026-08-13T00:07:40.184612Z",
        "2026-08-13T18:07:40.184612Z",
        "five post-rebuild warmer results",
        "did not deploy the approaching-expiry guard",
        "merging this dev lane does not deploy production",
        "`debbie sync prod` can update the prod mirror worktree, but the production trigger is an explicit",
        "git -C /Users/stuart/repos/gridl-hq/civibus add/commit/push",
        "`.github/workflows/deploy.yml` triggers on push",
        'urllib.request.urlopen("https://civibus.shareborough.com/sitemap-person-0.xml", timeout=30)',
        "person_body=$(mktemp) && trap 'rm -f \"$person_body\"' EXIT",
        "curl -sS --max-time 30 -o \"$person_body\" -w '%{http_code} %{time_total}\\n'",
        "Path(sys.argv[1]).read_text()",
        "curl -sS -o /dev/null --max-time 30 -w 'smith %{http_code} %{time_total}\\n' 'https://civibus.shareborough.com/donors?q=smith&by=name'",
    )
    for fragment in required_fragments:
        assert fragment in receipt_text

    assert "merging this lane is itself a deploy trigger" not in receipt_text
    assert "debbie sync prod pushes `main` in `gridl-hq/civibus`" not in receipt_text
    assert "Python XML parser over" not in receipt_text
    assert "python3 final_production_probe" not in receipt_text
    assert "/tmp/civibus_stage6_person_body.html" not in receipt_text
    assert receipt_text.count("PERSON OUTAGE VERDICT") == 1
    verdict = receipt_text.split("PERSON OUTAGE VERDICT", 1)[1].splitlines()
    assert verdict[:7] == [
        "",
        "deployed_sha: not-shipped",
        "person_page_http: 500",
        "api_web_sha_agreement: no",
        "rollup_completed_at: 2026-08-05T18:07:40.184612Z",
        "donor_surface_max_seconds: 3.699923",
        (
            "Ship disposition: not shipped; Debbie did not push prod main, "
            "production still serves split API/web SHAs, and the person route remains HTTP 500."
        ),
    ]
    assert receipt_text.rstrip().endswith(verdict[6])


def test_active_table_stage6_owned_rows_are_single_line_and_unique_active_table() -> None:
    active_rows = _active_table_rows(_read_text(ROADMAP_PATH))

    assert active_rows
    for row in active_rows:
        assert len(_split_markdown_row(row)) == 4, row

    for row_id in (
        "row_id: undeployed delta",
        "row_id: donor-search-identity-resolution-regression",
        "row_id: donor-rollup-provenance-expiry",
    ):
        assert sum(row_id in row for row in active_rows) == 1


def test_aug03_batch_stage2_roadmap_reconciliation_is_falsifiable() -> None:
    roadmap_text = _read_text(ROADMAP_PATH)
    required_fragments = (
        "### `aug03_8pm` Stage 2 ledger reconciliation — 2026-08-05",
        "git merge-base --is-ancestor 5cb2b02da origin/main exit=0",
        "git merge-base --is-ancestor abf1557ecd309342355ef9511e049efe11c02a0e origin/main exit=0",
        "Deploy refresh machine run `30943871526` failed its post-update digest assertion",
        "weekly scheduled refresh did not fire at `2026-08-04T18:53:21Z`",
        "docs/live-state/2026_08_05_end_the_person_outage.md",
        "`row_id: undeployed delta`: OPEN; residual controlled by `prod-sync-no-push`",
        "terminal_no_trigger_gap",
        "person_page_http: 500",
        "`row_id: donor-search-identity-resolution-regression`: OPEN; query exits repaired, deploy/person exit unmet",
        "all five donor query specimens passed under the row's serving bounds",
        "the required deployed person-page HTTP 200 proof is still absent",
        "`row_id: donor-rollup-provenance-expiry`: OPEN; clock reset, observable warning guard unshipped",
        "completed_at=2026-08-05T18:07:40.184612Z",
        "Production donor search fails closed on a timer at 2026-08-13T18:07:40.184612Z",
        "approaching-expiry guard remains unshipped",
        "`row_id: candidate-money coverage`: RESOLVED 2026-08-04",
        "`row_id: unbounded-serving-queries`: CLASS OPEN",
        "`row_id: refresh-partial-run`: OPEN",
    )

    for fragment in required_fragments:
        assert fragment in roadmap_text

    donor_identity_line = next(
        line for line in roadmap_text.splitlines() if "`row_id: donor-search-identity-resolution-regression`" in line
    )
    assert "query exits repaired" in donor_identity_line
    assert "person-page HTTP 200 proof is still absent" in donor_identity_line
    assert "CLOSED" not in donor_identity_line

    undeployed_delta_line = next(line for line in roadmap_text.splitlines() if "`row_id: undeployed delta`" in line)
    assert "prod-sync-no-push" in undeployed_delta_line
    assert "person_page_http: 500" in undeployed_delta_line
    assert "**CLOSED" not in undeployed_delta_line

    provenance_expiry_line = next(
        line for line in roadmap_text.splitlines() if "`row_id: donor-rollup-provenance-expiry`" in line
    )
    assert "completed_at=2026-08-05T18:07:40.184612Z" in provenance_expiry_line
    assert "approaching-expiry guard remains unshipped" in provenance_expiry_line
    assert "CLOSED" not in provenance_expiry_line
    assert "fails closed on a timer at 2026-08-12T01:52:38Z" not in provenance_expiry_line


def test_project_overview_current_scope_matches_implemented_fly_refresh_model() -> None:
    overview_text = _read_text(PROJECT_OVERVIEW_PATH)

    assert "federal-first" in overview_text
    assert "543 elected federal officials" in overview_text
    assert "Fly self-managed Postgres" in overview_text
    assert "scheduled Fly machine `civibus-refresh`" in overview_text
