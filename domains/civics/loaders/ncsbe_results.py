
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import psycopg
import yaml

from core.db import (
    get_connection,
    select_active_source_record_by_key,
    try_insert_data_source,
    try_insert_source_record,
)
from core.types.python.models import DataSource, SourceRecord, compute_record_hash
from domains.civics.loaders.ncsbe_results_parser import parse_ncsbe_results


@dataclass(frozen=True)
class NcsbeSourceMetadata:
    source_id: str
    election_date: str
    election_label: str
    fixture_file: str
    source_url: str


@dataclass(frozen=True)
class NcsbeResultsLoadSummary:
    source_record_count: int
    result_row_count: int
    contest_count: int
    source_record_ids_by_file: dict[str, UUID]


_NCSBE_REFRESH_ALLOWED_YEARS = frozenset({"2022", "2024"})
_NCSBE_RAW_EXTRACTS_DIR = (
    Path(__file__).resolve().parents[3]
    / "docs"
    / "research"
    / "artifacts"
    / "2026_04_30_dwo_past_results"
    / "ncsbe"
    / "raw_extracts"
)
_NCSBE_DATA_SOURCE_DOMAIN = "civics"
_NCSBE_DATA_SOURCE_JURISDICTION = "us/nc"
_NCSBE_DATA_SOURCE_UPDATE_FREQUENCY = "weekly"


@dataclass(frozen=True)
class _ResultRow:
    contest_id: UUID
    source_record_id: UUID
    candidate_name: str
    party: str
    votes: int
    vote_pct: float
    is_certified: bool
    is_winner: bool


def build_contest_match_key(
    *,
    election_date: str,
    election_label: str,
    jurisdiction_name: str,
    contest_name: str,
    contest_external_id: str,
) -> str:
    """Build deterministic mapping key for parser rows -> canonical civic contest IDs."""
    return "|".join(
        [
            election_date.strip(),
            election_label.strip().lower(),
            jurisdiction_name.strip().lower(),
            contest_name.strip().lower(),
            contest_external_id.strip(),
        ]
    )


def _default_metadata_path() -> Path:
    return Path(__file__).resolve().with_name("ncsbe_results_sources.yaml")


def _load_metadata(path: Path) -> list[NcsbeSourceMetadata]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    sources_payload = payload.get("sources")
    if not isinstance(sources_payload, list):
        raise ValueError("ncsbe_results_sources.yaml requires a top-level 'sources' list")

    sources: list[NcsbeSourceMetadata] = []
    for source_row in sources_payload:
        sources.append(
            NcsbeSourceMetadata(
                source_id=str(source_row["source_id"]).strip(),
                election_date=str(source_row["election_date"]).strip(),
                election_label=str(source_row["election_label"]).strip(),
                fixture_file=str(source_row["fixture_file"]).strip(),
                source_url=str(source_row["source_url"]).strip(),
            )
        )

    return sources


def _normalize_election_type(election_label: str) -> str:
    normalized = election_label.strip().lower()
    election_type_mapping = {
        "general": "general",
        "primary": "primary",
        "runoff": "runoff",
        "special": "special",
        "recall": "recall",
    }
    for prefix, canonical_type in election_type_mapping.items():
        if normalized.startswith(prefix):
            return canonical_type
    raise ValueError(f"Unsupported election label for contest resolution: {election_label}")


def _find_contest_ids_by_match(
    conn: psycopg.Connection,
    *,
    contest_name: str,
    election_date: str,
    election_type: str,
    jurisdiction_name: str,
) -> list[UUID]:
    normalized_jurisdiction = jurisdiction_name.strip().lower()
    query = """
        SELECT DISTINCT c.id
        FROM civic.contest AS c
        LEFT JOIN civic.election AS e ON e.id = c.election_id
        LEFT JOIN civic.electoral_division AS d ON d.id = c.electoral_division_id
        WHERE lower(c.name) = lower(%s)
          AND c.election_date = %s::date
          AND c.election_type = %s
          AND (
            %s = ''
            OR lower(d.name) = %s
            OR lower(e.county) = %s
            OR lower(e.municipality) = %s
            OR lower(e.state) = %s
          )
    """
    params = (
        contest_name,
        election_date,
        election_type,
        normalized_jurisdiction,
        normalized_jurisdiction,
        normalized_jurisdiction,
        normalized_jurisdiction,
        normalized_jurisdiction,
    )
    with conn.cursor() as cursor:
        cursor.execute(query, params)
        rows = cursor.fetchall()
    return [row[0] for row in rows]


