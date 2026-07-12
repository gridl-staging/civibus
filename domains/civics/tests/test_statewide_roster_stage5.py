from __future__ import annotations

import json
import inspect
from pathlib import Path

import psycopg
import pytest

from domains.civics.tests.statewide_roster_stage5_support import (
    STAGE5_LOCAL_PROOF_ARTIFACT_RELATIVE_PATH,
    build_stage5_local_proof_payload,
    canonical_stage5_local_proof_artifact_path,
    emit_stage5_local_proof_artifact,
)

pytestmark = pytest.mark.integration


def test_stage5_local_proof_emitter_defaults_to_canonical_artifact_path(tmp_path: Path) -> None:
    payload = {"combined_officeholding_total": 98}
    assert (
        canonical_stage5_local_proof_artifact_path()
        == Path(__file__).resolve().parents[3] / STAGE5_LOCAL_PROOF_ARTIFACT_RELATIVE_PATH
    )
    emitted_path = emit_stage5_local_proof_artifact(payload=payload, output_path=tmp_path / "proof.json")
    assert emitted_path == tmp_path / "proof.json"


def test_stage5_local_proof_payload_builder_is_rerunnable_against_existing_stage5_snapshots(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    build_stage5_local_proof_payload(
        db_conn,
        tmp_path,
        expect_clean_first_run=True,
    )
    payload = build_stage5_local_proof_payload(
        db_conn,
        tmp_path,
        expect_clean_first_run=False,
    )

    assert payload["combined_officeholding_total"] == 98
    assert payload["idempotency"]["second_run_reused_source_record_ids"] is True


def test_stage5_local_proof_module_avoids_pytest_owned_loader_test_imports() -> None:
    import domains.civics.tests.statewide_roster_stage5_proof_emitter as emitter_module

    source = inspect.getsource(emitter_module)
    assert "test_loader" not in source
    assert "pytest" not in source


def test_stage5_support_reuses_loader_helper_owner_without_duplicates() -> None:
    from domains.civics.loaders.official_rosters import test_loader as loader_test_module

    source = inspect.getsource(loader_test_module)
    assert "def _select_counts_for_source(" not in source
    assert "def _seed_person_names(" not in source
    assert "def _write_senate_fixture(" not in source
    assert "def _resolve_snapshot_stats(" not in source


def test_statewide_roster_stage5_proof_and_idempotency(db_conn: psycopg.Connection, tmp_path: Path) -> None:
    evidence_path = tmp_path / "stage5_statewide_roster_local_proof.json"
    payload = build_stage5_local_proof_payload(db_conn, tmp_path, expect_clean_first_run=True)
    emit_stage5_local_proof_artifact(payload=payload, output_path=evidence_path)
    assert json.loads(evidence_path.read_text(encoding="utf-8"))["combined_officeholding_total"] == 98
