"""Authless public federal API (`/public/v1`).

Thin wrappers over existing query owners — this module contains NO SQL. The
router is included in ``api/main.py`` WITHOUT any auth dependency (see
``_include_public_routers``); everything it exposes is nonpartisan, source-linked
public-record data.
"""

from __future__ import annotations

import csv
import io
from decimal import Decimal
from typing import Any
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query, Response

from api.deps import get_db
from api.middleware.access import enforce_public_ip_rate_limit
from api.models import (
    CandidateListParams,
    PublicFederalOfficial,
    PublicMemberMoneySummary,
)
from api.queries import (
    fetch_campaign_finance_provenance,
    fetch_candidate_ie_summary,
    fetch_candidate_list,
    fetch_candidate_summary,
)
from api.queries.civics import fetch_current_federal_members

router = APIRouter(prefix="/public/v1", dependencies=[Depends(enforce_public_ip_rate_limit)])

_ZERO_MONEY = Decimal("0")
PUBLIC_CACHE_MAX_AGE_SECONDS = 900
# Match the request size of the private candidate-list endpoint's upper bound so a
# member with several linked candidate rows is never silently truncated.
_CANDIDATE_LOOKUP_LIMIT = 200
_CANDIDATE_OFFICE_BY_CHAMBER = {
    "House": "H",
    "Senate": "S",
    "Executive": "P",
}
PUBLIC_FEDERAL_EXPORT_CSV_COLUMNS = [
    "person_id",
    "person_name",
    "has_fec_money",
    "candidate_id",
    "total_raised",
    "total_spent",
    "net",
    "cash_on_hand",
    "summary_source",
    "ie_support_total",
    "ie_oppose_total",
    "ie_support_count",
    "ie_oppose_count",
    "source_urls",
]


def _public_cache_control_value() -> str:
    return f"public, max-age={PUBLIC_CACHE_MAX_AGE_SECONDS}"


def _public_cache_headers() -> dict[str, str]:
    return {"Cache-Control": _public_cache_control_value()}


def _apply_public_cache_headers(response: Response) -> None:
    response.headers.update(_public_cache_headers())


def _matches_filters(
    official: dict[str, Any],
    *,
    chamber: str | None,
    state: str | None,
    party: str | None,
) -> bool:
    return (
        (chamber is None or official["chamber"] == chamber)
        and (state is None or official["state"] == state)
        and (party is None or official["party"] == party)
    )


@router.get("/federal/officials", response_model=list[PublicFederalOfficial])
def list_federal_officials(
    response: Response,
    chamber: str | None = Query(default=None),
    state: str | None = Query(default=None),
    party: str | None = Query(default=None),
    conn: psycopg.Connection = Depends(get_db),
) -> list[PublicFederalOfficial]:
    """Return the current federal-official directory, optionally filtered.

    Filters are applied in Python over the full directory (543 rows) rather than
    pushed into the query, keeping this a pure wrapper over the single directory
    owner ``fetch_current_federal_members``.
    """
    _apply_public_cache_headers(response)
    officials = fetch_current_federal_members(conn)
    return [
        PublicFederalOfficial.model_validate({**official, "person_detail_path": f"/person/{official['person_id']}"})
        for official in officials
        if _matches_filters(official, chamber=chamber, state=state, party=party)
    ]


def _no_fec_money_summary(person_id: UUID, person_name: str) -> PublicMemberMoneySummary:
    return PublicMemberMoneySummary(
        person_id=person_id,
        person_name=person_name,
        has_fec_money=False,
        candidate_id=None,
        total_raised=_ZERO_MONEY,
        total_spent=_ZERO_MONEY,
        net=_ZERO_MONEY,
        cash_on_hand=None,
        summary_source=None,
        ie_support_total=_ZERO_MONEY,
        ie_oppose_total=_ZERO_MONEY,
        ie_support_count=0,
        ie_oppose_count=0,
        sources=[],
    )


def _money_summary_for_candidate(
    conn: psycopg.Connection,
    *,
    person_id: UUID,
    person_name: str,
    candidate: dict[str, Any],
) -> PublicMemberMoneySummary:
    candidate_id = candidate["id"]
    summary = fetch_candidate_summary(conn, candidate_id, candidate["name"])
    if summary is None:
        # Defensive: the candidate row disappeared between the list read and the
        # summary read. Surface as 500 rather than a misleading zero payload.
        raise HTTPException(status_code=500, detail="Candidate summary unavailable")
    ie_summary = fetch_candidate_ie_summary(conn, candidate_id)
    sources = fetch_campaign_finance_provenance(
        conn,
        row_source_record_id=candidate.get("source_record_id"),
        canonical_entity_type="person",
        canonical_entity_id=person_id,
    )
    return PublicMemberMoneySummary.model_validate(
        {
            "person_id": person_id,
            "person_name": person_name,
            "has_fec_money": True,
            "candidate_id": candidate_id,
            "total_raised": summary["total_raised"],
            "total_spent": summary["total_spent"],
            "net": summary["net"],
            "cash_on_hand": summary["cash_on_hand"],
            "summary_source": summary["summary_source"],
            "ie_support_total": ie_summary["support_total"],
            "ie_oppose_total": ie_summary["oppose_total"],
            "ie_support_count": ie_summary["support_count"],
            "ie_oppose_count": ie_summary["oppose_count"],
            "sources": sources,
        }
    )


