"""Synthetic NY independent-expenditure fixture and its exact-key observers.

Test-only support. `sample_ie.csv` carries fixed identities — filer ids, filing
ids, trans numbers, payee names — so a rerun against the shared dev database
resolves to the rows a previous run committed and any exact cardinality
assertion over them is a race. This module owns a per-run copy whose every
identity-bearing column is unique, the loader-derived identities that copy
produces, and the observers that count its footprint from an independent
connection.

Identities are derived by calling the loader's own helpers over the written
rows, never by re-deriving row hashes or filing ids here, so the fixture cannot
drift from what a load actually writes. Cleanup is the jurisdiction-agnostic
owner in ``jurisdictions._bulk_fixture_support``; ``ensure_ny_data_source``
always resolves the canonical production NY data source, which cleanup must
leave untouched.
"""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple
from uuid import uuid4

from core.db import get_connection
from domains.campaign_finance.ingest.filing_loader import generate_synthetic_committee_id
from domains.campaign_finance.jurisdictions._bulk_fixture_support import (
    cleanup_scoped_fixture_rows,
    read_sample_csv,
    write_csv,
)
from domains.campaign_finance.jurisdictions.states.NY.scraper import (
    _load_column_for_semantic_path,
    _load_data_source_name_for_data_type,
)
from domains.campaign_finance.jurisdictions.states.NY.scraper.extract import extract_ny_expenditure
from domains.campaign_finance.jurisdictions.states.NY.scraper.load import (
    _NY_JURISDICTION,
    _build_ny_filing_fec_id,
    _ny_source_record_key,
    _ny_transaction_identifier,
)
from domains.campaign_finance.jurisdictions.states.NY.scraper.parse import parse_independent_expenditures

NY_IE_DATA_TYPE = "independent_expenditures"

_SAMPLE_IE_PATH = Path(__file__).parent / "test_fixtures" / "sample_ie.csv"

# Columns whose sample value the loader keys on, and which therefore have to be
# re-identified per run. An empty sample cell is left empty: filling it would
# flip the row's payee between the person and organization branches and cost the
# fixture its coverage of both.
_RE_IDENTIFIED_PATHS = (
    "committee.id",
    "ny.filer_previous_id",
    "committee.name",
    "ny.trans_number",
    "payee.org_name",
    "payee.first_name",
    "payee.last_name",
)
_STREET_PATH = "payee.address.street1"


def ie_column(semantic_path: str) -> str:
    """Return the IE CSV column for a semantic path — one lookup owner for fixture and tests."""
    return _load_column_for_semantic_path(NY_IE_DATA_TYPE, semantic_path)


class NYIEFixture(NamedTuple):
    """One generated NY IE CSV and the loader identities its rows produce."""

    csv_path: Path
    filer_ids: list[str]
    source_record_keys: list[str]
    filing_fec_ids: list[str]
    transaction_identifiers: list[str]

    @property
    def committee_fec_ids(self) -> list[str]:
        return [generate_synthetic_committee_id("NY", filer_id) for filer_id in self.filer_ids]


def _re_identify_row(row: dict[str, str | None], *, run_suffix: str, row_number: int) -> None:
    """Give one sample row identities no other run can produce."""
    for semantic_path in _RE_IDENTIFIED_PATHS:
        column = ie_column(semantic_path)
        existing = (row.get(column) or "").strip()
        if existing:
            row[column] = f"{existing}-{run_suffix}"
    # Row 1's sample street is empty, so its raw_address would be city/state/zip
    # alone and identical across runs. Every row gets its own street instead.
    row[ie_column(_STREET_PATH)] = f"{row_number} {run_suffix} Test Street"


def write_ny_ie_fixture(tmp_path: Path) -> NYIEFixture:
    """Write a per-run copy of sample_ie.csv and return the identities it will load as."""
    run_suffix = uuid4().hex[:12]
    rows = read_sample_csv(_SAMPLE_IE_PATH)
    for row_number, row in enumerate(rows, start=1):
        _re_identify_row(row, run_suffix=run_suffix, row_number=row_number)

    csv_path = tmp_path / f"ny_ie_{run_suffix}.csv"
    write_csv(csv_path, rows)

    parsed = [dict(row) for row in parse_independent_expenditures(csv_path)]
    return NYIEFixture(
        csv_path=csv_path,
        filer_ids=[row[ie_column("committee.id")] for row in parsed],
        source_record_keys=[_ny_source_record_key(row) for row in parsed],
        filing_fec_ids=[_build_ny_filing_fec_id(row, NY_IE_DATA_TYPE) for row in parsed],
        transaction_identifiers=[_ny_transaction_identifier(row, data_type=NY_IE_DATA_TYPE) for row in parsed],
    )


