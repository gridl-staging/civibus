"""Contract tests for IRS 527 refresh job wiring in build_refresh_plan()."""

from __future__ import annotations

import inspect
import json
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock
from uuid import UUID

import psycopg
import pytest

from api.test_campaign_finance_support import (
    CommitteeRowSeed,
    CommitteeSummaryRowSeed,
    FilingRowSeed,
    TransactionRowSeed,
    insert_committee_row,
    insert_committee_summary_row,
    insert_data_source_for_test,
    insert_filing_row,
    insert_source_record_for_test,
    insert_transaction_row,
)
from core.refresh import job_builders
from core.refresh.job_builders import build_refresh_plan
from core.refresh.runner import RefreshJob, RunnerParameters, build_argument_parser
from domains.civics.loaders.ncsbe_candidate_listing import _NCSBE_DATA_SOURCE_NAME
from domains.civics.loaders.ncsbe_results import collect_ncsbe_refresh_raw_csv_paths
from domains.civics.loaders.official_rosters.source_templates import (
    civic_roster_refresh_templates,
    roster_source_templates,
)
from domains.civics.loaders.official_rosters.source_registry import (
    list_nc_roster_source_metadata,
)
from domains.campaign_finance.jurisdictions.config_schema import load_jurisdiction_config
from domains.campaign_finance.jurisdictions.states.NC.scraper import _CONFIG_PATH as _NC_CONFIG_PATH
from domains.campaign_finance.jurisdictions.states.NC.scraper.load_support import (
    NC_COMMITTEE_DOCUMENT_SOURCE_NAME,
)

_EXPECTED_STAGE2_CIVIC_ROSTER_KEYS = (
    "civic-rosters-us-house-nc",
    "civic-rosters-us-senate-nc-ii",
    "civic-rosters-us-senate-nc-iii",
    "civic-rosters-nc-senate",
    "civic-rosters-council-of-state-gov",
    "civic-rosters-council-of-state-lt-gov",
    "civic-rosters-council-of-state-ag",
    "civic-rosters-council-of-state-sos",
    "civic-rosters-council-of-state-treasurer",
    "civic-rosters-council-of-state-auditor",
    "civic-rosters-council-of-state-supt",
    "civic-rosters-council-of-state-ag-comm",
    "civic-rosters-council-of-state-ins-comm",
    "civic-rosters-council-of-state-labor-comm",
    "civic-rosters-nc-supreme",
    "civic-rosters-nc-appeals",
)

_EXPECTED_CAMPAIGN_FINANCE_KEYS = (
    "city-la-transactions",
    "city-nyc-transactions",
    "city-phl-contributions",
    "city-phl-expenditures",
    "city-sf-transactions",
    "federal-congress-spine",
    "federal-fec-committee-summary",
    "federal-fec-masters",
    "federal-fec-schedule-a",
    "federal-fec-schedule-b",
    "federal-fec-schedule-e",
    "federal-irs-527",
    "state-al-contributions",
    "state-al-expenditures",
    "state-ca-refresh",
    "state-co-contributions",
    "state-co-expenditures",
    "state-fl-contributions",
    "state-fl-expenditures",
    "state-fl-other",
    "state-fl-transfers",
    "state-ga-contributions",
    "state-ga-expenditures",
    "state-il-contributions",
    "state-il-expenditures",
    "state-in-contributions",
    "state-in-expenditures",
    "state-ky-contributions-11-5-2024",
    "state-ky-contributions-11-7-2023",
    "state-ky-contributions-11-8-2022",
    "state-ky-contributions-5-16-2023",
    "state-ky-contributions-5-17-2022",
    "state-ky-contributions-5-19-2026",
    "state-ky-contributions-5-21-2024",
    "state-ky-expenditures",
    "state-la-contributions",
    "state-la-expenditures",
    "state-la-loans",
    "state-ma-contributions",
    "state-ma-expenditures",
    "state-mn-contributions",
    "state-mn-expenditures",
    "state-mn-independent_expenditures",
    "state-nc-committee-discovery",
    "state-ne-contributions",
    "state-ne-expenditures",
    "state-ne-loans",
    "state-nj-contributions",
    "state-ny-contributions",
    "state-ny-expenditures",
    "state-ny-independent_expenditures",
    "state-or-contributions",
    "state-or-expenditures",
    "state-pa-contributions",
    "state-pa-debts",
    "state-pa-expenditures",
    "state-pa-receipts",
    "state-tx-contributions",
    "state-tx-expenditures",
    "state-tx-loans",
    "state-va-contributions",
    "state-va-expenditures",
    "state-wa-contributions",
    "state-wa-expenditures",
    "state-wa-independent_expenditures",
    "state-wa-loans",
    "state-wi-transactions",
)


@pytest.mark.unit
class TestIRS527JobContract:
    """Contract: build_refresh_plan() must produce a federal-irs-527 job."""

    def _find_irs_527_job(self, jobs: list[RefreshJob]) -> RefreshJob:
        matches = [j for j in jobs if j.key == "federal-irs-527"]
        assert len(matches) == 1, (
            f"Expected exactly 1 job with key 'federal-irs-527', found {len(matches)} in {[j.key for j in jobs]}"
        )
        return matches[0]

    def test_plan_contains_irs_527_job_with_correct_metadata(self) -> None:
        jobs = build_refresh_plan()
        job = self._find_irs_527_job(jobs)

        assert job.domain == "campaign_finance"
        assert job.jurisdiction == "federal/irs_527"
        assert job.cadence == "continuous"
        assert "IRS Form 8872 Political Organizations" in job.data_source_names

    def test_key_prefix_filter_isolates_irs_527_job(self) -> None:
        jobs = build_refresh_plan(job_key_prefixes=("federal-irs-527",))

        assert len(jobs) == 1
        job = jobs[0]
        assert job.key == "federal-irs-527"
        assert not any(j.key.startswith(("fec-", "state-", "city-")) for j in jobs), (
            "Filtering by federal-irs-527 must exclude FEC, state, and city jobs"
        )

    def test_run_callable_is_zero_arg_callable(self) -> None:
        jobs = build_refresh_plan()
        job = self._find_irs_527_job(jobs)

        assert callable(job.run_callable)
        sig = inspect.signature(job.run_callable)
        required_params = [
            p
            for p in sig.parameters.values()
            if p.default is inspect.Parameter.empty
            and p.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
        ]
        assert len(required_params) == 0, (
            f"run_callable must accept zero positional arguments, "
            f"but has required params: {[p.name for p in required_params]}"
        )


