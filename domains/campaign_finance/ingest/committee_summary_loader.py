
from __future__ import annotations

from collections.abc import Mapping
import logging
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg

from core.db import try_insert_source_record
from core.types.python.models import SourceRecord, compute_record_hash, utc_now
from domains.campaign_finance.ingest.bulk_stage4_loader import LoadResult
from domains.campaign_finance.ingest.committee_summary_parser import read_committee_summary_file
from domains.campaign_finance.ingest.fec_lookup import find_committee_id_by_fec_id
from domains.campaign_finance.ingest.schedule_loader_common import (
    json_compatible_raw_fields,
    validate_batch_size,
)
from domains.campaign_finance.ingest.text_utils import normalize_optional_text
from domains.campaign_finance.types.models import CommitteeSummary

LOGGER = logging.getLogger(__name__)

_COMMITTEE_SUMMARY_ROW_SAVEPOINT = "committee_summary_row"

_COMMITTEE_SUMMARY_FIELD_MAP: tuple[tuple[str, str], ...] = (
    ("Link_Image", "link_image"),
    ("CMTE_NM", "committee_name"),
    ("CMTE_TP", "committee_type"),
    ("CMTE_DSGN", "committee_designation"),
    ("CMTE_FILING_FREQ", "committee_filing_frequency"),
    ("CMTE_ST1", "committee_street_1"),
    ("CMTE_ST2", "committee_street_2"),
    ("CMTE_CITY", "committee_city"),
    ("CMTE_ST", "committee_state"),
    ("CMTE_ZIP", "committee_zip"),
    ("TRES_NM", "treasurer_name"),
    ("INDV_CONTB", "individual_contributions"),
    ("PTY_CMTE_CONTB", "party_committee_contributions"),
    ("OTH_CMTE_CONTB", "other_committee_contributions"),
    ("TTL_CONTB", "total_contributions"),
    ("TRANF_FROM_OTHER_AUTH_CMTE", "transfers_from_other_authorized_committees"),
    ("OFFSETS_TO_OP_EXP", "offsets_to_operating_expenditures"),
    ("OTHER_RECEIPTS", "other_receipts"),
    ("TTL_RECEIPTS", "total_receipts"),
    ("TRANF_TO_OTHER_AUTH_CMTE", "transfers_to_other_authorized_committees"),
    ("OTH_LOAN_REPYMTS", "other_loan_repayments"),
    ("INDV_REF", "individual_refunds"),
    ("POL_PTY_CMTE_REF", "political_party_committee_refunds"),
    ("TTL_CONTB_REF", "total_contribution_refunds"),
    ("OTHER_DISB", "other_disbursements"),
    ("TTL_DISB", "total_disbursements"),
    ("NET_CONTB", "net_contributions"),
    ("NET_OP_EXP", "net_operating_expenditures"),
    ("COH_BOP", "cash_on_hand_beginning_of_period"),
    ("CVG_START_DT", "coverage_start_date"),
    ("COH_COP", "cash_on_hand"),
    ("CVG_END_DT", "coverage_end_date"),
    ("DEBTS_OWED_BY_CMTE", "debts_owed_by_committee"),
    ("DEBTS_OWED_TO_CMTE", "debts_owed_to_committee"),
    ("INDV_ITEM_CONTB", "individual_itemized_contributions"),
    ("INDV_UNITEM_CONTB", "individual_unitemized_contributions"),
    ("OTH_LOANS", "other_loans"),
    ("TRANF_FROM_NONFED_ACCT", "transfers_from_nonfederal_account"),
    ("TRANF_FROM_NONFED_LEVIN", "transfers_from_nonfederal_levin"),
    ("TTL_NONFED_TRANF", "total_nonfederal_transfers"),
    ("LOAN_REPYMTS_RECEIVED", "loan_repayments_received"),
    ("OFFSETS_TO_FNDRSG", "offsets_to_fundraising"),
    ("OFFSETS_TO_LEGAL_ACCTG", "offsets_to_legal_accounting"),
    ("FED_CAND_CONTB_REF", "federal_candidate_contribution_refunds"),
    ("TTL_FED_RECEIPTS", "total_federal_receipts"),
    ("SHARED_FED_OP_EXP", "shared_federal_operating_expenditures"),
    ("SHARED_NONFED_OP_EXP", "shared_nonfederal_operating_expenditures"),
    ("OTHER_FED_OP_EXP", "other_federal_operating_expenditures"),
    ("TTL_OP_EXP", "total_operating_expenditures"),
    ("FED_CAND_CMTE_CONTB", "federal_candidate_committee_contributions"),
    ("INDT_EXP", "independent_expenditures"),
    ("COORD_EXP_BY_PTY_CMTE", "coordinated_expenditures_by_party_committee"),
    ("LOANS_MADE", "loans_made"),
    ("SHARED_FED_ACTVY_FED_SHR", "shared_federal_activity_federal_share"),
    ("SHARED_FED_ACTVY_NONFED", "shared_federal_activity_nonfederal"),
    ("NON_ALLOC_FED_ELECT_ACTVY", "nonallocated_federal_election_activity"),
    ("TTL_FED_ELECT_ACTVY", "total_federal_election_activity"),
    ("TTL_FED_DISB", "total_federal_disbursements"),
    ("CAND_CNTB", "candidate_contributions"),
    ("CAND_LOAN", "candidate_loans"),
    ("TTL_LOANS", "total_loans"),
    ("OP_EXP", "operating_expenditures"),
    ("CAND_LOAN_REPYMNT", "candidate_loan_repayments"),
    ("TTL_LOAN_REPYMTS", "total_loan_repayments"),
    ("OTH_CMTE_REF", "other_committee_refunds"),
    ("TTL_OFFSETS_TO_OP_EXP", "total_offsets_to_operating_expenditures"),
    ("EXEMPT_LEGAL_ACCTG_DISB", "exempt_legal_accounting_disbursements"),
    ("FNDRSG_DISB", "fundraising_disbursements"),
    ("ITEM_REF_REB_RET", "itemized_refunds_rebates_returns"),
    ("SUBTTL_REF_REB_RET", "subtotal_refunds_rebates_returns"),
    ("UNITEM_REF_REB_RET", "unitemized_refunds_rebates_returns"),
    ("ITEM_OTHER_REF_REB_RET", "itemized_other_refunds_rebates_returns"),
    ("UNITEM_OTHER_REF_REB_RET", "unitemized_other_refunds_rebates_returns"),
    ("SUBTTL_OTHER_REF_REB_RET", "subtotal_other_refunds_rebates_returns"),
    ("ITEM_OTHER_INCOME", "itemized_other_income"),
    ("UNITEM_OTHER_INCOME", "unitemized_other_income"),
    ("EXP_PRIOR_YRS_SUBJECT_LIM", "expenditures_prior_years_subject_to_limits"),
    ("EXP_SUBJECT_LIMITS", "expenditures_subject_to_limits"),
    ("FED_FUNDS", "federal_funds"),
    ("ITEM_CONVN_EXP_DISB", "itemized_convention_expenditures_disbursements"),
    ("ITEM_OTHER_DISB", "itemized_other_disbursements"),
    ("SUBTTL_CONVN_EXP_DISB", "subtotal_convention_expenditures_disbursements"),
    ("TTL_EXP_SUBJECT_LIMITS", "total_expenditures_subject_to_limits"),
    ("UNITEM_CONVN_EXP_DISB", "unitemized_convention_expenditures_disbursements"),
    ("UNITEM_OTHER_DISB", "unitemized_other_disbursements"),
    ("TTL_COMMUNICATION_COST", "total_communication_cost"),
    ("COH_BOY", "cash_on_hand_beginning_of_year"),
    ("COH_COY", "cash_on_hand_close_of_year"),
)

