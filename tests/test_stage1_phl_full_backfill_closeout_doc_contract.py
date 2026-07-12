from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CLOSEOUT_PATH = REPO_ROOT / "docs" / "reference" / "research" / "phl_full_backfill_closeout_2026_04_29.md"


def test_stage1_phl_closeout_pins_exact_probe_command_shape_and_prior_facts() -> None:
    closeout_text = CLOSEOUT_PATH.read_text(encoding="utf-8")

    required_command_tokens = (
        "ssh -i /Users/stuart/repos/gridl-dev/civibus_dev/.secret/hetzner_ssh_key.txt",
        "root@5.78.207.136 <<'REMOTE_EOF'",
        "docker exec -i infra-db-1 psql -U civibus -d civibus",
    )
    for token in required_command_tokens:
        assert token in closeout_text

    required_prior_fact_tokens = (
        "campfin_contributions: count(*)=1,192,300, max(transaction_date)=2026-03-30T04:00:00Z.",
        "campfin_expenditures: count(*)=231,438, max(transaction_date)=2026-03-30T04:00:00Z.",
        "core.source_record pre-backfill count: 116 for contributions owner row.",
        "PHL pass-2 relational footprint pre-backfill: phl_filings=10, phl_transactions=10, phl_committees=10.",
        "Freshness re-verdict (2026-04-26): stable ~27-day lag, below weekly minimum launch policy.",
    )
    for token in required_prior_fact_tokens:
        assert token in closeout_text


def test_stage3_failure_evidence_section_present() -> None:
    closeout_text = CLOSEOUT_PATH.read_text(encoding="utf-8")

    required_stage3_tokens = (
        "## Stage 3 detached-lane failure evidence (2026-04-29)",
        "2026-04-29T06:09:37Z",
        "the earlier `2026-04-29T02:09:37Z` value was a local-time/UTC labeling mistake",
        "after the `2026-04-29T05:47:10Z` Stage 2 dispatch",
        "RuntimeError: Unable to connect to PostgreSQL at localhost:5433/civibus",
        "/var/log/civibus/phl_contributions_20260429.log",
        "/var/log/civibus/phl_expenditures_20260429.log",
        "Stage 3 stops here without relaunching lanes or claiming idempotency.",
    )
    for token in required_stage3_tokens:
        assert token in closeout_text


def test_stage3_rerun_detached_probe_section_present() -> None:
    closeout_text = CLOSEOUT_PATH.read_text(encoding="utf-8")

    required_stage3_rerun_tokens = (
        "## Stage 3 idempotency rerun detached status (2026-04-29)",
        "Probe timestamp (UTC): `2026-04-29T06:40:42Z`",
        "POSTGRES_HOST=127.0.0.1",
        "POSTGRES_PORT=5432",
        "3902647 (contributions): no longer present in `ps` during this bounded probe.",
        "3902648 (expenditures): still active with `stat=Sl`",
        "Both rerun log files remained zero-byte files with `0` lines",
        "Stage 3 remains in-progress for detached rerun completion evidence; no idempotency delta claim is made in this update.",
    )
    for token in required_stage3_rerun_tokens:
        assert token in closeout_text
