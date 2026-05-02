"""
Stub summary for /Users/stuart/parallel_development/civibus_dev/mar21_01_fec_pipeline_hardening/civibus_dev/domains/campaign_finance/jurisdictions/states/NC/scraper/cli_test_support.py.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import psycopg
import pytest

SAMPLE_TRANSACTIONS = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "transaction_export_sample.csv"
SAMPLE_COMMITTEE_DOCS = (
    Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "committee_document_export_sample.csv"
)
SAMPLE_IE_DOCUMENT_INDEX = (
    Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "cfdoclkup_ie_document_index_sample_2026_04_18.csv"
)


def _build_path_args(path: Path, data_type: str, *extra_args: str) -> list[str]:
    return ["--path", str(path), "--data-type", data_type, *extra_args]


def build_transaction_path_args(*extra_args: str) -> list[str]:
    return _build_path_args(SAMPLE_TRANSACTIONS, "transactions", *extra_args)


def build_committee_document_path_args(*extra_args: str) -> list[str]:
    return _build_path_args(SAMPLE_COMMITTEE_DOCS, "committee-documents", *extra_args)


def build_ie_document_index_path_args(*extra_args: str) -> list[str]:
    return _build_path_args(SAMPLE_IE_DOCUMENT_INDEX, "ie-document-index", *extra_args)


def build_download_transaction_args(
    *extra_args: str,
    committee_id: str | None = "C12345",
    committee_name: str | None = None,
    output_path: str | None = "/tmp/nc-transactions.csv",
    date_from: str = "01/01/2024",
    date_to: str = "01/31/2024",
) -> list[str]:
    if committee_id is None and committee_name is None:
        raise ValueError("committee_id or committee_name is required")

    committee_filters: list[str] = []
    if committee_id is not None:
        committee_filters.extend(["--committee-id", committee_id])
    if committee_name is not None:
        committee_filters.extend(["--committee-name", committee_name])

    output_path_args: list[str] = []
    if output_path is not None:
        output_path_args.extend(["--output-path", output_path])

    return [
        "--download",
        "--data-type",
        "transactions",
        "--date-from",
        date_from,
        "--date-to",
        date_to,
        *output_path_args,
        *committee_filters,
        *extra_args,
    ]


def build_orchestrate_args(*extra_args: str) -> list[str]:
    return [
        "--orchestrate-committees",
        "--data-type",
        "transactions",
        "--window-start",
        "2025-01-01",
        "--window-end",
        "2025-01-31",
        *extra_args,
    ]


_TEST_REGISTRY_DATA_SOURCE_NAME = "NC Test Registry Source"


def create_minimal_registry(conn: psycopg.Connection, rows: list[dict[str, object]]) -> None:
    """Seed the production cf.nc_committee_registry schema with test rows.

    Why this is not a separate test schema: db_conn fixtures connect to the live
    civibus DB which already has the canonical cf.nc_committee_registry table.
    A parallel "minimal" schema would diverge from prod (and did, until 2026-04-25
    when the divergence let two real bugs ship — is_active GENERATED column missing
    in prod, and orchestrator passing sboe_id where org_group_id was expected).

    Each test runs inside a transaction (db_conn fixture uses BEGIN/ROLLBACK), so
    rows inserted here are rolled back at test exit. We delete any pre-existing
    rows first to keep the test deterministic regardless of prior live data state.

    is_active is GENERATED from status_desc, so callers that pass is_active=True
    are translated into status_desc='ACTIVE (NON-EXEMPT)' (the live prod canonical
    active value) and is_active=False into 'INACTIVE'. Caller-provided status_desc
    overrides the translation.
    """
    # Ensure the canonical schema exists (no-op when prod schema is already loaded;
    # raises a clear error when the canonical table is missing — we will not
    # silently create a divergent shim).
    schema_present = conn.execute(
        """
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'cf' AND table_name = 'nc_committee_registry'
        )
        """
    ).fetchone()
    assert schema_present is not None and schema_present[0], (
        "cf.nc_committee_registry must exist (load tables.sql before running these tests)"
    )

    # Clean any pre-existing rows in this test transaction. Safe because db_conn
    # fixture rolls back at test exit; production data is never affected.
    conn.execute("DELETE FROM cf.nc_orchestrator_progress")
    conn.execute("DELETE FROM cf.nc_committee_registry")

    # Ensure a test data source exists for the FK; idempotent via ON CONFLICT.
    data_source_row = conn.execute(
        """
        INSERT INTO core.data_source (domain, jurisdiction, name, source_url, source_format)
        VALUES ('campaign_finance', 'state/NC', %(name)s, 'https://test.local/nc-registry', 'csv')
        ON CONFLICT (domain, jurisdiction, name) DO UPDATE
            SET source_url = EXCLUDED.source_url
        RETURNING id
        """,
        {"name": _TEST_REGISTRY_DATA_SOURCE_NAME},
    ).fetchone()
    assert data_source_row is not None
    data_source_id = data_source_row[0]

    for index, row in enumerate(rows, start=1):
        org_group_id = row.get("org_group_id", index)
        # Translate is_active -> status_desc since is_active is a generated column
        # in prod schema and cannot be inserted directly. Caller-provided status_desc
        # wins so tests can exercise specific status strings explicitly.
        is_active = bool(row.get("is_active", False))
        status_desc = row.get("status_desc")
        if status_desc is None:
            status_desc = "ACTIVE (NON-EXEMPT)" if is_active else "INACTIVE"
        conn.execute(
            """
            INSERT INTO cf.nc_committee_registry
                (org_group_id, sboe_id, committee_name, status_desc,
                 data_source_id, first_seen_at, last_seen_at, last_filing_date)
            VALUES
                (%(org_group_id)s, %(sboe_id)s, %(committee_name)s, %(status_desc)s,
                 %(data_source_id)s, NOW(), NOW(), %(last_filing_date)s)
            """,
            {
                "sboe_id": row["sboe_id"],
                "committee_name": row["committee_name"],
                "org_group_id": org_group_id,
                "status_desc": status_desc,
                "data_source_id": data_source_id,
                "last_filing_date": row.get("last_filing_date"),
            },
        )


def patch_download_resolution(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    cli_module: object,
) -> tuple[MagicMock, Path]:
    downloaded_path = tmp_path / "nc-download" / "transactions.csv"
    download_mock = MagicMock()
    monkeypatch.setattr(cli_module, "download_transaction_export_playwright", download_mock)

    return download_mock, downloaded_path
