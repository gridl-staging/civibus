"""Integration tests for the federal spine loader.

Verifies that load_federal_spine() materializes exactly one core.person per
current federal official (House + Senate + delegates + President + VP), one
current civic.officeholding per person, and authoritatively repoints every
matching cf.candidate.person_id by FEC candidate ID — for ALL five buckets —
so member money attaches to the spine person.

Idempotency is asserted by calling load_federal_spine() twice and confirming
that core.person count and cf.candidate.person_id values do not change.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest

from core.db_ingest import find_person_by_identifier
from core.refresh import job_builders
from core.types.python.models import DataSource
from domains.campaign_finance.ingest.bulk_loader import load_candidates
from domains.campaign_finance.ingest.congress_legislators_adapter import (
    AdaptedLegislators,
    HistoricalPredecessors,
)
from domains.campaign_finance.ingest.federal_officeholder_loader import (
    OFFICE_US_HOUSE_DELEGATE,
    OFFICE_US_PRESIDENT,
    OFFICE_US_VICE_PRESIDENT,
)
from domains.campaign_finance.ingest.federal_spine_loader import (
    OFFICE_BY_EXECUTIVE_TYPE,
    SpineLoadResult,
    ensure_federal_spine_data_source,
    load_federal_spine,
)
from domains.campaign_finance.jurisdictions.states.load_utils import ensure_data_source

# Deterministic seed UUIDs from domains/civics/schema/tables.sql
OFFICE_US_HOUSE = UUID("00000000-0000-4000-8000-000000000101")
OFFICE_US_SENATE = UUID("00000000-0000-4000-8000-000000000102")

# Test-only identifiers (chosen so cleanup can target them precisely and so
# they don't collide with anything in dev/prod data).
HOUSE_BIO = "TST00H1"
HOUSE_FEC_A = "H8WA01054"
HOUSE_FEC_B = "S8WA00194"  # second FEC ID on the same dual-bucket House member
SENATE_BIO = "TST00S1"
SENATE_FEC = "S6CA00194"
DELEGATE_BIO = "TST00D1"
DELEGATE_FEC = "H0AS00001"
PREZ_BIO = "TST00P1"
PREZ_FEC = "P00000001"
VP_BIO = "TST00V1"

ALL_BIOS = (HOUSE_BIO, SENATE_BIO, DELEGATE_BIO, PREZ_BIO, VP_BIO)
ALL_FEC_IDS = (HOUSE_FEC_A, HOUSE_FEC_B, SENATE_FEC, DELEGATE_FEC, PREZ_FEC)
SEEDED_FEC_IDS = (HOUSE_FEC_A, HOUSE_FEC_B, SENATE_FEC, DELEGATE_FEC)

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _write_cn_fixture(tmp_path: Path) -> Path:
    """Write a tiny FEC `cn` pipe-delimited fixture with 4 seeded candidate rows.

    Each row carries the 15 CN_COLUMNS in order so bulk_loader.read_bulk_file() can
    parse without warnings. Office codes: 'H' for House and delegate (FEC treats
    territory delegates as 'H'); 'S' for Senate; 'P' for President.
    """
    cn_rows = [
        # House member, first FEC ID
        (HOUSE_FEC_A, "TEST HOUSE DUAL A", "DEM", "2024", "WA", "H", "01", "I", "C", "", "", "", "", "", ""),
        # Same House member, second FEC ID (different office code 'S' to mimic legacy chamber-swap)
        (HOUSE_FEC_B, "TEST HOUSE DUAL B", "DEM", "2024", "WA", "S", "", "C", "C", "", "", "", "", "", ""),
        # Senator
        (SENATE_FEC, "TEST SENATOR", "DEM", "2024", "CA", "S", "", "I", "C", "", "", "", "", "", ""),
        # Delegate (FEC office='H' for territories)
        (DELEGATE_FEC, "TEST DELEGATE", "DEM", "2024", "AS", "H", "00", "I", "C", "", "", "", "", "", ""),
    ]
    path = tmp_path / "cn_test.txt"
    path.write_text("\n".join("|".join(row) for row in cn_rows) + "\n", encoding="latin-1")
    return path


def _build_adapted_legislators() -> AdaptedLegislators:
    """Build an inline AdaptedLegislators matching the cn fixture."""
    return AdaptedLegislators(
        house_rows=[
            {
                "bioguide_id": HOUSE_BIO,
                "member_name": "Test House Dual",
                "first_name": "Test",
                "last_name": "HouseDual",
                "state": "WA",
                "district": "01",
                "party": "Democrat",
                "phone": "202-225-0001",
                "sworn_date": "2025-01-03",
                "elected_date": "",
                "office_building": "",
                "office_room": "",
                "office_zip": "",
                "fec_ids": [HOUSE_FEC_A, HOUSE_FEC_B],
                "wikidata_id": "QTESTHOUSE",
                "govtrack_id": "400001",
            }
        ],
        senate_rows=[
            {
                "bioguide_id": SENATE_BIO,
                "member_full": "Test Senator",
                "first_name": "Test",
                "last_name": "Senator",
                "state": "CA",
                "party": "Democrat",
                "class": "1",
                "phone": "202-224-0001",
                "email": "",
                "website": "",
                "address": "",
                "appointed": "",
                "fec_ids": [SENATE_FEC],
                "wikidata_id": "QTESTSENATE",
                "govtrack_id": "300001",
            }
        ],
        delegate_rows=[
            {
                "bioguide_id": DELEGATE_BIO,
                "member_name": "Test Delegate",
                "first_name": "Test",
                "last_name": "Delegate",
                "state": "AS",
                "district": "00",
                "party": "Democrat",
                "phone": "202-225-0002",
                "sworn_date": "2025-01-03",
                "fec_ids": [DELEGATE_FEC],
                "wikidata_id": "QTESTDELEGATE",
                "govtrack_id": "400002",
                "office_id": OFFICE_US_HOUSE_DELEGATE,
            }
        ],
        president_rows=[
            {
                "bioguide_id": PREZ_BIO,
                "first_name": "Test",
                "last_name": "President",
                "party": "Democrat",
                "fec_ids": [PREZ_FEC],
                "office_type": "president",
                "term_start": "2025-01-20",
                "term_end": "2029-01-20",
            }
        ],
        vp_rows=[
            {
                "bioguide_id": VP_BIO,
                "first_name": "Test",
                "last_name": "VicePresident",
                "party": "Democrat",
                "fec_ids": [],
                "office_type": "vice_president",
                "term_start": "2025-01-20",
                "term_end": "2029-01-20",
            }
        ],
    )


def _ensure_candidates_data_source(conn: psycopg.Connection) -> UUID:
    return ensure_data_source(
        conn,
        DataSource(
            domain="campaign_finance",
            jurisdiction="federal/fec",
            name="FEC bulk cn (test)",
            source_url="https://www.fec.gov/data/browse-data/?tab=bulk-data",
        ),
    )


def _delete_test_rows(conn: psycopg.Connection) -> None:
    """Remove every row introduced by this test file, in FK-safe order."""
    cn_source_record_keys = [f"cn:2024:{fec_id}" for fec_id in SEEDED_FEC_IDS]
    spine_source_record_keys = [
        "house:" + HOUSE_BIO,
        "senate:" + SENATE_BIO,
        "delegate:" + DELEGATE_BIO,
        "president:" + PREZ_BIO,
        "vp:" + VP_BIO,
    ]
    candidate_source_record_keys = cn_source_record_keys + spine_source_record_keys
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM core.source_record WHERE source_record_key = ANY(%s)",
            (candidate_source_record_keys,),
        )
        source_record_ids = [row[0] for row in cur.fetchall()]

        if source_record_ids:
            cur.execute(
                "DELETE FROM cf.transaction WHERE source_record_id = ANY(%s)",
                (source_record_ids,),
            )
            cur.execute(
                "DELETE FROM cf.filing WHERE source_record_id = ANY(%s)",
                (source_record_ids,),
            )
            cur.execute(
                "DELETE FROM core.contact_point WHERE source_record_id = ANY(%s)",
                (source_record_ids,),
            )
            cur.execute(
                "DELETE FROM core.entity_address WHERE source_record_id = ANY(%s)",
                (source_record_ids,),
            )
            cur.execute(
                "DELETE FROM core.entity_source WHERE source_record_id = ANY(%s)",
                (source_record_ids,),
            )

        cur.execute(
            "SELECT id FROM cf.candidate WHERE fec_candidate_id = ANY(%s)",
            (list(SEEDED_FEC_IDS),),
        )
        candidate_ids = [row[0] for row in cur.fetchall()]
        if candidate_ids:
            cur.execute(
                "DELETE FROM cf.candidate_committee_link WHERE candidate_id = ANY(%s)",
                (candidate_ids,),
            )
            cur.execute(
                "DELETE FROM cf.transaction WHERE recipient_candidate_id = ANY(%s)",
                (candidate_ids,),
            )
            cur.execute(
                "DELETE FROM cf.filing WHERE candidate_id = ANY(%s)",
                (candidate_ids,),
            )

        cur.execute(
            "DELETE FROM cf.candidate WHERE fec_candidate_id = ANY(%s)",
            (list(SEEDED_FEC_IDS),),
        )
        cur.execute(
            "SELECT id FROM core.person WHERE identifiers ->> 'bioguide_id' = ANY(%s)"
            " UNION"
            " SELECT id FROM core.person WHERE identifiers ->> 'fec_candidate_id' = ANY(%s)",
            (list(ALL_BIOS), list(SEEDED_FEC_IDS)),
        )
        person_ids = [row[0] for row in cur.fetchall()]
        if person_ids:
            cur.execute(
                "DELETE FROM cf.transaction WHERE contributor_person_id = ANY(%s)",
                (person_ids,),
            )
            cur.execute(
                "DELETE FROM civic.candidacy WHERE person_id = ANY(%s)",
                (person_ids,),
            )
            cur.execute(
                "DELETE FROM prop.ownership WHERE owner_person_id = ANY(%s)",
                (person_ids,),
            )
            cur.execute(
                "DELETE FROM core.person_portrait WHERE person_id = ANY(%s)",
                (person_ids,),
            )
        cur.execute(
            "DELETE FROM civic.officeholding WHERE person_id IN ("
            " SELECT id FROM core.person WHERE identifiers ->> 'bioguide_id' = ANY(%s)"
            " UNION"
            " SELECT id FROM core.person WHERE identifiers ->> 'fec_candidate_id' = ANY(%s)"
            ")",
            (list(ALL_BIOS), list(SEEDED_FEC_IDS)),
        )
        cur.execute(
            "DELETE FROM core.entity_source WHERE entity_type = 'person' AND entity_id IN ("
            " SELECT id FROM core.person WHERE identifiers ->> 'bioguide_id' = ANY(%s)"
            " UNION"
            " SELECT id FROM core.person WHERE identifiers ->> 'fec_candidate_id' = ANY(%s)"
            ")",
            (list(ALL_BIOS), list(SEEDED_FEC_IDS)),
        )
        cur.execute(
            "DELETE FROM core.person WHERE identifiers ->> 'bioguide_id' = ANY(%s)",
            (list(ALL_BIOS),),
        )
        cur.execute(
            "DELETE FROM core.person WHERE identifiers ->> 'fec_candidate_id' = ANY(%s)",
            (list(SEEDED_FEC_IDS),),
        )
        if source_record_ids:
            cur.execute(
                "DELETE FROM core.source_record WHERE id = ANY(%s)",
                (source_record_ids,),
            )


@pytest.fixture
def spine_conn(committing_db_conn: psycopg.Connection) -> Iterator[psycopg.Connection]:
    """Connection that commits real work and tears down test rows on exit.

    Bulk loaders commit internally, so the standard rollback-only db_conn fixture
    cannot isolate them. This fixture instead explicitly cleans up every row keyed
    by the deterministic test bioguide/FEC identifiers above.
    """
    conn = committing_db_conn
    host = conn.info.host or ""
    port = str(conn.info.port or "")
    dbname = conn.info.dbname or ""
    if host not in {"localhost", "127.0.0.1"} or port == "5432":
        pytest.skip(
            "federal spine integration cleanup requires a local non-default "
            f"test database target; got host={host!r} port={port!r} dbname={dbname!r}"
        )
    try:
        _delete_test_rows(conn)
        conn.commit()
        yield conn
    finally:
        conn.rollback()
        _delete_test_rows(conn)
        conn.commit()


class _NonClosingConnection:
    """Proxy a real test connection while ignoring the job callable's close()."""

    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def close(self) -> None:
        return None

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)


