from __future__ import annotations

import json
from pathlib import Path
from xml.etree import ElementTree
from typing import Any

import psycopg
from bs4 import BeautifulSoup

from domains.civics.loaders.official_rosters.loader import harvest_official_roster
from domains.civics.loaders.official_rosters.parsers import parse_roster_rows
from domains.civics.loaders.official_rosters.source_templates import roster_source_templates
from scripts.register_roster_pilot_sources import register_roster_pilot_sources

_FIXTURE_DIR = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "roster"

EXPECTED_OFFICEHOLDING_COUNTS_BY_SOURCE = {
    "us_house_nc": 14,
    "us_senate_nc_class_ii": 1,
    "us_senate_nc_class_iii": 1,
    "nc_senate": 50,
    "nc_gov": 1,
    "nc_lt_gov": 1,
    "nc_attorney_general": 1,
    "nc_sec_of_state": 1,
    "nc_treasurer": 1,
    "nc_auditor": 1,
    "nc_supt_pub_instr": 1,
    "nc_ag_commissioner": 1,
    "nc_ins_commissioner": 1,
    "nc_labor_commissioner": 1,
    "nc_supreme_court": 7,
    "nc_court_of_appeals": 15,
}

FIXTURE_BY_BODY_KEY = {
    "nc_gov": "nc_council_of_state_nc_gov.html",
    "nc_lt_gov": "nc_council_of_state_nc_lt_gov.html",
    "nc_attorney_general": "nc_council_of_state_nc_attorney_general.html",
    "nc_sec_of_state": "nc_council_of_state_nc_sec_of_state.html",
    "nc_treasurer": "nc_council_of_state_nc_treasurer.html",
    "nc_auditor": "nc_council_of_state_nc_auditor.html",
    "nc_supt_pub_instr": "nc_council_of_state_nc_supt_pub_instr.html",
    "nc_ag_commissioner": "nc_council_of_state_nc_ag_commissioner.html",
    "nc_ins_commissioner": "nc_council_of_state_nc_ins_commissioner.html",
    "nc_labor_commissioner": "nc_council_of_state_nc_labor_commissioner.html",
    "nc_supreme_court": "nc_supreme_court.html",
    "nc_court_of_appeals": "nc_court_of_appeals.html",
}

STAGE5_LOCAL_PROOF_ARTIFACT_RELATIVE_PATH = Path(
    "docs/research/artifacts/2026_04_29_dwo_rosters/local/stage5_statewide_roster_local_proof.json"
)


def fixture_path(name: str) -> Path:
    return _FIXTURE_DIR / name


def select_counts_for_source(connection: psycopg.Connection, source_id: str) -> tuple[int, int, int]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                (SELECT COUNT(*)
                 FROM core.source_record sr
                 JOIN core.data_source ds ON ds.id = sr.data_source_id
                 WHERE ds.notes::jsonb->>'registry_source_id' = %s),
                (SELECT COUNT(*)
                 FROM core.person_portrait pp
                 JOIN core.source_record sr ON sr.id = pp.source_record_id
                 JOIN core.data_source ds ON ds.id = sr.data_source_id
                 WHERE ds.notes::jsonb->>'registry_source_id' = %s),
                (SELECT COUNT(*)
                 FROM civic.officeholding oh
                 JOIN core.source_record sr ON sr.id = oh.source_record_id
                 JOIN core.data_source ds ON ds.id = sr.data_source_id
                 WHERE ds.notes::jsonb->>'registry_source_id' = %s)
            """,
            (source_id, source_id, source_id),
        )
        row = cursor.fetchone()
    assert row is not None
    return row[0], row[1], row[2]


def seed_person_names(connection: psycopg.Connection, names: list[str]) -> None:
    rows: list[tuple[str, str, str]] = []
    for canonical_name in names:
        parts = canonical_name.split()
        if len(parts) < 2:
            continue
        rows.append((canonical_name, parts[0], parts[-1]))
    with connection.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO core.person (id, canonical_name, first_name, last_name, identifiers)
            VALUES (gen_random_uuid(), %s, %s, %s, '{}'::jsonb)
            ON CONFLICT DO NOTHING
            """,
            rows,
        )


def write_senate_fixture(path: Path, *, senate_class: str, member_name: str) -> None:
    root = ElementTree.fromstring(fixture_path("us_senate_contact_information_sample.xml").read_text(encoding="utf-8"))
    members = root.findall("./member")
    assert len(members) == 2
    first = members[0]
    first.find("member_full").text = member_name
    name_parts = member_name.split(" ", 1)
    first.find("first_name").text = name_parts[0]
    first.find("last_name").text = name_parts[1]
    first.find("state").text = "NC"
    first.find("class").text = senate_class
    path.write_text(ElementTree.tostring(root, encoding="unicode"), encoding="utf-8")


