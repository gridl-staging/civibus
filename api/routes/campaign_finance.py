
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Path, Query

from api.deps import get_db
from api.models import (
    CandidateFundraisingSummary,
    CountyCampaignFinanceSummary,
    CandidateListItem,
    CandidateListParams,
    CandidateListResponse,
    CandidateResponse,
    CommitteeFilingBreakdown,
    CommitteeFundraisingSummary,
    CommitteeIndependentExpenditureActivity,
    CommitteeListItem,
    CommitteeListParams,
    CommitteeListResponse,
    CommitteeResponse,
    FilingResponse,
    IndependentExpenditureResponse,
    IndependentExpenditureSummary,
    PersonContributionInsights,
    PersonTopEmployerRow,
    RankedTransactionParty,
    TransactionListParams,
    TransactionResponse,
)
from api.queries import (
    CAMPAIGN_FINANCE_CANDIDATE_DETAIL_SQL,
    CAMPAIGN_FINANCE_COMMITTEE_DETAIL_SQL,
    CAMPAIGN_FINANCE_FILING_DETAIL_SQL,
    SelectedCycle,
    UnknownCountySlugError,
    build_zero_committee_fundraising_summary,
    fetch_campaign_finance_provenance,
    fetch_cf_summary_by_county,
    fetch_candidate_ie_summary,
    fetch_candidate_ie_transactions,
    fetch_candidate_list,
    fetch_candidate_summary,
    fetch_candidates_by_slug,
    count_committee_filings,
    fetch_committee_filing_breakdown,
    fetch_committee_fundraising_summary,
    fetch_committee_ie_activity,
    fetch_committee_linked_candidates,
    fetch_committee_list,
    fetch_committees_by_slug,
    fetch_one_row,
    fetch_person_contribution_insights,
    fetch_person_top_donors,
    fetch_person_top_employers,
    fetch_state_campaign_finance_detail,  # noqa: F401 - retained for route-retirement guard tests.
    fetch_state_campaign_finance_summaries,  # noqa: F401 - retained for route-retirement guard tests.
    fetch_transaction_list,
    resolve_selected_cycle,
)
from api.routes.validation import build_query_params_dependency
from core.types.python.models import validate_optional_state_code
from domains.campaign_finance.constants import FILING_BREAKDOWN_STORE_LIMIT

router = APIRouter()
_build_transaction_list_params = build_query_params_dependency(TransactionListParams)
_build_candidate_list_params = build_query_params_dependency(CandidateListParams)
_build_committee_list_params = build_query_params_dependency(CommitteeListParams)
_STATE_CAMPAIGN_FINANCE_RETIRED_DETAIL = (
    "State campaign-finance endpoints are retired for federal-first v1; "
    "use federal candidate, committee, and person endpoints instead."
)


def _selected_cycle_dependency(cycle: int | None = Query(default=None)) -> SelectedCycle:
    try:
        return resolve_selected_cycle(cycle)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@dataclass(frozen=True)
class _ProvenanceContext:
    """Provenance routing parameters for campaign-finance detail endpoints."""

    canonical_entity_type: str
    canonical_entity_id_key: str | None
    fallback_row_source_record_id_key: str | None = None
    fallback_canonical_entity_id_key: str | None = None


def _resolve_provenance_targets(
    detail_row: dict[str, object],
    provenance: _ProvenanceContext,
) -> tuple[object | None, object | None]:
    row_source_record_id = detail_row.pop("source_record_id")
    canonical_entity_id = (
        detail_row[provenance.canonical_entity_id_key] if provenance.canonical_entity_id_key is not None else None
    )
    if provenance.fallback_row_source_record_id_key is None or row_source_record_id is not None:
        return row_source_record_id, canonical_entity_id

    # Filing rows should only use committee-level provenance when the filing row
    # itself does not carry a source_record_id.
    fallback_source_record_id = detail_row.pop(provenance.fallback_row_source_record_id_key)
    fallback_canonical_entity_id = (
        detail_row.pop(provenance.fallback_canonical_entity_id_key)
        if provenance.fallback_canonical_entity_id_key is not None
        else None
    )
    return fallback_source_record_id, fallback_canonical_entity_id


def _fetch_row_or_404(conn: psycopg.Connection, query: str, row_id: UUID, not_found_detail: str) -> dict:
    """Fetch a single row by id or raise 404."""
    row = fetch_one_row(conn, query=query, row_id=row_id)
    if row is None:
        raise HTTPException(status_code=404, detail=not_found_detail)
    return row


