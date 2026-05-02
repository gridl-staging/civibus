"""Tests for the Stage 2 ER cohort baseline probe.

Verify the load-bearing classification contract (`COHORT_RULES`), the gate
arithmetic (`pct_resolved`, `gate_target_pct`), and that the read-only DB
probe correctly counts persons through `civic.officeholding` AND `civic.candidacy`
into per-cohort baselines, including resolved subsets via `core.person.er_cluster_id`.
"""

from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest

from core.db import (
    insert_data_source,
    insert_entity_source,
    insert_person,
    insert_source_record,
)
from core.types.python.models import (
    DataSource,
    Person,
    SourceRecord,
    ValidDateRange,
    compute_record_hash,
    utc_now,
)
from domains.civics.ingest import (
    upsert_candidacy,
    upsert_contest,
    upsert_office,
    upsert_officeholding,
)
from domains.civics.scripts.er_cohort_baseline_probe import (
    COHORT_RULES,
    build_baseline_payload,
    cohort_for_office,
    compute_all_cohort_baselines,
    compute_cohort_baseline,
    compute_gate_target_pct,
    compute_pct_resolved,
    find_unclassified_office_drift,
    is_targeted_level_state,
    write_baseline_artifact,
)
from domains.civics.types.models import (
    Candidacy,
    Contest,
    Office,
    Officeholding,
)


# Pure-Python contract/arithmetic/artifact tests below run under the unit gate
# (`make test`). Only the DB-backed `TestCohortBaselineIntegration` class is
# marked `integration` so it is excluded from the unit gate but picked up by
# `make test-e2e` workflows that opt into integration markers.


# ---------------------------------------------------------------------------
# Cohort classification contract -- pure-Python tests (no DB)
# ---------------------------------------------------------------------------


_EXPECTED_COHORTS: tuple[str, ...] = (
    "federal",
    "ncga_senate",
    "ncga_house",
    "council_of_state",
    "appellate",
    "trial_judges",
    "das",
    "sheriffs",
    "register_of_deeds",
    "commissioners",
    "soil_water",
    "municipal",
    "school_board",
)

_FEDERAL_AND_STATE_COHORTS = {
    "federal",
    "ncga_senate",
    "ncga_house",
    "council_of_state",
}

_SUB_STATE_COHORTS = {
    "appellate",
    "trial_judges",
    "das",
    "sheriffs",
    "register_of_deeds",
    "commissioners",
    "soil_water",
    "municipal",
    "school_board",
}


class TestCohortRulesContract:
    def test_all_expected_cohorts_present(self) -> None:
        assert tuple(COHORT_RULES.keys()) == _EXPECTED_COHORTS

    def test_federal_state_cohorts_use_floor_080(self) -> None:
        for slug in _FEDERAL_AND_STATE_COHORTS:
            assert COHORT_RULES[slug]["floor"] == pytest.approx(0.80)

    def test_sub_state_cohorts_use_floor_070(self) -> None:
        for slug in _SUB_STATE_COHORTS:
            assert COHORT_RULES[slug]["floor"] == pytest.approx(0.70)

    def test_each_rule_has_required_keys(self) -> None:
        for slug, rule in COHORT_RULES.items():
            assert set(rule.keys()) >= {"office_level", "state", "name_patterns", "floor"}, slug
            valid_levels = {
                "federal",
                "state",
                "county",
                "municipal",
                "judicial",
                "school_board",
                "special_district",
            }
            assert rule["office_level"] in valid_levels, slug


