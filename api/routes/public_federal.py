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
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from api.deps import get_db
from api.middleware.access import enforce_public_ip_rate_limit, public_rate_limit_policy
from api.models import (
    DataSourceMetadataResponse,
    PublicContributorRow,
    PublicContributorsResponse,
    PublicEmployerIndustryCoverage,
    PublicEmployerRow,
    PublicEmployersResponse,
    PublicFederalCoverage,
    PublicFederalMetadataResponse,
    PublicFederalOfficial,
    PublicMemberMoneySummary,
    PublicRateLimitPolicy,
)
from api.queries import (
    fetch_campaign_finance_provenance,
    fetch_campaign_finance_provenance_batch,
    fetch_candidate_ie_summary,
    fetch_candidate_ie_summaries,
    fetch_candidate_public_money_summaries,
    fetch_candidate_public_money_summary,
    fetch_candidate_summary,
    fetch_candidates_for_people,
    fetch_person_contribution_sources,
    fetch_person_top_donors,
    fetch_person_top_employers,
    fetch_public_federal_data_sources,
    public_top_donors_identity_resolution_status,
)
from api.queries.civics import fetch_current_federal_members

# Every operation on this router shares one OpenAPI tag so generated clients
# group the public federal surface into a single namespace.
PUBLIC_FEDERAL_OPENAPI_TAG = "public-federal"

router = APIRouter(
    prefix="/public/v1",
    tags=[PUBLIC_FEDERAL_OPENAPI_TAG],
    dependencies=[Depends(enforce_public_ip_rate_limit)],
)

_ZERO_MONEY = Decimal("0")
# Fixed 14,324-row industry-classification benchmark: 837 classified /
# 13,487 unknown. Both the employer endpoint and the metadata payload derive the
# coverage percentage from these two counts, so the ratio can never drift.
_PUBLIC_EMPLOYER_INDUSTRY_CLASSIFIED_COUNT = 837
_PUBLIC_EMPLOYER_INDUSTRY_UNKNOWN_COUNT = 13487
_SAMPLED_COVERAGE_PERCENTAGE_QUANTUM = Decimal("0.000001")
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


class CsvResponse(Response):
    """``text/csv`` response owner for the public CSV export.

    Declared as the export route's ``response_class`` so the generated OpenAPI
    document advertises a ``text/csv`` string body instead of FastAPI's default
    ``application/json`` — a generated client must not JSON-decode the export.
    """

    media_type = "text/csv"


# Shared 404 contract for the routes that resolve one officeholder by path
# parameter, so the three declarations cannot drift apart.
_FEDERAL_OFFICIAL_NOT_FOUND_DETAIL = "Federal official not found"
_FEDERAL_OFFICIAL_NOT_FOUND_OPENAPI_RESPONSE = {
    404: {
        "description": "No current federal officeholder matches `person_id`.",
        "content": {
            "application/json": {
                "schema": {
                    "type": "object",
                    "properties": {
                        "detail": {
                            "type": "string",
                            "const": _FEDERAL_OFFICIAL_NOT_FOUND_DETAIL,
                        }
                    },
                    "required": ["detail"],
                    "additionalProperties": False,
                }
            }
        },
    }
}


def _public_cache_control_value() -> str:
    return f"public, max-age={PUBLIC_CACHE_MAX_AGE_SECONDS}"


# Access terms shared by every public operation description, sourced from the
# same cache-header owner the responses actually use.
_PUBLIC_ACCESS_NOTE = (
    f"No API key is required. Responses carry `Cache-Control: {_public_cache_control_value()}` "
    "and are rate limited per client IP."
)


def _public_cache_headers() -> dict[str, str]:
    return {"Cache-Control": _public_cache_control_value()}


def _apply_public_cache_headers(response: Response) -> None:
    response.headers.update(_public_cache_headers())


def _federal_official_not_found() -> HTTPException:
    return HTTPException(
        status_code=404,
        detail=_FEDERAL_OFFICIAL_NOT_FOUND_DETAIL,
        headers=_public_cache_headers(),
    )


