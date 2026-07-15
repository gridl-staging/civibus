"""Integration tests for the federal FEC races loader.

Seeds tiny FEC ``cn`` candidate source records plus election-date payloads and
asserts exact civic.election / civic.contest / civic.candidacy / core.person /
core.source_record / core.entity_source values, idempotent rerun behavior, and
challenger creation keyed by ``fec_candidate_id``.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID, uuid4

import psycopg
import pytest

from core.db import insert_data_source
from core.db_ingest import try_insert_source_record
from core.types.python.models import (
    DataSource,
    SourceRecord,
    compute_record_hash,
    utc_now,
)
from domains.campaign_finance.ingest.fec_client import FecApiError
from domains.civics.loaders.federal_fec_races import (
    _resolve_general_election_date,
    ensure_federal_fec_races_data_source,
    iter_cn_source_records,
    load_federal_fec_races,
)

pytestmark = pytest.mark.integration

# Deterministic seed UUIDs from domains/civics/schema/tables.sql
OFFICE_US_HOUSE = UUID("00000000-0000-4000-8000-000000000101")
OFFICE_US_SENATE = UUID("00000000-0000-4000-8000-000000000102")
OFFICE_US_PRESIDENT = UUID("00000000-0000-4000-8000-000000000103")


class FakeElectionClient:
    """Deterministic stand-in for FecClient.fetch_election_dates.

    Returns a general-election payload per queried year, records call arguments,
    and (like the real client) never receives Schedule A seek-cursor fields.
    """

    def __init__(self, general_dates_by_year: dict[int, str] | None = None) -> None:
        self._general_dates_by_year = general_dates_by_year or {}
        self.calls: list[dict] = []

    def fetch_election_dates(
        self,
        *,
        office=None,
        state=None,
        district=None,
        election_year=None,
        per_page: int = 20,
        limit=None,
    ) -> list[dict]:
        self.calls.append({"office": office, "state": state, "district": district, "election_year": election_year})
        general_date = self._general_dates_by_year.get(election_year)
        if general_date is None:
            return []
        return [
            {
                "election_type_id": "G",
                "election_date": general_date,
                "election_year": election_year,
                "office_sought": office,
                "election_state": state,
            }
        ]


class RateLimitedElectionClient:
    """Stand-in whose fetch always raises, mimicking an OpenFEC 429/HTTP failure."""

    def __init__(self) -> None:
        self.calls = 0

    def fetch_election_dates(self, **_kwargs) -> list[dict]:
        self.calls += 1
        raise FecApiError("Rate limit exceeded (HTTP 429). Slow down requests.")


class _CommitCountingConnection:
    """Proxy that counts commits and delegates everything else to a real connection."""

    def __init__(self, real: psycopg.Connection) -> None:
        self._real = real
        self.commit_count = 0

    def commit(self) -> None:
        self.commit_count += 1
        self._real.commit()

    def __getattr__(self, name: str):
        return getattr(self._real, name)


def _make_cn_data_source(conn: psycopg.Connection) -> UUID:
    ds = DataSource(
        domain="campaign_finance",
        jurisdiction="federal/fec",
        name=f"FEC Bulk Data Races Test {uuid4()}",
        source_url="https://www.fec.gov/data/browse-data/?tab=bulk-data",
    )
    insert_data_source(conn, ds)
    return ds.id


def _make_races_data_source(conn: psycopg.Connection) -> UUID:
    """Unique per-test races provenance source.

    The loader commits, so a shared singleton source would leak committed rows
    across tests; a unique source keeps per-test row counts deterministic.
    """
    ds = DataSource(
        domain="civics",
        jurisdiction="federal/fec",
        name=f"FEC Federal Races Test {uuid4()}",
        source_url="https://api.open.fec.gov/v1/election-dates/",
    )
    insert_data_source(conn, ds)
    return ds.id


def _cn_fields(
    *,
    cand_id: str,
    name: str,
    office: str,
    state: str,
    district: str = "00",
    year: str = "2024",
    party: str = "DEM",
    ici: str = "C",
    status: str = "C",
) -> dict[str, str]:
    return {
        "CAND_ID": cand_id,
        "CAND_NAME": name,
        "CAND_PTY_AFFILIATION": party,
        "CAND_ELECTION_YR": year,
        "CAND_OFFICE_ST": state,
        "CAND_OFFICE": office,
        "CAND_OFFICE_DISTRICT": district,
        "CAND_ICI": ici,
        "CAND_STATUS": status,
        "CAND_PCC": "",
    }


def _house(cand_id: str = "H4NC01234", **kwargs) -> dict[str, str]:
    return _cn_fields(
        cand_id=cand_id,
        name=kwargs.pop("name", "DOE, JANE"),
        office="H",
        state=kwargs.pop("state", "NC"),
        district=kwargs.pop("district", "01"),
        **kwargs,
    )


def _senate(cand_id: str = "S4NC00567", **kwargs) -> dict[str, str]:
    return _cn_fields(
        cand_id=cand_id, name=kwargs.pop("name", "SMITH, JOHN"), office="S", state=kwargs.pop("state", "NC"), **kwargs
    )


def _president(cand_id: str = "P40000001", **kwargs) -> dict[str, str]:
    return _cn_fields(cand_id=cand_id, name=kwargs.pop("name", "JONES, BOB"), office="P", state="US", **kwargs)


def _seed_cn_records(
    conn: psycopg.Connection, cn_ds_id: UUID, rows: list[dict[str, str]], *, cycle: int = 2024
) -> None:
    for row in rows:
        raw_fields = dict(row)
        try_insert_source_record(
            conn,
            SourceRecord(
                data_source_id=cn_ds_id,
                source_record_key=f"cn:{cycle}:{row['CAND_ID']}",
                raw_fields=raw_fields,
                pull_date=utc_now(),
                record_hash=compute_record_hash(raw_fields),
            ),
        )


def _load(
    conn: psycopg.Connection,
    *,
    rows: list[dict[str, str]],
    general_dates_by_year: dict[int, str] | None = None,
    min_election_year: int = 2022,
    cycle: int = 2024,
) -> tuple[UUID, FakeElectionClient, object]:
    cn_ds_id = _make_cn_data_source(conn)
    _seed_cn_records(conn, cn_ds_id, rows, cycle=cycle)
    races_ds_id = _make_races_data_source(conn)
    client = FakeElectionClient(general_dates_by_year or {2024: "2024-11-05", 2022: "2022-11-08"})
    result = load_federal_fec_races(
        conn,
        races_data_source_id=races_ds_id,
        cn_data_source_id=cn_ds_id,
        election_client=client,
        min_election_year=min_election_year,
    )
    return races_ds_id, client, result


def _races_source_ids(conn: psycopg.Connection, races_ds_id: UUID) -> list[UUID]:
    return [
        row[0]
        for row in conn.execute(
            "SELECT id FROM core.source_record WHERE data_source_id = %s AND source_record_key LIKE 'fec_races:%%'",
            (races_ds_id,),
        ).fetchall()
    ]


class TestElectionPopulation:
    def test_creates_single_coarse_federal_general_election(self, db_conn: psycopg.Connection) -> None:
        races_ds_id, client, result = _load(
            db_conn,
            rows=[_house(), _senate(), _president()],
        )
        assert result.inserted == 3
        assert result.errors == 0

        elections = db_conn.execute(
            """
            SELECT jurisdiction_scope, election_date, election_type, is_special, state, office_id, electoral_division_id
            FROM civic.election e
            JOIN core.source_record sr ON sr.id = e.source_record_id
            WHERE sr.data_source_id = %s
            """,
            (races_ds_id,),
        ).fetchall()
        # House + Senate + President for 2024 all link to ONE coarse general election.
        assert len(elections) == 1
        row = elections[0]
        assert row[0] == "federal"
        assert row[1] == date(2024, 11, 5)
        assert row[2] == "general"
        assert row[3] is False
        assert row[4] is None
        assert row[5] is None
        assert row[6] is None

    def test_contests_link_to_the_election(self, db_conn: psycopg.Connection) -> None:
        races_ds_id, _client, _result = _load(db_conn, rows=[_house(), _senate(), _president()])

        rows = db_conn.execute(
            """
            SELECT c.office_id, c.election_id, e.election_date
            FROM civic.contest c
            JOIN core.source_record sr ON sr.id = c.source_record_id
            JOIN civic.election e ON e.id = c.election_id
            WHERE sr.data_source_id = %s
            ORDER BY c.office_id
            """,
            (races_ds_id,),
        ).fetchall()
        assert len(rows) == 3
        office_ids = {r[0] for r in rows}
        assert office_ids == {OFFICE_US_HOUSE, OFFICE_US_SENATE, OFFICE_US_PRESIDENT}
        # All contests reference the same election id and date.
        assert len({r[1] for r in rows}) == 1
        assert all(r[2] == date(2024, 11, 5) for r in rows)

    def test_uses_general_election_date_from_payload(self, db_conn: psycopg.Connection) -> None:
        # Non-standard general date exercised end-to-end (payload wins over computed).
        races_ds_id, _client, _result = _load(
            db_conn,
            rows=[_house(cand_id="H4NC09001")],
            general_dates_by_year={2024: "2024-11-12"},
        )
        election_date = db_conn.execute(
            """
            SELECT e.election_date
            FROM civic.election e
            JOIN core.source_record sr ON sr.id = e.source_record_id
            WHERE sr.data_source_id = %s
            """,
            (races_ds_id,),
        ).fetchone()[0]
        assert election_date == date(2024, 11, 12)

    def test_falls_back_to_computed_date_when_payload_empty(self, db_conn: psycopg.Connection) -> None:
        races_ds_id, _client, _result = _load(
            db_conn,
            rows=[_house(cand_id="H4NC09002")],
            general_dates_by_year={},  # no payload for any year
        )
        election_date = db_conn.execute(
            """
            SELECT e.election_date
            FROM civic.election e
            JOIN core.source_record sr ON sr.id = e.source_record_id
            WHERE sr.data_source_id = %s
            """,
            (races_ds_id,),
        ).fetchone()[0]
        # First Tuesday after the first Monday in November 2024 = Nov 5, 2024.
        assert election_date == date(2024, 11, 5)


class TestCandidacyAndProvenance:
    def test_candidate_status_preserved_on_candidacy(self, db_conn: psycopg.Connection) -> None:
        races_ds_id, _client, _result = _load(
            db_conn,
            rows=[_house(cand_id="H4NC08001", status="N")],
        )
        status = db_conn.execute(
            """
            SELECT ca.status
            FROM civic.candidacy ca
            JOIN core.source_record sr ON sr.id = ca.source_record_id
            WHERE sr.data_source_id = %s
              AND ca.candidate_number = 'H4NC08001'
            """,
            (races_ds_id,),
        ).fetchone()[0]
        assert status == "N"

    def test_challenger_person_created_by_fec_candidate_id(self, db_conn: psycopg.Connection) -> None:
        _load(db_conn, rows=[_house(cand_id="H4NC07777", name="NEW, CHALLENGER")])

        person_rows = db_conn.execute(
            "SELECT canonical_name FROM core.person WHERE identifiers @> %s",
            ('{"fec_candidate_id": "H4NC07777"}',),
        ).fetchall()
        assert len(person_rows) == 1
        assert person_rows[0][0] == "NEW, CHALLENGER"

    def test_provenance_source_record_and_entity_sources(self, db_conn: psycopg.Connection) -> None:
        races_ds_id, _client, _result = _load(db_conn, rows=[_house(cand_id="H4NC06001")])

        source_ids = db_conn.execute(
            "SELECT id FROM core.source_record WHERE data_source_id = %s AND source_record_key = %s",
            (races_ds_id, "fec_races:H4NC06001:2024"),
        ).fetchall()
        assert len(source_ids) == 1
        source_record_id = source_ids[0][0]

        roles = db_conn.execute(
            """
            SELECT entity_type, extraction_role
            FROM core.entity_source
            WHERE source_record_id = %s
            ORDER BY entity_type
            """,
            (source_record_id,),
        ).fetchall()
        role_by_entity = {entity_type: role for entity_type, role in roles}
        assert role_by_entity["person"] == "candidate"
        assert role_by_entity["election"] == "election"
        assert role_by_entity["contest"] == "contest"
        assert role_by_entity["candidacy"] == "candidacy"

    def test_election_date_payload_stored_in_raw_fields(self, db_conn: psycopg.Connection) -> None:
        races_ds_id, _client, _result = _load(db_conn, rows=[_senate(cand_id="S4NC06002")])

        raw_fields = db_conn.execute(
            "SELECT raw_fields FROM core.source_record WHERE data_source_id = %s AND source_record_key = %s",
            (races_ds_id, "fec_races:S4NC06002:2024"),
        ).fetchone()[0]
        assert raw_fields["CAND_ID"] == "S4NC06002"
        assert raw_fields["resolved_election_date"] == "2024-11-05"
        assert isinstance(raw_fields["election_dates"], list)
        assert raw_fields["election_dates"][0]["election_type_id"] == "G"


class TestRecentWindowAndIdempotency:
    def test_old_rows_filtered_by_min_election_year(self, db_conn: psycopg.Connection) -> None:
        races_ds_id, _client, result = _load(
            db_conn,
            rows=[
                _house(cand_id="H4NC05001", year="2016"),
                _house(cand_id="H4NC05002", year="2024"),
            ],
            general_dates_by_year={2024: "2024-11-05"},
            min_election_year=2022,
        )
        assert result.inserted == 1

        candidate_numbers = db_conn.execute(
            """
            SELECT ca.candidate_number
            FROM civic.candidacy ca
            JOIN core.source_record sr ON sr.id = ca.source_record_id
            WHERE sr.data_source_id = %s
            """,
            (races_ds_id,),
        ).fetchall()
        assert {row[0] for row in candidate_numbers} == {"H4NC05002"}

    def test_rerun_is_idempotent(self, db_conn: psycopg.Connection) -> None:
        cn_ds_id = _make_cn_data_source(db_conn)
        _seed_cn_records(db_conn, cn_ds_id, [_house(cand_id="H4NC04001"), _senate(cand_id="S4NC04002")])
        races_ds_id = _make_races_data_source(db_conn)
        client = FakeElectionClient({2024: "2024-11-05"})

        first = load_federal_fec_races(
            db_conn,
            races_data_source_id=races_ds_id,
            cn_data_source_id=cn_ds_id,
            election_client=client,
            min_election_year=2022,
        )
        assert first.inserted == 2

        def _counts() -> tuple[int, int, int]:
            election_count = db_conn.execute(
                "SELECT COUNT(*) FROM civic.election e JOIN core.source_record sr ON sr.id = e.source_record_id WHERE sr.data_source_id = %s",
                (races_ds_id,),
            ).fetchone()[0]
            contest_count = db_conn.execute(
                "SELECT COUNT(*) FROM civic.contest c JOIN core.source_record sr ON sr.id = c.source_record_id WHERE sr.data_source_id = %s",
                (races_ds_id,),
            ).fetchone()[0]
            candidacy_count = db_conn.execute(
                "SELECT COUNT(*) FROM civic.candidacy ca JOIN core.source_record sr ON sr.id = ca.source_record_id WHERE sr.data_source_id = %s",
                (races_ds_id,),
            ).fetchone()[0]
            return election_count, contest_count, candidacy_count

        counts_after_first = _counts()
        assert counts_after_first == (1, 2, 2)

        second = load_federal_fec_races(
            db_conn,
            races_data_source_id=races_ds_id,
            cn_data_source_id=cn_ds_id,
            election_client=client,
            min_election_year=2022,
        )
        assert second.inserted == 0
        assert second.skipped == 2
        assert _counts() == counts_after_first


class TestElectionDateSupersession:
    """A rerun that resolves a different election date must move the existing race
    spine onto the new date rather than leaving a duplicate chain behind."""

    def test_changed_date_on_rerun_moves_chain_without_duplicating(self, db_conn: psycopg.Connection) -> None:
        # A distinct, otherwise-unused cycle keeps the globally-keyed coarse election
        # exclusive to this test so the counts below cannot be polluted by the other
        # committing tests in this file (which all use the 2024 general).
        cn_ds_id = _make_cn_data_source(db_conn)
        _seed_cn_records(
            db_conn,
            cn_ds_id,
            [_house(cand_id="H4NC0DT1", year="2028"), _senate(cand_id="S4NC0DT2", year="2028")],
        )
        races_ds_id = _make_races_data_source(db_conn)

        first = load_federal_fec_races(
            db_conn,
            races_data_source_id=races_ds_id,
            cn_data_source_id=cn_ds_id,
            election_client=FakeElectionClient({2028: "2028-11-07"}),
            min_election_year=2022,
        )
        assert first.inserted == 2

        # OpenFEC now reports a different general-election date for the same cycle.
        second = load_federal_fec_races(
            db_conn,
            races_data_source_id=races_ds_id,
            cn_data_source_id=cn_ds_id,
            election_client=FakeElectionClient({2028: "2028-11-21"}),
            min_election_year=2022,
        )
        # Changed payload => re-ingested via supersession, not a no-op skip.
        assert second.inserted == 2
        assert second.skipped == 0

        elections = db_conn.execute(
            """
            SELECT DISTINCT e.id, e.election_date
            FROM civic.election e
            JOIN core.source_record sr ON sr.id = e.source_record_id
            WHERE sr.data_source_id = %s
            """,
            (races_ds_id,),
        ).fetchall()
        # Exactly one election chain remains, now on the new date (no orphan at 11-07).
        assert len(elections) == 1
        election_id, election_date = elections[0]
        assert election_date == date(2028, 11, 21)

        contests = db_conn.execute(
            """
            SELECT c.id, c.election_date, c.election_id
            FROM civic.contest c
            JOIN core.source_record sr ON sr.id = c.source_record_id
            WHERE sr.data_source_id = %s
            """,
            (races_ds_id,),
        ).fetchall()
        assert len(contests) == 2
        assert all(row[1] == date(2028, 11, 21) for row in contests)
        assert all(row[2] == election_id for row in contests)

        candidacies = db_conn.execute(
            """
            SELECT ca.id
            FROM civic.candidacy ca
            JOIN core.source_record sr ON sr.id = ca.source_record_id
            WHERE sr.data_source_id = %s
            """,
            (races_ds_id,),
        ).fetchall()
        assert len(candidacies) == 2

        # No orphaned old-date rows survive anywhere for this cycle's seats.
        orphan_contests = db_conn.execute(
            "SELECT COUNT(*) FROM civic.contest WHERE election_date = %s AND election_type = 'general'",
            (date(2028, 11, 7),),
        ).fetchone()[0]
        assert orphan_contests == 0
        orphan_elections = db_conn.execute(
            """
            SELECT COUNT(*) FROM civic.election
            WHERE election_date = %s AND jurisdiction_scope = 'federal'
              AND election_type = 'general' AND is_special = FALSE
              AND office_id IS NULL AND electoral_division_id IS NULL
            """,
            (date(2028, 11, 7),),
        ).fetchone()[0]
        assert orphan_elections == 0

    def test_supersession_leaves_no_orphaned_entity_source_provenance(self, db_conn: psycopg.Connection) -> None:
        # Pruning the stale old-date civic rows must also drop their core.entity_source
        # links; otherwise provenance points at candidacy/contest/election ids that no
        # longer exist. Use an isolated cycle so the global coarse election is exclusive.
        cn_ds_id = _make_cn_data_source(db_conn)
        _seed_cn_records(
            db_conn,
            cn_ds_id,
            [_house(cand_id="H4NC0PV1", year="2029"), _senate(cand_id="S4NC0PV2", year="2029")],
        )
        races_ds_id = _make_races_data_source(db_conn)

        load_federal_fec_races(
            db_conn,
            races_data_source_id=races_ds_id,
            cn_data_source_id=cn_ds_id,
            election_client=FakeElectionClient({2029: "2029-11-06"}),
            min_election_year=2022,
        )
        # Capture the old-date entity ids before the supersession rerun deletes them.
        old_election_ids = {
            row[0]
            for row in db_conn.execute(
                "SELECT id FROM civic.election WHERE election_date = %s AND jurisdiction_scope = 'federal'",
                (date(2029, 11, 6),),
            ).fetchall()
        }
        old_contest_ids = {
            row[0]
            for row in db_conn.execute(
                "SELECT id FROM civic.contest WHERE election_date = %s AND election_type = 'general'",
                (date(2029, 11, 6),),
            ).fetchall()
        }
        old_candidacy_ids = {
            row[0]
            for row in db_conn.execute(
                "SELECT id FROM civic.candidacy WHERE contest_id = ANY(%s)",
                (list(old_contest_ids),),
            ).fetchall()
        }
        assert old_election_ids and old_contest_ids and old_candidacy_ids

        load_federal_fec_races(
            db_conn,
            races_data_source_id=races_ds_id,
            cn_data_source_id=cn_ds_id,
            election_client=FakeElectionClient({2029: "2029-11-20"}),
            min_election_year=2022,
        )

        deleted_ids = list(old_election_ids | old_contest_ids | old_candidacy_ids)
        orphaned = db_conn.execute(
            """
            SELECT COUNT(*) FROM core.entity_source
            WHERE entity_type IN ('election', 'contest', 'candidacy')
              AND entity_id = ANY(%s)
            """,
            (deleted_ids,),
        ).fetchone()[0]
        assert orphaned == 0


class TestIterCnSourceRecords:
    def test_yields_only_active_cn_records_for_data_source(self, db_conn: psycopg.Connection) -> None:
        cn_ds_id = _make_cn_data_source(db_conn)
        _seed_cn_records(db_conn, cn_ds_id, [_house(cand_id="H4NC03001")])
        # A non-cn record under the same source must be ignored.
        try_insert_source_record(
            db_conn,
            SourceRecord(
                data_source_id=cn_ds_id,
                source_record_key="cm:2024:C00000001",
                raw_fields={"CMTE_ID": "C00000001"},
                pull_date=utc_now(),
                record_hash=compute_record_hash({"CMTE_ID": "C00000001"}),
            ),
        )

        yielded = list(iter_cn_source_records(db_conn, cn_ds_id))
        assert len(yielded) == 1
        assert yielded[0]["CAND_ID"] == "H4NC03001"


class TestEnsureRacesDataSource:
    def test_is_idempotent_singleton(self, db_conn: psycopg.Connection) -> None:
        first_id = ensure_federal_fec_races_data_source(db_conn)
        second_id = ensure_federal_fec_races_data_source(db_conn)
        assert first_id == second_id

        row = db_conn.execute(
            "SELECT domain, jurisdiction FROM core.data_source WHERE id = %s",
            (first_id,),
        ).fetchone()
        assert row == ("civics", "federal/fec")

    def test_survives_concurrent_insert_race(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A concurrent worker that wins the race must not crash this worker.

        Uses `try_insert_data_source` (ON CONFLICT DO NOTHING) instead of the
        raise-on-conflict `insert_data_source`, then re-selects the winner's id.
        """
        from unittest.mock import MagicMock

        from domains.civics.loaders import federal_fec_races

        winner_id = uuid4()
        connection = MagicMock()

        select_returns = iter([None, winner_id])
        monkeypatch.setattr(
            federal_fec_races,
            "_select_races_data_source_id",
            lambda _conn: next(select_returns),
        )
        try_insert_calls: list[UUID] = []

        def _fake_try_insert(_conn, data_source):
            try_insert_calls.append(data_source.id)
            return None

        monkeypatch.setattr(federal_fec_races, "try_insert_data_source", _fake_try_insert)

        result = federal_fec_races.ensure_federal_fec_races_data_source(connection)

        assert result == winner_id
        assert len(try_insert_calls) == 1


