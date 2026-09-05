"""Refresh job assembly: config discovery, job construction, and plan building."""

from __future__ import annotations

import shutil
import tempfile
import zipfile
from dataclasses import replace
from datetime import date
from collections.abc import Iterator
import os
from pathlib import Path
from typing import Callable
from urllib.request import urlretrieve

from core.db import get_connection
from core.people.enrichment.orchestrator import FEDERAL_ENRICHMENT_DATA_SOURCE_NAME, run_federal_enrichment
from core.refresh import donor_rollup
from core.refresh.runner import (
    _REPO_ROOT,
    RefreshJob,
    RunnerParameters,
    _resolve_now,
)
from domains.campaign_finance.ingest.bulk_cli import (
    CliConfig,
    LoadRequest,
    dispatch_load,
)
from domains.campaign_finance.ingest.fec_bulk_files import (
    download_fec_bulk_file_to_cache,
    fec_baseline_url,
    fec_committee_summary_url,
    fec_schedule_b_url,
    fec_schedule_e_url,
    fec_weball_url,
)
from domains.campaign_finance.ingest.bulk_loader import (
    FEC_BULK_DATA_SOURCE_NAME,
    ensure_fec_bulk_data_source,
)
from domains.campaign_finance.constants import FILING_BREAKDOWN_STORE_LIMIT as _FILING_BREAKDOWN_STORE_LIMIT
from domains.campaign_finance.ingest.congress_legislators_adapter import (
    adapt_legislators_yaml,
    fetch_historical_entries,
    fetch_legislators_entries,
    select_most_recent_vacancy_predecessors,
)
from domains.campaign_finance.ingest.dark_money.download import (
    download_irs_527_full_data,
    extract_irs_527_txt,
)
from domains.campaign_finance.ingest.dark_money.loader import (
    _IRS_527_DATA_SOURCE_NAME,
    ensure_irs_527_data_source,
    load_irs_527_records,
)
from domains.campaign_finance.ingest.federal_spine_loader import (
    FEDERAL_SPINE_DATA_SOURCE_NAME,
    ensure_federal_spine_data_source,
    load_federal_spine,
    load_vacancy_predecessors,
)
from domains.campaign_finance.jurisdictions.config_schema import JurisdictionConfig
from domains.campaign_finance.jurisdictions.refresh_registry import (
    JURISDICTION_REFRESH_REGISTRATIONS,
    build_registered_refresh_jobs,
    load_validated_refresh_registrations,
)
from domains.civics.loaders.ncsbe_candidate_listing import _NCSBE_DATA_SOURCE_NAME
from domains.civics.loaders.ncsbe_results import (
    collect_ncsbe_refresh_data_source_names,
    run_ncsbe_results_refresh_2022_2024,
)
from domains.civics.loaders.federal_fec_races import (
    FEDERAL_FEC_RACES_DATA_SOURCE_NAME,
    ensure_federal_fec_races_data_source,
    load_federal_fec_races,
)
from domains.civics.loaders.zcta_district_loader import (
    TIGER_CD_LISTING_DATA_SOURCE_NAME,
    probe_tiger_congressional_district_listing,
)
from domains.civics.loaders.official_rosters.source_templates import civic_roster_refresh_templates
from domains.civics.loaders.official_rosters.cli import main as run_official_roster_cli
from domains.civics.loaders.official_rosters.source_registry import list_nc_roster_source_metadata

from datetime import datetime
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

_PRIORITY_CADENCE = "daily"
_COMMITTEE_SUMMARY_FILING_BATCH_SIZE = 500
_REFRESH_DATA_DIR_ENV = "CIVIBUS_REFRESH_DATA_DIR"
_SUPPORTED_REFRESH_SCOPES = {"all", "priority", "federal"}
_FEDERAL_SCOPE_JOB_KEY_PREFIXES = ("federal-",)
_PARKED_WEEKLY_FEDERAL_JOB_KEYS = frozenset({"federal-irs-527"})


class _ComputedElectionDatesClient:
    """Election-date client that activates the races loader's deterministic fallback."""

    def fetch_election_dates(self, **_filters: object) -> list[dict]:
        return []


_PRIORITY_STATE_TRANSACTION_TYPES: dict[str, frozenset[str]] = {
    "AL": frozenset({"contributions", "expenditures"}),
    "CA": frozenset({"contributions", "expenditures"}),
    "CO": frozenset({"contributions", "expenditures"}),
    "GA": frozenset({"contributions", "expenditures"}),
    "KY": frozenset({"contributions", "expenditures"}),
    "LA": frozenset({"contributions", "expenditures", "loans"}),
    "NE": frozenset({"contributions", "expenditures", "loans"}),
    "OR": frozenset({"contributions", "expenditures"}),
    "TX": frozenset({"contributions", "expenditures", "loans"}),
}


def _refresh_data_root() -> Path:
    configured_data_dir = os.environ.get(_REFRESH_DATA_DIR_ENV)
    if configured_data_dir:
        return Path(configured_data_dir)
    return _REPO_ROOT / "data"


def _temporary_refresh_directory(*, prefix: str) -> tempfile.TemporaryDirectory[str]:
    temp_root = _refresh_data_root() / "tmp"
    temp_root.mkdir(parents=True, exist_ok=True)
    return tempfile.TemporaryDirectory(prefix=prefix, dir=temp_root)


def _filter_weekly_federal_scope_jobs(
    jobs: list[RefreshJob],
    *,
    job_key_prefixes: tuple[str, ...],
) -> list[RefreshJob]:
    federal_jobs = _filter_jobs_by_key_prefixes(jobs, job_key_prefixes=_FEDERAL_SCOPE_JOB_KEY_PREFIXES)
    if job_key_prefixes:
        return federal_jobs
    return [job for job in federal_jobs if job.key not in _PARKED_WEEKLY_FEDERAL_JOB_KEYS]


def _build_official_roster_run_callable(source_id: str) -> Callable[[], object]:
    def _run_official_roster_job() -> object:
        exit_code = run_official_roster_cli(["--source-id", source_id])
        if exit_code != 0:
            raise RuntimeError(f"Official roster job failed for source_id={source_id} with exit_code={exit_code}")
        return exit_code

    return _run_official_roster_job


