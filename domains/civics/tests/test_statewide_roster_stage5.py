from __future__ import annotations

import json
import inspect
from pathlib import Path

import psycopg
import pytest

from domains.civics.tests.statewide_roster_stage5_support import (
    EXPECTED_OFFICEHOLDING_COUNTS_BY_SOURCE,
    STAGE5_LOCAL_PROOF_ARTIFACT_RELATIVE_PATH,
    build_stage5_local_proof_payload,
    canonical_stage5_local_proof_artifact_path,
    emit_stage5_local_proof_artifact,
    fixture_for_source_id,
    harvest_source_from_fixture,
    register_roster_pilot_sources,
    select_counts_for_source,
    seed_persons_for_sources,
    stage5_sources_by_id,
    write_nc_senate_fixture,
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


@pytest.mark.parametrize("source_id,expected_count", EXPECTED_OFFICEHOLDING_COUNTS_BY_SOURCE.items())
def test_stage2_statewide_sources_harvest_expected_officeholdings(
    db_conn: psycopg.Connection,
    tmp_path: Path,
    source_id: str,
    expected_count: int,
) -> None:
    register_roster_pilot_sources(db_conn)
    seed_persons_for_sources(db_conn, tmp_path)
    template = stage5_sources_by_id()[source_id]

    result = harvest_source_from_fixture(
        db_conn,
        source_id=source_id,
        fixture_path=fixture_for_source_id(source_id, tmp_path),
        dry_run=False,
    )

    assert result.body_key == template.body_key
    assert result.member_count == expected_count
    assert result.resolved_member_count == expected_count
    assert result.unresolved_member_count == 0
    assert result.officeholding_upserts == expected_count


def test_nc_senate_harvest_rejects_live_duplicate_district_shape(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    register_roster_pilot_sources(db_conn)
    fixture_path = tmp_path / "nc_senate_duplicate_districts.html"
    write_nc_senate_fixture(fixture_path, include_live_duplicate_districts=True)

    with pytest.raises(
        ValueError,
        match=r"nc_senate roster has multiple current members for districts: 18, 23, 34",
    ):
        harvest_source_from_fixture(
            db_conn,
            source_id="nc_senate",
            fixture_path=fixture_path,
            dry_run=False,
        )

    assert select_counts_for_source(db_conn, "nc_senate") == (0, 0, 0)
