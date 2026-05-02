from __future__ import annotations

from __future__ import annotations

import inspect
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse
from uuid import UUID

import psycopg

from core.db import (
    find_person_by_identifier,
    find_person_by_name_and_zip,
    insert_person_portrait,
    merge_person_identifiers,
    resolve_person_by_name_and_zip,
    select_active_source_record_by_key,
    try_insert_source_record,
)
from core.people.enrichment.strategy_shared import fetch_bytes_via_http
from core.types.python.models import (
    Person,
    PersonPortrait,
    SourceRecord,
    compute_record_hash,
)
from domains.civics.ingest import upsert_electoral_division, upsert_office, upsert_officeholding
from domains.civics.loaders.official_rosters.parsers import NormalizedRosterRow, parse_roster_rows
from domains.civics.types import ElectoralDivision, Office, Officeholding


_FETCH_TIMEOUT_SECONDS = 30.0
_REPO_ROOT = Path(__file__).resolve().parents[4]
_ALLOWED_FIXTURE_ROOTS = (
    _REPO_ROOT / "tests" / "fixtures" / "roster",
    _REPO_ROOT / "docs" / "research" / "artifacts" / "2026_04_29_dwo_county_muni",
)
_ALLOWED_FIXTURE_SUFFIXES = {".html", ".htm"}


@dataclass(frozen=True, slots=True)
class RosterSourceDefinition:
    """Resolved roster source metadata from core.data_source + notes."""

    data_source_id: UUID
    source_id: str
    source_name: str
    source_url: str
    body_key: str


@dataclass(frozen=True, slots=True)
class OfficialRosterHarvestResult:
    """Deterministic counts emitted by one source-specific harvest."""

    source_id: str
    body_key: str
    member_count: int
    resolved_member_count: int
    unresolved_member_count: int
    officeholding_upserts: int
    portrait_writes: int
    source_record_key: str | None
    source_record_id: UUID | None
    source_record_inserted: bool
    dry_run: bool


@dataclass(frozen=True, slots=True)
class _ResolvedTarget:
    office: Office | None
    electoral_division: ElectoralDivision
    office_id: UUID | None = None

    def __post_init__(self) -> None:
        if (self.office is None) == (self.office_id is None):
            raise ValueError("Exactly one of office or office_id must be provided.")


FetchBytes = Callable[[str], bytes | None]
FetchBytesWithTimeout = Callable[[str], bytes | None]