def _employer_industry_benchmark() -> PublicEmployerIndustryCoverage:
    """Return the fixed industry-classification benchmark with a derived ratio.

    ``sampled_coverage_percentage`` is computed from the two counts rather than
    stored as an independent constant, so it cannot disagree with them.
    """
    classified = _PUBLIC_EMPLOYER_INDUSTRY_CLASSIFIED_COUNT
    unknown = _PUBLIC_EMPLOYER_INDUSTRY_UNKNOWN_COUNT
    sampled_coverage_percentage = (Decimal(classified) / Decimal(classified + unknown) * Decimal(100)).quantize(
        _SAMPLED_COVERAGE_PERCENTAGE_QUANTUM
    )
    return PublicEmployerIndustryCoverage(
        classified_count=classified,
        unknown_count=unknown,
        sampled_coverage_percentage=sampled_coverage_percentage,
    )


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


@router.get(
    "/federal/officials",
    response_model=list[PublicFederalOfficial],
    operation_id="list_public_federal_officials",
    summary="List current federal officials",
    description=(
        "Return the directory of federal officials who currently hold office, with party, "
        "state, district or Senate class, portrait URL, and the Civibus person detail path. "
        "Candidates who do not hold the office are excluded, so a challenger who shares an "
        "officeholder's name never appears. The optional `chamber`, `state`, and `party` "
        "filters narrow the directory; omitting all three returns every current officeholder. "
        f"{_PUBLIC_ACCESS_NOTE}"
    ),
)
def list_federal_officials(
    response: Response,
    chamber: str | None = Query(
        default=None,
        description='Exact-match filter on the chamber label, e.g. "House", "Senate", or "Executive".',
    ),
    state: str | None = Query(
        default=None,
        description='Exact-match filter on the two-letter state or territory postal code, e.g. "NC".',
    ),
    party: str | None = Query(
        default=None,
        description='Exact-match filter on the party label exactly as this endpoint returns it, e.g. "Independent".',
    ),
    conn: psycopg.Connection = Depends(get_db),
) -> list[PublicFederalOfficial]:
    """Return the current federal-official directory, optionally filtered.

    Filters are applied in Python over the full current-officeholder directory
    rather than pushed into the query, keeping this a pure wrapper over the
    single directory owner ``fetch_current_federal_members``.
    """
    _apply_public_cache_headers(response)
    officials = fetch_current_federal_members(conn)
    return [
        PublicFederalOfficial.model_validate({**official, "person_detail_path": f"/person/{official['person_id']}"})
        for official in officials
        if _matches_filters(official, chamber=chamber, state=state, party=party)
    ]


def _no_fec_money_summary(
    person_id: UUID,
    person_name: str,
    sources: list[dict[str, Any]] | None = None,
) -> PublicMemberMoneySummary:
    """Return an honest, source-linked absence instead of invented FEC money."""
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
        sources=sources or [],
    )


def _money_summary_for_candidate(
    conn: psycopg.Connection,
    *,
    member: dict[str, Any],
    candidate: dict[str, Any],
    summary: dict[str, Any] | None = None,
    ie_summary: dict[str, Any] | None = None,
    sources: list[dict[str, Any]] | None = None,
) -> PublicMemberMoneySummary:
    person_id = member["person_id"]
    candidate_id = candidate["id"]
    resolved_summary = summary or fetch_candidate_public_money_summary(conn, candidate_id, candidate["name"])
    if resolved_summary is None:
        # Defensive: the candidate row disappeared between the list read and the
        # summary read. Surface as 500 rather than a misleading zero payload.
        raise HTTPException(status_code=500, detail="Candidate summary unavailable")
    resolved_ie_summary = ie_summary or fetch_candidate_ie_summary(conn, candidate_id)
    resolved_sources = (
        sources
        if sources is not None
        else fetch_campaign_finance_provenance(
            conn,
            row_source_record_id=candidate.get("source_record_id"),
            canonical_entity_type="person",
            canonical_entity_id=person_id,
        )
    )
    public_totals = _public_money_totals(resolved_summary)
    return PublicMemberMoneySummary.model_validate(
        {
            "person_id": person_id,
            "person_name": member["person_name"],
            "has_fec_money": True,
            "candidate_id": candidate_id,
            **public_totals,
            "ie_support_total": resolved_ie_summary["support_total"],
            "ie_oppose_total": resolved_ie_summary["oppose_total"],
            "ie_support_count": resolved_ie_summary["support_count"],
            "ie_oppose_count": resolved_ie_summary["oppose_count"],
            "sources": resolved_sources,
        }
    )