def _build_detail_response(
    conn: psycopg.Connection,
    *,
    query: str,
    row_id: UUID,
    not_found_detail: str,
    provenance: _ProvenanceContext,
    response_model: type[CommitteeResponse] | type[CandidateResponse] | type[FilingResponse],
    extra_detail_fields: Callable[[psycopg.Connection, UUID], dict[str, object]] | None = None,
) -> CommitteeResponse | CandidateResponse | FilingResponse:
    detail_row = _fetch_row_or_404(conn, query, row_id, not_found_detail)

    row_source_record_id, canonical_entity_id = _resolve_provenance_targets(detail_row, provenance)

    detail_row["sources"] = fetch_campaign_finance_provenance(
        conn,
        row_source_record_id=row_source_record_id,
        canonical_entity_type=provenance.canonical_entity_type,
        canonical_entity_id=canonical_entity_id,
    )
    if extra_detail_fields is not None:
        detail_row.update(extra_detail_fields(conn, row_id))
    return response_model.model_validate(detail_row)


@router.get("/committees", response_model=CommitteeListResponse)
def list_committees(
    params: CommitteeListParams = Depends(_build_committee_list_params),
    conn: psycopg.Connection = Depends(get_db),
) -> CommitteeListResponse:
    result = fetch_committee_list(conn, params)
    result["items"] = [CommitteeListItem.model_validate(row) for row in result["items"]]
    return CommitteeListResponse.model_validate(result)


@router.get("/committees/by-slug/{slug}", response_model=list[CommitteeListItem])
def get_committee_by_slug(slug: str, conn: psycopg.Connection = Depends(get_db)) -> list[CommitteeListItem]:
    rows = fetch_committees_by_slug(conn, slug)
    return [CommitteeListItem.model_validate(row) for row in rows]


@router.get("/committees/{committee_id}", response_model=CommitteeResponse)
def get_committee(committee_id: UUID, conn: psycopg.Connection = Depends(get_db)) -> CommitteeResponse:
    return _build_detail_response(
        conn,
        query=CAMPAIGN_FINANCE_COMMITTEE_DETAIL_SQL,
        row_id=committee_id,
        not_found_detail="Committee not found",
        provenance=_ProvenanceContext(
            canonical_entity_type="organization",
            canonical_entity_id_key="organization_id",
        ),
        response_model=CommitteeResponse,
        extra_detail_fields=lambda db_conn, current_committee_id: {
            "linked_candidates": fetch_committee_linked_candidates(db_conn, current_committee_id)
        },
    )


@router.get("/candidates", response_model=CandidateListResponse)
def list_candidates(
    params: CandidateListParams = Depends(_build_candidate_list_params),
    conn: psycopg.Connection = Depends(get_db),
) -> CandidateListResponse:
    result = fetch_candidate_list(conn, params)
    result["items"] = [CandidateListItem.model_validate(row) for row in result["items"]]
    return CandidateListResponse.model_validate(result)


@router.get("/candidates/by-slug/{slug}", response_model=list[CandidateListItem])
def get_candidate_by_slug(slug: str, conn: psycopg.Connection = Depends(get_db)) -> list[CandidateListItem]:
    rows = fetch_candidates_by_slug(conn, slug)
    return [CandidateListItem.model_validate(row) for row in rows]


@router.get("/candidates/{candidate_id}", response_model=CandidateResponse)
def get_candidate(candidate_id: UUID, conn: psycopg.Connection = Depends(get_db)) -> CandidateResponse:
    return _build_detail_response(
        conn,
        query=CAMPAIGN_FINANCE_CANDIDATE_DETAIL_SQL,
        row_id=candidate_id,
        not_found_detail="Candidate not found",
        provenance=_ProvenanceContext(
            canonical_entity_type="person",
            canonical_entity_id_key="person_id",
        ),
        response_model=CandidateResponse,
    )


@router.get("/filings/{filing_id}", response_model=FilingResponse)
def get_filing(filing_id: UUID, conn: psycopg.Connection = Depends(get_db)) -> FilingResponse:
    return _build_detail_response(
        conn,
        query=CAMPAIGN_FINANCE_FILING_DETAIL_SQL,
        row_id=filing_id,
        not_found_detail="Filing not found",
        provenance=_ProvenanceContext(
            canonical_entity_type="organization",
            canonical_entity_id_key=None,
            fallback_row_source_record_id_key="fallback_committee_source_record_id",
            fallback_canonical_entity_id_key="fallback_committee_organization_id",
        ),
        response_model=FilingResponse,
    )


