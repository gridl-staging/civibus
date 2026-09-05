from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

import psycopg
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from api.deps import get_db
from api.queries.regional_navigation import (
    fetch_washington_state_finance,
    resolve_regional_navigation_node,
    search_regional_navigation_nodes,
)
from api.routes.regional_navigation import router


_AS_OF = datetime(2026, 8, 28, 16, 0, tzinfo=timezone.utc)
_PERSON_ID = UUID("53000000-0000-4000-8000-000000000001")
_ORGANIZATION_ID = UUID("53000000-0000-4000-8000-000000000002")
_COMMITTEE_ID = UUID("53000000-0000-4000-8000-000000000003")
_CONTEST_ID = UUID("53000000-0000-4000-8000-000000000004")
_CANDIDACY_ID = UUID("53000000-0000-4000-8000-000000000005")
_OFFICEHOLDING_ID = UUID("53000000-0000-4000-8000-000000000006")
_WA_GOVERNOR_OFFICE_ID = UUID("00000000-0000-4000-8000-000000000204")
_WA_DIVISION_ID = UUID("00000000-0000-4000-8000-000000000502")
_SOURCE_ROWS = (
    (
        "contributions",
        "WA PDC Contributions",
        Decimal("125.50"),
        date(2026, 8, 20),
        {"office": "Governor", "jurisdiction_type": "State", "filer_id": "WA-FILER-1"},
    ),
    (
        "expenditures",
        "WA PDC Expenditures",
        Decimal("80.25"),
        date(2026, 8, 21),
        {"office": "Governor", "jurisdiction_type": "State", "filer_id": "WA-FILER-1"},
    ),
    (
        "independent_expenditures",
        "WA PDC Independent Expenditures",
        Decimal("45.75"),
        date(2026, 8, 22),
        {
            "origin": "C6.3 - Identified Entities",
            "candidate_office": "Governor",
            "candidate_jurisdiction": "STATE OF WASHINGTON",
            "candidate_filer_id": "WA-FILER-1",
        },
    ),
    (
        "loans",
        "WA PDC Loans",
        Decimal("20.00"),
        date(2026, 8, 23),
        {"office": "Governor", "jurisdiction_type": "State", "filer_id": "WA-FILER-1"},
    ),
)