def _identity_lists(adapted: AdaptedLegislators) -> tuple[list[str], list[str], list[str]]:
    bioguide_ids: list[str] = []
    govtrack_ids: list[str] = []
    wikidata_ids: list[str] = []
    for row in _all_adapted_rows(adapted):
        bioguide_id = str(row.get("bioguide_id") or "").strip()
        if bioguide_id:
            bioguide_ids.append(bioguide_id)
            continue
        govtrack_id = str(row.get("govtrack_id") or "").strip()
        wikidata_id = str(row.get("wikidata_id") or "").strip()
        if govtrack_id:
            govtrack_ids.append(govtrack_id)
        elif wikidata_id:
            wikidata_ids.append(wikidata_id)
    return bioguide_ids, govtrack_ids, wikidata_ids


def _all_adapted_rows(adapted: AdaptedLegislators) -> list[dict[str, Any]]:
    return adapted.house_rows + adapted.senate_rows + adapted.delegate_rows + adapted.president_rows + adapted.vp_rows


def _select_live_spine_person_ids(
    conn: psycopg.Connection,
    adapted: AdaptedLegislators,
) -> list[UUID]:
    bioguide_ids, govtrack_ids, wikidata_ids = _identity_lists(adapted)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id
            FROM core.person
            WHERE identifiers ->> 'bioguide_id' = ANY(%s)
               OR identifiers ->> 'govtrack_id' = ANY(%s)
               OR identifiers ->> 'wikidata_id' = ANY(%s)
            """,
            (bioguide_ids, govtrack_ids, wikidata_ids),
        )
        return [row[0] for row in cur.fetchall()]


def _person_ids_for_rows(conn: psycopg.Connection, rows: list[dict[str, Any]]) -> list[UUID]:
    person_ids: list[UUID] = []
    for row in rows:
        bioguide_id = str(row.get("bioguide_id") or "").strip()
        govtrack_id = str(row.get("govtrack_id") or "").strip()
        wikidata_id = str(row.get("wikidata_id") or "").strip()
        person_id: UUID | None = None
        if bioguide_id:
            person_id = find_person_by_identifier(conn, "bioguide_id", bioguide_id)
        elif govtrack_id:
            person_id = find_person_by_identifier(conn, "govtrack_id", govtrack_id)
        elif wikidata_id:
            person_id = find_person_by_identifier(conn, "wikidata_id", wikidata_id)
        assert person_id is not None, f"missing spine person for adapted row {row!r}"
        person_ids.append(person_id)
    return person_ids


def _current_officeholding_count(
    conn: psycopg.Connection,
    *,
    person_ids: list[UUID],
    office_id: UUID,
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT count(*)
            FROM civic.officeholding
            WHERE person_id = ANY(%s)
              AND office_id = %s
              AND upper_inf(valid_period)
            """,
            (person_ids, office_id),
        )
        return cur.fetchone()[0]