def _public_money_totals(summary: dict[str, Any]) -> dict[str, Any]:
    out_of_cycle_total = summary.get("out_of_cycle_official_total")
    coverage = summary.get("coverage")
    public_coverage_payload = (
        {"fundraising_coverage": coverage}
        if isinstance(coverage, dict) and coverage.get("activity_state") != "populated"
        else {}
    )
    if (
        isinstance(coverage, dict)
        and coverage.get("activity_state") == "out_of_cycle_official_total"
        and out_of_cycle_total is not None
    ):
        return {
            "total_raised": out_of_cycle_total["total_raised"],
            "total_spent": out_of_cycle_total["total_spent"],
            "net": out_of_cycle_total["net"],
            "cash_on_hand": out_of_cycle_total["cash_on_hand"],
            "summary_source": out_of_cycle_total["summary_source"],
            "fundraising_coverage": coverage,
            "out_of_cycle_official_total": out_of_cycle_total,
        }
    return {
        "total_raised": summary["total_raised"],
        "total_spent": summary["total_spent"],
        "net": summary["net"],
        "cash_on_hand": summary["cash_on_hand"],
        "summary_source": summary["summary_source"],
        **public_coverage_payload,
    }


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


def _candidate_matches_current_office_and_state(
    candidate: dict[str, Any],
    member: dict[str, Any],
) -> bool:
    expected_office = _CANDIDATE_OFFICE_BY_CHAMBER.get(member["chamber"])
    if expected_office is None or candidate["office"] != expected_office:
        return False
    member_state = _normalized_code(member["state"])
    return member_state is None or _normalized_code(candidate["state"]) == member_state


def _is_vice_president_member(member: dict[str, Any]) -> bool:
    return (
        member.get("chamber") == "Executive"
        and _normalized_code(member.get("office_name")) == "VICE PRESIDENT OF THE UNITED STATES"
    )


def _select_vice_president_prior_candidate(
    candidates: list[dict[str, Any]],
    member: dict[str, Any],
) -> dict[str, Any] | None:
    if not _is_vice_president_member(member) or len(candidates) != 1:
        return None
    candidate = candidates[0]
    return candidate if _normalized_code(candidate.get("office")) in {"H", "S", "P"} else None


def _select_public_money_candidate(
    candidates: list[dict[str, Any]],
    member: dict[str, Any],
) -> dict[str, Any] | None:
    """Rank current-cycle office matches, allowing sourced House map changes."""
    current_cycle_candidates = [
        candidate for candidate in candidates if candidate.get("has_selected_cycle_link") is True
    ]
    exact_current_cycle = _select_current_member_candidate(current_cycle_candidates, member)
    if exact_current_cycle is not None:
        return exact_current_cycle
    prior_map_current_cycle = next(
        (
            candidate
            for candidate in current_cycle_candidates
            if _candidate_matches_current_office_and_state(candidate, member)
        ),
        None,
    )
    selected_candidate = prior_map_current_cycle or _select_current_member_candidate(candidates, member)
    if selected_candidate is not None:
        return selected_candidate
    return _select_vice_president_prior_candidate(candidates, member)


def _member_needs_executive_full_summary(member: dict[str, Any]) -> bool:
    return member.get("chamber") == "Executive"


def _public_money_row_for_member(conn: psycopg.Connection, member: dict[str, Any]) -> PublicMemberMoneySummary:
    person_id = member["person_id"]
    candidates = fetch_candidates_for_people(conn, [person_id]).get(person_id, [])
    return _public_money_row_for_member_candidates(conn, member=member, candidates=candidates)


def _current_federal_member_for_person(conn: psycopg.Connection, person_id: UUID) -> dict[str, Any] | None:
    for member in fetch_current_federal_members(conn):
        if member["person_id"] == person_id:
            return member
    return None


def _public_money_row_for_member_candidates(
    conn: psycopg.Connection,
    *,
    member: dict[str, Any],
    candidates: list[dict[str, Any]],
    summaries_by_candidate: dict[UUID, dict[str, Any]] | None = None,
    full_summaries_by_candidate: dict[UUID, dict[str, Any]] | None = None,
    ie_summaries_by_candidate: dict[UUID, dict[str, Any]] | None = None,
    provenance_by_person: dict[UUID, list[dict[str, Any]]] | None = None,
) -> PublicMemberMoneySummary:
    person_id = member["person_id"]
    candidate = _select_public_money_candidate(candidates[:_CANDIDATE_LOOKUP_LIMIT], member)
    if candidate is None:
        sources = (
            provenance_by_person.get(person_id, [])
            if provenance_by_person is not None
            else fetch_campaign_finance_provenance(
                conn,
                row_source_record_id=member.get("officeholding_source_record_id"),
                canonical_entity_type="person",
                canonical_entity_id=person_id,
            )
        )
        return _no_fec_money_summary(person_id, member["person_name"], sources)
    return _money_summary_for_candidate(
        conn,
        member=member,
        candidate=candidate,
        summary=(full_summaries_by_candidate or {}).get(candidate["id"])
        or (summaries_by_candidate or {}).get(candidate["id"]),
        ie_summary=(ie_summaries_by_candidate or {}).get(candidate["id"]),
        sources=(provenance_by_person or {}).get(person_id),
    )


