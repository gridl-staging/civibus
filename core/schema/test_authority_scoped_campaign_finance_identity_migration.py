from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_FILE = (
    REPO_ROOT / "domains" / "campaign_finance" / "schema" / "migrations" / "2026_08_28_authority_scoped_identity.sql"
)


def _compact(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").lower().split())


def test_authority_identity_migration_is_a_bounded_phased_forward_delta() -> None:
    sql = _compact(MIGRATION_FILE)

    assert "begin;" not in sql
    assert "commit;" not in sql
    assert "-- civibus-phase: prepare" in sql
    assert "-- civibus-phase: backfill.transaction" in sql
    assert "-- civibus-phase: validate.ck_transaction_native_id_nonblank" in sql
    assert "-- civibus-phase: cutover" in sql
    assert "create unique index concurrently" in sql
    assert "add column if not exists filing_authority_type text" in sql
    assert "add column if not exists filing_authority_code text" in sql
    assert "create or replace function core.enforce_source_record_supersession_scope()" in sql
    assert "drop index if exists core.uq_source_record_id_data_source" in sql


def test_authority_identity_migration_backfills_every_shared_native_owner() -> None:
    sql = _compact(MIGRATION_FILE)

    for table, native_column, compatibility_column in (
        ("committee", "native_committee_id", "fec_committee_id"),
        ("candidate", "native_candidate_id", "fec_candidate_id"),
        ("filing", "native_filing_id", "filing_fec_id"),
        ("transaction", "native_transaction_id", "source_record.source_record_key"),
    ):
        assert f"update cf.{table}" in sql
        assert native_column in sql
        assert compatibility_column in sql

    assert "state:wa" not in sql
    assert "then 'state'" in sql
    assert "then 'municipality'" in sql
    assert "else 'named_other'" in sql


def test_authority_identity_migration_replaces_global_uniqueness_with_scoped_keys() -> None:
    sql = _compact(MIGRATION_FILE)

    for table, native_column in (
        ("committee", "native_committee_id"),
        ("candidate", "native_candidate_id"),
        ("filing", "native_filing_id"),
        ("transaction", "native_transaction_id"),
    ):
        assert f"uq_{table}_authority_native_id" in sql
        assert f"on cf.{table} (data_source_id, {native_column}) where data_source_id is not null" in sql
        assert f"ck_{table}_authority_native_pair" in sql

    assert "on cf.transaction (sub_id) where data_source_id is null and sub_id is not null" in sql
    assert "create or replace function cf.enforce_source_record_scope()" in sql
    assert "array['committee', 'candidate', 'filing', 'transaction']" in sql
    assert "trg_%1$s_source_scope_insert" in sql


def test_authority_identity_migration_scopes_supersession_and_amendment_edges() -> None:
    sql = _compact(MIGRATION_FILE)

    assert "fk_source_record_superseded_scope" in sql
    assert "trg_source_record_supersession_scope_update" in sql
    assert "fk_filing_amended_from_scope" in sql
    assert "trg_filing_amendment_scope_update" in sql
    assert "fk_transaction_amended_by_scope" in sql
    assert "trg_transaction_amendment_scope_update" in sql
