from __future__ import annotations

from typing import Callable
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from core.db import get_connection
from core.types.python.models import compute_record_hash
from domains.campaign_finance.jurisdictions.states.GA.scraper import load as ga_load_module
from domains.campaign_finance.jurisdictions.states.GA.scraper.load import (
    LoadResult,
    ensure_ga_data_source,
    load_ga_contribution,
    load_ga_contributions,
    load_ga_contributions_with_filings,
    load_ga_expenditure,
    load_ga_expenditures,
    load_ga_expenditures_with_filings,
)
from domains.campaign_finance.jurisdictions.states.GA.scraper.load_test_support import (
    CONTRIBUTION_FIXTURE_PATH,
    EXPENDITURE_FIXTURE_PATH,
    build_unique_batch_row,
    candidate_person_count_for_source_record_key,
    cleanup_source_record_by_key,
    distinct_person_count_for_source_record_keys,
    entity_source_count,
    ga_data_source_count,
    json_compatible_raw_fields,
    parsed_contribution_rows,
    parsed_expenditure_rows,
    source_record_count_for_key,
    source_record_id_for_row,
)

pytestmark = pytest.mark.integration

_GABatchLoader = Callable[[psycopg.Connection, list[dict[str, object]]], LoadResult]
_GARowsFactory = Callable[[], list[dict[str, object]]]
_GASingleRowLoader = Callable[[psycopg.Connection, dict[str, object], UUID], bool]
_GA_SINGLE_ROW_LOADERS: dict[str, _GASingleRowLoader] = {
    "contributions": load_ga_contribution,
    "expenditures": load_ga_expenditure,
}


def _ga_record_hash(row: dict[str, object]) -> str:
    return compute_record_hash(json_compatible_raw_fields(row))


def _build_expected_ga_filing_fec_id(row: dict[str, object], data_type: str) -> str:
    filer_id = row.get("FilerID")
    filing_date = row.get("Date")
    assert isinstance(filer_id, str)
    assert isinstance(filing_date, str)
    filing_year = filing_date.split("-", maxsplit=1)[0]
    return f"GA-{filer_id}-{filing_year}-{data_type}"


def _build_unique_fixture_rows(
    rows: list[dict[str, object]],
    *,
    prefix: str,
) -> list[dict[str, object]]:
    return [build_unique_batch_row(row, prefix=f"{prefix}-{index}") for index, row in enumerate(rows, start=1)]


def _stub_ga_parser(
    monkeypatch: pytest.MonkeyPatch,
    *,
    parser_name: str,
    rows: list[dict[str, object]],
) -> None:
    monkeypatch.setattr(
        ga_load_module,
        parser_name,
        lambda _path: [dict(row) for row in rows],
    )


def _build_unique_ga_org_row(
    base_row: dict[str, object],
    *,
    prefix: str,
) -> dict[str, object]:
    unique_suffix = uuid4().hex[:8]
    row = dict(base_row)
    row["FilerID"] = f"{prefix}-filer-{unique_suffix}"
    row["Committee_Name"] = f"Review Committee {unique_suffix}"
    last_name = row.get("LastName")
    assert isinstance(last_name, str)
    row["LastName"] = f"{last_name} {unique_suffix}"
    address = row.get("Address")
    assert isinstance(address, str)
    row["Address"] = f"{address} Suite {unique_suffix}"
    return row


def _load_single_ga_row(
    db_conn: psycopg.Connection,
    row: dict[str, object],
    *,
    data_type: str,
) -> tuple[bool, UUID]:
    data_source_id = ensure_ga_data_source(db_conn, data_type)
    inserted = _GA_SINGLE_ROW_LOADERS[data_type](db_conn, row, data_source_id)
    return inserted, source_record_id_for_row(db_conn, data_source_id, row)


def _assert_load_result(
    result: LoadResult,
    *,
    inserted: int,
    skipped: int = 0,
    errors: int = 0,
) -> None:
    assert isinstance(result, LoadResult)
    assert result.inserted == inserted
    assert result.skipped == skipped
    assert result.errors == errors