def _build_official_roster_jobs() -> list[RefreshJob]:
    jobs: list[RefreshJob] = []
    for source in list_nc_roster_source_metadata():
        jobs.append(
            RefreshJob(
                key=f"civics-roster-{source.source_id}",
                domain="civics",
                jurisdiction=source.jurisdiction,
                cadence=source.cadence,
                data_source_names=(source.name,),
                run_callable=_build_official_roster_run_callable(source.source_id),
            )
        )
    return jobs


def _active_fec_transaction_cycles(fec_cycle: int) -> tuple[int, ...]:
    previous_cycle = fec_cycle - 2
    if previous_cycle < 2024:
        return (fec_cycle,)
    return (previous_cycle, fec_cycle)


def _build_fec_job(parameters: RunnerParameters) -> RefreshJob:
    cycles = _active_fec_transaction_cycles(parameters.fec_cycle)

    def _run_fec_schedule_a_job() -> list[object]:
        download_paths: list[tuple[int, Path]] = []
        for cycle in cycles:
            archive_path = download_fec_bulk_file_to_cache(
                _REPO_ROOT,
                cycle=cycle,
                file_type="itcont",
                data_root=_refresh_data_root(),
                downloader=urlretrieve,
            )
            download_paths.append((cycle, archive_path))

        connection = get_connection()
        try:
            with connection.transaction():
                data_source_id = ensure_fec_bulk_data_source(connection)
            results: list[object] = []
            for cycle, archive_path in download_paths:
                results.append(
                    dispatch_load(
                        conn=connection,
                        config=CliConfig(
                            mode="single",
                            cycle=cycle,
                            file_type="itcont",
                            path=archive_path,
                            directory=None,
                            batch_size=1000,
                            limit=parameters.fec_limit,
                            graph_enabled=False,
                            with_transactions=False,
                            transactions_only=True,
                            spine_only=True,
                            min_date=date(2022, 1, 1),
                        ),
                        request=LoadRequest(file_type="itcont", path=archive_path),
                        data_source_id=data_source_id,
                    )
                )
            return results[0] if len(results) == 1 else results
        finally:
            connection.close()

    return RefreshJob(
        key="federal-fec-schedule-a",
        domain="campaign_finance",
        jurisdiction="federal/fec",
        cadence="continuous",
        data_source_names=(FEC_BULK_DATA_SOURCE_NAME,),
        run_callable=_run_fec_schedule_a_job,
    )


def _build_fec_masters_job(parameters: RunnerParameters) -> RefreshJob:
    file_types = ("cm", "cn", "ccl", "weball")
    cycles = _active_committee_summary_cycles(parameters.fec_cycle)

    def _fec_masters_url(cycle: int, file_type: str) -> str:
        if file_type == "weball":
            return fec_weball_url(cycle)
        return fec_baseline_url(cycle, file_type)

    def _run_fec_masters_job() -> list[object]:
        with _temporary_refresh_directory(prefix="refresh-fec-masters-") as temp_dir:
            temp_dir_path = Path(temp_dir)
            download_paths: list[tuple[int, str, Path]] = []
            for cycle in cycles:
                cycle_suffix = str(cycle)[-2:]
                for file_type in file_types:
                    archive_path = temp_dir_path / f"{file_type}{cycle_suffix}.zip"
                    urlretrieve(_fec_masters_url(cycle, file_type), archive_path)
                    download_paths.append((cycle, file_type, archive_path))

            connection = get_connection()
            try:
                with connection.transaction():
                    data_source_id = ensure_fec_bulk_data_source(connection)

                results: list[object] = []
                for cycle, file_type, archive_path in download_paths:
                    results.append(
                        dispatch_load(
                            conn=connection,
                            config=CliConfig(
                                mode="single",
                                cycle=cycle,
                                file_type=file_type,
                                path=archive_path,
                                directory=None,
                                batch_size=1000,
                                limit=None,
                                graph_enabled=False,
                                with_transactions=False,
                            ),
                            request=LoadRequest(file_type=file_type, path=archive_path),
                            data_source_id=data_source_id,
                        )
                    )
                return results
            finally:
                connection.close()

    return RefreshJob(
        key="federal-fec-masters",
        domain="campaign_finance",
        jurisdiction="federal/fec",
        cadence="weekly",
        data_source_names=(FEC_BULK_DATA_SOURCE_NAME,),
        run_callable=_run_fec_masters_job,
        refresh_history_key="federal-fec-masters",
        side_effects_repaired_by_job_key="federal-congress-spine",
    )


def _active_committee_summary_cycles(fec_cycle: int) -> tuple[int, ...]:
    first_recent_cycle = 2022
    if fec_cycle <= first_recent_cycle + 2:
        return (fec_cycle,)
    cycles = tuple(range(first_recent_cycle, fec_cycle + 1, 2))
    return cycles or (fec_cycle,)


