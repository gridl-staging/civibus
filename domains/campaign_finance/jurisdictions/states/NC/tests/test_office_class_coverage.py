from __future__ import annotations

from pathlib import Path

import psycopg
import pytest
from psycopg.rows import dict_row

from domains.campaign_finance.ingest.text_utils import normalize_optional_text
from domains.campaign_finance.jurisdictions.states.NC.scraper.load import (
    ensure_nc_committee_document_data_source,
    load_nc_committee_documents,
    normalize_nc_report_key,
)
from domains.campaign_finance.jurisdictions.states.NC.scraper.parse import parse_committee_docs
from test_office_class_fixture_inventory import PER_OFFICE_CLASS_DIR, _in_scope_rows
from test_office_universe_inventory import EVIDENCE_TOKEN_BY_FIXTURE_SLUG

pytestmark = pytest.mark.integration


def _committee_export_path_for_slug(slug: str) -> Path:
    slug_dir = PER_OFFICE_CLASS_DIR / slug
    csv_files = sorted(slug_dir.glob("committee_export_*.csv"))
    assert len(csv_files) == 1, f"slug={slug} must contain exactly one committee_export_*.csv, found {csv_files}"
    return csv_files[0]


def _loadable_disclosure_lookup_size(rows: list[dict[str, str | None]]) -> int:
    loadable_keys: set[tuple[str, str]] = set()
    for row in rows:
        if normalize_optional_text(row.get("Doc Type")) != "Disclosure Report":
            continue
        if normalize_optional_text(row.get("Data")) is None:
            continue
        committee_sboe_id = normalize_optional_text(row.get("SBoE ID"))
        doc_name = normalize_optional_text(row.get("Doc Name"))
        year = normalize_optional_text(row.get("Year"))
        if committee_sboe_id is None or doc_name is None or year is None:
            continue
        loadable_keys.add((committee_sboe_id, normalize_nc_report_key(year, doc_name)))
    return len(loadable_keys)


@pytest.mark.parametrize(
    ("office_class", "fixture_slug"),
    [(row["office_class"], row["fixture_slug"]) for row in _in_scope_rows()],
)
def test_per_class_committee_exports_load_with_deterministic_filing_lookup(
    db_conn: psycopg.Connection,
    office_class: str,
    fixture_slug: str,
) -> None:
    committee_export_path = _committee_export_path_for_slug(fixture_slug)
    parsed_rows = list(parse_committee_docs(committee_export_path))

    assert parsed_rows, f"{office_class} fixture export must not be empty: {committee_export_path}"
    expected_lookup_size = _loadable_disclosure_lookup_size(parsed_rows)

    data_source_id = ensure_nc_committee_document_data_source(db_conn)
    first_result, first_lookup = load_nc_committee_documents(
        db_conn,
        committee_export_path,
        data_source_id=data_source_id,
    )
    second_result, second_lookup = load_nc_committee_documents(
        db_conn,
        committee_export_path,
        data_source_id=data_source_id,
    )

    assert first_result.inserted + first_result.skipped == len(parsed_rows)
    assert first_result.inserted > 0
    assert first_result.errors == 0
    assert len(first_lookup) == expected_lookup_size
    assert second_result.inserted == 0
    assert second_result.skipped == len(parsed_rows)
    assert second_result.errors == 0
    assert len(second_lookup) == expected_lookup_size


@pytest.mark.parametrize(
    ("office_class", "fixture_slug"),
    [(row["office_class"], row["fixture_slug"]) for row in _in_scope_rows()],
)
def test_per_class_exports_preserve_expected_office_evidence_tokens(
    office_class: str,
    fixture_slug: str,
) -> None:
    evidence_token = EVIDENCE_TOKEN_BY_FIXTURE_SLUG.get(fixture_slug)
    assert evidence_token is not None, f"{office_class} fixture slug missing Stage 1 evidence token owner"

    committee_export_path = _committee_export_path_for_slug(fixture_slug)
    parsed_rows = list(parse_committee_docs(committee_export_path))
    committee_names = [normalize_optional_text(row.get("Committee Name")) for row in parsed_rows]

    assert any(name and evidence_token in name for name in committee_names), (
        f"{office_class} fixture must include retained evidence token {evidence_token!r}"
    )


@pytest.mark.parametrize(
    ("office_class", "fixture_slug"),
    [(row["office_class"], row["fixture_slug"]) for row in _in_scope_rows()],
)
def test_per_class_loadable_disclosure_rows_materialize_filings(
    db_conn: psycopg.Connection,
    office_class: str,
    fixture_slug: str,
) -> None:
    committee_export_path = _committee_export_path_for_slug(fixture_slug)
    parsed_rows = list(parse_committee_docs(committee_export_path))
    expected_lookup_size = _loadable_disclosure_lookup_size(parsed_rows)
    assert expected_lookup_size > 0, f"{office_class} must retain at least one loadable disclosure row"

    data_source_id = ensure_nc_committee_document_data_source(db_conn)
    load_nc_committee_documents(
        db_conn,
        committee_export_path,
        data_source_id=data_source_id,
    )

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM cf.filing f
            JOIN core.source_record sr
              ON sr.id = f.source_record_id
            WHERE sr.data_source_id = %s
              AND f.report_type = 'Disclosure Report'
            """,
            (data_source_id,),
        )
        filing_count = cursor.fetchone()["count"]

    assert filing_count == expected_lookup_size