_COMMITTEE_SUMMARY_TABLE_COLUMNS: tuple[str, ...] = (
    "committee_id",
    "cycle",
    *[field_name for _, field_name in _COMMITTEE_SUMMARY_FIELD_MAP],
    "source_record_id",
)
_COMMITTEE_SUMMARY_UPDATE_COLUMNS: tuple[str, ...] = tuple(
    column for column in _COMMITTEE_SUMMARY_TABLE_COLUMNS if column not in {"committee_id", "cycle"}
)
_COMMITTEE_SUMMARY_INSERT_COLUMNS_SQL = ", ".join(_COMMITTEE_SUMMARY_TABLE_COLUMNS)
_COMMITTEE_SUMMARY_PLACEHOLDERS_SQL = ", ".join(["%s"] * len(_COMMITTEE_SUMMARY_TABLE_COLUMNS))
_COMMITTEE_SUMMARY_UPDATE_SQL = ", ".join(
    f"{column} = EXCLUDED.{column}" for column in _COMMITTEE_SUMMARY_UPDATE_COLUMNS
)
_UPSERT_COMMITTEE_SUMMARY_SQL = f"""
    INSERT INTO cf.committee_summary (
        {_COMMITTEE_SUMMARY_INSERT_COLUMNS_SQL}
    )
    VALUES (
        {_COMMITTEE_SUMMARY_PLACEHOLDERS_SQL}
    )
    ON CONFLICT (committee_id, cycle)
    DO UPDATE SET
        {_COMMITTEE_SUMMARY_UPDATE_SQL},
        updated_at = NOW()
"""


def _require_committee_fec_id(row: Mapping[str, object]) -> str:
    committee_fec_id = normalize_optional_text(row.get("CMTE_ID"))
    if committee_fec_id is None:
        raise ValueError("CMTE_ID is required for committee summary ingest")
    return committee_fec_id


def _source_record_key(*, cycle: int, committee_fec_id: str) -> str:
    return f"committee_summary:{cycle}:{committee_fec_id}"