def _selected_public_money_candidates_by_person(
    members: list[dict[str, Any]],
    candidates_by_person: dict[UUID, list[dict[str, Any]]],
) -> dict[UUID, dict[str, Any]]:
    selected_candidates: dict[UUID, dict[str, Any]] = {}
    for member in members:
        person_id = member["person_id"]
        candidates = candidates_by_person.get(person_id, [])
        selected_candidate = _select_public_money_candidate(
            candidates[:_CANDIDATE_LOOKUP_LIMIT],
            member,
        )
        if selected_candidate is not None:
            selected_candidates[person_id] = selected_candidate
    return selected_candidates


def _provenance_requests_for_members(
    members: list[dict[str, Any]],
    selected_candidates_by_person: dict[UUID, dict[str, Any]],
) -> list[tuple[UUID, UUID | None]]:
    return [
        (
            member["person_id"],
            (
                selected_candidates_by_person[member["person_id"]].get("source_record_id")
                if member["person_id"] in selected_candidates_by_person
                else member.get("officeholding_source_record_id")
            ),
        )
        for member in members
    ]


def _fetch_executive_candidate_summaries(
    conn: psycopg.Connection,
    members: list[dict[str, Any]],
    selected_candidates_by_person: dict[UUID, dict[str, Any]],
) -> dict[UUID, dict[str, Any]]:
    summaries_by_candidate: dict[UUID, dict[str, Any]] = {}
    for member in members:
        candidate = selected_candidates_by_person.get(member["person_id"])
        if candidate is None or not _member_needs_executive_full_summary(member):
            continue
        summary = fetch_candidate_summary(conn, candidate["id"], candidate["name"])
        if summary is None:
            raise HTTPException(status_code=500, detail="Candidate summary unavailable")
        summaries_by_candidate[candidate["id"]] = summary
    return summaries_by_candidate


def build_public_federal_money_rows(conn: psycopg.Connection) -> list[PublicMemberMoneySummary]:
    """Build public money rows for every current federal official."""
    members = fetch_current_federal_members(conn)
    candidates_by_person = fetch_candidates_for_people(conn, [member["person_id"] for member in members])
    selected_candidates_by_person = _selected_public_money_candidates_by_person(members, candidates_by_person)
    selected_candidate_ids = [candidate["id"] for candidate in selected_candidates_by_person.values()]
    selected_candidate_refs = [
        (candidate["id"], candidate["name"]) for candidate in selected_candidates_by_person.values()
    ]
    summaries_by_candidate = fetch_candidate_public_money_summaries(conn, selected_candidate_refs)
    full_summaries_by_candidate = _fetch_executive_candidate_summaries(
        conn,
        members,
        selected_candidates_by_person,
    )
    ie_summaries_by_candidate = fetch_candidate_ie_summaries(conn, selected_candidate_ids)
    provenance_by_person = fetch_campaign_finance_provenance_batch(
        conn,
        provenance_requests=_provenance_requests_for_members(members, selected_candidates_by_person),
        canonical_entity_type="person",
    )
    return [
        _public_money_row_for_member_candidates(
            conn,
            member=member,
            candidates=candidates_by_person.get(member["person_id"], []),
            summaries_by_candidate=summaries_by_candidate,
            full_summaries_by_candidate=full_summaries_by_candidate,
            ie_summaries_by_candidate=ie_summaries_by_candidate,
            provenance_by_person=provenance_by_person,
        )
        for member in members
    ]