@router.get("/transactions", response_model=list[TransactionResponse])
def list_transactions(
    params: TransactionListParams = Depends(_build_transaction_list_params),
    selected_cycle: SelectedCycle = Depends(_selected_cycle_dependency),
    conn: psycopg.Connection = Depends(get_db),
) -> list[TransactionResponse]:
    transaction_rows = fetch_transaction_list(conn, params, selected_cycle)
    return [TransactionResponse.model_validate(transaction_row) for transaction_row in transaction_rows]


@router.get("/person/{person_id}/contribution-insights", response_model=PersonContributionInsights)
def get_person_contribution_insights(
    person_id: UUID,
    selected_cycle: SelectedCycle = Depends(_selected_cycle_dependency),
    conn: psycopg.Connection = Depends(get_db),
) -> PersonContributionInsights:
    insights = fetch_person_contribution_insights(conn, person_id, selected_cycle)
    if insights is None:
        raise HTTPException(status_code=404, detail="Person not found")
    return PersonContributionInsights.model_validate(insights)


@router.get("/person/{person_id}/top-donors", response_model=list[RankedTransactionParty])
def get_person_top_donors(
    person_id: UUID,
    limit: int = Query(default=10, ge=1, le=100),
    selected_cycle: SelectedCycle = Depends(_selected_cycle_dependency),
    conn: psycopg.Connection = Depends(get_db),
) -> list[RankedTransactionParty]:
    donor_rows = fetch_person_top_donors(conn, person_id, limit, selected_cycle)
    if donor_rows is None:
        raise HTTPException(status_code=404, detail="Person not found")
    return [RankedTransactionParty.model_validate(donor_row) for donor_row in donor_rows]


@router.get("/person/{person_id}/top-employers", response_model=list[PersonTopEmployerRow])
def get_person_top_employers(
    person_id: UUID,
    limit: int = Query(default=10, ge=1, le=100),
    selected_cycle: SelectedCycle = Depends(_selected_cycle_dependency),
    conn: psycopg.Connection = Depends(get_db),
) -> list[PersonTopEmployerRow]:
    employer_rows = fetch_person_top_employers(conn, person_id, limit, selected_cycle)
    if employer_rows is None:
        raise HTTPException(status_code=404, detail="Person not found")
    return [PersonTopEmployerRow.model_validate(employer_row) for employer_row in employer_rows]


@router.get("/committees/{committee_id}/summary", response_model=CommitteeFundraisingSummary)
def get_committee_summary(
    committee_id: UUID,
    selected_cycle: SelectedCycle = Depends(_selected_cycle_dependency),
    conn: psycopg.Connection = Depends(get_db),
) -> CommitteeFundraisingSummary:
    detail_row = _fetch_row_or_404(conn, CAMPAIGN_FINANCE_COMMITTEE_DETAIL_SQL, committee_id, "Committee not found")

    summary = fetch_committee_fundraising_summary(conn, committee_id, selected_cycle)
    if summary is None:
        summary = build_zero_committee_fundraising_summary(
            committee_id=committee_id,
            committee_name=detail_row["name"],
            selected_cycle=selected_cycle,
        )
    return CommitteeFundraisingSummary.model_validate(summary)


@router.get("/counties/{state}/{county_slug}/campaign-finance-summary", response_model=CountyCampaignFinanceSummary)
def get_county_campaign_finance_summary(
    state: str,
    county_slug: str,
    conn: psycopg.Connection = Depends(get_db),
) -> CountyCampaignFinanceSummary:
    # Stage 1 selected committee-city proxy path: this reports money flowing out of
    # committees in mapped county cities, not candidate residence or donor residence.
    try:
        summary = fetch_cf_summary_by_county(conn, state=state, county_slug=county_slug)
    except UnknownCountySlugError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    summary.setdefault("sources", [])
    return CountyCampaignFinanceSummary.model_validate(summary)


@router.get("/committees/{committee_id}/filings/summary", response_model=CommitteeFilingBreakdown)
def get_committee_filings_summary(
    committee_id: UUID,
    limit: int = Query(default=50, ge=1, le=FILING_BREAKDOWN_STORE_LIMIT),
    offset: int = Query(default=0, ge=0),
    conn: psycopg.Connection = Depends(get_db),
) -> CommitteeFilingBreakdown:
    detail_row = _fetch_row_or_404(conn, CAMPAIGN_FINANCE_COMMITTEE_DETAIL_SQL, committee_id, "Committee not found")

    filings = fetch_committee_filing_breakdown(conn, committee_id, limit=limit, offset=offset)
    total_filings = count_committee_filings(conn, committee_id)
    paginable_filings = min(total_filings, FILING_BREAKDOWN_STORE_LIMIT)
    return CommitteeFilingBreakdown.model_validate(
        {
            "committee_id": committee_id,
            "committee_name": detail_row["name"],
            "total_filings": total_filings,
            "store_limit": FILING_BREAKDOWN_STORE_LIMIT,
            "has_next": offset + len(filings) < paginable_filings,
            "offset": offset,
            "limit": limit,
            "filings": filings,
        }
    )