def test_ensure_ga_data_source_is_idempotent_for_contributions(db_conn: psycopg.Connection) -> None:
    first_id = ensure_ga_data_source(db_conn, "contributions")
    second_id = ensure_ga_data_source(db_conn, "contributions")

    assert isinstance(first_id, UUID)
    assert second_id == first_id
    assert ga_data_source_count(db_conn, "contributions") == 1


def test_ensure_ga_data_source_creates_distinct_ids_by_transaction_type(
    db_conn: psycopg.Connection,
) -> None:
    contribution_source_id = ensure_ga_data_source(db_conn, "contributions")
    expenditure_source_id = ensure_ga_data_source(db_conn, "expenditures")

    assert contribution_source_id != expenditure_source_id


def test_ensure_ga_data_source_rejects_unsupported_transaction_type(
    db_conn: psycopg.Connection,
) -> None:
    with pytest.raises(ValueError, match="Unsupported GA transaction type"):
        ensure_ga_data_source(db_conn, "unsupported_transaction_type")


def test_load_ga_contribution_person_donor_creates_entities_and_roles(
    db_conn: psycopg.Connection,
) -> None:
    row = dict(parsed_contribution_rows()[0])
    row["FirstName"] = "Jane"
    row["LastName"] = "Doe"
    inserted, source_record_id = _load_single_ga_row(db_conn, row, data_type="contributions")

    assert inserted is True
    assert entity_source_count(db_conn, source_record_id, "person", "donor") == 1
    assert entity_source_count(db_conn, source_record_id, "organization", "recipient") == 1
    assert entity_source_count(db_conn, source_record_id, "address", "donor_address") == 1


def test_load_ga_contribution_org_donor_creates_contributor_org_not_person(
    db_conn: psycopg.Connection,
) -> None:
    row = _build_unique_ga_org_row(parsed_contribution_rows()[0], prefix="org-donor")
    inserted, source_record_id = _load_single_ga_row(db_conn, row, data_type="contributions")

    assert inserted is True
    assert entity_source_count(db_conn, source_record_id, "person", "donor") == 0
    assert entity_source_count(db_conn, source_record_id, "organization", "contributor") == 1


def test_load_ga_contribution_deduplicates_by_record_hash(db_conn: psycopg.Connection) -> None:
    row = build_unique_batch_row(parsed_contribution_rows()[0], prefix="dedupe")
    data_source_id = ensure_ga_data_source(db_conn, "contributions")

    first_insert = load_ga_contribution(db_conn, row, data_source_id)
    second_insert = load_ga_contribution(db_conn, row, data_source_id)

    assert first_insert is True
    assert second_insert is False

    source_record_key = _ga_record_hash(row)
    assert source_record_count_for_key(db_conn, "contributions", source_record_key) == 1


def test_load_ga_contribution_creates_candidate_entity_with_candidate_role(
    db_conn: psycopg.Connection,
) -> None:
    row = parsed_contribution_rows()[0]
    row["Candidate_FirstName"] = "Nora"
    row["Candidate_LastName"] = "Henderson"
    inserted, source_record_id = _load_single_ga_row(db_conn, row, data_type="contributions")

    assert inserted is True
    assert entity_source_count(db_conn, source_record_id, "person", "candidate") == 1


def test_load_ga_contribution_without_zip_does_not_merge_people_by_name_only(
    db_conn: psycopg.Connection,
) -> None:
    first_row = dict(parsed_contribution_rows()[0])
    second_row = dict(parsed_contribution_rows()[0])

    for index, row in enumerate((first_row, second_row), start=1):
        row["FirstName"] = "Jordan"
        row["LastName"] = "Lee"
        row["Address"] = ""
        row["City"] = ""
        row["State"] = ""
        row["Zip"] = ""
        row["FilerID"] = f"ga-review-filer-{index}"
        row["Committee_Name"] = f"Jordan Lee Committee {index}"

    data_source_id = ensure_ga_data_source(db_conn, "contributions")

    first_inserted = load_ga_contribution(db_conn, first_row, data_source_id)
    second_inserted = load_ga_contribution(db_conn, second_row, data_source_id)

    assert first_inserted is True
    assert second_inserted is True
    assert (
        distinct_person_count_for_source_record_keys(
            db_conn,
            "contributions",
            [
                _ga_record_hash(first_row),
                _ga_record_hash(second_row),
            ],
            "donor",
        )
        == 2
    )