def _public_money_row_for_person(conn: psycopg.Connection, person_id: UUID) -> PublicMemberMoneySummary | None:
    member = _current_federal_member_for_person(conn, person_id)
    if member is None:
        return None

    candidates = fetch_candidates_for_people(conn, [person_id]).get(person_id, [])
    selected_candidate = _select_public_money_candidate(
        candidates[:_CANDIDATE_LOOKUP_LIMIT],
        member,
    )
    selected_candidate_ids = [selected_candidate["id"]] if selected_candidate is not None else []
    full_summaries_by_candidate = {}
    if selected_candidate is not None and _member_needs_executive_full_summary(member):
        summary = fetch_candidate_summary(conn, selected_candidate["id"], selected_candidate["name"])
        if summary is None:
            raise HTTPException(status_code=500, detail="Candidate summary unavailable")
        full_summaries_by_candidate[selected_candidate["id"]] = summary
    return _public_money_row_for_member_candidates(
        conn,
        member=member,
        candidates=candidates,
        full_summaries_by_candidate=full_summaries_by_candidate,
        ie_summaries_by_candidate=fetch_candidate_ie_summaries(conn, selected_candidate_ids),
    )


@router.get(
    "/federal/export.json",
    response_model=list[PublicMemberMoneySummary],
    operation_id="export_public_federal_money_json",
    summary="Export every official's money summary as JSON",
    description=(
        "Return the FEC money and Schedule E independent-expenditure summary for every "
        "current federal official in one JSON array — the bulk counterpart to the "
        "per-official money endpoint, with identical per-row fields. Officials with no "
        "linked FEC candidate are included with `has_fec_money` false and zeroed totals. "
        f"{_PUBLIC_ACCESS_NOTE}"
    ),
)
def export_federal_money_json(
    response: Response,
    conn: psycopg.Connection = Depends(get_db),
) -> list[PublicMemberMoneySummary]:
    """Return the bulk money + IE export for every current federal official."""
    _apply_public_cache_headers(response)
    return build_public_federal_money_rows(conn)


_DANGEROUS_CSV_FORMULA_PREFIXES = frozenset({"=", "+", "-", "@"})


def _requires_csv_formula_escaping(value: str) -> bool:
    stripped_value = value.lstrip(" \t\r\n")
    return bool(stripped_value) and stripped_value[0] in _DANGEROUS_CSV_FORMULA_PREFIXES


def _csv_cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, str):
        return f"'{value}" if _requires_csv_formula_escaping(value) else value
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


@router.get(
    "/federal/export.csv",
    response_class=CsvResponse,
    operation_id="export_public_federal_money_csv",
    summary="Export every official's money summary as CSV",
    description=(
        "Return the same rows as the JSON export as a `text/csv` document with a header "
        "row. Columns, in order: "
        f"{', '.join(f'`{column}`' for column in PUBLIC_FEDERAL_EXPORT_CSV_COLUMNS)}. "
        "`source_urls` is a semicolon-separated list of the filing URLs backing the row. "
        f"{_PUBLIC_ACCESS_NOTE}"
    ),
)
def export_federal_money_csv(
    conn: psycopg.Connection = Depends(get_db),
) -> Response:
    """Return the bulk money + IE export as a CSV document."""
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=PUBLIC_FEDERAL_EXPORT_CSV_COLUMNS)
    writer.writeheader()
    writer.writerows(_public_federal_export_csv_row(row) for row in build_public_federal_money_rows(conn))
    response = CsvResponse(content=output.getvalue())
    _apply_public_cache_headers(response)
    return response


@router.get(
    "/federal/officials/{person_id}/money",
    response_model=PublicMemberMoneySummary,
    operation_id="get_public_federal_official_money",
    summary="Get one official's FEC money and outside-spending summary",
    description=(
        "Return total raised, total spent, net, cash on hand, and the Schedule E "
        "independent expenditures made for and against one current federal official, with "
        "a source link for every figure. A known official with no linked FEC candidate "
        "returns 200 with `has_fec_money` false and zeroed totals rather than invented "
        f"money; 404 means `person_id` is not a current federal officeholder. {_PUBLIC_ACCESS_NOTE}"
    ),
    responses=_FEDERAL_OFFICIAL_NOT_FOUND_OPENAPI_RESPONSE,
)
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
        raise _federal_official_not_found()
    return row


@router.get(
    "/federal/officials/{person_id}/contributors",
    response_model=PublicContributorsResponse,
    operation_id="get_public_federal_official_contributors",
    summary="Get one official's top contributors",
    description=(
        "Return the top contributors to one current federal official, each with the total "
        "amount contributed and the number of itemized transactions behind it. Only "
        "source-backed contributions are included, and `sources` links the filings they "
        "come from. 404 means `person_id` is not a current federal officeholder. "
        f"{_PUBLIC_ACCESS_NOTE}"
    ),
    responses=_FEDERAL_OFFICIAL_NOT_FOUND_OPENAPI_RESPONSE,
)
def get_federal_official_contributors(
    person_id: UUID,
    response: Response,
    conn: psycopg.Connection = Depends(get_db),
) -> PublicContributorsResponse:
    """Return the top source-backed contributors for one current federal official."""
    _apply_public_cache_headers(response)
    if _current_federal_member_for_person(conn, person_id) is None:
        raise _federal_official_not_found()

    contributors = fetch_person_top_donors(conn, person_id, source_backed_only=True) or []
    sources = fetch_person_contribution_sources(conn, person_id) or []
    return PublicContributorsResponse(
        person_id=person_id,
        contributors=[PublicContributorRow.model_validate(row) for row in contributors],
        sources=sources,
    )