def _resolve_contest_id(conn: psycopg.Connection, row: dict[str, object]) -> UUID:
    contest_name = str(row["contest_name"])
    election_date = str(row["election_date"])
    election_label = str(row["election_label"])
    jurisdiction_name = str(row["jurisdiction_name"])
    contest_external_id = str(row["contest_external_id"])
    election_type = _normalize_election_type(election_label)

    contest_match_key = build_contest_match_key(
        election_date=election_date,
        election_label=election_label,
        jurisdiction_name=jurisdiction_name,
        contest_name=contest_name,
        contest_external_id=contest_external_id,
    )

    contest_ids = _find_contest_ids_by_match(
        conn,
        contest_name=contest_name,
        election_date=election_date,
        election_type=election_type,
        jurisdiction_name=jurisdiction_name,
    )
    if not contest_ids and jurisdiction_name.strip():
        contest_ids = _find_contest_ids_by_match(
            conn,
            contest_name=contest_name,
            election_date=election_date,
            election_type=election_type,
            jurisdiction_name="",
        )

    if not contest_ids:
        raise ValueError(f"Unresolved contest mapping for key={contest_match_key}")
    if len(contest_ids) > 1:
        raise ValueError(
            f"Ambiguous contest mapping for key={contest_match_key}, contest_ids={sorted(contest_ids)}"
        )
    return contest_ids[0]


def _read_raw_rows_by_file(raw_csv_paths: list[Path]) -> dict[str, list[dict[str, str]]]:
    rows_by_file: dict[str, list[dict[str, str]]] = {}
    for csv_path in raw_csv_paths:
        with csv_path.open("r", encoding="utf-8", newline="") as handle:
            rows_by_file[csv_path.name] = list(csv.DictReader(handle))
    return rows_by_file


def _refresh_sources_2022_2024() -> list[NcsbeSourceMetadata]:
    sources = _load_metadata(_default_metadata_path())
    return [source for source in sources if source.election_date[:4] in _NCSBE_REFRESH_ALLOWED_YEARS]


def collect_ncsbe_refresh_data_source_names() -> tuple[str, ...]:
    """Return canonical data-source names for runnable 2022/2024 ENRS refresh inputs."""
    return tuple(f"NCSBE ENRS {source.source_id}" for source in _refresh_sources_2022_2024())


def collect_ncsbe_refresh_raw_csv_paths() -> list[Path]:
    """Resolve runnable ENRS fixture paths for refresh-runner execution.

    Stage 3 contract: refresh-runner ingestion is limited to the 2022/2024 files.
    The 2020 file remains metadata/registry coverage only.
    """
    sources = _refresh_sources_2022_2024()
    canonical_raw_extracts_dir = _NCSBE_RAW_EXTRACTS_DIR.resolve()
    selected_paths: list[Path] = []
    for source in sources:
        resolved_path = (_NCSBE_RAW_EXTRACTS_DIR / source.fixture_file).resolve()
        if resolved_path.parent != canonical_raw_extracts_dir:
            raise ValueError(
                "NCSBE fixture_file must stay within the canonical raw-extract directory: "
                f"{source.fixture_file}"
            )
        selected_paths.append(resolved_path)
    return selected_paths


def _select_matching_data_sources(
    conn: psycopg.Connection, *, source_id: str
) -> list[tuple[UUID, str, str]]:
    """Return civics data_source rows tagged with the given registry source id."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, jurisdiction, name, notes
            FROM core.data_source
            WHERE domain = 'civics'
            """
        )
        rows = cursor.fetchall()

    matching_rows: list[tuple[UUID, str, str]] = []
    for data_source_id, jurisdiction, name, notes in rows:
        if notes is None:
            continue
        try:
            payload = json.loads(notes)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and payload.get("registry_source_id") == source_id:
            matching_rows.append((data_source_id, jurisdiction, name))

    return matching_rows


def _select_data_source_id(conn: psycopg.Connection, *, source_id: str) -> UUID:
    """Select the canonical ENRS data-source identity for a registry source id."""
    matching_rows = _select_matching_data_sources(conn, source_id=source_id)
    canonical_name = f"NCSBE ENRS {source_id}"
    canonical_rows = [
        data_source_id
        for data_source_id, jurisdiction, name in matching_rows
        if jurisdiction == _NCSBE_DATA_SOURCE_JURISDICTION and name == canonical_name
    ]

    if len(canonical_rows) == 0:
        raise ValueError(f"No core.data_source row found for source_id={source_id}")
    if len(canonical_rows) > 1:
        raise ValueError(f"Multiple core.data_source rows found for source_id={source_id}")
    return canonical_rows[0]


