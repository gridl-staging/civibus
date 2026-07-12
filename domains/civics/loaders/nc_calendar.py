
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import psycopg
import yaml

from core.db import get_connection
from domains.civics.ingest import (
    upsert_contest,
    upsert_election,
    upsert_filing_deadline,
    upsert_office,
    upsert_reporting_period,
)
from domains.civics.types import Contest, Election, FilingDeadline, Office, ReportingPeriod

_NC_TIMEZONE = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class CalendarLoadSummary:
    """Counts and deterministic key mappings emitted by one loader run."""

    office_count: int
    election_count: int
    contest_count: int
    filing_deadline_count: int
    reporting_period_count: int
    unresolved_office_seed_count: int
    unresolved_election_seed_count: int
    unresolved_contest_seed_count: int
    unresolved_filing_deadline_seed_count: int
    office_ids_by_key: dict[str, str]
    election_ids_by_key: dict[str, str]
    parent_election_links: dict[str, str]


@dataclass(frozen=True)
class CandidateListingFilingWindow:
    """Inclusive filing window boundaries derived from NC civic calendar data."""

    start_date: date
    end_date: date


def _default_calendar_path(year: int) -> Path:
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "domains" / "civics" / "data" / f"nc_{year}_civic_calendar.yaml"


def _calendar_data_dir() -> Path:
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "domains" / "civics" / "data"


def available_nc_calendar_years() -> tuple[int, ...]:
    """Return the sorted tuple of NC civic-calendar years present on disk."""
    pattern = re.compile(r"^nc_(\d{4})_civic_calendar\.ya?ml$")
    years: list[int] = []
    for path in _calendar_data_dir().glob("nc_*_civic_calendar.yaml"):
        match = pattern.match(path.name)
        if match is not None:
            years.append(int(match.group(1)))
    return tuple(sorted(years))


def _default_calendar_year() -> int:
    years = available_nc_calendar_years()
    if not years:
        raise ValueError("No NC civic calendar files found under domains/civics/data")
    return years[-1]


def _load_calendar_payload(calendar_path: Path) -> dict[str, list[dict[str, object]]]:
    if not calendar_path.exists():
        raise FileNotFoundError(f"Calendar YAML file not found: {calendar_path}")

    try:
        payload = yaml.safe_load(calendar_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"Failed to parse calendar YAML: {exc}") from exc

    if not isinstance(payload, dict):
        raise ValueError("Calendar YAML must be a mapping")

    required_sections = ("offices", "elections", "contests", "filing_deadlines", "reporting_periods")
    missing_sections = [section for section in required_sections if section not in payload]
    if missing_sections:
        raise ValueError(f"Calendar YAML missing required sections: {', '.join(missing_sections)}")

    for section in required_sections:
        rows = payload.get(section)
        if not isinstance(rows, list):
            raise ValueError(f"Calendar section '{section}' must be a list")
        if not all(isinstance(row, dict) for row in rows):
            raise ValueError(f"Calendar section '{section}' must contain object rows")

    return payload


def _election_key_for_row(row: dict[str, object], election: Election) -> str:
    key = row.get("election_key")
    if isinstance(key, str) and key:
        return key
    return str(election.id)


def _office_key_for_row(row: dict[str, object], office: Office) -> str:
    key = row.get("office_key")
    if isinstance(key, str) and key:
        return key
    return str(office.id)


def _optional_seed_key(row: dict[str, object], field_name: str) -> str | None:
    value = row.get(field_name)
    if isinstance(value, str) and value:
        return value
    return None


def _optional_seed_id(row: dict[str, object], field_name: str = "id") -> str | None:
    value = row.get(field_name)
    if value is None:
        return None
    identifier = str(value).strip()
    if not identifier:
        return None
    return identifier


def _resolve_election_id(row: dict[str, object], *, election_ids_by_key: dict[str, str]) -> str:
    raw_election_id = row.get("election_id")
    if raw_election_id is not None:
        return str(raw_election_id)

    election_key = row.get("election_key")
    if isinstance(election_key, str) and election_key in election_ids_by_key:
        return election_ids_by_key[election_key]

    unresolved_key = election_key if isinstance(election_key, str) else "<missing>"
    raise ValueError(f"Unresolved election linkage: election_key={unresolved_key}")