def _normalized_code(value: str | None) -> str | None:
    return value.strip().upper() if value else None


def _house_district_matches(*, member_district: str | None, candidate_district: str | None) -> bool:
    normalized_member_district = _normalized_code(member_district)
    normalized_candidate_district = _normalized_code(candidate_district)
    if normalized_member_district is None:
        return True
    if normalized_member_district == "AL":
        return normalized_candidate_district in (None, "AL", "00")
    return normalized_candidate_district == normalized_member_district


def _candidate_matches_current_member(candidate: dict[str, Any], member: dict[str, Any]) -> bool:
    expected_office = _CANDIDATE_OFFICE_BY_CHAMBER.get(member["chamber"])
    if expected_office is None or candidate["office"] != expected_office:
        return False

    member_state = _normalized_code(member["state"])
    if member_state is not None and _normalized_code(candidate["state"]) != member_state:
        return False

    if expected_office == "H":
        return _house_district_matches(member_district=member["district"], candidate_district=candidate["district"])
    return True


def _select_current_member_candidate(candidates: list[dict[str, Any]], member: dict[str, Any]) -> dict[str, Any] | None:
    return next((candidate for candidate in candidates if _candidate_matches_current_member(candidate, member)), None)


def _select_public_money_candidate(candidates: list[dict[str, Any]], member: dict[str, Any]) -> dict[str, Any]:
    """Prefer current-office rows; fall back to linked FEC rows rather than a false no-money response."""
    return _select_current_member_candidate(candidates, member) or candidates[0]


def _public_money_row_for_member(conn: psycopg.Connection, member: dict[str, Any]) -> PublicMemberMoneySummary:
    person_id = member["person_id"]
    candidates = fetch_candidate_list(conn, CandidateListParams(person_id=person_id, limit=_CANDIDATE_LOOKUP_LIMIT))
    candidate_items = candidates["items"]
    if not candidate_items:
        return _no_fec_money_summary(person_id, member["person_name"])

    candidate = _select_public_money_candidate(candidate_items, member)
    return _money_summary_for_candidate(
        conn,
        person_id=person_id,
        person_name=member["person_name"],
        candidate=candidate,
    )


def build_public_federal_money_rows(conn: psycopg.Connection) -> list[PublicMemberMoneySummary]:
    """Build public money rows for every current federal official."""
    return [_public_money_row_for_member(conn, member) for member in fetch_current_federal_members(conn)]


def _public_money_row_for_person(conn: psycopg.Connection, person_id: UUID) -> PublicMemberMoneySummary | None:
    for member in fetch_current_federal_members(conn):
        if member["person_id"] == person_id:
            return _public_money_row_for_member(conn, member)
    return None


@router.get("/federal/export.json", response_model=list[PublicMemberMoneySummary])
def export_federal_money_json(
    response: Response,
    conn: psycopg.Connection = Depends(get_db),
) -> list[PublicMemberMoneySummary]:
    _apply_public_cache_headers(response)
    return build_public_federal_money_rows(conn)


def _csv_cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


def _source_urls_cell(row: PublicMemberMoneySummary) -> str:
    urls = [source.record_url or source.data_source_url for source in row.sources]
    return ";".join(url for url in urls if url)


def _public_federal_export_csv_row(row: PublicMemberMoneySummary) -> dict[str, str]:
    return {
        "person_id": _csv_cell(row.person_id),
        "person_name": row.person_name,
        "has_fec_money": _csv_cell(row.has_fec_money),
        "candidate_id": _csv_cell(row.candidate_id),
        "total_raised": _csv_cell(row.total_raised),
        "total_spent": _csv_cell(row.total_spent),
        "net": _csv_cell(row.net),
        "cash_on_hand": _csv_cell(row.cash_on_hand),
        "summary_source": _csv_cell(row.summary_source),
        "ie_support_total": _csv_cell(row.ie_support_total),
        "ie_oppose_total": _csv_cell(row.ie_oppose_total),
        "ie_support_count": _csv_cell(row.ie_support_count),
        "ie_oppose_count": _csv_cell(row.ie_oppose_count),
        "source_urls": _source_urls_cell(row),
    }


@router.get("/federal/export.csv")
def export_federal_money_csv(
    conn: psycopg.Connection = Depends(get_db),
) -> Response:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=PUBLIC_FEDERAL_EXPORT_CSV_COLUMNS)
    writer.writeheader()
    writer.writerows(_public_federal_export_csv_row(row) for row in build_public_federal_money_rows(conn))
    response = Response(content=output.getvalue(), media_type="text/csv")
    _apply_public_cache_headers(response)
    return response


@router.get("/federal/officials/{person_id}/money", response_model=PublicMemberMoneySummary)
def get_federal_official_money(
    person_id: UUID,
    response: Response,
    conn: psycopg.Connection = Depends(get_db),
) -> PublicMemberMoneySummary:
    """Return the FEC money + IE summary for one current federal official.

    404 only when ``person_id`` is not a current federal official. A known member
    with no linked ``cf.candidate`` returns 200 with ``has_fec_money=False``.
    """
    _apply_public_cache_headers(response)
    row = _public_money_row_for_person(conn, person_id)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail="Federal official not found",
            headers=_public_cache_headers(),
        )
    return row