@pytest.mark.unit
class TestFederalEnrichmentJobContract:
    def _find_federal_enrichment_job(self) -> RefreshJob:
        jobs = build_refresh_plan(job_key_prefixes=("federal-enrichment",))
        assert len(jobs) == 1
        return jobs[0]

    def test_federal_enrichment_runs_after_fec_masters_and_congress_spine(self) -> None:
        jobs = build_refresh_plan(
            job_key_prefixes=(
                "federal-fec-masters",
                "federal-congress-spine",
                "federal-enrichment",
            ),
        )

        assert tuple(job.key for job in jobs) == (
            "federal-fec-masters",
            "federal-congress-spine",
            "federal-enrichment",
        )
        assert [job.key for job in jobs].count("federal-enrichment") == 1

    def test_federal_enrichment_job_metadata_matches_people_enrichment_source(self) -> None:
        job = self._find_federal_enrichment_job()

        assert job.key == "federal-enrichment"
        assert job.domain == "people_enrichment"
        assert job.jurisdiction == "federal/congress"
        assert job.cadence == "weekly"
        assert job.data_source_names == ("people-enrichment-federal-congress",)

    def test_priority_scope_includes_federal_spine_before_weekly_enrichment(self) -> None:
        jobs = build_refresh_plan(
            scope="priority",
            job_key_prefixes=("federal-congress-spine", "federal-enrichment"),
        )

        assert tuple(job.key for job in jobs) == (
            "federal-congress-spine",
            "federal-enrichment",
        )
        assert tuple(job.cadence for job in jobs) == ("weekly", "weekly")

    def test_federal_enrichment_run_callable_commits_and_closes_on_success(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        connection = MagicMock()
        enrichment_summary = {"updated": 3}
        get_connection = MagicMock(return_value=connection)
        run_federal_enrichment = MagicMock(return_value=enrichment_summary)
        monkeypatch.setattr(job_builders, "get_connection", get_connection)
        monkeypatch.setattr(job_builders, "run_federal_enrichment", run_federal_enrichment)
        job = self._find_federal_enrichment_job()

        result = job.run_callable()

        assert result == enrichment_summary
        get_connection.assert_called_once_with()
        run_federal_enrichment.assert_called_once_with(connection)
        connection.commit.assert_called_once_with()
        connection.rollback.assert_not_called()
        connection.close.assert_called_once_with()

    def test_federal_enrichment_run_callable_rolls_back_closes_and_reraises_on_failure(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        connection = MagicMock()
        error = RuntimeError("enrichment failed")
        get_connection = MagicMock(return_value=connection)
        run_federal_enrichment = MagicMock(side_effect=error)
        monkeypatch.setattr(job_builders, "get_connection", get_connection)
        monkeypatch.setattr(job_builders, "run_federal_enrichment", run_federal_enrichment)
        job = self._find_federal_enrichment_job()

        with pytest.raises(RuntimeError, match="enrichment failed"):
            job.run_callable()

        get_connection.assert_called_once_with()
        run_federal_enrichment.assert_called_once_with(connection)
        connection.commit.assert_not_called()
        connection.rollback.assert_called_once_with()
        connection.close.assert_called_once_with()


_EXPECTED_FEDERAL_JOB_KEYS = (
    "federal-fec-masters",
    "federal-fec-schedule-a",
    "federal-fec-committee-summary",
    "federal-congress-spine",
    "federal-fec-races",
    "federal-fec-schedule-b",
    "federal-fec-schedule-e",
    "federal-enrichment",
    "federal-irs-527",
    "federal-geometry-probe",
)


@pytest.mark.unit
class TestJobKeyPrefixFiltering:
    """Validates _filter_jobs_by_key_prefixes error path."""

    def test_nonexistent_prefix_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="No refresh jobs matched"):
            build_refresh_plan(job_key_prefixes=("nonexistent-prefix",))

    def test_repeated_prefixes_preserve_plan_order_without_duplicate_jobs(self) -> None:
        jobs = build_refresh_plan(
            job_key_prefixes=(
                "federal-fec-masters",
                "federal-congress-spine",
                "federal-enrichment",
                "federal-congress-spine",
            ),
        )

        assert tuple(job.key for job in jobs) == (
            "federal-fec-masters",
            "federal-congress-spine",
            "federal-enrichment",
        )
        assert [job.key for job in jobs].count("federal-congress-spine") == 1


@pytest.mark.unit
class TestFederalPrefixFilterContract:
    """Stage 2 contract: filtering by `federal-` selects exactly the federal
    slice the Stage 2 refresh lane targets, drops every state-, city-, and
    civic- job, deduplicates repeated prefixes, and preserves the plan order
    emitted by build_refresh_plan(). The exact federal key inventory lives
    only here — peer tests must not duplicate it."""

    def _expected_federal_order(self) -> tuple[str, ...]:
        full_plan_keys = [job.key for job in build_refresh_plan(scope="all")]
        return tuple(key for key in full_plan_keys if key in set(_EXPECTED_FEDERAL_JOB_KEYS))

    def test_expected_federal_key_inventory_matches_plan_order(self) -> None:
        assert _EXPECTED_FEDERAL_JOB_KEYS == self._expected_federal_order()

    def test_federal_prefix_selects_exact_federal_set_in_plan_order(self) -> None:
        jobs = build_refresh_plan(job_key_prefixes=("federal-",))

        actual_keys = tuple(job.key for job in jobs)
        assert set(actual_keys) == set(_EXPECTED_FEDERAL_JOB_KEYS)
        assert actual_keys == self._expected_federal_order()
        for actual_key in actual_keys:
            assert not actual_key.startswith(("state-", "city-", "civic-", "civics-"))

    def test_repeated_and_overlapping_federal_prefixes_return_each_job_once(self) -> None:
        jobs = build_refresh_plan(
            job_key_prefixes=("federal-", "federal-fec-masters", "federal-"),
        )

        actual_keys = tuple(job.key for job in jobs)
        assert actual_keys == self._expected_federal_order()
        for federal_key in _EXPECTED_FEDERAL_JOB_KEYS:
            assert actual_keys.count(federal_key) == 1

    def test_federal_scope_selects_exact_federal_set_in_plan_order(self) -> None:
        jobs = build_refresh_plan(scope="federal")

        actual_keys = tuple(job.key for job in jobs)
        assert actual_keys == _EXPECTED_FEDERAL_JOB_KEYS
        assert actual_keys == self._expected_federal_order()
        assert not any(job.key.startswith(("state-", "city-", "civic-", "civics-")) for job in jobs)


@pytest.mark.unit
class TestFederalGeometryProbeJobContract:
    def _find_geometry_probe_job(self) -> RefreshJob:
        jobs = build_refresh_plan(job_key_prefixes=("federal-geometry-probe",))
        assert len(jobs) == 1
        return jobs[0]

    def test_job_metadata(self) -> None:
        job = self._find_geometry_probe_job()

        assert job.key == "federal-geometry-probe"
        assert job.domain == "civics"
        assert job.jurisdiction == "federal/geometry"
        assert job.cadence == "weekly"
        assert job.data_source_names == ("Census TIGER congressional district listing",)

    def test_run_callable_invokes_probe_only(self, monkeypatch: pytest.MonkeyPatch) -> None:
        connection = MagicMock()
        probe_result = object()
        get_connection = MagicMock(return_value=connection)
        probe = MagicMock(return_value=probe_result)
        monkeypatch.setattr(job_builders, "get_connection", get_connection)
        monkeypatch.setattr(job_builders, "probe_tiger_congressional_district_listing", probe)

        result = self._find_geometry_probe_job().run_callable()

        assert result is probe_result
        get_connection.assert_called_once_with()
        probe.assert_called_once_with(connection, year=2024)
        connection.commit.assert_called_once_with()
        connection.close.assert_called_once_with()

    def test_probe_does_not_precede_independent_federal_prerequisites(self) -> None:
        keys = tuple(job.key for job in build_refresh_plan(scope="federal"))

        assert keys.index("federal-geometry-probe") > keys.index("federal-fec-masters")
        assert keys.index("federal-geometry-probe") > keys.index("federal-congress-spine")


@pytest.mark.unit
class TestFederalFecRacesJobContract:
    """Stage 2 contract: the federal races loader is wired as a single federal job."""

    def _find_races_job(self) -> RefreshJob:
        jobs = build_refresh_plan(job_key_prefixes=("federal-fec-races",))
        assert len(jobs) == 1, f"Expected exactly 1 federal-fec-races job, found {[j.key for j in jobs]}"
        return jobs[0]

    def test_job_metadata(self) -> None:
        from domains.civics.loaders.federal_fec_races import FEDERAL_FEC_RACES_DATA_SOURCE_NAME

        job = self._find_races_job()
        assert job.key == "federal-fec-races"
        assert job.domain == "civics"
        assert job.jurisdiction == "federal/fec"
        assert job.cadence == "weekly"
        assert job.data_source_names == (FEDERAL_FEC_RACES_DATA_SOURCE_NAME,)
        assert job.refresh_history_key == "federal-fec-races"

    def test_run_callable_is_zero_arg(self) -> None:
        job = self._find_races_job()
        assert callable(job.run_callable)
        required_params = [
            parameter
            for parameter in inspect.signature(job.run_callable).parameters.values()
            if parameter.default is inspect.Parameter.empty
            and parameter.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
        ]
        assert required_params == []

    def test_federal_scope_places_races_after_congress_spine(self) -> None:
        keys = [job.key for job in build_refresh_plan(scope="federal")]
        assert "federal-fec-races" in keys
        # Races consume cn candidate data produced by earlier federal jobs, so the
        # job is ordered immediately after the congress spine.
        assert keys.index("federal-fec-races") == keys.index("federal-congress-spine") + 1

    def test_federal_scope_excludes_other_civics_jobs(self) -> None:
        jobs = build_refresh_plan(scope="federal")
        keys = [job.key for job in jobs]
        assert "federal-fec-races" in keys
        # The civics-domain races job rides the federal scope by key prefix, while
        # every other civics job (rosters, NC candidate listing) stays excluded.
        assert not any(key.startswith(("civic-", "civics-", "state-", "city-")) for key in keys)


@pytest.mark.unit
class TestRunnerFECDefaultOwnership:
    def test_runner_parameters_default_fec_cycle_is_current_cycle(self) -> None:
        assert RunnerParameters().fec_cycle == 2026

    def test_argument_parser_default_fec_cycle_is_current_cycle(self) -> None:
        assert build_argument_parser().parse_args([]).fec_cycle == 2026


def _refresh_test_uuid(sequence: int) -> UUID:
    return UUID(f"91000000-0000-0000-0000-{sequence:012x}")


def _summary_top_list_transaction(
    sequence: int,
    *,
    filing_id: UUID,
    committee_id: UUID,
    transaction_type: str,
    amount: str,
    contributor_name_raw: str | None,
    memo_text: str | None,
    transaction_date: date = date(2026, 6, 1),
    amendment_indicator: str = "N",
    source_record_id: UUID | None = None,
    is_memo: bool = False,
) -> TransactionRowSeed:
    return TransactionRowSeed(
        id=_refresh_test_uuid(sequence),
        filing_id=filing_id,
        committee_id=committee_id,
        transaction_type=transaction_type,
        amount=Decimal(amount),
        amendment_indicator=amendment_indicator,
        source_record_id=source_record_id,
        transaction_identifier=f"top-list-{sequence}",
        transaction_date=transaction_date,
        contributor_name_raw=contributor_name_raw,
        memo_text=memo_text,
        is_memo=is_memo,
    )


def _insert_summary_top_list_transactions(
    db_conn: psycopg.Connection,
    transactions: tuple[TransactionRowSeed, ...],
) -> None:
    for transaction in transactions:
        insert_transaction_row(db_conn, transaction)


def _seed_ranked_receipt_transactions(
    db_conn: psycopg.Connection,
    *,
    filing_id: UUID,
    committee_id: UUID,
    active_source_id: UUID,
) -> None:
    rows = (
        (10, "11", "200.00", "  Alpha Donor  "),
        (11, "11", "200.00", "Alpha Donor"),
        (12, "11", "400.00", "Beta Donor"),
        (13, "11", "300.00", "Abel Donor"),
        (14, "11", "300.00", "Zed Donor"),
        (15, "11", "250.00", "Gamma Donor"),
        (16, "11", "200.00", "Delta Donor"),
        (17, "11", "100.00", "Epsilon Donor"),
        (18, "11", "50.00", "   "),
        (19, "11", "60.00", None),
        (20, "16", "70.00", "Loan Donor"),
        (21, "15Z", "80.00", "In Kind Donor"),
    )
    _insert_summary_top_list_transactions(
        db_conn,
        tuple(
            _summary_top_list_transaction(
                sequence,
                filing_id=filing_id,
                committee_id=committee_id,
                transaction_type=transaction_type,
                amount=amount,
                contributor_name_raw=contributor_name_raw,
                memo_text=None,
                source_record_id=active_source_id if sequence == 10 else None,
            )
            for sequence, transaction_type, amount, contributor_name_raw in rows
        ),
    )


def _seed_ranked_disbursement_transactions(
    db_conn: psycopg.Connection,
    *,
    filing_id: UUID,
    committee_id: UUID,
) -> None:
    rows = (
        (30, "150.00", "  Acme LLC  ", " Digital Ads "),
        (31, "150.00", "Acme LLC", "digital ads"),
        (32, "300.00", "Beta Vendor", "MAIL"),
        (33, "200.00", "Alpha Vendor", " events "),
        (34, "200.00", "Zeta Vendor", "Travel"),
        (35, "150.00", "Gamma Vendor", "printing"),
        (36, "100.00", "Delta Vendor", "office"),
        (37, "50.00", "Epsilon Vendor", "signage"),
        (38, "25.00", "Blank Memo Vendor", "   "),
        (39, "35.00", "Null Memo Vendor", None),
    )
    _insert_summary_top_list_transactions(
        db_conn,
        tuple(
            _summary_top_list_transaction(
                sequence,
                filing_id=filing_id,
                committee_id=committee_id,
                transaction_type="21",
                amount=amount,
                contributor_name_raw=contributor_name_raw,
                memo_text=memo_text,
            )
            for sequence, amount, contributor_name_raw, memo_text in rows
        ),
    )


def _seed_excluded_summary_transactions(
    db_conn: psycopg.Connection,
    *,
    filing_id: UUID,
    committee_id: UUID,
    superseded_source_id: UUID,
) -> None:
    _insert_summary_top_list_transactions(
        db_conn,
        (
            _summary_top_list_transaction(
                50,
                filing_id=filing_id,
                committee_id=committee_id,
                transaction_type="11",
                amount="1000.00",
                contributor_name_raw="Memo Excluded",
                memo_text=None,
                is_memo=True,
            ),
            _summary_top_list_transaction(
                51,
                filing_id=filing_id,
                committee_id=committee_id,
                transaction_type="21",
                amount="1000.00",
                contributor_name_raw="Amendment Excluded",
                memo_text="excluded",
                amendment_indicator="T",
            ),
            _summary_top_list_transaction(
                52,
                filing_id=filing_id,
                committee_id=committee_id,
                transaction_type="11",
                amount="1000.00",
                contributor_name_raw="Superseded Excluded",
                memo_text=None,
                source_record_id=superseded_source_id,
            ),
            _summary_top_list_transaction(
                53,
                filing_id=filing_id,
                committee_id=committee_id,
                transaction_type="11",
                amount="1000.00",
                contributor_name_raw="Cycle Excluded",
                memo_text=None,
                transaction_date=date(2027, 1, 1),
            ),
        ),
    )


def _seed_committee_summary_top_list_committee(
    db_conn: psycopg.Connection,
    *,
    committee_id: UUID,
    fec_committee_id: str,
    filing_id: UUID,
    cycle: int = 2026,
) -> None:
    insert_committee_row(
        db_conn,
        CommitteeRowSeed(
            id=committee_id,
            fec_committee_id=fec_committee_id,
            name=f"Top List Committee {fec_committee_id}",
        ),
    )
    insert_committee_summary_row(
        db_conn,
        CommitteeSummaryRowSeed(
            committee_id=committee_id,
            cycle=cycle,
            coverage_start_date=date(cycle - 1, 1, 1),
            coverage_end_date=date(cycle, 12, 31),
        ),
    )
    insert_filing_row(
        db_conn,
        FilingRowSeed(
            id=filing_id,
            filing_fec_id=f"F{fec_committee_id}",
            committee_id=committee_id,
            coverage_start_date=date(cycle, 1, 1),
            coverage_end_date=date(cycle, 6, 30),
        ),
    )


def _committee_summary_values(
    db_conn: psycopg.Connection,
    committee_id: UUID,
    *,
    cycle: int = 2026,
) -> dict[str, object]:
    with db_conn.cursor(row_factory=psycopg.rows.dict_row) as cursor:
        cursor.execute(
            """
            SELECT
                derived_total_raised,
                derived_total_spent,
                derived_net,
                derived_transaction_count,
                derived_cash_receipts_total,
                derived_in_kind_receipts_total,
                derived_loan_receipts_total,
                derived_contribution_receipts_total,
                derived_top_donors,
                derived_top_vendors,
                derived_spend_categories,
                derived_filing_breakdown
            FROM cf.committee_summary
            WHERE committee_id = %s
              AND cycle = %s
            """,
            (committee_id, cycle),
        )
        row = cursor.fetchone()
    assert row is not None
    return dict(row)


def _set_committee_summary_sentinels(db_conn: psycopg.Connection, committee_id: UUID) -> None:
    with db_conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE cf.committee_summary
            SET derived_total_raised = 999.00,
                derived_total_spent = 888.00,
                derived_net = 111.00,
                derived_transaction_count = 77,
                derived_top_donors = '[{"name": "sentinel donor"}]'::jsonb,
                derived_top_vendors = '[{"name": "sentinel vendor"}]'::jsonb,
                derived_spend_categories = '[{"category": "sentinel category"}]'::jsonb,
                derived_filing_breakdown = '[{"filing_id": "sentinel"}]'::jsonb
            WHERE committee_id = %s
              AND cycle = 2026
            """,
            (committee_id,),
        )


def _set_committee_summary_top_lists(
    db_conn: psycopg.Connection,
    committee_id: UUID,
    *,
    donors_sql: str | None,
    vendors_sql: str | None,
    spend_categories_sql: str | None,
    cycle: int = 2026,
) -> None:
    with db_conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE cf.committee_summary
            SET derived_top_donors = CASE WHEN %s THEN NULL ELSE %s::jsonb END,
                derived_top_vendors = CASE WHEN %s THEN NULL ELSE %s::jsonb END,
                derived_spend_categories = CASE WHEN %s THEN NULL ELSE %s::jsonb END
            WHERE committee_id = %s
              AND cycle = %s
            """,
            (
                donors_sql is None,
                donors_sql,
                vendors_sql is None,
                vendors_sql,
                spend_categories_sql is None,
                spend_categories_sql,
                committee_id,
                cycle,
            ),
        )