@router.get(
    "/federal/officials/{person_id}/employers",
    response_model=PublicEmployersResponse,
    operation_id="get_public_federal_official_employers",
    summary="Get one official's top contributor employers",
    description=(
        "Return the top employers reported by contributors to one current federal "
        "official, each with the total contributed, the itemized transaction count, and an "
        "industry label that is `UNKNOWN_INDUSTRY` where classification is unavailable. "
        "`classified_count`, `unknown_count`, and `sampled_coverage_percentage` state how "
        "sparse that industry coverage is, so the labels are never read as complete. 404 "
        f"means `person_id` is not a current federal officeholder. {_PUBLIC_ACCESS_NOTE}"
    ),
    responses=_FEDERAL_OFFICIAL_NOT_FOUND_OPENAPI_RESPONSE,
)
def get_federal_official_employers(
    person_id: UUID,
    response: Response,
    conn: psycopg.Connection = Depends(get_db),
) -> PublicEmployersResponse:
    """Return the top source-backed contributor employers for one current federal official."""
    _apply_public_cache_headers(response)
    if _current_federal_member_for_person(conn, person_id) is None:
        raise _federal_official_not_found()

    employers = fetch_person_top_employers(conn, person_id, source_backed_only=True) or []
    sources = fetch_person_contribution_sources(conn, person_id) or []
    # Sparse industry coverage stays explicit beside the UNKNOWN_INDUSTRY bucket,
    # sourced from the same benchmark the metadata payload publishes.
    industry_benchmark = _employer_industry_benchmark()
    return PublicEmployersResponse(
        person_id=person_id,
        employers=[PublicEmployerRow.model_validate(row) for row in employers],
        classified_count=industry_benchmark.classified_count,
        unknown_count=industry_benchmark.unknown_count,
        sampled_coverage_percentage=industry_benchmark.sampled_coverage_percentage,
        sources=sources,
    )


@router.get(
    "/federal/metadata",
    response_model=PublicFederalMetadataResponse,
    operation_id="get_public_federal_metadata",
    summary="Get federal-first data freshness, request limits, and coverage qualifications",
    description=(
        "Return a machine-readable contract describing the federal-first data behind this API: "
        "the source freshness (`last_pull_at`, `last_pull_status`, `record_count`) of the FEC and "
        "federal officeholder data sources, the effective per-client request limit, and honest "
        "coverage qualifications — the current officeholder count (never a fixed denominator), the "
        "fixed industry-classification benchmark, and the unresolved state of surfaced donor "
        f"identities. {_PUBLIC_ACCESS_NOTE}"
    ),
)
def get_public_federal_metadata(
    request: Request,
    response: Response,
    conn: psycopg.Connection = Depends(get_db),
) -> PublicFederalMetadataResponse:
    """Assemble the federal-first freshness, request-limit, and coverage contract.

    Every fact stays owned by its existing seam: source freshness from the
    bounded metadata snapshot query, the request limit from the access
    middleware policy accessor, the officeholder denominator from the current
    roster owner, and the donor-resolution disclosure from the campaign-finance
    grouping seam.
    """
    _apply_public_cache_headers(response)
    max_requests, window_seconds = public_rate_limit_policy(request.app.state)
    data_sources = fetch_public_federal_data_sources(conn)
    return PublicFederalMetadataResponse(
        data_sources=[DataSourceMetadataResponse.model_validate(row) for row in data_sources],
        rate_limit=PublicRateLimitPolicy(max_requests=max_requests, window_seconds=window_seconds),
        coverage=PublicFederalCoverage(
            current_officeholder_count=len(fetch_current_federal_members(conn)),
            officeholder_denominator_is_fixed=False,
            employer_industry=_employer_industry_benchmark(),
            donor_identity_resolution=public_top_donors_identity_resolution_status(),
        ),
    )