class TestResolveGeneralElectionDate:
    """Unit coverage for the payload-vs-computed election-date resolution."""

    def test_prefers_general_entry_matching_year(self) -> None:
        payload = [
            {"election_type_id": "P", "election_date": "2024-03-05", "election_year": 2024},
            {"election_type_id": "G", "election_date": "2024-11-05", "election_year": 2024},
        ]
        assert _resolve_general_election_date(payload, 2024) == date(2024, 11, 5)

    def test_ignores_general_entry_from_other_year(self) -> None:
        payload = [{"election_type_id": "G", "election_date": "2022-11-08", "election_year": 2022}]
        # No 2024 general in payload -> computed fallback (Nov 5, 2024).
        assert _resolve_general_election_date(payload, 2024) == date(2024, 11, 5)

    def test_empty_payload_uses_computed_date(self) -> None:
        assert _resolve_general_election_date([], 2022) == date(2022, 11, 8)

    def test_prefers_regular_november_over_earlier_special_general(self) -> None:
        # A special general earlier in the cycle must NOT win over the November general.
        payload = [
            {"election_type_id": "G", "election_date": "2024-05-14", "election_year": 2024},
            {"election_type_id": "G", "election_date": "2024-11-05", "election_year": 2024},
        ]
        assert _resolve_general_election_date(payload, 2024) == date(2024, 11, 5)

    def test_uses_latest_general_when_none_match_computed_date(self) -> None:
        # No entry equals the computed Nov 5 date -> the latest 'G' (the regular
        # general, shifted to Nov 12 here) is chosen over an earlier special.
        payload = [
            {"election_type_id": "G", "election_date": "2024-04-30", "election_year": 2024},
            {"election_type_id": "G", "election_date": "2024-11-12", "election_year": 2024},
        ]
        assert _resolve_general_election_date(payload, 2024) == date(2024, 11, 12)


