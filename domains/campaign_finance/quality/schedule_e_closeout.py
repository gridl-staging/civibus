"""
Stub summary for mar22_pm_01_seo_landing_pages_and_slug_routing/civibus_dev/domains/campaign_finance/quality/schedule_e_closeout.py.
"""

from __future__ import annotations

from uuid import UUID

import psycopg

from domains.campaign_finance.quality.checks import (
    check_duplicate_records,
    check_raw_field_null_rate,
    check_source_count,
)
from domains.campaign_finance.quality.models import (
    CheckResult,
    JurisdictionSummary,
    QualityReport,
)
from domains.campaign_finance.quality.reconciliation import count_source_records
from domains.campaign_finance.quality.schedule_e_closeout_models import (
    ScheduleECloseoutEvidence,
)

_SOURCE_KEY_PREFIX = "schedule_e:"
_JURISDICTION = "federal/fec"

# Schedule E raw_fields keys to check for null rates (CSV-native names)
_NULL_RATE_FIELDS = ("sup_opp", "exp_amo", "cand_id")


def _run_schedule_e_checks(
    conn: psycopg.Connection,
    data_source_id: UUID,
) -> list[CheckResult]:
    ds_name = _JURISDICTION
    prefix = _SOURCE_KEY_PREFIX

    results: list[CheckResult] = []

    # Source record count — at least 1 schedule_e record must exist
    results.append(
        check_source_count(
            conn,
            data_source_id,
            ds_name,
            source_key_prefix=prefix,
            check_name="schedule_e_source_count",
        )
    )

    # Duplicate hashes within the schedule_e subset
    results.append(
        check_duplicate_records(
            conn,
            data_source_id,
            ds_name,
            source_key_prefix=prefix,
            check_name="schedule_e_duplicate_records",
        )
    )

    # Null rate on critical raw_fields keys
    for field in _NULL_RATE_FIELDS:
        results.append(
            check_raw_field_null_rate(
                conn,
                data_source_id,
                ds_name,
                field,
                source_key_prefix=prefix,
                check_name=f"schedule_e_null_rate_{field}",
            )
        )

    return results


def run_schedule_e_closeout(
    conn: psycopg.Connection,
    data_source_id: UUID,
    cycle: int,
) -> ScheduleECloseoutEvidence:
    check_results = _run_schedule_e_checks(conn, data_source_id)
    record_count = count_source_records(
        conn,
        data_source_id,
        source_key_prefix=_SOURCE_KEY_PREFIX,
    )

    quality_report = QualityReport(
        jurisdiction_filter=_JURISDICTION,
        summaries=[
            JurisdictionSummary(
                jurisdiction=_JURISDICTION,
                data_source_ids=[str(data_source_id)],
                record_count=record_count,
                check_results=check_results,
            )
        ],
    )

    return ScheduleECloseoutEvidence(
        cycle=cycle,
        data_source_id=str(data_source_id),
        source_record_count=record_count,
        quality_report=quality_report,
    )