def _source_record_key(source: NcsbeSourceMetadata) -> str:
    return f"ncsbe_results:{source.source_id}:{source.election_date}"


def _build_data_source(source: NcsbeSourceMetadata) -> DataSource:
    return DataSource(
        domain=_NCSBE_DATA_SOURCE_DOMAIN,
        jurisdiction=_NCSBE_DATA_SOURCE_JURISDICTION,
        name=f"NCSBE ENRS {source.source_id}",
        source_url=source.source_url,
        source_format="csv",
        license="public_domain",
        update_frequency=_NCSBE_DATA_SOURCE_UPDATE_FREQUENCY,
        notes=json.dumps({"registry_source_id": source.source_id}),
    )


def _ensure_data_source_id(conn: psycopg.Connection, *, source: NcsbeSourceMetadata) -> UUID:
    try:
        return _select_data_source_id(conn, source_id=source.source_id)
    except ValueError as error:
        if not str(error).startswith("No core.data_source row found for source_id="):
            raise

    inserted_id = try_insert_data_source(conn, _build_data_source(source))
    if inserted_id is not None:
        return inserted_id

    try:
        return _select_data_source_id(conn, source_id=source.source_id)
    except ValueError as error:
        raise RuntimeError(
            "NCSBE ENRS data source upsert reported conflict but registry_source_id lookup still failed "
            f"for source_id={source.source_id}"
        ) from error