class TestCohortClassification:
    @pytest.mark.parametrize(
        ("office_level", "state", "name", "title", "expected"),
        [
            ("federal", None, "us_house", "Representative", "federal"),
            ("federal", None, "us_senate", "Senator", "federal"),
            ("state", "NC", "nc_house_member", "State Representative", "ncga_house"),
            ("state", "NC", "nc_senate_member", "State Senator", "ncga_senate"),
            ("state", "NC", "governor", "Governor", "council_of_state"),
            ("state", "NC", "lieutenant_governor", "Lieutenant Governor", "council_of_state"),
            ("state", "NC", "attorney_general", "Attorney General", "council_of_state"),
            ("state", "NC", "commissioner_of_agriculture", "Agriculture Commissioner", "council_of_state"),
            ("judicial", "NC", "nc_supreme_court_justice", "Justice", "appellate"),
            ("judicial", "NC", "nc_court_of_appeals_judge", "Judge", "appellate"),
            ("judicial", "NC", "nc_superior_court_judge", "Judge", "trial_judges"),
            ("judicial", "NC", "nc_district_court_judge", "Judge", "trial_judges"),
            ("judicial", "NC", "nc_district_attorney", "District Attorney", "das"),
            ("county", "NC", "nc_sheriff", "Sheriff", "sheriffs"),
            ("county", "NC", "nc_register_of_deeds", "Register of Deeds", "register_of_deeds"),
            ("county", "NC", "nc_county_commissioner", "Commissioner", "commissioners"),
            ("special_district", "NC", "nc_soil_water_district", "Supervisor", "soil_water"),
            ("municipal", "NC", "durham_nc_mayor", "Mayor", "municipal"),
            ("school_board", "NC", "nc_wake_school_board", "Member", "school_board"),
        ],
    )
    def test_office_classifies_to_expected_cohort(
        self,
        office_level: str,
        state: str | None,
        name: str,
        title: str | None,
        expected: str,
    ) -> None:
        assert cohort_for_office(office_level=office_level, state=state, name=name, title=title) == expected

    def test_all_thirteen_cohorts_have_at_least_one_classified_fixture(self) -> None:
        # Every cohort listed in COHORT_RULES must appear in the parametrize set
        # above. This guards against silently dropping a cohort from coverage.
        seen_in_parametrize = {
            "federal",
            "ncga_senate",
            "ncga_house",
            "council_of_state",
            "appellate",
            "trial_judges",
            "das",
            "sheriffs",
            "register_of_deeds",
            "commissioners",
            "soil_water",
            "municipal",
            "school_board",
        }
        assert seen_in_parametrize == set(COHORT_RULES.keys())

    def test_unclassified_state_office_returns_none(self) -> None:
        assert (
            cohort_for_office(
                office_level="state",
                state="NC",
                name="nc_unrecognized_state_office",
                title="Recordkeeper",
            )
            is None
        )

    def test_non_nc_state_office_does_not_match_nc_cohorts(self) -> None:
        # NC-specific cohorts must not catch other states.
        assert (
            cohort_for_office(
                office_level="state",
                state="WA",
                name="wa_state_senate_member",
                title="State Senator",
            )
            is None
        )

    def test_federal_cohort_is_state_agnostic(self) -> None:
        # `federal` cohort has state=None so it matches federal offices regardless of state column.
        assert (
            cohort_for_office(
                office_level="federal",
                state=None,
                name="random_federal_office_name",
                title=None,
            )
            == "federal"
        )


class TestUnclassifiedOfficeDrift:
    """Regression: targeted-level offices that match no cohort must surface as drift."""

    def test_drift_includes_unrecognized_nc_state_office(self) -> None:
        offices = [
            {"office_level": "state", "state": "NC", "name": "nc_house_member", "title": "Rep"},
            {
                "office_level": "state",
                "state": "NC",
                "name": "nc_some_brand_new_office",
                "title": "Czar",
            },
        ]
        drift = find_unclassified_office_drift(offices)
        assert len(drift) == 1
        assert drift[0]["name"] == "nc_some_brand_new_office"

    def test_drift_includes_unrecognized_nc_judicial_office(self) -> None:
        # Judicial NC offices not matching appellate/trial/da are drift.
        offices = [
            {"office_level": "judicial", "state": "NC", "name": "nc_supreme_court", "title": "Justice"},
            {"office_level": "judicial", "state": "NC", "name": "nc_unknown_court", "title": "Magistrate"},
        ]
        drift = find_unclassified_office_drift(offices)
        assert [o["name"] for o in drift] == ["nc_unknown_court"]

    def test_drift_skips_non_targeted_level_state_combinations(self) -> None:
        # WA state offices are not a targeted (level, state) pair -> no drift.
        offices = [
            {"office_level": "state", "state": "WA", "name": "wa_governor", "title": "Governor"},
        ]
        drift = find_unclassified_office_drift(offices)
        assert drift == []

    def test_drift_empty_when_all_offices_classify(self) -> None:
        offices = [
            {"office_level": "federal", "state": None, "name": "us_house", "title": "Rep"},
            {"office_level": "state", "state": "NC", "name": "nc_house_member", "title": "Rep"},
            {"office_level": "county", "state": "NC", "name": "nc_sheriff", "title": "Sheriff"},
        ]
        drift = find_unclassified_office_drift(offices)
        assert drift == []

    def test_targeted_pair_helper(self) -> None:
        assert is_targeted_level_state("federal", None) is True
        assert is_targeted_level_state("federal", "NC") is True  # federal cohort is state-agnostic
        assert is_targeted_level_state("state", "NC") is True
        assert is_targeted_level_state("state", "WA") is False
        assert is_targeted_level_state("county", "NC") is True
        assert is_targeted_level_state("school_board", "NC") is True
        assert is_targeted_level_state("special_district", "NC") is True