def test_load_ga_contribution_person_provenance_chain_is_campaign_finance_state_ga(
    db_conn: psycopg.Connection,
) -> None:
    row = dict(parsed_contribution_rows()[0])
    row["FirstName"] = "Avery"
    row["LastName"] = "Jordan"
    inserted, _source_record_id = _load_single_ga_row(db_conn, row, data_type="contributions")

    assert inserted is True

    source_record_key = _ga_record_hash(row)
    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT ds.domain, ds.jurisdiction
            FROM core.person p
            JOIN core.entity_source es
              ON es.entity_type = 'person'
             AND es.entity_id = p.id
             AND es.extraction_role = 'donor'
            JOIN core.source_record sr
              ON sr.id = es.source_record_id
            JOIN core.data_source ds
              ON ds.id = sr.data_source_id
            WHERE sr.source_record_key = %s
            LIMIT 1
            """,
            (source_record_key,),
        )
        provenance_row = cursor.fetchone()

    assert provenance_row is not None
    assert provenance_row["domain"] == "campaign_finance"
    assert provenance_row["jurisdiction"] == "state/GA"


def test_load_ga_expenditure_person_payee_creates_entities_and_roles(
    db_conn: psycopg.Connection,
) -> None:
    row = dict(parsed_expenditure_rows()[0])
    row["FirstName"] = "Mina"
    row["LastName"] = "Carter"
    inserted, source_record_id = _load_single_ga_row(db_conn, row, data_type="expenditures")

    assert inserted is True
    assert entity_source_count(db_conn, source_record_id, "person", "payee") == 1
    assert entity_source_count(db_conn, source_record_id, "organization", "payer") == 1
    assert entity_source_count(db_conn, source_record_id, "address", "payee_address") == 1


def test_load_ga_expenditure_org_payee_creates_org_not_person(db_conn: psycopg.Connection) -> None:
    row = _build_unique_ga_org_row(parsed_expenditure_rows()[0], prefix="org-payee")
    inserted, source_record_id = _load_single_ga_row(db_conn, row, data_type="expenditures")

    assert inserted is True
    assert entity_source_count(db_conn, source_record_id, "person", "payee") == 0
    assert entity_source_count(db_conn, source_record_id, "organization", "payee") == 1


def test_load_ga_expenditure_deduplicates_by_record_hash(db_conn: psycopg.Connection) -> None:
    row = _build_unique_ga_org_row(parsed_expenditure_rows()[0], prefix="expenditure-dedupe")
    data_source_id = ensure_ga_data_source(db_conn, "expenditures")

    first_insert = load_ga_expenditure(db_conn, row, data_source_id)
    second_insert = load_ga_expenditure(db_conn, row, data_source_id)

    assert first_insert is True
    assert second_insert is False


@pytest.mark.parametrize(
    ("transaction_type", "loader", "rows"),
    [
        (
            "contributions",
            load_ga_contributions,
            lambda: [build_unique_batch_row(parsed_contribution_rows()[0], prefix="contribution")],
        ),
        (
            "expenditures",
            load_ga_expenditures,
            lambda: [build_unique_batch_row(parsed_expenditure_rows()[0], prefix="expenditure")],
        ),
    ],
)
def test_ga_batch_loaders_commit_when_connection_is_idle(
    transaction_type: str,
    loader: _GABatchLoader,
    rows: _GARowsFactory,
) -> None:
    batch_rows = rows()
    source_record_key = _ga_record_hash(batch_rows[0])

    try:
        connection = get_connection()
        try:
            result = loader(connection, batch_rows)
            _assert_load_result(result, inserted=1)
        finally:
            connection.close()

        verification_conn = get_connection()
        try:
            assert (
                source_record_count_for_key(
                    verification_conn,
                    transaction_type,
                    source_record_key,
                )
                == 1
            )
        finally:
            verification_conn.rollback()
            verification_conn.close()
    finally:
        cleanup_source_record_by_key(transaction_type, source_record_key)


def test_cleanup_source_record_by_key_preserves_shared_candidate_entity() -> None:
    candidate_suffix = uuid4().hex[:8]
    first_row = build_unique_batch_row(parsed_contribution_rows()[0], prefix="seed")
    second_row = build_unique_batch_row(parsed_contribution_rows()[0], prefix="cleanup")
    shared_candidate_last_name = f"Candidate{candidate_suffix}"

    for row in (first_row, second_row):
        row["Candidate_FirstName"] = "Shared"
        row["Candidate_LastName"] = shared_candidate_last_name
        row["Candidate_MiddleName"] = ""
        row["Candidate_Suffix"] = ""

    first_source_record_key = compute_record_hash(json_compatible_raw_fields(first_row))
    second_source_record_key = compute_record_hash(json_compatible_raw_fields(second_row))

    try:
        seed_conn = get_connection()
        try:
            result = load_ga_contributions(seed_conn, [first_row])
            _assert_load_result(result, inserted=1)
        finally:
            seed_conn.close()

        review_conn = get_connection()
        try:
            result = load_ga_contributions(review_conn, [second_row])
            _assert_load_result(result, inserted=1)
        finally:
            review_conn.close()

        cleanup_source_record_by_key("contributions", second_source_record_key)

        verification_conn = get_connection()
        try:
            assert (
                source_record_count_for_key(
                    verification_conn,
                    "contributions",
                    first_source_record_key,
                )
                == 1
            )
            assert (
                candidate_person_count_for_source_record_key(
                    verification_conn,
                    "contributions",
                    first_source_record_key,
                )
                == 1
            )
        finally:
            verification_conn.rollback()
            verification_conn.close()
    finally:
        cleanup_source_record_by_key("contributions", second_source_record_key)
        cleanup_source_record_by_key("contributions", first_source_record_key)


def test_load_ga_contributions_batch_loads_fixture_and_is_idempotent(
    db_conn: psycopg.Connection,
) -> None:
    rows = _build_unique_fixture_rows(parsed_contribution_rows(), prefix="contribution-batch")
    fixture_row_count = len(rows)
    expected_source_record_counts = {_ga_record_hash(row): 1 for row in rows}

    first_result = load_ga_contributions(db_conn, rows)

    _assert_load_result(first_result, inserted=fixture_row_count)
    assert first_result.elapsed_seconds > 0
    assert {
        source_record_key: source_record_count_for_key(db_conn, "contributions", source_record_key)
        for source_record_key in expected_source_record_counts
    } == expected_source_record_counts
    contribution_data_source_id = ensure_ga_data_source(db_conn, "contributions")
    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT id, source_record_key, record_hash, raw_fields
            FROM core.source_record
            WHERE data_source_id = %s
              AND source_record_key = ANY(%s)
              AND superseded_by IS NULL
            ORDER BY source_record_key
            """,
            (contribution_data_source_id, sorted(expected_source_record_counts)),
        )
        first_source_record_snapshot = cursor.fetchall()
    assert [row["source_record_key"] for row in first_source_record_snapshot] == sorted(expected_source_record_counts)

    second_result = load_ga_contributions(db_conn, rows)

    _assert_load_result(second_result, inserted=0, skipped=fixture_row_count)
    assert {
        source_record_key: source_record_count_for_key(db_conn, "contributions", source_record_key)
        for source_record_key in expected_source_record_counts
    } == expected_source_record_counts
    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT id, source_record_key, record_hash, raw_fields
            FROM core.source_record
            WHERE data_source_id = %s
              AND source_record_key = ANY(%s)
              AND superseded_by IS NULL
            ORDER BY source_record_key
            """,
            (contribution_data_source_id, sorted(expected_source_record_counts)),
        )
        second_source_record_snapshot = cursor.fetchall()
    assert second_source_record_snapshot == first_source_record_snapshot

    assert ga_data_source_count(db_conn, "contributions") == 1


def test_load_ga_expenditures_batch_loads_fixture_rows(
    db_conn: psycopg.Connection,
) -> None:
    rows = _build_unique_fixture_rows(parsed_expenditure_rows(), prefix="expenditure-batch")
    fixture_row_count = len(rows)

    result = load_ga_expenditures(db_conn, rows)

    _assert_load_result(result, inserted=fixture_row_count)
    assert result.elapsed_seconds > 0

    assert ga_data_source_count(db_conn, "expenditures") == 1


def test_load_ga_batch_loaders_reject_negative_limit(db_conn: psycopg.Connection) -> None:
    rows = parsed_contribution_rows()

    with pytest.raises(ValueError, match="greater than or equal to 0"):
        load_ga_contributions(db_conn, rows, limit=-1)

    with pytest.raises(ValueError, match="greater than or equal to 0"):
        load_ga_expenditures(db_conn, parsed_expenditure_rows(), limit=-1)


def test_load_ga_contribution_blank_donor_names_creates_only_committee_entity(
    db_conn: psycopg.Connection,
) -> None:
    row = dict(parsed_contribution_rows()[0])
    row["LastName"] = ""
    row["FirstName"] = ""
    row["Address"] = ""
    row["City"] = ""
    row["State"] = ""
    row["Zip"] = ""
    row["Candidate_FirstName"] = ""
    row["Candidate_MiddleName"] = ""
    row["Candidate_LastName"] = ""
    row["Candidate_Suffix"] = ""
    inserted, source_record_id = _load_single_ga_row(db_conn, row, data_type="contributions")

    assert inserted is True
    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT entity_type, extraction_role
            FROM core.entity_source
            WHERE source_record_id = %s
            """,
            (source_record_id,),
        )
        links = cursor.fetchall()

    assert links == [{"entity_type": "organization", "extraction_role": "recipient"}]