def _seed_committee_summary_filing_breakdown_fixture(db_conn: psycopg.Connection) -> dict[str, UUID]:
    ids = {
        "requested_committee": _refresh_test_uuid(401),
        "sentinel_committee": _refresh_test_uuid(402),
        "filing_older": _refresh_test_uuid(403),
        "filing_recent_low": _refresh_test_uuid(404),
        "filing_recent_high": _refresh_test_uuid(405),
        "filing_zero": _refresh_test_uuid(406),
        "superseding_source": _refresh_test_uuid(407),
        "superseded_source": _refresh_test_uuid(408),
    }
    data_source = insert_data_source_for_test(db_conn, jurisdiction="federal/fec", name_suffix="filing-breakdown")
    insert_source_record_for_test(
        db_conn,
        source_record_id=ids["superseding_source"],
        data_source_id=data_source.id,
        source_record_key="filing-breakdown-current",
        source_url="https://example.org/source/filing-breakdown-current",
        pull_date=datetime(2026, 7, 18, tzinfo=timezone.utc),
    )
    insert_source_record_for_test(
        db_conn,
        source_record_id=ids["superseded_source"],
        data_source_id=data_source.id,
        source_record_key="filing-breakdown-superseded",
        source_url="https://example.org/source/filing-breakdown-superseded",
        pull_date=datetime(2026, 7, 17, tzinfo=timezone.utc),
        superseded_by=ids["superseding_source"],
    )
    _seed_committee_summary_top_list_committee(
        db_conn,
        committee_id=ids["requested_committee"],
        fec_committee_id="C90000401",
        filing_id=ids["filing_older"],
    )
    _seed_committee_summary_top_list_committee(
        db_conn,
        committee_id=ids["sentinel_committee"],
        fec_committee_id="C90000402",
        filing_id=_refresh_test_uuid(409),
    )
    _update_committee_summary_older_filing(db_conn, ids["filing_older"])
    _insert_committee_summary_filing_breakdown_rows(db_conn, ids)
    _set_committee_summary_sentinels(db_conn, ids["sentinel_committee"])
    return ids


def _update_committee_summary_older_filing(db_conn: psycopg.Connection, filing_id: UUID) -> None:
    db_conn.execute(
        """
        UPDATE cf.filing
        SET report_type = 'Q1',
            amendment_indicator = 'A',
            filing_name = 'Older Filing',
            coverage_start_date = DATE '2026-01-01',
            coverage_end_date = DATE '2026-03-31',
            receipt_date = DATE '2026-04-15'
        WHERE id = %s
        """,
        (filing_id,),
    )


def _insert_committee_summary_filing_breakdown_rows(db_conn: psycopg.Connection, ids: dict[str, UUID]) -> None:
    for filing_id, fec_id, coverage_end, receipt_date in (
        (ids["filing_recent_low"], "FILING-RECENT-LOW", date(2026, 6, 30), date(2026, 7, 20)),
        (ids["filing_recent_high"], "FILING-RECENT-HIGH", date(2026, 6, 30), date(2026, 7, 20)),
        (ids["filing_zero"], "FILING-ZERO", None, None),
    ):
        insert_filing_row(
            db_conn,
            FilingRowSeed(
                id=filing_id,
                filing_fec_id=fec_id,
                committee_id=ids["requested_committee"],
                report_type="Q2",
                amendment_indicator="N",
                filing_name=fec_id,
                coverage_start_date=None if coverage_end is None else date(2026, 4, 1),
                coverage_end_date=coverage_end,
                receipt_date=receipt_date,
            ),
        )
    _insert_committee_summary_filing_breakdown_transactions(db_conn, ids)


def _insert_committee_summary_filing_breakdown_transactions(db_conn: psycopg.Connection, ids: dict[str, UUID]) -> None:
    for sequence, filing_key, transaction_type, amount, source_key, is_memo, amendment_indicator in (
        (410, "filing_older", "15", "40.00", None, False, "A"),
        (411, "filing_older", "24A", "10.00", None, False, "A"),
        (412, "filing_recent_low", "15", "100.00", None, False, "N"),
        (413, "filing_recent_low", "24A", "30.00", None, False, "N"),
        (414, "filing_recent_high", "15", "50.00", None, False, "N"),
        (415, "filing_recent_high", "15", "999.00", None, True, "N"),
        (416, "filing_recent_high", "15", "888.00", None, False, "T"),
        (417, "filing_recent_high", "15", "777.00", "superseded_source", False, "N"),
    ):
        insert_transaction_row(
            db_conn,
            _summary_top_list_transaction(
                sequence,
                filing_id=ids[filing_key],
                committee_id=ids["requested_committee"],
                transaction_type=transaction_type,
                amount=amount,
                contributor_name_raw="Filing Donor",
                memo_text=None,
                source_record_id=None if source_key is None else ids[source_key],
                is_memo=is_memo,
                amendment_indicator=amendment_indicator,
            ),
        )