def _resolve_office_id(row: dict[str, object], *, office_ids_by_key: dict[str, str]) -> str:
    raw_office_id = row.get("office_id")
    if raw_office_id is not None:
        return str(raw_office_id)

    office_key = row.get("office_key")
    if isinstance(office_key, str) and office_key in office_ids_by_key:
        return office_ids_by_key[office_key]

    unresolved_key = office_key if isinstance(office_key, str) else "<missing>"
    raise ValueError(f"Unresolved office linkage: office_key={unresolved_key}")


def _office_exists(conn: psycopg.Connection, office_id: str) -> bool:
    result = conn.execute("SELECT 1 FROM civic.office WHERE id = %s", (office_id,)).fetchone()
    return result is not None


def _slugify(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return normalized or "unknown"


def _division_key_for_row(row: dict[str, object]) -> str | None:
    explicit_key = row.get("electoral_division_key")
    if isinstance(explicit_key, str) and explicit_key:
        return explicit_key

    county = row.get("county")
    if isinstance(county, str) and county.strip():
        return f"nc_county_{_slugify(county)}"

    municipality = row.get("municipality")
    if isinstance(municipality, str) and municipality.strip():
        return f"nc_municipal_{_slugify(municipality)}"

    return None


def _resolve_division_id(conn: psycopg.Connection, row: dict[str, object]) -> str | None:
    division_key = _division_key_for_row(row)
    if division_key is None:
        return None

    result = conn.execute(
        """
        SELECT id::text
        FROM civic.electoral_division
        WHERE name = %s
        ORDER BY COALESCE(boundary_year, 0) DESC, id
        LIMIT 1
        """,
        (division_key,),
    ).fetchone()
    if result is None:
        return None
    return result[0]


def _normalize_deadline_date(row: dict[str, object]) -> date:
    raw_deadline_at = row.get("deadline_at")
    if raw_deadline_at is not None:
        raw_text = str(raw_deadline_at).strip()
        if raw_text.endswith("Z"):
            raw_text = f"{raw_text[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(raw_text)
        except ValueError as exc:
            raise ValueError(f"Invalid deadline_at timestamp: {raw_deadline_at}") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            parsed = parsed.replace(tzinfo=_NC_TIMEZONE)
        return parsed.astimezone(_NC_TIMEZONE).date()

    raw_deadline_date = row.get("deadline_date")
    if raw_deadline_date is not None:
        if isinstance(raw_deadline_date, date):
            return raw_deadline_date
        try:
            return date.fromisoformat(str(raw_deadline_date))
        except ValueError as exc:
            raise ValueError(f"Invalid deadline_date value: {raw_deadline_date}") from exc

    raise ValueError("Filing deadline row must include deadline_at or deadline_date")


# Filing-window pairs are keyed by the natural identity of a single filing period:
# the same election + office + electoral_division + jurisdiction scope. Pairing on
# this key prevents flattening two disjoint filing periods (e.g., primary vs. general,
# or two separate offices) into one continuous min(open)/max(close) span.
_FilingWindowPairKey = tuple[str, str, str, str, str, str, str]


def _filing_window_pair_key(row: dict[str, object]) -> _FilingWindowPairKey:
    """Return the natural identity used to pair a filing-open row with its filing-close row."""

    def _str_or_empty(value: object) -> str:
        return "" if value is None else str(value)

    return (
        _str_or_empty(row.get("election_id")),
        _str_or_empty(row.get("office_id")),
        _str_or_empty(row.get("electoral_division_id")),
        _str_or_empty(row.get("jurisdiction_scope")),
        _str_or_empty(row.get("state")),
        _str_or_empty(row.get("county")),
        _str_or_empty(row.get("municipality")),
    )


def _scan_candidate_filing_rows(
    filing_deadline_rows: list[dict[str, object]],
    calendar_path: Path,
) -> tuple[dict[_FilingWindowPairKey, date], dict[_FilingWindowPairKey, date]]:
    """Collect candidate_filing_open and candidate_filing rows keyed by natural identity."""
    open_rows: dict[_FilingWindowPairKey, date] = {}
    close_rows: dict[_FilingWindowPairKey, date] = {}
    for row in filing_deadline_rows:
        deadline_kind = row.get("deadline_kind")
        if deadline_kind not in ("candidate_filing_open", "candidate_filing"):
            continue
        normalized_date = _normalize_deadline_date(dict(row))
        pair_key = _filing_window_pair_key(row)
        target = open_rows if deadline_kind == "candidate_filing_open" else close_rows
        if pair_key in target:
            raise ValueError(
                "NC civic calendar has duplicate "
                f"{deadline_kind} rows for the same filing-period key: "
                f"key={pair_key} file={calendar_path}"
            )
        target[pair_key] = normalized_date
    return open_rows, close_rows


def resolve_candidate_listing_filing_windows(
    *,
    year: int | None = None,
    calendar_path: Path | None = None,
) -> tuple[CandidateListingFilingWindow, ...]:
    """Resolve all NC candidate-listing filing windows from civic-calendar data.

    Each window pairs a ``candidate_filing_open`` row with its matching
    ``candidate_filing`` (close) row using the filing-deadline natural key
    (election + office + electoral_division + jurisdiction). Returning the full
    set of windows — rather than collapsing min(open)/max(close) — keeps cadence
    correct when a calendar contains multiple disjoint filing periods.
    """
    if calendar_path is not None:
        resolved_calendar_path = calendar_path
    else:
        resolved_year = _default_calendar_year() if year is None else year
        resolved_calendar_path = _default_calendar_path(resolved_year)

    payload = _load_calendar_payload(resolved_calendar_path)
    open_rows, close_rows = _scan_candidate_filing_rows(payload["filing_deadlines"], resolved_calendar_path)

    paired_keys = open_rows.keys() & close_rows.keys()
    unmatched_open = open_rows.keys() - paired_keys
    unmatched_close = close_rows.keys() - paired_keys
    if unmatched_open or unmatched_close:
        raise ValueError(
            "NC civic calendar has unmatched candidate filing window rows: "
            f"unmatched_open={sorted(unmatched_open)} "
            f"unmatched_close={sorted(unmatched_close)} "
            f"file={resolved_calendar_path}"
        )
    if not paired_keys:
        raise ValueError(
            "NC civic calendar must include at least one matched "
            "candidate_filing_open / candidate_filing pair "
            f"for filing-window cadence resolution: {resolved_calendar_path}"
        )

    windows: list[CandidateListingFilingWindow] = []
    for key in paired_keys:
        start_date = open_rows[key]
        end_date = close_rows[key]
        if start_date > end_date:
            raise ValueError(
                "NC civic calendar candidate filing window has start after end: "
                f"start={start_date} end={end_date} key={key} file={resolved_calendar_path}"
            )
        windows.append(CandidateListingFilingWindow(start_date=start_date, end_date=end_date))

    windows.sort(key=lambda window: window.start_date)
    return tuple(windows)


def resolve_candidate_listing_refresh_cadence(
    *,
    year: int | None = None,
    on_date: date | None = None,
    calendar_path: Path | None = None,
) -> str:
    """Return daily during any filing window; quarterly outside all filing windows."""
    filing_windows = resolve_candidate_listing_filing_windows(year=year, calendar_path=calendar_path)
    effective_date = date.today() if on_date is None else on_date
    for window in filing_windows:
        if window.start_date <= effective_date <= window.end_date:
            return "daily"
    return "quarterly"


def load_nc_civic_calendar(
    conn: psycopg.Connection,
    *,
    year: int,
    calendar_path: Path | None = None,
) -> CalendarLoadSummary:
    """Load NC civic calendar rows from YAML into civic tables via canonical upsert owners."""
    resolved_calendar_path = calendar_path or _default_calendar_path(year)
    payload = _load_calendar_payload(resolved_calendar_path)

    office_rows = payload["offices"]
    election_rows = payload["elections"]
    contest_rows = payload["contests"]
    filing_rows = payload["filing_deadlines"]
    reporting_rows = payload["reporting_periods"]

    office_ids_by_key: dict[str, str] = {}
    election_ids_by_key: dict[str, str] = {}
    parent_election_links: dict[str, str] = {}
    skipped_election_keys: set[str] = set()
    skipped_election_ids: set[str] = set()
    unresolved_office_seed_count = 0
    unresolved_election_seed_count = 0
    unresolved_contest_seed_count = 0
    unresolved_filing_deadline_seed_count = 0

    for row in office_rows:
        row_payload = dict(row)
        row_payload.pop("office_key", None)
        division_id = _resolve_division_id(conn, row_payload)
        if _division_key_for_row(row_payload) is not None and division_id is None:
            unresolved_office_seed_count += 1
            continue

        row_payload["electoral_division_id"] = division_id
        row_payload.pop("electoral_division_key", None)
        office_model = Office.model_validate(row_payload)
        office_id = str(upsert_office(conn, office_model))

        office_key = _office_key_for_row(row, office_model)
        office_ids_by_key[office_key] = office_id
        office_ids_by_key[str(office_model.id)] = office_id

    for row in election_rows:
        election_key_for_seed = _optional_seed_key(row, "election_key")
        parent_key_for_seed = _optional_seed_key(row, "parent_election_key")
        if parent_key_for_seed is not None and parent_key_for_seed in skipped_election_keys:
            unresolved_election_seed_count += 1
            if election_key_for_seed is not None:
                skipped_election_keys.add(election_key_for_seed)
            election_id_for_seed = _optional_seed_id(row)
            if election_id_for_seed is not None:
                skipped_election_ids.add(election_id_for_seed)
            continue

        row_payload = dict(row)
        row_payload.pop("election_key", None)
        row_payload.pop("parent_election_key", None)
        if row_payload.get("office_id") is None:
            row_payload["office_id"] = _resolve_office_id(row_payload, office_ids_by_key=office_ids_by_key)
        division_id = _resolve_division_id(conn, row_payload)
        if _division_key_for_row(row_payload) is not None and division_id is None:
            unresolved_election_seed_count += 1
            election_id_for_seed = _optional_seed_id(row_payload)
            if election_id_for_seed is not None:
                skipped_election_ids.add(election_id_for_seed)
            if election_key_for_seed is not None:
                skipped_election_keys.add(election_key_for_seed)
            continue

        row_payload["electoral_division_id"] = division_id
        row_payload.pop("electoral_division_key", None)

        election_model = Election.model_validate(row_payload)
        election_id = str(upsert_election(conn, election_model))
        election_key = _election_key_for_row(row, election_model)
        election_ids_by_key[election_key] = election_id
        election_ids_by_key[str(election_model.id)] = election_id

    for row in election_rows:
        parent_key = row.get("parent_election_key")
        if not isinstance(parent_key, str) or not parent_key:
            continue
        child_key = row.get("election_key")
        if not isinstance(child_key, str) or not child_key:
            raise ValueError("Unresolved election linkage: runoff row missing election_key")
        if child_key in skipped_election_keys:
            continue
        parent_id = election_ids_by_key.get(parent_key)
        if parent_id is None:
            if parent_key in skipped_election_keys:
                unresolved_election_seed_count += 1
                skipped_election_keys.add(child_key)
                child_id_for_seed = _optional_seed_id(row)
                if child_id_for_seed is not None:
                    skipped_election_ids.add(child_id_for_seed)
                continue
            raise ValueError(f"Unresolved election linkage: parent_election_key={parent_key}")
        parent_election_links[child_key] = parent_id

    for row in contest_rows:
        row_payload = dict(row)
        row_payload["office_id"] = _resolve_office_id(row_payload, office_ids_by_key=office_ids_by_key)
        if not _office_exists(conn, row_payload["office_id"]):
            unresolved_contest_seed_count += 1
            continue
        raw_election_id = row_payload.get("election_id")
        if raw_election_id is not None and str(raw_election_id) in skipped_election_ids:
            unresolved_contest_seed_count += 1
            continue
        if row_payload.get("election_id") is None:
            election_key = _optional_seed_key(row_payload, "election_key")
            if election_key is not None and election_key in skipped_election_keys:
                unresolved_contest_seed_count += 1
                continue
        row_payload["election_id"] = _resolve_election_id(row_payload, election_ids_by_key=election_ids_by_key)
        division_id = _resolve_division_id(conn, row_payload)
        if _division_key_for_row(row_payload) is not None and division_id is None:
            unresolved_contest_seed_count += 1
            continue

        row_payload["electoral_division_id"] = division_id
        row_payload.pop("election_key", None)
        row_payload.pop("office_key", None)
        row_payload.pop("electoral_division_key", None)
        contest_model = Contest.model_validate(row_payload)
        upsert_contest(conn, contest_model)

    for row in filing_rows:
        row_payload = dict(row)
        raw_election_id = row_payload.get("election_id")
        if raw_election_id is not None and str(raw_election_id) in skipped_election_ids:
            unresolved_filing_deadline_seed_count += 1
            continue
        if row_payload.get("election_id") is None:
            election_key = _optional_seed_key(row_payload, "election_key")
            if election_key is not None and election_key in skipped_election_keys:
                unresolved_filing_deadline_seed_count += 1
                continue
        row_payload["election_id"] = _resolve_election_id(row_payload, election_ids_by_key=election_ids_by_key)
        row_payload["office_id"] = _resolve_office_id(row_payload, office_ids_by_key=office_ids_by_key)
        if not _office_exists(conn, row_payload["office_id"]):
            raise ValueError(f"Unresolved office linkage: office_id={row_payload['office_id']}")
        division_id = _resolve_division_id(conn, row_payload)
        if _division_key_for_row(row_payload) is not None and division_id is None:
            unresolved_filing_deadline_seed_count += 1
            continue

        row_payload["electoral_division_id"] = division_id
        row_payload["deadline_date"] = _normalize_deadline_date(row_payload)
        row_payload.pop("deadline_at", None)
        row_payload.pop("election_key", None)
        row_payload.pop("office_key", None)
        row_payload.pop("electoral_division_key", None)
        filing_deadline = FilingDeadline.model_validate(row_payload)
        upsert_filing_deadline(conn, filing_deadline)

    for row in reporting_rows:
        row_payload = dict(row)
        raw_election_id = row_payload.get("election_id")
        if raw_election_id is not None and str(raw_election_id) in skipped_election_ids:
            # Reporting periods linked to skipped elections are unresolved
            # election seed work and should not abort the full run.
            unresolved_election_seed_count += 1
            continue
        if row_payload.get("election_id") is None:
            election_key = _optional_seed_key(row_payload, "election_key")
            if election_key is not None and election_key in skipped_election_keys:
                # Reporting periods linked to skipped elections are unresolved
                # election seed work and should not abort the full run.
                unresolved_election_seed_count += 1
                continue
        row_payload["election_id"] = _resolve_election_id(row_payload, election_ids_by_key=election_ids_by_key)
        row_payload.pop("election_key", None)
        reporting_period = ReportingPeriod.model_validate(row_payload)
        upsert_reporting_period(conn, reporting_period)

    return CalendarLoadSummary(
        office_count=len(office_rows),
        election_count=len(election_rows),
        contest_count=len(contest_rows),
        filing_deadline_count=len(filing_rows),
        reporting_period_count=len(reporting_rows),
        unresolved_office_seed_count=unresolved_office_seed_count,
        unresolved_election_seed_count=unresolved_election_seed_count,
        unresolved_contest_seed_count=unresolved_contest_seed_count,
        unresolved_filing_deadline_seed_count=unresolved_filing_deadline_seed_count,
        office_ids_by_key=office_ids_by_key,
        election_ids_by_key=election_ids_by_key,
        parent_election_links=parent_election_links,
    )


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bootstrap NC civic calendar rows into civic tables")
    parser.add_argument("--year", type=int, required=True, help="Calendar year to load (e.g., 2026)")
    parser.add_argument(
        "--calendar-path",
        type=Path,
        help="Optional override path to a civic calendar YAML file",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_argument_parser().parse_args(argv)
    conn: psycopg.Connection | None = None
    try:
        if args.calendar_path is None:
            calendar_path = _default_calendar_path(args.year)
        else:
            calendar_path = args.calendar_path

        # Parse and validate local file content before opening a DB connection so
        # file-shape failures do not depend on database availability.
        _load_calendar_payload(calendar_path)

        conn = get_connection()
        with conn.transaction():
            summary = load_nc_civic_calendar(conn, year=args.year, calendar_path=calendar_path)
        conn.commit()
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"NC civic calendar bootstrap failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if conn is not None:
            conn.close()

    print(
        "NC civic calendar bootstrap complete: "
        f"offices={summary.office_count} "
        f"elections={summary.election_count} "
        f"contests={summary.contest_count} "
        f"filing_deadlines={summary.filing_deadline_count} "
        f"reporting_periods={summary.reporting_period_count} "
        f"unresolved_office_rows={summary.unresolved_office_seed_count} "
        f"unresolved_election_rows={summary.unresolved_election_seed_count} "
        f"unresolved_contest_rows={summary.unresolved_contest_seed_count} "
        f"unresolved_filing_deadline_rows={summary.unresolved_filing_deadline_seed_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