def test_load_ga_contributions_with_filings_builds_relational_rows_and_is_idempotent(
    db_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = _build_unique_fixture_rows(parsed_contribution_rows(), prefix="contribution-filings")
    _stub_ga_parser(monkeypatch, parser_name="parse_contributions", rows=rows)
    result = load_ga_contributions_with_filings(db_conn, CONTRIBUTION_FIXTURE_PATH)

    _assert_load_result(result, inserted=len(rows))

    expected_filing_fec_ids = sorted({_build_expected_ga_filing_fec_id(row, "contributions") for row in rows})
    expected_record_hashes = sorted(_ga_record_hash(row) for row in rows)
    expected_by_identifier = {
        _ga_record_hash(row): _build_expected_ga_filing_fec_id(row, "contributions") for row in rows
    }
    expected_filer_id = rows[0]["FilerID"]
    assert isinstance(expected_filer_id, str)

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT filing_fec_id, amendment_indicator
            FROM cf.filing
            WHERE filing_fec_id = ANY(%s)
            ORDER BY filing_fec_id
            """,
            (expected_filing_fec_ids,),
        )
        filing_rows = cursor.fetchall()

        cursor.execute(
            """
            SELECT t.transaction_identifier,
                   t.amendment_indicator,
                   f.filing_fec_id,
                   t.source_record_id,
                   t.contributor_person_id,
                   t.contributor_organization_id,
                   (
                       SELECT es.entity_id
                       FROM core.entity_source es
                       WHERE es.source_record_id = t.source_record_id
                         AND es.entity_type = 'person'
                         AND es.extraction_role = 'donor'
                       LIMIT 1
                   ) AS expected_contributor_person_id,
                   (
                       SELECT es.entity_id
                       FROM core.entity_source es
                       WHERE es.source_record_id = t.source_record_id
                         AND es.entity_type = 'organization'
                         AND es.extraction_role = 'contributor'
                       LIMIT 1
                   ) AS expected_contributor_organization_id
            FROM cf.transaction t
            JOIN cf.filing f
              ON f.id = t.filing_id
            WHERE t.transaction_identifier = ANY(%s)
            ORDER BY t.transaction_identifier
            """,
            (expected_record_hashes,),
        )
        transaction_rows = cursor.fetchall()

        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM cf.committee c
            JOIN core.organization o
              ON o.id = c.organization_id
            WHERE c.state = 'GA'
              AND o.identifiers ->> 'ga_filer_id' = %s
            """,
            (expected_filer_id,),
        )
        committee_count = cursor.fetchone()["count"]

    contribution_data_source_id = ensure_ga_data_source(db_conn, "contributions")
    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT id, source_record_key, record_hash, raw_fields
            FROM core.source_record
            WHERE data_source_id = %s
              AND source_record_key = ANY(%s)
              AND superseded_by IS NULL
            ORDER BY source_record_key
            """,
            (contribution_data_source_id, expected_record_hashes),
        )
        source_record_snapshot = cursor.fetchall()

    assert [row["filing_fec_id"] for row in filing_rows] == expected_filing_fec_ids
    assert all(row["amendment_indicator"] == "N" for row in filing_rows)
    assert committee_count == 1
    assert [row["transaction_identifier"] for row in transaction_rows] == expected_record_hashes
    assert [row["source_record_key"] for row in source_record_snapshot] == expected_record_hashes
    assert all(row["amendment_indicator"] == "N" for row in transaction_rows)
    for row in transaction_rows:
        assert row["filing_fec_id"] == expected_by_identifier[row["transaction_identifier"]]
        assert row["contributor_person_id"] == row["expected_contributor_person_id"]
        assert row["contributor_organization_id"] == row["expected_contributor_organization_id"]

    first_filing_rows = filing_rows
    first_transaction_rows = transaction_rows
    first_committee_count = committee_count

    rerun_result = load_ga_contributions_with_filings(db_conn, CONTRIBUTION_FIXTURE_PATH)
    _assert_load_result(rerun_result, inserted=0, skipped=len(rows))

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT filing_fec_id, amendment_indicator
            FROM cf.filing
            WHERE filing_fec_id = ANY(%s)
            ORDER BY filing_fec_id
            """,
            (expected_filing_fec_ids,),
        )
        rerun_filing_rows = cursor.fetchall()

        cursor.execute(
            """
            SELECT t.transaction_identifier,
                   t.amendment_indicator,
                   f.filing_fec_id,
                   t.source_record_id,
                   t.contributor_person_id,
                   t.contributor_organization_id,
                   (
                       SELECT es.entity_id
                       FROM core.entity_source es
                       WHERE es.source_record_id = t.source_record_id
                         AND es.entity_type = 'person'
                         AND es.extraction_role = 'donor'
                       LIMIT 1
                   ) AS expected_contributor_person_id,
                   (
                       SELECT es.entity_id
                       FROM core.entity_source es
                       WHERE es.source_record_id = t.source_record_id
                         AND es.entity_type = 'organization'
                         AND es.extraction_role = 'contributor'
                       LIMIT 1
                   ) AS expected_contributor_organization_id
            FROM cf.transaction t
            JOIN cf.filing f
              ON f.id = t.filing_id
            WHERE transaction_identifier = ANY(%s)
            ORDER BY t.transaction_identifier
            """,
            (expected_record_hashes,),
        )
        rerun_transaction_rows = cursor.fetchall()

        cursor.execute(
            """
            SELECT id, source_record_key, record_hash, raw_fields
            FROM core.source_record
            WHERE data_source_id = %s
              AND source_record_key = ANY(%s)
              AND superseded_by IS NULL
            ORDER BY source_record_key
            """,
            (contribution_data_source_id, expected_record_hashes),
        )
        rerun_source_record_snapshot = cursor.fetchall()

        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM cf.committee c
            JOIN core.organization o
              ON o.id = c.organization_id
            WHERE c.state = 'GA'
              AND o.identifiers ->> 'ga_filer_id' = %s
            """,
            (expected_filer_id,),
        )
        rerun_committee_count = cursor.fetchone()["count"]

    assert rerun_filing_rows == first_filing_rows
    assert rerun_transaction_rows == first_transaction_rows
    assert rerun_committee_count == first_committee_count
    assert rerun_source_record_snapshot == source_record_snapshot


def test_load_ga_expenditures_with_filings_uses_paid_as_primary_amount(
    db_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = _build_unique_fixture_rows(parsed_expenditure_rows(), prefix="expenditure-filings")
    _stub_ga_parser(monkeypatch, parser_name="parse_expenditures", rows=rows)
    result = load_ga_expenditures_with_filings(db_conn, EXPENDITURE_FIXTURE_PATH)

    _assert_load_result(result, inserted=len(rows))

    expected_filing_fec_ids = sorted({_build_expected_ga_filing_fec_id(row, "expenditures") for row in rows})
    expected_record_hashes = sorted(_ga_record_hash(row) for row in rows)
    expected_by_identifier = {
        _ga_record_hash(row): (
            row["Type"],
            row["Paid"],
            row["Date"],
            _build_expected_ga_filing_fec_id(row, "expenditures"),
        )
        for row in rows
    }

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT t.transaction_identifier,
                   t.transaction_type,
                   t.amount,
                   t.transaction_date::text AS transaction_date,
                   t.amendment_indicator,
                   f.filing_fec_id,
                   t.contributor_person_id,
                   t.contributor_organization_id,
                   (
                       SELECT es.entity_id
                       FROM core.entity_source es
                       WHERE es.source_record_id = t.source_record_id
                         AND es.entity_type = 'person'
                         AND es.extraction_role = 'payee'
                       LIMIT 1
                   ) AS expected_contributor_person_id,
                   (
                       SELECT es.entity_id
                       FROM core.entity_source es
                       WHERE es.source_record_id = t.source_record_id
                         AND es.entity_type = 'organization'
                         AND es.extraction_role = 'payee'
                       LIMIT 1
                   ) AS expected_contributor_organization_id
            FROM cf.transaction t
            JOIN cf.filing f
              ON f.id = t.filing_id
            WHERE t.transaction_identifier = ANY(%s)
            ORDER BY t.transaction_identifier
            """,
            (expected_record_hashes,),
        )
        transaction_rows = cursor.fetchall()

        cursor.execute(
            """
            SELECT filing_fec_id
            FROM cf.filing
            WHERE filing_fec_id = ANY(%s)
            ORDER BY filing_fec_id
            """,
            (expected_filing_fec_ids,),
        )
        filing_rows = cursor.fetchall()

    assert [row["filing_fec_id"] for row in filing_rows] == expected_filing_fec_ids
    assert [row["transaction_identifier"] for row in transaction_rows] == expected_record_hashes
    for row in transaction_rows:
        expected_type, expected_amount, expected_date, expected_filing_fec_id = expected_by_identifier[
            row["transaction_identifier"]
        ]
        assert row["transaction_type"] == expected_type
        assert row["amount"] == expected_amount
        assert row["transaction_date"] == expected_date
        assert row["amendment_indicator"] == "N"
        assert row["filing_fec_id"] == expected_filing_fec_id
        assert row["contributor_person_id"] == row["expected_contributor_person_id"]
        assert row["contributor_organization_id"] == row["expected_contributor_organization_id"]

    rerun_result = load_ga_expenditures_with_filings(db_conn, EXPENDITURE_FIXTURE_PATH)
    _assert_load_result(rerun_result, inserted=0, skipped=len(rows))