def _spine_person_count(conn: psycopg.Connection, adapted: AdaptedLegislators) -> int:
    return len(_select_live_spine_person_ids(conn, adapted))


def _current_officeholding_total(conn: psycopg.Connection, person_ids: list[UUID]) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT count(*)
            FROM civic.officeholding
            WHERE person_id = ANY(%s)
              AND upper_inf(valid_period)
            """,
            (person_ids,),
        )
        return cur.fetchone()[0]


# ---------------------------------------------------------------------------
# Unit tests (no DB)
# ---------------------------------------------------------------------------


def test_office_id_classification_routes_correctly() -> None:
    """The OFFICE_BY_EXECUTIVE_TYPE helper maps to the correct seed UUIDs."""
    assert OFFICE_BY_EXECUTIVE_TYPE["delegate"] == OFFICE_US_HOUSE_DELEGATE
    assert OFFICE_BY_EXECUTIVE_TYPE["president"] == OFFICE_US_PRESIDENT
    assert OFFICE_BY_EXECUTIVE_TYPE["vice_president"] == OFFICE_US_VICE_PRESIDENT


# ---------------------------------------------------------------------------
# Integration test
# ---------------------------------------------------------------------------


def test_federal_congress_spine_refresh_job_loads_live_payload_idempotently(
    spine_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The refresh job seam loads the current upstream payload into the DB once."""
    adapted = _build_adapted_legislators()
    expected_counts = {
        "house": len(adapted.house_rows),
        "senate": len(adapted.senate_rows),
        "delegate": len(adapted.delegate_rows),
        "president": len(adapted.president_rows),
        "vice_president": len(adapted.vp_rows),
    }
    expected_person_count = sum(expected_counts.values())
    assert expected_counts["president"] == 1
    assert expected_counts["vice_president"] == 1

    test_data_source_id = ensure_data_source(
        spine_conn,
        DataSource(
            domain="campaign_finance",
            jurisdiction="federal/congress/test",
            name=f"Federal spine integration test {uuid4()}",
            source_url="https://github.com/unitedstates/congress-legislators",
        ),
    )
    spine_conn.commit()
    spine_conn.execute("BEGIN")
    job = job_builders.build_refresh_plan(scope="all", job_key_prefixes=("federal-congress-spine",))[0]
    connection_proxy = _NonClosingConnection(spine_conn)
    monkeypatch.setattr(job_builders, "get_connection", lambda: connection_proxy)
    monkeypatch.setattr(job_builders, "fetch_legislators_entries", lambda: [])
    monkeypatch.setattr(job_builders, "adapt_legislators_yaml", lambda _raw_entries: adapted)
    monkeypatch.setattr(job_builders, "fetch_historical_entries", lambda: [])
    monkeypatch.setattr(
        job_builders,
        "select_most_recent_vacancy_predecessors",
        lambda _adapted_legislators, _historical_entries: HistoricalPredecessors(),
    )
    monkeypatch.setattr(job_builders, "ensure_federal_spine_data_source", lambda _conn: test_data_source_id)

    try:
        result = job.run_callable()

        assert isinstance(result, SpineLoadResult)
        assert result.errors == 0
        assert result.house.inserted == expected_counts["house"]
        assert result.senate.inserted == expected_counts["senate"]
        assert result.delegate.inserted == expected_counts["delegate"]
        assert result.president.inserted == expected_counts["president"]
        assert result.vice_president.inserted == expected_counts["vice_president"]

        person_ids = _select_live_spine_person_ids(spine_conn, adapted)
        assert len(set(person_ids)) == expected_person_count
        assert _spine_person_count(spine_conn, adapted) == expected_person_count
        assert _current_officeholding_total(spine_conn, person_ids) == expected_person_count

        delegate_person_ids = _person_ids_for_rows(spine_conn, adapted.delegate_rows)
        president_person_ids = _person_ids_for_rows(spine_conn, adapted.president_rows)
        vp_person_ids = _person_ids_for_rows(spine_conn, adapted.vp_rows)
        assert (
            _current_officeholding_count(
                spine_conn,
                person_ids=delegate_person_ids,
                office_id=OFFICE_US_HOUSE_DELEGATE,
            )
            == expected_counts["delegate"]
        )
        assert (
            _current_officeholding_count(
                spine_conn,
                person_ids=president_person_ids,
                office_id=OFFICE_US_PRESIDENT,
            )
            == 1
        )
        assert (
            _current_officeholding_count(
                spine_conn,
                person_ids=vp_person_ids,
                office_id=OFFICE_US_VICE_PRESIDENT,
            )
            == 1
        )

        before_person_count = _spine_person_count(spine_conn, adapted)
        before_officeholding_count = _current_officeholding_total(spine_conn, person_ids)
        before_delegate_count = _current_officeholding_count(
            spine_conn,
            person_ids=delegate_person_ids,
            office_id=OFFICE_US_HOUSE_DELEGATE,
        )
        before_president_count = _current_officeholding_count(
            spine_conn,
            person_ids=president_person_ids,
            office_id=OFFICE_US_PRESIDENT,
        )
        before_vp_count = _current_officeholding_count(
            spine_conn,
            person_ids=vp_person_ids,
            office_id=OFFICE_US_VICE_PRESIDENT,
        )

        second_result = job.run_callable()

        assert isinstance(second_result, SpineLoadResult)
        assert second_result.errors == 0
        assert second_result.inserted == 0
        assert _spine_person_count(spine_conn, adapted) == before_person_count
        assert _current_officeholding_total(spine_conn, person_ids) == before_officeholding_count
        assert (
            _current_officeholding_count(
                spine_conn,
                person_ids=delegate_person_ids,
                office_id=OFFICE_US_HOUSE_DELEGATE,
            )
            == before_delegate_count
        )
        assert (
            _current_officeholding_count(
                spine_conn,
                person_ids=president_person_ids,
                office_id=OFFICE_US_PRESIDENT,
            )
            == before_president_count
        )
        assert (
            _current_officeholding_count(
                spine_conn,
                person_ids=vp_person_ids,
                office_id=OFFICE_US_VICE_PRESIDENT,
            )
            == before_vp_count
        )
    finally:
        spine_conn.rollback()