_COMMITTEE_SUMMARY_DERIVED_AGGREGATE_SQL = """
    WITH target_summaries AS (
        SELECT
            cs.committee_id,
            cs.cycle,
            MAKE_DATE(cs.cycle - 1, 1, 1) AS cycle_start_date,
            MAKE_DATE(cs.cycle, 12, 31) AS cycle_end_date
        FROM cf.committee_summary cs
        WHERE cs.cycle = ANY(%s)
          AND (%s::uuid[] IS NULL OR cs.committee_id = ANY(%s::uuid[]))
    ),
    eligible_transactions AS MATERIALIZED (
        SELECT
            ts.committee_id,
            ts.cycle,
            t.id,
            t.transaction_type,
            t.amount,
            t.contributor_name_raw,
            t.memo_text,
            sr.pull_date,
            ds.jurisdiction
        FROM target_summaries ts
        JOIN cf.transaction t
          ON t.committee_id = ts.committee_id
         AND t.transaction_date >= ts.cycle_start_date
         AND t.transaction_date <= ts.cycle_end_date
         AND t.is_memo = FALSE
         AND t.amendment_indicator != 'T'
        LEFT JOIN core.source_record sr
          ON sr.id = t.source_record_id
        LEFT JOIN core.data_source ds
          ON ds.id = sr.data_source_id
        WHERE t.source_record_id IS NULL
           OR sr.superseded_by IS NULL
    ),
    donor_groups AS (
        SELECT
            committee_id,
            cycle,
            BTRIM(contributor_name_raw) AS name,
            SUM(amount) AS total_amount,
            COUNT(id)::integer AS transaction_count
        FROM eligible_transactions
        WHERE transaction_type LIKE '1%%'
          AND contributor_name_raw IS NOT NULL
          AND BTRIM(contributor_name_raw) != ''
        GROUP BY committee_id, cycle, BTRIM(contributor_name_raw)
    ),
    ranked_donors AS (
        SELECT
            committee_id,
            cycle,
            name,
            total_amount,
            transaction_count,
            ROW_NUMBER() OVER (
                PARTITION BY committee_id, cycle
                ORDER BY total_amount DESC, transaction_count DESC, name ASC
            ) AS top_rank
        FROM donor_groups
    ),
    top_donors AS (
        SELECT
            committee_id,
            cycle,
            JSONB_AGG(
                JSONB_BUILD_OBJECT(
                    'name', name,
                    'total_amount', total_amount::text,
                    'transaction_count', transaction_count
                )
                ORDER BY total_amount DESC, transaction_count DESC, name ASC
            ) AS top_donors
        FROM ranked_donors
        WHERE top_rank <= 5
        GROUP BY committee_id, cycle
    ),
    vendor_groups AS (
        SELECT
            committee_id,
            cycle,
            BTRIM(contributor_name_raw) AS name,
            SUM(amount) AS total_amount,
            COUNT(id)::integer AS transaction_count
        FROM eligible_transactions
        WHERE transaction_type LIKE '2%%'
          AND contributor_name_raw IS NOT NULL
          AND BTRIM(contributor_name_raw) != ''
        GROUP BY committee_id, cycle, BTRIM(contributor_name_raw)
    ),
    ranked_vendors AS (
        SELECT
            committee_id,
            cycle,
            name,
            total_amount,
            transaction_count,
            ROW_NUMBER() OVER (
                PARTITION BY committee_id, cycle
                ORDER BY total_amount DESC, transaction_count DESC, name ASC
            ) AS top_rank
        FROM vendor_groups
    ),
    top_vendors AS (
        SELECT
            committee_id,
            cycle,
            JSONB_AGG(
                JSONB_BUILD_OBJECT(
                    'name', name,
                    'total_amount', total_amount::text,
                    'transaction_count', transaction_count
                )
                ORDER BY total_amount DESC, transaction_count DESC, name ASC
            ) AS top_vendors
        FROM ranked_vendors
        WHERE top_rank <= 5
        GROUP BY committee_id, cycle
    ),
    spend_category_groups AS (
        SELECT
            committee_id,
            cycle,
            LOWER(BTRIM(memo_text)) AS category,
            SUM(amount) AS total_amount,
            COUNT(id)::integer AS transaction_count
        FROM eligible_transactions
        WHERE transaction_type LIKE '2%%'
          AND memo_text IS NOT NULL
          AND BTRIM(memo_text) != ''
        GROUP BY committee_id, cycle, LOWER(BTRIM(memo_text))
    ),
    ranked_spend_categories AS (
        SELECT
            committee_id,
            cycle,
            category,
            total_amount,
            transaction_count,
            ROW_NUMBER() OVER (
                PARTITION BY committee_id, cycle
                ORDER BY total_amount DESC, transaction_count DESC, category ASC
            ) AS top_rank
        FROM spend_category_groups
    ),
    top_spend_categories AS (
        SELECT
            committee_id,
            cycle,
            JSONB_AGG(
                JSONB_BUILD_OBJECT(
                    'category', category,
                    'total_amount', total_amount::text,
                    'transaction_count', transaction_count
                )
                ORDER BY total_amount DESC, transaction_count DESC, category ASC
            ) AS spend_categories
        FROM ranked_spend_categories
        WHERE top_rank <= 5
        GROUP BY committee_id, cycle
    ),
    aggregates AS (
        SELECT
            committee_id,
            cycle,
            COALESCE(SUM(amount) FILTER (WHERE transaction_type LIKE '1%%'), 0) AS total_raised,
            COALESCE(SUM(amount) FILTER (WHERE transaction_type LIKE '2%%'), 0) AS total_spent,
            COALESCE(SUM(amount) FILTER (WHERE transaction_type LIKE '1%%'), 0)
              - COALESCE(SUM(amount) FILTER (WHERE transaction_type LIKE '2%%'), 0) AS net,
            COUNT(id)::integer AS transaction_count,
            COALESCE(SUM(amount) FILTER (
                WHERE transaction_type LIKE '1%%'
                  AND transaction_type LIKE '16%%'
            ), 0) AS loan_receipts_total,
            COALESCE(SUM(amount) FILTER (WHERE transaction_type = '15Z'), 0) AS in_kind_receipts_total,
            COALESCE(SUM(amount) FILTER (WHERE transaction_type LIKE '1%%'), 0)
              - COALESCE(SUM(amount) FILTER (
                    WHERE transaction_type LIKE '1%%'
                      AND transaction_type LIKE '16%%'
                ), 0) AS contribution_receipts_total,
            GREATEST(
                COALESCE(SUM(amount) FILTER (WHERE transaction_type LIKE '1%%'), 0)
                - COALESCE(SUM(amount) FILTER (
                    WHERE transaction_type LIKE '1%%'
                      AND transaction_type LIKE '16%%'
                ), 0)
                - COALESCE(SUM(amount) FILTER (WHERE transaction_type = '15Z'), 0),
                0
            ) AS cash_receipts_total,
            (ARRAY_AGG(
                jurisdiction
                ORDER BY pull_date DESC NULLS LAST, id ASC
            ) FILTER (WHERE jurisdiction IS NOT NULL))[1] AS jurisdiction,
            MAX(pull_date) AS data_through
        FROM eligible_transactions
        GROUP BY committee_id, cycle
    ),
    aggregate_updates AS (
        SELECT
            ts.committee_id,
            ts.cycle,
            COALESCE(a.total_raised, 0) AS total_raised,
            COALESCE(a.total_spent, 0) AS total_spent,
            COALESCE(a.net, 0) AS net,
            COALESCE(a.transaction_count, 0) AS transaction_count,
            COALESCE(a.cash_receipts_total, 0) AS cash_receipts_total,
            COALESCE(a.in_kind_receipts_total, 0) AS in_kind_receipts_total,
            COALESCE(a.loan_receipts_total, 0) AS loan_receipts_total,
            COALESCE(a.contribution_receipts_total, 0) AS contribution_receipts_total,
            a.jurisdiction,
            a.data_through,
            COALESCE(td.top_donors, '[]'::jsonb) AS top_donors,
            COALESCE(tv.top_vendors, '[]'::jsonb) AS top_vendors,
            COALESCE(tsc.spend_categories, '[]'::jsonb) AS spend_categories
        FROM target_summaries ts
        LEFT JOIN aggregates a
          ON a.committee_id = ts.committee_id
         AND a.cycle = ts.cycle
        LEFT JOIN top_donors td
          ON td.committee_id = ts.committee_id
         AND td.cycle = ts.cycle
        LEFT JOIN top_vendors tv
          ON tv.committee_id = ts.committee_id
         AND tv.cycle = ts.cycle
        LEFT JOIN top_spend_categories tsc
          ON tsc.committee_id = ts.committee_id
         AND tsc.cycle = ts.cycle
    )
    UPDATE cf.committee_summary cs
    SET derived_total_raised = au.total_raised,
        derived_total_spent = au.total_spent,
        derived_net = au.net,
        derived_transaction_count = au.transaction_count,
        derived_cash_receipts_total = au.cash_receipts_total,
        derived_in_kind_receipts_total = au.in_kind_receipts_total,
        derived_loan_receipts_total = au.loan_receipts_total,
        derived_contribution_receipts_total = au.contribution_receipts_total,
        derived_jurisdiction = au.jurisdiction,
        derived_data_through = au.data_through,
        derived_top_donors = au.top_donors,
        derived_top_vendors = au.top_vendors,
        derived_spend_categories = au.spend_categories
    FROM aggregate_updates au
    WHERE cs.committee_id = au.committee_id
      AND cs.cycle = au.cycle
"""