def resolve_snapshot_stats(connection: psycopg.Connection, source_id: str, source_record_key: str) -> tuple[int, int]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM core.source_record sr
            JOIN core.data_source ds ON ds.id = sr.data_source_id
            WHERE ds.notes::jsonb->>'registry_source_id' = %s
              AND sr.source_record_key = %s
              AND sr.superseded_by IS NULL
            """,
            (source_id, source_record_key),
        )
        snapshot_count = cursor.fetchone()[0]
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM civic.officeholding oh
            JOIN core.source_record sr ON sr.id = oh.source_record_id
            JOIN core.data_source ds ON ds.id = sr.data_source_id
            WHERE ds.notes::jsonb->>'registry_source_id' = %s
              AND sr.source_record_key = %s
            """,
            (source_id, source_record_key),
        )
        officeholding_count = cursor.fetchone()[0]
    return snapshot_count, officeholding_count


def write_us_house_fixture(path: Path) -> None:
    root = ElementTree.fromstring(fixture_path("us_house_member_data_sample.xml").read_text(encoding="utf-8"))
    members = root.findall("./member")
    assert members

    template = members[0]
    for member in members:
        root.remove(member)

    for district_number in range(1, 15):
        member = ElementTree.fromstring(ElementTree.tostring(template, encoding="unicode"))
        member.find("state").text = "NC"
        member.find("district").text = str(district_number)
        member.find("party").text = "R" if district_number % 2 == 0 else "D"
        member.find("member_name").text = f"MEMBER{district_number:02d}, House{district_number:02d}"
        member.find("first_name").text = f"House{district_number:02d}"
        member.find("last_name").text = f"MEMBER{district_number:02d}"
        root.append(member)

    path.write_text(ElementTree.tostring(root, encoding="unicode"), encoding="utf-8")


def write_nc_senate_fixture(path: Path) -> None:
    soup = BeautifulSoup(fixture_path("nc_general_assembly_senate.html").read_text(encoding="utf-8"), "html.parser")
    row_root = soup.select_one("div.row.ncga-row-no-gutters.d-print-block")
    cards = soup.select("div.member-col")
    assert row_root is not None
    assert cards

    template_html = str(cards[0])
    for card in cards:
        card.extract()

    for district_number in range(1, 51):
        card = BeautifulSoup(template_html, "html.parser").select_one("div.member-col")
        assert card is not None
        member_name = f"Senator {district_number:02d}"
        bio_link = card.select_one('.member-info-col a[href*="/Members/Biography/S/"]')
        district_link = card.select_one('.member-info-col a[href*="/Redistricting/DistrictPlanMap/"]')
        image = card.select_one(".member-image-col img")
        bio_anchor = card.select_one('.member-image-col a[href*="/Members/Biography/S/"]')
        assert bio_link is not None
        assert district_link is not None
        assert image is not None
        assert bio_anchor is not None
        bio_href = f"/Members/Biography/S/{500 + district_number}"
        bio_link.string = member_name
        bio_link["href"] = bio_href
        bio_anchor["href"] = bio_href
        district_link.string = f"District {district_number}"
        district_link["href"] = f"/Redistricting/DistrictPlanMap/S2023E/{district_number}"
        image["src"] = f"/Members/MemberImage/S/{500 + district_number}/Low"
        row_root.append(card)

    path.write_text(str(soup), encoding="utf-8")


def stage5_sources_by_id() -> dict[str, Any]:
    stage5_source_ids = set(EXPECTED_OFFICEHOLDING_COUNTS_BY_SOURCE)
    return {
        template.registry_source_id: template
        for template in roster_source_templates()
        if template.registry_source_id in stage5_source_ids
    }


def fixture_for_body_key(body_key: str, tmp_path: Path) -> Path:
    if body_key == "us_house_nc":
        path = tmp_path / "us_house_nc.xml"
        write_us_house_fixture(path)
        return path
    if body_key == "nc_senate":
        path = tmp_path / "nc_senate.html"
        write_nc_senate_fixture(path)
        return path
    if body_key == "us_senate_nc_class_ii":
        path = tmp_path / "us_senate_nc_class_ii.xml"
        write_senate_fixture(path, senate_class="2", member_name="Avery Classii")
        return path
    if body_key == "us_senate_nc_class_iii":
        path = tmp_path / "us_senate_nc_class_iii.xml"
        write_senate_fixture(path, senate_class="3", member_name="Blair Classthree")
        return path
    return fixture_path(FIXTURE_BY_BODY_KEY[body_key])


def fixture_for_source_id(source_id: str, tmp_path: Path) -> Path:
    template = stage5_sources_by_id()[source_id]
    return fixture_for_body_key(template.body_key, tmp_path)