def _seed_washington_product(conn: psycopg.Connection) -> None:
    conn.execute(
        """
        INSERT INTO core.organization (id, canonical_name, identifiers, registered_state)
        VALUES (%s, 'Washington Future Committee', %s, 'WA')
        """,
        (_ORGANIZATION_ID, Jsonb({"wa_committee_id": "WA-CMTE-1"})),
    )
    conn.execute(
        """
        INSERT INTO cf.committee (id, fec_committee_id, name, organization_id, state, city)
        VALUES (%s, 'C53000001', 'Washington Future Committee', %s, 'WA', 'Olympia')
        """,
        (_COMMITTEE_ID, _ORGANIZATION_ID),
    )

    for index, (class_key, source_name, amount, transaction_date, raw_fields) in enumerate(
        _SOURCE_ROWS,
        start=1,
    ):
        data_source_id = UUID(f"53000000-0000-4000-8100-{index:012d}")
        source_record_id = UUID(f"53000000-0000-4000-8200-{index:012d}")
        filing_id = UUID(f"53000000-0000-4000-8300-{index:012d}")
        transaction_id = UUID(f"53000000-0000-4000-8400-{index:012d}")
        refresh_id = UUID(f"53000000-0000-4000-8500-{index:012d}")
        conn.execute(
            """
            INSERT INTO core.data_source (
                id, domain, jurisdiction, name, source_url, source_format,
                update_frequency, last_pull_at, last_pull_status, record_count
            )
            VALUES (%s, 'campaign_finance', 'state/WA', %s, %s, 'api', 'daily', %s, 'success', 1)
            """,
            (data_source_id, source_name, f"https://data.wa.gov/{class_key}", _AS_OF),
        )
        conn.execute(
            """
            INSERT INTO core.refresh_run (
                id, job_key, domain, jurisdiction, data_source_names, execution_origin,
                pull_status, started_at, completed_at, inserted_count, message
            )
            VALUES (%s, %s, 'campaign_finance', 'state/WA', %s, 'scheduled',
                    'success', %s, %s, 1, 'deterministic Washington product fixture')
            """,
            (
                refresh_id,
                f"state-wa-{class_key}",
                [source_name],
                _AS_OF,
                _AS_OF,
            ),
        )
        conn.execute(
            """
            INSERT INTO core.source_record (
                id, data_source_id, source_record_key, source_url, raw_fields, pull_date, record_hash
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                source_record_id,
                data_source_id,
                f"WA-PDC:test:{class_key}",
                f"https://my.pdc.wa.gov/{class_key}",
                Jsonb(raw_fields),
                _AS_OF,
                f"hash-{class_key}",
            ),
        )
        conn.execute(
            """
            INSERT INTO cf.filing (
                id, filing_fec_id, committee_id, amendment_indicator, coverage_start_date,
                coverage_end_date, source_record_id
            )
            VALUES (%s, %s, %s, 'N', '2025-01-01', '2026-12-31', %s)
            """,
            (filing_id, f"WA-PDC-TEST-{class_key}", _COMMITTEE_ID, source_record_id),
        )
        conn.execute(
            """
            INSERT INTO cf.transaction (
                id, filing_id, committee_id, transaction_type, transaction_identifier,
                transaction_date, amount, amendment_indicator, source_record_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'N', %s)
            """,
            (
                transaction_id,
                filing_id,
                _COMMITTEE_ID,
                "Cash" if class_key == "contributions" else "New",
                f"WA-PDC:test:{class_key}",
                transaction_date,
                amount,
                source_record_id,
            ),
        )

    contributions_source_id = UUID("53000000-0000-4000-8100-000000000001")
    _seed_excluded_transaction(
        conn,
        suffix=10,
        data_source_id=contributions_source_id,
        amount=Decimal("999999.00"),
        raw_fields={"office": "Mayor", "jurisdiction_type": "Municipal", "filer_id": "LOCAL-1"},
    )
    independent_source_id = UUID("53000000-0000-4000-8100-000000000003")
    _seed_excluded_transaction(
        conn,
        suffix=11,
        data_source_id=independent_source_id,
        amount=Decimal("777777.00"),
        raw_fields={
            "origin": "C6.2 - Itemized Expenditures",
            "candidate_office": "Governor",
            "candidate_jurisdiction": "STATE OF WASHINGTON",
            "candidate_filer_id": "WA-FILER-1",
        },
    )

    conn.execute(
        """
        INSERT INTO core.person (id, canonical_name, identifiers)
        VALUES (%s, 'Alex Washington', %s)
        """,
        (_PERSON_ID, Jsonb({"wa_filer_id": "WA-FILER-1"})),
    )
    conn.execute(
        """
        INSERT INTO civic.contest (
            id, name, election_date, election_type, office_id, electoral_division_id
        )
        VALUES (%s, 'WA Governor General 2026', '2026-11-03', 'general', %s, %s)
        """,
        (_CONTEST_ID, _WA_GOVERNOR_OFFICE_ID, _WA_DIVISION_ID),
    )
    conn.execute(
        """
        INSERT INTO civic.candidacy (id, person_id, contest_id, party, status)
        VALUES (%s, %s, %s, 'Independent', 'qualified')
        """,
        (_CANDIDACY_ID, _PERSON_ID, _CONTEST_ID),
    )
    conn.execute(
        """
        INSERT INTO civic.officeholding (
            id, person_id, office_id, electoral_division_id, holder_status, valid_period
        )
        VALUES (%s, %s, %s, %s, 'elected', daterange('2025-01-01', NULL, '[)'))
        """,
        (_OFFICEHOLDING_ID, _PERSON_ID, _WA_GOVERNOR_OFFICE_ID, _WA_DIVISION_ID),
    )


def _seed_excluded_transaction(
    conn: psycopg.Connection,
    *,
    suffix: int,
    data_source_id: UUID,
    amount: Decimal,
    raw_fields: dict[str, str],
) -> None:
    source_record_id = UUID(f"53000000-0000-4000-8600-{suffix:012d}")
    filing_id = UUID(f"53000000-0000-4000-8700-{suffix:012d}")
    transaction_id = UUID(f"53000000-0000-4000-8800-{suffix:012d}")
    conn.execute(
        """
        INSERT INTO core.source_record (
            id, data_source_id, source_record_key, source_url, raw_fields, pull_date, record_hash
        )
        VALUES (%s, %s, %s, 'https://my.pdc.wa.gov/excluded', %s, %s, %s)
        """,
        (source_record_id, data_source_id, f"WA-PDC:test:excluded:{suffix}", Jsonb(raw_fields), _AS_OF, f"x{suffix}"),
    )
    conn.execute(
        """
        INSERT INTO cf.filing (id, filing_fec_id, committee_id, amendment_indicator, source_record_id)
        VALUES (%s, %s, %s, 'N', %s)
        """,
        (filing_id, f"WA-PDC-TEST-EXCLUDED-{suffix}", _COMMITTEE_ID, source_record_id),
    )
    conn.execute(
        """
        INSERT INTO cf.transaction (
            id, filing_id, committee_id, transaction_type, transaction_identifier,
            transaction_date, amount, amendment_indicator, source_record_id
        )
        VALUES (%s, %s, %s, 'New', %s, '2026-08-24', %s, 'N', %s)
        """,
        (
            transaction_id,
            filing_id,
            _COMMITTEE_ID,
            f"WA-PDC:test:excluded:{suffix}",
            amount,
            source_record_id,
        ),
    )


def test_washington_product_returns_exact_money_civic_connections_and_provenance(
    db_conn: psycopg.Connection,
) -> None:
    _seed_washington_product(db_conn)

    detail = fetch_washington_state_finance(db_conn, as_of=_AS_OF)

    assert detail.period_start == date(2025, 1, 1)
    assert detail.period_end == date(2026, 8, 28)
    assert {row.key: (row.amount, row.transaction_count, row.data_through, row.status) for row in detail.money} == {
        "contributions": (Decimal("125.50"), 1, date(2026, 8, 20), "available"),
        "expenditures": (Decimal("80.25"), 1, date(2026, 8, 21), "available"),
        "independent_expenditures": (Decimal("45.75"), 1, date(2026, 8, 22), "available"),
        "loans": (Decimal("20.00"), 1, date(2026, 8, 23), "available"),
    }
    assert len(detail.candidates) == 1
    candidate = detail.candidates[0]
    assert candidate.person_id == _PERSON_ID
    assert candidate.candidacy_id == _CANDIDACY_ID
    assert candidate.contest_id == _CONTEST_ID
    assert candidate.office_id == _WA_GOVERNOR_OFFICE_ID
    assert candidate.division_id == _WA_DIVISION_ID
    assert candidate.current_officeholding_id == _OFFICEHOLDING_ID
    assert candidate.native_filer_identifier is not None
    assert candidate.native_filer_identifier.model_dump() == {
        "authority_code": "WA",
        "value": "WA-FILER-1",
    }
    assert candidate.money_connection == "connected"
    assert candidate.activity_amount == Decimal("271.50")
    assert candidate.transaction_count == 4
    assert [(row.committee_id, row.activity_amount, row.transaction_count) for row in detail.committees] == [
        (_COMMITTEE_ID, Decimal("271.50"), 4)
    ]
    assert all(source.last_successful_pull == _AS_OF for source in detail.sources)
    assert all(source.latest_refresh_completed_at == _AS_OF for source in detail.sources)
    assert all(source.latest_refresh_status == "success" for source in detail.sources)
    assert "C6.2 vendor outlays and C6.5 funding-source records" in " ".join(detail.excluded)


def test_washington_route_and_search_share_degraded_status_without_hiding_valid_money(
    db_conn: psycopg.Connection,
) -> None:
    _seed_washington_product(db_conn)
    db_conn.execute(
        """
        UPDATE core.data_source
        SET last_pull_status = 'partial'
        WHERE domain = 'campaign_finance'
          AND jurisdiction = 'state/WA'
          AND name = 'WA PDC Independent Expenditures'
        """
    )

    node = resolve_regional_navigation_node(
        kind="state",
        state_code="WA",
        slug=None,
        conn=db_conn,
        as_of=_AS_OF,
    )
    assert node is not None
    assert node.finance.status == "degraded"
    assert node.finance_detail is not None
    ie_money = next(row for row in node.finance_detail.money if row.key == "independent_expenditures")
    assert ie_money.status == "degraded"
    assert ie_money.amount == Decimal("45.75")
    search_node = search_regional_navigation_nodes(query="Washington", limit=1, conn=db_conn)[0]
    assert search_node.finance.status == node.finance.status
    assert search_node.finance.authority_context == node.finance.authority_context

    app = FastAPI()
    app.include_router(router, prefix="/v1")
    app.dependency_overrides[get_db] = lambda: db_conn
    with TestClient(app) as client:
        response = client.get(
            "/v1/regional-navigation/resolve",
            params={"kind": "state", "state_code": "WA"},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["finance"]["status"] == "degraded"
    assert (
        next(row for row in payload["finance_detail"]["money"] if row["key"] == "independent_expenditures")["amount"]
        == "45.75"
    )


def test_washington_route_exposes_stale_source_and_refuses_promotion(
    db_conn: psycopg.Connection,
) -> None:
    _seed_washington_product(db_conn)
    db_conn.execute(
        """
        UPDATE core.data_source
        SET last_pull_at = %s
        WHERE domain = 'campaign_finance'
          AND jurisdiction = 'state/WA'
          AND name = 'WA PDC Contributions'
        """,
        (_AS_OF - timedelta(days=3),),
    )

    node = resolve_regional_navigation_node(
        kind="state",
        state_code="WA",
        slug=None,
        conn=db_conn,
        as_of=_AS_OF,
    )

    assert node is not None
    assert node.finance.status == "stale"
    assert node.finance_detail is not None
    contribution = next(row for row in node.finance_detail.sources if row.class_key == "contributions")
    assert contribution.status == "stale"
    assert contribution.recurrence_status == "qualified"
    health = node.finance.authority_health[0]
    assert health.freshness_status == "stale"
    assert health.promotion_eligible is False
    assert any("not fresh" in reason for reason in health.refusal_reasons)


def test_duplicate_filer_identifiers_refuse_candidate_money_without_erasing_state_totals(
    db_conn: psycopg.Connection,
) -> None:
    _seed_washington_product(db_conn)
    duplicate_person_id = UUID("53000000-0000-4000-8000-000000000099")
    db_conn.execute(
        "INSERT INTO core.person (id, canonical_name, identifiers) VALUES (%s, 'Ambiguous Person', %s)",
        (duplicate_person_id, Jsonb({"wa_filer_id": "WA-FILER-1"})),
    )

    detail = fetch_washington_state_finance(db_conn, as_of=_AS_OF)

    assert {row.key: row.amount for row in detail.money}["contributions"] == Decimal("125.50")
    assert detail.candidates[0].money_connection == "unavailable"
    assert detail.candidates[0].native_filer_identifier is None
    assert detail.candidates[0].activity_amount is None
    assert detail.candidates[0].transaction_count == 0