_COMMITTEE_SUMMARY_TARGET_COMMITTEE_SQL = """
    SELECT DISTINCT cs.committee_id::text
    FROM cf.committee_summary cs
    WHERE cs.cycle = ANY(%s)
      AND (%s::uuid[] IS NULL OR cs.committee_id = ANY(%s::uuid[]))
    ORDER BY cs.committee_id::text
"""

_COMMITTEE_SUMMARY_FILING_BREAKDOWN_ROWS_SQL = """
    WITH target_committees AS (
        SELECT UNNEST(%s::uuid[]) AS committee_id
    ),
    filing_eligible_transactions AS MATERIALIZED (
        SELECT
            tc.committee_id,
            t.id,
            t.filing_id,
            t.transaction_type,
            t.amount
        FROM target_committees tc
        JOIN cf.transaction t
          ON t.committee_id = tc.committee_id
         AND t.is_memo = FALSE
         AND t.amendment_indicator != 'T'
        LEFT JOIN core.source_record sr
          ON sr.id = t.source_record_id
        WHERE t.source_record_id IS NULL
           OR sr.superseded_by IS NULL
    ),
    filing_totals AS (
        SELECT
            f.committee_id,
            f.id AS filing_id,
            f.filing_fec_id,
            f.filing_name,
            f.report_type,
            f.amendment_indicator,
            f.coverage_start_date,
            f.coverage_end_date,
            f.receipt_date,
            COALESCE(SUM(ft.amount) FILTER (WHERE ft.transaction_type LIKE '1%%'), 0) AS total_raised,
            COALESCE(SUM(ft.amount) FILTER (WHERE ft.transaction_type LIKE '2%%'), 0) AS total_spent,
            COALESCE(SUM(ft.amount) FILTER (WHERE ft.transaction_type LIKE '1%%'), 0)
              - COALESCE(SUM(ft.amount) FILTER (WHERE ft.transaction_type LIKE '2%%'), 0) AS net,
            COUNT(ft.id)::integer AS transaction_count
        FROM target_committees tc
        JOIN cf.filing f
          ON f.committee_id = tc.committee_id
        LEFT JOIN filing_eligible_transactions ft
          ON ft.filing_id = f.id
        GROUP BY
            f.committee_id,
            f.id,
            f.filing_fec_id,
            f.filing_name,
            f.report_type,
            f.amendment_indicator,
            f.coverage_start_date,
            f.coverage_end_date,
            f.receipt_date
    ),
    filing_cash_on_hand AS (
        SELECT
            ft.*,
            SUM(ft.net) OVER (
                PARTITION BY ft.committee_id
                ORDER BY
                    ft.coverage_end_date ASC NULLS LAST,
                    ft.receipt_date ASC NULLS LAST,
                    ft.filing_id ASC
                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
            ) AS cash_on_hand
        FROM filing_totals ft
    ),
    ranked_filing_cash_on_hand AS (
        SELECT
            fcoh.*,
            ROW_NUMBER() OVER (
                PARTITION BY fcoh.committee_id
                ORDER BY
                    fcoh.coverage_end_date DESC NULLS LAST,
                    fcoh.receipt_date DESC NULLS LAST,
                    fcoh.filing_id ASC
            ) AS filing_rank
        FROM filing_cash_on_hand fcoh
    )
    SELECT
        committee_id::text AS committee_id,
        filing_id::text AS filing_id,
        filing_fec_id,
        filing_name,
        report_type,
        amendment_indicator,
        coverage_start_date::text AS coverage_start_date,
        coverage_end_date::text AS coverage_end_date,
        receipt_date::text AS receipt_date,
        TO_CHAR(total_raised, 'FM999999999999990.00') AS total_raised,
        TO_CHAR(total_spent, 'FM999999999999990.00') AS total_spent,
        TO_CHAR(net, 'FM999999999999990.00') AS net,
        transaction_count,
        TO_CHAR(cash_on_hand, 'FM999999999999990.00') AS cash_on_hand,
        filing_id::text || ':' || amendment_indicator AS row_id,
        filing_rank
    FROM ranked_filing_cash_on_hand
    ORDER BY committee_id ASC, filing_rank ASC
"""