def _try_insert_committee_summary_source_record(
    conn: psycopg.Connection,
    *,
    cycle: int,
    data_source_id: UUID,
    row: Mapping[str, object],
) -> tuple[str, UUID | None]:
    committee_fec_id = _require_committee_fec_id(row)
    source_record_key = _source_record_key(cycle=cycle, committee_fec_id=committee_fec_id)
    raw_fields = json_compatible_raw_fields(row)
    source_record_id = try_insert_source_record(
        conn,
        SourceRecord(
            data_source_id=data_source_id,
            source_record_key=source_record_key,
            raw_fields=raw_fields,
            pull_date=utc_now(),
            record_hash=compute_record_hash(raw_fields),
        ),
    )
    return source_record_key, source_record_id


def _build_committee_summary(
    *,
    row: Mapping[str, object],
    committee_id: UUID,
    cycle: int,
    source_record_id: UUID,
) -> CommitteeSummary:
    model_fields: dict[str, Any] = {
        "committee_id": committee_id,
        "cycle": cycle,
        "source_record_id": source_record_id,
    }
    model_fields.update({field_name: row.get(column_name) for column_name, field_name in _COMMITTEE_SUMMARY_FIELD_MAP})
    return CommitteeSummary(**model_fields)


def _upsert_committee_summary(conn: psycopg.Connection, summary: CommitteeSummary) -> None:
    summary_values = summary.model_dump()
    params = tuple(summary_values[column] for column in _COMMITTEE_SUMMARY_TABLE_COLUMNS)
    with conn.cursor() as cursor:
        cursor.execute(_UPSERT_COMMITTEE_SUMMARY_SQL, params)


def _commit_batch(conn: psycopg.Connection, processed_since_commit: int, batch_size: int) -> int:
    if processed_since_commit >= batch_size:
        conn.commit()
        return 0
    return processed_since_commit


def _commit_final_batch(conn: psycopg.Connection, processed_since_commit: int) -> None:
    if processed_since_commit > 0:
        conn.commit()


def load_committee_summaries(
    conn: psycopg.Connection,
    path: str | Path,
    *,
    cycle: int,
    data_source_id: UUID,
    batch_size: int = 1000,
    limit: int | None = None,
) -> LoadResult:
    """Load official FEC committee summary rows for committees already present in ``cf.committee``."""
    validate_batch_size(batch_size)

    result = LoadResult()
    processed_since_commit = 0

    for row in read_committee_summary_file(path, limit=limit):
        processed_since_commit += 1
        with conn.cursor() as cursor:
            cursor.execute(f"SAVEPOINT {_COMMITTEE_SUMMARY_ROW_SAVEPOINT}")
            try:
                committee_fec_id = _require_committee_fec_id(row)
                committee_id = find_committee_id_by_fec_id(conn, committee_fec_id)
                if committee_id is None:
                    LOGGER.warning(
                        "Skipping committee summary row for missing committee CMTE_ID=%s",
                        committee_fec_id,
                    )
                    result.skipped += 1
                    cursor.execute(f"ROLLBACK TO SAVEPOINT {_COMMITTEE_SUMMARY_ROW_SAVEPOINT}")
                    cursor.execute(f"RELEASE SAVEPOINT {_COMMITTEE_SUMMARY_ROW_SAVEPOINT}")
                    processed_since_commit = _commit_batch(conn, processed_since_commit, batch_size)
                    continue

                _, source_record_id = _try_insert_committee_summary_source_record(
                    conn,
                    cycle=cycle,
                    data_source_id=data_source_id,
                    row=row,
                )
                if source_record_id is None:
                    result.skipped += 1
                    cursor.execute(f"ROLLBACK TO SAVEPOINT {_COMMITTEE_SUMMARY_ROW_SAVEPOINT}")
                    cursor.execute(f"RELEASE SAVEPOINT {_COMMITTEE_SUMMARY_ROW_SAVEPOINT}")
                    processed_since_commit = _commit_batch(conn, processed_since_commit, batch_size)
                    continue

                summary = _build_committee_summary(
                    row=row,
                    committee_id=committee_id,
                    cycle=cycle,
                    source_record_id=source_record_id,
                )
                _upsert_committee_summary(conn, summary)
                result.inserted += 1
            except Exception:
                result.errors += 1
                cursor.execute(f"ROLLBACK TO SAVEPOINT {_COMMITTEE_SUMMARY_ROW_SAVEPOINT}")
                cursor.execute(f"RELEASE SAVEPOINT {_COMMITTEE_SUMMARY_ROW_SAVEPOINT}")
                LOGGER.exception("Failed to load committee summary row")
                processed_since_commit = _commit_batch(conn, processed_since_commit, batch_size)
                continue

            cursor.execute(f"RELEASE SAVEPOINT {_COMMITTEE_SUMMARY_ROW_SAVEPOINT}")
        processed_since_commit = _commit_batch(conn, processed_since_commit, batch_size)

    _commit_final_batch(conn, processed_since_commit)
    return result


__all__ = ["load_committee_summaries"]