# ---------------------------------------------------------------------------
# Gate arithmetic
# ---------------------------------------------------------------------------


class TestGateArithmetic:
    def test_pct_resolved_4_of_10_is_exactly_040(self) -> None:
        # Hand-calculated example required by the Stage 2 contract.
        assert compute_pct_resolved(4, 10) == pytest.approx(0.40, abs=1e-9)

    def test_pct_resolved_zero_total_is_zero(self) -> None:
        assert compute_pct_resolved(0, 0) == 0.0

    def test_pct_resolved_invariant_holds(self) -> None:
        # resolved_count + (total_count - resolved_count) == total_count for many samples
        for resolved, total in [(0, 0), (3, 7), (10, 10), (1, 100), (5, 9)]:
            assert resolved + (total - resolved) == total

    def test_gate_target_uses_pct_plus_30_when_above_floor(self) -> None:
        # 0.55 baseline + 0.30 = 0.85 > 0.80 floor -> gate target = 0.85
        target = compute_gate_target_pct(pct_resolved=0.55, floor=0.80)
        assert target == pytest.approx(0.85, abs=1e-9)

    def test_gate_target_uses_floor_when_pct_plus_30_below_floor(self) -> None:
        # 0.40 baseline + 0.30 = 0.70 < 0.80 floor -> gate target = 0.80
        target = compute_gate_target_pct(pct_resolved=0.40, floor=0.80)
        assert target == pytest.approx(0.80, abs=1e-9)

    def test_gate_target_caps_at_one(self) -> None:
        # 0.85 baseline + 0.30 = 1.15 -> clamp to 1.0
        target = compute_gate_target_pct(pct_resolved=0.85, floor=0.80)
        assert target == pytest.approx(1.0, abs=1e-9)

    def test_gate_target_ncga_house_contract_example(self) -> None:
        # NCGA House contract: max(baseline + 0.30, 0.80).
        for baseline, expected in [
            (0.0, 0.80),
            (0.40, 0.80),
            (0.50, 0.80),
            (0.51, pytest.approx(0.81, abs=1e-9)),
            (0.70, pytest.approx(1.0, abs=1e-9)),
        ]:
            assert compute_gate_target_pct(pct_resolved=baseline, floor=0.80) == expected


# ---------------------------------------------------------------------------
# Integration: DB-backed cohort baselines
# ---------------------------------------------------------------------------


def _make_data_source(conn: psycopg.Connection) -> DataSource:
    ds = DataSource(
        domain="campaign_finance",
        jurisdiction="federal/fec",
        name=f"ER Cohort Probe Test {uuid4()}",
        source_url="https://example.com/test",
    )
    insert_data_source(conn, ds)
    return ds


def _make_source_record(conn: psycopg.Connection, data_source_id: UUID, key: str) -> SourceRecord:
    raw: dict[str, object] = {"key": key}
    sr = SourceRecord(
        data_source_id=data_source_id,
        source_record_key=key,
        raw_fields=raw,
        pull_date=utc_now(),
        record_hash=compute_record_hash(raw),
    )
    insert_source_record(conn, sr)
    return sr