_COMMITTEE_SUMMARY_FILING_BREAKDOWN_UPDATE_SQL = """
    UPDATE cf.committee_summary
    SET derived_filing_breakdown = %s
    WHERE cycle = ANY(%s)
      AND committee_id = %s::uuid
"""
_COMMITTEE_SUMMARY_FILING_BREAKDOWN_CURSOR_NAME = "committee_summary_filing_breakdown_rows"


def _committee_summary_target_committee_ids(
    connection: object,
    *,
    cycles: tuple[int, ...],
    committee_ids: tuple[str, ...] | None,
) -> tuple[str, ...]:
    committee_id_list = None if committee_ids is None else list(committee_ids)
    with connection.cursor() as cursor:
        cursor.execute(
            _COMMITTEE_SUMMARY_TARGET_COMMITTEE_SQL,
            (list(cycles), committee_id_list, committee_id_list),
        )
        return tuple(row[0] for row in cursor.fetchall())


def _iter_committee_summary_filing_row_batches(
    connection: object,
    *,
    committee_ids: tuple[str, ...],
    filing_batch_size: int | None,
) -> Iterator[list[dict[str, object]]]:
    if not committee_ids:
        return
    effective_batch_size = _COMMITTEE_SUMMARY_FILING_BATCH_SIZE if filing_batch_size is None else filing_batch_size
    if effective_batch_size <= 0:
        raise ValueError("filing_batch_size must be greater than 0")
    with connection.cursor(name=_COMMITTEE_SUMMARY_FILING_BREAKDOWN_CURSOR_NAME, row_factory=dict_row) as cursor:
        cursor.execute(_COMMITTEE_SUMMARY_FILING_BREAKDOWN_ROWS_SQL, (list(committee_ids),))
        while batch := cursor.fetchmany(effective_batch_size):
            yield list(batch)


def _filing_breakdown_payloads_by_committee(
    filing_rows: list[dict[str, object]],
) -> dict[str, list[dict[str, object]]]:
    payloads: dict[str, list[dict[str, object]]] = {}
    for row in filing_rows:
        if row["filing_rank"] > _FILING_BREAKDOWN_STORE_LIMIT:  # type: ignore[operator]
            continue
        committee_id = str(row["committee_id"])
        payloads.setdefault(committee_id, []).append(
            {
                "filing_id": row["filing_id"],
                "filing_fec_id": row["filing_fec_id"],
                "filing_name": row["filing_name"],
                "report_type": row["report_type"],
                "amendment_indicator": row["amendment_indicator"],
                "coverage_start_date": row["coverage_start_date"],
                "coverage_end_date": row["coverage_end_date"],
                "receipt_date": row["receipt_date"],
                "total_raised": row["total_raised"],
                "total_spent": row["total_spent"],
                "net": row["net"],
                "transaction_count": row["transaction_count"],
                "cash_on_hand": row["cash_on_hand"],
                "row_id": row["row_id"],
            }
        )
    return payloads


def _merge_filing_breakdown_payloads(
    payloads_by_committee: dict[str, list[dict[str, object]]],
    batch_payloads_by_committee: dict[str, list[dict[str, object]]],
) -> None:
    for committee_id, batch_payloads in batch_payloads_by_committee.items():
        payloads_by_committee.setdefault(committee_id, []).extend(batch_payloads)


def _populate_committee_summary_filing_breakdowns(
    connection: object,
    *,
    cycles: tuple[int, ...],
    committee_ids: tuple[str, ...] | None,
    filing_batch_size: int | None,
) -> None:
    target_committee_ids = _committee_summary_target_committee_ids(
        connection,
        cycles=cycles,
        committee_ids=committee_ids,
    )
    if not target_committee_ids:
        return
    payloads_by_committee: dict[str, list[dict[str, object]]] = {}
    # Stream all-history rows so SQL can compute cash-on-hand before the recent-window trim.
    for filing_rows in _iter_committee_summary_filing_row_batches(
        connection,
        committee_ids=target_committee_ids,
        filing_batch_size=filing_batch_size,
    ):
        _merge_filing_breakdown_payloads(
            payloads_by_committee,
            _filing_breakdown_payloads_by_committee(filing_rows),
        )
    with connection.cursor() as cursor:
        for committee_id in target_committee_ids:
            cursor.execute(
                _COMMITTEE_SUMMARY_FILING_BREAKDOWN_UPDATE_SQL,
                (
                    Jsonb(payloads_by_committee.get(committee_id, [])),
                    list(cycles),
                    committee_id,
                ),
            )


def populate_committee_summary_derived_aggregates(
    connection: object,
    *,
    cycles: tuple[int, ...],
    committee_ids: tuple[str, ...] | None = None,
    filing_batch_size: int | None = None,
) -> int:
    committee_id_list = None if committee_ids is None else list(committee_ids)
    with connection.cursor() as cursor:
        cursor.execute(
            _COMMITTEE_SUMMARY_DERIVED_AGGREGATE_SQL,
            (list(cycles), committee_id_list, committee_id_list),
        )
        rows_updated = cursor.rowcount
    _populate_committee_summary_filing_breakdowns(
        connection,
        cycles=cycles,
        committee_ids=committee_ids,
        filing_batch_size=filing_batch_size,
    )
    return rows_updated