def _expected_committee_summary_filing_breakdown(ids: dict[str, UUID]) -> list[dict[str, object]]:
    return [
        {
            "filing_id": str(ids["filing_recent_low"]),
            "filing_fec_id": "FILING-RECENT-LOW",
            "filing_name": "FILING-RECENT-LOW",
            "report_type": "Q2",
            "amendment_indicator": "N",
            "coverage_start_date": "2026-04-01",
            "coverage_end_date": "2026-06-30",
            "receipt_date": "2026-07-20",
            "total_raised": "100.00",
            "total_spent": "30.00",
            "net": "70.00",
            "transaction_count": 2,
            "cash_on_hand": "100.00",
            "row_id": f"{ids['filing_recent_low']}:N",
        },
        {
            "filing_id": str(ids["filing_recent_high"]),
            "filing_fec_id": "FILING-RECENT-HIGH",
            "filing_name": "FILING-RECENT-HIGH",
            "report_type": "Q2",
            "amendment_indicator": "N",
            "coverage_start_date": "2026-04-01",
            "coverage_end_date": "2026-06-30",
            "receipt_date": "2026-07-20",
            "total_raised": "50.00",
            "total_spent": "0.00",
            "net": "50.00",
            "transaction_count": 1,
            "cash_on_hand": "150.00",
            "row_id": f"{ids['filing_recent_high']}:N",
        },
        {
            "filing_id": str(ids["filing_older"]),
            "filing_fec_id": "FC90000401",
            "filing_name": "Older Filing",
            "report_type": "Q1",
            "amendment_indicator": "A",
            "coverage_start_date": "2026-01-01",
            "coverage_end_date": "2026-03-31",
            "receipt_date": "2026-04-15",
            "total_raised": "40.00",
            "total_spent": "10.00",
            "net": "30.00",
            "transaction_count": 2,
            "cash_on_hand": "30.00",
            "row_id": f"{ids['filing_older']}:A",
        },
        {
            "filing_id": str(ids["filing_zero"]),
            "filing_fec_id": "FILING-ZERO",
            "filing_name": "FILING-ZERO",
            "report_type": "Q2",
            "amendment_indicator": "N",
            "coverage_start_date": None,
            "coverage_end_date": None,
            "receipt_date": None,
            "total_raised": "0.00",
            "total_spent": "0.00",
            "net": "0.00",
            "transaction_count": 0,
            "cash_on_hand": "150.00",
            "row_id": f"{ids['filing_zero']}:N",
        },
    ]


@pytest.mark.integration
class TestCommitteeSummaryDerivedTopLists:
    def test_committee_summary_derived_top_lists_store_exact_ranked_payloads(
        self,
        db_conn: psycopg.Connection,
    ) -> None:
        committee_id = _refresh_test_uuid(1)
        filing_id = _refresh_test_uuid(2)
        data_source = insert_data_source_for_test(
            db_conn,
            jurisdiction="federal/fec",
            name_suffix="committee-summary-top-lists",
        )
        active_source_id = _refresh_test_uuid(3)
        replacement_source_id = _refresh_test_uuid(4)
        superseded_source_id = _refresh_test_uuid(5)
        pull_date = datetime(2026, 7, 1, tzinfo=timezone.utc)
        insert_source_record_for_test(
            db_conn,
            source_record_id=active_source_id,
            data_source_id=data_source.id,
            source_record_key="active-top-list",
            source_url="https://example.org/source/active-top-list",
            pull_date=pull_date,
        )
        insert_source_record_for_test(
            db_conn,
            source_record_id=replacement_source_id,
            data_source_id=data_source.id,
            source_record_key="replacement-top-list",
            source_url="https://example.org/source/replacement-top-list",
            pull_date=pull_date,
        )
        insert_source_record_for_test(
            db_conn,
            source_record_id=superseded_source_id,
            data_source_id=data_source.id,
            source_record_key="superseded-top-list",
            source_url="https://example.org/source/superseded-top-list",
            pull_date=pull_date,
            superseded_by=replacement_source_id,
        )
        _seed_committee_summary_top_list_committee(
            db_conn,
            committee_id=committee_id,
            fec_committee_id="C90000001",
            filing_id=filing_id,
        )
        _seed_ranked_receipt_transactions(
            db_conn,
            filing_id=filing_id,
            committee_id=committee_id,
            active_source_id=active_source_id,
        )
        _seed_ranked_disbursement_transactions(
            db_conn,
            filing_id=filing_id,
            committee_id=committee_id,
        )
        _seed_excluded_summary_transactions(
            db_conn,
            filing_id=filing_id,
            committee_id=committee_id,
            superseded_source_id=superseded_source_id,
        )

        rowcount = job_builders.populate_committee_summary_derived_aggregates(db_conn, cycles=(2026,))

        summary = _committee_summary_values(db_conn, committee_id)
        assert rowcount == 1
        assert summary["derived_total_raised"] == Decimal("2210.00")
        assert summary["derived_total_spent"] == Decimal("1360.00")
        assert summary["derived_net"] == Decimal("850.00")
        assert summary["derived_transaction_count"] == 22
        assert summary["derived_loan_receipts_total"] == Decimal("70.00")
        assert summary["derived_in_kind_receipts_total"] == Decimal("80.00")
        assert summary["derived_contribution_receipts_total"] == Decimal("2140.00")
        assert summary["derived_cash_receipts_total"] == Decimal("2060.00")
        assert summary["derived_top_donors"] == [
            {"name": "Alpha Donor", "total_amount": "400.00", "transaction_count": 2},
            {"name": "Beta Donor", "total_amount": "400.00", "transaction_count": 1},
            {"name": "Abel Donor", "total_amount": "300.00", "transaction_count": 1},
            {"name": "Zed Donor", "total_amount": "300.00", "transaction_count": 1},
            {"name": "Gamma Donor", "total_amount": "250.00", "transaction_count": 1},
        ]
        assert summary["derived_top_vendors"] == [
            {"name": "Acme LLC", "total_amount": "300.00", "transaction_count": 2},
            {"name": "Beta Vendor", "total_amount": "300.00", "transaction_count": 1},
            {"name": "Alpha Vendor", "total_amount": "200.00", "transaction_count": 1},
            {"name": "Zeta Vendor", "total_amount": "200.00", "transaction_count": 1},
            {"name": "Gamma Vendor", "total_amount": "150.00", "transaction_count": 1},
        ]
        assert summary["derived_spend_categories"] == [
            {"category": "digital ads", "total_amount": "300.00", "transaction_count": 2},
            {"category": "mail", "total_amount": "300.00", "transaction_count": 1},
            {"category": "events", "total_amount": "200.00", "transaction_count": 1},
            {"category": "travel", "total_amount": "200.00", "transaction_count": 1},
            {"category": "printing", "total_amount": "150.00", "transaction_count": 1},
        ]

    def test_committee_summary_derived_top_lists_store_empty_arrays_for_blank_groups(
        self,
        db_conn: psycopg.Connection,
    ) -> None:
        committee_id = _refresh_test_uuid(101)
        filing_id = _refresh_test_uuid(102)
        _seed_committee_summary_top_list_committee(
            db_conn,
            committee_id=committee_id,
            fec_committee_id="C90000101",
            filing_id=filing_id,
        )
        insert_transaction_row(
            db_conn,
            _summary_top_list_transaction(
                103,
                filing_id=filing_id,
                committee_id=committee_id,
                transaction_type="11",
                amount="10.00",
                contributor_name_raw=" ",
                memo_text=None,
            ),
        )
        insert_transaction_row(
            db_conn,
            _summary_top_list_transaction(
                104,
                filing_id=filing_id,
                committee_id=committee_id,
                transaction_type="21",
                amount="5.00",
                contributor_name_raw=None,
                memo_text=" ",
            ),
        )

        rowcount = job_builders.populate_committee_summary_derived_aggregates(db_conn, cycles=(2026,))

        summary = _committee_summary_values(db_conn, committee_id)
        assert rowcount == 1
        assert summary["derived_total_raised"] == Decimal("10.00")
        assert summary["derived_total_spent"] == Decimal("5.00")
        assert summary["derived_transaction_count"] == 2
        assert summary["derived_top_donors"] == []
        assert summary["derived_top_vendors"] == []
        assert summary["derived_spend_categories"] == []

    def test_committee_summary_derived_scoping_updates_only_requested_committees(
        self,
        db_conn: psycopg.Connection,
    ) -> None:
        requested_committee_id = _refresh_test_uuid(201)
        sentinel_committee_id = _refresh_test_uuid(202)
        requested_filing_id = _refresh_test_uuid(203)
        sentinel_filing_id = _refresh_test_uuid(204)
        _seed_committee_summary_top_list_committee(
            db_conn,
            committee_id=requested_committee_id,
            fec_committee_id="C90000201",
            filing_id=requested_filing_id,
        )
        _seed_committee_summary_top_list_committee(
            db_conn,
            committee_id=sentinel_committee_id,
            fec_committee_id="C90000202",
            filing_id=sentinel_filing_id,
        )
        insert_transaction_row(
            db_conn,
            _summary_top_list_transaction(
                205,
                filing_id=requested_filing_id,
                committee_id=requested_committee_id,
                transaction_type="11",
                amount="25.00",
                contributor_name_raw="Requested Donor",
                memo_text=None,
            ),
        )
        _set_committee_summary_sentinels(db_conn, sentinel_committee_id)

        rowcount = job_builders.populate_committee_summary_derived_aggregates(
            db_conn,
            cycles=(2026,),
            committee_ids=(str(requested_committee_id),),
        )

        requested_summary = _committee_summary_values(db_conn, requested_committee_id)
        sentinel_summary = _committee_summary_values(db_conn, sentinel_committee_id)
        assert rowcount == 1
        assert requested_summary["derived_top_donors"] == [
            {"name": "Requested Donor", "total_amount": "25.00", "transaction_count": 1}
        ]
        assert sentinel_summary["derived_total_raised"] == Decimal("999.00")
        assert sentinel_summary["derived_top_donors"] == [{"name": "sentinel donor"}]

        rowcount = job_builders.populate_committee_summary_derived_aggregates(
            db_conn,
            cycles=(2026,),
            committee_ids=(),
        )

        assert rowcount == 0
        assert _committee_summary_values(db_conn, sentinel_committee_id)["derived_top_donors"] == [
            {"name": "sentinel donor"}
        ]

        rowcount = job_builders.populate_committee_summary_derived_aggregates(db_conn, cycles=(2026,))

        sentinel_summary = _committee_summary_values(db_conn, sentinel_committee_id)
        assert rowcount == 2
        assert sentinel_summary["derived_total_raised"] == Decimal("0.00")
        assert sentinel_summary["derived_transaction_count"] == 0
        assert sentinel_summary["derived_top_donors"] == []
        assert sentinel_summary["derived_top_vendors"] == []
        assert sentinel_summary["derived_spend_categories"] == []

    def test_committee_summary_derived_filing_breakdown_parity_and_scoping(
        self,
        db_conn: psycopg.Connection,
    ) -> None:
        ids = _seed_committee_summary_filing_breakdown_fixture(db_conn)

        rowcount = job_builders.populate_committee_summary_derived_aggregates(
            db_conn,
            cycles=(2026,),
            committee_ids=(str(ids["requested_committee"]),),
        )

        requested_summary = _committee_summary_values(db_conn, ids["requested_committee"])
        sentinel_summary = _committee_summary_values(db_conn, ids["sentinel_committee"])
        assert rowcount == 1
        assert requested_summary["derived_filing_breakdown"] == _expected_committee_summary_filing_breakdown(ids)
        assert sentinel_summary["derived_filing_breakdown"] == [{"filing_id": "sentinel"}]


