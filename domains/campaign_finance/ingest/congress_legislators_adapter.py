"""
Stub summary for jun04_3pm_3_member_photo_bio_enrichment/civibus_dev/domains/campaign_finance/ingest/congress_legislators_adapter.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any
from uuid import UUID

import httpx
import yaml

from domains.campaign_finance.ingest.federal_officeholder_loader import (
    OFFICE_US_HOUSE_DELEGATE,
)

_CONGRESS_LEGISLATORS_RAW_BASE_URL = "https://raw.githubusercontent.com/unitedstates/congress-legislators/main"
LEGISLATORS_CURRENT_YAML_URL = f"{_CONGRESS_LEGISLATORS_RAW_BASE_URL}/legislators-current.yaml"
LEGISLATORS_HISTORICAL_YAML_URL = f"{_CONGRESS_LEGISLATORS_RAW_BASE_URL}/legislators-historical.yaml"
EXECUTIVE_YAML_URL = f"{_CONGRESS_LEGISLATORS_RAW_BASE_URL}/executive.yaml"

# US territory codes whose House seats are non-voting delegate seats.
# These appear in legislators-current.yaml as type=rep entries and must be
# routed to the delegate bucket, not the House bucket.
_TERRITORY_STATES: frozenset[str] = frozenset({"DC", "GU", "AS", "MP", "VI", "PR"})

_PASSTHROUGH_HOUSE_EMPTY_KEYS = (
    "elected_date",
    "office_building",
    "office_room",
    "office_zip",
)


@dataclass
class AdaptedLegislators:
    """Bucketed row dicts produced by adapt_legislators_yaml.

    house_rows / senate_rows match the row-dict contract consumed by
    load_federal_house_officeholders / load_federal_senate_officeholders.
    delegate_rows, president_rows, vp_rows are consumed by Stage 3 spine ingest.
    """

    house_rows: list[dict[str, Any]] = field(default_factory=list)
    senate_rows: list[dict[str, Any]] = field(default_factory=list)
    delegate_rows: list[dict[str, Any]] = field(default_factory=list)
    president_rows: list[dict[str, Any]] = field(default_factory=list)
    vp_rows: list[dict[str, Any]] = field(default_factory=list)


def fetch_legislators_entries() -> list[dict[str, Any]]:
    """Fetch and parse the current legislative + executive YAML entries."""
    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        legislators_payload = _fetch_yaml_payload(
            client,
            LEGISLATORS_CURRENT_YAML_URL,
        )
        executive_payload = _fetch_yaml_payload(client, EXECUTIVE_YAML_URL)

    return _parse_yaml_entries(
        legislators_payload,
        LEGISLATORS_CURRENT_YAML_URL,
    ) + _parse_yaml_entries(executive_payload, EXECUTIVE_YAML_URL)


def adapt_legislators_yaml(entries: list[dict[str, Any]]) -> AdaptedLegislators:
    """Transform parsed congress-legislators YAML entries into bucketed row dicts."""
    result = AdaptedLegislators()
    for entry in entries:
        term = _current_term(entry)
        if term is None:
            continue
        term_type = term.get("type")
        if term_type == "rep":
            if _is_territory_delegate(term):
                result.delegate_rows.append(_build_delegate_row(entry, term))
            else:
                result.house_rows.append(_build_house_row(entry, term))
        elif term_type == "sen":
            result.senate_rows.append(_build_senate_row(entry, term))
        elif term_type == "prez":
            result.president_rows.append(_build_executive_row(entry, term, "president"))
        elif term_type == "viceprez":
            result.vp_rows.append(_build_executive_row(entry, term, "vice_president"))
    return result


def _fetch_yaml_payload(client: httpx.Client, url: str) -> str:
    response = client.get(url)
    response.raise_for_status()
    return response.text


def _parse_yaml_entries(payload: str, source_url: str) -> list[dict[str, Any]]:
    parsed = yaml.safe_load(payload)
    if parsed is None:
        return []
    if not isinstance(parsed, list):
        raise ValueError(f"Expected YAML list from {source_url}")
    if not all(isinstance(entry, dict) for entry in parsed):
        raise ValueError(f"Expected only mapping entries from {source_url}")
    return parsed


def _current_term(entry: dict[str, Any]) -> dict[str, Any] | None:
    """Return the last term if it has not ended (or end is in the future), else None.

    legislators-current.yaml + executive.yaml are intended to hold only currently
    serving officials, but the adapter still defensively filters expired entries
    so test fixtures and any stale upstream rows can't leak into Stage 3 buckets.
    """
    terms = entry.get("terms") or []
    if not terms:
        return None
    term = terms[-1]
    end_value = term.get("end")
    if end_value is None or end_value == "":
        return term
    end_date = _parse_iso_date(end_value)
    if end_date is None:
        # Unparseable end value — fall back to treating as current rather than
        # silently dropping an active legislator.
        return term
    if end_date < date.today():
        return None
    return term


def _parse_iso_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _is_territory_delegate(term: dict[str, Any]) -> bool:
    return term.get("type") == "rep" and term.get("state") in _TERRITORY_STATES


def _extract_fec_ids(entry: dict[str, Any]) -> list[str]:
    """Pull FEC IDs from entry.id.fec, normalizing list / scalar / None inputs."""
    raw = (entry.get("id") or {}).get("fec")
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw]
    return [str(value) for value in raw]


def _bioguide_id(entry: dict[str, Any]) -> str:
    return (entry.get("id") or {}).get("bioguide") or ""


def _govtrack_id(entry: dict[str, Any]) -> str:
    raw = (entry.get("id") or {}).get("govtrack")
    return "" if raw is None else str(raw)


def _wikidata_id(entry: dict[str, Any]) -> str:
    return (entry.get("id") or {}).get("wikidata") or ""


def _name_parts(entry: dict[str, Any]) -> tuple[str, str, str]:
    name = entry.get("name") or {}
    first = name.get("first", "") or ""
    last = name.get("last", "") or ""
    fallback = f"{first} {last}".strip()
    official_full = name.get("official_full") or fallback
    return first, last, official_full


def _string_or_empty(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _build_house_row(entry: dict[str, Any], term: dict[str, Any]) -> dict[str, Any]:
    first, last, official_full = _name_parts(entry)
    row: dict[str, Any] = {
        "bioguide_id": _bioguide_id(entry),
        "member_name": official_full,
        "first_name": first,
        "last_name": last,
        "state": _string_or_empty(term.get("state")),
        "district": _string_or_empty(term.get("district")),
        "party": _string_or_empty(term.get("party")),
        "phone": _string_or_empty(term.get("phone")),
        "sworn_date": _string_or_empty(term.get("start")),
        "fec_ids": _extract_fec_ids(entry),
        "wikidata_id": _wikidata_id(entry),
        "govtrack_id": _govtrack_id(entry),
    }
    for key in _PASSTHROUGH_HOUSE_EMPTY_KEYS:
        row[key] = ""
    return row


def _build_senate_row(entry: dict[str, Any], term: dict[str, Any]) -> dict[str, Any]:
    first, last, official_full = _name_parts(entry)
    return {
        "bioguide_id": _bioguide_id(entry),
        "member_full": official_full,
        "first_name": first,
        "last_name": last,
        "state": _string_or_empty(term.get("state")),
        "party": _string_or_empty(term.get("party")),
        "class": _string_or_empty(term.get("class")),
        "phone": _string_or_empty(term.get("phone")),
        # YAML terms carry contact_form (a URL), not an email address.
        "email": "",
        # YAML field is `url`; loader contract is `website`.
        "website": _string_or_empty(term.get("url")),
        "address": _string_or_empty(term.get("address")),
        "fec_ids": _extract_fec_ids(entry),
        "wikidata_id": _wikidata_id(entry),
        "govtrack_id": _govtrack_id(entry),
        # YAML does not encode an appointed flag.
        "appointed": "",
    }


def _build_delegate_row(entry: dict[str, Any], term: dict[str, Any]) -> dict[str, Any]:
    first, last, official_full = _name_parts(entry)
    return {
        "bioguide_id": _bioguide_id(entry),
        "member_name": official_full,
        "first_name": first,
        "last_name": last,
        "state": _string_or_empty(term.get("state")),
        "district": _string_or_empty(term.get("district")),
        "party": _string_or_empty(term.get("party")),
        "phone": _string_or_empty(term.get("phone")),
        "sworn_date": _string_or_empty(term.get("start")),
        "fec_ids": _extract_fec_ids(entry),
        "wikidata_id": _wikidata_id(entry),
        "govtrack_id": _govtrack_id(entry),
        "office_id": OFFICE_US_HOUSE_DELEGATE,
    }


def _build_executive_row(
    entry: dict[str, Any],
    term: dict[str, Any],
    office_type: str,
) -> dict[str, Any]:
    """Build a president/vp row.

    Executive entries frequently lack a bioguide_id (presidents who never served
    in Congress), so govtrack_id and wikidata_id are surfaced for the spine
    loader's identity-fallback chain.
    """
    first, last, _ = _name_parts(entry)
    return {
        "bioguide_id": _bioguide_id(entry),
        "govtrack_id": _govtrack_id(entry),
        "wikidata_id": _wikidata_id(entry),
        "first_name": first,
        "last_name": last,
        "party": _string_or_empty(term.get("party")),
        "fec_ids": _extract_fec_ids(entry),
        "office_type": office_type,
        "term_start": _string_or_empty(term.get("start")),
        "term_end": _string_or_empty(term.get("end")),
    }


@dataclass
class VacancyPredecessor:
    """A historical officeholder who last held a now-vacant House seat."""

    bioguide_id: str
    first_name: str
    last_name: str
    state: str
    district: str
    party: str
    term_end: str
    fec_ids: list[str] = field(default_factory=list)
    wikidata_id: str = ""
    govtrack_id: str = ""


@dataclass
class HistoricalPredecessors:
    """Most-recent predecessors for currently vacant federal seats."""

    house_predecessors: list[VacancyPredecessor] = field(default_factory=list)


def fetch_historical_entries() -> list[dict[str, Any]]:
    """Fetch and parse the historical legislators YAML."""
    with httpx.Client(timeout=120.0, follow_redirects=True) as client:
        payload = _fetch_yaml_payload(client, LEGISLATORS_HISTORICAL_YAML_URL)
    return _parse_yaml_entries(payload, LEGISLATORS_HISTORICAL_YAML_URL)


def select_most_recent_vacancy_predecessors(
    current: AdaptedLegislators,
    historical_entries: list[dict[str, Any]],
    *,
    min_term_end: date | None = None,
) -> HistoricalPredecessors:
    """Identify vacant House seats and return the most recent prior holder for each.

    Compares filled seats from ``current.house_rows`` against historical entries
    to find which districts lack a current member. For each vacant district,
    selects the entry whose last House term for that district ended most recently.

    ``min_term_end`` filters out defunct districts whose last holder left before
    that date (e.g. districts eliminated by redistricting). Defaults to 2 years
    before today.
    """
    if min_term_end is None:
        min_term_end = date(date.today().year - 2, 1, 1)

    filled_seats: set[tuple[str, str]] = {(row["state"], str(row["district"]).zfill(2)) for row in current.house_rows}

    best: dict[tuple[str, str], VacancyPredecessor] = {}

    for entry in historical_entries:
        terms = entry.get("terms") or []
        house_terms = [t for t in terms if t.get("type") == "rep"]
        if not house_terms:
            continue

        for term in reversed(house_terms):
            state = _string_or_empty(term.get("state"))
            district = _string_or_empty(term.get("district")).zfill(2)
            term_end = _string_or_empty(term.get("end"))
            if not state or not term_end:
                continue
            if _is_territory_delegate(term):
                continue

            parsed_end = _parse_iso_date(term_end)
            if parsed_end is not None and parsed_end < min_term_end:
                break

            seat = (state, district)
            if seat in filled_seats:
                continue

            existing = best.get(seat)
            if existing and existing.term_end >= term_end:
                continue

            first, last, _ = _name_parts(entry)
            best[seat] = VacancyPredecessor(
                bioguide_id=_bioguide_id(entry),
                first_name=first,
                last_name=last,
                state=state,
                district=district,
                party=_string_or_empty(term.get("party")),
                term_end=term_end,
                fec_ids=_extract_fec_ids(entry),
                wikidata_id=_wikidata_id(entry),
                govtrack_id=_govtrack_id(entry),
            )
            break

    return HistoricalPredecessors(
        house_predecessors=sorted(best.values(), key=lambda p: (p.state, p.district)),
    )


__all__ = [
    "AdaptedLegislators",
    "EXECUTIVE_YAML_URL",
    "HistoricalPredecessors",
    "LEGISLATORS_CURRENT_YAML_URL",
    "LEGISLATORS_HISTORICAL_YAML_URL",
    "VacancyPredecessor",
    "adapt_legislators_yaml",
    "fetch_historical_entries",
    "fetch_legislators_entries",
    "select_most_recent_vacancy_predecessors",
    "OFFICE_US_HOUSE_DELEGATE",
]


_ = UUID  # keep typing import optional-friendly without runtime warning.