def _build_fec_committee_summary_job(parameters: RunnerParameters) -> RefreshJob:
    cycles = _active_committee_summary_cycles(parameters.fec_cycle)

    def _run_fec_committee_summary_job() -> list[object]:
        with tempfile.TemporaryDirectory(prefix="refresh-fec-committee-summary-") as temp_dir:
            temp_dir_path = Path(temp_dir)
            download_paths: list[tuple[int, Path]] = []
            for cycle in cycles:
                destination_path = temp_dir_path / f"committee_summary_{cycle}.csv"
                urlretrieve(fec_committee_summary_url(cycle), destination_path)
                download_paths.append((cycle, destination_path))

            connection = get_connection()
            try:
                with connection.transaction():
                    data_source_id = ensure_fec_bulk_data_source(connection)

                results: list[object] = []
                for cycle, destination_path in download_paths:
                    results.append(
                        dispatch_load(
                            conn=connection,
                            config=CliConfig(
                                mode="single",
                                cycle=cycle,
                                file_type="committee_summary",
                                path=destination_path,
                                directory=None,
                                batch_size=1000,
                                limit=None,
                                graph_enabled=False,
                                with_transactions=False,
                            ),
                            request=LoadRequest(file_type="committee_summary", path=destination_path),
                            data_source_id=data_source_id,
                        )
                    )
                results.append(populate_committee_summary_derived_aggregates(connection, cycles=cycles))
                return results
            finally:
                connection.close()

    return RefreshJob(
        key="federal-fec-committee-summary",
        domain="campaign_finance",
        jurisdiction="federal/fec",
        cadence="weekly",
        data_source_names=(FEC_BULK_DATA_SOURCE_NAME,),
        run_callable=_run_fec_committee_summary_job,
        refresh_history_key="federal-fec-committee-summary",
    )


def _build_fec_schedule_e_job(parameters: RunnerParameters) -> RefreshJob:
    # Schedule E follows the same active-cycle window as Schedule A rather than
    # keeping its own rule. Loading only the current cycle meant a race in the
    # previous cycle had no independent-expenditure rows at all, so the surfaces
    # could show only "not loaded" for it — the 2024 Senate races among them.
    # Measured 2026-08-19 via HTTP HEAD on the FEC bulk endpoint:
    # independent_expenditure_2024.csv is 19,534,174 bytes and _2026.csv is
    # 3,694,250, so the added cycle is tens of MB, not the tens of GB the
    # Schedule A capacity work in docs/live-state/2026_07_27_b2_disposition.md
    # is about.
    cycles = _active_fec_transaction_cycles(parameters.fec_cycle)

    def _run_fec_schedule_e_job() -> list[object]:
        with _temporary_refresh_directory(prefix="refresh-fec-schedule-e-") as temp_dir:
            download_paths: list[tuple[int, Path]] = []
            for cycle in cycles:
                destination_path = Path(temp_dir) / f"independent_expenditure_{cycle}.csv"
                urlretrieve(fec_schedule_e_url(cycle), destination_path)
                download_paths.append((cycle, destination_path))

            connection = get_connection()
            try:
                with connection.transaction():
                    data_source_id = ensure_fec_bulk_data_source(connection)
                # One dispatch per cycle: the loader stamps the cycle into every
                # source_record key, so re-running is idempotent per cycle and
                # the two loads cannot collide on the active-key unique index.
                return [
                    dispatch_load(
                        conn=connection,
                        config=CliConfig(
                            mode="single",
                            cycle=cycle,
                            file_type="schedule_e",
                            path=destination_path,
                            directory=None,
                            batch_size=1000,
                            limit=None,
                            graph_enabled=False,
                            with_transactions=False,
                        ),
                        request=LoadRequest(file_type="schedule_e", path=destination_path),
                        data_source_id=data_source_id,
                    )
                    for cycle, destination_path in download_paths
                ]
            finally:
                connection.close()

    return RefreshJob(
        key="federal-fec-schedule-e",
        domain="campaign_finance",
        jurisdiction="federal/fec",
        cadence="continuous",
        data_source_names=(FEC_BULK_DATA_SOURCE_NAME,),
        run_callable=_run_fec_schedule_e_job,
    )


def _build_fec_schedule_b_job(parameters: RunnerParameters) -> RefreshJob:
    def _run_fec_schedule_b_job() -> object:
        with _temporary_refresh_directory(prefix="refresh-fec-schedule-b-") as temp_dir:
            temp_dir_path = Path(temp_dir)
            cycle_suffix = str(parameters.fec_cycle)[-2:]
            archive_path = temp_dir_path / f"oppexp{cycle_suffix}.zip"
            urlretrieve(fec_schedule_b_url(parameters.fec_cycle), archive_path)

            with zipfile.ZipFile(archive_path) as archive:
                txt_members = [name for name in archive.namelist() if name.lower().endswith(".txt")]
                if not txt_members:
                    raise ValueError(f"Schedule B archive has no .txt payload: {archive_path}")

                oppexp_members = [name for name in txt_members if Path(name).name.lower().startswith("oppexp")]
                selected_member = oppexp_members[0] if oppexp_members else txt_members[0]
                extracted_path = temp_dir_path / Path(selected_member).name
                with archive.open(selected_member) as source, extracted_path.open("wb") as destination:
                    shutil.copyfileobj(source, destination)

            connection = get_connection()
            try:
                with connection.transaction():
                    data_source_id = ensure_fec_bulk_data_source(connection)
                return dispatch_load(
                    conn=connection,
                    config=CliConfig(
                        mode="single",
                        cycle=parameters.fec_cycle,
                        file_type="schedule_b",
                        path=extracted_path,
                        directory=None,
                        batch_size=1000,
                        limit=parameters.fec_limit,
                        graph_enabled=False,
                        with_transactions=False,
                    ),
                    request=LoadRequest(file_type="schedule_b", path=extracted_path),
                    data_source_id=data_source_id,
                )
            finally:
                connection.close()

    return RefreshJob(
        key="federal-fec-schedule-b",
        domain="campaign_finance",
        jurisdiction="federal/fec",
        cadence="continuous",
        data_source_names=(FEC_BULK_DATA_SOURCE_NAME,),
        run_callable=_run_fec_schedule_b_job,
    )