@pytest.mark.integration
class TestBackfillCommitteeTopListsEntrypoint:
    def test_backfill_committee_top_lists_scopes_to_requested_committee(
        self,
        db_conn: psycopg.Connection,
    ) -> None:
        from core.refresh import backfill_committee_top_lists

        requested_committee_id = _refresh_test_uuid(301)
        sentinel_committee_id = _refresh_test_uuid(302)
        requested_filing_id = _refresh_test_uuid(303)
        sentinel_filing_id = _refresh_test_uuid(304)
        _seed_committee_summary_top_list_committee(
            db_conn,
            committee_id=requested_committee_id,
            fec_committee_id="C90000301",
            filing_id=requested_filing_id,
        )
        _seed_committee_summary_top_list_committee(
            db_conn,
            committee_id=sentinel_committee_id,
            fec_committee_id="C90000302",
            filing_id=sentinel_filing_id,
        )
        insert_transaction_row(
            db_conn,
            _summary_top_list_transaction(
                305,
                filing_id=requested_filing_id,
                committee_id=requested_committee_id,
                transaction_type="11",
                amount="31.00",
                contributor_name_raw="Backfill Donor",
                memo_text=None,
            ),
        )
        insert_transaction_row(
            db_conn,
            _summary_top_list_transaction(
                306,
                filing_id=sentinel_filing_id,
                committee_id=sentinel_committee_id,
                transaction_type="11",
                amount="72.00",
                contributor_name_raw="Unrequested Donor",
                memo_text=None,
            ),
        )
        _set_committee_summary_sentinels(db_conn, sentinel_committee_id)

        result = backfill_committee_top_lists.backfill_committee_top_lists(
            db_conn,
            cycles=(2026,),
            committee_ids=(str(requested_committee_id),),
        )

        requested_summary = _committee_summary_values(db_conn, requested_committee_id)
        sentinel_summary = _committee_summary_values(db_conn, sentinel_committee_id)
        assert result.rows_updated == 1
        assert requested_summary["derived_top_donors"] == [
            {"name": "Backfill Donor", "total_amount": "31.00", "transaction_count": 1}
        ]
        assert sentinel_summary["derived_top_donors"] == [{"name": "sentinel donor"}]
        assert sentinel_summary["derived_total_raised"] == Decimal("999.00")

    def test_backfill_committee_top_lists_limit_selects_bounded_summary_subset(
        self,
        db_conn: psycopg.Connection,
    ) -> None:
        from core.refresh import backfill_committee_top_lists

        selected_committee_id = _refresh_test_uuid(401)
        unselected_committee_id = _refresh_test_uuid(402)
        selected_filing_id = _refresh_test_uuid(403)
        unselected_filing_id = _refresh_test_uuid(404)
        _seed_committee_summary_top_list_committee(
            db_conn,
            committee_id=selected_committee_id,
            fec_committee_id="C90000401",
            filing_id=selected_filing_id,
        )
        _seed_committee_summary_top_list_committee(
            db_conn,
            committee_id=unselected_committee_id,
            fec_committee_id="C90000402",
            filing_id=unselected_filing_id,
        )
        insert_transaction_row(
            db_conn,
            _summary_top_list_transaction(
                405,
                filing_id=selected_filing_id,
                committee_id=selected_committee_id,
                transaction_type="11",
                amount="15.00",
                contributor_name_raw="Limit Donor",
                memo_text=None,
            ),
        )
        _set_committee_summary_sentinels(db_conn, unselected_committee_id)

        result = backfill_committee_top_lists.backfill_committee_top_lists(
            db_conn,
            cycles=(2026,),
            limit=1,
        )

        assert result.rows_updated == 1
        assert result.committee_ids == (str(selected_committee_id),)
        assert _committee_summary_values(db_conn, selected_committee_id)["derived_top_donors"] == [
            {"name": "Limit Donor", "total_amount": "15.00", "transaction_count": 1}
        ]
        assert _committee_summary_values(db_conn, unselected_committee_id)["derived_top_donors"] == [
            {"name": "sentinel donor"}
        ]

    def test_backfill_committee_top_lists_limit_zero_selects_empty_scope(
        self,
        db_conn: psycopg.Connection,
    ) -> None:
        from core.refresh import backfill_committee_top_lists

        committee_id = _refresh_test_uuid(411)
        filing_id = _refresh_test_uuid(412)
        _seed_committee_summary_top_list_committee(
            db_conn,
            committee_id=committee_id,
            fec_committee_id="C90000411",
            filing_id=filing_id,
        )

        result = backfill_committee_top_lists.backfill_committee_top_lists(
            db_conn,
            cycles=(2026,),
            limit=0,
        )

        assert result.rows_updated == 0
        assert result.committee_ids == ()
        assert _committee_summary_values(db_conn, committee_id)["derived_top_donors"] is None

    def test_backfill_committee_top_lists_explicit_ids_deduplicate_before_limit(
        self,
        db_conn: psycopg.Connection,
    ) -> None:
        from core.refresh import backfill_committee_top_lists

        first_committee_id = _refresh_test_uuid(421)
        second_committee_id = _refresh_test_uuid(422)
        third_committee_id = _refresh_test_uuid(423)
        first_filing_id = _refresh_test_uuid(424)
        second_filing_id = _refresh_test_uuid(425)
        third_filing_id = _refresh_test_uuid(426)
        for committee_id, fec_committee_id, filing_id, donor_name, sequence in (
            (first_committee_id, "C90000421", first_filing_id, "First Explicit", 427),
            (second_committee_id, "C90000422", second_filing_id, "Second Explicit", 428),
            (third_committee_id, "C90000423", third_filing_id, "Third Explicit", 429),
        ):
            _seed_committee_summary_top_list_committee(
                db_conn,
                committee_id=committee_id,
                fec_committee_id=fec_committee_id,
                filing_id=filing_id,
            )
            insert_transaction_row(
                db_conn,
                _summary_top_list_transaction(
                    sequence,
                    filing_id=filing_id,
                    committee_id=committee_id,
                    transaction_type="11",
                    amount="10.00",
                    contributor_name_raw=donor_name,
                    memo_text=None,
                ),
            )

        result = backfill_committee_top_lists.backfill_committee_top_lists(
            db_conn,
            cycles=(2026,),
            committee_ids=(
                str(first_committee_id),
                str(second_committee_id),
                str(first_committee_id),
                str(third_committee_id),
            ),
            limit=2,
        )

        assert result.rows_updated == 2
        assert result.committee_ids == (str(first_committee_id), str(second_committee_id))
        assert _committee_summary_values(db_conn, first_committee_id)["derived_top_donors"] == [
            {"name": "First Explicit", "total_amount": "10.00", "transaction_count": 1}
        ]
        assert _committee_summary_values(db_conn, second_committee_id)["derived_top_donors"] == [
            {"name": "Second Explicit", "total_amount": "10.00", "transaction_count": 1}
        ]
        assert _committee_summary_values(db_conn, third_committee_id)["derived_top_donors"] is None

    def test_backfill_committee_top_lists_limit_only_advances_through_incomplete_committees(
        self,
        db_conn: psycopg.Connection,
    ) -> None:
        from core.refresh import backfill_committee_top_lists

        complete_committee_id = _refresh_test_uuid(431)
        vendor_null_committee_id = _refresh_test_uuid(432)
        donors_null_committee_id = _refresh_test_uuid(433)
        spend_null_committee_id = _refresh_test_uuid(434)
        cycle_duplicate_committee_id = _refresh_test_uuid(435)
        for offset, committee_id in enumerate(
            (
                complete_committee_id,
                vendor_null_committee_id,
                donors_null_committee_id,
                spend_null_committee_id,
                cycle_duplicate_committee_id,
            ),
            start=436,
        ):
            _seed_committee_summary_top_list_committee(
                db_conn,
                committee_id=committee_id,
                fec_committee_id=f"C90000{offset}",
                filing_id=_refresh_test_uuid(offset),
            )
            insert_transaction_row(
                db_conn,
                _summary_top_list_transaction(
                    offset + 10,
                    filing_id=_refresh_test_uuid(offset),
                    committee_id=committee_id,
                    transaction_type="11",
                    amount=f"{offset}.00",
                    contributor_name_raw=f"Donor {offset}",
                    memo_text=None,
                ),
            )

        insert_committee_summary_row(
            db_conn,
            CommitteeSummaryRowSeed(
                committee_id=cycle_duplicate_committee_id,
                cycle=2024,
                coverage_start_date=date(2023, 1, 1),
                coverage_end_date=date(2024, 12, 31),
            ),
        )
        _set_committee_summary_top_lists(
            db_conn,
            complete_committee_id,
            donors_sql='[{"name": "complete"}]',
            vendors_sql='[{"name": "complete"}]',
            spend_categories_sql='[{"category": "complete"}]',
        )
        _set_committee_summary_top_lists(
            db_conn,
            vendor_null_committee_id,
            donors_sql='[{"name": "donor populated"}]',
            vendors_sql=None,
            spend_categories_sql='[{"category": "spend populated"}]',
        )
        _set_committee_summary_top_lists(
            db_conn,
            donors_null_committee_id,
            donors_sql=None,
            vendors_sql='[{"name": "vendor populated"}]',
            spend_categories_sql='[{"category": "spend populated"}]',
        )
        _set_committee_summary_top_lists(
            db_conn,
            spend_null_committee_id,
            donors_sql='[{"name": "donor populated"}]',
            vendors_sql='[{"name": "vendor populated"}]',
            spend_categories_sql=None,
        )

        first_batch = backfill_committee_top_lists.backfill_committee_top_lists(
            db_conn,
            cycles=(2024, 2026),
            limit=2,
        )
        second_batch = backfill_committee_top_lists.backfill_committee_top_lists(
            db_conn,
            cycles=(2024, 2026),
            limit=2,
        )
        exhausted = backfill_committee_top_lists.backfill_committee_top_lists(
            db_conn,
            cycles=(2024, 2026),
            limit=2,
        )

        assert first_batch.committee_ids == (str(vendor_null_committee_id), str(donors_null_committee_id))
        assert first_batch.rows_updated == 2
        assert second_batch.committee_ids == (str(spend_null_committee_id), str(cycle_duplicate_committee_id))
        assert second_batch.rows_updated == 3
        assert exhausted.committee_ids == ()
        assert exhausted.rows_updated == 0
        assert _committee_summary_values(db_conn, complete_committee_id)["derived_top_donors"] == [{"name": "complete"}]
        assert _committee_summary_values(db_conn, vendor_null_committee_id)["derived_top_donors"] == [
            {"name": "Donor 437", "total_amount": "437.00", "transaction_count": 1}
        ]
        assert _committee_summary_values(db_conn, cycle_duplicate_committee_id, cycle=2024)["derived_top_donors"] == []