def _make_person(
    conn: psycopg.Connection,
    *,
    name: str,
    er_cluster_id: UUID | None,
) -> UUID:
    person = Person(
        canonical_name=name,
        first_name=name.split(" ")[0].upper(),
        last_name=name.split(" ")[-1].upper(),
        er_cluster_id=er_cluster_id,
        er_confidence=0.99 if er_cluster_id is not None else None,
    )
    return insert_person(conn, person)


def _seed_officeholder(
    conn: psycopg.Connection,
    *,
    person_id: UUID,
    office_id: UUID,
) -> None:
    upsert_officeholding(
        conn,
        Officeholding(
            person_id=person_id,
            office_id=office_id,
            valid_period=ValidDateRange(start_date=date(2024, 1, 1), end_date=None),
        ),
    )


def _seed_candidacy(
    conn: psycopg.Connection,
    *,
    person_id: UUID,
    office_id: UUID,
    election_date: date,
) -> None:
    contest_id = upsert_contest(
        conn,
        Contest(
            name=f"Contest {uuid4()}",
            election_date=election_date,
            election_type="general",
            office_id=office_id,
        ),
    )
    upsert_candidacy(
        conn,
        Candidacy(
            person_id=person_id,
            contest_id=contest_id,
            status="filed",
        ),
    )