def _build_federal_congress_spine_job() -> RefreshJob:
    def _run_federal_congress_spine_job() -> object:
        raw_entries = fetch_legislators_entries()
        adapted_legislators = adapt_legislators_yaml(raw_entries)
        historical_entries = fetch_historical_entries()
        vacancy_predecessors = select_most_recent_vacancy_predecessors(
            adapted_legislators,
            historical_entries,
        )

        connection = get_connection()
        try:
            with connection.transaction():
                data_source_id = ensure_federal_spine_data_source(connection)
                load_result = load_federal_spine(
                    connection,
                    adapted_legislators,
                    data_source_id=data_source_id,
                )
                load_vacancy_predecessors(
                    connection,
                    vacancy_predecessors,
                    data_source_id=data_source_id,
                )
                return load_result
        finally:
            connection.close()

    return RefreshJob(
        key="federal-congress-spine",
        domain="campaign_finance",
        jurisdiction="federal/congress",
        cadence="weekly",
        data_source_names=(FEDERAL_SPINE_DATA_SOURCE_NAME,),
        run_callable=_run_federal_congress_spine_job,
    )


def _federal_fec_races_min_election_year(parameters: RunnerParameters) -> int:
    """Recent five-cycle window (inclusive) anchored on the configured FEC cycle."""
    return parameters.fec_cycle - 4


def _federal_fec_races_max_election_year(parameters: RunnerParameters) -> int:
    """Forward five-cycle window (inclusive), symmetric with the floor above.

    FEC candidate rows carry a filer-supplied election year that nothing
    validates beyond "parses as an int", so production accumulated contests
    dated 2089 and 2929 that served as live race pages. Two cycles ahead is too
    tight — presidential candidates genuinely file early — so the ceiling
    mirrors the existing floor at four years out. That admits every plausible
    early filing while excluding the implausible-and-unmaintainable tail; the
    threshold is a judgment call, and this is the one place to retune it.
    """
    return parameters.fec_cycle + 4


def _build_federal_fec_races_job(parameters: RunnerParameters) -> RefreshJob:
    def _run_federal_fec_races_job() -> object:
        connection = get_connection()
        try:
            with connection.transaction():
                races_data_source_id = ensure_federal_fec_races_data_source(connection)
                cn_data_source_id = ensure_fec_bulk_data_source(connection)
            return load_federal_fec_races(
                connection,
                races_data_source_id=races_data_source_id,
                cn_data_source_id=cn_data_source_id,
                election_client=_ComputedElectionDatesClient(),
                min_election_year=_federal_fec_races_min_election_year(parameters),
                max_election_year=_federal_fec_races_max_election_year(parameters),
            )
        finally:
            connection.close()

    return RefreshJob(
        key="federal-fec-races",
        domain="civics",
        jurisdiction="federal/fec",
        cadence="weekly",
        data_source_names=(FEDERAL_FEC_RACES_DATA_SOURCE_NAME,),
        run_callable=_run_federal_fec_races_job,
        refresh_history_key="federal-fec-races",
    )


def _build_federal_enrichment_job() -> RefreshJob:
    def _run_federal_enrichment_job() -> object:
        connection = get_connection()
        try:
            summary = run_federal_enrichment(connection)
            connection.commit()
            return summary
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    return RefreshJob(
        key="federal-enrichment",
        domain="people_enrichment",
        jurisdiction="federal/congress",
        cadence="weekly",
        data_source_names=(FEDERAL_ENRICHMENT_DATA_SOURCE_NAME,),
        run_callable=_run_federal_enrichment_job,
        activity_denominator_result_field="due",
    )


def _build_donor_search_rollup_job() -> RefreshJob:
    def _run_donor_search_rollup_job() -> donor_rollup.DonorRollupBuildResult:
        connection = get_connection()
        try:
            donor_rollup.ensure_donor_search_rollup_data_source(connection)
            result = donor_rollup.rebuild_donor_search_rollup(connection)
            connection.commit()
            return result
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    return RefreshJob(
        key="federal-donor-search-rollup",
        domain="campaign_finance",
        jurisdiction="federal/fec",
        cadence="weekly",
        data_source_names=("civibus-donor-search-rollup",),
        run_callable=_run_donor_search_rollup_job,
        refresh_history_key="federal-donor-search-rollup",
    )


def _build_irs_527_job() -> RefreshJob:
    def _run_irs_527_job() -> object:
        with _temporary_refresh_directory(prefix="refresh-irs-527-") as temp_dir:
            temp_dir_path = Path(temp_dir)
            archive_path = download_irs_527_full_data(temp_dir_path)
            txt_path = extract_irs_527_txt(archive_path, temp_dir_path)

            connection = get_connection()
            try:
                with connection.transaction():
                    data_source_id = ensure_irs_527_data_source(connection)
                return load_irs_527_records(
                    connection,
                    txt_path,
                    data_source_id=data_source_id,
                )
            finally:
                connection.close()

    return RefreshJob(
        key="federal-irs-527",
        domain="campaign_finance",
        jurisdiction="federal/irs_527",
        cadence="continuous",
        data_source_names=(_IRS_527_DATA_SOURCE_NAME,),
        run_callable=_run_irs_527_job,
    )


def _build_federal_geometry_probe_job() -> RefreshJob:
    def _run_federal_geometry_probe_job() -> object:
        connection = get_connection()
        try:
            result = probe_tiger_congressional_district_listing(connection, year=2024)
            connection.commit()
            return result
        finally:
            connection.close()

    return RefreshJob(
        key="federal-geometry-probe",
        domain="civics",
        jurisdiction="federal/geometry",
        cadence="weekly",
        data_source_names=(TIGER_CD_LISTING_DATA_SOURCE_NAME,),
        run_callable=_run_federal_geometry_probe_job,
    )


def _build_nc_past_results_job() -> RefreshJob:
    return RefreshJob(
        key="civics-nc-past-results-2022-2024",
        domain="civics",
        jurisdiction="us/nc",
        cadence="weekly",
        data_source_names=collect_ncsbe_refresh_data_source_names(),
        run_callable=run_ncsbe_results_refresh_2022_2024,
    )


def _include_explicit_nc_past_results_job(*, job_key_prefixes: tuple[str, ...]) -> bool:
    """Only materialize the sample-backed ENRS job for explicit operator invocations."""
    if not job_key_prefixes:
        return False
    job_key = "civics-nc-past-results-2022-2024"
    return any(job_key.startswith(job_key_prefix) for job_key_prefix in job_key_prefixes)