@pytest.mark.unit
class TestBackfillCommitteeTopListsCLI:
    def test_main_calls_populate_only_and_prints_probe_metrics(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from core.refresh import backfill_committee_top_lists

        connection = MagicMock()
        get_connection = MagicMock(return_value=connection)
        populate = MagicMock(return_value=3)
        monotonic_values = iter((10.0, 12.5))
        monkeypatch.setattr(backfill_committee_top_lists, "get_connection", get_connection)
        monkeypatch.setattr(backfill_committee_top_lists, "populate_committee_summary_derived_aggregates", populate)
        monkeypatch.setattr(backfill_committee_top_lists.time, "perf_counter", lambda: next(monotonic_values))

        result = backfill_committee_top_lists.main(
            [
                "--cycles",
                "2024",
                "2026",
                "--committee-id",
                "00000000-0000-0000-0000-000000000301",
            ]
        )

        assert result == 0
        get_connection.assert_called_once_with()
        connection.transaction.assert_called_once_with()
        connection.close.assert_called_once_with()
        populate.assert_called_once_with(
            connection,
            cycles=(2024, 2026),
            committee_ids=("00000000-0000-0000-0000-000000000301",),
        )
        output = capsys.readouterr().out
        assert output.endswith("\n")
        assert json.loads(output) == {
            "cycles": [2024, 2026],
            "committee_ids": ["00000000-0000-0000-0000-000000000301"],
            "rows_updated": 3,
            "elapsed_seconds": 2.5,
        }

    def test_main_normalizes_deduplicates_and_limits_explicit_committee_ids(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from core.refresh import backfill_committee_top_lists

        connection = MagicMock()
        monkeypatch.setattr(backfill_committee_top_lists, "get_connection", MagicMock(return_value=connection))
        monkeypatch.setattr(
            backfill_committee_top_lists,
            "populate_committee_summary_derived_aggregates",
            MagicMock(return_value=2),
        )
        monotonic_values = iter((4.0, 5.0))
        monkeypatch.setattr(backfill_committee_top_lists.time, "perf_counter", lambda: next(monotonic_values))

        result = backfill_committee_top_lists.main(
            [
                "--cycles",
                "2026",
                "--committee-id",
                "91000000000000000000000000000001",
                "--committee-id",
                "91000000-0000-0000-0000-000000000002",
                "--committee-id",
                "91000000-0000-0000-0000-000000000001",
                "--limit",
                "1",
            ]
        )

        assert result == 0
        backfill_committee_top_lists.populate_committee_summary_derived_aggregates.assert_called_once_with(
            connection,
            cycles=(2026,),
            committee_ids=("91000000-0000-0000-0000-000000000001",),
        )
        assert json.loads(capsys.readouterr().out) == {
            "cycles": [2026],
            "committee_ids": ["91000000-0000-0000-0000-000000000001"],
            "rows_updated": 2,
            "elapsed_seconds": 1.0,
        }

    @pytest.mark.parametrize(
        "argv",
        (
            [],
            ["--cycles", "2026", "--limit", "-1"],
            ["--cycles", "2026", "--committee-id", "not-a-uuid"],
        ),
    )
    def test_main_rejects_invalid_arguments_before_opening_connection(
        self,
        monkeypatch: pytest.MonkeyPatch,
        argv: list[str],
    ) -> None:
        from core.refresh import backfill_committee_top_lists

        get_connection = MagicMock()
        monkeypatch.setattr(backfill_committee_top_lists, "get_connection", get_connection)

        with pytest.raises(SystemExit):
            backfill_committee_top_lists.main(argv)

        get_connection.assert_not_called()

    def test_main_closes_connection_when_populate_fails(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from core.refresh import backfill_committee_top_lists

        connection = MagicMock()
        populate_error = RuntimeError("populate failed")
        monkeypatch.setattr(backfill_committee_top_lists, "get_connection", MagicMock(return_value=connection))
        monkeypatch.setattr(
            backfill_committee_top_lists,
            "populate_committee_summary_derived_aggregates",
            MagicMock(side_effect=populate_error),
        )
        monotonic_values = iter((1.0,))
        monkeypatch.setattr(backfill_committee_top_lists.time, "perf_counter", lambda: next(monotonic_values))

        with pytest.raises(RuntimeError, match="populate failed"):
            backfill_committee_top_lists.main(["--cycles", "2026"])

        connection.transaction.assert_called_once_with()
        connection.close.assert_called_once_with()

    def test_main_reports_null_committee_ids_for_all_scope(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from core.refresh import backfill_committee_top_lists

        connection = MagicMock()
        monkeypatch.setattr(backfill_committee_top_lists, "get_connection", MagicMock(return_value=connection))
        monkeypatch.setattr(
            backfill_committee_top_lists,
            "populate_committee_summary_derived_aggregates",
            MagicMock(return_value=7),
        )
        monotonic_values = iter((20.0, 23.25))
        monkeypatch.setattr(backfill_committee_top_lists.time, "perf_counter", lambda: next(monotonic_values))

        assert backfill_committee_top_lists.main(["--cycles", "2026"]) == 0

        backfill_committee_top_lists.populate_committee_summary_derived_aggregates.assert_called_once_with(
            connection,
            cycles=(2026,),
            committee_ids=None,
        )
        assert json.loads(capsys.readouterr().out) == {
            "cycles": [2026],
            "committee_ids": None,
            "rows_updated": 7,
            "elapsed_seconds": 3.25,
        }


@pytest.mark.unit
class TestFECCommitteeSummaryJobContract:
    def _find_committee_summary_job(self, *, fec_cycle: int = 2024) -> RefreshJob:
        jobs = build_refresh_plan(
            parameters=RunnerParameters(fec_cycle=fec_cycle),
            job_key_prefixes=("federal-fec-committee-summary",),
        )
        assert len(jobs) == 1
        return jobs[0]

    def test_committee_summary_job_metadata_has_dedicated_weekly_history_key(self) -> None:
        job = self._find_committee_summary_job()

        assert job.key == "federal-fec-committee-summary"
        assert job.domain == "campaign_finance"
        assert job.jurisdiction == "federal/fec"
        assert job.cadence == "weekly"
        assert job.data_source_names == (job_builders.FEC_BULK_DATA_SOURCE_NAME,)
        assert job.refresh_history_key == "federal-fec-committee-summary"

    def test_fec_cycle_2026_resolves_active_committee_summary_cycles_oldest_first(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        downloaded_cycles = self._run_committee_summary_job_and_capture_cycles(monkeypatch, fec_cycle=2026)

        assert downloaded_cycles == (2022, 2024, 2026)

    def test_fec_cycle_2024_resolves_only_current_active_committee_summary_cycle(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        downloaded_cycles = self._run_committee_summary_job_and_capture_cycles(monkeypatch, fec_cycle=2024)

        assert downloaded_cycles == (2024,)

    def test_committee_summary_job_schedules_recent_history_2022_cycle_by_default(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        downloaded_cycles = self._run_committee_summary_job_and_capture_cycles(monkeypatch, fec_cycle=2026)

        assert 2022 in downloaded_cycles

    def test_committee_summary_run_callable_downloads_and_dispatches_each_active_cycle(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        connection = MagicMock()
        data_source_id = UUID("6f93a177-c7ca-4a16-88e6-932245a1ddaf")
        load_results = [object(), object(), object()]
        aggregate_result = 12
        urlretrieve = MagicMock()
        ensure_fec_bulk_data_source = MagicMock(return_value=data_source_id)
        dispatch_load = MagicMock(side_effect=load_results)
        get_connection = MagicMock(return_value=connection)
        populate_derived_aggregates = MagicMock(return_value=aggregate_result)

        monkeypatch.setattr(job_builders, "urlretrieve", urlretrieve)
        monkeypatch.setattr(job_builders, "get_connection", get_connection)
        monkeypatch.setattr(job_builders, "ensure_fec_bulk_data_source", ensure_fec_bulk_data_source)
        monkeypatch.setattr(job_builders, "dispatch_load", dispatch_load)
        monkeypatch.setattr(
            job_builders,
            "populate_committee_summary_derived_aggregates",
            populate_derived_aggregates,
        )

        job = self._find_committee_summary_job(fec_cycle=2026)
        result = job.run_callable()

        assert result == [*load_results, aggregate_result]
        assert [call.args[0] for call in urlretrieve.call_args_list] == [
            job_builders.fec_committee_summary_url(2022),
            job_builders.fec_committee_summary_url(2024),
            job_builders.fec_committee_summary_url(2026),
        ]
        downloaded_paths = [Path(call.args[1]) for call in urlretrieve.call_args_list]
        assert [path.name for path in downloaded_paths] == [
            "committee_summary_2022.csv",
            "committee_summary_2024.csv",
            "committee_summary_2026.csv",
        ]

        get_connection.assert_called_once_with()
        connection.transaction.assert_called_once_with()
        ensure_fec_bulk_data_source.assert_called_once_with(connection)
        connection.close.assert_called_once_with()

        assert dispatch_load.call_count == 3
        assert [call.kwargs["conn"] for call in dispatch_load.call_args_list] == [connection, connection, connection]
        assert [call.kwargs["data_source_id"] for call in dispatch_load.call_args_list] == [
            data_source_id,
            data_source_id,
            data_source_id,
        ]

        for cycle, path, call in zip((2022, 2024, 2026), downloaded_paths, dispatch_load.call_args_list):
            assert call.kwargs["config"] == job_builders.CliConfig(
                mode="single",
                cycle=cycle,
                file_type="committee_summary",
                path=path,
                directory=None,
                batch_size=1000,
                limit=None,
                graph_enabled=False,
                with_transactions=False,
            )
            assert call.kwargs["request"] == job_builders.LoadRequest(
                file_type="committee_summary",
                path=path,
            )

        populate_derived_aggregates.assert_called_once_with(connection, cycles=(2022, 2024, 2026))

    def _run_committee_summary_job_and_capture_cycles(
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        fec_cycle: int,
    ) -> tuple[int, ...]:
        monkeypatch.setattr(job_builders, "urlretrieve", MagicMock())
        monkeypatch.setattr(job_builders, "get_connection", MagicMock(return_value=MagicMock()))
        monkeypatch.setattr(job_builders, "ensure_fec_bulk_data_source", MagicMock(return_value=UUID(int=0)))
        monkeypatch.setattr(job_builders, "dispatch_load", MagicMock())

        self._find_committee_summary_job(fec_cycle=fec_cycle).run_callable()

        return tuple(call.kwargs["config"].cycle for call in job_builders.dispatch_load.call_args_list)


@pytest.mark.unit
class TestFECScheduleAJobContract:
    def _find_schedule_a_job(self, *, fec_cycle: int = 2024, fec_limit: int = 100) -> RefreshJob:
        jobs = build_refresh_plan(
            parameters=RunnerParameters(fec_cycle=fec_cycle, fec_limit=fec_limit),
            job_key_prefixes=("federal-fec-schedule-a",),
        )
        assert len(jobs) == 1
        return jobs[0]

    def test_schedule_a_run_callable_dispatches_each_active_fec_cycle_oldest_first(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        connection = MagicMock()
        data_source_id = UUID("7d9153fd-a974-4984-963d-64d811892e24")
        load_results = [object(), object()]
        archive_paths = {
            2024: Path("/tmp/itcont_2024.zip"),
            2026: Path("/tmp/itcont_2026.zip"),
        }
        download_fec_bulk_file_to_cache = MagicMock(
            side_effect=lambda _repo_root, *, cycle, **_kwargs: archive_paths[cycle]
        )
        ensure_fec_bulk_data_source = MagicMock(return_value=data_source_id)
        dispatch_load = MagicMock(side_effect=load_results)
        get_connection = MagicMock(return_value=connection)

        monkeypatch.setattr(job_builders, "download_fec_bulk_file_to_cache", download_fec_bulk_file_to_cache)
        monkeypatch.setattr(job_builders, "get_connection", get_connection)
        monkeypatch.setattr(job_builders, "ensure_fec_bulk_data_source", ensure_fec_bulk_data_source)
        monkeypatch.setattr(job_builders, "dispatch_load", dispatch_load)

        result = self._find_schedule_a_job(fec_cycle=2026, fec_limit=50).run_callable()

        assert result == load_results
        assert [call.kwargs["cycle"] for call in download_fec_bulk_file_to_cache.call_args_list] == [2024, 2026]
        assert [call.kwargs["file_type"] for call in download_fec_bulk_file_to_cache.call_args_list] == [
            "itcont",
            "itcont",
        ]
        assert [call.kwargs["downloader"] for call in download_fec_bulk_file_to_cache.call_args_list] == [
            job_builders.urlretrieve,
            job_builders.urlretrieve,
        ]

        get_connection.assert_called_once_with()
        connection.transaction.assert_called_once_with()
        ensure_fec_bulk_data_source.assert_called_once_with(connection)
        connection.close.assert_called_once_with()

        assert dispatch_load.call_count == 2
        assert [call.kwargs["conn"] for call in dispatch_load.call_args_list] == [connection, connection]
        assert [call.kwargs["data_source_id"] for call in dispatch_load.call_args_list] == [
            data_source_id,
            data_source_id,
        ]

        for cycle, call in zip((2024, 2026), dispatch_load.call_args_list):
            archive_path = archive_paths[cycle]
            assert call.kwargs["config"] == job_builders.CliConfig(
                mode="single",
                cycle=cycle,
                file_type="itcont",
                path=archive_path,
                directory=None,
                batch_size=1000,
                limit=50,
                graph_enabled=False,
                with_transactions=False,
                transactions_only=True,
                spine_only=True,
                min_date=job_builders.date(2022, 1, 1),
            )
            assert call.kwargs["request"] == job_builders.LoadRequest(file_type="itcont", path=archive_path)


@pytest.mark.unit
class TestNCIEDocumentIndexJobContract:
    def test_plan_contains_nc_ie_document_index_job_with_correct_metadata(self) -> None:
        jobs = build_refresh_plan(
            parameters=RunnerParameters(
                nc_ie_document_index_path=Path("/tmp/nc-ie-document-index.csv"),
            ),
            job_key_prefixes=("state-nc-ie-document-index",),
        )

        assert len(jobs) == 1
        job = jobs[0]
        assert job.key == "state-nc-ie-document-index"
        assert job.domain == "campaign_finance"
        assert job.jurisdiction == "state/NC"
        assert "North Carolina SBoE IE Document Index" in job.data_source_names

    def test_nc_ie_job_run_callable_is_zero_arg_callable(self) -> None:
        jobs = build_refresh_plan(
            parameters=RunnerParameters(
                nc_ie_document_index_path=Path("/tmp/nc-ie-document-index.csv"),
            ),
            job_key_prefixes=("state-nc-ie-document-index",),
        )
        job = jobs[0]
        assert callable(job.run_callable)
        signature = inspect.signature(job.run_callable)
        required_params = [
            parameter
            for parameter in signature.parameters.values()
            if parameter.default is inspect.Parameter.empty
            and parameter.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
        ]
        assert required_params == []


@pytest.mark.unit
class TestNCCommitteeDiscoveryJobContract:
    def test_plan_contains_nc_committee_discovery_job_with_config_owned_metadata(self) -> None:
        config = load_jurisdiction_config(_NC_CONFIG_PATH)
        source_config = next(
            source for source in config.data_sources if source.name == NC_COMMITTEE_DOCUMENT_SOURCE_NAME
        )
        jobs = build_refresh_plan(job_key_prefixes=("state-nc-committee-discovery",))

        assert len(jobs) == 1
        job = jobs[0]
        assert job.key == "state-nc-committee-discovery"
        assert job.domain == "campaign_finance"
        assert job.jurisdiction == "state/NC"
        assert job.data_source_names == (source_config.name,)
        assert job.cadence == source_config.update_frequency


@pytest.mark.unit
class TestNCIEDetailTransactionJobContract:
    def test_plan_contains_nc_ie_transaction_job_with_correct_metadata(self) -> None:
        jobs = build_refresh_plan(
            parameters=RunnerParameters(
                nc_ie_document_index_path=Path("/tmp/nc-ie-document-index.csv"),
            ),
            job_key_prefixes=("state-nc-ie-transactions",),
        )

        assert len(jobs) == 1
        job = jobs[0]
        assert job.key == "state-nc-ie-transactions"
        assert job.domain == "campaign_finance"
        assert job.jurisdiction == "state/NC"
        assert "North Carolina SBoE IE Document Index" in job.data_source_names

    def test_nc_ie_transaction_job_run_callable_is_zero_arg_callable(self) -> None:
        jobs = build_refresh_plan(
            parameters=RunnerParameters(
                nc_ie_document_index_path=Path("/tmp/nc-ie-document-index.csv"),
            ),
            job_key_prefixes=("state-nc-ie-transactions",),
        )

        assert len(jobs) == 1
        job = jobs[0]
        assert callable(job.run_callable)
        signature = inspect.signature(job.run_callable)
        required_params = [
            parameter
            for parameter in signature.parameters.values()
            if parameter.default is inspect.Parameter.empty
            and parameter.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
        ]
        assert required_params == []

    def test_nc_ie_transaction_job_run_callable_uses_run_nc_refresh_ie_transactions(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        run_nc_refresh = MagicMock()
        monkeypatch.setattr(job_builders, "run_nc_refresh", run_nc_refresh)

        jobs = build_refresh_plan(
            parameters=RunnerParameters(
                nc_ie_document_index_path=Path("/tmp/nc-ie-document-index.csv"),
            ),
            job_key_prefixes=("state-nc-ie-transactions",),
        )
        assert len(jobs) == 1

        jobs[0].run_callable()

        run_nc_refresh.assert_called_once_with(data_type="ie-transactions")

    def test_plan_does_not_emit_nc_ie_transactions_job_without_ie_document_index_path(self) -> None:
        with pytest.raises(ValueError, match="No refresh jobs matched"):
            build_refresh_plan(job_key_prefixes=("state-nc-ie-transactions",))


@pytest.mark.unit
class TestPHLCityJobContract:
    """Contract: build_refresh_plan() must produce city-phl-contributions and
    city-phl-expenditures jobs (PHL has two distinct Carto SQL tables)."""

    def test_plan_contains_phl_contributions_job_with_correct_metadata(self) -> None:
        jobs = build_refresh_plan(job_key_prefixes=("city-phl-contributions",))
        assert len(jobs) == 1
        job = jobs[0]
        assert job.key == "city-phl-contributions"
        assert job.domain == "campaign_finance"
        assert job.jurisdiction == "municipality/PHL"
        assert "PHL Campaign Finance Contributions" in job.data_source_names

    def test_plan_contains_phl_expenditures_job_with_correct_metadata(self) -> None:
        jobs = build_refresh_plan(job_key_prefixes=("city-phl-expenditures",))
        assert len(jobs) == 1
        job = jobs[0]
        assert job.key == "city-phl-expenditures"
        assert job.domain == "campaign_finance"
        assert job.jurisdiction == "municipality/PHL"
        assert "PHL Campaign Finance Expenditures" in job.data_source_names

    def test_phl_jobs_run_callables_are_zero_arg(self) -> None:
        for prefix in ("city-phl-contributions", "city-phl-expenditures"):
            jobs = build_refresh_plan(job_key_prefixes=(prefix,))
            assert len(jobs) == 1, f"missing job for prefix {prefix!r}"
            job = jobs[0]
            assert callable(job.run_callable)
            sig = inspect.signature(job.run_callable)
            required = [
                p
                for p in sig.parameters.values()
                if p.default is inspect.Parameter.empty
                and p.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
            ]
            assert required == [], (
                f"{prefix} run_callable must be zero-arg; required params: {[p.name for p in required]}"
            )


@pytest.mark.unit
class TestNCCivicCandidateListingJobContract:
    def test_plan_contains_civic_candidate_listing_job_with_correct_metadata(self) -> None:
        jobs = build_refresh_plan(job_key_prefixes=("civic-nc-candidate-listing",))

        assert len(jobs) == 1
        job = jobs[0]
        assert job.key == "civic-nc-candidate-listing"
        assert job.domain == "civics"
        assert job.jurisdiction == "state/NC"
        assert job.data_source_names == (_NCSBE_DATA_SOURCE_NAME,)

    def test_civic_candidate_listing_job_run_callable_is_zero_arg_callable(self) -> None:
        jobs = build_refresh_plan(job_key_prefixes=("civic-nc-candidate-listing",))
        job = jobs[0]

        assert callable(job.run_callable)
        signature = inspect.signature(job.run_callable)
        required_params = [
            parameter
            for parameter in signature.parameters.values()
            if parameter.default is inspect.Parameter.empty
            and parameter.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
        ]
        assert required_params == []

    def test_civic_candidate_listing_job_run_callable_threads_year_and_optional_path(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        load_candidate_listing_from_source = MagicMock()
        monkeypatch.setattr(
            job_builders,
            "load_candidate_listing_from_source",
            load_candidate_listing_from_source,
        )
        candidate_listing_path = Path("/tmp/nc-candidate-listing-fixture.csv")

        jobs = build_refresh_plan(
            parameters=RunnerParameters(
                year_from=2024,
                candidate_listing_path=candidate_listing_path,
            ),
            job_key_prefixes=("civic-nc-candidate-listing",),
        )
        assert len(jobs) == 1

        jobs[0].run_callable()

        load_candidate_listing_from_source.assert_called_once_with(
            year_from=2024,
            candidate_listing_path=candidate_listing_path,
        )

    @pytest.mark.parametrize(
        ("now", "expected_cadence"),
        [
            (datetime(2025, 12, 18, 12, 0, tzinfo=timezone.utc), "daily"),
            (datetime(2026, 4, 30, 12, 0, tzinfo=timezone.utc), "quarterly"),
        ],
    )
    def test_civic_candidate_listing_job_cadence_tracks_nc_filing_window(
        self,
        now: datetime,
        expected_cadence: str,
    ) -> None:
        jobs = build_refresh_plan(
            now=now,
            job_key_prefixes=("civic-nc-candidate-listing",),
        )
        assert len(jobs) == 1
        assert jobs[0].cadence == expected_cadence

    @pytest.mark.parametrize(
        ("now", "expected_cadence"),
        [
            (datetime(2025, 12, 18, 12, 0, tzinfo=timezone.utc), "daily"),
            (datetime(2026, 4, 30, 12, 0, tzinfo=timezone.utc), "quarterly"),
        ],
    )
    def test_priority_scope_includes_civic_candidate_listing_with_calendar_cadence(
        self,
        now: datetime,
        expected_cadence: str,
    ) -> None:
        jobs = build_refresh_plan(
            scope="priority",
            now=now,
            job_key_prefixes=("civic-nc-candidate-listing",),
        )
        assert len(jobs) == 1
        assert jobs[0].key == "civic-nc-candidate-listing"
        assert jobs[0].cadence == expected_cadence

    def test_civic_candidate_listing_job_resolves_cadence_using_explicit_calendar_year(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        resolve_candidate_listing_refresh_cadence = MagicMock(return_value="daily")
        monkeypatch.setattr(
            job_builders,
            "resolve_candidate_listing_refresh_cadence",
            resolve_candidate_listing_refresh_cadence,
        )

        now = datetime(2026, 4, 30, 12, 0, tzinfo=timezone.utc)
        build_refresh_plan(
            now=now,
            job_key_prefixes=("civic-nc-candidate-listing",),
        )

        resolve_candidate_listing_refresh_cadence.assert_called_once_with(
            year=2026,
            on_date=now.date(),
        )

    def test_civic_candidate_listing_job_december_run_does_not_require_missing_next_year_calendar(
        self,
    ) -> None:
        jobs = build_refresh_plan(
            now=datetime(2026, 12, 20, 12, 0, tzinfo=timezone.utc),
            job_key_prefixes=("civic-nc-candidate-listing",),
        )

        assert len(jobs) == 1
        assert jobs[0].key == "civic-nc-candidate-listing"
        assert jobs[0].cadence == "quarterly"

    def test_civic_candidate_listing_job_pre_december_uses_upcoming_election_calendar(
        self,
    ) -> None:
        """Pre-December runs in the year before an election must bind cadence
        to the upcoming election year's calendar — not the wall-clock year
        that has no calendar file on disk."""
        jobs = build_refresh_plan(
            now=datetime(2025, 11, 30, 12, 0, tzinfo=timezone.utc),
            job_key_prefixes=("civic-nc-candidate-listing",),
        )

        assert len(jobs) == 1
        assert jobs[0].key == "civic-nc-candidate-listing"
        # Nov 30 2025 falls outside the 2026 calendar's filing window
        # (candidate_filing_open=2025-12-01), so cadence is quarterly.
        assert jobs[0].cadence == "quarterly"

    def test_civic_candidate_listing_job_pre_december_resolves_cadence_using_upcoming_election_year(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        resolve_candidate_listing_refresh_cadence = MagicMock(return_value="quarterly")
        monkeypatch.setattr(
            job_builders,
            "resolve_candidate_listing_refresh_cadence",
            resolve_candidate_listing_refresh_cadence,
        )

        now = datetime(2025, 11, 30, 12, 0, tzinfo=timezone.utc)
        build_refresh_plan(
            now=now,
            job_key_prefixes=("civic-nc-candidate-listing",),
        )

        resolve_candidate_listing_refresh_cadence.assert_called_once_with(
            year=2026,
            on_date=now.date(),
        )


@pytest.mark.unit
class TestNCPastResultsJobContract:
    _EXPECTED_NC_PAST_RESULTS_SOURCE_NAMES = (
        "NCSBE ENRS nc_ncsbe_enrs_2022_11_08_general",
        "NCSBE ENRS nc_ncsbe_enrs_2024_03_05_primary",
        "NCSBE ENRS nc_ncsbe_enrs_2024_11_05_general",
    )

    def test_plan_contains_canonical_nc_past_results_job(self) -> None:
        jobs = build_refresh_plan(job_key_prefixes=("civics-nc-past-results-2022-2024",))

        assert len(jobs) == 1
        job = jobs[0]
        assert job.key == "civics-nc-past-results-2022-2024"
        assert job.domain == "civics"
        assert job.jurisdiction == "us/nc"
        assert job.data_source_names == self._EXPECTED_NC_PAST_RESULTS_SOURCE_NAMES

    def test_nc_past_results_job_run_callable_is_zero_arg(self) -> None:
        jobs = build_refresh_plan(job_key_prefixes=("civics-nc-past-results-2022-2024",))

        assert len(jobs) == 1
        signature = inspect.signature(jobs[0].run_callable)
        required_parameters = [
            parameter
            for parameter in signature.parameters.values()
            if parameter.default is inspect.Parameter.empty
            and parameter.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
        ]
        assert required_parameters == []

    def test_nc_past_results_job_filters_runtime_inputs_to_2022_and_2024_fixtures_only(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        runnable_paths = collect_ncsbe_refresh_raw_csv_paths()
        jobs = build_refresh_plan(job_key_prefixes=("civics-nc-past-results-2022-2024",))
        job = jobs[0]

        selected_fixtures = sorted(path.name for path in runnable_paths)
        assert selected_fixtures == [
            "enrs_2022_11_08_general_sample.csv",
            "enrs_2024_03_05_primary_sample.csv",
            "enrs_2024_11_05_general_sample.csv",
        ]
        assert "enrs_2020_11_03_general_sample.csv" not in selected_fixtures
        assert callable(job.run_callable)

        from domains.civics.loaders import ncsbe_results

        monkeypatch.setattr(
            ncsbe_results,
            "_refresh_sources_2022_2024",
            lambda: [
                ncsbe_results.NcsbeSourceMetadata(
                    source_id="nc_ncsbe_enrs_2024_11_05_general",
                    election_date="2024-11-05",
                    election_label="General Election",
                    fixture_file="../escaped.csv",
                    source_url="https://example.test/escaped.csv",
                )
            ],
        )

        with pytest.raises(ValueError, match="must stay within the canonical raw-extract directory"):
            ncsbe_results.collect_ncsbe_refresh_raw_csv_paths()


@pytest.mark.unit
class TestCivicRosterJobContract:
    def test_stage2_civic_roster_prefix_filter_emits_exact_job_keys(self) -> None:
        jobs = build_refresh_plan(job_key_prefixes=("civic-rosters",))

        assert tuple(sorted(job.key for job in jobs)) == tuple(sorted(_EXPECTED_STAGE2_CIVIC_ROSTER_KEYS))

    def test_campaign_finance_keys_remain_unchanged_after_civic_roster_wiring(self) -> None:
        all_jobs = build_refresh_plan()
        campaign_finance_keys = tuple(sorted(job.key for job in all_jobs if job.domain == "campaign_finance"))

        assert campaign_finance_keys == _EXPECTED_CAMPAIGN_FINANCE_KEYS

    def test_civic_roster_templates_keep_data_source_and_job_jurisdictions_aligned(self) -> None:
        for template in civic_roster_refresh_templates():
            assert template.refresh_jurisdiction is not None
            assert template.data_source_jurisdiction == template.refresh_jurisdiction


@pytest.mark.unit
class TestOfficialRosterJobContract:
    """Contract: build_refresh_plan() must emit one roster refresh job per registered source."""

    def _expected_roster_metadata_by_key(self) -> dict[str, object]:
        return {f"civics-roster-{metadata.source_id}": metadata for metadata in list_nc_roster_source_metadata()}

    def test_plan_contains_one_roster_job_for_each_registered_roster_source(self) -> None:
        expected_by_key = self._expected_roster_metadata_by_key()
        jobs = build_refresh_plan()
        roster_jobs = [job for job in jobs if job.key.startswith("civics-roster-")]

        assert len(roster_jobs) == len(expected_by_key)
        assert {job.key for job in roster_jobs} == set(expected_by_key)

    def test_key_prefix_filter_isolates_roster_jobs(self) -> None:
        expected_by_key = self._expected_roster_metadata_by_key()
        jobs = build_refresh_plan(job_key_prefixes=("civics-roster-",))

        assert len(jobs) == len(expected_by_key)
        assert all(job.key.startswith("civics-roster-") for job in jobs)
        assert {job.key for job in jobs} == set(expected_by_key)

    def test_roster_job_metadata_matches_registered_roster_source_metadata(self) -> None:
        expected_by_key = self._expected_roster_metadata_by_key()
        jobs = build_refresh_plan(job_key_prefixes=("civics-roster-",))

        for job in jobs:
            metadata = expected_by_key[job.key]
            assert job.domain == "civics"
            assert job.jurisdiction == metadata.jurisdiction
            assert job.cadence == metadata.cadence
            assert job.data_source_names == (metadata.name,)
            assert callable(job.run_callable)

            signature = inspect.signature(job.run_callable)
            required_params = [
                parameter
                for parameter in signature.parameters.values()
                if parameter.default is inspect.Parameter.empty
                and parameter.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
            ]
            assert required_params == []

    def test_roster_source_templates_include_all_registered_roster_sources(self) -> None:
        registered_source_ids = {metadata.source_id for metadata in list_nc_roster_source_metadata()}
        template_source_ids = {template.registry_source_id for template in roster_source_templates()}

        assert registered_source_ids <= template_source_ids