class TestElectionDatesFetchResilience:
    def test_fetch_error_falls_back_to_computed_date(self, db_conn: psycopg.Connection) -> None:
        cn_ds_id = _make_cn_data_source(db_conn)
        _seed_cn_records(db_conn, cn_ds_id, [_house(cand_id="H4NC02001"), _senate(cand_id="S4NC02002")])
        races_ds_id = _make_races_data_source(db_conn)
        client = RateLimitedElectionClient()

        result = load_federal_fec_races(
            db_conn,
            races_data_source_id=races_ds_id,
            cn_data_source_id=cn_ds_id,
            election_client=client,
            min_election_year=2022,
        )
        # A rate-limit error must not abort the load; every row still lands.
        assert result.inserted == 2
        # One fetch per distinct year, cached even after the failure (no per-seat fan-out).
        assert client.calls == 1

        election_date = db_conn.execute(
            """
            SELECT e.election_date
            FROM civic.election e
            JOIN core.source_record sr ON sr.id = e.source_record_id
            WHERE sr.data_source_id = %s
            """,
            (races_ds_id,),
        ).fetchone()[0]
        # Computed first-Tuesday-after-first-Monday November 2024 = Nov 5, 2024.
        assert election_date == date(2024, 11, 5)


class TestBatchedCommits:
    def test_commits_periodically_by_batch_size(self, db_conn: psycopg.Connection) -> None:
        cn_ds_id = _make_cn_data_source(db_conn)
        _seed_cn_records(
            db_conn,
            cn_ds_id,
            [_house(cand_id="H4NC0AA1"), _house(cand_id="H4NC0AA2"), _house(cand_id="H4NC0AA3")],
        )
        races_ds_id = _make_races_data_source(db_conn)
        spy = _CommitCountingConnection(db_conn)

        result = load_federal_fec_races(
            spy,
            races_data_source_id=races_ds_id,
            cn_data_source_id=cn_ds_id,
            election_client=FakeElectionClient({2024: "2024-11-05"}),
            min_election_year=2022,
            batch_size=2,
        )
        assert result.inserted == 3
        # 3 rows at batch_size 2 -> one mid-loop commit + one final flush.
        assert spy.commit_count == 2

    def test_rejects_non_positive_batch_size(self, db_conn: psycopg.Connection) -> None:
        cn_ds_id = _make_cn_data_source(db_conn)
        races_ds_id = _make_races_data_source(db_conn)
        with pytest.raises(ValueError, match="batch_size"):
            load_federal_fec_races(
                db_conn,
                races_data_source_id=races_ds_id,
                cn_data_source_id=cn_ds_id,
                election_client=FakeElectionClient(),
                min_election_year=2022,
                batch_size=0,
            )