def _priority_source_names(
    configs_by_state_code: dict[str, JurisdictionConfig],
    *,
    parameters: RunnerParameters,
    jobs: list[RefreshJob],
) -> set[str]:
    priority_sources: set[str] = set()

    for state_code, transaction_types in _PRIORITY_STATE_TRANSACTION_TYPES.items():
        config = configs_by_state_code.get(state_code)
        if config is None:
            continue
        for data_source in config.data_sources:
            if set(data_source.coverage.transaction_types).intersection(transaction_types):
                priority_sources.add(data_source.name)

    for job in jobs:
        if parameters.nc_committee_docs_path is not None and job.key == "state-nc-transactions":
            priority_sources.update(job.data_source_names)
        if parameters.nc_ie_document_index_path is not None and job.key.startswith("state-nc-ie-"):
            priority_sources.update(job.data_source_names)

    priority_sources.add(_NCSBE_DATA_SOURCE_NAME)
    priority_sources.add(FEDERAL_SPINE_DATA_SOURCE_NAME)
    priority_sources.add(FEDERAL_ENRICHMENT_DATA_SOURCE_NAME)

    return priority_sources


def _priority_cadence_for_job(job: RefreshJob) -> str:
    if job.key == "civic-nc-candidate-listing":
        return job.cadence
    # The congress-legislators upstream YAML is republished weekly, so the
    # priority plan keeps the job's intrinsic weekly cadence instead of
    # promoting it to the generic daily priority cadence.
    if job.key in {"federal-congress-spine", "federal-enrichment"}:
        return job.cadence
    return _PRIORITY_CADENCE


def _filter_jobs_by_key_prefixes(
    jobs: list[RefreshJob],
    *,
    job_key_prefixes: tuple[str, ...],
) -> list[RefreshJob]:
    if not job_key_prefixes:
        return jobs

    filtered_jobs = [
        job for job in jobs if any(job.key.startswith(job_key_prefix) for job_key_prefix in job_key_prefixes)
    ]
    if filtered_jobs:
        return filtered_jobs

    joined_prefixes = ", ".join(repr(prefix) for prefix in job_key_prefixes)
    raise ValueError(f"No refresh jobs matched job_key_prefixes: {joined_prefixes}")


def _build_civic_roster_jobs() -> list[RefreshJob]:
    from domains.civics.loaders.official_rosters.loader import harvest_official_roster

    jobs: list[RefreshJob] = []
    for template in civic_roster_refresh_templates():
        if template.refresh_job_key is None or template.refresh_jurisdiction is None:
            continue

        source_id = template.registry_source_id

        def _run_civic_roster_job(*, roster_source_id: str = source_id) -> object:
            connection = get_connection()
            try:
                result = harvest_official_roster(connection, source_id=roster_source_id, dry_run=False)
                connection.commit()
                return result
            finally:
                connection.close()

        jobs.append(
            RefreshJob(
                key=template.refresh_job_key,
                domain="civics",
                jurisdiction=template.refresh_jurisdiction,
                cadence="weekly",
                data_source_names=(template.name,),
                run_callable=_run_civic_roster_job,
            )
        )
    return jobs


def build_refresh_plan(
    *,
    scope: str = "all",
    parameters: RunnerParameters | None = None,
    job_key_prefixes: tuple[str, ...] = (),
    now: datetime | None = None,
) -> list[RefreshJob]:
    if scope not in _SUPPORTED_REFRESH_SCOPES:
        raise ValueError(f"Unsupported scope: {scope!r}")

    resolved_now = _resolve_now(now)
    resolved_parameters = parameters or RunnerParameters()
    validated_registrations = load_validated_refresh_registrations()
    registered_configs = tuple(item.config for item in validated_registrations)
    configs_by_state_code = {
        item.config.jurisdiction.code: item.config for item in validated_registrations if item.identity[0] == "state"
    }

    jobs: list[RefreshJob] = [_build_fec_masters_job(resolved_parameters)]
    jobs.append(_build_fec_job(resolved_parameters))
    jobs.append(_build_fec_committee_summary_job(resolved_parameters))
    jobs.append(_build_federal_congress_spine_job())
    # federal-fec-races reads the cn candidate master rows loaded by
    # federal-fec-masters and populates the civic.election/contest/candidacy spine.
    jobs.append(_build_federal_fec_races_job(resolved_parameters))
    # The rollup requires the current federal roster/races plus committee-summary
    # derived jurisdiction before serving can switch away from transaction scans.
    jobs.append(_build_donor_search_rollup_job())
    # federal-enrichment joins on people, FEC transaction, and Schedule E rows
    # produced by the preceding federal jobs.
    jobs.append(_build_fec_schedule_b_job(resolved_parameters))
    jobs.append(_build_fec_schedule_e_job(resolved_parameters))
    jobs.append(_build_federal_enrichment_job())
    jobs.append(_build_irs_527_job())
    jobs.append(_build_federal_geometry_probe_job())
    if _include_explicit_nc_past_results_job(job_key_prefixes=job_key_prefixes):
        jobs.append(_build_nc_past_results_job())
    jobs.extend(
        build_registered_refresh_jobs(
            registrations=JURISDICTION_REFRESH_REGISTRATIONS,
            configs=registered_configs,
            parameters=resolved_parameters,
            now=resolved_now,
        )
    )
    jobs.extend(_build_civic_roster_jobs())
    jobs.extend(_build_official_roster_jobs())

    if scope == "priority":
        allowed_sources = _priority_source_names(
            configs_by_state_code,
            parameters=resolved_parameters,
            jobs=jobs,
        )
        jobs = [
            replace(job, cadence=_priority_cadence_for_job(job))
            for job in jobs
            if any(source_name in allowed_sources for source_name in job.data_source_names)
        ]
    elif scope == "federal":
        jobs = _filter_weekly_federal_scope_jobs(jobs, job_key_prefixes=job_key_prefixes)

    return _filter_jobs_by_key_prefixes(jobs, job_key_prefixes=job_key_prefixes)