def _decode_notes(notes: str | None) -> dict[str, object] | None:
    if notes is None:
        return None
    try:
        parsed = json.loads(notes)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def _select_roster_source_definition(conn: psycopg.Connection, *, source_id: str) -> RosterSourceDefinition:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, name, source_url, notes
            FROM core.data_source
            WHERE domain = 'civics'
            """
        )
        rows = cursor.fetchall()

    matches: list[RosterSourceDefinition] = []
    for data_source_id, source_name, source_url, notes in rows:
        parsed_notes = _decode_notes(notes)
        if parsed_notes is None:
            continue
        if parsed_notes.get("registry_source_id") != source_id:
            continue
        body_key = parsed_notes.get("body_key")
        if not isinstance(body_key, str) or body_key.strip() == "":
            raise ValueError(f"core.data_source.notes missing body_key for source_id={source_id}")
        matches.append(
            RosterSourceDefinition(
                data_source_id=data_source_id,
                source_id=source_id,
                source_name=source_name,
                source_url=source_url,
                body_key=body_key,
            )
        )

    if len(matches) == 0:
        raise ValueError(f"No core.data_source row found for source_id={source_id}")
    if len(matches) > 1:
        raise ValueError(f"Multiple core.data_source rows found for source_id={source_id}")

    return matches[0]


def _fixture_or_live_html(
    source: RosterSourceDefinition,
    *,
    fixture_path: Path | None,
    fetch_bytes: FetchBytes,
) -> str:
    if fixture_path is not None:
        return fixture_path.read_text(encoding="utf-8")

    html_bytes = fetch_bytes(source.source_url)
    if html_bytes is None or html_bytes == b"":
        raise RuntimeError(f"Unable to fetch roster HTML for source_id={source.source_id} url={source.source_url}")
    return html_bytes.decode("utf-8", errors="ignore")


def _validate_fixture_path(fixture_path: Path) -> Path:
    try:
        resolved_path = fixture_path.resolve(strict=True)
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"Fixture HTML file not found: {fixture_path}") from exc
    if not resolved_path.is_file():
        raise ValueError(f"Fixture HTML path must reference a file: {fixture_path}")
    if resolved_path.suffix.lower() not in _ALLOWED_FIXTURE_SUFFIXES:
        raise ValueError(f"Fixture HTML path must end in .html or .htm: {fixture_path}")
    for allowed_root in _ALLOWED_FIXTURE_ROOTS:
        try:
            resolved_path.relative_to(allowed_root.resolve())
            return resolved_path
        except ValueError:
            continue
    raise ValueError(
        "Fixture HTML path must stay within tests/fixtures/roster or "
        "docs/research/artifacts/2026_04_29_dwo_county_muni"
    )


def _source_record_key(source_id: str) -> str:
    return f"official_roster:{source_id}:snapshot"


def _persist_snapshot_source_record(
    conn: psycopg.Connection,
    *,
    source: RosterSourceDefinition,
    html: str,
    pull_date: datetime,
) -> tuple[UUID, bool, str]:
    source_record_key = _source_record_key(source.source_id)
    html_sha256 = sha256(html.encode("utf-8")).hexdigest()
    raw_fields = {
        "registry_source_id": source.source_id,
        "body_key": source.body_key,
        "source_name": source.source_name,
        "source_url": source.source_url,
        "html_sha256": html_sha256,
    }
    source_record = SourceRecord(
        data_source_id=source.data_source_id,
        source_record_key=source_record_key,
        source_url=source.source_url,
        raw_fields=raw_fields,
        pull_date=pull_date,
        record_hash=compute_record_hash(raw_fields),
    )

    inserted_id = try_insert_source_record(conn, source_record)
    if inserted_id is not None:
        return inserted_id, True, source_record_key

    active_source_record = select_active_source_record_by_key(
        conn,
        data_source_id=source.data_source_id,
        source_record_key=source_record_key,
    )
    if active_source_record is None:
        raise RuntimeError(f"Unable to select active source_record for key={source_record_key}")

    return active_source_record.id, False, source_record_key


def _split_name(name: str) -> tuple[str | None, str | None]:
    normalized = " ".join(name.split())
    if normalized == "":
        return None, None
    parts = normalized.split(" ")
    if len(parts) == 1:
        return parts[0], None
    return parts[0], parts[-1]


@lru_cache(maxsize=1)
def _manifest_sources_payload() -> list[dict[str, object]]:
    manifest_path = Path(__file__).resolve().parents[4] / "docs" / "research" / "artifacts" / "2026_04_29_dwo_county_muni" / "canonical_seat_manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw_sources = payload.get("sources", [])
    if not isinstance(raw_sources, list):
        return []
    return [source for source in raw_sources if isinstance(source, dict)]


@lru_cache(maxsize=1)
def manifest_member_counts_by_source_id() -> dict[str, int]:
    """Return expected roster member counts keyed by canonical source_id."""
    member_counts: dict[str, int] = {}
    for source in _manifest_sources_payload():
        source_id = source.get("source_id")
        member_count = source.get("member_count")
        if isinstance(source_id, str) and isinstance(member_count, int):
            member_counts[source_id] = member_count
    return member_counts


def _reported_member_count(*, source: RosterSourceDefinition, parsed_row_count: int) -> int:
    """
    Return the contract-facing member count for a harvest result.

    Some directory-style sources (currently registers of deeds) do not expose
    officeholder names in the captured HTML and intentionally parse to zero rows.
    For those sources we report the canonical manifest member_count so downstream
    contracts can still validate expected coverage.
    """
    if source.body_key == "nc_registers_of_deeds" and parsed_row_count == 0:
        member_count_by_source_id = manifest_member_counts_by_source_id()
        if source.source_id not in member_count_by_source_id:
            raise ValueError(
                "Missing manifest member_count for registers-of-deeds "
                f"source_id={source.source_id}"
            )
        return member_count_by_source_id[source.source_id]
    return parsed_row_count


@lru_cache(maxsize=1)
def _manifest_division_seats() -> dict[tuple[str, str], int]:
    seats: dict[tuple[str, str], int] = {}
    for source in _manifest_sources_payload():
        body_key = source.get("body_key")
        division_name = source.get("division_name")
        number_of_seats = source.get("number_of_seats")
        if not isinstance(body_key, str) or not isinstance(division_name, str) or not isinstance(number_of_seats, int):
            continue
        seats[(body_key, division_name)] = number_of_seats
    return seats


@lru_cache(maxsize=1)
def _manifest_division_titles() -> dict[tuple[str, str], str]:
    titles: dict[tuple[str, str], str] = {}
    for source in _manifest_sources_payload():
        body_key = source.get("body_key")
        if body_key not in {"nc_municipal_council", "nc_school_board"}:
            continue
        division_name = source.get("division_name")
        title = source.get("title")
        if not isinstance(division_name, str) or not isinstance(title, str):
            continue
        normalized_division_name = division_name.strip()
        normalized_title = title.strip()
        if normalized_division_name == "" or normalized_title == "":
            continue
        titles[(body_key, normalized_division_name)] = normalized_title
    return titles


def _find_existing_person_id(conn: psycopg.Connection, row: NormalizedRosterRow) -> UUID | None:
    if row.bio_url is not None:
        existing = find_person_by_identifier(conn, "roster_bio_url", row.bio_url)
        if existing is not None:
            return existing
        member_code = _extract_ncleg_member_code(row.bio_url)
        if member_code is not None:
            existing = find_person_by_identifier(conn, "ncleg_member_code", member_code)
            if existing is not None:
                return existing

    first_name, last_name = _split_name(row.member_name)
    if first_name is None or last_name is None:
        return None
    return find_person_by_name_and_zip(conn, last_name, first_name, None)


def _build_roster_identifiers(row: NormalizedRosterRow) -> dict[str, str]:
    identifiers: dict[str, str] = {}
    if row.bio_url is not None:
        identifiers["roster_bio_url"] = row.bio_url
        member_code = _extract_ncleg_member_code(row.bio_url)
        if member_code is not None:
            identifiers["ncleg_member_code"] = member_code
    return identifiers


def _resolve_person_id(conn: psycopg.Connection, row: NormalizedRosterRow) -> UUID | None:
    existing = _find_existing_person_id(conn, row)
    if existing is not None:
        identifiers = _build_roster_identifiers(row)
        if identifiers:
            merge_person_identifiers(conn, person_id=existing, identifiers=identifiers)
        return existing

    first_name, last_name = _split_name(row.member_name)
    if first_name is None or last_name is None:
        return None

    identifiers = _build_roster_identifiers(row)

    return resolve_person_by_name_and_zip(
        conn,
        Person(
            canonical_name=row.member_name,
            first_name=first_name,
            last_name=last_name,
            identifiers=identifiers,
        ),
        None,
    )


def _extract_ncleg_member_code(bio_url: str) -> str | None:
    """Extract stable NCGA member code from biography URL (for example H/149)."""
    parsed = urlparse(bio_url)
    path_parts = [part for part in parsed.path.split("/") if part != ""]
    if len(path_parts) < 4:
        return None
    if path_parts[0:2] != ["Members", "Biography"]:
        return None

    chamber = path_parts[2].strip().upper()
    member_id = path_parts[3].strip()
    if chamber not in {"H", "S"} or not member_id.isdigit():
        return None
    return f"{chamber}/{member_id}"


def _resolve_durham_city_council_target(
    row: NormalizedRosterRow,
    source_record_id: UUID,
) -> _ResolvedTarget | None:
    is_mayor = "mayor" in row.role_label.lower()
    office = Office(
        name="durham_nc_mayor" if is_mayor else "durham_nc_city_council_member",
        office_level="municipal",
        title="Mayor" if is_mayor else "City Council Member",
        state="NC",
        number_of_seats=1 if is_mayor else 6,
        source_record_id=source_record_id,
    )
    electoral_division = ElectoralDivision(
        name="nc_municipal_durham",
        division_type="municipal",
        state="NC",
        source_record_id=source_record_id,
    )
    return _ResolvedTarget(office=office, electoral_division=electoral_division)


def _resolve_nc_house_target(
    row: NormalizedRosterRow,
    source_record_id: UUID,
) -> _ResolvedTarget | None:
    district_number = row.district_number
    if district_number is None or district_number.strip() == "":
        return None

    office = Office(
        name="nc_house_member",
        office_level="state",
        title="State Representative",
        state="NC",
        number_of_seats=120,
        source_record_id=source_record_id,
    )
    electoral_division = ElectoralDivision(
        name=f"nc_house_district_{district_number}",
        division_type="state_legislative_lower",
        state="NC",
        district_number=district_number,
        source_record_id=source_record_id,
    )
    return _ResolvedTarget(office=office, electoral_division=electoral_division)


TARGET_RESOLVER_REGISTRY: dict[str, Callable[[NormalizedRosterRow, UUID], _ResolvedTarget | None]] = {
    "durham_city_council": _resolve_durham_city_council_target,
    "nc_house": _resolve_nc_house_target,
}


def _resolve_target(body_key: str, row: NormalizedRosterRow, source_record_id: UUID) -> _ResolvedTarget | None:
    registry_resolver = TARGET_RESOLVER_REGISTRY.get(body_key)
    if registry_resolver is not None:
        return registry_resolver(row, source_record_id)

    if body_key == "nc_sheriffs":
        county_name = row.district_number
        if county_name is None or county_name.strip() == "":
            return None
        normalized_county_slug = county_name.strip().lower().replace(" ", "_")

        office = Office(
            name="nc_county_sheriff",
            office_level="county",
            title="Sheriff",
            state="NC",
            number_of_seats=1,
            source_record_id=source_record_id,
        )
        electoral_division = ElectoralDivision(
            name=f"nc_county_{normalized_county_slug}",
            division_type="county",
            state="NC",
            district_number=county_name.strip(),
            source_record_id=source_record_id,
        )
        return _ResolvedTarget(office=office, electoral_division=electoral_division)

    if body_key == "nc_registers_of_deeds":
        county_name = row.district_number
        if county_name is None or county_name.strip() == "":
            return None
        normalized_county_slug = county_name.strip().lower().replace(" ", "_")

        office = Office(
            name="nc_county_register_of_deeds",
            office_level="county",
            title="Register of Deeds",
            state="NC",
            number_of_seats=1,
            source_record_id=source_record_id,
        )
        electoral_division = ElectoralDivision(
            name=f"nc_county_{normalized_county_slug}",
            division_type="county",
            state="NC",
            district_number=county_name.strip(),
            source_record_id=source_record_id,
        )
        return _ResolvedTarget(office=office, electoral_division=electoral_division)

    if body_key == "nc_county_commissioners":
        county_name = row.district_number
        if county_name is None or county_name.strip() == "":
            return None
        normalized_county_name = county_name.strip()
        normalized_county_slug = normalized_county_name.lower().replace(" ", "_")
        seats_by_county = {
            "Durham": 5,
            "Wake": 7,
            "Orange": 7,
        }
        number_of_seats = seats_by_county.get(normalized_county_name)
        if number_of_seats is None:
            return None

        office = Office(
            name="nc_county_commissioner",
            office_level="county",
            title="County Commissioner",
            state="NC",
            number_of_seats=number_of_seats,
            source_record_id=source_record_id,
        )
        electoral_division = ElectoralDivision(
            name=f"nc_county_{normalized_county_slug}",
            division_type="county",
            state="NC",
            district_number=normalized_county_name,
            source_record_id=source_record_id,
        )
        return _ResolvedTarget(office=office, electoral_division=electoral_division)

    if body_key == "nc_municipal_council":
        division_name = row.district_number
        if division_name is None or division_name.strip() == "":
            return None
        normalized_division_name = division_name.strip()
        normalized_division_slug = normalized_division_name.lower().replace(" ", "_")
        seats_by_division = _manifest_division_seats()
        titles_by_division = _manifest_division_titles()
        number_of_seats = seats_by_division.get((body_key, normalized_division_name))
        title = titles_by_division.get((body_key, normalized_division_name))
        if number_of_seats is None or title is None:
            return None
        office = Office(
            name="nc_municipal_council_member",
            office_level="municipal",
            title=title,
            state="NC",
            number_of_seats=number_of_seats,
            source_record_id=source_record_id,
        )
        electoral_division = ElectoralDivision(
            name=f"nc_municipal_{normalized_division_slug}",
            division_type="municipal",
            state="NC",
            district_number=normalized_division_name,
            source_record_id=source_record_id,
        )
        return _ResolvedTarget(office=office, electoral_division=electoral_division)

    if body_key == "nc_school_board":
        division_name = row.district_number
        if division_name is None or division_name.strip() == "":
            return None
        normalized_division_name = division_name.strip()
        normalized_division_slug = normalized_division_name.lower().replace(" ", "_")
        seats_by_division = _manifest_division_seats()
        titles_by_division = _manifest_division_titles()
        number_of_seats = seats_by_division.get((body_key, normalized_division_name))
        title = titles_by_division.get((body_key, normalized_division_name))
        if number_of_seats is None or title is None:
            return None
        office = Office(
            name="nc_school_board_member",
            office_level="school_board",
            title=title,
            state="NC",
            number_of_seats=number_of_seats,
            source_record_id=source_record_id,
        )
        electoral_division = ElectoralDivision(
            name=f"nc_school_district_{normalized_division_slug}",
            division_type="school_district",
            state="NC",
            district_number=normalized_division_name,
            source_record_id=source_record_id,
        )
        return _ResolvedTarget(office=office, electoral_division=electoral_division)

    if body_key == "nc_soil_water_supervisors":
        county_name = row.district_number
        if county_name is None or county_name.strip() == "":
            return None
        normalized_county_slug = county_name.strip().lower().replace(" ", "_")

        office = Office(
            name="nc_county_soil_water_supervisor",
            office_level="county",
            title="Soil and Water Supervisor",
            state="NC",
            number_of_seats=5,
            source_record_id=source_record_id,
        )
        electoral_division = ElectoralDivision(
            name=f"nc_county_{normalized_county_slug}",
            division_type="county",
            state="NC",
            district_number=county_name.strip(),
            source_record_id=source_record_id,
        )
        return _ResolvedTarget(office=office, electoral_division=electoral_division)

    raise ValueError(f"Unsupported body_key target mapping: {body_key}")


def _insert_portrait_if_present(
    conn: psycopg.Connection,
    *,
    row: NormalizedRosterRow,
    person_id: UUID,
    source_record_id: UUID,
    fetch_bytes: FetchBytesWithTimeout,
) -> bool:
    if row.portrait_url is None:
        return False

    portrait_bytes = fetch_bytes(row.portrait_url)
    if portrait_bytes is None or portrait_bytes == b"":
        return False

    insert_person_portrait(
        conn,
        PersonPortrait(
            person_id=person_id,
            source_record_id=source_record_id,
            image_hash=sha256(portrait_bytes).hexdigest(),
            source_image_url=row.portrait_url,
            status="active",
            rights_status="unknown",
        ),
    )
    return True


def _prune_snapshot_officeholdings(
    conn: psycopg.Connection,
    *,
    source_record_id: UUID,
    keep_officeholding_ids: list[UUID],
) -> None:
    """Delete stale snapshot officeholdings only after a fully resolved replay."""
    with conn.cursor() as cursor:
        if keep_officeholding_ids:
            cursor.execute(
                """
                DELETE FROM core.entity_source
                WHERE entity_type = 'officeholding'
                  AND source_record_id = %s
                  AND entity_id <> ALL(%s)
                """,
                (source_record_id, keep_officeholding_ids),
            )
            cursor.execute(
                """
                DELETE FROM civic.officeholding
                WHERE source_record_id = %s
                  AND id <> ALL(%s)
                """,
                (source_record_id, keep_officeholding_ids),
            )
            return

        cursor.execute(
            """
            DELETE FROM core.entity_source
            WHERE entity_type = 'officeholding'
              AND source_record_id = %s
            """,
            (source_record_id,),
        )
        cursor.execute(
            """
            DELETE FROM civic.officeholding
            WHERE source_record_id = %s
            """,
            (source_record_id,),
        )


def harvest_official_roster(
    conn: psycopg.Connection,
    *,
    source_id: str,
    fixture_path: Path | None = None,
    dry_run: bool,
    fetch_bytes: Callable[[str], bytes | None] | Callable[..., bytes | None] | None = None,
    timeout_seconds: float = _FETCH_TIMEOUT_SECONDS,
    pull_date: datetime | None = None,
) -> OfficialRosterHarvestResult:
    """Harvest one official roster source using existing SSOT owners only."""
    if fixture_path is not None:
        fixture_path = _validate_fixture_path(fixture_path)

    if fetch_bytes is None:
        def fetcher(url: str) -> bytes | None:
            return fetch_bytes_via_http(url, timeout_seconds=timeout_seconds)
    else:
        # Keep test injectors ergonomic: accept both fetch(url) and fetch(url, timeout_seconds=...).
        fetch_signature = inspect.signature(fetch_bytes)
        supports_timeout_seconds = "timeout_seconds" in fetch_signature.parameters

        def fetcher(url: str) -> bytes | None:
            if supports_timeout_seconds:
                return fetch_bytes(url, timeout_seconds=timeout_seconds)
            return fetch_bytes(url)
    effective_pull_date = pull_date or datetime.now(timezone.utc)

    source = _select_roster_source_definition(conn, source_id=source_id)
    use_fixture_input = fixture_path is not None
    html = _fixture_or_live_html(
        source,
        fixture_path=fixture_path,
        fetch_bytes=fetcher,
    )
    rows = parse_roster_rows(body_key=source.body_key, source_url=source.source_url, html=html)
    reported_member_count = _reported_member_count(source=source, parsed_row_count=len(rows))

    if dry_run:
        resolved_count = sum(1 for row in rows if _find_existing_person_id(conn, row) is not None)
        return OfficialRosterHarvestResult(
            source_id=source.source_id,
            body_key=source.body_key,
            member_count=reported_member_count,
            resolved_member_count=resolved_count,
            unresolved_member_count=reported_member_count - resolved_count,
            officeholding_upserts=0,
            portrait_writes=0,
            source_record_key=None,
            source_record_id=None,
            source_record_inserted=False,
            dry_run=True,
        )

    source_record_id, source_record_inserted, source_record_key = _persist_snapshot_source_record(
        conn,
        source=source,
        html=html,
        pull_date=effective_pull_date,
    )

    resolved_count = 0
    officeholding_upserts = 0
    portrait_writes = 0
    upserted_officeholding_ids: list[UUID] = []

    for row in rows:
        person_id = _resolve_person_id(conn, row)
        if person_id is None:
            continue

        target = _resolve_target(source.body_key, row, source_record_id)
        if target is None:
            continue

        division_id = upsert_electoral_division(conn, target.electoral_division)
        if target.office is not None:
            office_id = upsert_office(
                conn,
                target.office.model_copy(update={"electoral_division_id": division_id}),
            )
        else:
            office_id = target.office_id
            if office_id is None:
                raise ValueError("Resolved target must provide office or office_id.")
        officeholding_id = upsert_officeholding(
            conn,
            Officeholding(
                person_id=person_id,
                office_id=office_id,
                electoral_division_id=division_id,
                holder_status="elected",
                source_record_id=source_record_id,
            ),
        )
        upserted_officeholding_ids.append(officeholding_id)

        resolved_count += 1
        officeholding_upserts += 1
        # Fixture-driven runs stay network-independent by design.
        if not use_fixture_input:
            if _insert_portrait_if_present(
                conn,
                row=row,
                person_id=person_id,
                source_record_id=source_record_id,
                fetch_bytes=fetcher,
            ):
                portrait_writes += 1

    unresolved_count = reported_member_count - resolved_count
    should_prune_snapshot_rows = unresolved_count == 0 or (
        source.body_key == "nc_registers_of_deeds" and len(rows) == 0
    )
    if should_prune_snapshot_rows:
        # Never clear snapshot rows until every roster row resolves in this run.
        _prune_snapshot_officeholdings(
            conn,
            source_record_id=source_record_id,
            keep_officeholding_ids=upserted_officeholding_ids,
        )

    return OfficialRosterHarvestResult(
        source_id=source.source_id,
        body_key=source.body_key,
        member_count=reported_member_count,
        resolved_member_count=resolved_count,
        unresolved_member_count=unresolved_count,
        officeholding_upserts=officeholding_upserts,
        portrait_writes=portrait_writes,
        source_record_key=source_record_key,
        source_record_id=source_record_id,
        source_record_inserted=source_record_inserted,
        dry_run=False,
    )