def _persist_source_record(
    conn: psycopg.Connection,
    *,
    source: NcsbeSourceMetadata,
    data_source_id: UUID,
    source_rows: list[dict[str, str]],
    pull_date: datetime,
) -> UUID:
    source_record_key = _source_record_key(source)
    raw_fields = {
        "registry_source_id": source.source_id,
        "election_date": source.election_date,
        "election_label": source.election_label,
        "fixture_file": source.fixture_file,
        "source_url": source.source_url,
        "row_count": len(source_rows),
        "rows_sha256": hashlib.sha256(
            json.dumps(source_rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
    }
    source_record = SourceRecord(
        data_source_id=data_source_id,
        source_record_key=source_record_key,
        source_url=source.source_url,
        raw_fields=raw_fields,
        pull_date=pull_date,
        record_hash=compute_record_hash(raw_fields),
    )
    inserted_id = try_insert_source_record(conn, source_record)
    if inserted_id is not None:
        return inserted_id

    active = select_active_source_record_by_key(
        conn,
        data_source_id=data_source_id,
        source_record_key=source_record_key,
    )
    if active is None:
        raise RuntimeError(f"Unable to load active source_record for key={source_record_key}")
    return active.id


def _derive_winner_flags(parsed_rows: list[dict[str, object]], seat_count_by_contest: dict[UUID, int]) -> dict[int, bool]:
    by_contest: dict[UUID, list[tuple[int, int, str]]] = {}
    for idx, row in enumerate(parsed_rows):
        contest_id = row["contest_id"]
        candidate_name = str(row["candidate_name"])
        votes = int(row["votes"])
        by_contest.setdefault(contest_id, []).append((idx, votes, candidate_name))

    winner_flags: dict[int, bool] = {}
    for contest_id, ranked_rows in by_contest.items():
        seats = seat_count_by_contest[contest_id]
        ranked = sorted(ranked_rows, key=lambda value: (-value[1], value[2]))
        winner_indexes = {row_index for row_index, _, _ in ranked[:seats]}
        for row_index, _, _ in ranked:
            winner_flags[row_index] = row_index in winner_indexes

    return winner_flags


def _load_contest_seat_counts(conn: psycopg.Connection, contest_ids: list[UUID]) -> dict[UUID, int]:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, number_of_seats
            FROM civic.contest
            WHERE id = ANY(%s)
            """,
            (contest_ids,),
        )
        rows = cursor.fetchall()
    return {row[0]: int(row[1]) for row in rows}


def _insert_or_update_contest_result(conn: psycopg.Connection, row: _ResultRow) -> None:
    conn.execute(
        """
        INSERT INTO civic.contest_result (
            contest_id,
            source_record_id,
            candidate_name,
            party,
            votes,
            vote_pct,
            is_certified,
            is_winner
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT ON CONSTRAINT uq_contest_result_canonical
        DO UPDATE SET
            party = EXCLUDED.party,
            votes = EXCLUDED.votes,
            vote_pct = EXCLUDED.vote_pct,
            is_certified = EXCLUDED.is_certified,
            is_winner = EXCLUDED.is_winner,
            updated_at = NOW()
        """,
        (
            row.contest_id,
            row.source_record_id,
            row.candidate_name,
            row.party,
            row.votes,
            row.vote_pct,
            row.is_certified,
            row.is_winner,
        ),
    )


def load_ncsbe_results(
    conn: psycopg.Connection,
    *,
    metadata_path: Path | None = None,
    raw_rows_by_file: dict[str, list[dict[str, str]]],
    pull_date: datetime | None = None,
) -> NcsbeResultsLoadSummary:
    """Load NCSBE ENRS contest results into civic.contest_result."""
    effective_pull_date = pull_date or datetime.now(timezone.utc)
    effective_path = metadata_path or _default_metadata_path()
    source_metadata = _load_metadata(effective_path)
    source_by_file = {source.fixture_file: source for source in source_metadata}
    unknown_fixture_files = sorted(set(raw_rows_by_file) - set(source_by_file))
    if unknown_fixture_files:
        raise ValueError(f"Unknown fixture files not present in metadata: {unknown_fixture_files}")

    parsed_rows = parse_ncsbe_results(raw_rows_by_file)
    source_record_ids_by_file: dict[str, UUID] = {}
    for fixture_file, source_rows in raw_rows_by_file.items():
        source = source_by_file[fixture_file]
        data_source_id = _ensure_data_source_id(conn, source=source)
        source_record_ids_by_file[fixture_file] = _persist_source_record(
            conn,
            source=source,
            data_source_id=data_source_id,
            source_rows=source_rows,
            pull_date=effective_pull_date,
        )

    resolved_rows: list[dict[str, object]] = []
    for row in parsed_rows:
        fixture_file = str(row["fixture_file"])
        source_record_id = source_record_ids_by_file[fixture_file]
        contest_id = _resolve_contest_id(conn, row)

        resolved = dict(row)
        resolved["contest_id"] = contest_id
        resolved["source_record_id"] = source_record_id
        resolved_rows.append(resolved)

    contest_ids = [row["contest_id"] for row in resolved_rows]
    seat_counts = _load_contest_seat_counts(conn, contest_ids)
    missing_contests = sorted({contest_id for contest_id in contest_ids if contest_id not in seat_counts})
    if missing_contests:
        raise ValueError(f"Contest IDs missing from civic.contest: {missing_contests}")

    winner_flags = _derive_winner_flags(resolved_rows, seat_counts)

    for index, row in enumerate(resolved_rows):
        _insert_or_update_contest_result(
            conn,
            _ResultRow(
                contest_id=row["contest_id"],
                source_record_id=row["source_record_id"],
                candidate_name=str(row["candidate_name"]),
                party=str(row["party"]),
                votes=int(row["votes"]),
                vote_pct=float(row["vote_pct"]),
                is_certified=bool(row["is_certified"]),
                is_winner=winner_flags[index],
            ),
        )

    return NcsbeResultsLoadSummary(
        source_record_count=len(source_record_ids_by_file),
        result_row_count=len(resolved_rows),
        contest_count=len({row["contest_id"] for row in resolved_rows}),
        source_record_ids_by_file=source_record_ids_by_file,
    )


def run_ncsbe_results_refresh_2022_2024() -> NcsbeResultsLoadSummary:
    """Execute the shared refresh-runner ingest surface for NC past results."""
    raw_csv_paths = collect_ncsbe_refresh_raw_csv_paths()
    raw_rows_by_file = _read_raw_rows_by_file(raw_csv_paths)
    if not raw_rows_by_file:
        raise ValueError("No runnable NC NCSBE raw CSV inputs found for 2022-2024 refresh scope")

    conn = get_connection()
    try:
        summary = load_ncsbe_results(
            conn,
            metadata_path=_default_metadata_path(),
            raw_rows_by_file=raw_rows_by_file,
        )
        conn.commit()
        return summary
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load NC NCSBE ENRS contest results")
    parser.add_argument("--metadata-path", default=str(_default_metadata_path()))
    parser.add_argument(
        "--raw-csv",
        action="append",
        default=[],
        help="Path to ENRS CSV input. Repeat for multiple files.",
    )
    args = parser.parse_args(argv)

    raw_csv_paths = [Path(raw_csv_path) for raw_csv_path in args.raw_csv]
    raw_rows_by_file = _read_raw_rows_by_file(raw_csv_paths)
    if not raw_rows_by_file:
        print("No input rows provided. Pass at least one --raw-csv path.", file=sys.stderr)
        return 1

    conn = get_connection()
    try:
        load_ncsbe_results(
            conn,
            metadata_path=Path(args.metadata_path),
            raw_rows_by_file=raw_rows_by_file,
        )
        conn.commit()
    except Exception as exc:
        conn.rollback()
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