def seed_persons_for_sources(connection: psycopg.Connection, tmp_path: Path) -> None:
    names: list[str] = []
    sources = stage5_sources_by_id()
    for source_id in EXPECTED_OFFICEHOLDING_COUNTS_BY_SOURCE:
        template = sources[source_id]
        fixture = fixture_for_body_key(template.body_key, tmp_path)
        rows = parse_roster_rows(
            body_key=template.body_key,
            source_url=template.source_url,
            html=fixture.read_text(encoding="utf-8"),
        )
        names.extend(row.member_name for row in rows)
    seed_person_names(connection, sorted(set(names)))


def build_stage5_local_proof_payload(
    db_conn: psycopg.Connection,
    tmp_path: Path,
    *,
    expect_clean_first_run: bool,
) -> dict[str, object]:
    sources = stage5_sources_by_id()
    assert set(sources) == set(EXPECTED_OFFICEHOLDING_COUNTS_BY_SOURCE)

    register_roster_pilot_sources(db_conn)
    seed_persons_for_sources(db_conn, tmp_path)

    first_results = {}
    first_counts_by_source = {}
    first_snapshot_counts = {}
    first_officeholding_counts = {}
    for source_id, expected_count in EXPECTED_OFFICEHOLDING_COUNTS_BY_SOURCE.items():
        before_snapshot_count, _, before_officeholding_count = select_counts_for_source(db_conn, source_id)
        result = harvest_official_roster(
            db_conn,
            source_id=source_id,
            fixture_path=fixture_for_source_id(source_id, tmp_path),
            dry_run=False,
            fetch_bytes=lambda url, *, timeout_seconds: None,
        )
        after_snapshot_count, _, after_officeholding_count = select_counts_for_source(db_conn, source_id)
        assert result.officeholding_upserts == expected_count
        assert result.member_count == expected_count
        assert result.resolved_member_count == expected_count
        assert result.unresolved_member_count == 0
        if expect_clean_first_run:
            assert after_snapshot_count == before_snapshot_count + 1
            assert after_officeholding_count == before_officeholding_count + expected_count
        else:
            assert after_snapshot_count >= before_snapshot_count
            assert after_officeholding_count >= before_officeholding_count
        first_results[source_id] = result
        first_counts_by_source[source_id] = result.officeholding_upserts
        first_snapshot_counts[source_id] = after_snapshot_count
        first_officeholding_counts[source_id] = after_officeholding_count

    assert sum(first_counts_by_source.values()) == 98

    second_results = {}
    for source_id in EXPECTED_OFFICEHOLDING_COUNTS_BY_SOURCE:
        first = first_results[source_id]
        second = harvest_official_roster(
            db_conn,
            source_id=source_id,
            fixture_path=fixture_for_source_id(source_id, tmp_path),
            dry_run=False,
            fetch_bytes=lambda url, *, timeout_seconds: None,
        )
        assert second.source_record_inserted is False
        assert second.source_record_key == first.source_record_key
        assert second.source_record_id == first.source_record_id
        second_results[source_id] = second

    second_counts_by_source = {}
    for source_id, expected_count in EXPECTED_OFFICEHOLDING_COUNTS_BY_SOURCE.items():
        snapshot_count, _, officeholding_count = select_counts_for_source(db_conn, source_id)
        assert snapshot_count == first_snapshot_counts[source_id]
        assert officeholding_count == first_officeholding_counts[source_id]
        second_counts_by_source[source_id] = officeholding_count
        source_record_key = first_results[source_id].source_record_key
        active_snapshot_count, officeholding_count_for_key = resolve_snapshot_stats(db_conn, source_id, source_record_key)
        assert active_snapshot_count == 1
        assert officeholding_count_for_key == expected_count

    assert sum(second_counts_by_source.values()) == 98

    return {
        "source_ids": list(EXPECTED_OFFICEHOLDING_COUNTS_BY_SOURCE.keys()),
        "officeholding_counts_by_source": first_counts_by_source,
        "member_counts_by_source": {k: first_results[k].member_count for k in first_results},
        "combined_officeholding_total": sum(first_counts_by_source.values()),
        "snapshot_keys": {k: first_results[k].source_record_key for k in first_results},
        "idempotency": {
            "second_run_reused_source_record_ids": all(
                second_results[k].source_record_id == first_results[k].source_record_id
                for k in first_results
            ),
            "second_run_reused_source_record_keys": all(
                second_results[k].source_record_key == first_results[k].source_record_key
                for k in first_results
            ),
            "exact_second_run_officeholding_total": sum(second_counts_by_source.values()),
        },
    }


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def canonical_stage5_local_proof_artifact_path(repo_root_override: Path | None = None) -> Path:
    root = repo_root_override if repo_root_override is not None else repo_root()
    return root / STAGE5_LOCAL_PROOF_ARTIFACT_RELATIVE_PATH


def emit_stage5_local_proof_artifact(payload: dict[str, object], output_path: Path | None = None) -> Path:
    target_path = output_path if output_path is not None else canonical_stage5_local_proof_artifact_path()
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target_path