def cleanup_ny_ie_fixture(fixture: NYIEFixture) -> None:
    """Delete every row the fixture wrote, scoped to its own synthetic identities."""
    cleanup_scoped_fixture_rows(
        source_record_keys=fixture.source_record_keys,
        committee_fec_ids=fixture.committee_fec_ids,
    )


class _FixtureEntityIdentity(NamedTuple):
    """The entity identities one fixture's rows extract to."""

    person_names: list[str]
    payee_organization_names: list[str]
    raw_addresses: list[str]


def _fixture_entity_identity(fixture: NYIEFixture) -> _FixtureEntityIdentity:
    """Derive entity identities through the loader's own extractor, so they cannot drift."""
    extracted = [extract_ny_expenditure(dict(row)) for row in parse_independent_expenditures(fixture.csv_path)]
    return _FixtureEntityIdentity(
        person_names=[row["payee_person"].canonical_name for row in extracted if row["payee_person"] is not None],
        payee_organization_names=[row["payee_org"].canonical_name for row in extracted if row["payee_org"] is not None],
        raw_addresses=[row["address"].raw_address for row in extracted if row["address"] is not None],
    )


_FOOTPRINT_QUERIES: dict[str, str] = {
    "source_record": "SELECT COUNT(*) FROM core.source_record WHERE source_record_key = ANY(%(source_record_keys)s)",
    "filing": "SELECT COUNT(*) FROM cf.filing WHERE filing_fec_id = ANY(%(filing_fec_ids)s)",
    "transaction": """
        SELECT COUNT(*) FROM cf.transaction
        WHERE transaction_identifier = ANY(%(transaction_identifiers)s)
    """,
    "committee": "SELECT COUNT(*) FROM cf.committee WHERE fec_committee_id = ANY(%(committee_fec_ids)s)",
    "person": "SELECT COUNT(*) FROM core.person WHERE canonical_name = ANY(%(person_names)s)",
    "organization": """
        SELECT COUNT(*) FROM core.organization
        WHERE canonical_name = ANY(%(payee_organization_names)s)
           OR identifiers ->> 'ny_filer_id' = ANY(%(filer_ids)s)
    """,
    "address": "SELECT COUNT(*) FROM core.address WHERE raw_address = ANY(%(raw_addresses)s)",
}


def fixture_row_counts(fixture: NYIEFixture) -> dict[str, int]:
    """Count every row class the fixture's load writes, from an independent connection.

    Counted by the fixture's own identities rather than by provenance link:
    cleanup deletes the links, so a link-scoped count reads zero however many
    rows leaked.
    """
    parameters = {
        "source_record_keys": fixture.source_record_keys,
        "filing_fec_ids": fixture.filing_fec_ids,
        "transaction_identifiers": fixture.transaction_identifiers,
        "committee_fec_ids": fixture.committee_fec_ids,
        "filer_ids": fixture.filer_ids,
        **_fixture_entity_identity(fixture)._asdict(),
    }
    observer_conn = get_connection()
    try:
        with observer_conn.cursor() as cursor:
            counts = {}
            for row_class, query in _FOOTPRINT_QUERIES.items():
                cursor.execute(query, parameters)
                counts[row_class] = cursor.fetchone()[0]
        return counts
    finally:
        observer_conn.close()


def canonical_ie_data_source_count() -> int:
    """Count the canonical NY IE `core.data_source` rows cleanup must never delete."""
    observer_conn = get_connection()
    try:
        with observer_conn.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM core.data_source WHERE jurisdiction = %s AND name = %s",
                (_NY_JURISDICTION, _load_data_source_name_for_data_type(NY_IE_DATA_TYPE)),
            )
            return cursor.fetchone()[0]
    finally:
        observer_conn.close()