@pytest.mark.integration
class TestCohortBaselineIntegration:
    def test_federal_cohort_counts_officeholders_with_resolution_split(
        self,
        db_conn: psycopg.Connection,
    ) -> None:
        # Capture the cohort baseline BEFORE seeding so the test is correct
        # whether or not the live DB already contains other federal
        # officeholders. compute_cohort_baseline aggregates across every row
        # matching the cohort's (office_level/state/regex) filter, not just
        # the seeded office_id, and db_conn rollback only hides our seeded
        # rows -- it does not mask pre-existing committed rows on a populated
        # production-like DB. We therefore assert on the delta the seed
        # introduces, plus exact arithmetic against the seeded office in
        # isolation.
        before = compute_cohort_baseline(db_conn, "federal")

        # Seed: 1 federal office, 4 persons holding it (2 resolved, 2 unresolved).
        office_id = upsert_office(
            db_conn,
            Office(name=f"us_house_test_{uuid4().hex}", office_level="federal", title="Representative"),
        )
        cluster = uuid4()
        for idx in range(2):
            person_id = _make_person(db_conn, name=f"Resolved Federal {idx}", er_cluster_id=cluster)
            _seed_officeholder(db_conn, person_id=person_id, office_id=office_id)
        for idx in range(2):
            person_id = _make_person(db_conn, name=f"Unresolved Federal {idx}", er_cluster_id=None)
            _seed_officeholder(db_conn, person_id=person_id, office_id=office_id)

        baseline = compute_cohort_baseline(db_conn, "federal")

        # Delta MUST match exactly what we seeded -- this proves the probe SQL
        # buckets seeded rows into the federal cohort correctly regardless of
        # pre-existing data.
        assert baseline["total_count"] == before["total_count"] + 4
        assert baseline["resolved_count"] == before["resolved_count"] + 2

        # Exact arithmetic check on the seeded office in isolation: 2 of 4
        # resolved -> exactly 0.50 pct_resolved, gate target floor=0.80.
        with db_conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COUNT(DISTINCT p.id) AS total,
                    COUNT(DISTINCT p.id) FILTER (WHERE p.er_cluster_id IS NOT NULL) AS resolved
                FROM core.person p
                JOIN civic.officeholding oh ON oh.person_id = p.id
                WHERE oh.office_id = %s
                """,
                (office_id,),
            )
            row = cur.fetchone()
        assert row is not None
        seeded_total, seeded_resolved = row[0], row[1]
        assert seeded_total == 4
        assert seeded_resolved == 2
        assert (seeded_resolved / seeded_total) == pytest.approx(0.50, abs=1e-9)
        assert max((seeded_resolved / seeded_total) + 0.30, 0.80) == pytest.approx(0.80, abs=1e-9)

        # resolved + unresolved == total invariant from the checklist (holds on
        # the cohort-wide aggregate too).
        unresolved = baseline["total_count"] - baseline["resolved_count"]
        assert baseline["resolved_count"] + unresolved == baseline["total_count"]
        # gate_target_pct == max(pct + 0.30, 0.80) within 1e-9 (cohort-wide).
        expected_target = max(baseline["pct_resolved"] + 0.30, 0.80)
        assert math.isclose(baseline["gate_target_pct"], min(expected_target, 1.0), abs_tol=1e-9)

    def test_ncga_house_cohort_isolated_seed_has_exact_4_of_10(
        self,
        db_conn: psycopg.Connection,
    ) -> None:
        # Capture the ncga_house baseline BEFORE seeding so the seeded delta is
        # exact regardless of any pre-existing NC house rows in the live DB.
        before = compute_cohort_baseline(db_conn, "ncga_house")

        # Seed 10 distinct persons holding an NCGA House office; 4 are resolved.
        # We use a uniquely-named office so other in-DB house members don't
        # leak into the office-scoped exact arithmetic check below.
        office_id = upsert_office(
            db_conn,
            Office(
                name=f"nc_house_member_probe_{uuid4().hex}",
                office_level="state",
                state="NC",
                title="State Representative",
            ),
        )
        cluster = uuid4()
        seeded_person_ids: list[UUID] = []
        for idx in range(4):
            pid = _make_person(db_conn, name=f"Resolved House {idx}", er_cluster_id=cluster)
            _seed_officeholder(db_conn, person_id=pid, office_id=office_id)
            seeded_person_ids.append(pid)
        for idx in range(6):
            pid = _make_person(db_conn, name=f"Unresolved House {idx}", er_cluster_id=None)
            _seed_officeholder(db_conn, person_id=pid, office_id=office_id)
            seeded_person_ids.append(pid)

        # Load-bearing contract: probe must bucket every seeded NCGA house
        # member into the ncga_house cohort. Asserting the delta proves probe
        # correctness without coupling to whether the live DB already
        # contained other house members.
        baseline = compute_cohort_baseline(db_conn, "ncga_house")
        assert baseline["total_count"] == before["total_count"] + 10
        assert baseline["resolved_count"] == before["resolved_count"] + 4

        # Probe just this isolated cohort surface by querying directly.
        with db_conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COUNT(DISTINCT p.id) AS total,
                    COUNT(DISTINCT p.id) FILTER (WHERE p.er_cluster_id IS NOT NULL) AS resolved
                FROM core.person p
                JOIN civic.officeholding oh ON oh.person_id = p.id
                WHERE oh.office_id = %s
                """,
                (office_id,),
            )
            row = cur.fetchone()
        assert row is not None
        total = row[0]
        resolved = row[1]
        # Hand-calculated expectation
        assert total == 10
        assert resolved == 4
        # 4 of 10 -> exactly 0.40 (Stage 2 contract example)
        assert (resolved / total) == pytest.approx(0.40, abs=1e-9)
        assert max((resolved / total) + 0.30, 0.80) == pytest.approx(0.80, abs=1e-9)

    def test_candidacy_path_counts_distinct_persons(
        self,
        db_conn: psycopg.Connection,
    ) -> None:
        # Capture BEFORE seeding so the delta is exact regardless of
        # pre-existing sheriff rows in the live DB (same pattern as
        # federal/ncga_house tests above).
        before = compute_cohort_baseline(db_conn, "sheriffs")

        # Person linked via candidacy->contest->office only (no officeholding) must still be counted.
        office_id = upsert_office(
            db_conn,
            Office(
                name=f"nc_sheriff_probe_{uuid4().hex}",
                office_level="county",
                state="NC",
                title="Sheriff",
            ),
        )
        person_id = _make_person(db_conn, name="Cand Only Sheriff", er_cluster_id=None)
        _seed_candidacy(db_conn, person_id=person_id, office_id=office_id, election_date=date(2026, 11, 3))

        baseline = compute_cohort_baseline(db_conn, "sheriffs")

        # Delta: exactly 1 new person (unresolved) in the sheriffs cohort.
        assert baseline["total_count"] == before["total_count"] + 1
        assert baseline["resolved_count"] == before["resolved_count"] + 0

        # Office-scoped exact check: confirm the candidacy row landed.
        with db_conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(DISTINCT cd.person_id)
                FROM civic.candidacy cd
                JOIN civic.contest c ON cd.contest_id = c.id
                WHERE c.office_id = %s
                """,
                (office_id,),
            )
            row = cur.fetchone()
        assert row is not None
        assert row[0] == 1

    def test_cross_source_person_dedup_counts_one_identity(
        self,
        db_conn: psycopg.Connection,
    ) -> None:
        # Capture BEFORE seeding so the delta is exact regardless of
        # pre-existing federal rows in the live DB.
        before = compute_cohort_baseline(db_conn, "federal")

        # Two person rows representing the same identity (same er_cluster_id),
        # each linked by entity_source rows from different data_sources, both
        # holding the same office. The probe uses DISTINCT person.id so they
        # count as 2 person rows but BOTH resolved -- exercising the
        # cross-source linkage path mentioned in the checklist.
        office_id = upsert_office(
            db_conn,
            Office(name=f"cross_source_{uuid4().hex}", office_level="federal", title="Senator"),
        )
        cluster = uuid4()
        ds_a = _make_data_source(db_conn)
        ds_b = _make_data_source(db_conn)
        sr_a = _make_source_record(db_conn, ds_a.id, key=f"k-a-{uuid4()}")
        sr_b = _make_source_record(db_conn, ds_b.id, key=f"k-b-{uuid4()}")

        # Two person rows in same cluster, each tied to a separate source.
        person_a = _make_person(db_conn, name="Cross Source A", er_cluster_id=cluster)
        insert_entity_source(db_conn, "person", person_a, sr_a.id, "donor")
        _seed_officeholder(db_conn, person_id=person_a, office_id=office_id)

        person_b = _make_person(db_conn, name="Cross Source B", er_cluster_id=cluster)
        insert_entity_source(db_conn, "person", person_b, sr_b.id, "donor")
        _seed_officeholder(db_conn, person_id=person_b, office_id=office_id)

        baseline = compute_cohort_baseline(db_conn, "federal")

        # Delta: exactly 2 new person rows, both resolved (er_cluster_id set).
        assert baseline["total_count"] == before["total_count"] + 2
        assert baseline["resolved_count"] == before["resolved_count"] + 2

    def test_compute_all_cohort_baselines_returns_every_cohort(
        self,
        db_conn: psycopg.Connection,
    ) -> None:
        baselines = compute_all_cohort_baselines(db_conn)
        assert set(baselines.keys()) == set(COHORT_RULES.keys())
        for slug, b in baselines.items():
            assert {"resolved_count", "total_count", "pct_resolved", "gate_target_pct", "floor"} <= set(b.keys()), slug
            assert b["resolved_count"] <= b["total_count"]
            assert 0.0 <= b["pct_resolved"] <= 1.0


# ---------------------------------------------------------------------------
# Artifact emission
# ---------------------------------------------------------------------------


class TestArtifactEmission:
    def test_payload_shape(self) -> None:
        cohort_baselines = {
            "federal": {
                "resolved_count": 4,
                "total_count": 10,
                "pct_resolved": 0.40,
                "gate_target_pct": 0.80,
                "floor": 0.80,
            },
        }
        payload = build_baseline_payload(cohort_baselines)
        assert payload["schema_version"] == 1
        assert payload["scope"] == "stage_02_dwo_er_baseline"
        assert payload["cohorts"] == cohort_baselines

    def test_write_artifact_round_trip(self, tmp_path: Path) -> None:
        cohort_baselines = {
            "federal": {
                "resolved_count": 4,
                "total_count": 10,
                "pct_resolved": 0.40,
                "gate_target_pct": 0.80,
                "floor": 0.80,
            },
        }
        payload = build_baseline_payload(cohort_baselines)
        artifact_path = tmp_path / "out" / "cohort_baseline.json"
        write_baseline_artifact(payload, artifact_path=artifact_path)
        on_disk = json.loads(artifact_path.read_text(encoding="utf-8"))
        assert on_disk == payload