@router.get("/candidates/{candidate_id}/summary", response_model=CandidateFundraisingSummary)
def get_candidate_summary(
    candidate_id: UUID,
    selected_cycle: SelectedCycle = Depends(_selected_cycle_dependency),
    conn: psycopg.Connection = Depends(get_db),
) -> CandidateFundraisingSummary:
    """Return the FEC weball / derived fundraising summary for a candidate."""
    detail_row = _fetch_row_or_404(conn, CAMPAIGN_FINANCE_CANDIDATE_DETAIL_SQL, candidate_id, "Candidate not found")

    # ``fetch_candidate_summary`` owns the zero-payload / no-linked-committee branch
    # itself, so the route does not need a fallback. ``None`` would mean the
    # candidate row has been deleted between the 404 check above and the summary
    # read; that race surfaces as 500 deliberately.
    summary = fetch_candidate_summary(conn, candidate_id, detail_row["name"], selected_cycle)
    if summary is None:
        raise HTTPException(status_code=500, detail="Candidate summary unavailable")
    return CandidateFundraisingSummary.model_validate(summary)


@router.get(
    "/candidates/{candidate_id}/independent-expenditures",
    response_model=list[IndependentExpenditureResponse],
)
def get_candidate_independent_expenditures(
    candidate_id: UUID,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    selected_cycle: SelectedCycle = Depends(_selected_cycle_dependency),
    conn: psycopg.Connection = Depends(get_db),
) -> list[IndependentExpenditureResponse]:
    _fetch_row_or_404(conn, CAMPAIGN_FINANCE_CANDIDATE_DETAIL_SQL, candidate_id, "Candidate not found")

    ie_rows = fetch_candidate_ie_transactions(
        conn, candidate_id, limit=limit, offset=offset, selected_cycle=selected_cycle
    )
    return [IndependentExpenditureResponse.model_validate(ie_row) for ie_row in ie_rows]


@router.get(
    "/candidates/{candidate_id}/independent-expenditures/summary",
    response_model=IndependentExpenditureSummary,
)
def get_candidate_independent_expenditures_summary(
    candidate_id: UUID,
    selected_cycle: SelectedCycle = Depends(_selected_cycle_dependency),
    conn: psycopg.Connection = Depends(get_db),
) -> IndependentExpenditureSummary:
    _fetch_row_or_404(conn, CAMPAIGN_FINANCE_CANDIDATE_DETAIL_SQL, candidate_id, "Candidate not found")

    return IndependentExpenditureSummary.model_validate(
        fetch_candidate_ie_summary(conn, candidate_id, selected_cycle=selected_cycle)
    )


@router.get("/campaign-finance/states/summary")
def get_campaign_finance_state_summary() -> None:
    raise HTTPException(status_code=410, detail=_STATE_CAMPAIGN_FINANCE_RETIRED_DETAIL)


@router.get("/campaign-finance/states/{state_code}")
def get_campaign_finance_state_detail(
    state_code: str = Path(pattern=r"^[A-Z]{2}$"),
) -> None:
    validated_state_code = validate_optional_state_code(state_code, field_name="state_code")
    if validated_state_code is None:
        raise HTTPException(status_code=404, detail="State not found")
    raise HTTPException(status_code=410, detail=_STATE_CAMPAIGN_FINANCE_RETIRED_DETAIL)


@router.get(
    "/committees/{committee_id}/independent-expenditures-made",
    response_model=CommitteeIndependentExpenditureActivity,
)
def get_committee_independent_expenditures_made(
    committee_id: UUID,
    limit: int = Query(default=10, ge=1, le=100),
    conn: psycopg.Connection = Depends(get_db),
) -> CommitteeIndependentExpenditureActivity:
    _fetch_row_or_404(conn, CAMPAIGN_FINANCE_COMMITTEE_DETAIL_SQL, committee_id, "Committee not found")
    return CommitteeIndependentExpenditureActivity.model_validate(
        fetch_committee_ie_activity(conn, committee_id, limit)
    )