def test_load_federal_spine_converges_candidate_money_onto_spine_person(
    spine_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    """Spine ingest creates one person + one officeholding per official across
    all five buckets, and repoints every matching cf.candidate.person_id onto
    the spine person — for House, Senate, AND delegate (the third FEC-bearing
    bucket in this fixture). Re-running the loader is idempotent."""
    # --- Seed cf.candidate rows via the existing FEC `cn` loader ------------
    cn_path = _write_cn_fixture(tmp_path)
    candidates_ds_id = _ensure_candidates_data_source(spine_conn)
    spine_conn.commit()
    candidate_result = load_candidates(
        spine_conn,
        cn_path,
        cycle=2024,
        data_source_id=candidates_ds_id,
    )
    assert candidate_result.inserted == 4

    # Sanity: every seeded fec_candidate_id has a cf.candidate row pre-converge,
    # each pointing at an FEC-only person (NOT the bioguide spine person).
    with spine_conn.cursor() as cur:
        cur.execute(
            "SELECT fec_candidate_id, person_id FROM cf.candidate WHERE fec_candidate_id = ANY(%s)",
            (list(SEEDED_FEC_IDS),),
        )
        pre_rows = {row[0]: row[1] for row in cur.fetchall()}
    assert set(pre_rows.keys()) == set(SEEDED_FEC_IDS)
    assert all(person_id is not None for person_id in pre_rows.values())

    # --- Run the spine loader ----------------------------------------------
    adapted = _build_adapted_legislators()
    spine_ds_id = ensure_federal_spine_data_source(spine_conn)
    spine_conn.commit()

    result = load_federal_spine(spine_conn, adapted, data_source_id=spine_ds_id)
    spine_conn.commit()
    assert isinstance(result, SpineLoadResult)

    # --- Assert: exactly one spine person per bioguide ----------------------
    for bio in ALL_BIOS:
        person_id = find_person_by_identifier(spine_conn, "bioguide_id", bio)
        assert person_id is not None, f"missing spine person for bioguide {bio!r}"

    house_spine_person_id = find_person_by_identifier(spine_conn, "bioguide_id", HOUSE_BIO)
    senate_spine_person_id = find_person_by_identifier(spine_conn, "bioguide_id", SENATE_BIO)
    delegate_spine_person_id = find_person_by_identifier(spine_conn, "bioguide_id", DELEGATE_BIO)
    prez_spine_person_id = find_person_by_identifier(spine_conn, "bioguide_id", PREZ_BIO)
    vp_spine_person_id = find_person_by_identifier(spine_conn, "bioguide_id", VP_BIO)

    # --- Assert: identifiers JSONB carries fec_candidate_id + fec_candidate_ids
    with spine_conn.cursor() as cur:
        cur.execute(
            "SELECT identifiers FROM core.person WHERE id = %s",
            (house_spine_person_id,),
        )
        house_identifiers = cur.fetchone()[0]
    assert house_identifiers.get("bioguide_id") == HOUSE_BIO
    assert house_identifiers.get("fec_candidate_id") in {HOUSE_FEC_A, HOUSE_FEC_B}
    assert sorted(house_identifiers.get("fec_candidate_ids") or []) == sorted([HOUSE_FEC_A, HOUSE_FEC_B])
    assert house_identifiers.get("wikidata_id") == "QTESTHOUSE"
    assert house_identifiers.get("govtrack_id") == "400001"

    # --- Assert: BOTH House candidate rows repointed to the spine person ----
    with spine_conn.cursor() as cur:
        cur.execute(
            "SELECT fec_candidate_id, person_id FROM cf.candidate WHERE fec_candidate_id = ANY(%s)",
            ([HOUSE_FEC_A, HOUSE_FEC_B],),
        )
        house_candidate_rows = dict(cur.fetchall())
    assert house_candidate_rows[HOUSE_FEC_A] == house_spine_person_id
    assert house_candidate_rows[HOUSE_FEC_B] == house_spine_person_id

    # --- Assert: Senate candidate row repointed ----------------------------
    with spine_conn.cursor() as cur:
        cur.execute("SELECT person_id FROM cf.candidate WHERE fec_candidate_id = %s", (SENATE_FEC,))
        senate_candidate_person_id = cur.fetchone()[0]
    assert senate_candidate_person_id == senate_spine_person_id

    # --- Assert: Delegate candidate row repointed (5-bucket convergence) ----
    with spine_conn.cursor() as cur:
        cur.execute("SELECT person_id FROM cf.candidate WHERE fec_candidate_id = %s", (DELEGATE_FEC,))
        delegate_candidate_person_id = cur.fetchone()[0]
    assert delegate_candidate_person_id == delegate_spine_person_id

    # --- Assert: exactly one current officeholding per member with correct office_id
    expected_officeholdings = {
        house_spine_person_id: OFFICE_US_HOUSE,
        senate_spine_person_id: OFFICE_US_SENATE,
        delegate_spine_person_id: OFFICE_US_HOUSE_DELEGATE,
        prez_spine_person_id: OFFICE_US_PRESIDENT,
        vp_spine_person_id: OFFICE_US_VICE_PRESIDENT,
    }
    for person_id, expected_office in expected_officeholdings.items():
        with spine_conn.cursor() as cur:
            cur.execute(
                """
                SELECT office_id, upper_inf(valid_period)
                FROM civic.officeholding
                WHERE person_id = %s
                """,
                (person_id,),
            )
            rows = cur.fetchall()
        assert len(rows) == 1, f"expected one officeholding for person {person_id}, got {rows}"
        assert rows[0][0] == expected_office
        assert rows[0][1] is True, f"officeholding for person {person_id} should be active/open-ended"

    # --- Idempotency: re-run with the same inputs ---------------------------
    before_person_count = _count_test_persons(spine_conn)
    second_result = load_federal_spine(spine_conn, adapted, data_source_id=spine_ds_id)
    spine_conn.commit()
    assert isinstance(second_result, SpineLoadResult)
    assert second_result.inserted == 0
    after_person_count = _count_test_persons(spine_conn)
    assert before_person_count == after_person_count

    # cf.candidate.person_id values must still match the spine persons (no NULLs, no drift).
    with spine_conn.cursor() as cur:
        cur.execute(
            "SELECT fec_candidate_id, person_id FROM cf.candidate WHERE fec_candidate_id = ANY(%s)",
            (list(SEEDED_FEC_IDS),),
        )
        post_idempotent_rows = dict(cur.fetchall())
    assert post_idempotent_rows[HOUSE_FEC_A] == house_spine_person_id
    assert post_idempotent_rows[HOUSE_FEC_B] == house_spine_person_id
    assert post_idempotent_rows[SENATE_FEC] == senate_spine_person_id
    assert post_idempotent_rows[DELEGATE_FEC] == delegate_spine_person_id


def _count_test_persons(conn: psycopg.Connection) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM core.person WHERE identifiers ->> 'bioguide_id' = ANY(%s)",
            (list(ALL_BIOS),),
        )
        return cur.fetchone()[0]
